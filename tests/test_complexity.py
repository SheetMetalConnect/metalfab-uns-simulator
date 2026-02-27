"""Tests for complexity levels."""

import pytest
from metalfab_uns_sim.complexity import (
    ComplexityLevel,
    get_features_for_level,
    get_namespaces_for_level,
)


class TestComplexityLevel:
    """Tests for ComplexityLevel enum."""

    def test_levels_are_ordered(self):
        assert ComplexityLevel.LEVEL_1_SENSORS < ComplexityLevel.LEVEL_2_STATEFUL
        assert ComplexityLevel.LEVEL_2_STATEFUL < ComplexityLevel.LEVEL_3_ERP_MES
        assert ComplexityLevel.LEVEL_3_ERP_MES < ComplexityLevel.LEVEL_4_FULL

    def test_level_values(self):
        assert ComplexityLevel.LEVEL_1_SENSORS.value == 1
        assert ComplexityLevel.LEVEL_2_STATEFUL.value == 2
        assert ComplexityLevel.LEVEL_3_ERP_MES.value == 3
        assert ComplexityLevel.LEVEL_4_FULL.value == 4


class TestGetFeaturesForLevel:
    """Tests for get_features_for_level."""

    def test_level_1_features(self):
        features = get_features_for_level(ComplexityLevel.LEVEL_1_SENSORS)

        # Level 1 features enabled
        assert features.sensors is True
        assert features.energy_basic is True

        # Higher level features disabled
        assert features.machine_state is False
        assert features.erp_job_data is False
        assert features.dashboards is False

    def test_level_2_features(self):
        features = get_features_for_level(ComplexityLevel.LEVEL_2_STATEFUL)

        # Level 1 features still enabled
        assert features.sensors is True

        # Level 2 features enabled
        assert features.machine_state is True
        assert features.job_tracking is True
        assert features.agv_positions is True
        assert features.retain_messages is True

        # Level 3 features disabled
        assert features.erp_job_data is False

    def test_level_3_features(self):
        features = get_features_for_level(ComplexityLevel.LEVEL_3_ERP_MES)

        # Lower level features enabled
        assert features.sensors is True
        assert features.machine_state is True

        # Level 3 features enabled
        assert features.erp_job_data is True
        assert features.mes_quality is True
        assert features.mes_oee is True
        assert features.delivery_metrics is True
        assert features.inventory_wip is True
        assert features.dashboards is True

        # Level 4 features disabled
        assert features.dpp is False

    def test_level_4_features(self):
        features = get_features_for_level(ComplexityLevel.LEVEL_4_FULL)

        # All features enabled
        assert features.sensors is True
        assert features.machine_state is True
        assert features.erp_job_data is True
        assert features.historian_erp_mes is True
        assert features.analytics_advanced is True
        assert features.events_alarms is True
        assert features.dashboards is True


class TestGetNamespacesForLevel:
    """Tests for get_namespaces_for_level."""

    def test_level_1_namespaces(self):
        ns = get_namespaces_for_level(ComplexityLevel.LEVEL_1_SENSORS)

        assert "_historian" in ns
        assert "_state" not in ns
        assert "_erp" not in ns

    def test_level_2_namespaces(self):
        ns = get_namespaces_for_level(ComplexityLevel.LEVEL_2_STATEFUL)

        assert "_historian" in ns
        assert "_state" in ns
        assert "_meta" in ns
        assert "_jobs" in ns
        assert "_erp" not in ns

    def test_level_3_namespaces(self):
        ns = get_namespaces_for_level(ComplexityLevel.LEVEL_3_ERP_MES)

        assert "_historian" in ns
        assert "_state" in ns
        assert "_erp" in ns
        assert "_mes" in ns
        assert "_dashboard" in ns
        assert "_analytics" not in ns

    def test_level_4_namespaces(self):
        ns = get_namespaces_for_level(ComplexityLevel.LEVEL_4_FULL)

        # All namespaces present
        expected = {
            "_historian", "_state", "_meta", "_jobs",
            "_erp", "_mes", "_dashboard",
            "_analytics", "_event", "_alarms", "_dpp"
        }
        assert ns == expected
