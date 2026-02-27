# Architecture

## Sites

```
                    MetalFab BV (Enterprise)
                           |
          +----------------+----------------+
          |                |                |
    +-----------+    +-----------+    +-----------+
    | Eindhoven |    | Roeselare |    |   Brasov  |
    |    (NL)   |    |    (BE)   |    |    (RO)   |
    | HQ + Mfg  |    | Full Mfg  |    |  Welding  |
    +-----------+    +-----------+    +-----------+
    | 2x Laser  |    | 2x Laser  |    | 3x Robot  |
    | 2x Press  |    | 1x Press  |    |   Weld    |
    | 1x Assemb |    | 2x Robot  |    | 2x Manual |
    | 2x AGV    |    |   Weld    |    |   Weld    |
    |           |    | 1x Coating|    | 2x Assemb |
    | 230 kWp   |    |   Line    |    | 1x QC CMM |
    | Solar     |    | 1x Assemb |    |           |
    |           |    | 180 kWp   |    | 50 kWp    |
    | 380 g/kWh |    | 160 g/kWh |    | 260 g/kWh |
    +-----------+    +-----------+    +-----------+
```

22 machines total. Grid carbon intensity varies by country (NL gas, BE nuclear, RO hydro).

## Complexity Levels

| Level | Name | Namespaces Added |
|-------|------|-----------------|
| 0 | Paused | None |
| 1 | Sensors | `Edge/` |
| 2 | Stateful | + `Line/`, `Asset/`, `ShopFloor/` |
| 3 | ERP/MES | + `ERP/`, `MES/`, `Dashboard/` |
| 4 | Full | + `_dpp/`, `_analytics`, `_event`, `_alarms` |

Default is level 2. Change at runtime via `metalfab-sim/control/level`.

## Machine Types

| Type | OEM | Ideal Rate (parts/hr) |
|------|-----|----------------------|
| laser_cutter | TRUMPF | 30 |
| press_brake | TRUMPF | 45 |
| robot_weld | KUKA / ABB | 20 |
| manual_weld | Lincoln Electric | 12 |
| assembly | Custom | 25 |
| powder_coating_line | Wagner | 15 |
| quality_control | Zeiss | 40 |
| agv | Jungheinrich | 60 |

## PackML States

| Value | Name | Meaning |
|-------|------|---------|
| 0 | STOPPED | Not running |
| 1 | STARTING | Transitioning to run |
| 2 | IDLE | Waiting for job |
| 3 | EXECUTE | Producing |
| 4 | COMPLETING | Finishing job |
| 5 | HELD | Breakdown |
| 6 | SUSPENDED | External hold |
| 7 | ABORTED | Fault |

## Source Structure

```
src/metalfab_uns_sim/
  cli.py               CLI commands
  complexity.py         Level definitions and feature flags
  config.py             YAML config loading
  digital_passport.py   DPP generation (Level 4)
  facilities.py         Site definitions (machines, energy, carbon)
  generators.py         Sensor data, job routing, PackML states
  mqtt_client.py        MQTT publish/subscribe
  multi_site.py         Main orchestrator (Docker entry point)
  simulator.py          Legacy single-site orchestrator
```
