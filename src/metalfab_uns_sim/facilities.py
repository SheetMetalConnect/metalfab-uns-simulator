"""Multi-facility configuration for realistic metalworking operations.

Each facility specializes in different operations, reflecting how real
manufacturing companies organize their production across multiple sites.

Facilities:
- Eindhoven (NL): Headquarters, laser cutting, press brakes, assembly, powder coating (shared)
- Roeselare (BE): High-volume manufacturing, welding
- Brasov (RO): Welding specialization, cost-effective production

Note: Powder coating line is located in Eindhoven but serves all facilities as a shared resource.

Topic structure:
    umh/v1/{enterprise}/{site}/...
    umh/v1/metalfab/eindhoven/...
    umh/v1/metalfab/roeselare/...
    umh/v1/metalfab/brasov/...
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum


class FacilityType(Enum):
    """Type of manufacturing facility."""

    HEADQUARTERS = "HEADQUARTERS"
    MANUFACTURING = "MANUFACTURING"
    WELDING_CENTER = "WELDING_CENTER"
    FINISHING_CENTER = "FINISHING_CENTER"


@dataclass
class FacilityConfig:
    """Configuration for a manufacturing facility/site."""

    site_id: str
    name: str
    country: str
    country_code: str
    city: str
    facility_type: FacilityType
    timezone: str

    # Capabilities - what operations this site can do
    capabilities: List[str] = field(default_factory=list)

    # Areas and cells at this site
    areas: List[str] = field(default_factory=list)

    # Workforce
    num_operators: int = 12
    shifts_per_day: int = 2

    # Power and sustainability
    solar_capacity_kwp: float = 0.0
    grid_carbon_intensity_g_per_kwh: float = 350.0  # g CO2/kWh
    renewable_energy_pct: float = 30.0  # % renewable in grid mix

    # Contact
    plant_manager: str = ""
    phone: str = ""

    def to_meta_dict(self) -> Dict[str, Any]:
        """Convert to metadata for _meta namespace."""
        return {
            "site_id": self.site_id,
            "name": self.name,
            "location": {
                "city": self.city,
                "country": self.country,
                "country_code": self.country_code,
            },
            "facility_type": self.facility_type.value,
            "timezone": self.timezone,
            "capabilities": self.capabilities,
            "areas": self.areas,
            "workforce": {
                "num_operators": self.num_operators,
                "shifts_per_day": self.shifts_per_day,
            },
            "sustainability": {
                "solar_capacity_kwp": self.solar_capacity_kwp,
                "grid_carbon_intensity_g_per_kwh": self.grid_carbon_intensity_g_per_kwh,
                "renewable_energy_pct": self.renewable_energy_pct,
            },
            "contact": {
                "plant_manager": self.plant_manager,
                "phone": self.phone,
            },
        }


# =============================================================================
# Pre-configured Facilities
# =============================================================================

FACILITY_EINDHOVEN = FacilityConfig(
    site_id="eindhoven",
    name="MetalFab Eindhoven - Headquarters",
    country="Netherlands",
    country_code="NL",
    city="Eindhoven",
    facility_type=FacilityType.HEADQUARTERS,
    timezone="Europe/Amsterdam",
    capabilities=[
        "laser_cutting",
        "press_brake",
        "assembly",
        "powder_coating",  # Shared resource serving all facilities
        "engineering",
        "quality_control",
        "shipping",
    ],
    areas=["cutting", "forming", "assembly", "finishing", "warehouse", "shipping"],
    num_operators=18,
    shifts_per_day=2,
    solar_capacity_kwp=230.0,
    grid_carbon_intensity_g_per_kwh=380.0,  # NL: gas-heavy grid
    renewable_energy_pct=33.0,
    plant_manager="Jan van den Berg",
    phone="+31 40 123 4567",
)

FACILITY_ROESELARE = FacilityConfig(
    site_id="roeselare",
    name="MetalFab Roeselare - Manufacturing",
    country="Belgium",
    country_code="BE",
    city="Roeselare",
    facility_type=FacilityType.MANUFACTURING,
    timezone="Europe/Brussels",
    capabilities=[
        "laser_cutting",
        "press_brake",
        "robot_welding",
        "powder_coating",
        "assembly",
    ],
    areas=["cutting", "forming", "welding", "finishing", "assembly"],
    num_operators=24,
    shifts_per_day=3,  # 24/7 operation
    solar_capacity_kwp=180.0,
    grid_carbon_intensity_g_per_kwh=160.0,  # BE: nuclear-heavy grid
    renewable_energy_pct=25.0,
    plant_manager="Marc Willems",
    phone="+32 51 123 456",
)

FACILITY_BRASOV = FacilityConfig(
    site_id="brasov",
    name="MetalFab Brasov - Welding Center",
    country="Romania",
    country_code="RO",
    city="Brasov",
    facility_type=FacilityType.WELDING_CENTER,
    timezone="Europe/Bucharest",
    capabilities=[
        "robot_welding",
        "manual_welding",
        "assembly",
        "quality_control",
    ],
    areas=["welding", "assembly", "quality", "warehouse"],
    num_operators=32,
    shifts_per_day=2,
    solar_capacity_kwp=50.0,
    grid_carbon_intensity_g_per_kwh=260.0,  # RO: hydro-heavy grid
    renewable_energy_pct=44.0,
    plant_manager="Andrei Popescu",
    phone="+40 268 123 456",
)

# All facilities indexed by site_id
FACILITIES: Dict[str, FacilityConfig] = {
    "eindhoven": FACILITY_EINDHOVEN,
    "roeselare": FACILITY_ROESELARE,
    "brasov": FACILITY_BRASOV,
}


def get_facility(site_id: str) -> Optional[FacilityConfig]:
    """Get facility configuration by site ID."""
    return FACILITIES.get(site_id.lower())


def get_all_facilities() -> List[FacilityConfig]:
    """Get all facility configurations."""
    return list(FACILITIES.values())


def get_facilities_with_capability(capability: str) -> List[FacilityConfig]:
    """Get all facilities that have a specific capability."""
    return [f for f in FACILITIES.values() if capability in f.capabilities]


# =============================================================================
# Cell configurations per facility
# =============================================================================

# Eindhoven: HQ with cutting, forming, assembly
EINDHOVEN_CELLS = [
    {"area": "cutting", "cells": [
        {"id": "laser_01", "type": "laser_cutter", "name": "TruLaser 3030 #1"},
        {"id": "laser_02", "type": "laser_cutter", "name": "TruLaser 5030 #2"},
    ]},
    {"area": "forming", "cells": [
        {"id": "press_brake_01", "type": "press_brake", "name": "TruBend 5130 #1"},
        {"id": "press_brake_02", "type": "press_brake", "name": "TruBend 7036 #2"},
    ]},
    {"area": "assembly", "cells": [
        {"id": "assembly_01", "type": "assembly", "name": "Assembly Station 1"},
    ]},
    {"area": "warehouse", "cells": [
        {"id": "agv_01", "type": "agv", "name": "AGV Unit 1"},
        {"id": "agv_02", "type": "agv", "name": "AGV Unit 2"},
    ]},
]

# Roeselare: Full manufacturing with coating
ROESELARE_CELLS = [
    {"area": "cutting", "cells": [
        {"id": "laser_03", "type": "laser_cutter", "name": "ByStar Fiber 3015 #3"},
        {"id": "laser_04", "type": "laser_cutter", "name": "TruLaser 3030 #4"},
    ]},
    {"area": "forming", "cells": [
        {"id": "press_brake_03", "type": "press_brake", "name": "Xpert 150 #3"},
    ]},
    {"area": "welding", "cells": [
        {"id": "robot_weld_01", "type": "robot_weld", "name": "KUKA KR 16 #1"},
        {"id": "robot_weld_02", "type": "robot_weld", "name": "ABB IRB 1600 #2"},
    ]},
    {"area": "finishing", "cells": [
        {"id": "coating_line_01", "type": "powder_coating_line", "name": "Wagner PrimaSprint Line"},
    ]},
    {"area": "assembly", "cells": [
        {"id": "assembly_02", "type": "assembly", "name": "Assembly Station 2"},
    ]},
]

# Brasov: Welding specialization
BRASOV_CELLS = [
    {"area": "welding", "cells": [
        {"id": "robot_weld_03", "type": "robot_weld", "name": "Fronius TPS 500i #3"},
        {"id": "robot_weld_04", "type": "robot_weld", "name": "KUKA KR 16 #4"},
        {"id": "robot_weld_05", "type": "robot_weld", "name": "ABB IRB 1600 #5"},
        {"id": "manual_weld_01", "type": "manual_weld", "name": "Manual Weld Station 1"},
        {"id": "manual_weld_02", "type": "manual_weld", "name": "Manual Weld Station 2"},
    ]},
    {"area": "assembly", "cells": [
        {"id": "assembly_03", "type": "assembly", "name": "Assembly Station 3"},
        {"id": "assembly_04", "type": "assembly", "name": "Assembly Station 4"},
    ]},
    {"area": "quality", "cells": [
        {"id": "qc_01", "type": "quality_control", "name": "CMM Quality Station"},
    ]},
]

# All cells indexed by facility
FACILITY_CELLS: Dict[str, List[Dict]] = {
    "eindhoven": EINDHOVEN_CELLS,
    "roeselare": ROESELARE_CELLS,
    "brasov": BRASOV_CELLS,
}


def get_cells_for_facility(site_id: str) -> List[Dict]:
    """Get cell configurations for a facility."""
    return FACILITY_CELLS.get(site_id.lower(), [])
