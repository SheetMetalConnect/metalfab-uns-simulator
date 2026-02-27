"""Complexity levels for the UNS simulator.

Level 1: Basic monitoring - stateless, sensors only
Level 2: Stateful - MQTT retain, latest jobs and positions
Level 3: ERP/MES enrichments - quality, margins, lead times
Level 4: Full historian - ERP/MES historian plus all advanced features
"""

from enum import IntEnum
from dataclasses import dataclass
from typing import Set


class ComplexityLevel(IntEnum):
    """Simulation complexity levels."""

    LEVEL_0_PAUSED = 0  # Paused, no data is being generated
    LEVEL_1_SENSORS = 1  # Basic monitoring - stateless, sensors only
    LEVEL_2_STATEFUL = 2  # Stateful with MQTT retain, jobs, positions
    LEVEL_3_ERP_MES = 3  # ERP/MES enrichments (quality, margins, lead times)
    LEVEL_4_FULL = 4  # Full historian with ERP/MES + all features


@dataclass
class LevelFeatures:
    """Features enabled at each complexity level."""

    # Level 1: Sensors
    sensors: bool = False
    energy_basic: bool = False

    # Level 2: Stateful
    machine_state: bool = False
    job_tracking: bool = False
    agv_positions: bool = False
    retain_messages: bool = False

    # Level 3: ERP/MES
    erp_job_data: bool = False  # Lead times, margins, costs
    mes_quality: bool = False  # Quality %, defect rates
    mes_oee: bool = False  # OEE calculations
    delivery_metrics: bool = False  # On-time delivery
    inventory_wip: bool = False  # WIP value, turns
    dashboards: bool = False  # Aggregated dashboards

    # Level 4: Full
    historian_erp_mes: bool = False  # Historical ERP/MES data
    analytics_advanced: bool = False  # Bottleneck analysis, trends
    events_alarms: bool = False  # Full event/alarm system
    dpp: bool = False  # Digital Product Passports with CO2 tracking


def get_features_for_level(level: ComplexityLevel) -> LevelFeatures:
    """Get the features enabled for a given complexity level."""
    features = LevelFeatures()

    if level == ComplexityLevel.LEVEL_0_PAUSED:
        return features

    # Level 1: Basic sensors
    if level >= ComplexityLevel.LEVEL_1_SENSORS:
        features.sensors = True
        features.energy_basic = True

    # Level 2: Stateful
    if level >= ComplexityLevel.LEVEL_2_STATEFUL:
        features.machine_state = True
        features.job_tracking = True
        features.agv_positions = True
        features.retain_messages = True

    # Level 3: ERP/MES enrichments
    if level >= ComplexityLevel.LEVEL_3_ERP_MES:
        features.erp_job_data = True
        features.mes_quality = True
        features.mes_oee = True
        features.delivery_metrics = True
        features.inventory_wip = True
        features.dashboards = True

    # Level 4: Full historian
    if level >= ComplexityLevel.LEVEL_4_FULL:
        features.historian_erp_mes = True
        features.analytics_advanced = True
        features.events_alarms = True
        features.dpp = True  # Digital Product Passports with CO2 and traceability

    return features


def get_namespaces_for_level(level: ComplexityLevel) -> Set[str]:
    """Get the namespaces published at each level."""
    namespaces = set()

    if level >= ComplexityLevel.LEVEL_1_SENSORS:
        namespaces.add("_raw")  # Sensor time-series (UMH data contract)

    if level >= ComplexityLevel.LEVEL_2_STATEFUL:
        namespaces.add("_state")  # Machine/job state
        namespaces.add("_meta")  # Asset metadata
        namespaces.add("_jobs")  # Job tracking

    if level >= ComplexityLevel.LEVEL_3_ERP_MES:
        namespaces.add("_erp")  # ERP data (jobs, costs, margins)
        namespaces.add("_mes")  # MES data (quality, OEE)
        namespaces.add("_dashboard")  # Aggregated views

    if level >= ComplexityLevel.LEVEL_4_FULL:
        namespaces.add("_analytics")  # Advanced analytics
        namespaces.add("_event")  # Events
        namespaces.add("_alarms")  # Alarms
        namespaces.add("_dpp")  # Digital Product Passports

    return namespaces
