"""Configuration management for the simulator."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .complexity import ComplexityLevel


@dataclass
class MQTTConfig:
    """MQTT broker configuration."""

    broker: str = "localhost"
    port: int = 1883
    username: str = ""
    password: str = ""
    client_id: str = "metalfab-simulator"
    qos: int = 1


@dataclass
class UNSConfig:
    """Unified Namespace configuration."""

    enterprise: str = "acme_metalworks"
    site: str = "plant_vienna"
    topic_prefix: str = "umh/v1"


@dataclass
class SiteConfig:
    """Individual site configuration."""

    site_id: str
    enabled: bool = True
    name: str = ""
    country: str = ""


@dataclass
class SimulationConfig:
    """Simulation parameters."""

    tick_interval_ms: int = 1000
    tick_jitter_pct: int = 0  # Randomization ±% around tick_interval
    time_acceleration: float = 1.0
    random_seed: Optional[int] = None
    initial_level: int = 2  # Default to Level 2


@dataclass
class SensorConfig:
    """Sensor definition."""

    id: str
    name: str
    unit: str = ""
    min_value: float = 0.0
    max_value: float = 100.0
    noise_stddev: float = 1.0
    update_interval_ms: int = 1000


@dataclass
class CellConfig:
    """Machine cell configuration."""

    id: str
    name: str
    cell_type: str  # laser_cutter, press_brake, robot_weld, etc.
    oem: str = ""
    model: str = ""
    area_id: str = ""
    sensors: List[str] = field(default_factory=list)
    nominal_power_kw: float = 10.0
    cycle_time_range: tuple = (30, 300)


@dataclass
class AreaConfig:
    """Production area configuration."""

    id: str
    name: str
    cells: List[CellConfig] = field(default_factory=list)


@dataclass
class JobTemplateConfig:
    """Job template configuration."""

    id: str
    name: str
    routing: List[str] = field(default_factory=list)
    qty_range: tuple = (50, 200)
    customers: List[str] = field(default_factory=list)


@dataclass
class Config:
    """Main configuration container."""

    mqtt: MQTTConfig = field(default_factory=MQTTConfig)
    uns: UNSConfig = field(default_factory=UNSConfig)
    simulation: SimulationConfig = field(default_factory=SimulationConfig)
    sites: List[SiteConfig] = field(default_factory=list)
    areas: List[AreaConfig] = field(default_factory=list)
    job_templates: List[JobTemplateConfig] = field(default_factory=list)
    customers: List[str] = field(default_factory=list)

    @property
    def enabled_sites(self) -> List[SiteConfig]:
        """Get list of enabled sites."""
        return [s for s in self.sites if s.enabled]

    @classmethod
    def from_yaml(cls, config_path: Path) -> "Config":
        """Load configuration from YAML file."""
        if not config_path.exists():
            return cls.default()

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        return cls._from_dict(data)

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        config = cls.default()

        # Override MQTT settings from env
        config.mqtt.broker = os.getenv("MQTT_BROKER", config.mqtt.broker)
        config.mqtt.port = int(os.getenv("MQTT_PORT", config.mqtt.port))
        config.mqtt.username = os.getenv("MQTT_USERNAME", config.mqtt.username)
        config.mqtt.password = os.getenv("MQTT_PASSWORD", config.mqtt.password)

        # Override UNS settings
        config.uns.enterprise = os.getenv("UNS_ENTERPRISE", config.uns.enterprise)
        config.uns.site = os.getenv("UNS_SITE", config.uns.site)

        # Override simulation settings
        level = os.getenv("SIMULATION_LEVEL")
        if level:
            config.simulation.initial_level = int(level)

        return config

    @classmethod
    def default(cls) -> "Config":
        """Create default configuration with sample assets."""
        config = cls()

        # Default areas and cells
        config.areas = [
            AreaConfig(
                id="cutting",
                name="Cutting Department",
                cells=[
                    CellConfig(
                        id="laser_01",
                        name="Fiber Laser 6kW",
                        cell_type="laser_cutter",
                        oem="TRUMPF",
                        model="TruLaser 3030 fiber",
                        area_id="cutting",
                        sensors=[
                            "laser_power_pct",
                            "cutting_speed_mmpm",
                            "assist_gas_bar",
                            "power_kw",
                        ],
                        nominal_power_kw=45.0,
                        cycle_time_range=(30, 600),
                    ),
                    CellConfig(
                        id="laser_02",
                        name="CO2 Laser 4kW",
                        cell_type="laser_cutter",
                        oem="TRUMPF",
                        model="TruLaser 5030 classic",
                        area_id="cutting",
                        sensors=["laser_power_pct", "cutting_speed_mmpm", "power_kw"],
                        nominal_power_kw=35.0,
                        cycle_time_range=(45, 720),
                    ),
                ],
            ),
            AreaConfig(
                id="forming",
                name="Forming Department",
                cells=[
                    CellConfig(
                        id="press_brake_01",
                        name="Press Brake 320T",
                        cell_type="press_brake",
                        oem="TRUMPF",
                        model="TruBend 5320",
                        area_id="forming",
                        sensors=["tonnage_t", "bend_angle_deg", "stroke_mm", "power_kw"],
                        nominal_power_kw=25.0,
                        cycle_time_range=(15, 180),
                    ),
                    CellConfig(
                        id="press_brake_02",
                        name="Press Brake 170T",
                        cell_type="press_brake",
                        oem="TRUMPF",
                        model="TruBend 5170",
                        area_id="forming",
                        sensors=["tonnage_t", "bend_angle_deg", "power_kw"],
                        nominal_power_kw=18.0,
                        cycle_time_range=(10, 120),
                    ),
                ],
            ),
            AreaConfig(
                id="welding",
                name="Welding Department",
                cells=[
                    CellConfig(
                        id="weld_cell_01",
                        name="Robot Weld Cell MIG",
                        cell_type="robot_weld",
                        oem="KUKA",
                        model="KR 16-2",
                        area_id="welding",
                        sensors=[
                            "weld_current_a",
                            "weld_voltage_v",
                            "wire_feed_mpm",
                            "gas_flow_lpm",
                        ],
                        nominal_power_kw=15.0,
                        cycle_time_range=(60, 300),
                    ),
                    CellConfig(
                        id="weld_cell_02",
                        name="Robot Weld Cell TIG",
                        cell_type="robot_weld",
                        oem="ABB",
                        model="IRB 2600",
                        area_id="welding",
                        sensors=["weld_current_a", "weld_voltage_v", "gas_flow_lpm"],
                        nominal_power_kw=12.0,
                        cycle_time_range=(90, 450),
                    ),
                ],
            ),
            AreaConfig(
                id="finishing",
                name="Finishing Department",
                cells=[
                    CellConfig(
                        id="paint_booth_01",
                        name="Powder Coating Booth",
                        cell_type="paint_booth",
                        oem="Nordson",
                        model="Encore HD",
                        area_id="finishing",
                        sensors=["temp_c", "humidity_pct", "airflow_cfm"],
                        nominal_power_kw=8.0,
                        cycle_time_range=(120, 600),
                    ),
                ],
            ),
            AreaConfig(
                id="logistics",
                name="Logistics",
                cells=[
                    CellConfig(
                        id="agv_01",
                        name="AGV Transport 1",
                        cell_type="agv",
                        oem="MiR",
                        model="MiR250",
                        area_id="logistics",
                        sensors=["battery_pct", "speed_mps", "position_x", "position_y"],
                        nominal_power_kw=0.5,
                    ),
                ],
            ),
        ]

        # Default job templates
        config.job_templates = [
            JobTemplateConfig(
                id="bracket_assembly",
                name="Bracket Assembly",
                routing=["laser_01", "press_brake_01", "weld_cell_01", "paint_booth_01"],
                qty_range=(50, 200),
            ),
            JobTemplateConfig(
                id="enclosure_panel",
                name="Enclosure Panel",
                routing=["laser_02", "press_brake_02"],
                qty_range=(20, 100),
            ),
            JobTemplateConfig(
                id="welded_frame",
                name="Welded Frame",
                routing=["laser_01", "press_brake_01", "weld_cell_02"],
                qty_range=(10, 50),
            ),
        ]

        # Default customers
        config.customers = [
            "AutoCorp GmbH",
            "MechParts AG",
            "TechBuild Systems",
            "IndustriaWerk",
            "MetalPro BV",
        ]

        return config

    @classmethod
    def _from_dict(cls, data: Dict[str, Any]) -> "Config":
        """Create config from dictionary."""
        config = cls.default()

        # MQTT config
        if "mqtt" in data:
            mqtt_data = data["mqtt"]
            config.mqtt = MQTTConfig(
                broker=mqtt_data.get("broker", config.mqtt.broker),
                port=mqtt_data.get("port", config.mqtt.port),
                username=mqtt_data.get("username", config.mqtt.username),
                password=mqtt_data.get("password", config.mqtt.password),
                client_id=mqtt_data.get("client_id", config.mqtt.client_id),
                qos=mqtt_data.get("qos", config.mqtt.qos),
            )

        # UNS config
        if "uns" in data:
            uns_data = data["uns"]
            config.uns = UNSConfig(
                enterprise=uns_data.get("enterprise", config.uns.enterprise),
                site=uns_data.get("site", config.uns.site),
                topic_prefix=uns_data.get("topic_prefix", config.uns.topic_prefix),
            )

        # Simulation config
        if "simulation" in data:
            sim_data = data["simulation"]
            config.simulation = SimulationConfig(
                tick_interval_ms=sim_data.get(
                    "tick_interval_ms", config.simulation.tick_interval_ms
                ),
                tick_jitter_pct=sim_data.get(
                    "tick_jitter_pct", config.simulation.tick_jitter_pct
                ),
                time_acceleration=sim_data.get(
                    "time_acceleration", config.simulation.time_acceleration
                ),
                random_seed=sim_data.get("random_seed"),
                initial_level=sim_data.get("initial_level", config.simulation.initial_level),
            )

        # Top-level 'level' overrides simulation.initial_level
        if "level" in data:
            config.simulation.initial_level = int(data["level"])

        # Sites config
        if "sites" in data:
            config.sites = []
            for site_id, site_data in data["sites"].items():
                config.sites.append(
                    SiteConfig(
                        site_id=site_id,
                        enabled=site_data.get("enabled", True),
                        name=site_data.get("name", site_id),
                        country=site_data.get("country", ""),
                    )
                )

        return config

    def to_yaml(self, path: Path) -> None:
        """Save configuration to YAML file."""
        data = {
            "mqtt": {
                "broker": self.mqtt.broker,
                "port": self.mqtt.port,
                "username": self.mqtt.username,
                "password": self.mqtt.password,
                "client_id": self.mqtt.client_id,
                "qos": self.mqtt.qos,
            },
            "uns": {
                "enterprise": self.uns.enterprise,
                "site": self.uns.site,
                "topic_prefix": self.uns.topic_prefix,
            },
            "simulation": {
                "tick_interval_ms": self.simulation.tick_interval_ms,
                "tick_jitter_pct": self.simulation.tick_jitter_pct,
                "time_acceleration": self.simulation.time_acceleration,
                "random_seed": self.simulation.random_seed,
                "initial_level": self.simulation.initial_level,
            },
        }

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
