"""Tests for MQTT client."""

import json
import pytest
from unittest.mock import MagicMock, patch

from metalfab_uns_sim.complexity import ComplexityLevel
from metalfab_uns_sim.config import MQTTConfig, UNSConfig
from metalfab_uns_sim.mqtt_client import MQTTClient, Message


class TestMQTTClient:
    """Tests for MQTTClient."""

    @pytest.fixture
    def mqtt_config(self):
        return MQTTConfig(
            broker="localhost",
            port=1883,
            client_id="test-client",
        )

    @pytest.fixture
    def uns_config(self):
        return UNSConfig(
            enterprise="test_enterprise",
            site="test_site",
            topic_prefix="umh/v1",
        )

    @pytest.fixture
    def client(self, mqtt_config, uns_config):
        return MQTTClient(mqtt_config, uns_config)

    def test_base_topic(self, client):
        assert client.base_topic == "umh/v1/test_enterprise/test_site"

    def test_initial_level(self, client):
        assert client.current_level == ComplexityLevel.LEVEL_2_STATEFUL

    def test_set_level(self, client):
        callback_called = []
        client.on_level_change = lambda l: callback_called.append(l)

        client.set_level(ComplexityLevel.LEVEL_3_ERP_MES)

        assert client.current_level == ComplexityLevel.LEVEL_3_ERP_MES
        assert len(callback_called) == 1
        assert callback_called[0] == ComplexityLevel.LEVEL_3_ERP_MES

    def test_publish_respects_level(self, client):
        client._current_level = ComplexityLevel.LEVEL_1_SENSORS
        client._connected = True

        # Should succeed for Level 1
        result1 = client.publish(
            "test/topic",
            {"value": 1},
            required_level=ComplexityLevel.LEVEL_1_SENSORS,
        )
        assert result1 is True

        # Should fail for Level 3 (current is 1)
        result2 = client.publish(
            "test/topic",
            {"value": 2},
            required_level=ComplexityLevel.LEVEL_3_ERP_MES,
        )
        assert result2 is False

    def test_dry_run_connect(self, client):
        result = client.connect(dry_run=True)

        assert result is True
        assert client.connected is True

    def test_dry_run_disconnect(self, client):
        client.connect(dry_run=True)
        client.disconnect()

        assert client.connected is False


class TestMessage:
    """Tests for Message dataclass."""

    def test_message_defaults(self):
        msg = Message(topic="test", payload={"value": 1})

        assert msg.retain is False
        assert msg.qos == 1

    def test_message_with_retain(self):
        msg = Message(topic="test", payload={"value": 1}, retain=True)

        assert msg.retain is True


class TestPublishWhileDisconnected:
    """A message that cannot reach the broker must be counted and logged, not dropped silently."""

    @pytest.fixture
    def client(self):
        return MQTTClient(
            MQTTConfig(broker="localhost", port=1883, client_id="test-client"),
            UNSConfig(enterprise="test_enterprise", site="test_site", topic_prefix="umh/v1"),
        )

    def test_disconnected_publish_counts_as_dropped_and_warns(self, client, caplog):
        assert not client.connected

        with caplog.at_level("WARNING", logger="metalfab_uns_sim.mqtt_client"):
            client._do_publish(Message(topic="umh/v1/test/x", payload={"v": 1}))

        assert client._messages_dropped == 1
        assert client._messages_published == 0
        assert "umh/v1/test/x" in caplog.text


class TestSemanticPublisherHealth:
    """The multi-site publisher must notice a rejected publish, once per transition."""

    @pytest.fixture
    def publisher(self):
        from metalfab_uns_sim.multi_site import SemanticPublisher

        pub = SemanticPublisher()
        pub.client = MagicMock()
        return pub

    def test_rejected_publish_is_counted_and_warned_once(self, publisher, caplog):
        import paho.mqtt.client as mqtt

        publisher.client.publish.return_value = MagicMock(rc=mqtt.MQTT_ERR_NO_CONN)

        with caplog.at_level("WARNING", logger="metalfab_uns_sim.multi_site"):
            publisher.publish("umh/v1/metalfab/a/b/c", 1)
            publisher.publish("umh/v1/metalfab/a/b/d", 2)

        assert publisher.messages_dropped == 2
        assert publisher.messages_published == 0
        assert caplog.text.count("messages are being dropped") == 1

    def test_recovery_is_logged_and_counted(self, publisher, caplog):
        import paho.mqtt.client as mqtt

        publisher.client.publish.return_value = MagicMock(rc=mqtt.MQTT_ERR_NO_CONN)
        publisher.publish("umh/v1/metalfab/a/b/c", 1)

        publisher.client.publish.return_value = MagicMock(rc=mqtt.MQTT_ERR_SUCCESS)
        with caplog.at_level("INFO", logger="metalfab_uns_sim.multi_site"):
            publisher.publish("umh/v1/metalfab/a/b/c", 2)

        assert publisher.messages_dropped == 1
        assert publisher.messages_published == 1
        assert "Publishing recovered" in caplog.text
