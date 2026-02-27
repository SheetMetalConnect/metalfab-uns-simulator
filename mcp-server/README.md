# MetalFab UNS MCP Server

**Educational MQTT/UNS Interface for Claude Desktop**

This MCP server demonstrates industrial data access patterns for the MetalFab simulator, showcasing ISA-95 hierarchy and semantic namespace organization.

---

## Overview

Connect Claude Desktop to your local MetalFab simulator to explore real-time manufacturing data using natural language. This server is designed for **education** - it teaches concepts like:

- **Semantic UNS Organization** (Descriptive, Functional, Informative namespaces)
- **ISA-95 Hierarchy** (Enterprise → Site → Department → Machine)
- **Data Retention Patterns** (Streaming vs Retained messages)
- **Industrial Control via MQTT** (Level control, site toggle)

---

## Architecture

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   Claude Desktop    │────▶│   MetalFab MCP      │◀───▶│   MQTT Broker       │
│                     │ MCP │   Server            │MQTT │   (localhost:1883)  │
│   Natural Language  │     │                     │     │                     │
│   Queries           │     │   • Query tools     │     │   MetalFab          │
│                     │     │   • Control tools   │     │   Simulator         │
│                     │     │   • Search tools    │     │                     │
│                     │     │   • Self-reporting  │     │   + MCP Activity    │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
```

### Self-Reporting UNS Node

The MCP server publishes its own activity to the UNS, making it a **visible, observable node** in the manufacturing system. This demonstrates the UNS principle that all nodes should publish their state and activity.

**Published Topics:**

- `metalfab-sim/mcp_server/{client_id}/_meta/identity` (RETAINED)
  Server identity, version, capabilities, startup time

- `metalfab-sim/mcp_server/{client_id}/_state` (RETAINED)
  Current state: connected, idle, processing, reconnecting, shutdown

- `metalfab-sim/mcp_server/{client_id}/_event/tool_call` (STREAMING)
  Every tool invocation with arguments and results

- `metalfab-sim/mcp_server/{client_id}/_historian/activity` (STREAMING)
  Activity metrics: tool call counts, uptime, cache size

**Example Identity:**
```json
{
  "client_id": "metalfab-mcp-a1b2c3d4",
  "type": "mcp_server",
  "name": "MetalFab UNS MCP Server",
  "description": "Model Context Protocol server providing Claude AI access to the MetalFab UNS via MQTT",
  "version": "1.0.0",
  "started_at": "2026-01-28T10:30:45.123456",
  "broker": "localhost:1883",
  "capabilities": ["explore_uns", "list_topics", "get_topic", "search_topics", "get_dashboard", "control_simulator", "publish_message"],
  "subscriptions": ["#"]
}
```

**Example Tool Call Event:**
```json
{
  "timestamp": "2026-01-28T10:32:15.789012",
  "tool": "get_dashboard",
  "arguments": {"site": "eindhoven", "area": "cutting", "machine": "laser_01"},
  "result_summary": "Completed in 45.2ms | # Dashboard: LASER_01...",
  "call_count": 3
}
```

---

## Quick Start

### 1. Install Dependencies

```bash
cd mcp-server
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Start MetalFab Simulator

In another terminal:

```bash
cd ..
metalfab-sim run --level 3
```

The simulator must be running for the MCP server to have data to query.

### 3. Configure Claude Desktop

Edit your Claude Desktop config file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Add this configuration:

```json
{
  "mcpServers": {
    "metalfab-uns": {
      "command": "/ABSOLUTE/PATH/TO/mcp-server/venv/bin/python",
      "args": ["/ABSOLUTE/PATH/TO/mcp-server/src/metalfab_mcp_server.py"]
    }
  }
}
```

**Important**: Replace `/ABSOLUTE/PATH/TO/` with the actual path to your project directory.

To get the absolute path:
```bash
cd mcp-server
pwd  # Copy this path
```

### 4. Restart Claude Desktop

Quit and relaunch Claude Desktop to load the MCP server.

### 5. Verify It Works

In Claude Desktop, try these queries:

- "What is the structure of the MetalFab UNS?"
- "Show me the dashboard for laser_01 in Eindhoven cutting department"
- "What is the current simulator status?"
- "What ERP data is available for Eindhoven?"

---

## Tools Available

### 1. explore_uns_structure
Explore the hierarchical UNS organization by level:
- **Enterprise**: Top-level (metalfab)
- **Site**: Facilities (eindhoven, roeselare, brasov)
- **Department**: Production areas (cutting, forming, welding, etc.)
- **Machine**: Individual assets (laser_01, press_01, etc.)
- **Namespace**: Data types (Asset, Edge, Line, Dashboard, ERP, MES, Energy)

