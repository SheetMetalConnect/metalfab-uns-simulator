"""Multi-site UNS simulator for metalworking demonstration.

Topic Structure (ISA-95 hierarchy):
  umh/v1/{enterprise}/{site}/{department}/{machine}/

Each machine has:
  - Asset/      Static metadata (retained)
  - Dashboard/  Aggregated views (retained)
  - Edge/       Real-time sensor data (streaming)
  - Line/       Production data (retained)

Example:
  umh/v1/metalfab/eindhoven/cutting/laser_01/
    ├── Asset/
    │   ├── AssetID, InService, Model, Name, OEM
    ├── Dashboard/
    │   ├── Asset, Job, OEE
    ├── Edge/
    │   ├── LaserPower, CuttingSpeed, State
    │   └── ShopFloor/
    │       ├── JobID, WorkOrder, Customer, ...
    └── Line/
        ├── Infeed, Outfeed, State, Waste
        └── OEE/
            ├── Availability, Quality, Performance, OEE

Control Topics (root level - for demo control):
  metalfab-sim/
    ├── status          Current simulator state (retained)
    ├── control/
    │   ├── level       Set complexity level 1-4
    │   ├── site/{id}   Enable/disable site (1/0)
    │   └── clear       Clear all retained data (1)
    └── sites/
        ├── eindhoven   Site status (retained)
        ├── roeselare   Site status (retained)
        └── brasov      Site status (retained)
"""

import json
import logging
import random
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt

from .complexity import ComplexityLevel
from .config import Config
from .facilities import FACILITIES, FacilityConfig, get_cells_for_facility
from .digital_passport import (
    DigitalProductPassport,
    DPPGenerator,
    DPPEventType,
    DPPStatus,
)

logger = logging.getLogger(__name__)


# =============================================================================
# OEE Constants
# =============================================================================

IDEAL_CYCLE_RATES = {  # parts per hour (ideal, no losses)
    "laser_cutter": 30,
    "press_brake": 45,
    "robot_weld": 20,
    "manual_weld": 12,
    "assembly": 25,
    "powder_coating_line": 15,
    "quality_control": 40,
    "agv": 60,
}

SHIFT_DURATION_S = 8 * 3600  # 8-hour shift


# =============================================================================
# Machine State
# =============================================================================

class MachineState(Enum):
    """PackML-style machine states."""
    STOPPED = 0
    STARTING = 1
    IDLE = 2
    EXECUTE = 3
    COMPLETING = 4
    HELD = 5
    SUSPENDED = 6
    ABORTED = 7


# Stop reason codes — modeled after real sheet metal shop-floor classifications
STOP_REASONS = {
    # Changeovers (between jobs)
    "changeover": [
        ("ST01", "Sheet Size Changeover"),
        ("ST02", "Tool/Die Change"),
        ("ST03", "Material Change"),
        ("ST04", "NC Program Load"),
        ("ST05", "Fixture Setup"),
    ],
    # Planned stops
    "planned": [
        ("PS01", "Lunch Break"),
        ("PS02", "Shift Change"),
        ("PS03", "Planned Maintenance"),
        ("PS04", "Tooling Inspection"),
    ],
    # Breakdowns (longer HELD, slower recovery)
    "breakdown": [
        ("BD01", "Laser Source Error"),
        ("BD02", "Hydraulic Pressure Loss"),
        ("BD03", "Drive Axis Fault"),
        ("BD04", "Chiller Overtemp"),
        ("BD05", "Safety Circuit Trip"),
        ("BD06", "Gas Supply Fault"),
    ],
    # Microstops (brief HELD, fast auto-recovery)
    "microstop": [
        ("MS01", "Sheet Misposition"),
        ("MS02", "Nozzle Collision Detect"),
        ("MS03", "Part Tip-Up"),
        ("MS04", "Slug Jam"),
        ("MS05", "Backgauge Timeout"),
        ("MS06", "Wire Feed Stall"),
    ],
}


