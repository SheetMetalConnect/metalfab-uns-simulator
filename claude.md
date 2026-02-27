# MetalFab UNS Simulator - Claude Code Context

## Project Overview

MQTT-based Unified Namespace (UNS) simulator for High-Mix Low-Volume (HMLV) metalworking and sheet metal fabrication environments. Generates realistic manufacturing data following ISA-95/PackML standards compatible with United Manufacturing Hub (UMH).

## Quick Commands

```bash
# Install
pip install -e .

# Run simulator (Level 2 default)
metalfab-sim run

# Run with specific level
metalfab-sim run --level 3

# Dry run (no MQTT)
metalfab-sim run --dry-run

# Subscribe to messages
metalfab-sim subscribe

# Change level via MQTT
metalfab-sim set-level --level 4
```

## Complexity Levels

The simulator supports 4 complexity levels, controlled via MQTT topic subscription:

| Level | Name | Features | Namespaces |
|-------|------|----------|------------|
| 1 | Sensors | Stateless sensor data only | `_historian` |
| 2 | Stateful | + MQTT retain, jobs, positions | + `_state`, `_meta`, `_jobs` |
| 3 | ERP/MES | + Quality, margins, lead times, OEE, dashboards | + `_erp`, `_mes`, `_dashboard` |
| 4 | Full | + DPP, analytics, events, alarms | + `_analytics`, `_event`, `_alarms`, `_dpp` |

### Change Level at Runtime

Publish to: `umh/v1/{enterprise}/{site}/_control/level`
```json
{"level": 3}
```

## Digital Product Passports (DPP) - Level 4

At **Level 4**, the simulator generates EU-compliant **Digital Product Passports** for every manufactured product with complete traceability and CO2 emissions tracking.

### Features

- **CO2 Emissions Tracking**: Complete carbon footprint from material to shipping
  - Material embodied carbon (kg CO2/kg by material type)
  - Processing emissions per operation (based on energy consumption)
  - Transport emissions (truck/rail/ship)
  - Grid carbon intensity (g CO2/kWh)
  - Renewable energy percentage

- **Complete Traceability**: Full production history
  - All manufacturing operations (cutting, forming, welding, coating, assembly)
  - Machine IDs, operator names, timestamps, durations
  - Process parameters (laser power, bend angles, weld settings)
  - Quality checks (dimensional, visual, functional)
  - Parts produced and scrap rates

- **Event Notifications**: Real-time event stream for external systems
  - `DPP_CREATED` - When manufacturing starts
  - `OPERATION_STARTED` - Operation begins
  - `OPERATION_COMPLETED` - Operation finished (includes CO2)
  - `QUALITY_CHECKED` - Quality inspection performed
  - `DPP_FINALIZED` - Product completed
  - `DPP_SHIPPED` - Product shipped

- **EU Compliance**: Regulatory data
  - REACH, RoHS, CE marking compliance
  - ISO certifications (9001, 14001)
  - Recyclability score (0-100)
  - Expected lifetime
  - Recycling instructions

### Topic Structure

```
umh/v1/{enterprise}/{site}/_dpp/
  ├── passports/{dpp_id}/           # Individual passport data (retained)
  │   ├── metadata                  # Product info, customer, job ID
  │   ├── carbon_footprint          # Total CO2 + breakdown by operation
  │   ├── traceability              # Complete operations history
  │   ├── certifications            # Compliance & circularity data
  │   └── summary                   # Dashboard view
  └── events/                       # Event notifications (non-retained)
      ├── dpp_created/{dpp_id}
      ├── operation_completed/{dpp_id}
      ├── quality_checked/{dpp_id}
      ├── dpp_finalized/{dpp_id}
      └── dpp_shipped/{dpp_id}
```

### Example DPP Data

