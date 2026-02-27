#!/usr/bin/env python3
"""
MetalFab UNS MCP Server - Educational MQTT/UNS Interface

This MCP server provides Claude Desktop with read/write access to the MetalFab
simulator's Unified Namespace via MQTT.

Architecture:
    - On connect: Subscribe to all topics (#) and cache values in JSON file
    - On message: Update cache file with latest value for each topic
    - Cache persists across reconnections for stability
    - Tools read from cache for instant responses

Tools:
    - explore_uns: Discover the UNS hierarchical structure
    - list_topics: List all cached topics (with optional filter)
    - get_topic: Get value for a specific topic
    - search_topics: Find topics by pattern or keyword
    - get_dashboard: Get dashboard data for a machine
    - control_simulator: Change simulator level or toggle sites
    - publish_message: Write messages to UNS topics
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any
import fnmatch
import re
import threading
from datetime import datetime
from collections import defaultdict

import paho.mqtt.client as mqtt
from paho.mqtt.reasoncodes import ReasonCode
from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Configure logging to stderr (stdout reserved for MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("metalfab-mcp")

# Load environment from project root .env if exists
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    logger.info(f"Loaded environment from: {env_path}")

# MQTT Configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_USE_WEBSOCKETS = os.getenv("MQTT_USE_WEBSOCKETS", "false").lower() == "true"
MQTT_WS_PATH = os.getenv("MQTT_WS_PATH", "/mqtt")  # WebSocket path (usually /mqtt or /ws)

# Generate unique client ID
_base_client_id = os.getenv("MQTT_CLIENT_ID", "metalfab-mcp")
MQTT_CLIENT_ID = f"{_base_client_id}-{uuid.uuid4().hex[:8]}"

# Cache file in same directory as script
CACHE_FILE = Path(__file__).parent / "metalfab_mqtt_cache.json"


class MQTTClientWrapper:
    """MQTT client with file-based caching (thread-safe)."""

    def __init__(self):
        """Initialize MQTT client with v2.0+ API."""
        # Determine transport type
        transport = "websockets" if MQTT_USE_WEBSOCKETS else "tcp"

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=MQTT_CLIENT_ID,
            protocol=mqtt.MQTTv311,
            clean_session=True,
            transport=transport
        )
        self.connected = False
        self._cache_lock = threading.Lock()
        self._message_count = 0
        self._start_time = time.time()

        # Activity tracking
        self._tool_call_count = defaultdict(int)
        self._last_tool_call = None
        self._last_activity_time = time.time()

        # UNS topic base for this MCP server instance (matches simulator namespace)
        self._uns_base = f"metalfab-sim/mcp_server/{MQTT_CLIENT_ID}"

        # Set up callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        # Set credentials if provided
        if MQTT_USERNAME and MQTT_PASSWORD:
            self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

        # Configure WebSocket path if using websockets
        if MQTT_USE_WEBSOCKETS:
            self.client.ws_set_options(path=MQTT_WS_PATH)
            logger.info(f"WebSocket transport enabled (path: {MQTT_WS_PATH})")

        # Configure reconnection
        self.client.reconnect_delay_set(min_delay=1, max_delay=120)

        # Initialize cache
        self._init_cache()

    def _init_cache(self):
        """Load existing cache from disk into memory."""
        with self._cache_lock:
            self._memory_cache = {}
            self._cache_dirty = False
            try:
                if CACHE_FILE.exists():
                    try:
                        with open(CACHE_FILE, 'r') as f:
                            import fcntl
                            fcntl.flock(f, fcntl.LOCK_SH)
                            self._memory_cache = json.load(f)
                            fcntl.flock(f, fcntl.LOCK_UN)
                        logger.info(f"Loaded cache with {len(self._memory_cache)} topics")
                    except (json.JSONDecodeError, Exception):
                        self._memory_cache = {}
                        logger.warning("Cache was corrupted, starting fresh")
                else:
                    logger.info(f"No cache file found, starting fresh: {CACHE_FILE}")
            except Exception as e:
                logger.error(f"Failed to initialize cache: {e}")

            # Start periodic flush thread
            self._flush_thread = threading.Thread(target=self._periodic_flush, daemon=True)
            self._flush_thread.start()

    def _periodic_flush(self):
        """Flush in-memory cache to disk every 2 seconds."""
        while True:
            time.sleep(2)
            self._flush_cache()

    def _flush_cache(self):
        """Write in-memory cache to disk with file locking."""
        with self._cache_lock:
            if not self._cache_dirty:
                return
            try:
                import fcntl
                # Merge with any data other instances wrote
                existing = {}
                if CACHE_FILE.exists():
                    try:
                        with open(CACHE_FILE, 'r') as f:
                            fcntl.flock(f, fcntl.LOCK_SH)
                            existing = json.load(f)
                            fcntl.flock(f, fcntl.LOCK_UN)
                    except (json.JSONDecodeError, Exception):
                        existing = {}

                # Merge: keep newer timestamps from either source
                merged = existing.copy()
                for topic, data in self._memory_cache.items():
                    if topic not in merged:
                        merged[topic] = data
                    elif isinstance(data, dict) and isinstance(merged.get(topic), dict):
                        if data.get("timestamp", 0) >= merged[topic].get("timestamp", 0):
                            merged[topic] = data
                    else:
                        merged[topic] = data

                self._memory_cache = merged

                # Atomic write with exclusive lock
                temp_file = CACHE_FILE.with_suffix('.tmp')
                with open(temp_file, 'w') as f:
                    fcntl.flock(f, fcntl.LOCK_EX)
                    json.dump(merged, f)
                    fcntl.flock(f, fcntl.LOCK_UN)
                temp_file.replace(CACHE_FILE)

                self._cache_dirty = False
            except Exception as e:
                logger.error(f"Failed to flush cache: {e}")

    def _read_cache(self) -> dict[str, Any]:
        """Read from in-memory cache (fast)."""
        with self._cache_lock:
            return self._memory_cache.copy()

    def _write_to_cache(self, topic: str, value: str):
        """Write/update topic in memory (batched disk flush)."""
        with self._cache_lock:
            self._memory_cache[topic] = {
                "value": value,
                "timestamp": time.time(),
            }
            self._cache_dirty = True
            self._message_count += 1
            if self._message_count % 500 == 0:
                logger.info(f"Cache: {self._message_count} messages, {len(self._memory_cache)} topics")

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Callback when connected to broker."""
        if reason_code == 0 or (isinstance(reason_code, ReasonCode) and reason_code.is_failure is False):
            self.connected = True
            logger.info(f"Connected to {MQTT_BROKER}:{MQTT_PORT}")

            # Subscribe to all topics
            result, mid = self.client.subscribe("#", qos=0)
            if result == mqtt.MQTT_ERR_SUCCESS:
                logger.info("Subscribed to all topics (#)")
            else:
                logger.error(f"Subscribe failed: {result}")

            # Publish MCP server identity to UNS
            self._publish_identity()
            self._publish_state("connected")
        else:
            logger.error(f"Connection failed: {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        """Callback when disconnected from broker."""
        self.connected = False
        if reason_code == 0:
            logger.info("Disconnected from broker")
            self._publish_state("disconnected")
        else:
            logger.warning(f"Unexpected disconnect (rc={reason_code}), will reconnect")
            self._publish_state("reconnecting")

    def _on_message(self, client, userdata, message):
        """Callback when message received - cache it."""
        try:
            payload = message.payload.decode("utf-8")
        except UnicodeDecodeError:
            payload = str(message.payload)

        self._write_to_cache(message.topic, payload)

    def connect(self):
        """Connect to MQTT broker."""
        try:
            logger.info(f"Connecting to {MQTT_BROKER}:{MQTT_PORT} as {MQTT_CLIENT_ID}")
            self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            self.client.loop_start()

            # Wait for connection (10 second timeout)
            timeout = 10
            start = time.time()
            while not self.connected and (time.time() - start) < timeout:
                time.sleep(0.1)

            if not self.connected:
                logger.error("Connection timeout")
                return False
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from broker."""
        self._flush_cache()  # Ensure all data is written to disk
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("Disconnected (cache flushed and preserved)")

    def get_all_topics(self) -> dict[str, Any]:
        """Get all cached topics."""
        return self._read_cache()

    def get_topic_value(self, topic: str) -> dict[str, Any] | None:
        """Get specific topic value."""
        cache = self._read_cache()
        return cache.get(topic)

    def _publish_identity(self):
        """Publish MCP server identity and capabilities to UNS."""
        if not self.connected:
            return

        identity = {
            "client_id": MQTT_CLIENT_ID,
            "type": "mcp_server",
            "name": "MetalFab UNS MCP Server",
            "description": "Model Context Protocol server providing Claude AI access to the MetalFab UNS via MQTT",
            "version": "1.0.0",
            "started_at": datetime.fromtimestamp(self._start_time).isoformat(),
            "broker": f"{MQTT_BROKER}:{MQTT_PORT}",
            "transport": "websockets" if MQTT_USE_WEBSOCKETS else "tcp",
            "websocket_path": MQTT_WS_PATH if MQTT_USE_WEBSOCKETS else None,
            "capabilities": [
                "explore_uns",
                "list_topics",
                "get_topic",
                "search_topics",
                "get_dashboard",
                "control_simulator",
                "publish_message"
            ],
            "subscriptions": ["#"],
            "cache_file": str(CACHE_FILE)
        }

        topic = f"{self._uns_base}/_meta/identity"
        self.client.publish(topic, json.dumps(identity), qos=1, retain=True)
        logger.info(f"Published identity to {topic}")

    def _publish_state(self, state: str):
        """Publish current state to UNS."""
        if not self.connected and state != "disconnected":
            return

        state_data = {
            "state": state,
            "timestamp": datetime.now().isoformat(),
            "uptime_seconds": time.time() - self._start_time,
            "last_activity": datetime.fromtimestamp(self._last_activity_time).isoformat(),
            "messages_cached": self._message_count,
            "cache_size_topics": len(self._read_cache())
        }

        topic = f"{self._uns_base}/_state"
        self.client.publish(topic, json.dumps(state_data), qos=1, retain=True)

    def publish_tool_call(self, tool_name: str, arguments: dict[str, Any], result_summary: str = None):
        """Publish tool call event to UNS."""
        if not self.connected:
            return

        self._last_activity_time = time.time()
        self._tool_call_count[tool_name] += 1
        self._last_tool_call = tool_name

        # Event (non-retained, transient)
        event = {
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "arguments": arguments,
            "result_summary": result_summary,
            "call_count": self._tool_call_count[tool_name]
        }

        topic = f"{self._uns_base}/_event/tool_call"
        self.client.publish(topic, json.dumps(event), qos=0, retain=False)

        # Update activity metrics (non-retained, streaming)
        self._publish_activity_metrics()

        # Update state (retained)
        self._publish_state("processing")

    def _publish_activity_metrics(self):
        """Publish activity metrics to UNS."""
        if not self.connected:
            return

        metrics = {
            "timestamp": datetime.now().isoformat(),
            "total_tool_calls": sum(self._tool_call_count.values()),
            "tool_call_breakdown": dict(self._tool_call_count),
            "last_tool_call": self._last_tool_call,
            "uptime_seconds": time.time() - self._start_time,
            "messages_received": self._message_count,
            "cache_size_topics": len(self._read_cache()),
            "cache_file_size_bytes": CACHE_FILE.stat().st_size if CACHE_FILE.exists() else 0
        }

        topic = f"{self._uns_base}/_raw/activity"
        self.client.publish(topic, json.dumps(metrics), qos=0, retain=False)

    async def publish_message(self, topic: str, payload: str, retain: bool = False, qos: int = 1) -> dict[str, Any]:
        """Publish message to topic."""
        if not self.connected:
            raise ConnectionError("Not connected to MQTT broker")

        # Validate
        if qos not in (0, 1, 2):
            raise ValueError(f"Invalid QoS: {qos}")
        if not topic or not topic.strip():
            raise ValueError("Topic cannot be empty")
        if "#" in topic or "+" in topic:
            raise ValueError("Cannot publish to wildcard topics")

        logger.info(f"Publishing to '{topic}': {payload[:100]}, retain={retain}, qos={qos}")

        result = self.client.publish(topic, payload, qos=qos, retain=retain)

        if qos > 0:
            result.wait_for_publish(timeout=10)

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            return {
                "success": True,
                "topic": topic,
                "payload": payload,
                "retain": retain,
                "qos": qos,
                "message_id": result.mid,
            }
        else:
            return {
                "success": False,
                "error": f"Publish failed: {result.rc}",
            }


# Global MQTT client
mqtt_client = MQTTClientWrapper()

# MCP Server
server = Server("metalfab-uns")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available MCP tools."""
    return [
        Tool(
            name="explore_uns",
            description="Explore the MetalFab UNS structure. Shows enterprise/site/area/cell hierarchy and available namespaces (Asset, Edge, Line, Dashboard, ERP, MES, Energy). Use this first to understand what data is available.",
            inputSchema={
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "description": "Hierarchy level: 'overview', 'sites', 'areas', 'machines', or 'namespaces'",
                        "enum": ["overview", "sites", "areas", "machines", "namespaces"],
                        "default": "overview"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="list_topics",
            description="List all topics in the UNS cache. Cache is continuously updated with live MQTT data. Use 'prefix' to filter (e.g., 'umh/v1/metalfab/eindhoven' for Eindhoven site only).",
            inputSchema={
                "type": "object",
                "properties": {
                    "prefix": {
                        "type": "string",
                        "description": "Optional prefix filter. Examples: 'umh/v1/metalfab/eindhoven', 'umh/v1/metalfab/eindhoven/cutting'. Leave empty for all topics.",
                        "default": ""
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of topics to return (default: 50)",
                        "default": 50,
                        "minimum": 1,
                        "maximum": 500
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="get_topic",
            description="Get the current value for a specific MQTT topic. Returns the latest cached value. Example: 'umh/v1/metalfab/eindhoven/cutting/laser_01/Dashboard/OEE'",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Full topic path, e.g., 'umh/v1/metalfab/eindhoven/cutting/laser_01/Line/State'"
                    }
                },
                "required": ["topic"]
            }
        ),
        Tool(
            name="search_topics",
            description="Search topics by pattern or keyword. Supports glob patterns (*, ?) and MQTT wildcards (+, #). Examples: '*laser*', 'umh/v1/metalfab/+/cutting/#', 'OEE'",
            inputSchema={
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Search pattern: keyword, glob (*laser*), or MQTT wildcard (umh/+/metalfab/#)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum results (default: 50)",
                        "default": 50,
                        "minimum": 1,
                        "maximum": 200
                    }
                },
                "required": ["pattern"]
            }
        ),
        Tool(
            name="get_dashboard",
            description="Get Dashboard namespace data for a machine (Asset info, current Job, OEE metrics, current state and stop reason). Example: site='eindhoven', area='cutting', machine='laser_01'",
            inputSchema={
                "type": "object",
                "properties": {
                    "site": {
                        "type": "string",
                        "description": "Site name: 'eindhoven', 'roeselare', or 'brasov'"
                    },
                    "area": {
                        "type": "string",
                        "description": "Area name: 'cutting', 'forming', 'welding', 'assembly', 'finishing', 'logistics'"
                    },
                    "machine": {
                        "type": "string",
                        "description": "Machine ID: 'laser_01', 'press_brake_01', 'weld_cell_01', etc."
                    }
                },
                "required": ["site", "area", "machine"]
            }
        ),
        Tool(
            name="control_simulator",
            description="Control the MetalFab simulator. Change level (0=Paused, 1=Sensors, 2=Stateful, 3=ERP/MES, 4=Full) or toggle sites on/off.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Action: 'set_level' or 'toggle_site'",
                        "enum": ["set_level", "toggle_site"]
                    },
                    "level": {
                        "type": "integer",
                        "description": "Level (0-4) for 'set_level'",
                        "minimum": 0,
                        "maximum": 4
                    },
                    "site": {
                        "type": "string",
                        "description": "Site name for 'toggle_site'"
                    },
                    "enabled": {
                        "type": "boolean",
                        "description": "true=enable, false=disable for 'toggle_site'"
                    }
                },
                "required": ["action"]
            }
        ),
        Tool(
            name="publish_message",
            description="Publish message to MQTT topic. WARNING: Writes to live broker. Use for testing or sending commands.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Full topic path (no wildcards)"
                    },
                    "payload": {
                        "type": "string",
                        "description": "Message payload (string or JSON)"
                    },
                    "retain": {
                        "type": "boolean",
                        "description": "Retain message on broker (default: false)",
                        "default": False
                    },
                    "qos": {
                        "type": "integer",
                        "description": "Quality of Service: 0, 1, or 2 (default: 1)",
                        "default": 1,
                        "enum": [0, 1, 2]
                    }
                },
                "required": ["topic", "payload"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""

    try:
        # Track tool call start
        start_time = time.time()

        # Execute tool
        if name == "explore_uns":
            result = await handle_explore_uns(arguments)
        elif name == "list_topics":
            result = await handle_list_topics(arguments)
        elif name == "get_topic":
            result = await handle_get_topic(arguments)
        elif name == "search_topics":
            result = await handle_search_topics(arguments)
        elif name == "get_dashboard":
            result = await handle_get_dashboard(arguments)
        elif name == "control_simulator":
            result = await handle_control_simulator(arguments)
        elif name == "publish_message":
            result = await handle_publish_message(arguments)
        else:
            result = [TextContent(type="text", text=f"Unknown tool: {name}")]

        # Publish tool call to UNS
        duration_ms = (time.time() - start_time) * 1000
        result_text = result[0].text if result else ""
        summary = f"Completed in {duration_ms:.1f}ms"
        if len(result_text) > 100:
            summary += f" | {result_text[:100]}..."
        else:
            summary += f" | {result_text}"

        mqtt_client.publish_tool_call(name, arguments, summary)

        return result

    except Exception as e:
        logger.exception(f"Error in {name}")
        mqtt_client.publish_tool_call(name, arguments, f"Error: {str(e)}")
        return [TextContent(type="text", text=f"Error: {e}")]


async def handle_explore_uns(arguments: dict[str, Any]) -> list[TextContent]:
    """Explore UNS structure."""
    level = arguments.get("level", "overview")

    cache = mqtt_client.get_all_topics()
    if not cache:
        return [TextContent(type="text", text="No data in cache yet. Is the simulator running?")]

    # Extract structure from topics
    sites = set()
    areas = set()
    machines = set()
    namespaces = set()

    for topic in cache.keys():
        if topic.startswith("umh/v1/metalfab/"):
            parts = topic.split("/")
            if len(parts) >= 4:
                sites.add(parts[3])
            if len(parts) >= 5:
                areas.add(parts[4])
            if len(parts) >= 6:
                machines.add(f"{parts[4]}/{parts[5]}")
            if len(parts) >= 7:
                namespaces.add(parts[6])

    if level == "overview":
        output = [
            "# MetalFab UNS Structure Overview",
            "",
            f"**Total Topics:** {len(cache)}",
            f"**Sites:** {len(sites)}",
            f"**Areas:** {len(areas)}",
            f"**Machines:** {len(machines)}",
            f"**Namespaces:** {len(namespaces)}",
            "",
            "Use level='sites', 'areas', 'machines', or 'namespaces' for details."
        ]
    elif level == "sites":
        output = [f"# Sites ({len(sites)})", ""] + [f"- {s}" for s in sorted(sites)]
    elif level == "areas":
        output = [f"# Areas ({len(areas)})", ""] + [f"- {a}" for a in sorted(areas)]
    elif level == "machines":
        output = [f"# Machines ({len(machines)})", ""] + [f"- {m}" for m in sorted(machines)]
    elif level == "namespaces":
        output = [
            f"# Namespaces ({len(namespaces)})",
            "",
            "**Available namespaces:**"
        ] + [f"- {n}" for n in sorted(namespaces)] + [
            "",
            "**Namespace types:**",
            "- Asset: Static descriptive data (OEM, model, capacity)",
            "- Edge: Real-time streaming data (sensor values)",
            "- Line: Functional retained data (state, counters)",
            "- Dashboard: Aggregated informative data (OEE, jobs)",
            "- ERP: Production orders, inventory",
            "- MES: Quality, delivery, utilization",
            "- Energy: Power consumption monitoring"
        ]
    else:
        output = ["Unknown level"]

    return [TextContent(type="text", text="\n".join(output))]


async def handle_list_topics(arguments: dict[str, Any]) -> list[TextContent]:
    """List topics with optional prefix filter."""
    prefix = arguments.get("prefix", "")
    limit = arguments.get("limit", 50)

    if not mqtt_client.connected:
        return [TextContent(type="text", text="Not connected to broker. Cache may be stale.")]

    cache = mqtt_client.get_all_topics()
    if not cache:
        return [TextContent(type="text", text="No topics in cache. Wait for messages or check if simulator is running.")]

    # Filter by prefix
    if prefix:
        filtered = {k: v for k, v in cache.items() if k.startswith(prefix)}
    else:
        filtered = cache

    if not filtered:
        return [TextContent(type="text", text=f"No topics matching prefix '{prefix}'. Total in cache: {len(cache)}")]

    # Format results
    result_lines = [f"Found {len(filtered)} topics (showing first {limit}):\n"]
    for i, (topic, data) in enumerate(sorted(filtered.items())):
        if i >= limit:
            result_lines.append(f"\n... and {len(filtered) - limit} more")
            break
        value = data.get("value", "")
        if len(value) > 80:
            value = value[:80] + "..."
        result_lines.append(f"  • {topic}: {value}")

    return [TextContent(type="text", text="\n".join(result_lines))]


async def handle_get_topic(arguments: dict[str, Any]) -> list[TextContent]:
    """Get value for specific topic."""
    topic = arguments.get("topic")
    if not topic:
        return [TextContent(type="text", text="Error: 'topic' is required")]

    result = mqtt_client.get_topic_value(topic)
    if result is None:
        cache_size = len(mqtt_client.get_all_topics())
        return [TextContent(type="text", text=f"Topic '{topic}' not found. Cache has {cache_size} topics.")]

    timestamp = result.get("timestamp", 0)
    age = time.time() - timestamp if timestamp else 0

    output = [
        f"**Topic:** {topic}",
        f"**Value:** {result['value']}",
        f"**Last Updated:** {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))}",
        f"**Age:** {age:.1f} seconds ago"
    ]

    return [TextContent(type="text", text="\n".join(output))]


async def handle_search_topics(arguments: dict[str, Any]) -> list[TextContent]:
    """Search topics by pattern."""
    pattern = arguments.get("pattern")
    limit = arguments.get("limit", 50)

    if not pattern:
        return [TextContent(type="text", text="Error: 'pattern' is required")]

    cache = mqtt_client.get_all_topics()
    if not cache:
        return [TextContent(type="text", text="No topics in cache to search.")]

    # Search logic
    matching = {}
    has_wildcards = any(c in pattern for c in ["*", "?", "+", "#"])

    for topic, data in cache.items():
        matched = False

        if has_wildcards:
            # MQTT wildcards
            if "+" in pattern or "#" in pattern:
                mqtt_pattern = pattern.replace("+", "[^/]+").replace("#", ".*")
                if re.match(f"^{mqtt_pattern}$", topic):
                    matched = True
            # Glob wildcards
            else:
                if fnmatch.fnmatch(topic, f"*{pattern}*"):
                    matched = True
        else:
            # Simple keyword search
            if pattern.lower() in topic.lower():
                matched = True

        if matched:
            matching[topic] = data

    if not matching:
        return [TextContent(type="text", text=f"No topics matching '{pattern}'. Searched {len(cache)} topics.")]

    # Format results
    result_lines = [f"Found {len(matching)} matching topics (showing first {limit}):\n"]
    for i, (topic, data) in enumerate(sorted(matching.items())):
        if i >= limit:
            result_lines.append(f"\n... and {len(matching) - limit} more")
            break
        value = data.get("value", "")
        if len(value) > 80:
            value = value[:80] + "..."
        result_lines.append(f"  • {topic}: {value}")

    return [TextContent(type="text", text="\n".join(result_lines))]


async def handle_get_dashboard(arguments: dict[str, Any]) -> list[TextContent]:
    """Get dashboard data for a machine."""
    site = arguments.get("site")
    area = arguments.get("area")
    machine = arguments.get("machine")

    if not all([site, area, machine]):
        return [TextContent(type="text", text="Error: site, area, and machine are required")]

    base = f"umh/v1/metalfab/{site}/{area}/{machine}/Dashboard"
    edge_base = f"umh/v1/metalfab/{site}/{area}/{machine}/Edge"
    cache = mqtt_client.get_all_topics()

    # Collect dashboard topics
    dashboard_data = {}
    for topic, data in cache.items():
        if topic.startswith(base):
            key = topic.replace(base + "/", "")
            dashboard_data[key] = data.get("value")

    if not dashboard_data:
        return [TextContent(type="text", text=f"No dashboard data found for {site}/{area}/{machine}. Is the machine configured?")]

    # Format output
    output = [
        f"# Dashboard: {machine.upper()}",
        f"**Site:** {site} | **Area:** {area}",
        ""
    ]

    # Current state and stop reason from Edge namespace
    state_topic = f"{edge_base}/StateName"
    stop_topic = f"{edge_base}/StopReason"
    state_raw = cache.get(state_topic, {}).get("value", "UNKNOWN")
    state_val = state_raw.strip('"') if isinstance(state_raw, str) else state_raw
    stop_raw = cache.get(stop_topic, {}).get("value")

    output.append("## Current State")
    output.append(f"- **State:** {state_val}")
    if stop_raw:
        try:
            stop_val = json.loads(stop_raw) if isinstance(stop_raw, str) else stop_raw
            if stop_val.get("code"):
                output.append(f"- **Stop Reason:** {stop_val['code']} — {stop_val.get('name', '')}")
                output.append(f"- **Category:** {stop_val.get('category', '')}")
        except (json.JSONDecodeError, AttributeError):
            pass
    output.append("")

    # Group by category
    asset = {k: v for k, v in dashboard_data.items() if k.startswith("Asset/")}
    job = {k: v for k, v in dashboard_data.items() if k.startswith("Job/")}
    oee = {k: v for k, v in dashboard_data.items() if k.startswith("OEE/")}

    if asset:
        output.append("## Asset Info")
        for k, v in sorted(asset.items()):
            output.append(f"- **{k.replace('Asset/', '')}:** {v}")
        output.append("")

    if job:
        output.append("## Current Job")
        for k, v in sorted(job.items()):
            output.append(f"- **{k.replace('Job/', '')}:** {v}")
        output.append("")

    if oee:
        output.append("## OEE Metrics")
        for k, v in sorted(oee.items()):
            output.append(f"- **{k.replace('OEE/', '')}:** {v}")
        output.append("")

    return [TextContent(type="text", text="\n".join(output))]


async def handle_control_simulator(arguments: dict[str, Any]) -> list[TextContent]:
    """Control simulator via MQTT."""
    action = arguments.get("action")

    if action == "set_level":
        level = arguments.get("level")
        if level is None:
            return [TextContent(type="text", text="Error: 'level' is required for set_level")]

        try:
            result = await mqtt_client.publish_message(
                "metalfab-sim/control/level",
                str(level),
                retain=True,
                qos=1
            )
            if result["success"]:
                return [TextContent(type="text", text=f"✓ Simulator level set to {level}")]
            else:
                return [TextContent(type="text", text=f"✗ Failed: {result.get('error')}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    elif action == "toggle_site":
        site = arguments.get("site")
        enabled = arguments.get("enabled")

        if not site or enabled is None:
            return [TextContent(type="text", text="Error: 'site' and 'enabled' are required for toggle_site")]

        try:
            result = await mqtt_client.publish_message(
                f"metalfab-sim/control/site/{site}",
                "1" if enabled else "0",
                retain=True,
                qos=1
            )
            if result["success"]:
                status = "enabled" if enabled else "disabled"
                return [TextContent(type="text", text=f"✓ Site '{site}' {status}")]
            else:
                return [TextContent(type="text", text=f"✗ Failed: {result.get('error')}")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {e}")]

    else:
        return [TextContent(type="text", text=f"Unknown action: {action}")]


async def handle_publish_message(arguments: dict[str, Any]) -> list[TextContent]:
    """Publish message to MQTT topic."""
    topic = arguments.get("topic")
    payload = arguments.get("payload")
    retain = arguments.get("retain", False)
    qos = arguments.get("qos", 1)

    if not topic or payload is None:
        return [TextContent(type="text", text="Error: 'topic' and 'payload' are required")]

    try:
        result = await mqtt_client.publish_message(topic, str(payload), retain, qos)

        if result["success"]:
            output = [
                "✓ Message published successfully!",
                "",
                f"**Topic:** {topic}",
                f"**Payload:** {payload}",
                f"**Retain:** {retain}",
                f"**QoS:** {qos}",
                f"**Message ID:** {result['message_id']}"
            ]
            return [TextContent(type="text", text="\n".join(output))]
        else:
            return [TextContent(type="text", text=f"✗ Publish failed: {result.get('error')}")]

    except ValueError as e:
        return [TextContent(type="text", text=f"Validation error: {e}")]
    except ConnectionError as e:
        return [TextContent(type="text", text=f"Connection error: {e}")]
    except Exception as e:
        logger.exception("Publish error")
        return [TextContent(type="text", text=f"Error: {e}")]


async def heartbeat_task():
    """Periodic heartbeat to publish state and metrics."""
    while True:
        try:
            await asyncio.sleep(30)  # Every 30 seconds
            if mqtt_client.connected:
                mqtt_client._publish_state("idle")
                mqtt_client._publish_activity_metrics()
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")


async def main():
    """Main entry point."""
    logger.info("Starting MetalFab MCP Server")
    logger.info(f"Broker: {MQTT_BROKER}:{MQTT_PORT}")
    logger.info(f"Transport: {'WebSockets' if MQTT_USE_WEBSOCKETS else 'TCP'}")
    if MQTT_USE_WEBSOCKETS:
        logger.info(f"WebSocket Path: {MQTT_WS_PATH}")
    logger.info(f"Client ID: {MQTT_CLIENT_ID}")
    logger.info(f"Cache: {CACHE_FILE}")
    logger.info(f"UNS Base Topic: metalfab-sim/mcp_server/{MQTT_CLIENT_ID}")

    # Connect to MQTT
    if not mqtt_client.connect():
        logger.error("Failed to connect to MQTT. Server will start but tools may fail.")

    # Start heartbeat task
    heartbeat = asyncio.create_task(heartbeat_task())

    try:
        # Run MCP server
        async with stdio_server() as (read_stream, write_stream):
            logger.info("MCP server running")
            mqtt_client._publish_state("running")
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        heartbeat.cancel()
        mqtt_client._publish_state("shutdown")
        await asyncio.sleep(0.5)  # Give time to publish final state
        mqtt_client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