@dataclass
class Machine:
    """Represents a machine/cell with all its data."""

    machine_id: str
    name: str
    machine_type: str
    department: str
    oem: str
    model: str

    # State
    state: MachineState = MachineState.IDLE

    # Asset info
    asset_id: int = 0
    in_service: str = ""
    serial_number: str = ""

    # Edge data (raw sensors)
    edge_data: Dict[str, Any] = field(default_factory=dict)

    # Line data (production)
    infeed: int = 0
    outfeed: int = 0
    waste: int = 0
    parts_produced: int = 0
    parts_scrap: int = 0

    # Job tracking
    job_id: Optional[str] = None
    work_order: Optional[str] = None
    job_started_at: Optional[datetime] = None  # For DPP tracking
    dpp_created: bool = False  # Flag to track if DPP created for current job

    # ERP/MES enrichment
    customer: str = ""
    product_name: str = ""
    qty_target: int = 0
    qty_complete: int = 0
    due_date: str = ""
    scheduled_start: str = ""
    scheduled_end: str = ""
    operator_id: str = ""
    operator_name: str = ""
    operator_notes: str = ""
    priority: str = "NORMAL"
    material_code: str = ""
    material_thickness_mm: float = 0.0

    # OEE
    availability: float = 0.0
    quality: float = 0.0
    performance: float = 0.0
    oee: float = 0.0

    # OEE context for publishing
    downtime_minutes: float = 0.0
    idle_minutes: float = 0.0
    shift_duration_minutes: float = 0.0

    # Stop reason tracking
    stop_reason_code: str = ""       # e.g. "ST02", "BD01", "MS03"
    stop_reason_name: str = ""       # e.g. "Size Changeover"
    stop_category: str = ""          # "changeover", "planned", "breakdown", "microstop"
    stop_since: Optional[float] = None  # timestamp when stop began

    def __post_init__(self):
        self.asset_id = random.randint(1, 999)
        self.in_service = f"20{random.randint(18, 24)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
        self.serial_number = f"SN{random.randint(100000, 999999)}"
        self._init_edge_data()

        # Shift-level OEE accumulators
        self._shift_start_time: float = time.time()
        self._last_tick_time: float = time.time()
        self._time_in_execute_s: float = 0.0
        self._time_in_idle_s: float = 0.0
        self._time_in_held_s: float = 0.0
        self._shift_outfeed: int = 0
        self._shift_waste: int = 0
        self._shift_infeed: int = 0

    def _init_edge_data(self):
        """Initialize edge data based on machine type."""
        if self.machine_type == "laser_cutter":
            self.edge_data = {
                "LaserPower": 0.0,
                "CuttingSpeed": 0,
                "AssistGas": 0.0,
                "FocalPosition": 0.0,
                "SheetTemp": 20.0,
            }
        elif self.machine_type == "press_brake":
            self.edge_data = {
                "Tonnage": 0.0,
                "BendAngle": 0.0,
                "StrokePosition": 0.0,
                "BackgaugePos": 0.0,
            }
        elif self.machine_type in ("robot_weld", "manual_weld"):
            self.edge_data = {
                "WeldCurrent": 0.0,
                "WeldVoltage": 0.0,
                "WireFeed": 0.0,
                "GasFlow": 0.0,
                "ArcTime": 0,
            }
        elif self.machine_type == "powder_coating_line":
            self.edge_data = {
                "OvenTemp": 0.0,
                "BoothHumidity": 0.0,
                "ConveyorSpeed": 0.0,
                "PowderFlow": 0.0,
            }
        else:
            self.edge_data = {
                "Power": 0.0,
                "Status": 0,
            }

    def _set_stop_reason(self, category: str):
        """Assign a random stop reason from the given category."""
        reasons = STOP_REASONS.get(category, [("XX00", "Unknown")])
        code, name = random.choice(reasons)
        self.stop_reason_code = code
        self.stop_reason_name = name
        self.stop_category = category
        self.stop_since = time.time()

    def _clear_stop_reason(self):
        """Clear stop reason when returning to productive state."""
        self.stop_reason_code = ""
        self.stop_reason_name = ""
        self.stop_category = ""
        self.stop_since = None

    def tick(self):
        """Update machine state for one tick."""
        now = time.time()
        elapsed = now - self._last_tick_time
        self._last_tick_time = now

        # Accumulate time per state
        if self.state == MachineState.EXECUTE:
            self._time_in_execute_s += elapsed
        elif self.state == MachineState.IDLE:
            self._time_in_idle_s += elapsed
        elif self.state == MachineState.HELD:
            self._time_in_held_s += elapsed

        # Check for shift reset
        shift_elapsed = now - self._shift_start_time
        if shift_elapsed >= SHIFT_DURATION_S:
            self._reset_shift(now)

        # Simulate state changes with stop reason assignment
        if self.state == MachineState.IDLE:
            if random.random() < 0.1:
                self.state = MachineState.STARTING
                self._clear_stop_reason()
                self._start_new_job()
            elif not self.stop_reason_code:
                # Assign a stop reason for idle (changeover or planned)
                if random.random() < 0.7:
                    self._set_stop_reason("changeover")
                else:
                    self._set_stop_reason("planned")

        elif self.state == MachineState.STARTING:
            self.state = MachineState.EXECUTE
            self._clear_stop_reason()

        elif self.state == MachineState.EXECUTE:
            # Update counters
            if random.random() < 0.3:
                self.infeed += 1
                self._shift_infeed += 1
            if random.random() < 0.28:
                self.outfeed += 1
                self._shift_outfeed += 1
                self.parts_produced += 1
                self.qty_complete += 1
            if random.random() < 0.01:
                self.waste += 1
                self._shift_waste += 1
                self.parts_scrap += 1

            # Microstop (brief, 2% chance) — auto-recovers in 1-5 ticks
            if random.random() < 0.02:
                self.state = MachineState.HELD
                self._set_stop_reason("microstop")

            # Breakdown (longer, 0.3% chance)
            elif random.random() < 0.003:
                self.state = MachineState.HELD
                self._set_stop_reason("breakdown")

            # Job complete
            elif random.random() < 0.02:
                self.state = MachineState.COMPLETING
                self._set_stop_reason("changeover")

        elif self.state == MachineState.HELD:
            if self.stop_category == "microstop":
                # Microstops recover fast: 40% chance per tick (avg ~2.5 ticks)
                if random.random() < 0.40:
                    self.state = MachineState.EXECUTE
                    self._clear_stop_reason()
            else:
                # Breakdowns recover slower: 5% chance per tick (avg ~20 ticks)
                if random.random() < 0.05:
                    self.state = MachineState.EXECUTE
                    self._clear_stop_reason()

        elif self.state == MachineState.COMPLETING:
            self.state = MachineState.IDLE
            self._set_stop_reason("changeover")
            self._clear_job()

        # Update edge data
        self._update_edge_data()

        # Update OEE from real accumulators
        self._update_oee()

    def _update_edge_data(self):
        """Update raw sensor values."""
        if self.state == MachineState.EXECUTE:
            if self.machine_type == "laser_cutter":
                self.edge_data["LaserPower"] = random.uniform(75, 100)
                self.edge_data["CuttingSpeed"] = random.randint(2000, 4000)
                self.edge_data["AssistGas"] = random.uniform(8, 15)
                self.edge_data["SheetTemp"] = random.uniform(100, 300)
            elif self.machine_type == "press_brake":
                self.edge_data["Tonnage"] = random.uniform(50, 200)
                self.edge_data["BendAngle"] = random.uniform(30, 150)
                self.edge_data["StrokePosition"] = random.uniform(0, 100)
            elif self.machine_type in ("robot_weld", "manual_weld"):
                self.edge_data["WeldCurrent"] = random.uniform(150, 300)
                self.edge_data["WeldVoltage"] = random.uniform(20, 35)
                self.edge_data["WireFeed"] = random.uniform(5, 15)
                self.edge_data["GasFlow"] = random.uniform(12, 20)
            elif self.machine_type == "powder_coating_line":
                self.edge_data["OvenTemp"] = random.uniform(180, 200)
                self.edge_data["BoothHumidity"] = random.uniform(40, 60)
                self.edge_data["ConveyorSpeed"] = random.uniform(1.5, 3.0)
        else:
            # Idle values
            for key in self.edge_data:
                if isinstance(self.edge_data[key], float):
                    self.edge_data[key] = 0.0
                elif isinstance(self.edge_data[key], int):
                    self.edge_data[key] = 0

    def _reset_shift(self, now: float):
        """Reset shift-level OEE accumulators."""
        self._shift_start_time = now
        self._time_in_execute_s = 0.0
        self._time_in_idle_s = 0.0
        self._time_in_held_s = 0.0
        self._shift_outfeed = 0
        self._shift_waste = 0
        self._shift_infeed = 0

    def _update_oee(self):
        """Calculate OEE from real state accumulators: A × P × Q."""
        shift_elapsed = time.time() - self._shift_start_time

        # Planned production time = shift elapsed minus 0 (no planned stops in sim)
        planned_time_s = max(shift_elapsed, 1.0)

        # Availability = Run Time / Planned Production Time
        # Run time = time in EXECUTE (not IDLE, not HELD)
        run_time_s = self._time_in_execute_s
        self.availability = min(1.0, run_time_s / planned_time_s)

        # Performance = (Ideal Cycle Time × Total Count) / Run Time
        ideal_rate = IDEAL_CYCLE_RATES.get(self.machine_type, 25)  # parts/hour
        execute_hours = run_time_s / 3600.0
        if execute_hours > 0 and ideal_rate > 0:
            expected_output = ideal_rate * execute_hours
            self.performance = min(1.0, self._shift_outfeed / expected_output) if expected_output > 0 else 0.0
        else:
            self.performance = 0.0

        # Quality = Good Count / Total Count
        total_count = self._shift_outfeed + self._shift_waste
        if total_count > 0:
            self.quality = (self._shift_outfeed - self._shift_waste) / total_count
            self.quality = max(0.0, min(1.0, self.quality))
        else:
            self.quality = 1.0

        # Add small noise to prevent perfectly flat lines (±0.5%)
        noise = random.uniform(-0.005, 0.005)
        self.availability = max(0.0, min(1.0, self.availability + noise))
        self.performance = max(0.0, min(1.0, self.performance + noise))
        self.quality = max(0.0, min(1.0, self.quality + noise))

        # OEE = A × P × Q
        self.oee = self.availability * self.performance * self.quality

        # Published context fields
        self.downtime_minutes = round(self._time_in_held_s / 60, 1)
        self.idle_minutes = round(self._time_in_idle_s / 60, 1)
        self.shift_duration_minutes = round(shift_elapsed / 60, 1)

    def _start_new_job(self):
        """Start a new job with ERP/MES data."""
        self.job_id = f"JOB_{random.randint(1000, 9999)}"
        self.work_order = f"WO-2025-{random.randint(1000, 9999)}"
        self.job_started_at = datetime.now()  # Track when job started
        self.dpp_created = False  # Flag to track if DPP was created for this job

        # Customer data
        customers = [
            ("Bosch Rexroth", "Hydraulic Manifold Block"),
            ("Siemens AG", "Control Cabinet Panel"),
            ("ABB Automation", "Robot Arm Bracket"),
            ("KUKA", "Welding Fixture Base"),
            ("Phoenix Contact", "Terminal Housing"),
            ("Schneider Electric", "Enclosure Door"),
            ("Festo", "Pneumatic Mounting Plate"),
        ]
        self.customer, self.product_name = random.choice(customers)

        # Quantities
        self.qty_target = random.randint(50, 500)
        self.qty_complete = 0

        # Scheduling (simulate job due in 1-5 days)
        from datetime import timedelta
        now = datetime.now()
        self.scheduled_start = now.isoformat()
        end_offset = timedelta(hours=random.randint(2, 16))
        due_offset = timedelta(days=random.randint(1, 5))
        self.scheduled_end = (now + end_offset).isoformat()
        self.due_date = (now + due_offset).isoformat()

        # Operator
        operators = [
            ("OP_1001", "Jan van der Berg"),
            ("OP_1002", "Pieter de Vries"),
            ("OP_1003", "Maria Jansen"),
            ("OP_1004", "Marc Willems"),
            ("OP_1005", "Elena Popescu"),
            ("OP_1006", "Andrei Ionescu"),
        ]
        self.operator_id, self.operator_name = random.choice(operators)

        # Priority
        self.priority = random.choice(["LOW", "NORMAL", "NORMAL", "HIGH", "URGENT"])

        # Operator notes (occasional)
        notes = [
            "",
            "",
            "Customer requested expedite",
            "Quality check after first 10 parts",
            "Use new tooling",
            "Prototype run - document settings",
            "",
        ]
        self.operator_notes = random.choice(notes)

        # Material (codes match DPPGenerator.MATERIALS keys)
        materials = [
            ("DC01", 2.0),
            ("S235JR", 3.0),
            ("S355", 4.0),
            ("AISI304", 1.5),
            ("AISI316L", 2.0),
            ("AL5052", 2.5),
            ("AL6061", 3.0),
        ]
        self.material_code, self.material_thickness_mm = random.choice(materials)

    def _clear_job(self):
        """Clear job data when completing."""
        self.job_id = None
        self.work_order = None
        self.customer = ""
        self.product_name = ""
        self.qty_target = 0
        self.qty_complete = 0
        self.due_date = ""
        self.scheduled_start = ""
        self.scheduled_end = ""
        self.operator_id = ""
        self.operator_name = ""
        self.operator_notes = ""
        self.priority = "NORMAL"
        self.material_code = ""
        self.material_thickness_mm = 0.0


# =============================================================================
# Facility with Machines
# =============================================================================

@dataclass
class CoatingLine:
    """Powder coating line simulation."""

    line_id: str = "coating_line_01"
    current_ral: str = "RAL 9005"
    current_ral_name: str = "Jet Black"
    oven_temp_c: float = 185.0
    booth_humidity_pct: float = 45.0
    conveyor_speed_mpm: float = 2.5
    traversals_in_line: int = 12
    parts_in_line: int = 48
    last_color_change: str = ""

    # Zone counts
    zone_loading: int = 2
    zone_pretreat: int = 3
    zone_drying: int = 2
    zone_coating: int = 2
    zone_curing: int = 2
    zone_cooling: int = 1

    def tick(self):
        """Update coating line state."""
        self.oven_temp_c = random.uniform(180, 195)
        self.booth_humidity_pct = random.uniform(40, 55)
        self.conveyor_speed_mpm = random.uniform(2.0, 3.0)

        # Occasionally change colors
        if random.random() < 0.002:
            colors = [
                ("RAL 9005", "Jet Black"),
                ("RAL 9016", "Traffic White"),
                ("RAL 7035", "Light Grey"),
                ("RAL 5010", "Gentian Blue"),
                ("RAL 3000", "Flame Red"),
            ]
            self.current_ral, self.current_ral_name = random.choice(colors)
            self.last_color_change = datetime.now().isoformat()

        # Update zone counts
        self.zone_loading = random.randint(1, 3)
        self.zone_pretreat = random.randint(2, 4)
        self.zone_drying = random.randint(1, 3)
        self.zone_coating = random.randint(1, 3)
        self.zone_curing = random.randint(2, 4)
        self.zone_cooling = random.randint(1, 2)
        self.traversals_in_line = sum([
            self.zone_loading, self.zone_pretreat, self.zone_drying,
            self.zone_coating, self.zone_curing, self.zone_cooling
        ])
        self.parts_in_line = self.traversals_in_line * random.randint(3, 6)


