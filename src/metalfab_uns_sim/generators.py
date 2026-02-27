"""Data generators for sensors, jobs, ERP/MES data, and facility systems.

This module provides realistic data generation for a metalworking/sheet metal
fabrication facility, including:

- **Descriptive Namespace** (_meta): Asset metadata, OEM info, service dates
- **Functional Namespace** (_state, _raw, _erp, _mes): Real-time operations
- **Informative Namespace** (_dashboard): Aggregated data for consumers

ERP Integration follows Pattern A (On-Demand Fetch) from UMH docs:
When a triggering value changes, related data is fetched to populate UNS
with complete relational records.
"""

import math
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from faker import Faker

fake = Faker()
fake_nl = Faker("nl_NL")  # Dutch locale for realistic European names


# =============================================================================
# PackML State Machine (ISA-88/PackML compliant)
# =============================================================================


class PackMLState(Enum):
    """PackML unit/machine mode states."""

    # Stopped states
    STOPPED = "STOPPED"
    IDLE = "IDLE"

    # Acting states
    STARTING = "STARTING"
    EXECUTE = "EXECUTE"  # Main production state
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"

    # Dual states (can be commanded or automatic)
    RESETTING = "RESETTING"
    HOLDING = "HOLDING"
    HELD = "HELD"
    UNHOLDING = "UNHOLDING"
    SUSPENDING = "SUSPENDING"
    SUSPENDED = "SUSPENDED"
    UNSUSPENDING = "UNSUSPENDING"

    # Abort states
    ABORTING = "ABORTING"
    ABORTED = "ABORTED"
    CLEARING = "CLEARING"

    # Stopping states
    STOPPING = "STOPPING"


class MachineSubState(Enum):
    """Sub-states for detailed tracking."""

    NONE = "NONE"
    SETUP = "SETUP"
    CUTTING = "CUTTING"
    BENDING = "BENDING"
    WELDING = "WELDING"
    PAINTING = "PAINTING"
    CHANGEOVER = "CHANGEOVER"
    WAITING_MATERIAL = "WAITING_MATERIAL"
    WAITING_OPERATOR = "WAITING_OPERATOR"
    TOOL_CHANGE = "TOOL_CHANGE"
    QUALITY_CHECK = "QUALITY_CHECK"
    MAINTENANCE = "MAINTENANCE"
    FAULT_CLEARING = "FAULT_CLEARING"


