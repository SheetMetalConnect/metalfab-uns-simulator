"""Main simulator orchestrating all components.

Simulates a realistic metalworking/sheet metal fabrication facility with:

- **Descriptive Namespace** (_meta): Asset metadata, OEM info, service dates
- **Functional Namespace** (_state, _raw, _erp, _mes): Real-time operations
- **Informative Namespace** (_dashboard): Aggregated data for consumers

Includes realistic simulation of:
- Machine cells with PackML state machines
- Jobs with ERP/MES enrichment data
- Operators and shift management
- Solar power generation
- AGV fleet management
- Inventory tracking
"""

import logging
import math
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from .complexity import ComplexityLevel, get_features_for_level
from .config import Config, CellConfig
from .generators import (
    # Core generators
    ERPMESGenerator,
    Job,
    JobGenerator,
    JobStatus,
    MachineSubState,
    PackMLState,
    SensorGenerator,
    create_sensor_generators,
    # New generators
    OperatorGenerator,
    OperatorRole,
    OperatorStatus,
    ShiftType,
    SolarGenerator,
    ProductionOrderGenerator,
    InventoryGenerator,
    AGVPosition,
    create_asset_metadata,
    # Powder coating line
    PowderCoatingLine,
    PowderCoatingZone,
    RAL_COLORS,
)
from .mqtt_client import MQTTClient
from .digital_passport import (
    DigitalProductPassport,
    DPPGenerator,
    DPPEventType,
    DPPStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class CellState:
    """Runtime state for a machine cell."""

    config: CellConfig
    state: PackMLState = PackMLState.IDLE
    sub_state: MachineSubState = MachineSubState.NONE
    current_job: Optional[Job] = None
    operator_id: Optional[str] = None
    state_since: datetime = field(default_factory=datetime.now)
    cycle_count: int = 0
    parts_produced: int = 0
    parts_scrap: int = 0
    sensors: Dict[str, SensorGenerator] = field(default_factory=dict)

    # AGV specific
    position_x: float = 0.0
    position_y: float = 0.0
    target_x: float = 0.0
    target_y: float = 0.0
    battery_pct: float = 100.0


class Simulator:
    """Main simulator class orchestrating all components."""

    def __init__(self, config: Config, mqtt_client: Optional[MQTTClient] = None):
        self.config = config
        self._level = ComplexityLevel(config.simulation.initial_level)
        self._running = False
        self._tick_thread: Optional[threading.Thread] = None
        self._sites_enabled: Dict[str, bool] = {}

        # Initialize MQTT client
        if mqtt_client:
            self._mqtt = mqtt_client
        else:
            self._mqtt = MQTTClient(
                config.mqtt,
                config.uns,
                on_level_change=self._on_level_change,
                on_site_toggle=self._on_site_toggle,
            )

        # Initialize cell states
        self._cells: Dict[str, CellState] = {}
        self._init_cells()

        # Initialize job management
        self._jobs: Dict[str, Job] = {}
        self._job_generator = JobGenerator(
            templates=[
                {
                    "name": t.name,
                    "routing": t.routing,
                    "qty_range": t.qty_range,
                    "material": getattr(t, "material", "DC01"),
                    "thickness": getattr(t, "thickness", 2.0),
                }
                for t in config.job_templates
            ],
            customers=config.customers,
        )

        # Initialize ERP/MES generator
        self._erp_mes = ERPMESGenerator()

        # Initialize new generators
        self._operator_gen = OperatorGenerator(num_operators=12)
        self._solar_gen = SolarGenerator()
        self._production_order_gen = ProductionOrderGenerator()
        self._inventory_gen = InventoryGenerator()

        # Digital Product Passports (Level 4)
        self._dpp_generator = DPPGenerator(
            grid_carbon_intensity=350.0,  # EU average g CO2/kWh
            renewable_pct=30.0  # EU renewable energy %
        )
        self._digital_passports: Dict[str, DigitalProductPassport] = {}  # job_id -> DPP
        self._dpp_events: List[Dict[str, Any]] = []  # Recent events for external subscribers

        # Asset metadata cache
        self._asset_metadata = {}
        self._init_asset_metadata()

        # AGV fleet state
        self._agv_positions: Dict[str, AGVPosition] = {}
        self._init_agv_positions()

        # Shared Powder Coating Line (located in Eindhoven, serves all facilities)
        self._powder_coating_line = PowderCoatingLine(
            line_id="COAT_LINE_01",
            location="eindhoven"
        )

        # Timing
        self._tick_count = 0
        self._last_job_time = 0.0
        self._job_interval = random.randint(30, 90)  # New job every 30-90s (faster for demo)
        self._shift_check_time = 0.0

        # Random update intervals (10-60 seconds) for ERP/MES/Dashboard data
        self._last_erp_time = 0.0
        self._erp_interval = random.uniform(10, 60)
        self._last_mes_quality_time = 0.0
        self._mes_quality_interval = random.uniform(10, 60)
        self._last_oee_time = 0.0
        self._oee_interval = random.uniform(10, 60)
        self._last_delivery_time = 0.0
        self._delivery_interval = random.uniform(10, 60)
        self._last_inventory_time = 0.0
        self._inventory_interval = random.uniform(10, 60)
        self._last_dashboard_time = 0.0
        self._dashboard_interval = random.uniform(10, 60)
        self._last_analytics_time = 0.0
        self._analytics_interval = random.uniform(60, 180)  # Analytics stays longer
        self._last_powder_planning_time = 0.0
        self._powder_planning_interval = random.uniform(10, 60)

    def _init_asset_metadata(self) -> None:
        """Initialize asset metadata for all cells."""
        for cell_id, cell in self._cells.items():
            self._asset_metadata[cell_id] = create_asset_metadata(
                cell_id, cell.config.cell_type
            )

    def _init_agv_positions(self) -> None:
        """Initialize AGV positions with waypoint system."""
        # Define waypoints with coordinates (meters)
        waypoints = {
            "A": (5.0, 5.0, "WAREHOUSE"),
            "B": (15.0, 5.0, "LASER_AREA"),
            "C": (25.0, 5.0, "BENDING_AREA"),
            "D": (35.0, 5.0, "WELDING_AREA"),
            "E": (45.0, 5.0, "SHIPPING"),
            "F": (25.0, 15.0, "FINISHING"),
            "DOCK_01": (2.0, 2.0, "WAREHOUSE"),
            "DOCK_02": (48.0, 2.0, "SHIPPING"),
            "CHARGE_01": (10.0, 25.0, "CHARGING_STATION"),
        }

        for cell_id, cell in self._cells.items():
            if cell.config.cell_type == "agv":
                # Start at random waypoint
                start_wp = random.choice(["A", "B", "C", "D", "E", "F"])
                start_x, start_y, start_zone = waypoints[start_wp]

                # Random target
                target_wp = random.choice(["A", "B", "C", "D", "E", "F"])

                self._agv_positions[cell_id] = AGVPosition(
                    agv_id=cell_id,
                    x=start_x,
                    y=start_y,
                    heading_deg=random.uniform(0, 360),
                    current_waypoint=start_wp,
                    target_waypoint=target_wp,
                    path=f"{start_wp}→{target_wp}",
                    zone=start_zone,
                    status="IDLE",
                    battery_pct=random.uniform(70, 100),
                    max_payload_kg=250.0,
                )

        # Store waypoints for later use
        self._agv_waypoints = waypoints

    @property
    def level(self) -> ComplexityLevel:
        return self._level

    @level.setter
    def level(self, value: ComplexityLevel):
        self._level = value
        self._mqtt.set_level(value)

    def _init_cells(self) -> None:
        """Initialize cell states from config."""
        first_site = True
        for area in self.config.areas:
            site_id = area.id  # Treat area as a site for toggling
            self._sites_enabled[site_id] = first_site
            first_site = False  # Disable all subsequent sites
            for cell_config in area.cells:
                cell_config.area_id = area.id
                sensors = create_sensor_generators(cell_config.cell_type)
                self._cells[cell_config.id] = CellState(
                    config=cell_config,
                    sensors=sensors,
                    operator_id=f"OP_{random.randint(100, 999)}",
                )
        logger.info(f"Initialized {len(self._cells)} cells across {len(self._sites_enabled)} sites.")
        enabled_sites = [site for site, enabled in self._sites_enabled.items() if enabled]
        logger.info(f"Enabled sites: {enabled_sites}")

    def _on_level_change(self, level: ComplexityLevel) -> None:
        """Handle complexity level changes from MQTT."""
        old_level = self._level
        self._level = level
        logger.info(f"Level changed to {level.name}")
        self._publish_simulator_status()

        # If switching to Level 4, create DPPs for jobs already in progress
        if level == ComplexityLevel.LEVEL_4_FULL and old_level < ComplexityLevel.LEVEL_4_FULL:
            self._create_dpps_for_active_jobs()

    def _on_site_toggle(self, site_id: str, enabled: bool) -> None:
        """Handle site enable/disable changes from MQTT."""
        if site_id in self._sites_enabled:
            self._sites_enabled[site_id] = enabled
            logger.info(f"Site '{site_id}' {'enabled' if enabled else 'disabled'}")
            self._publish_simulator_status()
        else:
            logger.warning(f"Received toggle for unknown site: {site_id}")

    def _publish_simulator_status(self) -> None:
        """Publish the current status of the simulator."""
        self._mqtt.publish_simulator_status(self._level, self._sites_enabled)

    def start(self, dry_run: bool = False) -> bool:
        """Start the simulator."""
        # Connect to MQTT
        if not self._mqtt.connect(dry_run=dry_run):
            logger.error("Failed to connect to MQTT broker")
            return False

        # Set initial level
        self._mqtt.set_level(self._level)

        # Publish initial status
        self._publish_simulator_status()

        # Publish initial metadata
        self._publish_metadata()

        # Generate initial jobs
        self._generate_initial_jobs()

        # Start tick loop
        self._running = True
        self._tick_thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._tick_thread.start()

        # If starting at Level 4, create DPPs for any active jobs after a brief delay
        # (gives time for jobs to start)
        if self._level == ComplexityLevel.LEVEL_4_FULL:
            def delayed_dpp_creation():
                time.sleep(3)  # Wait for initial jobs to start
                self._create_dpps_for_active_jobs()
            threading.Thread(target=delayed_dpp_creation, daemon=True).start()

        logger.info(f"Simulator started at level {self._level.name}")
        return True

    def stop(self) -> None:
        """Stop the simulator."""
        self._running = False
        if self._tick_thread:
            self._tick_thread.join(timeout=5)
        self._mqtt.disconnect()
        logger.info("Simulator stopped")

    def _tick_loop(self) -> None:
        """Main simulation tick loop with randomized intervals."""
        base_interval = self.config.simulation.tick_interval_ms / 1000.0 / self.config.simulation.time_acceleration
        jitter_pct = getattr(self.config.simulation, 'tick_jitter_pct', 0) / 100.0

        while self._running:
            try:
                self._tick()

                # Add randomization (jitter) to make timing more realistic
                if jitter_pct > 0:
                    jitter = random.uniform(-jitter_pct, jitter_pct)
                    actual_interval = base_interval * (1.0 + jitter)
                else:
                    actual_interval = base_interval

                time.sleep(actual_interval)
            except Exception as e:
                logger.error(f"Error in tick loop: {e}")
                time.sleep(1)

    def _tick(self) -> None:
        """Execute one simulation tick.

        Realistic update intervals (assuming 1 second tick):
        - Sensors (_raw): Every tick (1s) - real-time process data
        - Machine states: Every tick (1s) - state machine updates
        - Jobs: Every tick (1s) - position tracking
        - Solar: Every 5s - power generation readings
        - Operators: Every 30s - attendance updates
        - ERP data: Random 10-60s - business system integration
        - MES quality: Random 10-60s - quality aggregations
        - OEE: Random 10-60s - performance calculations
        - Delivery: Random 10-60s - logistics metrics
        - Inventory: Random 10-60s - stock levels
        - Dashboard: Random 10-60s - summary updates
        - Analytics: Random 60-180s - advanced calculations
        - Powder coating planning: Random 10-60s
        """
        if self._level == ComplexityLevel.LEVEL_0_PAUSED:
            # If paused, do nothing.
            return

        self._tick_count += 1
        current_time = time.time()
        features = get_features_for_level(self._level)

        # Level 1: Sensors
        if features.sensors:
            self._publish_sensors()

        # Level 1+: Solar power (always publish energy generation)
        if features.energy_basic and self._tick_count % 5 == 0:
            self._publish_solar_power()

        # Level 2: Stateful
        if features.machine_state:
            self._update_machine_states()
            self._publish_machine_states()

        if features.job_tracking:
            self._update_jobs()
            self._publish_jobs()

        if features.agv_positions:
            self._update_agv()
            self._publish_agv_positions()

        # Level 2+: Operator attendance (part of stateful)
        if features.machine_state and self._tick_count % 30 == 0:
            self._update_operators()
            self._publish_operator_attendance()

        # Level 3: ERP/MES (random intervals 10-60s for realistic variation)
        if features.erp_job_data and (current_time - self._last_erp_time) >= self._erp_interval:
            self._publish_erp_data()
            self._last_erp_time = current_time
            self._erp_interval = random.uniform(10, 60)

        if features.mes_quality and (current_time - self._last_mes_quality_time) >= self._mes_quality_interval:
            self._publish_mes_quality()
            self._last_mes_quality_time = current_time
            self._mes_quality_interval = random.uniform(10, 60)

        if features.mes_oee and (current_time - self._last_oee_time) >= self._oee_interval:
            self._publish_oee()
            self._last_oee_time = current_time
            self._oee_interval = random.uniform(10, 60)

        if features.delivery_metrics and (current_time - self._last_delivery_time) >= self._delivery_interval:
            self._publish_delivery_metrics()
            self._last_delivery_time = current_time
            self._delivery_interval = random.uniform(10, 60)

        if features.inventory_wip and (current_time - self._last_inventory_time) >= self._inventory_interval:
            self._publish_inventory()
            self._publish_raw_material_inventory()
            self._last_inventory_time = current_time
            self._inventory_interval = random.uniform(10, 60)

        # Level 4: Full (random intervals)
        if features.dashboards and (current_time - self._last_dashboard_time) >= self._dashboard_interval:
            self._publish_dashboard()
            self._last_dashboard_time = current_time
            self._dashboard_interval = random.uniform(10, 60)

        if features.analytics_advanced and (current_time - self._last_analytics_time) >= self._analytics_interval:
            self._publish_analytics()
            self._last_analytics_time = current_time
            self._analytics_interval = random.uniform(60, 180)  # Analytics stays longer

        if features.events_alarms and random.random() < 0.02:
            self._publish_random_event()

        # Powder Coating Line (Level 2+)
        if features.machine_state:
            self._update_powder_coating_line()
            self._publish_powder_coating_state()

        # Powder Coating MES Planning (Level 3+, random 10-60s)
        if features.erp_job_data and (current_time - self._last_powder_planning_time) >= self._powder_planning_interval:
            self._publish_powder_coating_planning()
            self._last_powder_planning_time = current_time
            self._powder_planning_interval = random.uniform(10, 60)

        # Periodically generate new jobs (faster in Level 4 for DPP demo)
        if time.time() - self._last_job_time > self._job_interval:
            self._generate_new_job()
            self._last_job_time = time.time()
            # Generate jobs faster at Level 4 to create more DPPs
            if self._level == ComplexityLevel.LEVEL_4_FULL:
                self._job_interval = random.randint(20, 60)  # Every 20-60s at Level 4
            else:
                self._job_interval = random.randint(60, 180)  # Every 1-3 min at other levels

        # Check for shift changes
        self._check_shift_change()

    # =========================================================================
    # Publishing methods
    # =========================================================================

    def _publish_metadata(self) -> None:
        """Publish rich asset metadata (Level 2+) - Descriptive Namespace."""
        for cell_id, cell in self._cells.items():
            # Use rich asset metadata
            meta = self._asset_metadata.get(cell_id)
            if meta:
                topic = f"{cell.config.area_id}/{cell_id}/_meta/asset"
                payload = meta.to_meta_dict()
                # Add runtime sensor list
                payload["sensors"] = list(cell.sensors.keys())
                payload["nominal_power_kw"] = cell.config.nominal_power_kw
                self._mqtt.publish(
                    topic, payload, retain=True, required_level=ComplexityLevel.LEVEL_2_STATEFUL
                )

        # Publish solar array metadata
        for array in self._solar_gen.arrays:
            topic = f"_meta/solar/{array.array_id}"
            self._mqtt.publish(
                topic, array.to_meta_dict(), retain=True, required_level=ComplexityLevel.LEVEL_2_STATEFUL
            )

        # Publish operator metadata
        for op_id, op in self._operator_gen.operators.items():
            topic = f"_meta/operators/{op_id}"
            self._mqtt.publish(
                topic, op.to_meta_dict(), retain=True, required_level=ComplexityLevel.LEVEL_2_STATEFUL
            )

        # Publish powder coating line metadata
        self._publish_powder_coating_metadata()

    def _publish_sensors(self) -> None:
        """Publish sensor data (Level 1+)."""
        for cell_id, cell in self._cells.items():
            if not self._sites_enabled.get(cell.config.area_id, True):
                continue
            for sensor_id, generator in cell.sensors.items():
                reading = generator.generate(cell.state)
                topic = f"{cell.config.area_id}/{cell_id}/_raw/process/{sensor_id}"
                self._mqtt.publish(
                    topic, reading, retain=False, required_level=ComplexityLevel.LEVEL_1_SENSORS
                )

    def _publish_machine_states(self) -> None:
        """Publish machine states (Level 2+)."""
        for cell_id, cell in self._cells.items():
            if not self._sites_enabled.get(cell.config.area_id, True):
                continue
            topic = f"{cell.config.area_id}/{cell_id}/_state"
            payload = {
                "state": cell.state.value,
                "sub_state": cell.sub_state.value,
                "job_id": cell.current_job.job_id if cell.current_job else None,
                "job_name": cell.current_job.job_name if cell.current_job else None,
                "operator_id": cell.operator_id,
                "since": cell.state_since.isoformat() + "Z",
                "cycle_count": cell.cycle_count,
                "parts_produced": cell.parts_produced,
                "parts_scrap": cell.parts_scrap,
                "_updated_at": datetime.now().isoformat() + "Z",
            }
            self._mqtt.publish(
                topic, payload, retain=True, required_level=ComplexityLevel.LEVEL_2_STATEFUL
            )

    def _publish_jobs(self) -> None:
        """Publish job tracking data (Level 2+)."""
        for job_id, job in self._jobs.items():
            if job.status in (JobStatus.IN_PROGRESS, JobStatus.QUEUED):
                topic = f"_jobs/active/{job_id}"
                self._mqtt.publish(
                    topic,
                    job.to_state_dict(),
                    retain=True,
                    required_level=ComplexityLevel.LEVEL_2_STATEFUL,
                )

    def _publish_erp_data(self) -> None:
        """Publish ERP enrichment data (Level 3+)."""
        for job_id, job in self._jobs.items():
            if job.status == JobStatus.IN_PROGRESS:
                topic = f"_erp/jobs/{job_id}"
                # Retain job ERP data for active jobs
                self._mqtt.publish(
                    topic, job.to_erp_dict(), retain=True, required_level=ComplexityLevel.LEVEL_3_ERP_MES
                )

        # Energy metrics (no retention - transient data)
        cells_data = [{"power_kw": c.sensors.get("power_kw", SensorGenerator("power_kw")).base_value} for c in self._cells.values()]
        topic = "_erp/energy"
        self._mqtt.publish(
            topic,
            self._erp_mes.generate_energy_metrics(cells_data),
            retain=False,
            required_level=ComplexityLevel.LEVEL_3_ERP_MES,
        )

    def _publish_mes_quality(self) -> None:
        """Publish MES quality data (Level 3+)."""
        for cell_id, cell in self._cells.items():
            if not self._sites_enabled.get(cell.config.area_id, True):
                continue
            topic = f"_mes/quality/{cell_id}"
            # Quality metrics don't need retention - transient aggregated data
            self._mqtt.publish(
                topic,
                self._erp_mes.generate_quality_metrics(cell_id),
                retain=False,
                required_level=ComplexityLevel.LEVEL_3_ERP_MES,
            )

    def _publish_oee(self) -> None:
        """Publish OEE metrics (Level 3+)."""
        for cell_id, cell in self._cells.items():
            if not self._sites_enabled.get(cell.config.area_id, True):
                continue
            topic = f"_mes/oee/{cell_id}"
            # OEE metrics don't need retention - calculated periodically
            self._mqtt.publish(
                topic,
                self._erp_mes.generate_oee_metrics(cell_id),
                retain=False,
                required_level=ComplexityLevel.LEVEL_3_ERP_MES,
            )

    def _publish_delivery_metrics(self) -> None:
        """Publish delivery performance (Level 3+)."""
        topic = "_erp/delivery"
        # Delivery metrics are aggregated data, no retention needed
        self._mqtt.publish(
            topic,
            self._erp_mes.generate_delivery_metrics(list(self._jobs.values())),
            retain=False,
            required_level=ComplexityLevel.LEVEL_3_ERP_MES,
        )

    def _publish_inventory(self) -> None:
        """Publish inventory/WIP metrics (Level 3+)."""
        topic = "_erp/inventory"
        # Inventory summary - no retention needed
        self._mqtt.publish(
            topic,
            self._erp_mes.generate_inventory_metrics(list(self._jobs.values())),
            retain=False,
            required_level=ComplexityLevel.LEVEL_3_ERP_MES,
        )

        # Machine utilization - no retention needed
        cells_states = {cid: c.state for cid, c in self._cells.items()}
        topic = "_mes/utilization"
        self._mqtt.publish(
            topic,
            self._erp_mes.generate_machine_utilization(cells_states),
            retain=False,
            required_level=ComplexityLevel.LEVEL_3_ERP_MES,
        )

    def _publish_dashboard(self) -> None:
        """Publish dashboard summary (Level 4)."""
        cells_states = {cid: c.state for cid, c in self._cells.items()}
        topic = "_dashboard/production"
        self._mqtt.publish(
            topic,
            self._erp_mes.generate_dashboard_summary(list(self._jobs.values()), cells_states),
            retain=True,
            required_level=ComplexityLevel.LEVEL_4_FULL,
        )

    def _publish_analytics(self) -> None:
        """Publish advanced analytics (Level 4)."""
        topic = "_analytics/quotes"
        # Analytics are periodic calculations, no retention needed
        self._mqtt.publish(
            topic,
            self._erp_mes.generate_quote_metrics(),
            retain=False,
            required_level=ComplexityLevel.LEVEL_4_FULL,
        )

    def _publish_random_event(self) -> None:
        """Publish a random event (Level 4)."""
        event_types = [
            ("MATERIAL_ARRIVED", "Material delivery received"),
            ("TOOL_CHANGE", "Scheduled tool change completed"),
            ("QUALITY_CHECK", "Quality inspection passed"),
            ("SHIFT_CHANGE", "Shift handover completed"),
            ("MAINTENANCE_DUE", "Preventive maintenance scheduled"),
        ]
        event_type, message = random.choice(event_types)

        enabled_cells = [
            cell_id
            for cell_id, cell in self._cells.items()
            if self._sites_enabled.get(cell.config.area_id, True)
        ]
        if not enabled_cells:
            return
        cell_id = random.choice(enabled_cells)

        topic = f"{self._cells[cell_id].config.area_id}/{cell_id}/_event"
        payload = {
            "event_type": event_type,
            "message": message,
            "cell_id": cell_id,
            "timestamp_ms": int(time.time() * 1000),
        }
        self._mqtt.publish(topic, payload, retain=False, required_level=ComplexityLevel.LEVEL_4_FULL)

    # =========================================================================
    # State update methods
    # =========================================================================

    def _update_machine_states(self) -> None:
        """Update machine states based on simulation logic."""
        for cell_id, cell in self._cells.items():
            if not self._sites_enabled.get(cell.config.area_id, True):
                continue
            if cell.config.cell_type == "agv":
                continue  # AGVs handled separately

            # State machine transitions
            if cell.state == PackMLState.IDLE:
                # Check if there's a job to process
                if cell.current_job is None:
                    job = self._get_next_job_for_cell(cell_id)
                    if job:
                        cell.current_job = job
                        cell.state = PackMLState.STARTING
                        cell.sub_state = MachineSubState.SETUP
                        cell.state_since = datetime.now()

            elif cell.state == PackMLState.STARTING:
                # Setup time (simplified: random 5-20 ticks)
                if (datetime.now() - cell.state_since).seconds > random.randint(5, 20):
                    cell.state = PackMLState.EXECUTE
                    cell.sub_state = self._get_sub_state_for_type(cell.config.cell_type)
                    cell.state_since = datetime.now()

            elif cell.state == PackMLState.EXECUTE:
                # Production - increment parts
                if random.random() < 0.3:  # 30% chance per tick to produce a part
                    cell.parts_produced += 1
                    cell.cycle_count += 1

                    # Scrap chance
                    if random.random() < 0.02:
                        cell.parts_scrap += 1

                    # Update job progress
                    if cell.current_job:
                        cell.current_job.qty_complete = cell.parts_produced
                        cell.current_job.qty_scrap = cell.parts_scrap
                        cell.current_job.actual_hours += 0.01

                        # Check if job complete at this cell
                        if cell.current_job.qty_complete >= cell.current_job.qty_target:
                            cell.state = PackMLState.COMPLETING
                            cell.state_since = datetime.now()

                # ISA-95/PackML realistic state transitions (more frequent pauses)
                rand_val = random.random()

                # Fault/alarm - HOLDING state (2% chance)
                if rand_val < 0.02:
                    cell.state = PackMLState.HOLDING
                    cell.sub_state = random.choice([
                        MachineSubState.FAULT_CLEARING,
                        MachineSubState.QUALITY_CHECK,
                        MachineSubState.WAITING_MATERIAL,
                        MachineSubState.WAITING_OPERATOR,
                    ])
                    cell.state_since = datetime.now()
                    logger.debug(f"{cell_id} entering HOLDING state: {cell.sub_state.value}")

                # Planned suspension - SUSPENDING state (1% chance)
                elif rand_val < 0.03:
                    cell.state = PackMLState.SUSPENDING
                    cell.sub_state = random.choice([
                        MachineSubState.TOOL_CHANGE,
                        MachineSubState.MAINTENANCE,
                        MachineSubState.SETUP,
                    ])
                    cell.state_since = datetime.now()
                    logger.debug(f"{cell_id} entering SUSPENDING state: {cell.sub_state.value}")

            elif cell.state == PackMLState.COMPLETING:
                if (datetime.now() - cell.state_since).seconds > 3:
                    cell.state = PackMLState.COMPLETED
                    cell.state_since = datetime.now()

            elif cell.state == PackMLState.COMPLETED:
                # Move job to next operation
                if cell.current_job:
                    self._advance_job(cell.current_job)
                cell.current_job = None
                cell.parts_produced = 0
                cell.parts_scrap = 0
                cell.state = PackMLState.RESETTING
                cell.state_since = datetime.now()

            elif cell.state == PackMLState.RESETTING:
                if (datetime.now() - cell.state_since).seconds > 2:
                    cell.state = PackMLState.IDLE
                    cell.sub_state = MachineSubState.NONE
                    cell.state_since = datetime.now()

            elif cell.state == PackMLState.HOLDING:
                # Auto-recover after some time (shorter holds = more state transitions)
                hold_duration = random.randint(5, 30)  # 5-30 seconds
                if (datetime.now() - cell.state_since).seconds > hold_duration:
                    cell.state = PackMLState.UNHOLDING
                    cell.state_since = datetime.now()
                    logger.debug(f"{cell_id} recovering from HOLDING → UNHOLDING")

            elif cell.state == PackMLState.UNHOLDING:
                if (datetime.now() - cell.state_since).seconds > 2:
                    cell.state = PackMLState.EXECUTE
                    cell.sub_state = self._get_sub_state_for_type(cell.config.cell_type)
                    cell.state_since = datetime.now()
                    logger.debug(f"{cell_id} resumed: UNHOLDING → EXECUTE")

            elif cell.state == PackMLState.SUSPENDING:
                # Transition to SUSPENDED after brief suspending period
                if (datetime.now() - cell.state_since).seconds > 3:
                    cell.state = PackMLState.SUSPENDED
                    cell.state_since = datetime.now()
                    logger.debug(f"{cell_id} now SUSPENDED")

            elif cell.state == PackMLState.SUSPENDED:
                # Resume after planned intervention (10-45 seconds)
                suspend_duration = random.randint(10, 45)
                if (datetime.now() - cell.state_since).seconds > suspend_duration:
                    cell.state = PackMLState.UNSUSPENDING
                    cell.state_since = datetime.now()
                    logger.debug(f"{cell_id} resuming from SUSPENDED → UNSUSPENDING")

            elif cell.state == PackMLState.UNSUSPENDING:
                # Quick transition back to EXECUTE
                if (datetime.now() - cell.state_since).seconds > 2:
                    cell.state = PackMLState.EXECUTE
                    cell.sub_state = self._get_sub_state_for_type(cell.config.cell_type)
                    cell.state_since = datetime.now()
                    logger.debug(f"{cell_id} back to production: UNSUSPENDING → EXECUTE")

    def _get_sub_state_for_type(self, cell_type: str) -> MachineSubState:
        """Get the appropriate sub-state for a cell type."""
        mapping = {
            "laser_cutter": MachineSubState.CUTTING,
            "press_brake": MachineSubState.BENDING,
            "robot_weld": MachineSubState.WELDING,
            "paint_booth": MachineSubState.PAINTING,
        }
        return mapping.get(cell_type, MachineSubState.NONE)

    def _update_jobs(self) -> None:
        """Update job states."""
        for job in list(self._jobs.values()):
            if job.status == JobStatus.CREATED:
                job.status = JobStatus.QUEUED

            # Clean up completed/shipped jobs
            if job.status == JobStatus.SHIPPED:
                if job.completed_at and (datetime.now() - job.completed_at).seconds > 300:
                    del self._jobs[job.job_id]

    def _update_agv(self) -> None:
        """Update AGV positions using waypoint system."""
        for agv_id, agv_pos in self._agv_positions.items():
            # Get target waypoint coordinates
            if agv_pos.target_waypoint in self._agv_waypoints:
                target_x, target_y, target_zone = self._agv_waypoints[agv_pos.target_waypoint]

                dx = target_x - agv_pos.x
                dy = target_y - agv_pos.y
                dist = (dx**2 + dy**2) ** 0.5

                # Update heading
                if dist > 0.1:
                    agv_pos.heading_deg = (math.atan2(dy, dx) * 180 / math.pi) % 360

                # State machine
                if agv_pos.status == "IDLE":
                    # Check battery - go to charging if low
                    if agv_pos.battery_pct < 25:
                        agv_pos.target_waypoint = "CHARGE_01"
                        agv_pos.path = f"{agv_pos.current_waypoint}→CHARGE_01"
                        agv_pos.status = "MOVING"
                        agv_pos.current_task = "RETURN_TO_CHARGE"
                    # Random chance to start new task
                    elif random.random() < 0.05:
                        # Pick random waypoint
                        new_target = random.choice(["A", "B", "C", "D", "E", "F"])
                        agv_pos.target_waypoint = new_target
                        agv_pos.path = f"{agv_pos.current_waypoint}→{new_target}"
                        agv_pos.status = "MOVING"
                        agv_pos.current_task = f"TRANSPORT_TO_{new_target}"
                        agv_pos.payload_kg = random.uniform(20, agv_pos.max_payload_kg * 0.8)

                elif agv_pos.status == "MOVING":
                    if dist > 0.5:
                        # Move towards target
                        speed = random.gauss(1.5, 0.2)  # 1.5 m/s avg speed
                        speed = max(0.5, min(2.0, speed))
                        agv_pos.speed_mps = speed

                        step = speed * 0.1  # Tick interval
                        agv_pos.x += (dx / dist) * step
                        agv_pos.y += (dy / dist) * step
                        agv_pos.distance_traveled_m += step

                        # Battery drain when moving
                        drain_rate = 0.02 if agv_pos.payload_kg > 0 else 0.01
                        agv_pos.battery_pct = max(0, agv_pos.battery_pct - drain_rate)

                        # Update zone as we move
                        agv_pos.zone = target_zone
                    else:
                        # Arrived at waypoint
                        agv_pos.x = target_x
                        agv_pos.y = target_y
                        agv_pos.current_waypoint = agv_pos.target_waypoint
                        agv_pos.zone = target_zone
                        agv_pos.speed_mps = 0.0

                        # Determine next state
                        if agv_pos.current_waypoint == "CHARGE_01":
                            agv_pos.status = "CHARGING"
                            agv_pos.is_charging = True
                            agv_pos.docking_station = "CHARGE_01"
                            agv_pos.current_task = "CHARGING"
                        elif agv_pos.current_waypoint.startswith("DOCK_"):
                            agv_pos.status = "DOCKED"
                            agv_pos.docking_station = agv_pos.current_waypoint
                            agv_pos.current_task = None
                        elif agv_pos.payload_kg > 0:
                            agv_pos.status = "UNLOADING"
                        else:
                            agv_pos.status = "LOADING"

                elif agv_pos.status == "CHARGING":
                    # Charge battery
                    agv_pos.battery_pct = min(100, agv_pos.battery_pct + 0.5)  # Fast charging
                    if agv_pos.battery_pct >= 95:
                        # Fully charged - pick new destination
                        agv_pos.is_charging = False
                        agv_pos.status = "IDLE"
                        agv_pos.docking_station = None
                        agv_pos.current_task = None
                        new_target = random.choice(["A", "B", "C", "D", "E"])
                        agv_pos.target_waypoint = new_target
                        agv_pos.path = f"CHARGE_01→{new_target}"

                elif agv_pos.status in ("LOADING", "UNLOADING"):
                    # Simulate loading/unloading for a few ticks
                    if random.random() < 0.2:  # 20% chance to finish per tick
                        if agv_pos.status == "LOADING":
                            agv_pos.payload_kg = random.uniform(20, agv_pos.max_payload_kg * 0.8)
                        else:
                            agv_pos.payload_kg = 0

                        # Pick next destination
                        agv_pos.status = "IDLE"
                        agv_pos.current_task = None

                elif agv_pos.status == "DOCKED":
                    # Idle at dock - random chance to start new task
                    if random.random() < 0.03:
                        new_target = random.choice(["A", "B", "C", "D", "E", "F"])
                        agv_pos.target_waypoint = new_target
                        agv_pos.path = f"{agv_pos.current_waypoint}→{new_target}"
                        agv_pos.status = "MOVING"
                        agv_pos.current_task = f"TRANSPORT_TO_{new_target}"
                        agv_pos.docking_station = None

    def _get_next_job_for_cell(self, cell_id: str) -> Optional[Job]:
        """Get the next queued job for a cell."""
        for job in self._jobs.values():
            if job.status == JobStatus.QUEUED:
                if job.current_operation_idx < len(job.routing):
                    if job.routing[job.current_operation_idx] == cell_id:
                        job.status = JobStatus.IN_PROGRESS
                        job.current_cell = cell_id
                        if not job.started_at:
                            job.started_at = datetime.now()

                        # Create Digital Product Passport when job starts (Level 4)
                        # Create DPP if this is the first operation AND we don't have one yet
                        if job.current_operation_idx == 0 and job.job_id not in self._digital_passports:
                            self._create_dpp_for_job(job)
                        return job
        return None

    def _advance_job(self, job: Job) -> None:
        """Advance a job to its next operation."""
        # Record operation completion for DPP (before advancing)
        if job.current_cell:
            cell = self._cells.get(job.current_cell)
            if cell:
                operation_duration = (datetime.now() - cell.state_since).seconds / 60.0
                self._record_operation_complete(
                    job=job,
                    cell_id=job.current_cell,
                    cell_type=cell.config.cell_type,
                    operator_id=cell.operator_id or "OP_UNKNOWN",
                    duration_minutes=operation_duration,
                    parts_produced=cell.parts_produced,
                    parts_scrap=cell.parts_scrap,
                )

        job.current_operation_idx += 1
        if job.current_operation_idx >= len(job.routing):
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now()
            job.current_cell = None
            # Finalize DPP
            self._finalize_dpp(job)
            # Auto-ship after completion
            job.status = JobStatus.SHIPPED
        else:
            job.status = JobStatus.QUEUED
            job.current_cell = None

    def _generate_initial_jobs(self) -> None:
        """Generate initial set of jobs."""
        for _ in range(5):
            job = self._job_generator.generate_job()
            self._jobs[job.job_id] = job
        logger.info(f"Generated {len(self._jobs)} initial jobs")

    def _generate_new_job(self) -> None:
        """Generate a new job."""
        if len(self._jobs) < 20:  # Cap at 20 active jobs
            job = self._job_generator.generate_job()
            self._jobs[job.job_id] = job
            logger.debug(f"Generated new job: {job.job_id}")

    # =========================================================================
    # New publishing methods for enhanced data
    # =========================================================================

    def _publish_solar_power(self) -> None:
        """Publish solar power generation data (Level 1+)."""
        # Per-array readings (historian data - no retention)
        for array in self._solar_gen.arrays:
            reading = self._solar_gen.generate_power_reading(array)
            topic = f"_raw/solar/{array.array_id}"
            self._mqtt.publish(
                topic, reading, retain=False, required_level=ComplexityLevel.LEVEL_1_SENSORS
            )

        # Facility-wide solar summary - no retention for energy metrics
        summary = self._solar_gen.generate_facility_solar_summary()
        topic = "_erp/energy/solar"
        self._mqtt.publish(
            topic, summary, retain=False, required_level=ComplexityLevel.LEVEL_1_SENSORS
        )

    def _publish_agv_positions(self) -> None:
        """Publish enhanced AGV position data (Level 2+)."""
        for agv_id, agv_pos in self._agv_positions.items():
            # Find the cell to get the area_id
            cell = self._cells.get(agv_id)
            if not cell:
                continue

            # Publish to the standard _state topic for the AGV cell
            topic = f"{cell.config.area_id}/{agv_id}/_state"
            self._mqtt.publish(
                topic, agv_pos.to_state_dict(), retain=True, required_level=ComplexityLevel.LEVEL_2_STATEFUL
            )

            # Also publish to aggregated topic for fleet view
            fleet_topic = f"_state/agv_fleet/{agv_id}"
            self._mqtt.publish(
                fleet_topic, agv_pos.to_state_dict(), retain=True, required_level=ComplexityLevel.LEVEL_2_STATEFUL
            )

    def _update_operators(self) -> None:
        """Update operator states based on time and simulation."""
        now = datetime.now()
        current_shift = (
            ShiftType.DAY if 6 <= now.hour < 14
            else ShiftType.EVENING if 14 <= now.hour < 22
            else ShiftType.NIGHT
        )

        for op in self._operator_gen.operators.values():
            # Clock in operators for current shift
            if op.shift == current_shift and op.status == OperatorStatus.CLOCKED_OUT:
                op.status = OperatorStatus.CLOCKED_IN
                op.clocked_in_at = now

            # Randomly put some operators at machines
            if op.status == OperatorStatus.CLOCKED_IN and random.random() < 0.3:
                op.status = OperatorStatus.AT_MACHINE
                # Assign to a random cell
                cell_ids = list(self._cells.keys())
                if cell_ids:
                    op.assigned_cell = random.choice(cell_ids)

            # Random breaks
            if op.status == OperatorStatus.AT_MACHINE and random.random() < 0.02:
                op.status = OperatorStatus.ON_BREAK
                op.break_start = now

            # End breaks
            if op.status == OperatorStatus.ON_BREAK and op.break_start:
                if (now - op.break_start).seconds > 900:  # 15 min break
                    op.status = OperatorStatus.AT_MACHINE
                    op.break_start = None

    def _publish_operator_attendance(self) -> None:
        """Publish operator attendance data (Level 2+)."""
        # Individual operator states
        for op_id, op in self._operator_gen.operators.items():
            if op.status in (OperatorStatus.CLOCKED_IN, OperatorStatus.AT_MACHINE, OperatorStatus.ON_BREAK):
                topic = f"_state/operators/{op_id}"
                self._mqtt.publish(
                    topic, op.to_state_dict(), retain=True, required_level=ComplexityLevel.LEVEL_2_STATEFUL
                )

        # Attendance summary (MES level) - no retention needed
        topic = "_mes/attendance"
        self._mqtt.publish(
            topic,
            self._operator_gen.generate_attendance_summary(),
            retain=False,
            required_level=ComplexityLevel.LEVEL_3_ERP_MES,
        )

    def _publish_raw_material_inventory(self) -> None:
        """Publish raw material inventory data (Level 3+)."""
        # Summary of low-stock items
        low_stock_items = []
        for item_num, item in self._inventory_gen.inventory.items():
            if item.available_quantity < item.minimum_stock:
                low_stock_items.append({
                    "item_number": item.item_number,
                    "description": item.item_description,
                    "available": item.available_quantity,
                    "minimum": item.minimum_stock,
                    "shortfall": item.minimum_stock - item.available_quantity,
                })

        # Inventory summary
        total_value = sum(i.available_quantity * i.unit_cost_eur for i in self._inventory_gen.inventory.values())
        summary = {
            "total_sku_count": len(self._inventory_gen.inventory),
            "total_value_eur": round(total_value, 2),
            "low_stock_count": len(low_stock_items),
            "low_stock_items": low_stock_items[:5],  # Top 5 low stock
            "timestamp_ms": int(time.time() * 1000),
        }

        topic = "_erp/inventory/raw_materials"
        # Raw material inventory summary - retain for reference
        self._mqtt.publish(
            topic, summary, retain=True, required_level=ComplexityLevel.LEVEL_3_ERP_MES
        )

        # Publish a few individual inventory items - retain for reference
        for item_num, item in list(self._inventory_gen.inventory.items())[:10]:
            topic = f"_erp/inventory/{item_num}"
            self._mqtt.publish(
                topic, item.to_erp_dict(), retain=True, required_level=ComplexityLevel.LEVEL_3_ERP_MES
            )

    def _check_shift_change(self) -> None:
        """Check for shift changes and publish events."""
        now = datetime.now()
        current_hour = now.hour

        # Check every hour
        if time.time() - self._shift_check_time < 3600:
            return

        self._shift_check_time = time.time()

        # Shift change hours
        if current_hour in (6, 14, 22):
            new_shift = (
                ShiftType.DAY if current_hour == 6
                else ShiftType.EVENING if current_hour == 14
                else ShiftType.NIGHT
            )

            # Publish shift change event
            topic = "_event/shift_change"
            payload = {
                "event_type": "SHIFT_CHANGE",
                "new_shift": new_shift.value,
                "message": f"Shift change to {new_shift.value} shift",
                "timestamp_ms": int(time.time() * 1000),
            }
            self._mqtt.publish(
                topic, payload, retain=False, required_level=ComplexityLevel.LEVEL_4_FULL
            )

            # Clock out previous shift, clock in new shift
            for op in self._operator_gen.operators.values():
                if op.shift != new_shift:
                    op.status = OperatorStatus.CLOCKED_OUT
                    op.assigned_cell = None
                elif op.shift == new_shift:
                    op.status = OperatorStatus.CLOCKED_IN
                    op.clocked_in_at = now

            logger.info(f"Shift change to {new_shift.value}")

    # =========================================================================
    # Digital Product Passport Methods (Level 4)
    # =========================================================================

    def _create_dpps_for_active_jobs(self) -> None:
        """Create DPPs for all jobs currently in progress (when switching to Level 4)."""
        features = get_features_for_level(self._level)
        if not features.dpp:
            return

        created_count = 0
        for job in self._jobs.values():
            if job.status == JobStatus.IN_PROGRESS and job.job_id not in self._digital_passports:
                self._create_dpp_for_job(job)
                created_count += 1

        if created_count > 0:
            logger.info(f"Created {created_count} DPPs for jobs already in progress")

    def _create_dpp_for_job(self, job: Job) -> None:
        """Create a Digital Product Passport when a job starts."""
        features = get_features_for_level(self._level)
        if not features.dpp:
            return

        # Extract material info from job
        material_code = getattr(job, "material", "DC01")
        thickness = getattr(job, "thickness", 2.0)

        # Create DPP
        dpp = self._dpp_generator.create_dpp_for_job(
            job_id=job.job_id,
            work_order=f"WO-2025-{random.randint(1000, 9999)}",
            product_name=job.job_name,
            customer=job.customer_name,
            material_code=material_code,
            thickness_mm=thickness,
            quantity=job.qty_target,
            site=self.config.uns.site.title(),
            country=self.config.uns.enterprise.upper(),
        )

        self._digital_passports[job.job_id] = dpp

        # Publish DPP creation event
        self._publish_dpp_event(dpp, DPPEventType.CREATED)

        # Publish DPP data
        self._publish_dpp(dpp)

        logger.info(f"Created DPP {dpp.dpp_id} for job {job.job_id}")

    def _record_operation_complete(self, job: Job, cell_id: str, cell_type: str,
                                   operator_id: str, duration_minutes: float,
                                   parts_produced: int, parts_scrap: int) -> None:
        """Record an operation completion in the DPP."""
        features = get_features_for_level(self._level)
        if not features.dpp or job.job_id not in self._digital_passports:
            return

        dpp = self._digital_passports[job.job_id]

        # Get cell to estimate energy consumption
        cell = self._cells.get(cell_id)
        if not cell:
            return

        # Estimate energy based on machine type and duration
        energy_kwh = self._estimate_operation_energy(cell_type, duration_minutes)

        # Map cell type to operation type
        operation_type = self._map_cell_to_operation(cell_type)

        # Get operator name
        operator = self._operator_gen.operators.get(operator_id)
        operator_name = operator.name if operator else operator_id

        # Create operation record
        operation = self._dpp_generator.create_operation_record(
            operation_type=operation_type,
            machine_id=cell_id,
            machine_type=cell_type,
            operator_id=operator_id,
            operator_name=operator_name,
            duration_minutes=duration_minutes,
            energy_kwh=energy_kwh,
            parts_produced=parts_produced,
            parts_scrap=parts_scrap,
        )

        dpp.add_operation(operation)

        # Randomly add quality check (30% chance)
        if random.random() < 0.3:
            check_type = random.choice(["DIMENSIONAL", "VISUAL", "FUNCTIONAL"])
            quality_check = self._dpp_generator.create_quality_check(check_type)
            dpp.add_quality_check(quality_check)

            self._publish_dpp_event(dpp, DPPEventType.QUALITY_CHECKED, {
                "check_id": quality_check.check_id,
                "check_type": check_type,
                "passed": quality_check.passed,
            })

        # Publish operation completion event
        self._publish_dpp_event(dpp, DPPEventType.OPERATION_COMPLETED, {
            "operation_type": operation_type,
            "machine_id": cell_id,
            "co2_kg": round(operation.co2_kg, 4),
        })

        # Update DPP data
        self._publish_dpp(dpp)

    def _finalize_dpp(self, job: Job) -> None:
        """Finalize DPP when job is complete."""
        features = get_features_for_level(self._level)
        if not features.dpp or job.job_id not in self._digital_passports:
            return

        dpp = self._digital_passports[job.job_id]
        dpp.finalize()

        # Simulate shipping
        transport_km = random.uniform(50, 500)  # 50-500 km
        transport_mode = random.choice(["TRUCK", "TRUCK", "RAIL"])  # Trucks more common
        dpp.ship(transport_km, transport_mode)

        # Publish finalized event
        self._publish_dpp_event(dpp, DPPEventType.FINALIZED)
        self._publish_dpp_event(dpp, DPPEventType.SHIPPED, {
            "transport_mode": transport_mode,
            "distance_km": round(transport_km, 1),
        })

        # Update DPP data
        self._publish_dpp(dpp)

        logger.info(f"Finalized DPP {dpp.dpp_id} - Total CO2: {dpp.carbon_footprint.total_co2_kg:.4f} kg")

    def _estimate_operation_energy(self, cell_type: str, duration_minutes: float) -> float:
        """Estimate energy consumption for an operation."""
        # Average power consumption by machine type (kW)
        power_ratings = {
            "laser_cutter": 25.0,
            "press_brake": 15.0,
            "robot_weld": 8.0,
            "powder_coating_line": 45.0,
            "assembly": 2.0,
            "agv": 1.5,
        }

        power_kw = power_ratings.get(cell_type, 10.0)
        energy_kwh = (power_kw * duration_minutes) / 60.0
        return energy_kwh

    def _map_cell_to_operation(self, cell_type: str) -> str:
        """Map cell type to DPP operation type."""
        mapping = {
            "laser_cutter": "LASER_CUTTING",
            "press_brake": "PRESS_FORMING",
            "robot_weld": "ROBOTIC_WELDING",
            "powder_coating_line": "POWDER_COATING",
            "assembly": "ASSEMBLY",
        }
        return mapping.get(cell_type, "PROCESSING")

    def _publish_dpp(self, dpp: DigitalProductPassport) -> None:
        """Publish DPP data to MQTT."""
        base = f"_dpp/passports/{dpp.dpp_id}"

        # Metadata (retained)
        self._mqtt.publish(
            f"{base}/metadata",
            dpp.to_metadata_dict(),
            retain=True,
            required_level=ComplexityLevel.LEVEL_4_FULL,
        )

        # Carbon footprint (retained)
        self._mqtt.publish(
            f"{base}/carbon_footprint",
            {**dpp.carbon_footprint.to_dict(), "material": dpp.material.to_dict()},
            retain=True,
            required_level=ComplexityLevel.LEVEL_4_FULL,
        )

        # Traceability (retained)
        self._mqtt.publish(
            f"{base}/traceability",
            dpp.to_traceability_dict(),
            retain=True,
            required_level=ComplexityLevel.LEVEL_4_FULL,
        )

        # Certifications (retained)
        self._mqtt.publish(
            f"{base}/certifications",
            dpp.to_certifications_dict(),
            retain=True,
            required_level=ComplexityLevel.LEVEL_4_FULL,
        )

        # Summary (retained)
        self._mqtt.publish(
            f"{base}/summary",
            dpp.to_summary_dict(),
            retain=True,
            required_level=ComplexityLevel.LEVEL_4_FULL,
        )

    def _publish_dpp_event(self, dpp: DigitalProductPassport, event_type: DPPEventType,
                          extra_data: Optional[Dict[str, Any]] = None) -> None:
        """Publish a DPP event notification (non-retained, for external subscribers)."""
        event_data = {
            "event_type": event_type.value,
            "dpp_id": dpp.dpp_id,
            "job_id": dpp.job_id,
            "product_name": dpp.product_name,
            "customer": dpp.customer,
            "status": dpp.status.value,
            "timestamp": datetime.now().isoformat() + "Z",
            "timestamp_ms": int(time.time() * 1000),
        }

        if extra_data:
            event_data.update(extra_data)

        # Publish to general events topic (external systems subscribe here)
        self._mqtt.publish(
            "_dpp/events",
            event_data,
            retain=False,  # Events are streaming, not retained
            required_level=ComplexityLevel.LEVEL_4_FULL,
        )

        # Also publish to event-specific topic
        event_name = event_type.value.lower()
        self._mqtt.publish(
            f"_dpp/events/{event_name}/{dpp.dpp_id}",
            event_data,
            retain=False,
            required_level=ComplexityLevel.LEVEL_4_FULL,
        )

    # =========================================================================
    # Powder Coating Line Methods
    # =========================================================================

    def _update_powder_coating_line(self) -> None:
        """Update powder coating line simulation."""
        completed = self._powder_coating_line.tick()

        # Handle completed traversals (parts done coating)
        for trav in completed:
            logger.debug(f"Traversal {trav.traversal_id} completed coating")

        # Random color change (roughly every 2-4 hours in real time)
        if random.random() < 0.001:
            new_color = random.choice(RAL_COLORS)
            self._powder_coating_line.change_color(new_color[0], new_color[1], new_color[2])
            logger.info(f"Color change to {new_color[0]} ({new_color[1]})")

    def _publish_powder_coating_state(self) -> None:
        """Publish powder coating line state data (Level 2+)."""
        line = self._powder_coating_line

        # Zone summary - overall line state
        topic = f"finishing/coating_line_01/_state/summary"
        self._mqtt.publish(
            topic, line.get_zone_summary(), retain=True, required_level=ComplexityLevel.LEVEL_2_STATEFUL
        )

        # Coating booth state (retained)
        topic = f"finishing/coating_line_01/_state/booth"
        self._mqtt.publish(
            topic, line.coating_booth.to_state_dict(), retain=True, required_level=ComplexityLevel.LEVEL_2_STATEFUL
        )

        # Booth sensor data (non-retained historian)
        topic = f"finishing/coating_line_01/_raw/booth"
        self._mqtt.publish(
            topic, line.coating_booth.to_sensor_dict(), retain=False, required_level=ComplexityLevel.LEVEL_1_SENSORS
        )

        # Drying oven state
        topic = f"finishing/coating_line_01/_state/drying_oven"
        self._mqtt.publish(
            topic, line.drying_oven.to_state_dict(), retain=True, required_level=ComplexityLevel.LEVEL_2_STATEFUL
        )

        # Drying oven sensor data
        topic = f"finishing/coating_line_01/_raw/drying_oven"
        self._mqtt.publish(
            topic, line.drying_oven.to_sensor_dict(), retain=False, required_level=ComplexityLevel.LEVEL_1_SENSORS
        )

        # Curing oven state
        topic = f"finishing/coating_line_01/_state/curing_oven"
        self._mqtt.publish(
            topic, line.curing_oven.to_state_dict(), retain=True, required_level=ComplexityLevel.LEVEL_2_STATEFUL
        )

        # Curing oven sensor data
        topic = f"finishing/coating_line_01/_raw/curing_oven"
        self._mqtt.publish(
            topic, line.curing_oven.to_sensor_dict(), retain=False, required_level=ComplexityLevel.LEVEL_1_SENSORS
        )

        # Individual traversal states (active work in progress)
        for trav_id, trav in line.traversals.items():
            topic = f"finishing/coating_line_01/_state/traversals/{trav_id}"
            self._mqtt.publish(
                topic, trav.to_state_dict(), retain=True, required_level=ComplexityLevel.LEVEL_2_STATEFUL
            )

    def _publish_powder_coating_metadata(self) -> None:
        """Publish powder coating line metadata (Level 2+)."""
        # Main metadata
        topic = f"finishing/coating_line_01/_meta/line"
        self._mqtt.publish(
            topic,
            self._powder_coating_line.to_meta_dict(),
            retain=True,
            required_level=ComplexityLevel.LEVEL_2_STATEFUL,
        )

        # Shared resource metadata (enterprise-level topic)
        shared_topic = "_meta/shared_resources/powder_coating"
        self._mqtt.publish(
            shared_topic,
            {
                "resource_type": "POWDER_COATING_LINE",
                "line_id": self._powder_coating_line.line_id,
                "location_facility": self._powder_coating_line.location,
                "location_area": "finishing",
                "shared_resource": True,
                "serves_facilities": list(self._powder_coating_line.facilities.keys()),
                "capacity_parts_per_day": 500,
                "available_colors": [{"ral_code": r[0], "ral_name": r[1], "hex": r[2]} for r in RAL_COLORS],
            },
            retain=True,
            required_level=ComplexityLevel.LEVEL_2_STATEFUL,
        )

    def _publish_powder_coating_planning(self) -> None:
        """Publish MES planning data for shared powder coating resource (Level 3+)."""
        line = self._powder_coating_line

        # Planning summary (shows orders from all facilities)
        topic = "finishing/coating_line_01/_mes/planning/summary"
        self._mqtt.publish(
            topic,
            line.get_planning_summary(),
            retain=True,
            required_level=ComplexityLevel.LEVEL_3_ERP_MES,
        )

        # Detailed order queue
        topic = "finishing/coating_line_01/_mes/planning/queue"
        self._mqtt.publish(
            topic,
            {"orders": line.get_order_queue(max_orders=15)},
            retain=False,  # Queue changes frequently
            required_level=ComplexityLevel.LEVEL_3_ERP_MES,
        )

        # Per-facility views
        for facility in line.facilities.keys():
            topic = f"finishing/coating_line_01/_mes/planning/facility/{facility}"
            self._mqtt.publish(
                topic,
                line.get_facility_orders(facility),
                retain=False,
                required_level=ComplexityLevel.LEVEL_3_ERP_MES,
            )

        # Enterprise-level shared resource planning view
        enterprise_topic = "_mes/shared_resources/powder_coating/planning"
        self._mqtt.publish(
            enterprise_topic,
            {
                "resource_id": line.line_id,
                "location": line.location,
                "summary": line.get_planning_summary(),
                "next_available_slot": (datetime.now() + timedelta(minutes=45)).isoformat() + "Z",
            },
            retain=True,
            required_level=ComplexityLevel.LEVEL_3_ERP_MES,
        )