@dataclass
class EnergyMonitor:
    """Site energy monitoring."""

    site_id: str
    solar_capacity_kwp: float = 0.0

    # Current readings
    consumption_kw: float = 0.0
    solar_generation_kw: float = 0.0
    grid_import_kw: float = 0.0

    # Daily totals
    consumption_kwh_today: float = 0.0
    solar_kwh_today: float = 0.0
    cost_today_eur: float = 0.0

    def tick(self):
        """Update energy readings."""
        hour = datetime.now().hour

        # Simulate consumption based on time of day
        if 6 <= hour <= 22:
            self.consumption_kw = random.uniform(80, 150)
        else:
            self.consumption_kw = random.uniform(20, 40)

        # Solar generation (daylight hours, peak midday)
        if 7 <= hour <= 19 and self.solar_capacity_kwp > 0:
            # Bell curve around noon
            solar_factor = max(0, 1 - abs(hour - 13) / 6)
            self.solar_generation_kw = self.solar_capacity_kwp * solar_factor * random.uniform(0.7, 0.95)
        else:
            self.solar_generation_kw = 0.0

        # Grid import = consumption - solar
        self.grid_import_kw = max(0, self.consumption_kw - self.solar_generation_kw)

        # Accumulate daily totals (simplified)
        self.consumption_kwh_today += self.consumption_kw / 3600
        self.solar_kwh_today += self.solar_generation_kw / 3600
        self.cost_today_eur = self.consumption_kwh_today * 0.15 - self.solar_kwh_today * 0.08


@dataclass
class FacilitySim:
    """Simulator for one facility with its machines."""

    facility: FacilityConfig
    machines: Dict[str, Machine] = field(default_factory=dict)
    coating_line: Optional[CoatingLine] = None
    energy: Optional[EnergyMonitor] = None

    def __post_init__(self):
        """Initialize machines from facility config."""
        cell_defs = get_cells_for_facility(self.facility.site_id)

        for area_def in cell_defs:
            department = area_def["area"]
            for cell_def in area_def["cells"]:
                machine = Machine(
                    machine_id=cell_def["id"],
                    name=cell_def.get("name", cell_def["id"]),
                    machine_type=cell_def["type"],
                    department=department,
                    oem=self._get_oem(cell_def["type"]),
                    model=self._get_model(cell_def["type"]),
                )
                self.machines[machine.machine_id] = machine

        # Initialize coating line if facility has finishing capability
        if "powder_coating" in self.facility.capabilities:
            self.coating_line = CoatingLine()
            self.coating_line.last_color_change = datetime.now().isoformat()

        # Initialize energy monitor for all facilities
        self.energy = EnergyMonitor(
            site_id=self.facility.site_id,
            solar_capacity_kwp=self.facility.solar_capacity_kwp,
        )

    def _get_oem(self, machine_type: str) -> str:
        oems = {
            "laser_cutter": "TRUMPF",
            "press_brake": "TRUMPF",
            "robot_weld": "Fronius",
            "manual_weld": "Lincoln Electric",
            "powder_coating_line": "Wagner",
            "assembly": "Custom",
            "quality_control": "Zeiss",
            "agv": "Jungheinrich",
        }
        return oems.get(machine_type, "Generic")

    def _get_model(self, machine_type: str) -> str:
        models = {
            "laser_cutter": "TruLaser 3030 fiber",
            "press_brake": "TruBend 5130",
            "robot_weld": "TPS 500i CMT",
            "manual_weld": "Power MIG 360MP",
            "powder_coating_line": "PrimaSprint",
            "assembly": "Assembly Station",
            "quality_control": "CONTURA CMM",
            "agv": "EKS 215a",
        }
        return models.get(machine_type, "Standard")

    def tick(self):
        """Advance simulation one tick."""
        for machine in self.machines.values():
            machine.tick()

        # Update coating line if present
        if self.coating_line:
            self.coating_line.tick()

        # Update energy monitor
        if self.energy:
            self.energy.tick()


# =============================================================================
# MQTT Publisher with Semantic Hierarchy
# =============================================================================

