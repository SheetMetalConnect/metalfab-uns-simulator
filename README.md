# MetalFab UNS Simulator

A realistic MQTT-based **Unified Namespace (UNS)** simulator for a multi-site metal fabrication company. Generates production data following ISA-95 hierarchy and PackML state machines -- designed for board demos, dashboard development, and integration testing.

## Why UNS?

A Unified Namespace puts **all** manufacturing data -- sensors, jobs, ERP orders, quality metrics, energy -- into a single MQTT topic tree. Any system can subscribe to exactly the data it needs without point-to-point integrations. This simulator lets you experience that with realistic metalworking data from 3 European facilities.

## Quick Start

```bash
# Clone and run (Docker)
git clone https://github.com/SheetMetalConnect/metalfab-uns-simulator
cd metalfab-uns-simulator
docker compose up -d --build

# Or install locally
pip install -e .
metalfab-sim run --level 2
```

The simulator starts publishing to `umh/v1/metalfab/...` on your MQTT broker (port 1883). Open MQTT Explorer or subscribe:

```bash
mosquitto_sub -t "umh/v1/metalfab/#" -v
```

## Architecture

```
                    MetalFab BV (Enterprise)
                           │
          ┌────────────────┼────────────────┐
          │                │                │
    ┌─────┴──────┐  ┌─────┴──────┐  ┌──────┴─────┐
    │ Eindhoven  │  │ Roeselare  │  │   Brasov   │
    │    (NL)    │  │    (BE)    │  │    (RO)    │
    │ HQ + Mfg   │  │ Full Mfg   │  │  Welding   │
    ├────────────┤  ├────────────┤  ├────────────┤
    │ 2x Laser   │  │ 2x Laser   │  │ 3x Robot   │
    │ 2x Press   │  │ 1x Press   │  │   Weld     │
    │ 1x Assembly│  │ 2x Robot   │  │ 2x Manual  │
    │ 2x AGV     │  │   Weld     │  │   Weld     │
    │            │  │ 1x Coating │  │ 2x Assembly│
    │ 230 kWp    │  │   Line     │  │ 1x QC CMM  │
    │ Solar      │  │ 1x Assembly│  │            │
    │            │  │ 180 kWp    │  │ 50 kWp     │
    │ 380 g/kWh  │  │ 160 g/kWh  │  │ 260 g/kWh  │
    └────────────┘  └────────────┘  └────────────┘
```

**22 machines** across 3 sites, each with realistic sensor data, job tracking, OEE, and energy monitoring. Grid carbon intensity varies per country (NL gas-heavy, BE nuclear, RO hydro).

## Namespace Reference

Every machine publishes to 4 namespaces following ISA-95:

```
umh/v1/metalfab/{site}/{department}/{machine}/
├── Asset/          Static metadata (retained)
│   ├── AssetID, Name, OEM, Model, InService, SerialNumber, MachineType
│
├── Edge/           Real-time sensors (streaming, NOT retained)
│   ├── LaserPower, CuttingSpeed, AssistGas, SheetTemp   (laser_cutter)
│   ├── Tonnage, BendAngle, StrokePosition               (press_brake)
│   ├── WeldCurrent, WeldVoltage, WireFeed, GasFlow      (weld cells)
│   ├── State, StateName, Infeed, Outfeed, Waste
│   └── ShopFloor/   (Level 2+: job context, operator, material, ERP data)
│
├── Line/           Production data (retained)
│   ├── Infeed, Outfeed, Waste, State, PartsProduced, PartsScrap
│   └── OEE/
│       ├── Availability, Performance, Quality, OEE
│       ├── DowntimeMinutes, IdleMinutes, ShiftDurationMinutes
│
└── Dashboard/      Aggregated views (Level 3+, retained)
    ├── Asset       {AssetID, Name, OEM, State}
    ├── Job         {JobID, Customer, Progress, Priority, DueDate}
    └── OEE         {Availability, Performance, Quality, OEE, DowntimeMinutes, ...}
```

### Site-Level Topics

```
umh/v1/metalfab/{site}/
├── ERP/                          (Level 3+)
│   ├── ProductionOrder/{JobID}   Active orders with customer, quantities, progress
│   ├── SalesOrder/New            New sales order events (streaming)
│   └── Inventory/{MaterialCode}  Stock levels per material
│
├── MES/                          (Level 3+)
│   ├── Quality/{machine}         Quality %, defect rates
│   ├── Delivery                  On-time delivery performance
│   ├── Utilization               Fleet utilization, bottleneck machine
│   └── WIP                       Work-in-progress value, inventory turns
│
├── Energy/
│   ├── Asset/SolarCapacityKWp    Solar installation size
│   ├── Edge/                     Real-time kW (consumption, solar, grid import)
│   ├── Line/                     Daily totals (kWh, cost EUR)
│   └── Dashboard/Summary         Energy overview
│
└── _dpp/                         (Level 4 only)
    ├── passports/{dpp_id}/       ESPR-compliant Digital Product Passports
    └── events/                   DPP lifecycle events
```

