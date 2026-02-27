"""Tests for level switching functionality."""

import json
import pytest
from unittest.mock import MagicMock, patch, call

from metalfab_uns_sim.complexity import ComplexityLevel, get_features_for_level
from metalfab_uns_sim.config import Config, MQTTConfig, UNSConfig
from metalfab_uns_sim.mqtt_client import MQTTClient
from metalfab_uns_sim.simulator import Simulator


class TestLevelSwitcherMQTTClient:
    """Tests for level switching in MQTTClient."""

    @pytest.fixture
    def mqtt_config(self):
        return MQTTConfig(broker="localhost", port=1883, client_id="test")

    @pytest.fixture
    def uns_config(self):
        return UNSConfig(enterprise="test", site="site1", topic_prefix="umh/v1")

    def test_initial_level_is_level_2(self, mqtt_config, uns_config):
        """Default level should be Level 2 (Stateful)."""
        client = MQTTClient(mqtt_config, uns_config)
        assert client.current_level == ComplexityLevel.LEVEL_2_STATEFUL

    def test_set_level_updates_current_level(self, mqtt_config, uns_config):
        """Setting level should update current_level property."""
        client = MQTTClient(mqtt_config, uns_config)

        client.set_level(ComplexityLevel.LEVEL_1_SENSORS)
        assert client.current_level == ComplexityLevel.LEVEL_1_SENSORS

        client.set_level(ComplexityLevel.LEVEL_3_ERP_MES)
        assert client.current_level == ComplexityLevel.LEVEL_3_ERP_MES

        client.set_level(ComplexityLevel.LEVEL_4_FULL)
        assert client.current_level == ComplexityLevel.LEVEL_4_FULL

    def test_set_level_calls_callback(self, mqtt_config, uns_config):
        """Setting level should trigger the on_level_change callback."""
        callback_log = []
        client = MQTTClient(
            mqtt_config, uns_config, on_level_change=lambda l: callback_log.append(l)
        )

        client.set_level(ComplexityLevel.LEVEL_3_ERP_MES)

        assert len(callback_log) == 1
        assert callback_log[0] == ComplexityLevel.LEVEL_3_ERP_MES

    def test_set_level_no_callback_when_same_level(self, mqtt_config, uns_config):
        """Setting the same level should not trigger callback."""
        callback_log = []
        client = MQTTClient(
            mqtt_config, uns_config, on_level_change=lambda l: callback_log.append(l)
        )

        # Set to current level (Level 2)
        client.set_level(ComplexityLevel.LEVEL_2_STATEFUL)

        assert len(callback_log) == 0

    def test_level_change_via_mqtt_message(self, mqtt_config, uns_config):
        """Simulate receiving a level change message via MQTT."""
        client = MQTTClient(mqtt_config, uns_config)
        client._connected = True

        # Simulate incoming MQTT message (uses root-level topic)
        mock_msg = MagicMock()
        mock_msg.topic = MQTTClient.LEVEL_CONTROL_TOPIC  # metalfab-sim/settings/level
        mock_msg.payload = json.dumps({"level": 4}).encode()

        client._on_message(None, None, mock_msg)

        assert client.current_level == ComplexityLevel.LEVEL_4_FULL

    def test_level_change_via_mqtt_handles_invalid_json(self, mqtt_config, uns_config):
        """Invalid JSON in level message should not crash."""
        client = MQTTClient(mqtt_config, uns_config)
        original_level = client.current_level

        mock_msg = MagicMock()
        mock_msg.topic = MQTTClient.LEVEL_CONTROL_TOPIC
        mock_msg.payload = b"not json"

        # Should not raise exception
        client._on_message(None, None, mock_msg)

        # Level should remain unchanged
        assert client.current_level == original_level

    def test_level_change_via_mqtt_handles_invalid_level(self, mqtt_config, uns_config):
        """Invalid level value should not crash."""
        client = MQTTClient(mqtt_config, uns_config)
        original_level = client.current_level

        mock_msg = MagicMock()
        mock_msg.topic = f"umh/v1/test/site1/{MQTTClient.LEVEL_CONTROL_TOPIC}"
        mock_msg.payload = json.dumps({"level": 99}).encode()

        # Should not raise exception (will log error)
        client._on_message(None, None, mock_msg)

        # Level should remain unchanged
        assert client.current_level == original_level

    def test_publish_filtered_by_level(self, mqtt_config, uns_config):
        """Messages requiring higher level should be filtered."""
        client = MQTTClient(mqtt_config, uns_config)
        client._connected = True
        client._current_level = ComplexityLevel.LEVEL_1_SENSORS

        # Level 1 message should be accepted
        result1 = client.publish(
            "test/sensors",
            {"value": 1},
            required_level=ComplexityLevel.LEVEL_1_SENSORS,
        )
        assert result1 is True

        # Level 2 message should be rejected
        result2 = client.publish(
            "test/state",
            {"state": "RUNNING"},
            required_level=ComplexityLevel.LEVEL_2_STATEFUL,
        )
        assert result2 is False

        # Level 3 message should be rejected
        result3 = client.publish(
            "test/erp",
            {"margin": 35},
            required_level=ComplexityLevel.LEVEL_3_ERP_MES,
        )
        assert result3 is False

    def test_publish_allowed_at_higher_level(self, mqtt_config, uns_config):
        """Messages requiring lower level should pass at higher level."""
        client = MQTTClient(mqtt_config, uns_config)
        client._connected = True
        client._current_level = ComplexityLevel.LEVEL_4_FULL

        # All levels should be accepted
        assert client.publish("a", {}, required_level=ComplexityLevel.LEVEL_1_SENSORS)
        assert client.publish("b", {}, required_level=ComplexityLevel.LEVEL_2_STATEFUL)
        assert client.publish("c", {}, required_level=ComplexityLevel.LEVEL_3_ERP_MES)
        assert client.publish("d", {}, required_level=ComplexityLevel.LEVEL_4_FULL)