class SemanticPublisher:
    """Publishes data following the semantic UNS hierarchy."""

    def __init__(self, broker: str = "localhost", port: int = 1883):
        self.broker = broker
        self.port = port
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="metalfab-multi-site"
        )
        self.connected = False
        self._level = ComplexityLevel.LEVEL_2_STATEFUL
        self.prefix = "umh/v1/metalfab"

        # Callbacks for control messages
        self._level_callback = None
        self._site_callback = None
        self._clear_callback = None

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.connected = True
            logger.info("Connected to MQTT broker")
            # Subscribe to control topics
            client.subscribe("metalfab-sim/control/level", qos=1)
            client.subscribe("metalfab-sim/control/site/+", qos=1)
            client.subscribe("metalfab-sim/control/clear", qos=1)
            logger.info("Subscribed to metalfab-sim/control/# topics")
        else:
            logger.error(f"Connection failed: {rc}")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode().strip()
        except Exception:
            payload = ""

        # Handle level control (accepts JSON or plain integer)
        if topic == "metalfab-sim/control/level":
            try:
                # Try JSON first
                if payload.startswith("{"):
                    data = json.loads(payload)
                    level_val = data.get("level", 2)
                else:
                    level_val = int(payload)

                # Clamp to valid range
                level_val = max(0, min(4, level_val))
                new_level = ComplexityLevel(level_val)

                # Only trigger callback if level actually changed
                if new_level != self._level:
                    old = self._level
                    self._level = new_level
                    logger.info(f"Level changed: {old.name} -> {new_level.name}")
                    # Notify callback if set
                    if self._level_callback:
                        self._level_callback(new_level)
            except Exception as e:
                logger.error(f"Invalid level message: {e}")

        # Handle site enable/disable
        elif topic.startswith("metalfab-sim/control/site/"):
            site_id = topic.split("/")[-1]
            try:
                enabled = payload == "1" or payload.lower() == "true"
                # Only trigger callback if state actually changed
                if self._site_callback:
                    self._site_callback(site_id, enabled)
            except Exception as e:
                logger.error(f"Invalid site control message: {e}")

        # Handle clear retained
        elif topic == "metalfab-sim/control/clear":
            try:
                if payload == "1" or payload.lower() == "true":
                    if self._clear_callback:
                        self._clear_callback()
            except Exception as e:
                logger.error(f"Invalid clear message: {e}")

    def connect(self) -> bool:
        try:
            self.client.connect(self.broker, self.port)
            self.client.loop_start()
            time.sleep(0.5)
            return self.connected
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def set_level(self, level: ComplexityLevel):
        self._level = level

    @property
    def level(self) -> ComplexityLevel:
        return self._level

    def set_callbacks(
        self,
        level_callback=None,
        site_callback=None,
        clear_callback=None
    ):
        """Set callbacks for control messages."""
        self._level_callback = level_callback
        self._site_callback = site_callback
        self._clear_callback = clear_callback

    def clear_retained(self, topics: List[str]):
        """Clear retained messages by publishing empty payload with retain=True."""
        count = 0
        for topic in topics:
            self.client.publish(topic, "", retain=True, qos=1)
            count += 1
        logger.info(f"Cleared {count} retained topics")

    def publish(self, topic: str, value: Any, retain: bool = True):
        """Publish a value - can be simple value or dict."""
        if isinstance(value, dict):
            payload = json.dumps(value)
        elif isinstance(value, (int, float)):
            payload = json.dumps(value)
        elif isinstance(value, str):
            payload = json.dumps(value)
        else:
            payload = str(value)

        self.client.publish(topic, payload, retain=retain, qos=1)

    def publish_machine_descriptive(self, site_id: str, machine: Machine):
        """Publish Asset/ namespace - static metadata (retained, published once)."""
        base = f"{self.prefix}/{site_id}/{machine.department}/{machine.machine_id}"

        # Asset/ - individual values like in the screenshot
        self.publish(f"{base}/Asset/AssetID", machine.asset_id)
        self.publish(f"{base}/Asset/Name", machine.name)
        self.publish(f"{base}/Asset/OEM", machine.oem)
        self.publish(f"{base}/Asset/Model", machine.model)
        self.publish(f"{base}/Asset/InService", machine.in_service)
        self.publish(f"{base}/Asset/SerialNumber", machine.serial_number)
        self.publish(f"{base}/Asset/MachineType", machine.machine_type)

    @staticmethod
    def _to_raw_tag(name: str) -> str:
        """Convert CamelCase sensor name to snake_case _raw tag name."""
        import re
        s1 = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', name)
        return re.sub(r'([a-z\d])([A-Z])', r'\1_\2', s1).lower().replace(" ", "_")

    def publish_machine_functional(self, site_id: str, machine: Machine):
        """Publish Edge/ and Line/ namespaces - real-time operational data."""
        base = f"{self.prefix}/{site_id}/{machine.department}/{machine.machine_id}"

        # =====================================================================
        # Edge/ - Raw sensor data (streaming, NOT retained)
        # =====================================================================
        for sensor_name, value in machine.edge_data.items():
            val = round(value, 2) if isinstance(value, float) else value
            self.publish(f"{base}/Edge/{sensor_name}", val, retain=False)

        # Edge/State - current machine state code
        self.publish(f"{base}/Edge/State", machine.state.value, retain=False)
        self.publish(f"{base}/Edge/StateName", machine.state.name, retain=False)

        # Edge/StopReason - stop code when not producing (for OEE Pareto)
        if machine.stop_reason_code:
            self.publish(f"{base}/Edge/StopReason", {
                "code": machine.stop_reason_code,
                "name": machine.stop_reason_name,
                "category": machine.stop_category,
            }, retain=False)
        else:
            self.publish(f"{base}/Edge/StopReason", {
                "code": "",
                "name": "",
                "category": "",
            }, retain=False)

        # Edge/Infeed, Outfeed, Waste - streaming counters
        self.publish(f"{base}/Edge/Infeed", machine.infeed, retain=False)
        self.publish(f"{base}/Edge/Outfeed", machine.outfeed, retain=False)
        self.publish(f"{base}/Edge/Waste", machine.waste, retain=False)

        # =====================================================================
        # _raw — UMH Core data contract (streaming, NOT retained)
        # Publishes same sensor values as Edge/ but using the _raw data contract
        # convention so they're automatically picked up by the historian flow
        # and persisted to TimescaleDB via: _raw → historian → tag/tag_string
        # =====================================================================
        for sensor_name, value in machine.edge_data.items():
            val = round(value, 2) if isinstance(value, float) else value
            self.publish(f"{base}/_raw/{self._to_raw_tag(sensor_name)}", val, retain=False)

        self.publish(f"{base}/_raw/state", machine.state.value, retain=False)
        self.publish(f"{base}/_raw/state_name", machine.state.name, retain=False)
        self.publish(f"{base}/_raw/infeed", machine.infeed, retain=False)
        self.publish(f"{base}/_raw/outfeed", machine.outfeed, retain=False)
        self.publish(f"{base}/_raw/waste", machine.waste, retain=False)

        # Edge/ShopFloor/ - Job context (Level 2+, retained for job tracking)
        if self._level >= ComplexityLevel.LEVEL_2_STATEFUL:
            shopfloor_data = {
                "timestamp": datetime.now().isoformat() + "Z",
                "job_id": machine.job_id or "",
                "work_order": machine.work_order or "",
            }

            # ERP/MES enrichment at Level 3+
            if self._level >= ComplexityLevel.LEVEL_3_ERP_MES and machine.job_id:
                shopfloor_data.update({
                    "customer": machine.customer,
                    "product_name": machine.product_name,
                    "qty_target": machine.qty_target,
                    "qty_complete": machine.qty_complete,
                    "progress_pct": round((machine.qty_complete / machine.qty_target * 100), 1) if machine.qty_target > 0 else 0,
                    "due_date": machine.due_date,
                    "scheduled_start": machine.scheduled_start,
                    "scheduled_end": machine.scheduled_end,
                    "operator_id": machine.operator_id,
                    "operator_name": machine.operator_name,
                    "operator_notes": machine.operator_notes,
                    "priority": machine.priority,
                    "material_code": machine.material_code,
                    "material_thickness_mm": machine.material_thickness_mm,
                })

            self.publish(f"{base}/Edge/ShopFloor", shopfloor_data)

        # =====================================================================
        # Line/ - Production data (retained)
        # =====================================================================
        if self._level >= ComplexityLevel.LEVEL_2_STATEFUL:
            # Line/ counters
            self.publish(f"{base}/Line/Infeed", machine.infeed)
            self.publish(f"{base}/Line/Outfeed", machine.outfeed)
            self.publish(f"{base}/Line/Waste", machine.waste)
            self.publish(f"{base}/Line/State", machine.state.value)
            self.publish(f"{base}/Line/PartsProduced", machine.parts_produced)
            self.publish(f"{base}/Line/PartsScrap", machine.parts_scrap)

            # Line/OEE/ - OEE metrics (real A×P×Q calculation)
            self.publish(f"{base}/Line/OEE/Availability", round(machine.availability, 3))
            self.publish(f"{base}/Line/OEE/Quality", round(machine.quality, 3))
            self.publish(f"{base}/Line/OEE/Performance", round(machine.performance, 3))
            self.publish(f"{base}/Line/OEE/OEE", round(machine.oee, 3))
            self.publish(f"{base}/Line/OEE/DowntimeMinutes", machine.downtime_minutes)
            self.publish(f"{base}/Line/OEE/IdleMinutes", machine.idle_minutes)
            self.publish(f"{base}/Line/OEE/ShiftDurationMinutes", machine.shift_duration_minutes)

            # _raw OEE — persisted to TimescaleDB by historian flow
            self.publish(f"{base}/_raw/oee.availability", round(machine.availability, 3), retain=False)
            self.publish(f"{base}/_raw/oee.quality", round(machine.quality, 3), retain=False)
            self.publish(f"{base}/_raw/oee.performance", round(machine.performance, 3), retain=False)
            self.publish(f"{base}/_raw/oee.oee", round(machine.oee, 3), retain=False)
            self.publish(f"{base}/_raw/parts_produced", machine.parts_produced, retain=False)
            self.publish(f"{base}/_raw/parts_scrap", machine.parts_scrap, retain=False)

    def publish_machine_informative(self, site_id: str, machine: Machine):
        """Publish Dashboard/ namespace - aggregated views (Level 3+, retained)."""
        base = f"{self.prefix}/{site_id}/{machine.department}/{machine.machine_id}"

        if self._level >= ComplexityLevel.LEVEL_3_ERP_MES:
            timestamp = datetime.now().isoformat() + "Z"

            # Dashboard/Asset - asset summary
            self.publish(f"{base}/Dashboard/Asset", {
                "timestamp": timestamp,
                "AssetID": machine.asset_id,
                "Name": machine.name,
                "OEM": machine.oem,
                "Model": machine.model,
                "State": machine.state.name,
            })

            # Dashboard/Job - current job summary
            self.publish(f"{base}/Dashboard/Job", {
                "timestamp": timestamp,
                "JobID": machine.job_id or "",
                "WorkOrder": machine.work_order or "",
                "Customer": machine.customer,
                "ProductName": machine.product_name,
                "QtyTarget": machine.qty_target,
                "QtyComplete": machine.qty_complete,
                "Progress": round(machine.qty_complete / machine.qty_target * 100, 1) if machine.qty_target > 0 else 0,
                "Priority": machine.priority,
                "DueDate": machine.due_date,
            })

            # Dashboard/OEE - OEE summary
            self.publish(f"{base}/Dashboard/OEE", {
                "timestamp": timestamp,
                "Availability": round(machine.availability, 3),
                "Quality": round(machine.quality, 3),
                "Performance": round(machine.performance, 3),
                "OEE": round(machine.oee, 3),
                "DowntimeMinutes": machine.downtime_minutes,
                "IdleMinutes": machine.idle_minutes,
                "ShiftDurationMinutes": machine.shift_duration_minutes,
            })

    def publish_machine(self, site_id: str, machine: Machine, include_descriptive: bool = False):
        """Publish all namespace types for a machine."""
        # Descriptive only on startup or when requested (static data)
        if include_descriptive:
            self.publish_machine_descriptive(site_id, machine)

        # Functional: Real-time operational data
        self.publish_machine_functional(site_id, machine)

        # Informative: Dashboard aggregations (Level 3+)
        self.publish_machine_informative(site_id, machine)

    def publish_status(self, sites: Dict[str, bool]):
        """Publish simulator status."""
        self.publish("metalfab-sim/status", {
            "level": self._level.value,
            "level_name": self._level.name,
            "sites": sites,
            "timestamp": datetime.now().isoformat(),
        })

    def publish_coating_line(self, site_id: str, coating: CoatingLine):
        """Publish CoatingLine data using Edge/, Line/, Dashboard/ structure."""
        base = f"{self.prefix}/{site_id}/finishing/{coating.line_id}"

        # =====================================================================
        # Edge/ - Real-time sensor data (streaming, NOT retained)
        # =====================================================================
        self.publish(f"{base}/Edge/OvenTemp", round(coating.oven_temp_c, 1), retain=False)
        self.publish(f"{base}/Edge/BoothHumidity", round(coating.booth_humidity_pct, 1), retain=False)
        self.publish(f"{base}/Edge/ConveyorSpeed", round(coating.conveyor_speed_mpm, 2), retain=False)

        # Edge/CoatingBooth/ - Booth state (retained - stateful)
        self.publish(f"{base}/Edge/CoatingBooth/CurrentRAL", coating.current_ral)
        self.publish(f"{base}/Edge/CoatingBooth/CurrentColor", coating.current_ral_name)
        self.publish(f"{base}/Edge/CoatingBooth/LastColorChange", coating.last_color_change)

        # _raw — UMH Core data contract for coating sensors
        self.publish(f"{base}/_raw/oven_temp_c", round(coating.oven_temp_c, 1), retain=False)
        self.publish(f"{base}/_raw/booth_humidity_pct", round(coating.booth_humidity_pct, 1), retain=False)
        self.publish(f"{base}/_raw/conveyor_speed_mpm", round(coating.conveyor_speed_mpm, 2), retain=False)
        self.publish(f"{base}/_raw/current_ral", coating.current_ral, retain=False)

        # =====================================================================
        # Line/ - Production data (retained)
        # =====================================================================
        self.publish(f"{base}/Line/TraversalsInLine", coating.traversals_in_line)
        self.publish(f"{base}/Line/PartsInLine", coating.parts_in_line)

        # Line/Zones/ - Zone occupancy counts
        self.publish(f"{base}/Line/Zones/Loading", coating.zone_loading)
        self.publish(f"{base}/Line/Zones/PreTreatment", coating.zone_pretreat)
        self.publish(f"{base}/Line/Zones/Drying", coating.zone_drying)
        self.publish(f"{base}/Line/Zones/Coating", coating.zone_coating)
        self.publish(f"{base}/Line/Zones/Curing", coating.zone_curing)
        self.publish(f"{base}/Line/Zones/Cooling", coating.zone_cooling)

        # =====================================================================
        # Dashboard/ - Aggregated views (Level 3+, retained)
        # =====================================================================
        if self._level >= ComplexityLevel.LEVEL_3_ERP_MES:
            timestamp = datetime.now().isoformat() + "Z"
            self.publish(f"{base}/Dashboard/Summary", {
                "timestamp": timestamp,
                "CurrentRAL": coating.current_ral,
                "CurrentColor": coating.current_ral_name,
                "LastColorChange": coating.last_color_change,
                "OvenTemp": round(coating.oven_temp_c, 1),
                "TraversalsInLine": coating.traversals_in_line,
                "PartsInLine": coating.parts_in_line,
            })
            self.publish(f"{base}/Dashboard/Zones", {
                "timestamp": timestamp,
                "Loading": coating.zone_loading,
                "PreTreatment": coating.zone_pretreat,
                "Drying": coating.zone_drying,
                "Coating": coating.zone_coating,
                "Curing": coating.zone_curing,
                "Cooling": coating.zone_cooling,
            })

    def publish_site_erp(self, site_id: str, facility_sim):
        """Publish site-level ERP namespace (Level 3+) - ProductionOrder, Inventory."""
        if self._level < ComplexityLevel.LEVEL_3_ERP_MES:
            return

        base = f"{self.prefix}/{site_id}/ERP"

        # =====================================================================
        # ERP/ProductionOrder/ - Active production orders
        # =====================================================================
        # Get active jobs from machines - publish complete order data with timestamp
        for machine in facility_sim.machines.values():
            if machine.job_id and machine.state == MachineState.EXECUTE:
                production_order = {
                    "timestamp": datetime.now().isoformat() + "Z",
                    "order_number": machine.job_id,
                    "work_order": machine.work_order or "",
                    "order_status": "InProgress",
                    "customer": machine.customer,
                    "product_name": machine.product_name,
                    "scheduled_start": machine.scheduled_start,
                    "scheduled_end": machine.scheduled_end,
                    "actual_start": machine.scheduled_start,
                    "due_date": machine.due_date,
                    "ordered_quantity": machine.qty_target,
                    "produced_quantity": machine.qty_complete,
                    "remaining_quantity": max(0, machine.qty_target - machine.qty_complete),
                    "progress_pct": round((machine.qty_complete / machine.qty_target * 100), 1) if machine.qty_target > 0 else 0,
                    "priority": machine.priority,
                    "assigned_machine": machine.machine_id,
                    "operator_id": machine.operator_id,
                    "operator_name": machine.operator_name,
                    "operator_notes": machine.operator_notes,
                }
                self.publish(f"{base}/ProductionOrder/{machine.job_id}", production_order)

        # =====================================================================
        # ERP/SalesOrder/New - New sales order events (non-retained)
        # =====================================================================
        # Simulate new sales orders coming in from ERP system
        if random.random() < 0.5:  # 50% chance of new order per ERP publish
            customers = [
                "Bosch Rexroth GmbH",
                "Siemens AG",
                "ABB Automation BV",
                "KUKA Robotics",
                "Phoenix Contact",
                "Schneider Electric",
                "Festo AG",
                "SMC Corporation",
            ]

            products = [
                ("Hydraulic Manifold Block", "DC01", 3.0, 50, 200),
                ("Control Cabinet Panel", "S235JR", 2.0, 100, 500),
                ("Robot Arm Bracket", "S355", 4.0, 20, 100),
                ("Welding Fixture Base", "AISI304", 2.5, 10, 50),
                ("Terminal Housing", "AL5052", 1.5, 200, 1000),
                ("Enclosure Door", "DC01", 2.0, 50, 300),
                ("Pneumatic Mounting Plate", "AL6061", 3.0, 100, 500),
            ]

            customer = random.choice(customers)
            product_name, material, thickness, min_qty, max_qty = random.choice(products)
            order_id = f"SO-2025-{random.randint(10000, 99999)}"
            quantity = random.randint(min_qty, max_qty)

            # Calculate pricing (simplified)
            unit_price = random.uniform(15.50, 89.99)
            total_value = quantity * unit_price

            # Delivery date (2-8 weeks out)
            delivery_date = (datetime.now() + timedelta(weeks=random.randint(2, 8))).isoformat()
            order_date = datetime.now().isoformat()

            sales_order = {
                "event_type": "SALES_ORDER_NEW",
                "timestamp": datetime.now().isoformat() + "Z",
                "order_id": order_id,
                "order_date": order_date,
                "customer": {
                    "name": customer,
                    "customer_id": f"CUST_{random.randint(1000, 9999)}",
                },
                "product": {
                    "name": product_name,
                    "material_code": material,
                    "thickness_mm": thickness,
                    "quantity": quantity,
                    "unit": "pieces",
                },
                "pricing": {
                    "unit_price_eur": round(unit_price, 2),
                    "total_value_eur": round(total_value, 2),
                    "currency": "EUR",
                },
                "delivery": {
                    "requested_date": delivery_date,
                    "delivery_terms": random.choice(["EXW", "FCA", "DAP", "DDP"]),
                    "shipping_address": {
                        "country": random.choice(["DE", "NL", "BE", "AT", "FR"]),
                        "city": random.choice(["Munich", "Stuttgart", "Eindhoven", "Brussels", "Vienna"]),
                    },
                },
                "status": "NEW",
                "priority": random.choice(["STANDARD", "STANDARD", "STANDARD", "EXPRESS", "URGENT"]),
                "payment_terms": random.choice(["NET30", "NET45", "NET60", "PREPAID"]),
                "notes": random.choice([
                    "",
                    "Rush order - expedite if possible",
                    "Quality inspection required",
                    "First order from new customer",
                    "Repeat order - same specs as previous",
                ]),
            }

            self.publish(f"{base}/SalesOrder/New", sales_order, retain=False)

        # =====================================================================
        # ERP/Inventory/ - Material inventory (simulated)
        # =====================================================================
        materials = [
            ("DC01", "Cold rolled steel 2.0mm", 120, 50, 80, "Warehouse A"),
            ("S235JR", "Structural steel 3.0mm", 85, 30, 60, "Warehouse A"),
            ("S355", "High strength steel 4.0mm", 45, 20, 100, "Warehouse B"),
            ("AISI304", "Stainless steel 1.5mm", 60, 25, 40, "Warehouse B"),
            ("AISI316L", "Marine grade SS 2.0mm", 30, 15, 25, "Warehouse B"),
            ("AL5052", "Aluminum alloy 2.5mm", 75, 40, 50, "Warehouse C"),
            ("AL6061", "Aluminum 6061 3.0mm", 55, 20, 45, "Warehouse C"),
        ]

        for mat_code, desc, avail, reserved, ordered, location in materials:
            inventory_item = {
                "timestamp": datetime.now().isoformat() + "Z",
                "item_number": mat_code,
                "item_description": desc,
                "available_quantity": avail + random.randint(-5, 5),
                "reserved_quantity": reserved + random.randint(-3, 3),
                "ordered_quantity": ordered,
                "location": location,
                "unit": "sheets",
            }
            self.publish(f"{base}/Inventory/{mat_code}", inventory_item)

    def publish_site_mes(self, site_id: str, facility_sim):
        """Publish site-level MES namespace (Level 3+) - Quality, Delivery, Utilization."""
        if self._level < ComplexityLevel.LEVEL_3_ERP_MES:
            return

        base = f"{self.prefix}/{site_id}/MES"

        # =====================================================================
        # MES/Quality/ - Quality metrics per machine
        # =====================================================================
        for machine in facility_sim.machines.values():
            quality_pct = round(machine.quality * 100, 1)
            defect_rate = round((1 - machine.quality) * 100, 2)
            quality_data = {
                "timestamp": datetime.now().isoformat() + "Z",
                "machine_id": machine.machine_id,
                "quality_pct": quality_pct,
                "defect_rate_pct": defect_rate,
                "parts_inspected": machine.parts_produced,
                "parts_rejected": machine.parts_scrap,
            }
            self.publish(f"{base}/Quality/{machine.machine_id}", quality_data)

        # =====================================================================
        # MES/Delivery/ - Delivery performance
        # =====================================================================
        on_time_pct = round(random.uniform(94, 99), 1)
        late_orders = random.randint(0, 5)
        total_orders = random.randint(50, 150)
        delivery_data = {
            "timestamp": datetime.now().isoformat() + "Z",
            "on_time_pct": on_time_pct,
            "late_orders": late_orders,
            "total_orders": total_orders,
            "on_time_orders": total_orders - late_orders,
        }
        self.publish(f"{base}/Delivery", delivery_data)

        # =====================================================================
        # MES/Utilization/ - Machine utilization
        # =====================================================================
        machines = list(facility_sim.machines.values())
        fleet_util = sum(m.availability for m in machines) / len(machines) * 100 if machines else 0
        bottleneck = min(machines, key=lambda m: m.oee).machine_id if machines else ""
        utilization_data = {
            "timestamp": datetime.now().isoformat() + "Z",
            "fleet_utilization_pct": round(fleet_util, 1),
            "bottleneck_machine": bottleneck,
            "idle_machines": sum(1 for m in machines if m.state == MachineState.IDLE),
            "executing_machines": sum(1 for m in machines if m.state == MachineState.EXECUTE),
            "total_machines": len(machines),
        }
        self.publish(f"{base}/Utilization", utilization_data)

        # =====================================================================
        # MES/WIP/ - Work in progress
        # =====================================================================
        wip_value = random.randint(25000, 50000)
        turns_per_year = round(random.uniform(10, 15), 1)
        wip_data = {
            "timestamp": datetime.now().isoformat() + "Z",
            "wip_value_eur": wip_value,
            "inventory_turns_per_year": turns_per_year,
            "days_of_inventory": round(365 / turns_per_year, 1),
        }
        self.publish(f"{base}/WIP", wip_data)

    def publish_energy(self, site_id: str, energy: EnergyMonitor):
        """Publish EnergyMonitor data using Edge/, Line/, Asset/, Dashboard/ structure."""
        base = f"{self.prefix}/{site_id}/Energy"

        # =====================================================================
        # Asset/ - Static config (retained)
        # =====================================================================
        self.publish(f"{base}/Asset/SolarCapacityKWp", energy.solar_capacity_kwp)

        # =====================================================================
        # Edge/ - Real-time power readings (streaming, NOT retained)
        # =====================================================================
        self.publish(f"{base}/Edge/ConsumptionKW", round(energy.consumption_kw, 2), retain=False)
        self.publish(f"{base}/Edge/SolarGenerationKW", round(energy.solar_generation_kw, 2), retain=False)
        self.publish(f"{base}/Edge/GridImportKW", round(energy.grid_import_kw, 2), retain=False)

        # =====================================================================
        # Line/ - Daily totals (retained)
        # =====================================================================
        self.publish(f"{base}/Line/ConsumptionKWh", round(energy.consumption_kwh_today, 2))
        self.publish(f"{base}/Line/SolarKWh", round(energy.solar_kwh_today, 2))
        self.publish(f"{base}/Line/CostEUR", round(energy.cost_today_eur, 2))

        # =====================================================================
        # _raw — Unvalidated sensor data for historian flow
        # Topic: umh/v1/metalfab/{site}/energy/main/_raw/{tag}
        # =====================================================================
        raw_base = f"{self.prefix}/{site_id}/energy/main"
        self.publish(f"{raw_base}/_raw/consumption_kw", round(energy.consumption_kw, 2), retain=False)
        self.publish(f"{raw_base}/_raw/solar_generation_kw", round(energy.solar_generation_kw, 2), retain=False)
        self.publish(f"{raw_base}/_raw/grid_import_kw", round(energy.grid_import_kw, 2), retain=False)
        self.publish(f"{raw_base}/_raw/daily_consumption_kwh", round(energy.consumption_kwh_today, 2), retain=False)
        self.publish(f"{raw_base}/_raw/daily_solar_kwh", round(energy.solar_kwh_today, 2), retain=False)
        self.publish(f"{raw_base}/_raw/daily_cost_eur", round(energy.cost_today_eur, 2), retain=False)

        # =====================================================================
        # _energy-monitor_v1 — Validated data contract (educational example)
        # Same data, but published to a typed contract. When a matching data
        # model is defined in UMH Core, the bridge validates every message.
        # Shows how to scale from _raw → structured contracts in production.
        # Topic: umh/v1/metalfab/{site}/energy/main/_energy-monitor_v1/{tag}
        # =====================================================================
        solar_coverage = 0.0
        if energy.consumption_kw > 0:
            solar_coverage = min(100, (energy.solar_generation_kw / energy.consumption_kw) * 100)

        self.publish(f"{raw_base}/_energy-monitor_v1/consumption_kw", round(energy.consumption_kw, 2), retain=False)
        self.publish(f"{raw_base}/_energy-monitor_v1/solar_generation_kw", round(energy.solar_generation_kw, 2), retain=False)
        self.publish(f"{raw_base}/_energy-monitor_v1/grid_import_kw", round(energy.grid_import_kw, 2), retain=False)
        self.publish(f"{raw_base}/_energy-monitor_v1/solar_coverage_pct", round(solar_coverage, 1), retain=False)
        self.publish(f"{raw_base}/_energy-monitor_v1/daily_consumption_kwh", round(energy.consumption_kwh_today, 2), retain=False)
        self.publish(f"{raw_base}/_energy-monitor_v1/daily_solar_kwh", round(energy.solar_kwh_today, 2), retain=False)
        self.publish(f"{raw_base}/_energy-monitor_v1/daily_cost_eur", round(energy.cost_today_eur, 2), retain=False)

        # =====================================================================
        # Dashboard/ - Aggregated views (Level 3+, retained)
        # =====================================================================
        if self._level >= ComplexityLevel.LEVEL_3_ERP_MES:
            self.publish(f"{base}/Dashboard/Summary", {
                "timestamp": datetime.now().isoformat() + "Z",
                "ConsumptionKW": round(energy.consumption_kw, 2),
                "SolarGenerationKW": round(energy.solar_generation_kw, 2),
                "GridImportKW": round(energy.grid_import_kw, 2),
                "SolarCoveragePct": round(solar_coverage, 1),
                "DailyConsumptionKWh": round(energy.consumption_kwh_today, 2),
                "DailySolarKWh": round(energy.solar_kwh_today, 2),
                "DailyCostEUR": round(energy.cost_today_eur, 2),
                "SolarCapacityKWp": energy.solar_capacity_kwp,
            })

    def publish_dpp(self, site_id: str, dpp: DigitalProductPassport):
        """Publish Digital Product Passport data (Level 4, retained)."""
        base = f"{self.prefix}/{site_id}/_dpp/passports/{dpp.dpp_id}"

        # Publish individual DPP namespaces
        self.publish(f"{base}/metadata", dpp.to_metadata_dict())
        self.publish(f"{base}/carbon_footprint", dpp.carbon_footprint.to_dict())
        self.publish(f"{base}/material", dpp.material.to_dict())
        self.publish(f"{base}/traceability", dpp.to_traceability_dict())
        self.publish(f"{base}/certifications", dpp.to_certifications_dict())
        self.publish(f"{base}/summary", dpp.to_summary_dict())

    def publish_dpp_event(self, site_id: str, dpp: DigitalProductPassport, event_type: DPPEventType):
        """Publish DPP event for external subscribers (Level 4, non-retained)."""
        base = f"{self.prefix}/{site_id}/_dpp/events/{event_type.value.lower()}"

        event_data = {
            "event_type": event_type.value,
            "dpp_id": dpp.dpp_id,
            "espr_uid": dpp.espr_uid,
            "job_id": dpp.job_id,
            "work_order": dpp.work_order,
            "product_name": dpp.product_name,
            "customer": dpp.customer,
            "status": dpp.status.value,
            "timestamp": datetime.now().isoformat() + "Z",
        }

        # Add event-specific data
        if event_type == DPPEventType.CREATED:
            event_data["material_code"] = dpp.material.material_code
            event_data["quantity"] = dpp.quantity
        elif event_type == DPPEventType.OPERATION_COMPLETED:
            if dpp.operations:
                last_op = dpp.operations[-1]
                event_data["operation_type"] = last_op.operation_type
                event_data["machine_id"] = last_op.machine_id
                event_data["co2_kg"] = round(last_op.co2_kg, 4)
        elif event_type == DPPEventType.FINALIZED:
            event_data["total_co2_kg"] = round(dpp.carbon_footprint.total_co2_kg, 4)
            event_data["operations_count"] = len(dpp.operations)
            event_data["finalized_at"] = dpp.finalized_at

        self.publish(base, event_data, retain=False)


