# MetalFab Real-Time Dashboards

Browser-based dashboards that connect to MQTT via WebSocket for live factory monitoring. No backend required — pure client-side HTML/JS.

---

## Available Dashboards

| Dashboard | File | Description |
|-----------|------|-------------|
| Factory Overview | `eindhoven-premium.html` | All machines with sparklines, OEE, drill-down to OEE detail |
| OEE Deep Dive | `oee-dashboard.html` | Single-machine OEE drill-down: A/P/Q breakdown, downtime Pareto, state timeline |
| Powder Coating Line | `coating_line_dashboard.html` | Zone tracking, RAL colors, process flow |
| Warehouse & Logistics | `warehouse_dashboard.html` | AGV fleet, inventory, material flow |
| Landing Page | `index.html` | Dashboard launcher with MQTT connection status |

---

## Quick Start

### Prerequisites

1. HiveMQ running with WebSocket on port 8083:
   ```bash
   docker ps | grep hivemq
   ```

2. Simulator running at level 3+:
   ```bash
   metalfab-sim run --level 3
   ```

### Open a Dashboard

```bash
open dashboards/eindhoven-premium.html
```

Or use the launcher:
```bash
bash dashboards/launch-dashboard.sh
```

---

## Architecture

```
Simulator ──MQTT (1883)──▶ HiveMQ ◀──WebSocket (8083)── Dashboard (Browser)
```

- Simulator publishes to MQTT broker on `localhost:1883`
- Dashboards connect via WebSocket on `localhost:8083`
- Updates flow directly to browser — no polling, no backend

---

## MQTT Topics Consumed

```
umh/v1/metalfab/eindhoven/+/+/Dashboard/#   → Asset, Job, OEE summaries
umh/v1/metalfab/eindhoven/+/+/Line/State     → PackML state number
umh/v1/metalfab/eindhoven/+/+/Edge/StateName → State name (IDLE, EXECUTE, etc.)
```

The coating line dashboard additionally subscribes to:
```
umh/v1/metalfab/eindhoven/finishing/coating_line_01/Dashboard/#
umh/v1/metalfab/eindhoven/finishing/coating_line_01/Line/#
umh/v1/metalfab/eindhoven/finishing/coating_line_01/Edge/#
```

---

## Status Colors

| State | Color | Meaning |
|-------|-------|---------|
| EXECUTE | Green | Running production |
| IDLE | Yellow | Waiting for job |
| STARTING | Blue | Starting up |
| COMPLETING | Blue | Finishing cycle |
| HELD | Orange | Paused (breakdown) |
| SUSPENDED | Purple | Suspended |
| STOPPED | Red | Stopped |
| ABORTED | Red | Faulted |

---

## Configuration

Each dashboard has constants at the top of the file:

```javascript
const MQTT_BROKER = 'ws://localhost:8083/mqtt';
const SITE = 'eindhoven';
```

Change these to point to a different broker or site.

---

## Troubleshooting

**Dashboard shows "Connecting..." forever**
- Verify HiveMQ is running: `docker ps | grep hivemq`
- Check port 8083 is exposed (WebSocket listener)
- Open browser console (F12) for connection errors

**No machines appearing**
- Check simulator is running and publishing data
- Verify site is enabled: `mosquitto_sub -t "umh/v1/metalfab/eindhoven/#" -v`

**Stale data**
- Check the "Last Update" timestamp in the dashboard header
- Verify the message counter is incrementing

---

## Security Note

These dashboards are for local development and demos only. No authentication, plain WebSocket (not WSS), client-side only. For production, add broker authentication and use WSS.

---

## License

MIT License — see parent project LICENSE file
