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
