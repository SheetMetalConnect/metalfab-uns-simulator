# Topic Reference

All topics are prefixed with `umh/v1/metalfab/`.

## Per-Machine Topics

```
{site}/{department}/{machine}/
  Asset/              (Level 2+, retained, published once)
    AssetID           int
    Name              string
    OEM               string
    Model             string
    InService         string (date)
    SerialNumber      string
    MachineType       string

  Edge/               (Level 1+, NOT retained, every tick)
    State             int (0-7, PackML)
    StateName         string ("EXECUTE", "IDLE", etc.)
    Infeed            int
    Outfeed           int
    Waste             int
    {sensor}          float (varies by machine type, see below)
    ShopFloor         JSON (Level 2+, retained — job context)

  Line/               (Level 2+, retained, every tick)
    Infeed            int
    Outfeed           int
    Waste             int
    State             int
    PartsProduced     int
    PartsScrap        int
    OEE/
      Availability    float (0-1)
      Performance     float (0-1)
      Quality         float (0-1)
      OEE             float (0-1)
      DowntimeMinutes float
      IdleMinutes     float
      ShiftDurationMinutes float

  Dashboard/          (Level 3+, retained)
    Asset             JSON {AssetID, Name, OEM, State}
    Job               JSON {JobID, Customer, Progress, Priority, DueDate}
    OEE               JSON {Availability, Performance, Quality, OEE, DowntimeMinutes, ...}
```

### Edge Sensors by Machine Type

| Machine Type | Sensors |
|-------------|---------|
| laser_cutter | LaserPower (float), CuttingSpeed (int), AssistGas (float), FocalPosition (float), SheetTemp (float) |
| press_brake | Tonnage (float), BendAngle (float), StrokePosition (float), BackgaugePos (float) |
| robot_weld / manual_weld | WeldCurrent (float), WeldVoltage (float), WireFeed (float), GasFlow (float), ArcTime (int) |
| powder_coating_line | OvenTemp (float), BoothHumidity (float), ConveyorSpeed (float), PowderFlow (float) |
| assembly, agv, quality_control | Power (float), Status (int) |

## Site-Level Topics

```
{site}/
  ERP/                            (Level 3+)
    ProductionOrder/{JobID}       JSON — active orders
    SalesOrder/New                JSON — new order events (streaming)
    Inventory/{MaterialCode}      JSON — stock levels

  MES/                            (Level 3+)
    Quality/{machine}             JSON — quality %, defect rate
    Delivery                      JSON — on-time %
    Utilization                   JSON — fleet utilization, bottleneck
    WIP                           JSON — work-in-progress value

  Energy/
    Asset/SolarCapacityKWp        float (retained)
    Edge/ConsumptionKW            float (streaming)
    Edge/SolarGenerationKW        float (streaming)
    Edge/GridImportKW             float (streaming)
    Line/ConsumptionKWh           float (retained)
    Line/SolarKWh                 float (retained)
    Line/CostEUR                  float (retained)
    Dashboard/Summary             JSON (retained)

  _dpp/                           (Level 4)
    passports/{dpp_id}/metadata   JSON
    passports/{dpp_id}/carbon_footprint  JSON
    passports/{dpp_id}/traceability      JSON
    passports/{dpp_id}/certifications    JSON
    passports/{dpp_id}/summary           JSON
    events/{event_type}/{dpp_id}         JSON (streaming)
```

## Historian-Ready Topics

These publish a single numeric value every tick (~1s) and can be written directly to TimescaleDB/InfluxDB without parsing.

**Machine topics** (per machine):
- `Edge/State`, `Edge/Infeed`, `Edge/Outfeed`, `Edge/Waste`, all Edge sensors
- `Line/Infeed`, `Line/Outfeed`, `Line/Waste`, `Line/State`, `Line/PartsProduced`, `Line/PartsScrap`
- `Line/OEE/Availability`, `Line/OEE/Performance`, `Line/OEE/Quality`, `Line/OEE/OEE`
- `Line/OEE/DowntimeMinutes`, `Line/OEE/IdleMinutes`, `Line/OEE/ShiftDurationMinutes`

**Energy topics** (per site):
- `Energy/Edge/ConsumptionKW`, `Energy/Edge/SolarGenerationKW`, `Energy/Edge/GridImportKW`
- `Energy/Line/ConsumptionKWh`, `Energy/Line/SolarKWh`, `Energy/Line/CostEUR`

Everything else (Dashboard/*, ERP/*, MES/*, _dpp/*) publishes JSON and needs parsing before historization.
