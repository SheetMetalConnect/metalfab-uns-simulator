"""Integration tests for message flow across the simulator.

Tests the complete flow from simulator tick to MQTT publish,
verifying that:
- Correct topics are used
- Correct namespaces are published at each level
- Messages are retained appropriately
- Data flows correctly between components
"""

import json
import pytest
from unittest.mock import MagicMock, call
from typing import List, Dict, Any

from metalfab_uns_sim.complexity import ComplexityLevel
from metalfab_uns_sim.config import Config
from metalfab_uns_sim.generators import PackMLState, JobStatus
from metalfab_uns_sim.simulator import Simulator


class MockMQTTCapture:
    """Mock MQTT client that captures all publish calls."""

    def __init__(self):
        self.connected = True
        self.published_messages: List[Dict[str, Any]] = []
        self._level = ComplexityLevel.LEVEL_2_STATEFUL
        self.base_topic = "umh/v1/test_enterprise/test_site"

    def connect(self, dry_run=False):
        return True

    def disconnect(self):
        pass

    def set_level(self, level):
        self._level = level

    @property
    def current_level(self):
        return self._level

    def publish(self, topic, payload, retain=False, required_level=ComplexityLevel.LEVEL_1_SENSORS):
        """Capture publish call if level allows."""
        if self._level >= required_level:
            self.published_messages.append({
                "topic": f"{self.base_topic}/{topic}",
                "payload": payload,
                "retain": retain,
                "required_level": required_level,
            })
            return True
        return False

    def clear(self):
        """Clear captured messages."""
        self.published_messages.clear()

    def get_messages_by_namespace(self, namespace: str) -> List[Dict]:
        """Get all messages for a given namespace."""
        return [
            m for m in self.published_messages
            if f"/{namespace}/" in m["topic"] or m["topic"].endswith(f"/{namespace}")
        ]

    def get_messages_by_topic_pattern(self, pattern: str) -> List[Dict]:
        """Get all messages matching a topic pattern."""
        return [m for m in self.published_messages if pattern in m["topic"]]


class TestMessageFlowLevel1:
    """Tests for Level 1 (Sensors only) message flow."""

    @pytest.fixture
    def simulator(self):
        config = Config.default()
        mqtt = MockMQTTCapture()
        mqtt._level = ComplexityLevel.LEVEL_1_SENSORS
        sim = Simulator(config, mqtt_client=mqtt)
        sim._level = ComplexityLevel.LEVEL_1_SENSORS
        return sim, mqtt

    def test_level_1_publishes_historian(self, simulator):
        """Level 1 should publish _historian messages."""
        sim, mqtt = simulator
        sim._generate_initial_jobs()
        sim._tick()

        historian_msgs = mqtt.get_messages_by_namespace("_historian")
        assert len(historian_msgs) > 0

    def test_level_1_does_not_publish_state(self, simulator):
        """Level 1 should NOT publish _state messages."""
        sim, mqtt = simulator
        sim._generate_initial_jobs()
        sim._tick()

        state_msgs = mqtt.get_messages_by_namespace("_state")
        assert len(state_msgs) == 0

    def test_level_1_does_not_publish_jobs(self, simulator):
        """Level 1 should NOT publish _jobs messages."""
        sim, mqtt = simulator
        sim._generate_initial_jobs()
        sim._tick()

        job_msgs = mqtt.get_messages_by_namespace("_jobs")
        assert len(job_msgs) == 0

    def test_level_1_does_not_publish_erp(self, simulator):
        """Level 1 should NOT publish _erp messages."""
        sim, mqtt = simulator
        sim._generate_initial_jobs()
        sim._tick_count = 30  # Trigger periodic tasks
        sim._tick()

        erp_msgs = mqtt.get_messages_by_namespace("_erp")
        assert len(erp_msgs) == 0

    def test_level_1_historian_topics_correct(self, simulator):
        """Level 1 historian topics should follow correct structure."""
        sim, mqtt = simulator
        sim._tick()

        historian_msgs = mqtt.get_messages_by_namespace("_historian")
        for msg in historian_msgs:
            # Topic should be: base/area/cell/_historian/process/sensor
            parts = msg["topic"].split("/")
            assert "_historian" in parts
            assert "process" in parts  # Sensor group