### Powder Coating Line (Roeselare)

```
umh/v1/metalfab/roeselare/finishing/coating_line_01/
├── Edge/OvenTemp, BoothHumidity, ConveyorSpeed
├── Edge/CoatingBooth/CurrentRAL, CurrentColor, LastColorChange
├── Line/TraversalsInLine, PartsInLine, Zones/{zone}
└── Dashboard/Summary, Zones
```

## Complexity Levels

The simulator supports 5 levels (0-4), controllable at runtime via MQTT:

| Level | Name | What It Adds |
|-------|------|-------------|
| **0** | Paused | No data published |
| **1** | Sensors | `Edge/` raw sensor data only (streaming) |
| **2** | Stateful | + `Line/`, `Asset/`, `ShopFloor/` (retained state, jobs, OEE) |
| **3** | ERP/MES | + `ERP/`, `MES/`, `Dashboard/` (business data, quality, aggregations) |
| **4** | Full | + `_dpp/`, `_analytics`, `_event`, `_alarms` (DPP, advanced analytics) |

**Level 2** is the default -- good for dashboard development. **Level 3** adds ERP/MES context for business demos. **Level 4** enables Digital Product Passports with CO2 tracking.

## OEE Calculation

OEE is calculated from **real machine state**, not random numbers:

```
OEE = Availability × Performance × Quality
```

| Component | Formula | What It Measures |
|-----------|---------|-----------------|
| **Availability** | Run Time / Planned Time | How often the machine runs vs. sits idle or broken |
| **Performance** | Actual Output / (Ideal Rate × Run Time) | How fast it runs vs. theoretical maximum |
| **Quality** | Good Parts / Total Parts | How many parts are scrap |

The simulator tracks time spent in each PackML state (EXECUTE, IDLE, HELD) per 8-hour shift. Machines can randomly enter HELD state (breakdown) and recover, affecting Availability. Ideal cycle rates are defined per machine type (e.g., laser cutter: 30 parts/hour, press brake: 45 parts/hour).

Published per machine at `Line/OEE/`:
- `Availability`, `Performance`, `Quality`, `OEE` -- ratios 0-1
- `DowntimeMinutes` -- time in HELD state this shift
- `IdleMinutes` -- time in IDLE state this shift
- `ShiftDurationMinutes` -- elapsed time in current shift

## Digital Product Passport (Level 4)

At Level 4, the simulator generates **EU ESPR-compliant** Digital Product Passports for every manufactured product:

### ESPR Fields (EU Regulation 2024/1781)

| Field | Description | Example |
|-------|-------------|---------|
| `espr_uid` | GS1 SGTIN unique identifier | `urn:epc:id:sgtin:8712345.12345.123456789` |
| `data_carrier` | QR code with GS1 Digital Link | `https://id.metalfab.eu/01/08712345.../21/...` |
| `economic_operator` | Company name, EORI, address | MetalFab BV, NL123456789000 |
| `product_classification` | PRODCOM, HS, CN codes | 24.10.31 / 7208 / 7208 51 00 |
| `substances_of_concern` | CAS numbers, concentrations | Nickel (7440-02-0) 8.0% in stainless |
| `durability_score` | Product durability rating | 85.2 / 100 |
| `repairability_score` | Ease of repair rating | 62.0 / 100 |

### CO2 Tracking

Each DPP tracks carbon footprint with **site-specific grid carbon intensity**:

| Site | Grid Carbon | Renewable | Why |
|------|-------------|-----------|-----|
| Eindhoven (NL) | 380 g/kWh | 33% | Gas-heavy grid |
| Roeselare (BE) | 160 g/kWh | 25% | Nuclear-heavy grid |
| Brasov (RO) | 260 g/kWh | 44% | Hydro-heavy grid |

The same product manufactured in Roeselare has **less than half** the manufacturing CO2 footprint vs. Eindhoven -- demonstrating how location affects sustainability.

### DPP Events

External systems can subscribe to real-time DPP lifecycle events:

```bash
# All DPP events
mosquitto_sub -t "umh/v1/metalfab/+/_dpp/events/#" -v

# Only finalized products
mosquitto_sub -t "umh/v1/metalfab/+/_dpp/events/dpp_finalized/#" -v
```