class JobStatus(Enum):
    """Job lifecycle states."""

    CREATED = "CREATED"
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class JobPriority(Enum):
    """Job priority levels."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    RUSH = "RUSH"


class ShiftType(Enum):
    """Work shift types."""

    DAY = "DAY"  # 06:00 - 14:00
    EVENING = "EVENING"  # 14:00 - 22:00
    NIGHT = "NIGHT"  # 22:00 - 06:00


class OperatorRole(Enum):
    """Operator roles in the jobshop."""

    LASER_OPERATOR = "LASER_OPERATOR"
    PRESS_BRAKE_OPERATOR = "PRESS_BRAKE_OPERATOR"
    WELDER = "WELDER"
    PAINTER = "PAINTER"
    AGV_SUPERVISOR = "AGV_SUPERVISOR"
    QUALITY_INSPECTOR = "QUALITY_INSPECTOR"
    TEAM_LEAD = "TEAM_LEAD"
    MAINTENANCE_TECH = "MAINTENANCE_TECH"


class OperatorStatus(Enum):
    """Operator attendance status."""

    CLOCKED_IN = "CLOCKED_IN"
    ON_BREAK = "ON_BREAK"
    AT_MACHINE = "AT_MACHINE"
    CLOCKED_OUT = "CLOCKED_OUT"
    ABSENT = "ABSENT"
    SICK = "SICK"
    VACATION = "VACATION"


# =============================================================================
# Operator and Shift Management
# =============================================================================


@dataclass
class Operator:
    """Represents a shop floor operator/metalworker."""

    operator_id: str
    employee_number: str
    first_name: str
    last_name: str
    role: OperatorRole
    status: OperatorStatus = OperatorStatus.CLOCKED_OUT
    assigned_cell: Optional[str] = None
    current_job: Optional[str] = None
    shift: ShiftType = ShiftType.DAY
    clocked_in_at: Optional[datetime] = None
    break_start: Optional[datetime] = None
    certifications: List[str] = field(default_factory=list)
    efficiency_rating: float = 1.0  # 0.8-1.2 typical range
    years_experience: int = 0

    def to_state_dict(self) -> Dict[str, Any]:
        """Convert to state message for _state namespace."""
        return {
            "operator_id": self.operator_id,
            "employee_number": self.employee_number,
            "name": f"{self.first_name} {self.last_name}",
            "role": self.role.value,
            "status": self.status.value,
            "assigned_cell": self.assigned_cell,
            "current_job": self.current_job,
            "shift": self.shift.value,
            "clocked_in_at": self.clocked_in_at.isoformat() + "Z" if self.clocked_in_at else None,
            "_updated_at": datetime.now().isoformat() + "Z",
        }

    def to_meta_dict(self) -> Dict[str, Any]:
        """Convert to metadata for _meta namespace (descriptive)."""
        return {
            "operator_id": self.operator_id,
            "employee_number": self.employee_number,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "role": self.role.value,
            "certifications": self.certifications,
            "efficiency_rating": self.efficiency_rating,
            "years_experience": self.years_experience,
            "default_shift": self.shift.value,
        }


class OperatorGenerator:
    """Generates and manages operators for the jobshop."""

    # Realistic Dutch/European metalworker names
    FIRST_NAMES = ["Jan", "Pieter", "Marco", "Stefan", "Dennis", "Rob", "Henk", "Erik",
                   "Johan", "Bert", "Frank", "Marcel", "Tom", "Kees", "Wim", "Mark",
                   "Anna", "Linda", "Sandra", "Petra", "Kim", "Lisa", "Nicole", "Monique"]
    LAST_NAMES = ["de Vries", "Jansen", "van den Berg", "Bakker", "Visser", "Smit",
                  "Meijer", "de Groot", "Bos", "Vos", "Peters", "Hendriks", "van Dijk",
                  "Willems", "de Boer", "Dekker", "Mulder", "Claessen", "van Leeuwen"]

    def __init__(self, num_operators: int = 12):
        self.num_operators = num_operators
        self._operator_counter = 1000
        self.operators: Dict[str, Operator] = {}
        self._generate_initial_operators()

    def _generate_initial_operators(self) -> None:
        """Generate the initial operator pool."""
        # Define role distribution for a typical metalworking shop
        roles_distribution = [
            (OperatorRole.LASER_OPERATOR, 3),
            (OperatorRole.PRESS_BRAKE_OPERATOR, 3),
            (OperatorRole.WELDER, 2),
            (OperatorRole.PAINTER, 1),
            (OperatorRole.QUALITY_INSPECTOR, 1),
            (OperatorRole.TEAM_LEAD, 1),
            (OperatorRole.MAINTENANCE_TECH, 1),
        ]

        for role, count in roles_distribution:
            for _ in range(count):
                operator = self._create_operator(role)
                self.operators[operator.operator_id] = operator

    def _create_operator(self, role: OperatorRole) -> Operator:
        """Create a single operator."""
        self._operator_counter += 1
        first_name = random.choice(self.FIRST_NAMES)
        last_name = random.choice(self.LAST_NAMES)

        # Role-specific certifications
        certs = self._get_certifications_for_role(role)

        return Operator(
            operator_id=f"OP_{self._operator_counter}",
            employee_number=f"EMP{self._operator_counter}",
            first_name=first_name,
            last_name=last_name,
            role=role,
            certifications=certs,
            efficiency_rating=round(random.uniform(0.85, 1.15), 2),
            years_experience=random.randint(1, 25),
            shift=random.choice(list(ShiftType)),
        )

    def _get_certifications_for_role(self, role: OperatorRole) -> List[str]:
        """Get relevant certifications for a role."""
        certs_map = {
            OperatorRole.LASER_OPERATOR: ["TRUMPF TruLaser Certified", "Laser Safety Level 3"],
            OperatorRole.PRESS_BRAKE_OPERATOR: ["TRUMPF TruBend Certified", "Delem DA-69T"],
            OperatorRole.WELDER: ["MIG/MAG EN ISO 9606-1", "TIG Certified", "Robot Welding"],
            OperatorRole.PAINTER: ["Powder Coating Cert", "Wet Paint Cert"],
            OperatorRole.QUALITY_INSPECTOR: ["ISO 9001 Auditor", "CMM Operation", "Visual Inspection"],
            OperatorRole.TEAM_LEAD: ["Leadership Training", "Safety Officer"],
            OperatorRole.MAINTENANCE_TECH: ["Electrical Cert", "Hydraulics", "PLC Programming"],
        }
        return certs_map.get(role, [])

    def clock_in_shift(self, shift: ShiftType) -> List[Operator]:
        """Clock in all operators for a shift."""
        clocked_in = []
        for op in self.operators.values():
            if op.shift == shift:
                op.status = OperatorStatus.CLOCKED_IN
                op.clocked_in_at = datetime.now()
                clocked_in.append(op)
        return clocked_in

    def get_available_operators(self, role: Optional[OperatorRole] = None) -> List[Operator]:
        """Get operators available for work."""
        available = [
            op for op in self.operators.values()
            if op.status in (OperatorStatus.CLOCKED_IN, OperatorStatus.AT_MACHINE)
        ]
        if role:
            available = [op for op in available if op.role == role]
        return available

    def generate_attendance_summary(self) -> Dict[str, Any]:
        """Generate attendance summary for _mes namespace."""
        now = datetime.now()
        current_shift = (
            ShiftType.DAY if 6 <= now.hour < 14
            else ShiftType.EVENING if 14 <= now.hour < 22
            else ShiftType.NIGHT
        )

        present = [op for op in self.operators.values() if op.status in (
            OperatorStatus.CLOCKED_IN, OperatorStatus.AT_MACHINE, OperatorStatus.ON_BREAK
        )]
        absent = [op for op in self.operators.values() if op.status in (
            OperatorStatus.ABSENT, OperatorStatus.SICK, OperatorStatus.VACATION
        )]

        return {
            "current_shift": current_shift.value,
            "shift_start": datetime.now().replace(
                hour=6 if current_shift == ShiftType.DAY else 14 if current_shift == ShiftType.EVENING else 22,
                minute=0, second=0
            ).isoformat() + "Z",
            "operators_present": len(present),
            "operators_absent": len(absent),
            "operators_on_break": len([op for op in present if op.status == OperatorStatus.ON_BREAK]),
            "roles_staffed": {
                role.value: len([op for op in present if op.role == role])
                for role in OperatorRole
            },
            "attendance_rate_pct": round(len(present) / max(len(self.operators), 1) * 100, 1),
            "timestamp_ms": int(time.time() * 1000),
        }


# =============================================================================
# Solar Power Generation System
# =============================================================================


@dataclass
class SolarArray:
    """Represents a solar panel array on the facility roof."""

    array_id: str
    name: str
    capacity_kwp: float  # Peak capacity in kWp
    panel_count: int
    orientation: str  # "SOUTH", "SOUTH-EAST", etc.
    tilt_angle_deg: int
    install_date: datetime
    inverter_model: str

    def to_meta_dict(self) -> Dict[str, Any]:
        """Convert to metadata for _meta namespace."""
        return {
            "array_id": self.array_id,
            "name": self.name,
            "capacity_kwp": self.capacity_kwp,
            "panel_count": self.panel_count,
            "orientation": self.orientation,
            "tilt_angle_deg": self.tilt_angle_deg,
            "install_date": self.install_date.isoformat(),
            "inverter_model": self.inverter_model,
            "oem": "SolarEdge" if "SE" in self.inverter_model else "Fronius",
        }


class SolarGenerator:
    """Generates solar power production data."""

    def __init__(self, arrays: Optional[List[SolarArray]] = None):
        if arrays is None:
            # Default: typical medium-sized metalworking facility
            self.arrays = [
                SolarArray(
                    array_id="SOLAR_01",
                    name="Main Roof Array",
                    capacity_kwp=150.0,
                    panel_count=375,  # 400W panels
                    orientation="SOUTH",
                    tilt_angle_deg=15,
                    install_date=datetime(2022, 6, 15),
                    inverter_model="SE100K-RW00IBNN4",
                ),
                SolarArray(
                    array_id="SOLAR_02",
                    name="Warehouse Roof Array",
                    capacity_kwp=80.0,
                    panel_count=200,
                    orientation="SOUTH-WEST",
                    tilt_angle_deg=10,
                    install_date=datetime(2023, 3, 20),
                    inverter_model="Fronius Symo 20.0-3-M",
                ),
            ]
        else:
            self.arrays = arrays

        self._daily_production: Dict[str, float] = {a.array_id: 0.0 for a in self.arrays}
        self._last_reset = datetime.now().date()

    def _get_solar_intensity(self) -> float:
        """Calculate current solar intensity based on time of day and weather."""
        now = datetime.now()
        hour = now.hour + now.minute / 60

        # Solar curve: peaks at noon, zero at night
        if hour < 5 or hour > 21:
            return 0.0

        # Bell curve peaking at 12:30
        peak_hour = 12.5
        intensity = math.exp(-0.5 * ((hour - peak_hour) / 3.5) ** 2)

        # Add weather variability (cloud cover)
        weather_factor = random.gauss(0.85, 0.15)
        weather_factor = max(0.2, min(1.0, weather_factor))

        # Seasonal factor (lower in winter) - simplified
        month = now.month
        seasonal = 0.6 + 0.4 * math.sin((month - 3) * math.pi / 6)

        return intensity * weather_factor * seasonal

    def generate_power_reading(self, array: SolarArray) -> Dict[str, Any]:
        """Generate current power output for an array."""
        intensity = self._get_solar_intensity()
        current_power = array.capacity_kwp * intensity * random.uniform(0.9, 1.0)

        # Reset daily counter if new day
        if datetime.now().date() != self._last_reset:
            self._daily_production = {a.array_id: 0.0 for a in self.arrays}
            self._last_reset = datetime.now().date()

        # Accumulate daily production (assuming 1-second intervals)
        self._daily_production[array.array_id] += current_power / 3600  # kWh

        return {
            "array_id": array.array_id,
            "current_power_kw": round(current_power, 2),
            "capacity_kwp": array.capacity_kwp,
            "efficiency_pct": round(current_power / array.capacity_kwp * 100, 1) if array.capacity_kwp > 0 else 0,
            "daily_production_kwh": round(self._daily_production[array.array_id], 2),
            "timestamp_ms": int(time.time() * 1000),
        }

    def generate_facility_solar_summary(self) -> Dict[str, Any]:
        """Generate total solar production for _erp/energy namespace."""
        total_capacity = sum(a.capacity_kwp for a in self.arrays)
        intensity = self._get_solar_intensity()
        current_total = total_capacity * intensity * random.uniform(0.9, 1.0)
        daily_total = sum(self._daily_production.values())

        # Estimated monetary value (€0.08/kWh feed-in + savings)
        daily_value = daily_total * 0.12

        return {
            "total_capacity_kwp": total_capacity,
            "current_generation_kw": round(current_total, 2),
            "daily_generation_kwh": round(daily_total, 2),
            "daily_value_eur": round(daily_value, 2),
            "arrays_online": len(self.arrays),
            "solar_coverage_pct": round(min(current_total / 50 * 100, 100), 1),  # vs 50kW base load
            "co2_saved_kg": round(daily_total * 0.4, 1),  # ~0.4 kg CO2/kWh
            "timestamp_ms": int(time.time() * 1000),
        }


# =============================================================================
# ERP Production Order (Rich Data Model)
# =============================================================================


@dataclass
class ProductionOrder:
    """ERP Production Order following UMH ERP integration patterns.

    This models the complete relational record that would be fetched
    from an ERP system when OrderNumber changes (Pattern A: On-Demand Fetch).
    """

    # Core identifiers
    order_number: int
    order_id: str = field(default="")

    # Status and scheduling
    order_status: str = "PENDING"  # PENDING, RELEASED, IN_PROGRESS, COMPLETED, CLOSED
    scheduled_start_time: Optional[datetime] = None
    scheduled_end_time: Optional[datetime] = None
    actual_start_time: Optional[datetime] = None
    actual_end_time: Optional[datetime] = None

    # Quantities
    ordered_quantity: int = 0
    produced_quantity: int = 0
    remaining_quantity: int = 0
    scrap_quantity: int = 0

    # Item/Part reference
    item_number: str = ""
    item_description: str = ""
    material_spec: str = ""
    sheet_thickness_mm: float = 0.0

    # Customer and routing
    customer_id: str = ""
    customer_name: str = ""
    sales_order_number: str = ""
    routing_id: str = ""
    current_operation: int = 1
    total_operations: int = 1

    # Cost tracking
    estimated_hours: float = 0.0
    actual_hours: float = 0.0
    material_cost_eur: float = 0.0
    labor_cost_eur: float = 0.0
    quoted_price_eur: float = 0.0

    def __post_init__(self):
        if not self.order_id:
            self.order_id = f"PO_{self.order_number}"
        if not self.remaining_quantity:
            self.remaining_quantity = self.ordered_quantity - self.produced_quantity

    def to_erp_dict(self) -> Dict[str, Any]:
        """Convert to ERP namespace message following UMH conventions."""
        return {
            "order_number": self.order_number,
            "order_id": self.order_id,
            "order_status": self.order_status,
            "scheduled_start_time": self.scheduled_start_time.isoformat() + "Z" if self.scheduled_start_time else None,
            "scheduled_end_time": self.scheduled_end_time.isoformat() + "Z" if self.scheduled_end_time else None,
            "actual_start_time": self.actual_start_time.isoformat() + "Z" if self.actual_start_time else None,
            "actual_end_time": self.actual_end_time.isoformat() + "Z" if self.actual_end_time else None,
            "ordered_quantity": self.ordered_quantity,
            "produced_quantity": self.produced_quantity,
            "remaining_quantity": self.remaining_quantity,
            "scrap_quantity": self.scrap_quantity,
            "completion_pct": round(self.produced_quantity / max(self.ordered_quantity, 1) * 100, 1),
            "item_number": self.item_number,
            "item_description": self.item_description,
            "material_spec": self.material_spec,
            "sheet_thickness_mm": self.sheet_thickness_mm,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "sales_order_number": self.sales_order_number,
            "routing_id": self.routing_id,
            "current_operation": self.current_operation,
            "total_operations": self.total_operations,
            "estimated_hours": self.estimated_hours,
            "actual_hours": self.actual_hours,
            "est_vs_actual_hours": round(self.actual_hours - self.estimated_hours, 2),
            "material_cost_eur": self.material_cost_eur,
            "labor_cost_eur": self.labor_cost_eur,
            "total_cost_eur": round(self.material_cost_eur + self.labor_cost_eur, 2),
            "quoted_price_eur": self.quoted_price_eur,
            "margin_pct": round((self.quoted_price_eur - self.material_cost_eur - self.labor_cost_eur) / max(self.quoted_price_eur, 1) * 100, 1),
            "_updated_at": datetime.now().isoformat() + "Z",
        }


@dataclass
class InventoryItem:
    """ERP Inventory record following UMH patterns.

    Fetched when ItemNumber changes - provides complete inventory context.
    """

    item_number: str
    item_description: str
    bom: str = ""  # Bill of Materials reference
    material_type: str = ""  # DC01, S235JR, 1.4301, etc.
    thickness_mm: float = 0.0
    available_quantity: int = 0
    reserved_quantity: int = 0
    ordered_quantity: int = 0  # On order from supplier
    location: str = ""
    unit_cost_eur: float = 0.0
    last_receipt_date: Optional[datetime] = None
    minimum_stock: int = 0
    supplier: str = ""

    def to_erp_dict(self) -> Dict[str, Any]:
        """Convert to ERP/Inventory namespace message."""
        return {
            "item_number": self.item_number,
            "item_description": self.item_description,
            "bom": self.bom,
            "material_type": self.material_type,
            "thickness_mm": self.thickness_mm,
            "available_quantity": self.available_quantity,
            "reserved_quantity": self.reserved_quantity,
            "ordered_quantity": self.ordered_quantity,
            "free_stock": max(0, self.available_quantity - self.reserved_quantity),
            "location": self.location,
            "unit_cost_eur": self.unit_cost_eur,
            "total_value_eur": round(self.available_quantity * self.unit_cost_eur, 2),
            "last_receipt_date": self.last_receipt_date.isoformat() if self.last_receipt_date else None,
            "minimum_stock": self.minimum_stock,
            "reorder_needed": self.available_quantity < self.minimum_stock,
            "supplier": self.supplier,
            "_updated_at": datetime.now().isoformat() + "Z",
        }


class ProductionOrderGenerator:
    """Generates realistic production orders for a metalworking facility."""

    # Typical sheet metal parts and materials
    PART_TEMPLATES = [
        {"name": "Bracket Assembly", "ops": 3, "material": "DC01", "thickness": 2.0},
        {"name": "Enclosure Panel", "ops": 4, "material": "1.4301", "thickness": 1.5},
        {"name": "Support Frame", "ops": 5, "material": "S235JR", "thickness": 3.0},
        {"name": "Cover Plate", "ops": 2, "material": "DC01", "thickness": 1.0},
        {"name": "Mounting Flange", "ops": 3, "material": "S355", "thickness": 4.0},
        {"name": "Cable Tray Section", "ops": 4, "material": "DX51D+Z", "thickness": 1.25},
        {"name": "Machine Guard", "ops": 3, "material": "DC01", "thickness": 2.0},
        {"name": "Control Panel Housing", "ops": 6, "material": "1.4301", "thickness": 1.5},
        {"name": "Heat Shield", "ops": 2, "material": "1.4828", "thickness": 2.0},
        {"name": "Conveyor Side Rail", "ops": 4, "material": "S235JR", "thickness": 3.0},
    ]

    CUSTOMERS = [
        ("CUST001", "Bosch Rexroth"),
        ("CUST002", "Siemens AG"),
        ("CUST003", "Festo"),
        ("CUST004", "Atlas Copco"),
        ("CUST005", "Vanderlande"),
        ("CUST006", "ASML"),
        ("CUST007", "Philips"),
        ("CUST008", "DAF Trucks"),
        ("CUST009", "VDL Groep"),
        ("CUST010", "Marel"),
    ]

    def __init__(self):
        self._order_counter = 7400

    def generate_order(self) -> ProductionOrder:
        """Generate a new production order."""
        self._order_counter += 1
        template = random.choice(self.PART_TEMPLATES)
        customer_id, customer_name = random.choice(self.CUSTOMERS)

        qty = random.randint(25, 500)
        est_hours = qty * random.uniform(0.02, 0.08)
        material_cost = qty * random.uniform(1.5, 8.0)
        labor_cost = est_hours * 55.0  # €55/hour labor rate
        margin = random.uniform(0.25, 0.40)
        quoted = (material_cost + labor_cost) / (1 - margin)

        now = datetime.now()
        sched_start = now + timedelta(days=random.randint(1, 5))
        sched_end = sched_start + timedelta(hours=est_hours * 1.2)

        return ProductionOrder(
            order_number=self._order_counter,
            order_status="RELEASED",
            scheduled_start_time=sched_start,
            scheduled_end_time=sched_end,
            ordered_quantity=qty,
            item_number=f"PN-{random.randint(10000, 99999)}",
            item_description=f"{template['name']} {random.randint(100, 999)}",
            material_spec=template["material"],
            sheet_thickness_mm=template["thickness"],
            customer_id=customer_id,
            customer_name=customer_name,
            sales_order_number=f"SO-{random.randint(50000, 59999)}",
            routing_id=f"RTG-{random.randint(100, 999)}",
            total_operations=template["ops"],
            estimated_hours=round(est_hours, 1),
            material_cost_eur=round(material_cost, 2),
            labor_cost_eur=round(labor_cost, 2),
            quoted_price_eur=round(quoted, 2),
        )


class InventoryGenerator:
    """Generates inventory data for raw materials."""

    MATERIALS = [
        ("DC01", "Cold rolled steel", [0.8, 1.0, 1.5, 2.0, 3.0]),
        ("S235JR", "Structural steel", [2.0, 3.0, 4.0, 5.0, 6.0]),
        ("S355", "High strength steel", [3.0, 4.0, 5.0, 6.0, 8.0]),
        ("1.4301", "Stainless 304", [1.0, 1.5, 2.0, 3.0]),
        ("1.4404", "Stainless 316L", [1.5, 2.0, 3.0]),
        ("DX51D+Z", "Galvanized steel", [0.8, 1.0, 1.25, 1.5]),
        ("5754-H22", "Aluminum alloy", [1.5, 2.0, 3.0]),
    ]

    SUPPLIERS = ["ThyssenKrupp", "ArcelorMittal", "SSAB", "Outokumpu", "Aleris"]
    LOCATIONS = ["Warehouse A", "Warehouse B", "Production Floor", "Receiving Dock"]

    def __init__(self):
        self.inventory: Dict[str, InventoryItem] = {}
        self._generate_initial_inventory()

    def _generate_initial_inventory(self) -> None:
        """Generate initial inventory stock."""
        for material_code, description, thicknesses in self.MATERIALS:
            for thickness in thicknesses:
                item_num = f"MAT-{material_code}-{int(thickness*10):02d}"
                self.inventory[item_num] = InventoryItem(
                    item_number=item_num,
                    item_description=f"{description} {thickness}mm",
                    material_type=material_code,
                    thickness_mm=thickness,
                    available_quantity=random.randint(50, 500),
                    reserved_quantity=random.randint(0, 50),
                    ordered_quantity=random.randint(0, 200) if random.random() > 0.7 else 0,
                    location=random.choice(self.LOCATIONS),
                    unit_cost_eur=round(random.uniform(5, 50) * thickness, 2),
                    last_receipt_date=datetime.now() - timedelta(days=random.randint(1, 30)),
                    minimum_stock=random.randint(20, 100),
                    supplier=random.choice(self.SUPPLIERS),
                )


# =============================================================================
# Asset Metadata (Descriptive Namespace)
# =============================================================================


@dataclass
class AssetMetadata:
    """Descriptive metadata for a production asset (machine/cell).

    This is relatively static data that describes the asset - OEM info,
    installation date, capabilities, etc. Published to _meta namespace.
    """

    asset_id: str
    asset_name: str
    asset_type: str
    oem: str
    model: str
    serial_number: str
    install_date: datetime
    last_service_date: Optional[datetime] = None
    next_service_date: Optional[datetime] = None
    location: str = ""
    area: str = ""
    ip_address: Optional[str] = None
    capabilities: List[str] = field(default_factory=list)
    max_sheet_size_mm: Tuple[float, float] = (0, 0)
    max_thickness_mm: float = 0.0

    def to_meta_dict(self) -> Dict[str, Any]:
        """Convert to _meta namespace message."""
        return {
            "asset_id": self.asset_id,
            "asset_name": self.asset_name,
            "asset_type": self.asset_type,
            "oem": self.oem,
            "model": self.model,
            "serial_number": self.serial_number,
            "install_date": self.install_date.isoformat(),
            "last_service_date": self.last_service_date.isoformat() if self.last_service_date else None,
            "next_service_date": self.next_service_date.isoformat() if self.next_service_date else None,
            "service_status": self._get_service_status(),
            "location": self.location,
            "area": self.area,
            "ip_address": self.ip_address,
            "capabilities": self.capabilities,
            "max_sheet_size_mm": {"x": self.max_sheet_size_mm[0], "y": self.max_sheet_size_mm[1]},
            "max_thickness_mm": self.max_thickness_mm,
            "operational_years": round((datetime.now() - self.install_date).days / 365.25, 1),
        }

    def _get_service_status(self) -> str:
        """Determine service status."""
        if not self.next_service_date:
            return "UNKNOWN"
        days_until = (self.next_service_date - datetime.now()).days
        if days_until < 0:
            return "OVERDUE"
        elif days_until < 30:
            return "DUE_SOON"
        return "OK"


def create_asset_metadata(cell_id: str, cell_type: str) -> AssetMetadata:
    """Create asset metadata for a cell."""
    # OEM and model mapping
    oem_models = {
        "laser_cutter": [
            ("TRUMPF", "TruLaser 3030 fiber", ["fiber_laser", "2D_cutting", "nitrogen_assist"]),
            ("TRUMPF", "TruLaser 5030 fiber", ["fiber_laser", "2D_cutting", "bevel_cutting"]),
            ("Bystronic", "ByStar Fiber 3015", ["fiber_laser", "2D_cutting", "automation"]),
        ],
        "press_brake": [
            ("TRUMPF", "TruBend 5130", ["bending", "angle_sensor", "6_axis"]),
            ("TRUMPF", "TruBend 7036", ["bending", "electric_drive", "compact"]),
            ("Bystronic", "Xpert 150", ["bending", "crowning", "multi_axis"]),
        ],
        "robot_weld": [
            ("KUKA", "KR 16 R1610-2", ["MIG_MAG", "6_axis", "arc_welding"]),
            ("ABB", "IRB 1600", ["MIG_MAG", "TIG", "spot_welding"]),
            ("Fronius", "TPS 500i CMT", ["CMT", "pulse", "low_spatter"]),
        ],
        "paint_booth": [
            ("Wagner", "PrimaSprint", ["powder_coating", "automatic", "color_change"]),
            ("Gema", "OptiCenter", ["powder_coating", "dense_phase", "recovery"]),
        ],
        "agv": [
            ("STILL", "EXV-SF 14", ["forklift", "autonomous", "1400kg"]),
            ("Jungheinrich", "EKS 215a", ["vertical_order_picker", "semi_auto"]),
        ],
    }

    sheet_sizes = {
        "laser_cutter": (3000, 1500),
        "press_brake": (3000, 100),
        "robot_weld": (2000, 1500),
        "paint_booth": (4000, 2000),
        "agv": (0, 0),
    }

    max_thickness = {
        "laser_cutter": 25.0,
        "press_brake": 12.0,
        "robot_weld": 8.0,
        "paint_booth": 0,
        "agv": 0,
    }

    choices = oem_models.get(cell_type, [("Generic", "Model X", [])])
    oem, model, caps = random.choice(choices)

    install_date = datetime.now() - timedelta(days=random.randint(365, 2500))
    last_service = datetime.now() - timedelta(days=random.randint(30, 180))

    return AssetMetadata(
        asset_id=cell_id,
        asset_name=f"{oem} {model}",
        asset_type=cell_type,
        oem=oem,
        model=model,
        serial_number=f"SN{random.randint(100000, 999999)}",
        install_date=install_date,
        last_service_date=last_service,
        next_service_date=last_service + timedelta(days=180),
        location="Production Hall 1",
        area="cutting" if "laser" in cell_type else "forming" if "press" in cell_type else "assembly",
        ip_address=f"192.168.1.{random.randint(10, 250)}",
        capabilities=caps,
        max_sheet_size_mm=sheet_sizes.get(cell_type, (0, 0)),
        max_thickness_mm=max_thickness.get(cell_type, 0),
    )


# =============================================================================
# AGV Position Tracking (Enhanced)
# =============================================================================


@dataclass
class AGVPosition:
    """Enhanced AGV position with rich state data.

    Tracks AGV movement through named waypoints (A-F) and docking stations.
    """

    agv_id: str
    x: float  # meters from origin
    y: float
    heading_deg: float  # 0-360
    current_waypoint: str  # "A", "B", "C", "D", "E", "F", "DOCK_01", "CHARGE_01"
    target_waypoint: str  # Target waypoint
    path: str  # "A→D", "D→CHARGE_01", etc.
    zone: str  # "WAREHOUSE", "LASER_AREA", "BENDING_AREA", etc.
    status: str  # "MOVING", "LOADING", "UNLOADING", "CHARGING", "DOCKED", "IDLE", "WAITING"
    battery_pct: float
    current_task: Optional[str] = None
    payload_kg: float = 0.0
    max_payload_kg: float = 250.0
    speed_mps: float = 0.0
    distance_traveled_m: float = 0.0
    docking_station: Optional[str] = None  # "DOCK_01", "DOCK_02", "CHARGE_01"
    is_charging: bool = False
    error_code: Optional[str] = None

    def to_state_dict(self) -> Dict[str, Any]:
        """Convert to state message for _state namespace."""
        return {
            "agv_id": self.agv_id,
            "position": {"x": round(self.x, 2), "y": round(self.y, 2)},
            "heading_deg": round(self.heading_deg, 1),

            # Waypoint tracking
            "current_waypoint": self.current_waypoint,
            "target_waypoint": self.target_waypoint,
            "path": self.path,
            "zone": self.zone,

            # Status
            "status": self.status,
            "battery_pct": round(self.battery_pct, 1),
            "is_charging": self.is_charging,
            "docking_station": self.docking_station,

            # Task and payload
            "current_task": self.current_task,
            "payload_kg": round(self.payload_kg, 1),
            "payload_pct": round(self.payload_kg / self.max_payload_kg * 100, 1) if self.max_payload_kg > 0 else 0,
            "max_payload_kg": self.max_payload_kg,

            # Movement
            "speed_mps": round(self.speed_mps, 2),
            "distance_traveled_m": round(self.distance_traveled_m, 1),

            # Diagnostics
            "error_code": self.error_code,

            "_updated_at": datetime.now().isoformat() + "Z",
        }


# =============================================================================
# Powder Coating Line Simulation (Realistic)
# =============================================================================


class PowderCoatingZone(Enum):
    """Zones in a powder coating line."""

    LOADING = "LOADING"  # Parts hung on traversals
    PRE_TREATMENT = "PRE_TREATMENT"  # Wash/phosphate
    DRYING_OVEN = "DRYING_OVEN"  # Pre-dry before coating
    COATING_BOOTH = "COATING_BOOTH"  # Powder application
    CURING_OVEN = "CURING_OVEN"  # Cure at ~180-200°C
    COOLING = "COOLING"  # Cool down zone
    UNLOADING = "UNLOADING"  # Parts removed from traversals


# Standard RAL colors used in sheet metal industry
RAL_COLORS = [
    ("RAL 9005", "Jet Black", "#0A0A0A"),
    ("RAL 9016", "Traffic White", "#F7F7F7"),
    ("RAL 7035", "Light Grey", "#C5C7C4"),
    ("RAL 7016", "Anthracite Grey", "#383E42"),
    ("RAL 5010", "Gentian Blue", "#0E4C8E"),
    ("RAL 3000", "Flame Red", "#A72920"),
    ("RAL 1023", "Traffic Yellow", "#F0CA00"),
    ("RAL 6005", "Moss Green", "#0F4336"),
    ("RAL 2004", "Pure Orange", "#E25303"),
    ("RAL 9006", "White Aluminium", "#A1A1A0"),
]


@dataclass
class CoatingOrder:
    """An order for powder coating from a facility."""

    order_id: str
    source_facility: str  # "eindhoven", "roeselare", "brasov"
    source_site_name: str  # "MetalFab Eindhoven HQ"
    job_id: str
    customer: str
    part_description: str
    part_count: int
    ral_code: str
    ral_name: str
    ral_hex: str
    priority: int = 5  # 1=urgent, 5=normal, 10=low
    requested_date: Optional[datetime] = None
    scheduled_date: Optional[datetime] = None
    estimated_duration_min: float = 0.0  # Total line time
    status: str = "QUEUED"  # QUEUED, SCHEDULED, LOADING, IN_PROGRESS, COMPLETED
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_planning_dict(self) -> Dict[str, Any]:
        """Convert to MES planning message."""
        return {
            "order_id": self.order_id,
            "source_facility": self.source_facility,
            "source_site_name": self.source_site_name,
            "job_id": self.job_id,
            "customer": self.customer,
            "part_description": self.part_description,
            "part_count": self.part_count,
            "ral_code": self.ral_code,
            "ral_name": self.ral_name,
            "ral_hex": self.ral_hex,
            "priority": self.priority,
            "status": self.status,
            "requested_date": self.requested_date.isoformat() + "Z" if self.requested_date else None,
            "scheduled_date": self.scheduled_date.isoformat() + "Z" if self.scheduled_date else None,
            "estimated_duration_min": round(self.estimated_duration_min, 1),
            "created_at": self.created_at.isoformat() + "Z",
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,
            "completed_at": self.completed_at.isoformat() + "Z" if self.completed_at else None,
        }


@dataclass
class Traversal:
    """A traversal (batch of parts on hangers) moving through the coating line."""

    traversal_id: str
    coating_order: CoatingOrder
    job_id: str
    part_count: int
    current_zone: PowderCoatingZone
    zone_entered_at: datetime
    ral_code: str
    ral_name: str
    total_weight_kg: float = 0.0
    hanger_count: int = 1

    def time_in_zone_seconds(self) -> float:
        """Calculate time spent in current zone."""
        return (datetime.now() - self.zone_entered_at).total_seconds()

    def time_in_zone_formatted(self) -> str:
        """Human readable time in zone."""
        secs = self.time_in_zone_seconds()
        if secs < 60:
            return f"{int(secs)}s"
        elif secs < 3600:
            return f"{int(secs / 60)}m {int(secs % 60)}s"
        else:
            return f"{secs / 3600:.1f}h"

    def to_state_dict(self) -> Dict[str, Any]:
        """Convert to state message."""
        return {
            "traversal_id": self.traversal_id,
            "job_id": self.job_id,
            "source_facility": self.coating_order.source_facility,
            "source_site_name": self.coating_order.source_site_name,
            "customer": self.coating_order.customer,
            "part_count": self.part_count,
            "hanger_count": self.hanger_count,
            "current_zone": self.current_zone.value,
            "zone_entered_at": self.zone_entered_at.isoformat() + "Z",
            "time_in_zone": self.time_in_zone_formatted(),
            "time_in_zone_seconds": round(self.time_in_zone_seconds(), 0),
            "ral_code": self.ral_code,
            "ral_name": self.ral_name,
            "total_weight_kg": round(self.total_weight_kg, 1),
            "_updated_at": datetime.now().isoformat() + "Z",
        }


@dataclass
class CoatingBoothState:
    """State of the powder coating booth."""

    booth_id: str
    current_ral_code: str
    current_ral_name: str
    current_ral_hex: str
    last_color_change: datetime
    color_change_count_today: int = 0
    powder_level_pct: float = 85.0
    recovery_efficiency_pct: float = 95.0
    booth_temp_c: float = 22.0
    humidity_pct: float = 45.0
    gun_count: int = 12
    guns_active: int = 12
    electrostatic_kv: float = 80.0
    air_pressure_bar: float = 4.0

    def time_since_color_change(self) -> str:
        """Human readable time since last color change."""
        delta = datetime.now() - self.last_color_change
        hours = delta.total_seconds() / 3600
        if hours < 1:
            return f"{int(delta.total_seconds() / 60)}m"
        elif hours < 24:
            return f"{hours:.1f}h"
        else:
            return f"{hours / 24:.1f}d"

    def to_state_dict(self) -> Dict[str, Any]:
        """Convert to stateful message for _state namespace."""
        return {
            "booth_id": self.booth_id,
            "current_color": {
                "ral_code": self.current_ral_code,
                "ral_name": self.current_ral_name,
                "hex": self.current_ral_hex,
            },
            "last_color_change": self.last_color_change.isoformat() + "Z",
            "time_since_color_change": self.time_since_color_change(),
            "color_change_count_today": self.color_change_count_today,
            "powder_level_pct": round(self.powder_level_pct, 1),
            "recovery_efficiency_pct": round(self.recovery_efficiency_pct, 1),
            "guns_active": self.guns_active,
            "guns_total": self.gun_count,
            "_updated_at": datetime.now().isoformat() + "Z",
        }

    def to_sensor_dict(self) -> Dict[str, Any]:
        """Convert to sensor readings for _raw namespace."""
        return {
            "booth_temp_c": round(self.booth_temp_c + random.gauss(0, 0.5), 1),
            "humidity_pct": round(self.humidity_pct + random.gauss(0, 2), 1),
            "electrostatic_kv": round(self.electrostatic_kv + random.gauss(0, 1), 1),
            "air_pressure_bar": round(self.air_pressure_bar + random.gauss(0, 0.1), 2),
            "powder_flow_gpm": round(random.uniform(150, 200), 1),
            "timestamp_ms": int(time.time() * 1000),
        }


@dataclass
class OvenState:
    """State of a curing/drying oven."""

    oven_id: str
    oven_type: str  # "DRYING" or "CURING"
    setpoint_temp_c: float
    internal_temp_c: float
    external_temp_c: float
    zone_temps_c: List[float] = field(default_factory=list)  # Multiple zones in oven
    conveyor_speed_mpm: float = 2.0
    exhaust_temp_c: float = 0.0
    gas_consumption_m3h: float = 0.0
    traversals_inside: int = 0
    max_capacity: int = 10
    dwell_time_min: float = 20.0

    def to_state_dict(self) -> Dict[str, Any]:
        """Convert to stateful message."""
        return {
            "oven_id": self.oven_id,
            "oven_type": self.oven_type,
            "setpoint_temp_c": self.setpoint_temp_c,
            "traversals_inside": self.traversals_inside,
            "max_capacity": self.max_capacity,
            "utilization_pct": round(self.traversals_inside / max(self.max_capacity, 1) * 100, 1),
            "conveyor_speed_mpm": round(self.conveyor_speed_mpm, 2),
            "dwell_time_min": self.dwell_time_min,
            "_updated_at": datetime.now().isoformat() + "Z",
        }

    def to_sensor_dict(self) -> Dict[str, Any]:
        """Convert to sensor readings for _raw namespace."""
        # Simulate zone temperatures with slight variation
        zone_temps = [
            round(self.internal_temp_c + random.gauss(0, 2), 1)
            for _ in range(3)
        ]
        return {
            "setpoint_temp_c": self.setpoint_temp_c,
            "internal_temp_c": round(self.internal_temp_c + random.gauss(0, 1), 1),
            "external_temp_c": round(self.external_temp_c + random.gauss(0, 0.5), 1),
            "zone_1_temp_c": zone_temps[0],
            "zone_2_temp_c": zone_temps[1],
            "zone_3_temp_c": zone_temps[2],
            "exhaust_temp_c": round(self.internal_temp_c * 0.6 + random.gauss(0, 2), 1),
            "gas_consumption_m3h": round(self.gas_consumption_m3h + random.gauss(0, 0.5), 2),
            "conveyor_speed_mpm": round(self.conveyor_speed_mpm + random.gauss(0, 0.05), 2),
            "timestamp_ms": int(time.time() * 1000),
        }


class PowderCoatingLine:
    """Simulates a complete powder coating line with zones and traversals.

    Zones in order:
    1. LOADING - Parts hung on hangers/traversals
    2. PRE_TREATMENT - Wash, phosphate, rinse
    3. DRYING_OVEN - Dry parts before coating (~120°C)
    4. COATING_BOOTH - Powder application
    5. CURING_OVEN - Cure powder (~180-200°C, 15-20 min)
    6. COOLING - Cool down zone
    7. UNLOADING - Parts removed
    """

    ZONE_ORDER = [
        PowderCoatingZone.LOADING,
        PowderCoatingZone.PRE_TREATMENT,
        PowderCoatingZone.DRYING_OVEN,
        PowderCoatingZone.COATING_BOOTH,
        PowderCoatingZone.CURING_OVEN,
        PowderCoatingZone.COOLING,
        PowderCoatingZone.UNLOADING,
    ]

    # Typical dwell times in seconds per zone
    ZONE_DWELL_TIMES = {
        PowderCoatingZone.LOADING: 60,
        PowderCoatingZone.PRE_TREATMENT: 300,  # 5 min wash cycle
        PowderCoatingZone.DRYING_OVEN: 600,  # 10 min drying
        PowderCoatingZone.COATING_BOOTH: 120,  # 2 min coating
        PowderCoatingZone.CURING_OVEN: 1200,  # 20 min curing
        PowderCoatingZone.COOLING: 300,  # 5 min cooling
        PowderCoatingZone.UNLOADING: 60,
    }

    def __init__(self, line_id: str = "COAT_LINE_01", location: str = "eindhoven"):
        self.line_id = line_id
        self.location = location  # Shared resource location
        self._traversal_counter = 1000
        self._order_counter = 5000

        # Current RAL color
        ral = random.choice(RAL_COLORS)
        self.current_ral_code = ral[0]
        self.current_ral_name = ral[1]
        self.current_ral_hex = ral[2]

        # Traversals currently in the line
        self.traversals: Dict[str, Traversal] = {}

        # MES Planning System
        self.order_queue: List[CoatingOrder] = []  # Orders waiting to be scheduled
        self.scheduled_orders: List[CoatingOrder] = []  # Orders scheduled
        self.active_orders: List[CoatingOrder] = []  # Orders in progress
        self.completed_orders: List[CoatingOrder] = []  # Recently completed

        # Facility definitions
        self.facilities = {
            "eindhoven": "MetalFab Eindhoven HQ (NL)",
            "roeselare": "MetalFab Roeselare (BE)",
            "brasov": "MetalFab Brasov (RO)",
        }

        # Zone states
        self.coating_booth = CoatingBoothState(
            booth_id=f"{line_id}_BOOTH",
            current_ral_code=self.current_ral_code,
            current_ral_name=self.current_ral_name,
            current_ral_hex=self.current_ral_hex,
            last_color_change=datetime.now() - timedelta(hours=random.randint(1, 8)),
        )

        self.drying_oven = OvenState(
            oven_id=f"{line_id}_DRY_OVEN",
            oven_type="DRYING",
            setpoint_temp_c=120.0,
            internal_temp_c=118.0,
            external_temp_c=35.0,
            dwell_time_min=10.0,
            gas_consumption_m3h=15.0,
        )

        self.curing_oven = OvenState(
            oven_id=f"{line_id}_CURE_OVEN",
            oven_type="CURING",
            setpoint_temp_c=190.0,
            internal_temp_c=188.0,
            external_temp_c=45.0,
            dwell_time_min=20.0,
            gas_consumption_m3h=25.0,
        )

        # Initialize with some orders from different facilities
        self._init_orders()
        self._init_traversals()

    def _init_orders(self) -> None:
        """Initialize with orders from different facilities."""
        facilities = ["eindhoven", "roeselare", "brasov"]
        customers = ["Siemens AG", "Bosch Rexroth", "Atlas Copco", "Vanderlande", "ASML"]

        # Create 8-12 orders from various facilities
        for _ in range(random.randint(8, 12)):
            facility = random.choice(facilities)
            ral = random.choice(RAL_COLORS)
            self._order_counter += 1

            order = CoatingOrder(
                order_id=f"COAT_{self._order_counter}",
                source_facility=facility,
                source_site_name=self.facilities[facility],
                job_id=f"JOB_{random.randint(9900, 9999)}",
                customer=random.choice(customers),
                part_description=f"{random.choice(['Bracket', 'Panel', 'Frame', 'Housing'])} {random.randint(100, 999)}",
                part_count=random.randint(10, 100),
                ral_code=ral[0],
                ral_name=ral[1],
                ral_hex=ral[2],
                priority=random.choice([1, 1, 5, 5, 5, 5, 10]),  # Most are normal priority
                requested_date=datetime.now() + timedelta(days=random.randint(1, 14)),
                estimated_duration_min=random.uniform(30, 90),
            )
            self.order_queue.append(order)

        # Schedule orders by RAL color grouping
        self._schedule_orders()

    def _schedule_orders(self) -> None:
        """Simple MES scheduler: group by RAL color to minimize changeovers."""
        # Sort by: 1) RAL color (batch same colors), 2) Priority, 3) Requested date
        self.order_queue.sort(
            key=lambda o: (o.ral_code, o.priority, o.requested_date or datetime.now())
        )

        # Schedule first batch matching current color or highest priority
        scheduled_count = 0
        for order in list(self.order_queue):
            # Schedule orders that match current color or are urgent
            if order.ral_code == self.current_ral_code or order.priority == 1:
                if scheduled_count < 5:  # Max 5 scheduled at a time
                    order.status = "SCHEDULED"
                    order.scheduled_date = datetime.now() + timedelta(
                        minutes=scheduled_count * 45
                    )
                    self.order_queue.remove(order)
                    self.scheduled_orders.append(order)
                    scheduled_count += 1

    def create_order_from_facility(
        self, facility: str, job_id: str, part_count: int, ral_code: str, priority: int = 5
    ) -> CoatingOrder:
        """Create a new coating order from a facility."""
        self._order_counter += 1

        # Find RAL color details
        ral_details = next((r for r in RAL_COLORS if r[0] == ral_code), RAL_COLORS[0])

        order = CoatingOrder(
            order_id=f"COAT_{self._order_counter}",
            source_facility=facility,
            source_site_name=self.facilities.get(facility, f"Unknown ({facility})"),
            job_id=job_id,
            customer="Internal",
            part_description=f"Parts from {facility}",
            part_count=part_count,
            ral_code=ral_details[0],
            ral_name=ral_details[1],
            ral_hex=ral_details[2],
            priority=priority,
            requested_date=datetime.now() + timedelta(days=7),
            estimated_duration_min=part_count * 0.5,  # ~30s per part
        )

        self.order_queue.append(order)
        self._schedule_orders()
        return order

    def _init_traversals(self) -> None:
        """Initialize line with some traversals in various zones."""
        # Start first scheduled order if available
        if self.scheduled_orders:
            order = self.scheduled_orders.pop(0)
            order.status = "IN_PROGRESS"
            order.started_at = datetime.now()
            self.active_orders.append(order)

            # Create traversal from order
            for zone in self.ZONE_ORDER[:-1]:  # Skip unloading
                if random.random() < 0.3:  # 30% chance per zone
                    self._add_traversal_from_order(zone, order)
        else:
            # Fallback: create dummy orders for initial traversals
            for zone in self.ZONE_ORDER[:-1]:
                if random.random() < 0.2:
                    dummy_order = self._create_dummy_order()
                    self._add_traversal_from_order(zone, dummy_order)

    def _create_dummy_order(self) -> CoatingOrder:
        """Create a dummy order for initialization."""
        self._order_counter += 1
        ral = random.choice(RAL_COLORS)
        facility = random.choice(["eindhoven", "roeselare", "brasov"])

        return CoatingOrder(
            order_id=f"COAT_{self._order_counter}",
            source_facility=facility,
            source_site_name=self.facilities[facility],
            job_id=f"JOB_{random.randint(9900, 9999)}",
            customer="Sample Customer",
            part_description="Sample Part",
            part_count=random.randint(10, 50),
            ral_code=ral[0],
            ral_name=ral[1],
            ral_hex=ral[2],
            status="IN_PROGRESS",
        )

    def _add_traversal_from_order(
        self, zone: PowderCoatingZone, order: CoatingOrder
    ) -> Traversal:
        """Add a new traversal from a coating order."""
        self._traversal_counter += 1
        trav_id = f"TRAV_{self._traversal_counter}"

        traversal = Traversal(
            traversal_id=trav_id,
            coating_order=order,
            job_id=order.job_id,
            part_count=min(order.part_count, random.randint(4, 20)),  # Parts per hanger batch
            current_zone=zone,
            zone_entered_at=datetime.now() - timedelta(
                seconds=random.randint(0, self.ZONE_DWELL_TIMES[zone])
            ),
            ral_code=order.ral_code,
            ral_name=order.ral_name,
            total_weight_kg=random.uniform(20, 100),
            hanger_count=random.randint(2, 8),
        )
        self.traversals[trav_id] = traversal
        return traversal

    def _add_traversal(self, zone: PowderCoatingZone, job_id: Optional[str] = None) -> Traversal:
        """Add a new traversal to a zone (legacy method - creates dummy order)."""
        order = self._create_dummy_order()
        return self._add_traversal_from_order(zone, order)

    def tick(self) -> List[Traversal]:
        """Advance simulation - move traversals between zones.

        Returns list of traversals that completed (exited unloading).
        """
        completed = []

        for trav in list(self.traversals.values()):
            # Check if dwell time exceeded
            dwell_time = self.ZONE_DWELL_TIMES[trav.current_zone]
            if trav.time_in_zone_seconds() >= dwell_time:
                # Move to next zone
                current_idx = self.ZONE_ORDER.index(trav.current_zone)
                if current_idx < len(self.ZONE_ORDER) - 1:
                    next_zone = self.ZONE_ORDER[current_idx + 1]
                    trav.current_zone = next_zone
                    trav.zone_entered_at = datetime.now()
                else:
                    # Completed - remove from line
                    completed.append(trav)
                    del self.traversals[trav.traversal_id]

                    # Mark order as complete if all parts done
                    order = trav.coating_order
                    if order.status == "IN_PROGRESS":
                        order.status = "COMPLETED"
                        order.completed_at = datetime.now()
                        if order in self.active_orders:
                            self.active_orders.remove(order)
                        self.completed_orders.append(order)

        # Start scheduled orders when loading zone has capacity
        if self.count_in_zone(PowderCoatingZone.LOADING) < 3 and self.scheduled_orders:
            next_order = self.scheduled_orders[0]
            # Check if color matches or if it's time for changeover
            if next_order.ral_code == self.current_ral_code or random.random() < 0.05:
                # Start order
                order = self.scheduled_orders.pop(0)
                order.status = "IN_PROGRESS"
                order.started_at = datetime.now()
                self.active_orders.append(order)

                # Create traversal for this order
                self._add_traversal_from_order(PowderCoatingZone.LOADING, order)

        # Periodically generate new orders from random facilities
        if random.random() < 0.02:  # 2% chance per tick
            facility = random.choice(["eindhoven", "roeselare", "brasov"])
            ral = random.choice(RAL_COLORS)
            self.create_order_from_facility(
                facility=facility,
                job_id=f"JOB_{random.randint(9900, 9999)}",
                part_count=random.randint(10, 80),
                ral_code=ral[0],
                priority=random.choice([1, 5, 5, 10]),
            )

        # Update oven traversal counts
        self.drying_oven.traversals_inside = self.count_in_zone(PowderCoatingZone.DRYING_OVEN)
        self.curing_oven.traversals_inside = self.count_in_zone(PowderCoatingZone.CURING_OVEN)

        # Simulate oven temperature fluctuations
        self.drying_oven.internal_temp_c = self.drying_oven.setpoint_temp_c + random.gauss(0, 2)
        self.curing_oven.internal_temp_c = self.curing_oven.setpoint_temp_c + random.gauss(0, 3)

        # Powder consumption
        coating_count = self.count_in_zone(PowderCoatingZone.COATING_BOOTH)
        if coating_count > 0:
            self.coating_booth.powder_level_pct -= random.uniform(0.01, 0.05)
            if self.coating_booth.powder_level_pct < 20:
                self.coating_booth.powder_level_pct = 85  # Refilled

        return completed

    def change_color(self, ral_code: str, ral_name: str, ral_hex: str) -> None:
        """Change the current color (requires line purge in real life)."""
        self.current_ral_code = ral_code
        self.current_ral_name = ral_name
        self.current_ral_hex = ral_hex

        self.coating_booth.current_ral_code = ral_code
        self.coating_booth.current_ral_name = ral_name
        self.coating_booth.current_ral_hex = ral_hex
        self.coating_booth.last_color_change = datetime.now()
        self.coating_booth.color_change_count_today += 1

    def count_in_zone(self, zone: PowderCoatingZone) -> int:
        """Count traversals in a specific zone."""
        return sum(1 for t in self.traversals.values() if t.current_zone == zone)

    def get_zone_summary(self) -> Dict[str, Any]:
        """Get summary of all zones for _state namespace."""
        return {
            "line_id": self.line_id,
            "current_color": {
                "ral_code": self.current_ral_code,
                "ral_name": self.current_ral_name,
            },
            "zones": {
                zone.value: {
                    "traversal_count": self.count_in_zone(zone),
                    "part_count": sum(
                        t.part_count for t in self.traversals.values()
                        if t.current_zone == zone
                    ),
                }
                for zone in self.ZONE_ORDER
            },
            "total_traversals": len(self.traversals),
            "total_parts_in_line": sum(t.part_count for t in self.traversals.values()),
            "_updated_at": datetime.now().isoformat() + "Z",
        }

    def get_traversals_by_zone(self, zone: PowderCoatingZone) -> List[Dict[str, Any]]:
        """Get all traversals in a specific zone."""
        return [
            t.to_state_dict()
            for t in self.traversals.values()
            if t.current_zone == zone
        ]

    def get_planning_summary(self) -> Dict[str, Any]:
        """Get MES planning summary showing orders from all facilities."""
        # Group orders by facility
        orders_by_facility = {}
        for facility in self.facilities.keys():
            orders_by_facility[facility] = {
                "queued": [o for o in self.order_queue if o.source_facility == facility],
                "scheduled": [o for o in self.scheduled_orders if o.source_facility == facility],
                "active": [o for o in self.active_orders if o.source_facility == facility],
            }

        # Calculate statistics
        total_queued = len(self.order_queue)
        total_scheduled = len(self.scheduled_orders)
        total_active = len(self.active_orders)

        # Next color changeover needed
        next_color_needed = None
        if self.scheduled_orders:
            next_scheduled = self.scheduled_orders[0]
            if next_scheduled.ral_code != self.current_ral_code:
                next_color_needed = {
                    "from": {"code": self.current_ral_code, "name": self.current_ral_name},
                    "to": {"code": next_scheduled.ral_code, "name": next_scheduled.ral_name},
                    "changeover_time_min": 45,  # Typical changeover time
                }

        return {
            "line_id": self.line_id,
            "location": self.location,
            "shared_resource": True,
            "current_color": {
                "ral_code": self.current_ral_code,
                "ral_name": self.current_ral_name,
                "ral_hex": self.current_ral_hex,
            },
            "statistics": {
                "orders_queued": total_queued,
                "orders_scheduled": total_scheduled,
                "orders_active": total_active,
                "orders_completed_today": len(self.completed_orders),
            },
            "facility_breakdown": {
                facility: {
                    "queued_count": len(data["queued"]),
                    "scheduled_count": len(data["scheduled"]),
                    "active_count": len(data["active"]),
                }
                for facility, data in orders_by_facility.items()
            },
            "next_color_changeover": next_color_needed,
            "_updated_at": datetime.now().isoformat() + "Z",
        }

    def get_order_queue(self, max_orders: int = 20) -> List[Dict[str, Any]]:
        """Get detailed order queue for planning view."""
        orders = []

        # Scheduled orders (top priority)
        for order in self.scheduled_orders[:max_orders]:
            orders.append(order.to_planning_dict())

        # Queued orders
        remaining = max_orders - len(orders)
        for order in self.order_queue[:remaining]:
            orders.append(order.to_planning_dict())

        return orders

    def get_facility_orders(self, facility: str) -> Dict[str, Any]:
        """Get all orders for a specific facility."""
        return {
            "facility": facility,
            "site_name": self.facilities.get(facility, "Unknown"),
            "queued": [o.to_planning_dict() for o in self.order_queue if o.source_facility == facility],
            "scheduled": [o.to_planning_dict() for o in self.scheduled_orders if o.source_facility == facility],
            "active": [o.to_planning_dict() for o in self.active_orders if o.source_facility == facility],
            "completed_today": [o.to_planning_dict() for o in self.completed_orders if o.source_facility == facility],
            "_updated_at": datetime.now().isoformat() + "Z",
        }

    def to_meta_dict(self) -> Dict[str, Any]:
        """Get descriptive metadata for _meta namespace."""
        return {
            "line_id": self.line_id,
            "location": self.location,
            "line_type": "POWDER_COATING",
            "shared_resource": True,
            "serves_facilities": list(self.facilities.keys()),
            "zones": [z.value for z in self.ZONE_ORDER],
            "booth": {
                "gun_count": self.coating_booth.gun_count,
                "electrostatic_kv": self.coating_booth.electrostatic_kv,
            },
            "drying_oven": {
                "setpoint_temp_c": self.drying_oven.setpoint_temp_c,
                "dwell_time_min": self.drying_oven.dwell_time_min,
            },
            "curing_oven": {
                "setpoint_temp_c": self.curing_oven.setpoint_temp_c,
                "dwell_time_min": self.curing_oven.dwell_time_min,
            },
            "available_colors": [
                {"ral_code": r[0], "ral_name": r[1], "hex": r[2]}
                for r in RAL_COLORS
            ],
        }


# =============================================================================
# Sensor Generators
# =============================================================================


@dataclass
class SensorGenerator:
    """Generates realistic sensor values with noise."""

    sensor_id: str
    base_value: float = 50.0
    min_value: float = 0.0
    max_value: float = 100.0
    noise_stddev: float = 2.0
    drift_rate: float = 0.0  # Value change per hour
    unit: str = ""

    _current_drift: float = field(default=0.0, init=False)
    _last_update: float = field(default_factory=time.time, init=False)

    def _compute_value(self, state: PackMLState = PackMLState.EXECUTE) -> float:
        """Compute the sensor value based on state."""
        now = time.time()
        elapsed_hours = (now - self._last_update) / 3600
        self._last_update = now

        # Apply drift
        if self.drift_rate != 0:
            self._current_drift += self.drift_rate * elapsed_hours

        # Base value depends on state
        if state in (PackMLState.STOPPED, PackMLState.IDLE, PackMLState.ABORTED):
            effective_base = self.min_value
        elif state == PackMLState.EXECUTE:
            effective_base = self.base_value + self._current_drift
        else:
            effective_base = self.base_value * 0.5  # Transitional states

        # Add noise
        noise = random.gauss(0, self.noise_stddev)
        value = effective_base + noise

        # Clamp to range
        value = max(self.min_value, min(self.max_value, value))
        return round(value, 2)

    def generate_value(self, state: PackMLState = PackMLState.EXECUTE) -> float:
        """Generate just the sensor value (simple payload)."""
        return self._compute_value(state)

    def generate(self, state: PackMLState = PackMLState.EXECUTE) -> Dict[str, Any]:
        """Generate a sensor reading with timestamp (for _raw)."""
        value = self._compute_value(state)
        return {
            "timestamp_ms": int(time.time() * 1000),
            "value": value,
        }

    def generate_extended(self, state: PackMLState = PackMLState.EXECUTE) -> Dict[str, Any]:
        """Generate extended sensor reading with metadata."""
        reading = self.generate(state)
        reading.update(
            {
                "quality": "GOOD",
                "unit": self.unit,
                "sensor_id": self.sensor_id,
            }
        )
        return reading


def create_sensor_generators(cell_type: str) -> Dict[str, SensorGenerator]:
    """Create sensor generators for a cell type."""
    generators = {}

    if cell_type == "laser_cutter":
        generators = {
            "laser_power_pct": SensorGenerator(
                "laser_power_pct", base_value=85.0, max_value=100.0, noise_stddev=2.0, unit="%"
            ),
            "cutting_speed_mmpm": SensorGenerator(
                "cutting_speed_mmpm",
                base_value=15000.0,
                min_value=0.0,
                max_value=50000.0,
                noise_stddev=200.0,
                unit="mm/min",
            ),
            "assist_gas_bar": SensorGenerator(
                "assist_gas_bar", base_value=12.0, max_value=25.0, noise_stddev=0.5, unit="bar"
            ),
            "power_kw": SensorGenerator(
                "power_kw", base_value=42.0, min_value=5.0, max_value=55.0, noise_stddev=1.5, unit="kW"
            ),
            "coolant_temp_c": SensorGenerator(
                "coolant_temp_c",
                base_value=22.0,
                min_value=18.0,
                max_value=30.0,
                noise_stddev=0.3,
                unit="°C",
            ),
        }

    elif cell_type == "press_brake":
        generators = {
            "tonnage_t": SensorGenerator(
                "tonnage_t", base_value=180.0, min_value=0.0, max_value=320.0, noise_stddev=5.0, unit="t"
            ),
            "bend_angle_deg": SensorGenerator(
                "bend_angle_deg", base_value=90.0, min_value=0.0, max_value=180.0, noise_stddev=0.3, unit="°"
            ),
            "stroke_mm": SensorGenerator(
                "stroke_mm", base_value=250.0, min_value=0.0, max_value=500.0, noise_stddev=1.0, unit="mm"
            ),
            "power_kw": SensorGenerator(
                "power_kw", base_value=20.0, min_value=2.0, max_value=30.0, noise_stddev=1.0, unit="kW"
            ),
        }

    elif cell_type == "robot_weld":
        generators = {
            "weld_current_a": SensorGenerator(
                "weld_current_a", base_value=220.0, min_value=0.0, max_value=350.0, noise_stddev=8.0, unit="A"
            ),
            "weld_voltage_v": SensorGenerator(
                "weld_voltage_v", base_value=24.0, min_value=0.0, max_value=32.0, noise_stddev=0.5, unit="V"
            ),
            "wire_feed_mpm": SensorGenerator(
                "wire_feed_mpm", base_value=10.0, min_value=0.0, max_value=20.0, noise_stddev=0.3, unit="m/min"
            ),
            "gas_flow_lpm": SensorGenerator(
                "gas_flow_lpm", base_value=15.0, min_value=0.0, max_value=25.0, noise_stddev=0.5, unit="L/min"
            ),
        }

    elif cell_type == "paint_booth":
        generators = {
            "temp_c": SensorGenerator(
                "temp_c", base_value=60.0, min_value=20.0, max_value=200.0, noise_stddev=2.0, unit="°C"
            ),
            "humidity_pct": SensorGenerator(
                "humidity_pct", base_value=45.0, min_value=20.0, max_value=80.0, noise_stddev=3.0, unit="%"
            ),
            "airflow_cfm": SensorGenerator(
                "airflow_cfm", base_value=800.0, min_value=0.0, max_value=1200.0, noise_stddev=20.0, unit="CFM"
            ),
        }

    elif cell_type == "agv":
        generators = {
            "battery_pct": SensorGenerator(
                "battery_pct", base_value=75.0, min_value=0.0, max_value=100.0, noise_stddev=0.1, unit="%"
            ),
            "speed_mps": SensorGenerator(
                "speed_mps", base_value=1.5, min_value=0.0, max_value=2.5, noise_stddev=0.1, unit="m/s"
            ),
        }

    # Add generic power sensor if not already present
    if "power_kw" not in generators:
        generators["power_kw"] = SensorGenerator(
            "power_kw", base_value=10.0, min_value=0.5, max_value=50.0, noise_stddev=1.0, unit="kW"
        )

    return generators


# =============================================================================
# Job Generator
# =============================================================================


@dataclass
class Job:
    """Represents a manufacturing job with rich stateful data.

    This class supports retained stateful messages that provide complete
    context about a job's position, timing, and ERP/MES enrichment.
    """

    # Core identification
    job_id: str
    job_number: str
    job_name: str
    customer: str
    customer_id: str = ""

    # Status tracking
    status: JobStatus = JobStatus.CREATED
    priority: JobPriority = JobPriority.NORMAL

    # Quantity tracking
    qty_target: int = 100
    qty_complete: int = 0
    qty_scrap: int = 0
    qty_rework: int = 0

    # Routing and position (stateful - where is the job?)
    routing: List[str] = field(default_factory=list)
    current_operation_idx: int = 0
    current_cell: Optional[str] = None
    current_operation_name: str = ""
    assigned_operator: Optional[str] = None

    # Timestamps for tracking
    created_at: datetime = field(default_factory=datetime.now)
    released_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    operation_started_at: Optional[datetime] = None
    due_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Scheduling (ERP data)
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    operation_planned_finish: Optional[datetime] = None
    sales_order_number: str = ""

    # ERP/MES enrichment data (Level 3+)
    estimated_hours: float = 0.0
    actual_hours: float = 0.0
    operation_estimated_hours: float = 0.0
    operation_actual_hours: float = 0.0
    material_cost: float = 0.0
    labor_cost: float = 0.0
    quoted_price: float = 0.0
    margin_pct: float = 0.0

    # Material and part info
    item_number: str = ""
    material_spec: str = ""
    sheet_thickness_mm: float = 0.0

    # MES quality data
    quality_score: float = 100.0
    inspection_required: bool = False
    last_inspection_at: Optional[datetime] = None

    def _calculate_active_since(self) -> Optional[str]:
        """Calculate human-readable 'active since' duration."""
        if not self.operation_started_at:
            return None
        delta = datetime.now() - self.operation_started_at
        hours = delta.total_seconds() / 3600
        if hours < 1:
            return f"{int(delta.total_seconds() / 60)}m"
        elif hours < 24:
            return f"{hours:.1f}h"
        else:
            return f"{hours / 24:.1f}d"

    def _calculate_lead_time_status(self) -> Tuple[float, str]:
        """Calculate lead time and status."""
        if not self.due_date:
            return 0.0, "UNKNOWN"
        remaining = (self.due_date - datetime.now()).total_seconds() / 86400
        lead_time_days = round(remaining, 1)
        if lead_time_days > 2:
            status = "AHEAD"
        elif lead_time_days > 0:
            status = "ON_TIME"
        else:
            status = "LATE"
        return lead_time_days, status

    def to_state_dict(self) -> Dict[str, Any]:
        """Convert to rich state message (Level 2) - RETAINED.

        This provides complete job context for retained MQTT messages,
        including position, timing, and current status.
        """
        lead_time, lead_status = self._calculate_lead_time_status()

        return {
            # Core identification
            "job_id": self.job_id,
            "job_number": self.job_number,
            "job_name": self.job_name,
            "customer": self.customer,

            # Current status
            "status": self.status.value,
            "priority": self.priority.value,

            # Position - where is this job right now?
            "current_cell": self.current_cell,
            "current_operation": self.current_operation_name or f"OP{self.current_operation_idx + 1:02d}",
            "current_operation_idx": self.current_operation_idx,
            "total_operations": len(self.routing),
            "assigned_operator": self.assigned_operator,

            # Timing - how long has it been here?
            "active_since": self._calculate_active_since(),
            "operation_started_at": self.operation_started_at.isoformat() + "Z" if self.operation_started_at else None,
            "started_at": self.started_at.isoformat() + "Z" if self.started_at else None,

            # Progress
            "qty_target": self.qty_target,
            "qty_complete": self.qty_complete,
            "qty_scrap": self.qty_scrap,
            "progress_pct": round(self.qty_complete / self.qty_target * 100, 1) if self.qty_target > 0 else 0,

            # Schedule
            "due_date": self.due_date.isoformat() + "Z" if self.due_date else None,
            "lead_time_days": lead_time,
            "lead_time_status": lead_status,
            "operation_planned_finish": self.operation_planned_finish.isoformat() + "Z" if self.operation_planned_finish else None,

            # Routing
            "routing": self.routing,

            "_updated_at": datetime.now().isoformat() + "Z",
        }

    def to_erp_dict(self) -> Dict[str, Any]:
        """Convert to ERP message (Level 3) with full relational data.

        Following UMH Pattern A: On-demand fetch - this provides the complete
        record that would be fetched from ERP when order number changes.
        """
        lead_time, lead_status = self._calculate_lead_time_status()

        return {
            # ERP identifiers
            "job_id": self.job_id,
            "job_number": self.job_number,
            "sales_order_number": self.sales_order_number,

            # Customer
            "customer": self.customer,
            "customer_id": self.customer_id,

            # Status
            "status": self.status.value,
            "priority": self.priority.value,

            # Schedule (ERP master data)
            "scheduled_start": self.scheduled_start.isoformat() + "Z" if self.scheduled_start else None,
            "scheduled_end": self.scheduled_end.isoformat() + "Z" if self.scheduled_end else None,
            "actual_start": self.started_at.isoformat() + "Z" if self.started_at else None,
            "due_date": self.due_date.isoformat() + "Z" if self.due_date else None,

            # Lead time
            "lead_time_days": lead_time,
            "lead_time_status": lead_status,

            # Quantities
            "ordered_quantity": self.qty_target,
            "produced_quantity": self.qty_complete,
            "remaining_quantity": self.qty_target - self.qty_complete,
            "scrap_quantity": self.qty_scrap,
            "completion_pct": round(self.qty_complete / self.qty_target * 100, 1) if self.qty_target > 0 else 0,

            # Item/Part
            "item_number": self.item_number,
            "item_description": self.job_name,
            "material_spec": self.material_spec,
            "sheet_thickness_mm": self.sheet_thickness_mm,

            # Time tracking
            "estimated_hours": self.estimated_hours,
            "actual_hours": self.actual_hours,
            "est_vs_actual_hours": round(self.actual_hours - self.estimated_hours, 2),

            # Cost tracking
            "material_cost_eur": self.material_cost,
            "labor_cost_eur": self.labor_cost,
            "total_cost_eur": round(self.material_cost + self.labor_cost, 2),
            "quoted_price_eur": self.quoted_price,
            "margin_pct": self.margin_pct,

            "_updated_at": datetime.now().isoformat() + "Z",
        }

    def to_mes_dict(self) -> Dict[str, Any]:
        """Convert to MES message (Level 3) with operational data."""
        return {
            "job_id": self.job_id,
            "job_number": self.job_number,

            # Current operation
            "current_cell": self.current_cell,
            "current_operation": self.current_operation_name or f"OP{self.current_operation_idx + 1:02d}",
            "assigned_operator": self.assigned_operator,

            # Operation timing
            "operation_started_at": self.operation_started_at.isoformat() + "Z" if self.operation_started_at else None,
            "operation_estimated_hours": self.operation_estimated_hours,
            "operation_actual_hours": self.operation_actual_hours,
            "operation_planned_finish": self.operation_planned_finish.isoformat() + "Z" if self.operation_planned_finish else None,

            # Quality
            "quality_score": self.quality_score,
            "qty_scrap": self.qty_scrap,
            "qty_rework": self.qty_rework,
            "inspection_required": self.inspection_required,
            "last_inspection_at": self.last_inspection_at.isoformat() + "Z" if self.last_inspection_at else None,

            # Progress
            "qty_complete": self.qty_complete,
            "qty_target": self.qty_target,
            "progress_pct": round(self.qty_complete / self.qty_target * 100, 1) if self.qty_target > 0 else 0,

            "_updated_at": datetime.now().isoformat() + "Z",
        }


class JobGenerator:
    """Generates and manages manufacturing jobs with rich ERP/MES data."""

    # Realistic customers (European industrial companies)
    CUSTOMERS = [
        ("CUST001", "Bosch Rexroth GmbH"),
        ("CUST002", "Siemens AG"),
        ("CUST003", "Festo SE & Co. KG"),
        ("CUST004", "Atlas Copco"),
        ("CUST005", "Vanderlande Industries"),
        ("CUST006", "ASML Holding"),
        ("CUST007", "Philips"),
        ("CUST008", "DAF Trucks"),
        ("CUST009", "VDL Groep"),
        ("CUST010", "Marel"),
        ("CUST011", "Krone GmbH"),
        ("CUST012", "Liebherr"),
    ]

    # Operation names for routing
    OPERATION_NAMES = {
        "laser_cutter": "Laser Cutting",
        "press_brake": "Bending",
        "robot_weld": "Welding",
        "paint_booth": "Painting",
        "agv": "Transport",
    }

    def __init__(self, templates: List[Dict], customers: Optional[List[str]] = None):
        self.templates = templates
        self.customers = customers  # Legacy support
        self._job_counter = 9940  # Start from JOB_9940

    def generate_job(self) -> Job:
        """Generate a new job with rich data from templates."""
        template = random.choice(self.templates) if self.templates else {}
        self._job_counter += 1

        job_id = f"JOB_{self._job_counter}"
        qty = random.randint(
            template.get("qty_range", (50, 200))[0],
            template.get("qty_range", (50, 200))[1],
        )

        # Select customer
        if self.customers:
            customer = random.choice(self.customers)
            customer_id = ""
        else:
            customer_id, customer = random.choice(self.CUSTOMERS)

        # Calculate pricing and estimates
        estimated_hours = qty * random.uniform(0.02, 0.1)  # 1.2-6 min per part
        material_cost = qty * random.uniform(2, 15)
        labor_cost = estimated_hours * 55.0  # €55/hour rate
        margin = random.uniform(0.25, 0.40)
        quoted_price = (material_cost + labor_cost) / (1 - margin)
        margin_pct = round(margin * 100, 1)

        # Scheduling
        now = datetime.now()
        scheduled_start = now + timedelta(days=random.randint(0, 3))
        due_date = now + timedelta(days=random.randint(3, 14))
        scheduled_end = due_date - timedelta(hours=random.randint(4, 24))

        # Get routing from template
        routing = template.get("routing", ["laser_01"])

        # Material info
        material_spec = template.get("material", "DC01")
        thickness = template.get("thickness", 2.0)

        job = Job(
            job_id=job_id,
            job_number=f"WO-{self._job_counter}",
            job_name=f"{template.get('name', 'Custom Part')} Batch {self._job_counter % 100}",
            customer=customer,
            customer_id=customer_id,
            priority=random.choices(
                list(JobPriority),
                weights=[0.3, 0.5, 0.15, 0.05],
            )[0],
            qty_target=qty,
            routing=routing,

            # Scheduling
            scheduled_start=scheduled_start,
            scheduled_end=scheduled_end,
            due_date=due_date,
            sales_order_number=f"SO-{random.randint(50000, 59999)}",

            # Time estimates
            estimated_hours=round(estimated_hours, 1),
            operation_estimated_hours=round(estimated_hours / len(routing), 2) if routing else 0,

            # Cost/pricing
            material_cost=round(material_cost, 2),
            labor_cost=round(labor_cost, 2),
            quoted_price=round(quoted_price, 2),
            margin_pct=margin_pct,

            # Material info
            item_number=f"PN-{random.randint(10000, 99999)}",
            material_spec=material_spec,
            sheet_thickness_mm=thickness,
        )

        return job

    def start_job(self, job: Job, cell_id: str) -> None:
        """Start a job on a cell with all stateful data."""
        now = datetime.now()
        job.status = JobStatus.IN_PROGRESS
        job.current_cell = cell_id
        job.started_at = job.started_at or now
        job.operation_started_at = now
        job.released_at = job.released_at or (now - timedelta(hours=random.randint(1, 24)))

        # Set operation name based on cell type
        for cell_type, op_name in self.OPERATION_NAMES.items():
            if cell_type in cell_id:
                job.current_operation_name = op_name
                break
        else:
            job.current_operation_name = f"Operation {job.current_operation_idx + 1}"

        # Calculate operation planned finish
        if job.operation_estimated_hours > 0:
            job.operation_planned_finish = now + timedelta(hours=job.operation_estimated_hours * 1.1)

    def advance_job(self, job: Job) -> bool:
        """Advance job to next operation. Returns True if job completed."""
        job.current_operation_idx += 1
        job.operation_started_at = datetime.now()
        job.operation_actual_hours = 0

        if job.current_operation_idx >= len(job.routing):
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now()
            job.current_cell = None
            return True

        job.current_cell = job.routing[job.current_operation_idx]

        # Set new operation name
        for cell_type, op_name in self.OPERATION_NAMES.items():
            if cell_type in job.current_cell:
                job.current_operation_name = op_name
                break

        # Update planned finish
        if job.operation_estimated_hours > 0:
            job.operation_planned_finish = datetime.now() + timedelta(hours=job.operation_estimated_hours * 1.1)

        return False


# =============================================================================
# ERP/MES Data Generators (Level 3-4)
# =============================================================================


@dataclass
class ERPMESGenerator:
    """Generates ERP/MES enrichment data."""

    def generate_energy_metrics(self, cells_data: List[Dict]) -> Dict[str, Any]:
        """Generate energy consumption metrics."""
        total_kwh = sum(c.get("power_kw", 10) for c in cells_data) * (random.uniform(0.8, 1.2))

        return {
            "kwh_today": round(total_kwh * 8, 1),  # Assume 8-hour shift
            "kwh_this_shift": round(total_kwh * 4, 1),
            "cost_per_kwh_eur": 0.15,
            "total_cost_today_eur": round(total_kwh * 8 * 0.15, 2),
            "avg_cost_per_order_eur": round(random.uniform(8, 18), 2),
            "timestamp_ms": int(time.time() * 1000),
        }

    def generate_quality_metrics(self, cell_id: str) -> Dict[str, Any]:
        """Generate quality metrics for a cell."""
        quality_pct = random.gauss(98.5, 1.0)
        quality_pct = max(90.0, min(100.0, quality_pct))

        return {
            "cell_id": cell_id,
            "quality_pct": round(quality_pct, 1),
            "defect_rate_pct": round(100 - quality_pct, 2),
            "scrap_count_today": random.randint(0, 15),
            "rework_count_today": random.randint(0, 8),
            "first_pass_yield_pct": round(quality_pct - random.uniform(0, 2), 1),
            "timestamp_ms": int(time.time() * 1000),
        }

    def generate_oee_metrics(self, cell_id: str) -> Dict[str, Any]:
        """Generate OEE metrics for a cell."""
        availability = random.gauss(92, 4)
        performance = random.gauss(88, 5)
        quality = random.gauss(98, 1.5)

        availability = max(70, min(100, availability))
        performance = max(60, min(100, performance))
        quality = max(85, min(100, quality))

        oee = (availability * performance * quality) / 10000

        return {
            "cell_id": cell_id,
            "oee_pct": round(oee, 1),
            "availability_pct": round(availability, 1),
            "performance_pct": round(performance, 1),
            "quality_pct": round(quality, 1),
            "idle_time_min": random.randint(5, 45),
            "downtime_min": random.randint(0, 30),
            "period": "SHIFT",
            "timestamp_ms": int(time.time() * 1000),
        }

    def generate_delivery_metrics(self, jobs: List[Job]) -> Dict[str, Any]:
        """Generate delivery performance metrics."""
        on_time = sum(1 for j in jobs if j.due_date and j.due_date > datetime.now())
        total = len(jobs) if jobs else 1

        return {
            "on_time_pct": round(on_time / total * 100, 1) if total > 0 else 100.0,
            "late_orders": max(0, total - on_time),
            "orders_shipping_today": random.randint(3, 12),
            "orders_due_this_week": random.randint(15, 40),
            "avg_lead_time_days": round(random.uniform(3, 8), 1),
            "timestamp_ms": int(time.time() * 1000),
        }

    def generate_inventory_metrics(self, jobs: List[Job]) -> Dict[str, Any]:
        """Generate inventory/WIP metrics."""
        wip_value = sum(j.material_cost * (j.qty_complete / j.qty_target) for j in jobs if j.status == JobStatus.IN_PROGRESS)

        return {
            "wip_value_eur": round(wip_value, 0) if wip_value > 0 else random.randint(25000, 50000),
            "wip_orders": len([j for j in jobs if j.status == JobStatus.IN_PROGRESS]),
            "inventory_turns_yr": round(random.uniform(10, 15), 1),
            "raw_material_value_eur": random.randint(80000, 150000),
            "finished_goods_value_eur": random.randint(30000, 70000),
            "timestamp_ms": int(time.time() * 1000),
        }

    def generate_machine_utilization(self, cells_states: Dict[str, PackMLState]) -> Dict[str, Any]:
        """Generate machine utilization metrics."""
        running = sum(1 for s in cells_states.values() if s == PackMLState.EXECUTE)
        total = len(cells_states) if cells_states else 1

        # Find bottleneck (random for simulation)
        bottleneck = random.choice(list(cells_states.keys())) if cells_states else "press_brake_02"

        return {
            "fleet_utilization_pct": round(running / total * 100, 1) if total > 0 else 0,
            "machines_running": running,
            "machines_total": total,
            "machines_idle": total - running,
            "bottleneck_cell": bottleneck,
            "bottleneck_queue_hours": round(random.uniform(2, 12), 1),
            "timestamp_ms": int(time.time() * 1000),
        }

    def generate_quote_metrics(self) -> Dict[str, Any]:
        """Generate quotation metrics."""
        return {
            "quote_id": f"QUOTE_{random.randint(9900, 9999)}",
            "margin_pct": round(random.uniform(25, 45), 1),
            "est_vs_actual_hours": round(random.gauss(0, 3), 1),
            "quotes_pending": random.randint(5, 20),
            "quotes_won_this_month": random.randint(10, 35),
            "win_rate_pct": round(random.uniform(35, 55), 1),
            "avg_quote_value_eur": random.randint(2000, 15000),
            "timestamp_ms": int(time.time() * 1000),
        }

    def generate_dashboard_summary(
        self, jobs: List[Job], cells_states: Dict[str, PackMLState]
    ) -> Dict[str, Any]:
        """Generate dashboard summary data (Level 4)."""
        active_jobs = [j for j in jobs if j.status == JobStatus.IN_PROGRESS]

        return {
            "shift": {
                "current": "DAY" if 6 <= datetime.now().hour < 14 else "EVENING" if datetime.now().hour < 22 else "NIGHT",
                "start": datetime.now().replace(hour=6, minute=0, second=0).isoformat() + "Z",
            },
            "jobs": {
                "active": len(active_jobs),
                "completed_today": random.randint(8, 25),
                "on_time_pct": round(random.uniform(90, 99), 1),
            },
            "production": {
                "parts_today": random.randint(300, 800),
                "scrap_pct": round(random.uniform(0.5, 3.0), 1),
                "throughput_per_hour": random.randint(30, 80),
            },
            "machines": {
                "running": sum(1 for s in cells_states.values() if s == PackMLState.EXECUTE),
                "total": len(cells_states),
                "utilization_pct": round(
                    sum(1 for s in cells_states.values() if s == PackMLState.EXECUTE) / max(len(cells_states), 1) * 100,
                    1,
                ),
            },
            "energy": {
                "kwh_today": random.randint(600, 1200),
                "cost_eur": round(random.randint(600, 1200) * 0.15, 2),
            },
            "_updated_at": datetime.now().isoformat() + "Z",
        }