# =============================================================================
# Multi-Site Runner
# =============================================================================

class MultiSiteSimulator:
    """Runs all facilities with proper semantic hierarchy."""

    def __init__(self, broker: str = "localhost", port: int = 1883, level: int = 2):
        self.publisher = SemanticPublisher(broker, port)
        self.facilities: Dict[str, FacilitySim] = {}
        self._level = ComplexityLevel(level)
        self._running = False

        # Load config for timing parameters
        config_path = Path("config/config.yaml")
        if config_path.exists():
            self.config = Config.from_yaml(config_path)
        else:
            self.config = Config.default()

        # Timing parameters with jitter
        self.tick_interval_ms = self.config.simulation.tick_interval_ms
        self.tick_jitter_pct = self.config.simulation.tick_jitter_pct

        # Site enable/disable tracking
        self._sites_enabled: Dict[str, bool] = {}

        # Track published topics for clear functionality
        self._published_topics: set = set()

        # Digital Product Passports (Level 4) - per-site generators with site-specific grid carbon
        self._dpp_generators: Dict[str, DPPGenerator] = {}
        self._digital_passports: Dict[str, DigitalProductPassport] = {}  # job_id -> DPP

        # Initialize facilities
        first_site = True
        for site_id, facility_config in FACILITIES.items():
            self.facilities[site_id] = FacilitySim(facility_config)
            self._sites_enabled[site_id] = first_site
            first_site = False  # Disable all subsequent sites
            # Per-site DPP generator with site-specific grid carbon intensity
            self._dpp_generators[site_id] = DPPGenerator(
                grid_carbon_intensity=facility_config.grid_carbon_intensity_g_per_kwh,
                renewable_pct=facility_config.renewable_energy_pct,
            )
            logger.info(f"Initialized {facility_config.name} with {len(self.facilities[site_id].machines)} machines")

    def start(self) -> bool:
        if not self.publisher.connect():
            return False

        self.publisher.set_level(self._level)
        self._running = True

        # Set up control callbacks
        self.publisher.set_callbacks(
            level_callback=self._on_level_change,
            site_callback=self._on_site_toggle,
            clear_callback=self._on_clear_retained
        )

        # Publish initial control topics (retained, so they're visible in MQTT Explorer)
        self._publish_initial_control_topics()

        # Publish initial status
        self.publisher.publish_status(self._sites_enabled)

        return True

    def _on_level_change(self, new_level: ComplexityLevel):
        """Handle level change from MQTT control."""
        old_level = self._level
        self._level = new_level
        self.publisher.set_level(new_level)
        logger.info(f"Simulator level changed to {new_level.name}")

        # When switching to Level 4, create DPPs for all active jobs
        if new_level >= ComplexityLevel.LEVEL_4_FULL and old_level < ComplexityLevel.LEVEL_4_FULL:
            logger.info("Level 4 activated - creating DPPs for active jobs...")
            for site_id, facility_sim in self.facilities.items():
                if not self._sites_enabled.get(site_id, True):
                    continue

                for machine in facility_sim.machines.values():
                    if machine.job_id and not machine.dpp_created:
                        self._create_dpp_for_machine(site_id, machine)
                        machine.dpp_created = True
            logger.info("DPPs created for active jobs")

    def _on_site_toggle(self, site_id: str, enabled: bool):
        """Handle site enable/disable from MQTT control."""
        if site_id in self._sites_enabled:
            # Only act if state actually changed
            if self._sites_enabled[site_id] != enabled:
                self._sites_enabled[site_id] = enabled
                logger.info(f"Site '{site_id}' {'enabled' if enabled else 'disabled'}")

                if not enabled:
                    # Clear retained data for disabled site
                    site_topics = [t for t in self._published_topics if f"/{site_id}/" in t]
                    self.publisher.clear_retained(site_topics)
                    logger.info(f"Cleared retained data for disabled site: {site_id}")
        else:
            logger.warning(f"Unknown site: {site_id}")

    def _on_clear_retained(self):
        """Handle clear all retained data from MQTT control."""
        logger.info(f"Clearing all retained data ({len(self._published_topics)} topics)...")
        self.publisher.clear_retained(list(self._published_topics))
        self._published_topics.clear()
        # Republish control topics (they were cleared too)
        self._publish_initial_control_topics()
        logger.info("All retained data cleared, control topics republished")

    def _publish_initial_control_topics(self):
        """Publish initial control topics (retained) so they're visible in MQTT Explorer."""
        # Publish current level
        self.publisher.publish("metalfab-sim/control/level", self._level.value, retain=True)
        logger.info(f"Published initial control/level: {self._level.value}")

        # Publish current site states
        for site_id, enabled in self._sites_enabled.items():
            topic = f"metalfab-sim/control/site/{site_id}"
            self.publisher.publish(topic, 1 if enabled else 0, retain=True)
            logger.info(f"Published initial control/site/{site_id}: {1 if enabled else 0}")

        # Publish clear state (0 = not clearing)
        self.publisher.publish("metalfab-sim/control/clear", 0, retain=True)
        logger.info("Published initial control/clear: 0")

    def stop(self):
        self._running = False
        self.publisher.disconnect()

    def run(self):
        """Main simulation loop."""
        tick = 0
        descriptive_published = False

        while self._running:
            if self._level == ComplexityLevel.LEVEL_0_PAUSED:
                time.sleep(1)
                continue

            tick += 1

            # Publish DESCRIPTIVE data for all sites on the first tick
            if not descriptive_published:
                logger.info("Publishing Descriptive namespace for all sites...")
                for site_id, facility_sim in self.facilities.items():
                    for machine in facility_sim.machines.values():
                        self._publish_tracked(
                            lambda s=site_id, m=machine: self.publisher.publish_machine_descriptive(s, m),
                            site_id, machine
                        )
                descriptive_published = True

            # Update all enabled facilities
            for site_id, facility_sim in self.facilities.items():
                # Skip disabled sites
                if not self._sites_enabled.get(site_id, True):
                    continue

                # Check for jobs about to complete (before tick) - Level 4 DPP
                if self._level >= ComplexityLevel.LEVEL_4_FULL:
                    for machine in facility_sim.machines.values():
                        # If machine is in COMPLETING state and has a DPP, finalize it
                        if machine.state == MachineState.COMPLETING and machine.job_id:
                            if machine.job_id in self._digital_passports:
                                self._record_operation_for_machine(site_id, machine)
                                self._finalize_dpp_for_machine(site_id, machine)

                facility_sim.tick()

                # Publish FUNCTIONAL and INFORMATIVE data each tick
                for machine in facility_sim.machines.values():
                    self._publish_tracked(
                        lambda s=site_id, m=machine: self.publisher.publish_machine(s, m, include_descriptive=False),
                        site_id, machine
                    )

                    # Create DPPs for new jobs (Level 4 only)
                    if self._level >= ComplexityLevel.LEVEL_4_FULL:
                        if machine.job_id and not machine.dpp_created:
                            self._create_dpp_for_machine(site_id, machine)
                            machine.dpp_created = True

                # Publish CoatingLine data (Eindhoven has shared coating line)
                if facility_sim.coating_line:
                    self._publish_tracked(
                        lambda s=site_id, c=facility_sim.coating_line: self.publisher.publish_coating_line(s, c),
                        site_id, None
                    )

                # Publish Energy data (all facilities)
                if facility_sim.energy:
                    self._publish_tracked(
                        lambda s=site_id, e=facility_sim.energy: self.publisher.publish_energy(s, e),
                        site_id, None
                    )

                # Publish ERP data (Level 3+ only, every 3 ticks = ~15s)
                if tick % 3 == 0:
                    self.publisher.publish_site_erp(site_id, facility_sim)

                # Publish MES data (Level 3+ only, every 2 ticks = ~10s)
                if tick % 2 == 0:
                    self.publisher.publish_site_mes(site_id, facility_sim)

            # Update status periodically and publish root control state
            if tick % 10 == 0:
                self.publisher.publish_status(self._sites_enabled)
                self._publish_root_status()

            # Calculate sleep time with jitter
            jitter_factor = 1.0 + random.uniform(-self.tick_jitter_pct / 100, self.tick_jitter_pct / 100)
            sleep_time = (self.tick_interval_ms / 1000.0) * jitter_factor
            time.sleep(sleep_time)

    def _publish_root_status(self):
        """Publish root level status topics for demo control - separate values."""
        # metalfab-sim/status/ - main status as separate topics (retained)
        self.publisher.publish("metalfab-sim/status/level", self._level.value)
        self.publisher.publish("metalfab-sim/status/level_name", self._level.name)
        self.publisher.publish("metalfab-sim/status/timestamp", datetime.now().isoformat())

        # metalfab-sim/sites/{site}/ - individual site status as separate topics (retained)
        for site_id, enabled in self._sites_enabled.items():
            facility = FACILITIES.get(site_id)
            base = f"metalfab-sim/sites/{site_id}"
            self.publisher.publish(f"{base}/enabled", enabled)
            self.publisher.publish(f"{base}/name", facility.name if facility else site_id)
            self.publisher.publish(f"{base}/machines", len(self.facilities[site_id].machines) if site_id in self.facilities else 0)
            if facility:
                self.publisher.publish(f"{base}/country", facility.country)
                self.publisher.publish(f"{base}/city", facility.city)

    def _publish_tracked(self, publish_fn, site_id: str, machine):
        """Publish and track the topics for later clear."""
        # Build expected topic patterns for tracking
        prefix = self.publisher.prefix
        if machine:
            base = f"{prefix}/{site_id}/{machine.department}/{machine.machine_id}"
            self._published_topics.add(f"{base}/Asset/AssetID")
            self._published_topics.add(f"{base}/Edge/State")
            self._published_topics.add(f"{base}/Line/Infeed")
        else:
            # Site-level topics
            self._published_topics.add(f"{prefix}/{site_id}/finishing/coating_line_01/Functional/CoatingBooth/CurrentRAL")
            self._published_topics.add(f"{prefix}/{site_id}/Energy/Functional/Daily/ConsumptionKWh")

        # Execute the publish
        publish_fn()

    def _create_dpp_for_machine(self, site_id: str, machine: Machine):
        """Create a Digital Product Passport for a machine's current job."""
        if not machine.job_id or machine.dpp_created:
            return

        facility = FACILITIES.get(site_id)
        country = facility.country if facility else "XX"

        # Create DPP using the site-specific generator
        dpp = self._dpp_generators[site_id].create_dpp_for_job(
            job_id=machine.job_id,
            work_order=machine.work_order or f"WO-{random.randint(1000, 9999)}",
            product_name=machine.product_name or "Sheet Metal Part",
            customer=machine.customer or "Unknown Customer",
            material_code=machine.material_code or "DC01",
            thickness_mm=machine.material_thickness_mm or 2.0,
            quantity=machine.qty_target or 100,
            site=facility.name if facility else site_id,
            country=country,
        )

        # Store the DPP
        self._digital_passports[machine.job_id] = dpp

        # Publish DPP to MQTT
        self.publisher.publish_dpp(site_id, dpp)
        self.publisher.publish_dpp_event(site_id, dpp, DPPEventType.CREATED)

        logger.info(f"Created DPP {dpp.dpp_id} for job {machine.job_id} on {machine.machine_id}")

    def _record_operation_for_machine(self, site_id: str, machine: Machine):
        """Record an operation for a machine's DPP when job completes."""
        if not machine.job_id or machine.job_id not in self._digital_passports:
            return

        dpp = self._digital_passports[machine.job_id]

        # Determine operation type from machine type
        operation_type_map = {
            "laser_cutter": "LASER_CUTTING",
            "press_brake": "PRESS_FORMING",
            "robot_weld": "ROBOTIC_WELDING",
            "manual_weld": "MANUAL_WELDING",
            "powder_coating_line": "POWDER_COATING",
            "assembly": "ASSEMBLY",
            "quality_control": "QUALITY_INSPECTION",
        }
        operation_type = operation_type_map.get(machine.machine_type, "PROCESSING")

        # Simulate operation duration and energy
        if machine.job_started_at:
            duration_minutes = (datetime.now() - machine.job_started_at).total_seconds() / 60
        else:
            duration_minutes = random.uniform(15, 120)

        # Estimate energy consumption based on machine type and duration
        power_kw_map = {
            "laser_cutter": random.uniform(35, 50),
            "press_brake": random.uniform(15, 30),
            "robot_weld": random.uniform(10, 18),
            "manual_weld": random.uniform(5, 12),
            "powder_coating_line": random.uniform(40, 60),
            "assembly": random.uniform(2, 5),
            "quality_control": random.uniform(1, 3),
        }
        power_kw = power_kw_map.get(machine.machine_type, 10.0)
        energy_kwh = (power_kw * duration_minutes) / 60

        # Create operation record
        operation = self._dpp_generators[site_id].create_operation_record(
            operation_type=operation_type,
            machine_id=machine.machine_id,
            machine_type=machine.machine_type,
            operator_id=machine.operator_id or "OP_UNKNOWN",
            operator_name=machine.operator_name or "Unknown Operator",
            duration_minutes=duration_minutes,
            energy_kwh=energy_kwh,
            parts_produced=machine.qty_complete,
            parts_scrap=machine.parts_scrap,
        )

        # Add operation to DPP
        dpp.add_operation(operation)
        dpp.status = DPPStatus.IN_PROGRESS

        # Publish updated DPP and event
        self.publisher.publish_dpp(site_id, dpp)
        self.publisher.publish_dpp_event(site_id, dpp, DPPEventType.OPERATION_COMPLETED)

        logger.info(f"Recorded {operation_type} operation for DPP {dpp.dpp_id}")

    def _finalize_dpp_for_machine(self, site_id: str, machine: Machine):
        """Finalize DPP when job completes."""
        if not machine.job_id or machine.job_id not in self._digital_passports:
            return

        dpp = self._digital_passports[machine.job_id]

        # Add quality check (simulated)
        quality_check = self._dpp_generators[site_id].create_quality_check("DIMENSIONAL")
        dpp.add_quality_check(quality_check)

        # Finalize the DPP
        dpp.finalize()

        # Publish updated DPP and event
        self.publisher.publish_dpp(site_id, dpp)
        self.publisher.publish_dpp_event(site_id, dpp, DPPEventType.FINALIZED)

        logger.info(f"Finalized DPP {dpp.dpp_id} for completed job {machine.job_id}")

        # Remove from active passports (keep in memory for potential lookup)
        # del self._digital_passports[machine.job_id]