Event types: `DPP_CREATED`, `OPERATION_COMPLETED`, `DPP_FINALIZED`, `DPP_SHIPPED`

## Historian-Ready Topics

A historian (TimescaleDB, InfluxDB) needs a **single numeric value per topic, on a consistent cadence**. JSON objects, strings, and event-driven payloads cannot be written directly to a time-series column -- they need parsing first.

The topics below all publish one `int` or `float` every tick (~1s). All topic paths are prefixed with `umh/v1/metalfab/`.

### Machine Topics (per machine, every tick)

All Level 1+:

| Topic | Type | Retain | Notes |
|-------|------|--------|-------|
| `{site}/{dept}/{machine}/Edge/State` | int | no | PackML state code (0=STOPPED .. 7=ABORTED) |
| `{site}/{dept}/{machine}/Edge/Infeed` | int | no | Streaming duplicate of Line/ counters |
| `{site}/{dept}/{machine}/Edge/Outfeed` | int | no | |
| `{site}/{dept}/{machine}/Edge/Waste` | int | no | |

Edge sensors vary by machine type (all float, not retained):

| Machine Type | Sensors |
|-------------|---------|
| `laser_cutter` | `LaserPower`, `CuttingSpeed` (int), `AssistGas`, `FocalPosition`, `SheetTemp` |
| `press_brake` | `Tonnage`, `BendAngle`, `StrokePosition`, `BackgaugePos` |
| `robot_weld` / `manual_weld` | `WeldCurrent`, `WeldVoltage`, `WireFeed`, `GasFlow`, `ArcTime` (int) |
| `powder_coating_line` | `OvenTemp`, `BoothHumidity`, `ConveyorSpeed`, `PowderFlow` |
| other (`assembly`, `agv`, `quality_control`) | `Power`, `Status` (int) |

All Level 2+ (retained):

| Topic | Type | Notes |
|-------|------|-------|
| `{site}/{dept}/{machine}/Line/Infeed` | int | Cumulative parts in |
| `{site}/{dept}/{machine}/Line/Outfeed` | int | Cumulative good parts out |
| `{site}/{dept}/{machine}/Line/Waste` | int | Cumulative scrap |
| `{site}/{dept}/{machine}/Line/State` | int | Same value as Edge/State, but retained |
| `{site}/{dept}/{machine}/Line/PartsProduced` | int | Lifetime total (not shift-reset) |
| `{site}/{dept}/{machine}/Line/PartsScrap` | int | Lifetime total |
| `{site}/{dept}/{machine}/Line/OEE/Availability` | float | 0.0 - 1.0, calculated from state time |
| `{site}/{dept}/{machine}/Line/OEE/Performance` | float | 0.0 - 1.0, actual vs. ideal rate |
| `{site}/{dept}/{machine}/Line/OEE/Quality` | float | 0.0 - 1.0, good / total |
| `{site}/{dept}/{machine}/Line/OEE/OEE` | float | A x P x Q |
| `{site}/{dept}/{machine}/Line/OEE/DowntimeMinutes` | float | Time in HELD state this shift |
| `{site}/{dept}/{machine}/Line/OEE/IdleMinutes` | float | Time in IDLE state this shift |
| `{site}/{dept}/{machine}/Line/OEE/ShiftDurationMinutes` | float | Elapsed time in current shift |

### Energy Topics (per site, every tick)

| Topic | Type | Retain | Notes |
|-------|------|--------|-------|
| `{site}/Energy/Edge/ConsumptionKW` | float | no | Current total draw |
| `{site}/Energy/Edge/SolarGenerationKW` | float | no | Current solar output |
| `{site}/Energy/Edge/GridImportKW` | float | no | Consumption minus solar |
| `{site}/Energy/Line/ConsumptionKWh` | float | yes | Running daily total |
| `{site}/Energy/Line/SolarKWh` | float | yes | Running daily total |
| `{site}/Energy/Line/CostEUR` | float | yes | Running daily cost |

### Coating Line Topics (Roeselare, every tick)

| Topic | Type | Retain | Notes |
|-------|------|--------|-------|
| `{site}/finishing/coating_line_01/Edge/OvenTemp` | float | no | Curing oven temperature |
| `{site}/finishing/coating_line_01/Edge/BoothHumidity` | float | no | Booth relative humidity |
| `{site}/finishing/coating_line_01/Edge/ConveyorSpeed` | float | no | m/min |
| `{site}/finishing/coating_line_01/Line/TraversalsInLine` | int | yes | Traversals across all zones |
| `{site}/finishing/coating_line_01/Line/PartsInLine` | int | yes | Parts on hooks |
| `{site}/finishing/coating_line_01/Line/Zones/Loading` | int | yes | Count per zone (6 topics) |
| `{site}/finishing/coating_line_01/Line/Zones/PreTreatment` | int | yes | |
| `{site}/finishing/coating_line_01/Line/Zones/Drying` | int | yes | |
| `{site}/finishing/coating_line_01/Line/Zones/Coating` | int | yes | |
| `{site}/finishing/coating_line_01/Line/Zones/Curing` | int | yes | |
| `{site}/finishing/coating_line_01/Line/Zones/Cooling` | int | yes | |