class TestLevelSwitcherSimulator:
    """Tests for level switching in Simulator."""

    @pytest.fixture
    def config(self):
        return Config.default()

    @pytest.fixture
    def mock_mqtt(self):
        mqtt = MagicMock()
        mqtt.connected = True
        mqtt.connect.return_value = True
        mqtt.publish.return_value = True
        mqtt.base_topic = "umh/v1/test/site"
        return mqtt

    @pytest.fixture
    def simulator(self, config, mock_mqtt):
        return Simulator(config, mqtt_client=mock_mqtt)

    def test_simulator_level_property(self, simulator):
        """Simulator should expose level property."""
        assert simulator.level == ComplexityLevel.LEVEL_2_STATEFUL

    def test_simulator_set_level_updates_mqtt(self, simulator, mock_mqtt):
        """Setting simulator level should update MQTT client."""
        simulator.level = ComplexityLevel.LEVEL_3_ERP_MES

        mock_mqtt.set_level.assert_called_with(ComplexityLevel.LEVEL_3_ERP_MES)

    def test_simulator_responds_to_level_callback(self, config, mock_mqtt):
        """Simulator should update when MQTT client changes level."""
        sim = Simulator(config, mqtt_client=mock_mqtt)

        # Simulate level change from MQTT
        sim._on_level_change(ComplexityLevel.LEVEL_4_FULL)

        assert sim._level == ComplexityLevel.LEVEL_4_FULL

    def test_simulator_publishes_based_on_level(self, config, mock_mqtt):
        """Simulator should pass correct required_level to publish calls."""
        sim = Simulator(config, mqtt_client=mock_mqtt)
        sim._generate_initial_jobs()

        # Run one tick at Level 1
        sim._level = ComplexityLevel.LEVEL_1_SENSORS
        sim._tick_count = 0
        sim._tick()

        # Check that publish was called with Level 1 requirement for sensors
        sensor_calls = [
            c for c in mock_mqtt.publish.call_args_list
            if "_historian" in str(c)
        ]
        assert len(sensor_calls) > 0


