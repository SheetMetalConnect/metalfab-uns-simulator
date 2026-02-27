"""MQTT client wrapper with publish buffering and level control."""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from queue import Queue, Empty
from typing import Any, Callable, Dict, Optional

import paho.mqtt.client as mqtt

from .complexity import ComplexityLevel
from .config import MQTTConfig, UNSConfig

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """MQTT message to be published."""

    topic: str
    payload: Dict[str, Any]
    retain: bool = False
    qos: int = 1


class MQTTClient:
    """MQTT client with buffering and complexity level control."""

    # Control topics - ROOT level (outside UNS path for easy access)
    CONTROL_ROOT = "metalfab-sim"
    LEVEL_CONTROL_TOPIC = f"{CONTROL_ROOT}/settings/level"
    STATUS_TOPIC = f"{CONTROL_ROOT}/status"
    CONFIG_TOPIC = f"{CONTROL_ROOT}/settings/config"

    def __init__(
        self,
        mqtt_config: MQTTConfig,
        uns_config: UNSConfig,
        on_level_change: Optional[Callable[[ComplexityLevel], None]] = None,
        on_site_toggle: Optional[Callable[[str, bool], None]] = None,
    ):
        self.mqtt_config = mqtt_config
        self.uns_config = uns_config
        self.on_level_change = on_level_change
        self.on_site_toggle = on_site_toggle

        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._current_level = ComplexityLevel.LEVEL_2_STATEFUL
        self._publish_queue: Queue[Message] = Queue()
        self._publish_thread: Optional[threading.Thread] = None
        self._running = False
        self._dry_run = False

        # Stats
        self._messages_published = 0
        self._messages_dropped = 0

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def current_level(self) -> ComplexityLevel:
        return self._current_level

    @property
    def base_topic(self) -> str:
        """Get the base topic path."""
        return f"{self.uns_config.topic_prefix}/{self.uns_config.enterprise}/{self.uns_config.site}"

    def connect(self, dry_run: bool = False) -> bool:
        """Connect to the MQTT broker."""
        self._dry_run = dry_run

        if dry_run:
            logger.info("Dry run mode - not connecting to MQTT broker")
            self._connected = True
            self._start_publish_thread()
            return True

        try:
            self._client = mqtt.Client(
                client_id=self.mqtt_config.client_id,
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            )

            if self.mqtt_config.username:
                self._client.username_pw_set(
                    self.mqtt_config.username, self.mqtt_config.password
                )

            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.on_message = self._on_message

            logger.info(
                f"Connecting to MQTT broker {self.mqtt_config.broker}:{self.mqtt_config.port}"
            )
            self._client.connect(self.mqtt_config.broker, self.mqtt_config.port)
            self._client.loop_start()

            # Wait for connection
            timeout = 10
            start = time.time()
            while not self._connected and (time.time() - start) < timeout:
                time.sleep(0.1)

            if self._connected:
                self._start_publish_thread()
                self._subscribe_to_control()
                self._publish_status()

            return self._connected

        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        self._running = False

        if self._publish_thread:
            self._publish_thread.join(timeout=2)

        if self._client and not self._dry_run:
            self._client.loop_stop()
            self._client.disconnect()

        self._connected = False
        logger.info("Disconnected from MQTT broker")

    def clear_retained_topics(self) -> None:
        """Clear all retained MQTT topics by publishing empty messages.

        This wipes all previously retained data from the broker for a clean start.
        """
        if self._dry_run:
            logger.info("[DRY RUN] Would clear retained topics")
            return

        if not self._connected:
            logger.warning("Not connected to MQTT broker - cannot clear topics")
            return

        logger.info("Clearing all retained topics...")

        # Topic patterns to clear (all UNS namespaces)
        topic_patterns = [
            # Root simulator topics
            f"{self.CONTROL_ROOT}/status",
            f"{self.CONTROL_ROOT}/settings/#",

            # UNS topics - all namespaces
            f"{self.base_topic}/_meta/#",
            f"{self.base_topic}/_state/#",
            f"{self.base_topic}/_jobs/#",
            f"{self.base_topic}/_erp/#",
            f"{self.base_topic}/_mes/#",
            f"{self.base_topic}/_dashboard/#",
            f"{self.base_topic}/_analytics/#",
            f"{self.base_topic}/_event/#",
            f"{self.base_topic}/_alarms/#",

            # Enterprise-level shared resources
            f"{self.uns_config.topic_prefix}/{self.uns_config.enterprise}/_meta/#",
            f"{self.uns_config.topic_prefix}/{self.uns_config.enterprise}/_mes/#",

            # Area-level topics (for each common area)
            f"{self.base_topic}/cutting/#",
            f"{self.base_topic}/forming/#",
            f"{self.base_topic}/welding/#",
            f"{self.base_topic}/finishing/#",
            f"{self.base_topic}/logistics/#",
        ]

        # Subscribe temporarily to discover retained messages
        discovered_topics = []

        def on_message(client, userdata, msg):
            if msg.retain:
                discovered_topics.append(msg.topic)

        if self._client:
            self._client.on_message = on_message

            # Subscribe to all patterns
            for pattern in topic_patterns:
                self._client.subscribe(pattern)

            # Wait briefly to receive retained messages
            import time
            time.sleep(2)

            # Restore original message handler
            self._client.on_message = self._on_message

            # Unsubscribe from all patterns
            for pattern in topic_patterns:
                self._client.unsubscribe(pattern)

        # Clear each discovered topic by publishing empty retained message
        cleared_count = 0
        for topic in discovered_topics:
            try:
                result = self._client.publish(topic, payload=None, qos=1, retain=True)
                result.wait_for_publish()
                cleared_count += 1
            except Exception as e:
                logger.error(f"Error clearing topic {topic}: {e}")

        logger.info(f"Cleared {cleared_count} retained topics")

        # Also clear known patterns with wildcard approach
        # (publish empty to common parent topics)
        common_topics = [
            f"{self.CONTROL_ROOT}/status",
            f"{self.base_topic}/_meta/shared_resources/powder_coating",
            f"{self.base_topic}/_mes/shared_resources/powder_coating/planning",
        ]

        for topic in common_topics:
            try:
                self._client.publish(topic, payload=None, qos=1, retain=True)
            except Exception as e:
                logger.debug(f"Could not clear {topic}: {e}")

    def publish(
        self,
        topic: str,
        payload: Dict[str, Any],
        retain: bool = False,
        required_level: ComplexityLevel = ComplexityLevel.LEVEL_1_SENSORS,
    ) -> bool:
        """Queue a message for publishing if current level allows it."""
        if self._current_level < required_level:
            return False

        full_topic = f"{self.base_topic}/{topic}"
        msg = Message(topic=full_topic, payload=payload, retain=retain, qos=self.mqtt_config.qos)
        self._publish_queue.put(msg)
        return True

    def publish_raw(self, topic: str, payload: Dict[str, Any], retain: bool = False) -> bool:
        """Publish to a raw topic (no base path)."""
        msg = Message(topic=topic, payload=payload, retain=retain, qos=self.mqtt_config.qos)
        self._publish_queue.put(msg)
        return True

    def set_level(self, level: ComplexityLevel) -> None:
        """Set the current complexity level."""
        if level != self._current_level:
            old_level = self._current_level
            self._current_level = level
            logger.info(f"Complexity level changed: {old_level.name} -> {level.name}")

            if self.on_level_change:
                self.on_level_change(level)

            self._publish_status()

    def _start_publish_thread(self) -> None:
        """Start the background publish thread."""
        self._running = True
        self._publish_thread = threading.Thread(target=self._publish_loop, daemon=True)
        self._publish_thread.start()

    def _publish_loop(self) -> None:
        """Background thread that publishes queued messages."""
        while self._running:
            try:
                msg = self._publish_queue.get(timeout=0.1)
                self._do_publish(msg)
            except Empty:
                continue

    def _do_publish(self, msg: Message) -> None:
        """Actually publish a message."""
        payload_str = json.dumps(msg.payload)

        if self._dry_run:
            logger.debug(f"[DRY RUN] {msg.topic}: {payload_str[:100]}")
            self._messages_published += 1
            return

        if self._client and self._connected:
            try:
                result = self._client.publish(
                    msg.topic, payload_str, qos=msg.qos, retain=msg.retain
                )
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    self._messages_published += 1
                else:
                    self._messages_dropped += 1
                    logger.warning(f"Failed to publish to {msg.topic}: {result.rc}")
            except Exception as e:
                self._messages_dropped += 1
                logger.error(f"Error publishing to {msg.topic}: {e}")

    def _subscribe_to_control(self) -> None:
        """Subscribe to control topics for level changes (root level)."""
        if not self._client:
            return

        # Subscribe to root-level control topic (not under UNS path)
        self._client.subscribe(self.LEVEL_CONTROL_TOPIC, qos=1)
        logger.info(f"Subscribed to control topic: {self.LEVEL_CONTROL_TOPIC}")

        # Also subscribe to config topic for other settings
        self._client.subscribe(self.CONFIG_TOPIC, qos=1)

    def _publish_status(self) -> None:
        """Publish current simulator status to root-level topic."""
        status = {
            "level": self._current_level.value,
            "level_name": self._current_level.name,
            "enterprise": self.uns_config.enterprise,
            "site": self.uns_config.site,
            "messages_published": self._messages_published,
            "messages_dropped": self._messages_dropped,
            "timestamp_ms": int(time.time() * 1000),
        }
        # Use publish_raw to publish to root-level topic (not UNS path)
        self.publish_raw(self.STATUS_TOPIC, status, retain=True)

    def publish_simulator_status(self, level: ComplexityLevel, sites_enabled: Dict[str, bool]) -> None:
        """Publish simulator status including level and site states."""
        status = {
            "level": level.value,
            "level_name": level.name,
            "enterprise": self.uns_config.enterprise,
            "site": self.uns_config.site,
            "sites_enabled": sites_enabled,
            "messages_published": self._messages_published,
            "messages_dropped": self._messages_dropped,
            "timestamp_ms": int(time.time() * 1000),
        }
        self.publish_raw(self.STATUS_TOPIC, status, retain=True)

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        """Handle connection callback."""
        if rc == 0:
            self._connected = True
            logger.info("Connected to MQTT broker")
        else:
            logger.error(f"Connection failed with code {rc}")

    def _on_disconnect(self, client, userdata, flags, rc, properties=None) -> None:
        """Handle disconnection callback."""
        self._connected = False
        if rc != 0:
            logger.warning(f"Unexpected disconnection (rc={rc})")

    def _on_message(self, client, userdata, msg) -> None:
        """Handle incoming messages (for level and config control)."""
        try:
            # Level control: metalfab-sim/settings/level
            if msg.topic == self.LEVEL_CONTROL_TOPIC:
                payload = json.loads(msg.payload.decode())
                new_level = payload.get("level")

                if new_level is not None:
                    level = ComplexityLevel(int(new_level))
                    self.set_level(level)

            # Config control: metalfab-sim/settings/config
            elif msg.topic == self.CONFIG_TOPIC:
                payload = json.loads(msg.payload.decode())
                # Handle config changes (enterprise, site, speed, etc.)
                if "level" in payload:
                    level = ComplexityLevel(int(payload["level"]))
                    self.set_level(level)
                # Future: handle other config options

        except Exception as e:
            logger.error(f"Error processing control message: {e}")