### Topics That Are NOT Historian-Ready

Everything else publishes JSON objects, strings, or fires on events rather than on a fixed cadence. These are useful for dashboards and applications, but need parsing before they can go into a time-series database.

| Topic | Payload | Why |
|-------|---------|-----|
| `Edge/ShopFloor` | JSON | 15+ mixed fields (strings, ints, timestamps) |
| `Edge/StateName` | string | "EXECUTE", "IDLE", etc. |
| `Dashboard/*` | JSON | Aggregated views. OEE data duplicates `Line/OEE/*` |
| `Asset/*` | string | Static metadata, published once at startup |
| `ERP/ProductionOrder/*` | JSON | Order details, mixed types, only while job is active |
| `ERP/SalesOrder/New` | JSON | Sporadic event (~50% chance per publish cycle) |
| `ERP/Inventory/*` | JSON | Stock snapshot with descriptions |
| `MES/Quality/*` | JSON | Per-machine quality. Contains numeric fields (`quality_pct`, `defect_rate_pct`) that could be extracted |
| `MES/Delivery` | JSON | Contains `on_time_pct` that could be extracted |
| `MES/Utilization` | JSON | Contains `fleet_utilization_pct` that could be extracted |
| `MES/WIP` | JSON | Contains `wip_value_eur` that could be extracted |
| `Energy/Dashboard/Summary` | JSON | Duplicates `Energy/Edge/*` and `Energy/Line/*` |
| `Edge/CoatingBooth/*` | string | RAL code, color name, timestamp |
| `_dpp/passports/*` | JSON | Full DPP documents (Level 4) |
| `_dpp/events/*` | JSON | Lifecycle events (Level 4) |

The MES/ERP JSON topics contain numeric fields that *could* be historized if you parse them out first (e.g., via Node-RED or a custom MQTT-to-DB transformer). The `Dashboard/` topics are intentionally redundant -- they exist for MQTT Explorer and simple dashboards that want a single JSON blob, while `Line/` and `Edge/` provide the same data as individual historian-ready values.

## Interactive Control

Control the simulator at runtime by publishing to MQTT topics:

### Set Complexity Level

```bash
# Set to Level 3 (ERP/MES + Dashboard)
mosquitto_pub -t "metalfab-sim/control/level" -m "3"

# Set to Level 4 (Full + DPP)
mosquitto_pub -t "metalfab-sim/control/level" -m "4"

# Pause all output
mosquitto_pub -t "metalfab-sim/control/level" -m "0"
```

### Toggle Sites On/Off

```bash
# Enable Brasov
mosquitto_pub -t "metalfab-sim/control/site/brasov" -m "1"

# Disable Eindhoven
mosquitto_pub -t "metalfab-sim/control/site/eindhoven" -m "0"
```

### Clear Retained Data

```bash
mosquitto_pub -t "metalfab-sim/control/clear" -m "1"
```

### Monitor Status

```bash
# Simulator status (level, sites, timestamp)
mosquitto_sub -t "metalfab-sim/#" -v
```

## Use Cases

| Audience | Use Case | Recommended Level |
|----------|----------|------------------|
| **Board / Management** | Demo what UNS looks like with real manufacturing data | Level 3 |
| **Dashboard Developers** | Build Grafana/Power BI dashboards against consistent topics | Level 2-3 |
| **Integration Engineers** | Test MQTT consumers, data pipelines, TimescaleDB sinks | Level 2 |
| **Sustainability Team** | DPP proof-of-concept with CO2 tracking across sites | Level 4 |
| **IIoT Architects** | ISA-95 hierarchy and namespace design reference | Level 2 |
| **Training / Education** | Teach UNS concepts with hands-on exercises | Level 1-3 |

## MCP Server for Claude Desktop

Connect Claude Desktop directly to your simulator for natural language queries:

```
"What is the OEE for laser_01 at Eindhoven?"
"Show me active production orders"
"Which machines are bottlenecks?"
```

See [mcp-server/README.md](mcp-server/README.md) for setup instructions.

## License

MIT License

## Contributing

Contributions welcome! Please read CONTRIBUTING.md first.