**Example**: "Show me all machines in the Eindhoven cutting department"

### 2. query_machine_dashboard
Get aggregated Dashboard views for a specific machine:
- **Asset** summary (OEM, model, state)
- **Job** summary (current job, progress, priority)
- **OEE** metrics (availability, quality, performance)

**Example**: "What is the OEE for laser_01 in Eindhoven?"

### 3. query_erp_data
Access enterprise-level data (Level 3+):
- **ProductionOrder**: Job orders, quantities, schedules, operators
- **Inventory**: Material stock levels, locations, BOMs

**Example**: "Show me active production orders for Eindhoven"

### 4. query_mes_data
Access manufacturing execution data (Level 3+):
- **Quality**: Defect rates per machine
- **Delivery**: On-time percentage, late orders
- **Utilization**: Fleet utilization, bottlenecks
- **WIP**: Work in progress value and turns

**Example**: "What is the quality status at Eindhoven?"

### 5. query_energy_data
Access energy monitoring data (all levels):
- **Asset**: Solar panel capacity
- **Edge**: Real-time consumption/generation (kW)
- **Line**: Daily totals (kWh)
- **Dashboard**: Aggregated summary with solar coverage %

**Example**: "Show me energy consumption for Roeselare"

### 6. control_simulator
Control the simulator remotely:
- **set_level**: Change complexity level (0-4)
- **toggle_site**: Enable/disable sites

**Example**: "Set simulator to level 4"

### 7. search_topics
Find topics using wildcards:
- `*laser*` - All topics containing "laser"
- `*Dashboard/OEE` - All OEE dashboard topics
- `*/Energy/*` - All energy topics

**Example**: "Find all topics related to welding"

### 8. get_simulator_status
Get current simulator state:
- Active complexity level
- Enabled/disabled sites
- Last update timestamp

**Example**: "What is the current simulator status?"

---

## Educational Concepts

### Namespace Types

The simulator uses **semantic namespace organization**:

#### Descriptive Namespace (Asset/)
Static metadata that rarely changes:
- OEM manufacturer
- Model number
- Serial number
- Installation date
- Nominal power rating

**MQTT**: RETAINED messages published once on startup

#### Functional Namespace (Edge/, Line/)
Real-time operational data:

**Edge/**: Raw sensor data (STREAMING, not retained)
- Laser power percentage
- Cutting speed
- Temperature readings
- Pressure values

**Line/**: Production counters (RETAINED)
- Infeed/outfeed counts
- Parts produced/scrap
- State (IDLE, EXECUTE, etc.)
- OEE metrics

#### Informative Namespace (Dashboard/)
Aggregated views for consumers (RETAINED):
- Asset summary objects
- Job summary objects
- OEE summary objects

#### Enterprise Namespaces (ERP/, MES/)
Site-level data (RETAINED, Level 3+):

**ERP/**: Enterprise resource planning
- ProductionOrder/{JobID}/
- Inventory/{MaterialCode}/

**MES/**: Manufacturing execution system
- Quality/{machine}/
- Delivery/
- Utilization/
- WIP/

#### Energy Namespace (Energy/)
Power monitoring (MIXED):
- Asset/: Solar capacity (RETAINED)
- Edge/: Real-time kW (STREAMING)
- Line/: Daily kWh (RETAINED)
- Dashboard/: Summary (RETAINED)

### Data Retention Strategy

**RETAINED** messages (persist on broker):
- Good for: Current state, configuration, dashboard views
- Examples: Asset metadata, Line production data, Dashboard summaries

**STREAMING** messages (do not persist):
- Good for: High-frequency sensor data, events
- Examples: Edge sensor readings, real-time position updates

---

## Topic Structure Examples

```
umh/v1/metalfab/eindhoven/cutting/laser_01/
├── Asset/              (Descriptive - RETAINED)
│   ├── AssetID
│   ├── Name
│   ├── OEM
│   ├── Model
│   └── SerialNumber
├── Edge/               (Functional - STREAMING)
│   ├── LaserPower
│   ├── CuttingSpeed
│   ├── State
│   └── ShopFloor/      (Job context - RETAINED)
│       ├── JobID
│       ├── Customer
│       └── ProductName
├── Line/               (Functional - RETAINED)
│   ├── Infeed
│   ├── Outfeed
│   ├── State
│   └── OEE/
│       ├── Availability
│       ├── Quality
│       ├── Performance
│       └── OEE
└── Dashboard/          (Informative - RETAINED)
    ├── Asset           (JSON object)
    ├── Job             (JSON object)
    └── OEE             (JSON object)
```

---

## Simulator Complexity Levels

The simulator supports 5 complexity levels:

| Level | Name | Features | Use Case |
|-------|------|----------|----------|
| 0 | PAUSED | No data generation | Initialization, testing |
| 1 | SENSORS | Basic sensor data, Energy | Simple monitoring |
| 2 | STATEFUL | + Machine states, Jobs, Operators | Production tracking |
| 3 | ERP/MES | + Quality, Margins, OEE, Inventory | Full manufacturing system |
| 4 | FULL | + Dashboards, Analytics, Events | Complete IIoT platform |

Change levels using the `control_simulator` tool or MQTT:

```bash
mosquitto_pub -t "metalfab-sim/control/level" -m "3"
```

---

## Example Conversation Flow

**User**: "What manufacturing data is available?"

**Claude** (using explore_uns_structure): Shows enterprise → sites → departments → machines hierarchy

**User**: "Show me the Eindhoven cutting department machines"

**Claude** (using explore_uns_structure with filter): Lists laser_01, laser_02 with available namespaces

**User**: "What's the OEE for laser_01?"

**Claude** (using query_machine_dashboard): Shows OEE metrics from Dashboard namespace

**User**: "Are there any production bottlenecks?"

**Claude** (using query_mes_data): Shows utilization data with bottleneck identification

**User**: "Increase simulator detail to see more data"

**Claude** (using control_simulator): Sets level to 4

---

## Troubleshooting

### "No data found" errors

**Problem**: Cache is empty or simulator not running

**Solution**:
1. Check simulator is running: `ps aux | grep metalfab-sim`
2. Check MQTT broker: `mosquitto_sub -t '#' -v` (should see messages)
3. Restart MCP server (restart Claude Desktop)
4. Check cache file: `cat mcp-server/src/metalfab_mqtt_cache.json`

### MCP server not appearing in Claude

**Problem**: Config file path is incorrect

**Solution**:
1. Verify absolute paths in claude_desktop_config.json
2. Check file has executable permission: `chmod +x mcp-server/src/metalfab_mcp_server.py`
3. Test server manually: `./mcp-server/venv/bin/python mcp-server/src/metalfab_mcp_server.py`
4. Check Claude logs (Help → View Logs in Claude Desktop)

### Connection timeout warnings

**Problem**: MQTT broker not reachable

**Solution**:
1. Verify broker is running: `netstat -an | grep 1883`
2. Check firewall settings
3. Server will auto-reconnect in background

---

## Advanced Usage

### Custom MQTT Broker

Set environment variables:

```bash
export MQTT_BROKER="remote.broker.com"
export MQTT_PORT="1883"
export MQTT_USERNAME="user"
export MQTT_PASSWORD="pass"
```

### Cache Inspection

The cache file stores all topics and values:

```bash
cat mcp-server/src/metalfab_mqtt_cache.json | jq .
```

### Direct MQTT Testing

Use mosquitto_sub to verify data:

```bash
# See all topics
mosquitto_sub -t '#' -v

# Watch Dashboard updates
mosquitto_sub -t 'umh/v1/metalfab/+/+/+/Dashboard/#' -v

# Control simulator
mosquitto_pub -t 'metalfab-sim/control/level' -m '4'
```

### Observing MCP Server Activity

Watch the MCP server's own activity in the UNS:

```bash
# Watch all MCP server topics
mosquitto_sub -t 'metalfab-sim/mcp_server/#' -v

# See server identity
mosquitto_sub -t 'metalfab-sim/mcp_server/+/_meta/identity' -v

# Watch tool calls in real-time
mosquitto_sub -t 'metalfab-sim/mcp_server/+/_event/tool_call' -v

# Monitor activity metrics
mosquitto_sub -t 'metalfab-sim/mcp_server/+/_historian/activity' -v

# Check current state
mosquitto_sub -t 'metalfab-sim/mcp_server/+/_state' -v
```

**What you'll see:**
- Every time Claude uses a tool, an event is published
- Activity metrics update every 30 seconds (heartbeat)
- State changes when server connects, processes queries, or shuts down
- The MCP server becomes a fully observable node in the UNS

---

## Files

| File | Description |
|------|-------------|
| `src/metalfab_mcp_server.py` | Main MCP server implementation |
| `src/metalfab_mqtt_cache.json` | Auto-generated cache (gitignored) |
| `requirements.txt` | Python dependencies |
| `README.md` | This file |

---

## Learning Resources

- **MCP Documentation**: [modelcontextprotocol.io](https://modelcontextprotocol.io)
- **UMH Data Model**: [docs.umh.app/datamodel](https://docs.umh.app/datamodel)
- **ISA-95 Standard**: [isa.org/standards](https://www.isa.org/standards-and-publications/isa-standards)
- **MQTT Essentials**: [hivemq.com/mqtt-essentials](https://www.hivemq.com/mqtt-essentials/)

---

## License

MIT License - See parent project LICENSE file