def _get_marker_file() -> Path:
    """Get path to the first-run marker file."""
    # Store in user's home directory or current directory
    home_marker = Path.home() / ".metalfab-simulator" / ".first_run_complete"
    local_marker = Path(".metalfab-simulator-initialized")

    # Prefer home directory, fallback to local
    if home_marker.parent.exists() or not local_marker.exists():
        home_marker.parent.mkdir(parents=True, exist_ok=True)
        return home_marker
    return local_marker


def _is_first_run() -> bool:
    """Check if this is the first run of the simulator."""
    marker_file = _get_marker_file()
    return not marker_file.exists()


def _mark_first_run_complete() -> None:
    """Mark that the first run has completed successfully."""
    marker_file = _get_marker_file()
    marker_file.parent.mkdir(parents=True, exist_ok=True)
    marker_file.write_text(f"First run completed at {datetime.now().isoformat()}\n")
    logger.info(f"Created marker file: {marker_file}")


def run_multi_site(
    level: int = 2,
    broker: str = "localhost",
    port: int = 1883,
    clean_start: bool = False,
    auto_clean: bool = True,
):
    """Run the multi-site simulator.

    Args:
        level: Complexity level (0-4)
        broker: MQTT broker address
        port: MQTT broker port
        clean_start: Force clear all retained topics on this run
        auto_clean: Automatically clear retained topics on first run (default: True)
    """

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Check if we need to clear retained topics
    should_clear = clean_start or (auto_clean and _is_first_run())

    if should_clear:
        logger.info("=" * 60)
        logger.info("CLEARING RETAINED MQTT TOPICS")
        logger.info("=" * 60)

        if _is_first_run() and not clean_start:
            logger.info("First run detected - performing automatic cleanup")
        elif clean_start:
            logger.info("Clean start requested - clearing all retained data")

        # Create temporary MQTT client just for clearing
        from .mqtt_client import MQTTClient
        from .config import Config

        config = Config()
        config.mqtt.broker = broker
        config.mqtt.port = port

        temp_client = MQTTClient(config.mqtt, config.uns)

        # Connect temporarily
        if temp_client.connect():
            logger.info("Connected to MQTT broker for cleanup")

            # Clear all retained topics BEFORE starting simulator
            temp_client.clear_retained_topics()

            # Disconnect cleanup client
            temp_client.disconnect()
            logger.info("Cleanup complete")

            # Wait a moment for MQTT to process
            import time
            time.sleep(1)
        else:
            logger.warning("Could not connect to MQTT broker for cleanup - proceeding anyway")

        logger.info("=" * 60)
        logger.info("")

    sim = MultiSiteSimulator(broker, port, level)

    def signal_handler(sig, frame):
        logger.info("Shutting down...")
        sim.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if sim.start():
        # Mark first run as complete (only after successful start)
        if _is_first_run():
            _mark_first_run_complete()
        print()
        print("=" * 60)
        print("MetalFab Multi-Site Simulator")
        print("=" * 60)
        print(f"Level: {level} ({ComplexityLevel(level).name})")
        print(f"MQTT:  {broker}:{port}")
        print(f"Tick:  {sim.tick_interval_ms}ms ±{sim.tick_jitter_pct}% ({int(sim.tick_interval_ms * (1 - sim.tick_jitter_pct/100))}-{int(sim.tick_interval_ms * (1 + sim.tick_jitter_pct/100))}ms)")
        print()
        print("Facilities:")
        for site_id, facility in FACILITIES.items():
            facility_sim = sim.facilities[site_id]
            machines = facility_sim.machines
            print(f"  {site_id}: {facility.name}")
            print(f"    Departments: {set(m.department for m in machines.values())}")
            print(f"    Machines: {len(machines)}")
            if facility_sim.coating_line:
                print(f"    Coating Line: Yes (RAL colors, zones)")
            if facility_sim.energy:
                print(f"    Solar: {facility_sim.energy.solar_capacity_kwp} kWp")
        print()
        print("Topic Structure:")
        print("  umh/v1/metalfab/{site}/{dept}/{machine}/")
        print("    ├── Asset/       (Static metadata - retained)")
        print("    ├── Edge/        (Real-time sensors - streaming)")
        print("    │   └── ShopFloor/  (Job context, ERP data)")
        print("    ├── Line/        (Production data - retained)")
        print("    │   └── OEE/        (Availability, Quality, etc.)")
        print("    └── Dashboard/   (Aggregated views - Level 3+)")
        print()
        print("  umh/v1/metalfab/{site}/ERP/  (Level 3+)")
        print("    ├── ProductionOrder/{JobID}/  (Orders, quantities)")
        print("    └── Inventory/{MaterialCode}/ (Stock levels)")
        print()
        print("  umh/v1/metalfab/{site}/MES/  (Level 3+)")
        print("    ├── Quality/{machine}/  (Defect rates)")
        print("    ├── Delivery/           (On-time %)")
        print("    ├── Utilization/        (Fleet, bottleneck)")
        print("    └── WIP/                (Value, turns)")
        print()
        print("  umh/v1/metalfab/{site}/Energy/")
        print("    ├── Asset/      (Solar capacity)")
        print("    ├── Edge/       (Real-time kW)")
        print("    ├── Line/       (Daily kWh)")
        print("    └── Dashboard/  (Summary)")
        print()
        print("=" * 60)
        print("MQTT Control Topics (interactive demo control)")
        print("=" * 60)
        print()
        print("  Level Control (0-4) - visible in MQTT Explorer:")
        print("    Topic:   metalfab-sim/control/level")
        print("    Current: " + str(level))
        print("    Payload: 0 (paused), 1 (sensors), 2 (stateful), 3 (ERP/MES), 4 (full)")
        print()
        print("  Site Toggle (on/off) - visible in MQTT Explorer:")
        print("    Topic:   metalfab-sim/control/site/eindhoven")
        print("    Topic:   metalfab-sim/control/site/roeselare")
        print("    Topic:   metalfab-sim/control/site/brasov")
        print("    Payload: 1 (enable) or 0 (disable)")
        print()
        print("  Clear All Retained Data:")
        print("    Topic:   metalfab-sim/control/clear")
        print("    Payload: 1 (will auto-reset to 0)")
        print()
        print("Examples (mosquitto_pub or MQTT Explorer):")
        print('  mosquitto_pub -t "metalfab-sim/control/level" -m "3"')
        print('  mosquitto_pub -t "metalfab-sim/control/site/brasov" -m "0"')
        print('  mosquitto_pub -t "metalfab-sim/control/clear" -m "1"')
        print()
        print("Press Ctrl+C to stop")
        print()

        sim.run()
    else:
        print("Failed to start simulator")
        sys.exit(1)


if __name__ == "__main__":
    run_multi_site(level=4)
