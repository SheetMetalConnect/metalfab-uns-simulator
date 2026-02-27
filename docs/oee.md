# OEE Calculation

OEE is calculated from real machine state accumulators, not random numbers.

```
OEE = Availability x Performance x Quality
```

## Components

**Availability** = Time in EXECUTE / Total shift time elapsed

The machine tracks seconds spent in EXECUTE, IDLE, and HELD per 8-hour shift. Only EXECUTE counts as productive.

**Performance** = Actual output / (Ideal rate x Execute hours)

Each machine type has an ideal cycle rate (parts/hour). Performance compares actual output against what should have been produced in the time the machine was running.

**Quality** = (Good parts - Scrap) / (Good parts + Scrap)

Tracked per shift from outfeed and waste counters.

## Published Topics

Per machine at `Line/OEE/`:

| Topic | Type | Description |
|-------|------|-------------|
| Availability | float 0-1 | Run time fraction |
| Performance | float 0-1 | Speed fraction |
| Quality | float 0-1 | Good parts fraction |
| OEE | float 0-1 | A x P x Q |
| DowntimeMinutes | float | Time in HELD (breakdown) this shift |
| IdleMinutes | float | Time in IDLE this shift |
| ShiftDurationMinutes | float | Elapsed shift time |

Same data is also in `Dashboard/OEE` as a JSON object.

## State Transitions

- IDLE -> STARTING (10% chance per tick)
- STARTING -> EXECUTE (next tick)
- EXECUTE -> COMPLETING (2% chance) or HELD (0.3% chance, breakdown)
- HELD -> EXECUTE (10% chance, recovery)
- COMPLETING -> IDLE

Shift resets after 8 hours (all accumulators zero out).

## Ideal Cycle Rates

| Machine Type | Parts/Hour |
|-------------|-----------|
| laser_cutter | 30 |
| press_brake | 45 |
| robot_weld | 20 |
| manual_weld | 12 |
| assembly | 25 |
| powder_coating_line | 15 |
| quality_control | 40 |
| agv | 60 |
