# MetalFab UNS Simulator

MQTT-based Unified Namespace simulator for a multi-site metal fabrication company. 22 machines across 3 European sites, ISA-95 hierarchy, PackML state machines.

## Quick Start

```bash
git clone https://github.com/SheetMetalConnect/metalfab-uns-simulator
cd metalfab-uns-simulator
docker compose up -d --build
```

Simulator publishes to `umh/v1/metalfab/...` on port 1883. Verify:

```bash
mosquitto_sub -t "umh/v1/metalfab/#" -v
```

## Dashboards

Open `dashboards/index.html` in your browser. Connects to MQTT via WebSocket on port 8083.

Available dashboards:
- **OEE Deep Dive** — Single-machine A/P/Q breakdown, downtime Pareto, state timeline
- **Factory Overview** — All machines at a site with status, jobs, OEE
- **Powder Coating Line** — Zone tracking, RAL colors, process flow
- **Warehouse** — AGV fleet, inventory

## MCP Server (Claude Desktop)

Connect Claude to the simulator for natural language queries. See [mcp-server/README.md](mcp-server/README.md).

## Control

```bash
# Change complexity level (0=paused, 1=sensors, 2=stateful, 3=ERP/MES, 4=full+DPP)
mosquitto_pub -t "metalfab-sim/control/level" -m "3"

# Enable/disable sites
mosquitto_pub -t "metalfab-sim/control/site/brasov" -m "1"
mosquitto_pub -t "metalfab-sim/control/site/roeselare" -m "0"

# Clear all retained data
mosquitto_pub -t "metalfab-sim/control/clear" -m "1"

# Watch simulator status
mosquitto_sub -t "metalfab-sim/#" -v
```

## Local Development

```bash
pip install -e .
metalfab-sim run --level 3
metalfab-sim subscribe
pytest
```

## Reference

- [Topic Reference](docs/topics.md) — complete namespace tree, data types, retention
- [OEE Calculation](docs/oee.md) — how Availability, Performance, Quality are computed
- [Digital Product Passport](docs/dpp.md) — ESPR compliance, CO2 tracking
- [Architecture](docs/architecture.md) — site layout, machine types, complexity levels

## Use with UMH Core Stack

This simulator integrates with [Luke's UMH Starter Kit](https://github.com/SheetMetalConnect/UMH-Core-Stack) — an opinionated, batteries-included UMH Core stack. The starter kit's historian flow automatically persists `_raw` sensor data from this simulator to TimescaleDB.

```bash
# From the UMH-Core-Stack repo
docker compose -f docker-compose.yaml -f examples/simulator/docker-compose.simulator.yaml up -d
```

## License

MIT