**Carbon Footprint:**
```json
{
  "total_co2_kg": 12.4567,
  "breakdown": {
    "material_co2_kg": 7.5000,
    "manufacturing": {
      "cutting_co2_kg": 1.2340,
      "forming_co2_kg": 0.8750,
      "welding_co2_kg": 1.4567,
      "coating_co2_kg": 0.8900
    },
    "transport_co2_kg": 0.5010
  },
  "grid_info": {
    "carbon_intensity_g_per_kwh": 350.0,
    "renewable_energy_pct": 30.0
  },
  "co2_equivalent": {
    "trees_needed_to_offset": 593.2,
    "km_driven_equivalent": 103.8
  }
}
```

**Event Notification:**
```json
{
  "event_type": "OPERATION_COMPLETED",
  "dpp_id": "DPP-20250128-12345",
  "job_id": "JOB_8742",
  "product_name": "Hydraulic Manifold Block",
  "customer": "Bosch Rexroth",
  "status": "IN_PROGRESS",
  "timestamp": "2025-01-28T21:45:32Z",
  "operation_type": "LASER_CUTTING",
  "machine_id": "laser_01",
  "co2_kg": 1.2340
}
```

### External System Integration

External services can subscribe to DPP events:

```python
# Subscribe to all DPP events
client.subscribe("umh/v1/metalfab/+/_dpp/events")

# Subscribe to specific events
client.subscribe("umh/v1/metalfab/+/_dpp/events/dpp_finalized/#")
client.subscribe("umh/v1/metalfab/+/_dpp/events/operation_completed/#")
```

Use cases:
- **ERP/MES integration**: Receive real-time production updates
- **Sustainability reporting**: Track carbon emissions per product
- **Supply chain transparency**: Share DPP with customers
- **Quality management**: Alert on quality check failures
- **Logistics**: Notify when products are shipped

## Update Frequencies & Retention Policy

The simulator uses realistic update intervals that mirror real industrial systems:

### Update Intervals (1 second tick default)

| Data Type | Interval | Reason |
|-----------|----------|--------|
| Sensors (_historian) | 1s | Real-time process data |
| Machine states (_state) | 1s | PackML state machine updates |
| Jobs (_jobs) | 1s | Position tracking |
| Solar power | 5s | Power generation readings |
| Operators | 30s | Attendance updates |
| **ERP data** | **Random 10-60s** | Business system integration (variable latency) |
| **MES quality** | **Random 10-60s** | Quality aggregations (periodic calculations) |
| **OEE** | **Random 10-60s** | Performance calculations (batch processing) |
| **Delivery metrics** | **Random 10-60s** | Logistics metrics (batch updates) |
| **Inventory** | **Random 10-60s** | Stock levels (periodic sync) |
| **Dashboard** | **Random 10-60s** | Summary updates for consumers |
| **Analytics** | **Random 60-180s** | Advanced calculations (heavy processing) |
| **Powder coating planning** | **Random 10-60s** | MES scheduling updates |

### MQTT Retention Policy

Retained topics (keep last value):
- ✅ Asset metadata (`_meta/*`) - Asset identifications
- ✅ Machine states (`_state`) - Current state
- ✅ Active jobs (`_jobs/active/*`) - Job positions
- ✅ Dashboard (`_dashboard/*`) - Summary views
- ✅ Individual inventory items (`_erp/inventory/{item}`) - Stock reference
- ✅ Raw material summary (`_erp/inventory/raw_materials`) - Inventory reference

Non-retained topics (transient):
- ❌ Sensor data (`_historian/*`) - Time-series data
- ❌ ERP energy metrics (`_erp/energy`) - Aggregated transient data
- ❌ MES quality (`_mes/quality/*`) - Calculated metrics
- ❌ OEE (`_mes/oee/*`) - Calculated metrics
- ❌ Delivery metrics (`_erp/delivery`) - Aggregated data
- ❌ Inventory summary (`_erp/inventory`) - WIP calculations
- ❌ Utilization (`_mes/utilization`) - Fleet metrics
- ❌ Analytics (`_analytics/*`) - Periodic calculations
- ❌ Attendance (`_mes/attendance`) - Summary data
- ❌ Solar summary (`_erp/energy/solar`) - Energy metrics