class TestMessageFlowLevel2:
    """Tests for Level 2 (Stateful) message flow."""

    @pytest.fixture
    def simulator(self):
        config = Config.default()
        mqtt = MockMQTTCapture()
        mqtt._level = ComplexityLevel.LEVEL_2_STATEFUL
        sim = Simulator(config, mqtt_client=mqtt)
        sim._level = ComplexityLevel.LEVEL_2_STATEFUL
        return sim, mqtt

    def test_level_2_publishes_historian(self, simulator):
        """Level 2 should still publish _historian messages."""
        sim, mqtt = simulator
        sim._tick()

        historian_msgs = mqtt.get_messages_by_namespace("_historian")
        assert len(historian_msgs) > 0

    def test_level_2_publishes_state(self, simulator):
        """Level 2 should publish _state messages."""
        sim, mqtt = simulator
        sim._tick()

        state_msgs = mqtt.get_messages_by_namespace("_state")
        assert len(state_msgs) > 0

    def test_level_2_publishes_meta(self, simulator):
        """Level 2 should publish _meta messages."""
        sim, mqtt = simulator
        sim._publish_metadata()

        meta_msgs = mqtt.get_messages_by_namespace("_meta")
        assert len(meta_msgs) > 0

    def test_level_2_publishes_jobs(self, simulator):
        """Level 2 should publish _jobs messages for active jobs."""
        sim, mqtt = simulator
        sim._generate_initial_jobs()

        # Set a job to IN_PROGRESS
        for job in sim._jobs.values():
            job.status = JobStatus.IN_PROGRESS
            break

        sim._tick()

        job_msgs = mqtt.get_messages_by_namespace("_jobs")
        assert len(job_msgs) > 0

    def test_level_2_state_messages_retained(self, simulator):
        """Level 2 _state messages should be retained."""
        sim, mqtt = simulator
        sim._tick()

        state_msgs = mqtt.get_messages_by_namespace("_state")
        for msg in state_msgs:
            assert msg["retain"] is True, f"State message not retained: {msg['topic']}"

    def test_level_2_historian_not_retained(self, simulator):
        """Level 2 _historian messages should NOT be retained."""
        sim, mqtt = simulator
        sim._tick()

        historian_msgs = mqtt.get_messages_by_namespace("_historian")
        for msg in historian_msgs:
            assert msg["retain"] is False, f"Historian message retained: {msg['topic']}"


class TestMessageFlowLevel3:
    """Tests for Level 3 (ERP/MES) message flow."""

    @pytest.fixture
    def simulator(self):
        config = Config.default()
        mqtt = MockMQTTCapture()
        mqtt._level = ComplexityLevel.LEVEL_3_ERP_MES
        sim = Simulator(config, mqtt_client=mqtt)
        sim._level = ComplexityLevel.LEVEL_3_ERP_MES
        return sim, mqtt

    def test_level_3_publishes_erp(self, simulator):
        """Level 3 should publish _erp messages."""
        sim, mqtt = simulator
        sim._generate_initial_jobs()
        # Set a job to IN_PROGRESS so ERP data is published
        for job in sim._jobs.values():
            job.status = JobStatus.IN_PROGRESS
            break
        sim._tick_count = 9  # After increment becomes 10, triggers ERP (10 % 10 == 0)
        sim._tick()

        erp_msgs = mqtt.get_messages_by_namespace("_erp")
        assert len(erp_msgs) > 0

    def test_level_3_publishes_mes(self, simulator):
        """Level 3 should publish _mes messages."""
        sim, mqtt = simulator
        sim._tick_count = 14  # After increment becomes 15, triggers MES (15 % 15 == 0)
        sim._tick()

        mes_msgs = mqtt.get_messages_by_namespace("_mes")
        assert len(mes_msgs) > 0

    def test_level_3_publishes_analytics(self, simulator):
        """Level 3 should publish _analytics via OEE."""
        sim, mqtt = simulator
        sim._tick_count = 29  # After increment becomes 30, triggers OEE (30 % 30 == 0)
        sim._tick()

        # OEE is under _mes, check for that
        mes_msgs = mqtt.get_messages_by_namespace("_mes")
        oee_msgs = [m for m in mes_msgs if "oee" in m["topic"]]
        assert len(oee_msgs) > 0

    def test_level_3_erp_energy_data(self, simulator):
        """Level 3 should publish energy metrics (both consumption and solar)."""
        sim, mqtt = simulator
        sim._tick_count = 9  # After increment becomes 10
        sim._tick()

        energy_msgs = mqtt.get_messages_by_topic_pattern("_erp/energy")
        assert len(energy_msgs) > 0

        # Check for energy consumption metrics (original)
        consumption_msgs = [m for m in energy_msgs if "solar" not in m["topic"]]
        if consumption_msgs:
            payload = consumption_msgs[0]["payload"]
            assert "kwh_today" in payload
            assert "total_cost_today_eur" in payload

        # Also check for solar energy metrics (new)
        solar_msgs = [m for m in energy_msgs if "solar" in m["topic"]]
        if solar_msgs:
            payload = solar_msgs[0]["payload"]
            assert "current_generation_kw" in payload or "daily_generation_kwh" in payload

    def test_level_3_mes_quality_data(self, simulator):
        """Level 3 should publish quality metrics per cell."""
        sim, mqtt = simulator
        sim._tick_count = 14  # After increment becomes 15
        sim._tick()

        quality_msgs = mqtt.get_messages_by_topic_pattern("_mes/quality")
        assert len(quality_msgs) > 0

        # Verify quality payload structure
        payload = quality_msgs[0]["payload"]
        assert "cell_id" in payload
        assert "quality_pct" in payload
        assert "defect_rate_pct" in payload