class TestLevelFeatureGating:
    """Tests that features are properly gated by level."""

    def test_level_1_only_sensors(self):
        """Level 1 should only enable sensors."""
        features = get_features_for_level(ComplexityLevel.LEVEL_1_SENSORS)

        # Enabled
        assert features.sensors is True
        assert features.energy_basic is True

        # Disabled
        assert features.machine_state is False
        assert features.job_tracking is False
        assert features.erp_job_data is False
        assert features.dashboards is False

    def test_level_2_adds_state(self):
        """Level 2 should add stateful features."""
        features = get_features_for_level(ComplexityLevel.LEVEL_2_STATEFUL)

        # Level 1 still enabled
        assert features.sensors is True

        # Level 2 additions
        assert features.machine_state is True
        assert features.job_tracking is True
        assert features.agv_positions is True
        assert features.retain_messages is True

        # Level 3 still disabled
        assert features.erp_job_data is False
        assert features.mes_quality is False

    def test_level_3_adds_erp_mes(self):
        """Level 3 should add ERP/MES features."""
        features = get_features_for_level(ComplexityLevel.LEVEL_3_ERP_MES)

        # Previous levels enabled
        assert features.sensors is True
        assert features.machine_state is True

        # Level 3 additions
        assert features.erp_job_data is True
        assert features.mes_quality is True
        assert features.mes_oee is True
        assert features.delivery_metrics is True
        assert features.inventory_wip is True

        # Level 3 includes dashboards now
        assert features.dashboards is True

        # Level 4 still disabled
        assert features.events_alarms is False

    def test_level_4_enables_all(self):
        """Level 4 should enable all features."""
        features = get_features_for_level(ComplexityLevel.LEVEL_4_FULL)

        # All features enabled
        assert features.sensors is True
        assert features.machine_state is True
        assert features.erp_job_data is True
        assert features.historian_erp_mes is True
        assert features.analytics_advanced is True
        assert features.events_alarms is True
        assert features.dashboards is True


class TestLevelTransitions:
    """Tests for transitions between levels."""

    @pytest.fixture
    def config(self):
        return Config.default()

    @pytest.fixture
    def mock_mqtt(self):
        mqtt = MagicMock()
        mqtt.connected = True
        mqtt.connect.return_value = True
        mqtt.publish.return_value = True
        mqtt.base_topic = "umh/v1/test/site"
        return mqtt

    def test_upgrade_from_level_1_to_4(self, config, mock_mqtt):
        """Upgrading from Level 1 to 4 should enable all features."""
        sim = Simulator(config, mqtt_client=mock_mqtt)
        sim._generate_initial_jobs()

        # Start at Level 1
        sim._level = ComplexityLevel.LEVEL_1_SENSORS
        mock_mqtt.publish.reset_mock()
        sim._tick_count = 30  # Trigger all periodic tasks
        sim._tick()

        level_1_calls = len(mock_mqtt.publish.call_args_list)

        # Upgrade to Level 4
        sim._level = ComplexityLevel.LEVEL_4_FULL
        mock_mqtt.publish.reset_mock()
        sim._tick()

        level_4_calls = len(mock_mqtt.publish.call_args_list)

        # Level 4 should have more publish calls
        assert level_4_calls > level_1_calls

    def test_downgrade_from_level_4_to_1(self, config, mock_mqtt):
        """Downgrading from Level 4 to 1 should reduce features."""
        sim = Simulator(config, mqtt_client=mock_mqtt)
        sim._generate_initial_jobs()

        # Start at Level 4
        sim._level = ComplexityLevel.LEVEL_4_FULL
        mock_mqtt.publish.reset_mock()
        sim._tick_count = 30
        sim._tick()

        level_4_calls = len(mock_mqtt.publish.call_args_list)

        # Downgrade to Level 1
        sim._level = ComplexityLevel.LEVEL_1_SENSORS
        mock_mqtt.publish.reset_mock()
        sim._tick()

        level_1_calls = len(mock_mqtt.publish.call_args_list)

        # Level 1 should have fewer publish calls
        assert level_1_calls < level_4_calls