## Shared Resources

### Powder Coating Line (Eindhoven)

The simulator includes a **shared powder coating line** located in Eindhoven that serves all facilities (Eindhoven, Roeselare, Brasov). This demonstrates:

- **Multi-facility planning**: Orders from different sites queue at a central resource
- **RAL color management**: 10 standard RAL colors with automatic batching
- **Simple MES scheduler**: Groups orders by color to minimize changeovers
- **Hook/traversal tracking**: Parts hung on hangers moving through 7 zones
- **Planning visibility**: Shows queue from each facility

#### Zones

1. **LOADING** - Parts hung on hangers/traversals (60s)
2. **PRE_TREATMENT** - Wash, phosphate, rinse (5 min)
3. **DRYING_OVEN** - Pre-dry at 120°C (10 min)
4. **COATING_BOOTH** - Powder application with electrostatic guns (2 min)
5. **CURING_OVEN** - Cure at 190°C (20 min)
6. **COOLING** - Cool down (5 min)
7. **UNLOADING** - Parts removed from hooks (60s)

#### Available RAL Colors

- RAL 9005 (Jet Black), RAL 9016 (Traffic White)
- RAL 7035 (Light Grey), RAL 7016 (Anthracite Grey)
- RAL 5010 (Gentian Blue), RAL 3000 (Flame Red)
- RAL 1023 (Traffic Yellow), RAL 6005 (Moss Green)
- RAL 2004 (Pure Orange), RAL 9006 (White Aluminium)

#### Topic Structure

```
# Line-specific topics (in Eindhoven)
finishing/coating_line_01/
  ├── _meta/line                           # Metadata (retained)
  ├── _state/summary                       # Zone summary (retained)
  ├── _state/booth                         # Booth state (retained)
  ├── _state/traversals/{traversal_id}     # Individual parts on hooks (retained)
  ├── _historian/booth                     # Booth sensors (streaming)
  ├── _historian/drying_oven               # Oven sensors (streaming)
  ├── _historian/curing_oven               # Oven sensors (streaming)
  └── _mes/planning/
      ├── summary                          # Planning summary (retained)
      ├── queue                            # Order queue (streaming)
      └── facility/{facility}              # Per-facility orders (streaming)

# Enterprise-level shared resource topics
_meta/shared_resources/powder_coating      # Shared resource info (retained)
_mes/shared_resources/powder_coating/planning  # Enterprise planning view (retained)
```

#### Example Planning Message

```json
{
  "line_id": "COAT_LINE_01",
  "location": "eindhoven",
  "shared_resource": true,
  "current_color": {
    "ral_code": "RAL 9005",
    "ral_name": "Jet Black",
    "ral_hex": "#0A0A0A"
  },
  "statistics": {
    "orders_queued": 5,
    "orders_scheduled": 3,
    "orders_active": 1,
    "orders_completed_today": 12
  },
  "facility_breakdown": {
    "eindhoven": {"queued_count": 2, "scheduled_count": 1, "active_count": 1},
    "roeselare": {"queued_count": 2, "scheduled_count": 1, "active_count": 0},
    "brasov": {"queued_count": 1, "scheduled_count": 1, "active_count": 0}
  },
  "next_color_changeover": {
    "from": {"code": "RAL 9005", "name": "Jet Black"},
    "to": {"code": "RAL 7035", "name": "Light Grey"},
    "changeover_time_min": 45
  }
}
```

## Architecture

```
src/metalfab_uns_sim/
├── __init__.py          # Package exports
├── cli.py               # Click CLI commands
├── complexity.py        # Level definitions and features
├── config.py            # YAML config loading
├── generators.py        # Sensor, Job, ERP/MES, Shared Resource generators
├── mqtt_client.py       # MQTT publish/subscribe with buffering
└── simulator.py         # Main orchestrator with PackML states
```

## Topic Structure

```
umh/v1/{enterprise}/{site}/{area}/{cell}/{namespace}/{...}
```