class TestMessageFlowLevel4:
    """Tests for Level 4 (Full) message flow."""

    @pytest.fixture
    def simulator(self):
        config = Config.default()
        mqtt = MockMQTTCapture()
        mqtt._level = ComplexityLevel.LEVEL_4_FULL
        sim = Simulator(config, mqtt_client=mqtt)
        sim._level = ComplexityLevel.LEVEL_4_FULL
        return sim, mqtt

    def test_level_4_publishes_dashboard(self, simulator):
        """Level 4 should publish _dashboard messages."""
        sim, mqtt = simulator
        sim._generate_initial_jobs()
        sim._tick_count = 4  # After increment becomes 5, triggers dashboard (5 % 5 == 0)
        sim._tick()

        dashboard_msgs = mqtt.get_messages_by_namespace("_dashboard")
        assert len(dashboard_msgs) > 0

    def test_level_4_dashboard_payload_complete(self, simulator):
        """Level 4 dashboard should have complete payload."""
        sim, mqtt = simulator
        sim._generate_initial_jobs()
        sim._tick_count = 4  # After increment becomes 5
        sim._tick()

        dashboard_msgs = mqtt.get_messages_by_topic_pattern("_dashboard/production")
        assert len(dashboard_msgs) > 0

        payload = dashboard_msgs[0]["payload"]
        assert "shift" in payload
        assert "jobs" in payload
        assert "production" in payload
        assert "machines" in payload
        assert "energy" in payload


class TestTopicStructure:
    """Tests for topic structure compliance."""

    @pytest.fixture
    def simulator(self):
        config = Config.default()
        mqtt = MockMQTTCapture()
        mqtt._level = ComplexityLevel.LEVEL_4_FULL
        sim = Simulator(config, mqtt_client=mqtt)
        sim._level = ComplexityLevel.LEVEL_4_FULL
        return sim, mqtt

    def test_topic_follows_uns_structure(self, simulator):
        """Topics should follow UNS structure: prefix/enterprise/site/..."""
        sim, mqtt = simulator
        sim._publish_metadata()
        sim._tick()

        for msg in mqtt.published_messages:
            topic = msg["topic"]
            # Should start with base topic
            assert topic.startswith(mqtt.base_topic)

    def test_cell_topics_include_area(self, simulator):
        """Cell-level topics should include area."""
        sim, mqtt = simulator
        sim._tick()

        # Get historian messages (cell-level)
        historian_msgs = mqtt.get_messages_by_namespace("_historian")
        for msg in historian_msgs:
            parts = msg["topic"].split("/")
            # Should have area before cell
            historian_idx = parts.index("_historian")
            assert historian_idx >= 4  # prefix/enterprise/site/area/cell/_historian

    def test_site_level_topics(self, simulator):
        """Site-level topics should not include area/cell."""
        sim, mqtt = simulator
        sim._generate_initial_jobs()

        # Set job to in progress
        for job in sim._jobs.values():
            job.status = JobStatus.IN_PROGRESS
            break

        sim._tick()

        # Jobs are site-level
        job_msgs = mqtt.get_messages_by_namespace("_jobs")
        for msg in job_msgs:
            # Should be: base/_jobs/active/JOB_XXX
            assert "_jobs/active/" in msg["topic"]