Example topics:
- `umh/v1/acme_metalworks/plant_vienna/cutting/laser_01/_historian/process/laser_power_pct`
- `umh/v1/acme_metalworks/plant_vienna/cutting/laser_01/_state`
- `umh/v1/acme_metalworks/plant_vienna/_jobs/active/JOB_9942`
- `umh/v1/acme_metalworks/plant_vienna/_erp/energy`
- `umh/v1/acme_metalworks/plant_vienna/_mes/quality/weld_cell_01`

## Key Classes

### ComplexityLevel (complexity.py)
Enum defining the 4 levels. Use `get_features_for_level()` to get enabled features.

### PackMLState (generators.py)
ISA-88/PackML compliant state machine:
- STOPPED, IDLE, STARTING, EXECUTE, COMPLETING, COMPLETED
- RESETTING, HOLDING, HELD, UNHOLDING
- SUSPENDING, SUSPENDED, UNSUSPENDING
- ABORTING, ABORTED, CLEARING, STOPPING

### SensorGenerator (generators.py)
Generates realistic sensor values with configurable noise, drift, and state-dependent behavior.

### Job (generators.py)
Manufacturing job with routing, quantities, ERP enrichment (margins, lead times, costs).

### MQTTClient (mqtt_client.py)
Paho MQTT wrapper with:
- Publish buffering
- Level-based message filtering
- Control topic subscription for runtime level changes

### Simulator (simulator.py)
Main orchestrator that:
- Manages cell states (PackML state machine)
- Generates and routes jobs through cells
- Publishes data based on current complexity level

## Data Examples (Level 3+)

```
JOB_9942 [STATUS: BENDING] // LEAD_TIME: 2.3d ahead
ENERGY [KWH_TODAY: 847] // COST_PER_ORDER: €12.40
WELD_CELL_01 [QUALITY: 99.2%] // DEFECT_RATE: 0.8%
LASER_01 [OEE: 94%] // IDLE_TIME: 12min
DELIVERY [ON_TIME: 97.3%] // LATE_ORDERS: 2
QUOTE_9943 [MARGIN: 34%] // EST_VS_ACTUAL: +2.1h
MACHINE_UTIL [FLEET: 78%] // BOTTLENECK: PRESS_02
INVENTORY [WIP: €34k] // TURNS: 12.4/yr
```

## Configuration

Main config: `config/config.yaml`
```yaml
mqtt:
  broker: localhost
  port: 1883

uns:
  enterprise: acme_metalworks
  site: plant_vienna
  topic_prefix: umh/v1

simulation:
  tick_interval_ms: 1000
  time_acceleration: 1.0
  initial_level: 2
```

Environment variables override config:
- `MQTT_BROKER`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`
- `UNS_ENTERPRISE`, `UNS_SITE`
- `SIMULATION_LEVEL`

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=metalfab_uns_sim

# Run specific test file
pytest tests/test_generators.py
```

## Default Assets

The simulator includes default metalworking assets:
- **Cutting**: 2x laser cutters (TRUMPF fiber/CO2)
- **Forming**: 2x press brakes (TRUMPF 320T/170T)
- **Welding**: 2x robot weld cells (KUKA MIG, ABB TIG)
- **Finishing**: 1x powder coating booth (Nordson)
- **Logistics**: 1x AGV (MiR250)

## Dependencies

- `paho-mqtt>=2.0.0` - MQTT client
- `pyyaml>=6.0` - Config parsing
- `click>=8.0` - CLI
- `faker>=20.0` - Realistic data generation
- `numpy>=1.24` - Statistical distributions

## References

- [UMH Data Model](https://umh.docs.umh.app/docs/datamodel/)
- [ISA-95 Standard](https://www.isa.org/standards-and-publications/isa-standards)
- [PackML State Model](https://www.omac.org/packml)
- [PackML-MQTT-Simulator](https://github.com/libremfg/PackML-MQTT-Simulator) - Reference implementation