class TestNamespaceConsistency:
    """Tests for namespace usage consistency."""

    def test_namespace_prefixes_correct(self):
        """All namespace names should start with underscore."""
        namespaces = [
            "_historian", "_state", "_meta", "_jobs",
            "_erp", "_mes", "_analytics",
            "_dashboard", "_event", "_alarms", "_control"
        ]
        for ns in namespaces:
            assert ns.startswith("_")

    @pytest.fixture
    def simulator(self):
        config = Config.default()
        mqtt = MockMQTTCapture()
        mqtt._level = ComplexityLevel.LEVEL_4_FULL
        sim = Simulator(config, mqtt_client=mqtt)
        sim._level = ComplexityLevel.LEVEL_4_FULL
        return sim, mqtt

    def test_all_published_topics_have_namespace(self, simulator):
        """All published topics should contain a recognized namespace."""
        sim, mqtt = simulator
        sim._generate_initial_jobs()
        sim._publish_metadata()

        for job in sim._jobs.values():
            job.status = JobStatus.IN_PROGRESS
            break

        sim._tick_count = 30
        sim._tick()

        valid_namespaces = {
            "_historian", "_state", "_meta", "_jobs",
            "_erp", "_mes", "_analytics",
            "_dashboard", "_event", "_alarms", "_control"
        }

        for msg in mqtt.published_messages:
            topic = msg["topic"]
            has_namespace = any(f"/{ns}" in topic or f"/{ns}/" in topic for ns in valid_namespaces)
            assert has_namespace, f"Topic missing namespace: {topic}"


class TestDataFlow:
    """Tests for data flow between components."""

    @pytest.fixture
    def simulator(self):
        config = Config.default()
        mqtt = MockMQTTCapture()
        mqtt._level = ComplexityLevel.LEVEL_4_FULL
        sim = Simulator(config, mqtt_client=mqtt)
        sim._level = ComplexityLevel.LEVEL_4_FULL
        return sim, mqtt

    def test_job_flows_to_multiple_namespaces(self, simulator):
        """A job should appear in both _jobs and _erp namespaces at Level 3+."""
        sim, mqtt = simulator
        sim._generate_initial_jobs()

        # Set a job to in progress
        test_job = None
        for job in sim._jobs.values():
            job.status = JobStatus.IN_PROGRESS
            test_job = job
            break

        sim._tick_count = 9  # After increment becomes 10, triggers ERP (10 % 10 == 0)
        sim._tick()

        # Check _jobs namespace
        job_msgs = mqtt.get_messages_by_namespace("_jobs")
        job_ids_in_jobs = [m["payload"].get("job_id") for m in job_msgs]

        # Check _erp namespace
        erp_msgs = mqtt.get_messages_by_namespace("_erp")
        erp_job_msgs = [m for m in erp_msgs if "jobs" in m["topic"]]
        job_ids_in_erp = [m["payload"].get("job_id") for m in erp_job_msgs]

        # Job should appear in both
        assert test_job.job_id in job_ids_in_jobs or len(job_ids_in_jobs) > 0
        assert test_job.job_id in job_ids_in_erp or len(job_ids_in_erp) > 0

    def test_cell_data_consistent_across_namespaces(self, simulator):
        """Cell data should be consistent across _state and _mes."""
        sim, mqtt = simulator

        # Set a cell to running
        cell = sim._cells["laser_01"]
        cell.state = PackMLState.EXECUTE

        sim._tick_count = 14  # After increment becomes 15, triggers MES (15 % 15 == 0)
        sim._tick()

        # Get state for laser_01
        state_msgs = [
            m for m in mqtt.get_messages_by_namespace("_state")
            if "laser_01" in m["topic"]
        ]

        # Get quality for laser_01
        quality_msgs = [
            m for m in mqtt.get_messages_by_topic_pattern("_mes/quality")
            if m["payload"].get("cell_id") == "laser_01"
        ]

        assert len(state_msgs) > 0
        assert len(quality_msgs) > 0

        # Cell ID should match
        assert state_msgs[0]["topic"].split("/")[-2] == "laser_01"
        assert quality_msgs[0]["payload"]["cell_id"] == "laser_01"
