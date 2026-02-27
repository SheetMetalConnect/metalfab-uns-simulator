"""Tests for payload structure and content validation.

Validates that all message types have:
- Required fields present
- Correct data types
- Values in reasonable ranges
- Proper timestamp formats
"""

import re
from datetime import datetime
from typing import Any, Dict, List

import pytest

from metalfab_uns_sim.generators import (
    ERPMESGenerator,
    Job,
    JobGenerator,
    JobPriority,
    JobStatus,
    PackMLState,
    SensorGenerator,
    create_sensor_generators,
)
from metalfab_uns_sim.config import Config
from metalfab_uns_sim.simulator import Simulator, CellState


# =============================================================================
# Helper Functions
# =============================================================================


def validate_timestamp_ms(value: int) -> bool:
    """Validate timestamp is a reasonable millisecond epoch."""
    # Should be after 2020 and before 2100
    min_ts = 1577836800000  # 2020-01-01
    max_ts = 4102444800000  # 2100-01-01
    return min_ts < value < max_ts


def validate_iso_timestamp(value: str) -> bool:
    """Validate ISO 8601 timestamp format."""
    pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    return bool(re.match(pattern, value))


def validate_percentage(value: float) -> bool:
    """Validate percentage is in 0-100 range."""
    return 0.0 <= value <= 100.0


# =============================================================================
# Sensor Payload Tests (Level 1 - _raw)
# =============================================================================


class TestSensorPayloads:
    """Tests for sensor/historian payloads."""

    def test_basic_sensor_payload_structure(self):
        """Basic sensor reading should have timestamp_ms and value."""
        gen = SensorGenerator("test_sensor", base_value=50.0)
        payload = gen.generate()

        assert "timestamp_ms" in payload
        assert "value" in payload
        assert isinstance(payload["timestamp_ms"], int)
        assert isinstance(payload["value"], float)

    def test_sensor_timestamp_is_valid(self):
        """Sensor timestamp should be a valid epoch milliseconds."""
        gen = SensorGenerator("test_sensor", base_value=50.0)
        payload = gen.generate()

        assert validate_timestamp_ms(payload["timestamp_ms"])

    def test_sensor_value_respects_range(self):
        """Sensor value should be within configured min/max."""
        gen = SensorGenerator(
            "test_sensor",
            base_value=50.0,
            min_value=10.0,
            max_value=90.0,
            noise_stddev=5.0,
        )

        for _ in range(100):
            payload = gen.generate()
            assert 10.0 <= payload["value"] <= 90.0

    def test_extended_sensor_payload_structure(self):
        """Extended sensor payload should include metadata."""
        gen = SensorGenerator("power_kw", base_value=10.0, unit="kW")
        payload = gen.generate_extended()

        assert "timestamp_ms" in payload
        assert "value" in payload
        assert "quality" in payload
        assert "unit" in payload
        assert "sensor_id" in payload

        assert payload["quality"] == "GOOD"
        assert payload["unit"] == "kW"
        assert payload["sensor_id"] == "power_kw"

    @pytest.mark.parametrize(
        "cell_type,expected_sensors",
        [
            ("laser_cutter", ["laser_power_pct", "cutting_speed_mmpm", "power_kw"]),
            ("press_brake", ["tonnage_t", "bend_angle_deg", "power_kw"]),
            ("robot_weld", ["weld_current_a", "weld_voltage_v", "wire_feed_mpm"]),
            ("paint_booth", ["temp_c", "humidity_pct", "airflow_cfm"]),
            ("agv", ["battery_pct", "speed_mps"]),
        ],
    )
    def test_cell_type_sensors_generate_valid_payloads(self, cell_type, expected_sensors):
        """Each cell type should generate valid sensor payloads."""
        sensors = create_sensor_generators(cell_type)

        for sensor_id in expected_sensors:
            assert sensor_id in sensors, f"Missing sensor {sensor_id} for {cell_type}"

            payload = sensors[sensor_id].generate()
            assert "timestamp_ms" in payload
            assert "value" in payload
            assert isinstance(payload["value"], (int, float))


# =============================================================================
# Job Payload Tests (Level 2 - _jobs, Level 3 - _erp)
# =============================================================================


class TestJobPayloads:
    """Tests for job state and ERP payloads."""

    @pytest.fixture
    def sample_job(self):
        """Create a sample job for testing."""
        from datetime import datetime, timedelta
        return Job(
            job_id="JOB_9942",
            job_number="WO-9942",
            job_name="Bracket Assembly Batch 42",
            customer="AutoCorp GmbH",
            status=JobStatus.IN_PROGRESS,
            priority=JobPriority.HIGH,
            qty_target=150,
            qty_complete=87,
            qty_scrap=2,
            routing=["laser_01", "press_brake_01", "weld_cell_01"],
            current_operation_idx=1,
            current_cell="press_brake_01",
            estimated_hours=12.5,
            actual_hours=10.4,
            material_cost=1250.00,
            quoted_price=3750.00,
            margin_pct=33.3,
            due_date=datetime.now() + timedelta(days=5),  # 5 days ahead = AHEAD status
        )

    def test_job_state_payload_structure(self, sample_job):
        """Job state payload should have required fields."""
        payload = sample_job.to_state_dict()

        # Required fields
        assert "job_id" in payload
        assert "job_number" in payload
        assert "job_name" in payload
        assert "status" in payload
        assert "current_cell" in payload
        assert "qty_target" in payload
        assert "qty_complete" in payload
        assert "qty_scrap" in payload
        assert "progress_pct" in payload
        assert "routing" in payload
        assert "_updated_at" in payload

    def test_job_state_payload_values(self, sample_job):
        """Job state payload values should be correct types and ranges."""
        payload = sample_job.to_state_dict()

        assert payload["job_id"] == "JOB_9942"
        assert payload["status"] == "IN_PROGRESS"
        assert payload["qty_target"] == 150
        assert payload["qty_complete"] == 87
        assert validate_percentage(payload["progress_pct"])
        assert isinstance(payload["routing"], list)
        assert validate_iso_timestamp(payload["_updated_at"])

    def test_job_progress_calculation(self, sample_job):
        """Progress percentage should be correctly calculated."""
        payload = sample_job.to_state_dict()

        expected_progress = round(87 / 150 * 100, 1)
        assert payload["progress_pct"] == expected_progress

    def test_job_erp_payload_structure(self, sample_job):
        """Job ERP payload should have required fields."""
        payload = sample_job.to_erp_dict()

        # Required ERP fields
        assert "job_id" in payload
        assert "customer" in payload
        assert "priority" in payload
        assert "lead_time_days" in payload
        assert "lead_time_status" in payload
        assert "estimated_hours" in payload
        assert "actual_hours" in payload
        assert "est_vs_actual_hours" in payload
        assert "quoted_price_eur" in payload  # Changed to _eur suffix
        assert "margin_pct" in payload

    def test_job_erp_payload_values(self, sample_job):
        """Job ERP payload values should be correct."""
        payload = sample_job.to_erp_dict()

        assert payload["customer"] == "AutoCorp GmbH"
        assert payload["priority"] == "HIGH"
        assert payload["estimated_hours"] == 12.5
        assert payload["actual_hours"] == 10.4
        assert payload["est_vs_actual_hours"] == pytest.approx(-2.1, rel=0.01)
        assert payload["margin_pct"] == 33.3

    def test_job_erp_lead_time_status(self, sample_job):
        """Lead time status should be one of expected values."""
        payload = sample_job.to_erp_dict()

        valid_statuses = ["AHEAD", "ON_TIME", "LATE"]
        assert payload["lead_time_status"] in valid_statuses

    def test_job_generator_creates_valid_jobs(self):
        """JobGenerator should create jobs with valid payloads."""
        templates = [
            {"name": "Test Part", "routing": ["laser_01", "press_brake_01"], "qty_range": (50, 100)}
        ]
        customers = ["Customer A", "Customer B"]

        gen = JobGenerator(templates, customers)

        for _ in range(10):
            job = gen.generate_job()

            # Check job attributes
            assert job.job_id.startswith("JOB_")
            assert job.customer in customers
            assert 50 <= job.qty_target <= 100
            assert job.routing == ["laser_01", "press_brake_01"]

            # Check payloads are valid
            state_payload = job.to_state_dict()
            assert state_payload["job_id"] == job.job_id

            erp_payload = job.to_erp_dict()
            assert erp_payload["customer"] == job.customer


# =============================================================================
# ERP/MES Metrics Payload Tests (Level 3)
# =============================================================================


class TestERPMESPayloads:
    """Tests for ERP/MES enrichment payloads."""

    @pytest.fixture
    def erp_mes_gen(self):
        return ERPMESGenerator()

    # -------------------------------------------------------------------------
    # Energy Metrics
    # -------------------------------------------------------------------------

    def test_energy_metrics_payload_structure(self, erp_mes_gen):
        """Energy metrics should have required fields."""
        cells = [{"power_kw": 10}, {"power_kw": 20}]
        payload = erp_mes_gen.generate_energy_metrics(cells)

        assert "kwh_today" in payload
        assert "kwh_this_shift" in payload
        assert "cost_per_kwh_eur" in payload
        assert "total_cost_today_eur" in payload
        assert "avg_cost_per_order_eur" in payload
        assert "timestamp_ms" in payload

    def test_energy_metrics_payload_values(self, erp_mes_gen):
        """Energy metrics should have valid values."""
        cells = [{"power_kw": 10}, {"power_kw": 20}]
        payload = erp_mes_gen.generate_energy_metrics(cells)

        assert payload["kwh_today"] > 0
        assert payload["cost_per_kwh_eur"] == 0.15
        assert payload["total_cost_today_eur"] > 0
        assert validate_timestamp_ms(payload["timestamp_ms"])

    # -------------------------------------------------------------------------
    # Quality Metrics
    # -------------------------------------------------------------------------

    def test_quality_metrics_payload_structure(self, erp_mes_gen):
        """Quality metrics should have required fields."""
        payload = erp_mes_gen.generate_quality_metrics("weld_cell_01")

        assert "cell_id" in payload
        assert "quality_pct" in payload
        assert "defect_rate_pct" in payload
        assert "scrap_count_today" in payload
        assert "rework_count_today" in payload
        assert "first_pass_yield_pct" in payload
        assert "timestamp_ms" in payload

    def test_quality_metrics_payload_values(self, erp_mes_gen):
        """Quality metrics should have valid values."""
        payload = erp_mes_gen.generate_quality_metrics("laser_01")

        assert payload["cell_id"] == "laser_01"
        assert validate_percentage(payload["quality_pct"])
        assert payload["defect_rate_pct"] >= 0
        assert payload["scrap_count_today"] >= 0
        assert payload["rework_count_today"] >= 0
        assert validate_percentage(payload["first_pass_yield_pct"])

    # -------------------------------------------------------------------------
    # OEE Metrics
    # -------------------------------------------------------------------------

    def test_oee_metrics_payload_structure(self, erp_mes_gen):
        """OEE metrics should have required fields."""
        payload = erp_mes_gen.generate_oee_metrics("press_brake_01")

        assert "cell_id" in payload
        assert "oee_pct" in payload
        assert "availability_pct" in payload
        assert "performance_pct" in payload
        assert "quality_pct" in payload
        assert "idle_time_min" in payload
        assert "downtime_min" in payload
        assert "period" in payload
        assert "timestamp_ms" in payload

    def test_oee_metrics_payload_values(self, erp_mes_gen):
        """OEE metrics should have valid values."""
        payload = erp_mes_gen.generate_oee_metrics("laser_01")

        # OEE components should be percentages
        assert validate_percentage(payload["oee_pct"])
        assert validate_percentage(payload["availability_pct"])
        assert validate_percentage(payload["performance_pct"])
        assert validate_percentage(payload["quality_pct"])

        # OEE should be product of components (approximately)
        calculated_oee = (
            payload["availability_pct"]
            * payload["performance_pct"]
            * payload["quality_pct"]
        ) / 10000
        assert payload["oee_pct"] == pytest.approx(calculated_oee, rel=0.01)

        # Time values should be non-negative
        assert payload["idle_time_min"] >= 0
        assert payload["downtime_min"] >= 0

        # Period should be a valid value
        assert payload["period"] in ["SHIFT", "DAY", "WEEK"]

    # -------------------------------------------------------------------------
    # Delivery Metrics
    # -------------------------------------------------------------------------

    def test_delivery_metrics_payload_structure(self, erp_mes_gen):
        """Delivery metrics should have required fields."""
        jobs = [Job("J1", "WO1", "Job 1", "C1")]
        payload = erp_mes_gen.generate_delivery_metrics(jobs)

        assert "on_time_pct" in payload
        assert "late_orders" in payload
        assert "orders_shipping_today" in payload
        assert "orders_due_this_week" in payload
        assert "avg_lead_time_days" in payload
        assert "timestamp_ms" in payload

    def test_delivery_metrics_payload_values(self, erp_mes_gen):
        """Delivery metrics should have valid values."""
        jobs = [
            Job("J1", "WO1", "Job 1", "C1"),
            Job("J2", "WO2", "Job 2", "C2"),
        ]
        payload = erp_mes_gen.generate_delivery_metrics(jobs)

        assert validate_percentage(payload["on_time_pct"])
        assert payload["late_orders"] >= 0
        assert payload["orders_shipping_today"] >= 0
        assert payload["avg_lead_time_days"] > 0

    # -------------------------------------------------------------------------
    # Inventory/WIP Metrics
    # -------------------------------------------------------------------------

    def test_inventory_metrics_payload_structure(self, erp_mes_gen):
        """Inventory metrics should have required fields."""
        jobs = []
        payload = erp_mes_gen.generate_inventory_metrics(jobs)

        assert "wip_value_eur" in payload
        assert "wip_orders" in payload
        assert "inventory_turns_yr" in payload
        assert "raw_material_value_eur" in payload
        assert "finished_goods_value_eur" in payload
        assert "timestamp_ms" in payload

    def test_inventory_metrics_payload_values(self, erp_mes_gen):
        """Inventory metrics should have valid values."""
        jobs = []
        payload = erp_mes_gen.generate_inventory_metrics(jobs)

        assert payload["wip_value_eur"] >= 0
        assert payload["wip_orders"] >= 0
        assert payload["inventory_turns_yr"] > 0
        assert payload["raw_material_value_eur"] > 0

    # -------------------------------------------------------------------------
    # Machine Utilization
    # -------------------------------------------------------------------------

    def test_machine_utilization_payload_structure(self, erp_mes_gen):
        """Machine utilization should have required fields."""
        states = {"laser_01": PackMLState.EXECUTE, "laser_02": PackMLState.IDLE}
        payload = erp_mes_gen.generate_machine_utilization(states)

        assert "fleet_utilization_pct" in payload
        assert "machines_running" in payload
        assert "machines_total" in payload
        assert "machines_idle" in payload
        assert "bottleneck_cell" in payload
        assert "bottleneck_queue_hours" in payload
        assert "timestamp_ms" in payload

    def test_machine_utilization_payload_values(self, erp_mes_gen):
        """Machine utilization should have valid values."""
        states = {
            "laser_01": PackMLState.EXECUTE,
            "laser_02": PackMLState.IDLE,
            "press_01": PackMLState.EXECUTE,
        }
        payload = erp_mes_gen.generate_machine_utilization(states)

        assert validate_percentage(payload["fleet_utilization_pct"])
        assert payload["machines_running"] == 2
        assert payload["machines_total"] == 3
        assert payload["machines_idle"] == 1
        assert payload["bottleneck_queue_hours"] >= 0

    # -------------------------------------------------------------------------
    # Quote Metrics
    # -------------------------------------------------------------------------

    def test_quote_metrics_payload_structure(self, erp_mes_gen):
        """Quote metrics should have required fields."""
        payload = erp_mes_gen.generate_quote_metrics()

        assert "quote_id" in payload
        assert "margin_pct" in payload
        assert "est_vs_actual_hours" in payload
        assert "quotes_pending" in payload
        assert "quotes_won_this_month" in payload
        assert "win_rate_pct" in payload
        assert "avg_quote_value_eur" in payload
        assert "timestamp_ms" in payload

    def test_quote_metrics_payload_values(self, erp_mes_gen):
        """Quote metrics should have valid values."""
        payload = erp_mes_gen.generate_quote_metrics()

        assert payload["quote_id"].startswith("QUOTE_")
        assert validate_percentage(payload["margin_pct"])
        assert validate_percentage(payload["win_rate_pct"])
        assert payload["quotes_pending"] >= 0
        assert payload["avg_quote_value_eur"] > 0


# =============================================================================
# Dashboard Payload Tests (Level 4)
# =============================================================================


class TestDashboardPayloads:
    """Tests for dashboard/aggregated payloads."""

    @pytest.fixture
    def erp_mes_gen(self):
        return ERPMESGenerator()

    def test_dashboard_summary_payload_structure(self, erp_mes_gen):
        """Dashboard summary should have required nested sections."""
        jobs = [Job("J1", "WO1", "Job 1", "C1")]
        states = {"laser_01": PackMLState.EXECUTE}
        payload = erp_mes_gen.generate_dashboard_summary(jobs, states)

        # Top-level sections
        assert "shift" in payload
        assert "jobs" in payload
        assert "production" in payload
        assert "machines" in payload
        assert "energy" in payload
        assert "_updated_at" in payload

    def test_dashboard_shift_section(self, erp_mes_gen):
        """Dashboard shift section should have valid values."""
        payload = erp_mes_gen.generate_dashboard_summary([], {})

        shift = payload["shift"]
        assert "current" in shift
        assert "start" in shift
        assert shift["current"] in ["DAY", "EVENING", "NIGHT"]
        assert validate_iso_timestamp(shift["start"])

    def test_dashboard_jobs_section(self, erp_mes_gen):
        """Dashboard jobs section should have valid values."""
        jobs = [
            Job("J1", "WO1", "Job 1", "C1", status=JobStatus.IN_PROGRESS),
            Job("J2", "WO2", "Job 2", "C2", status=JobStatus.IN_PROGRESS),
        ]
        payload = erp_mes_gen.generate_dashboard_summary(jobs, {})

        jobs_section = payload["jobs"]
        assert "active" in jobs_section
        assert "completed_today" in jobs_section
        assert "on_time_pct" in jobs_section

        assert jobs_section["active"] == 2
        assert jobs_section["completed_today"] >= 0
        assert validate_percentage(jobs_section["on_time_pct"])

    def test_dashboard_production_section(self, erp_mes_gen):
        """Dashboard production section should have valid values."""
        payload = erp_mes_gen.generate_dashboard_summary([], {})

        prod = payload["production"]
        assert "parts_today" in prod
        assert "scrap_pct" in prod
        assert "throughput_per_hour" in prod

        assert prod["parts_today"] >= 0
        assert validate_percentage(prod["scrap_pct"])
        assert prod["throughput_per_hour"] >= 0

    def test_dashboard_machines_section(self, erp_mes_gen):
        """Dashboard machines section should have valid values."""
        states = {
            "laser_01": PackMLState.EXECUTE,
            "laser_02": PackMLState.IDLE,
            "press_01": PackMLState.EXECUTE,
        }
        payload = erp_mes_gen.generate_dashboard_summary([], states)

        machines = payload["machines"]
        assert "running" in machines
        assert "total" in machines
        assert "utilization_pct" in machines

        assert machines["running"] == 2
        assert machines["total"] == 3
        assert validate_percentage(machines["utilization_pct"])

    def test_dashboard_energy_section(self, erp_mes_gen):
        """Dashboard energy section should have valid values."""
        payload = erp_mes_gen.generate_dashboard_summary([], {})

        energy = payload["energy"]
        assert "kwh_today" in energy
        assert "cost_eur" in energy

        assert energy["kwh_today"] >= 0
        assert energy["cost_eur"] >= 0


# =============================================================================
# Machine State Payload Tests (Level 2 - _state)
# =============================================================================


class TestMachineStatePayloads:
    """Tests for machine state payloads."""

    def test_packml_state_values(self):
        """PackML states should have valid string values."""
        valid_states = [
            "STOPPED", "IDLE", "STARTING", "EXECUTE", "COMPLETING", "COMPLETED",
            "RESETTING", "HOLDING", "HELD", "UNHOLDING", "SUSPENDING", "SUSPENDED",
            "UNSUSPENDING", "ABORTING", "ABORTED", "CLEARING", "STOPPING"
        ]

        for state in PackMLState:
            assert state.value in valid_states


class TestPayloadConsistency:
    """Tests for payload consistency across the system."""

    @pytest.fixture
    def simulator(self):
        config = Config.default()
        mock_mqtt = pytest.importorskip("unittest.mock").MagicMock()
        mock_mqtt.connected = True
        mock_mqtt.connect.return_value = True
        mock_mqtt.publish.return_value = True
        mock_mqtt.base_topic = "umh/v1/test/site"
        return Simulator(config, mqtt_client=mock_mqtt)

    def test_all_cells_have_sensors(self, simulator):
        """Every cell should have at least one sensor generator."""
        for cell_id, cell in simulator._cells.items():
            assert len(cell.sensors) > 0, f"Cell {cell_id} has no sensors"

    def test_all_sensors_generate_valid_payloads(self, simulator):
        """Every sensor should generate a valid payload."""
        for cell_id, cell in simulator._cells.items():
            for sensor_id, generator in cell.sensors.items():
                payload = generator.generate()

                assert "timestamp_ms" in payload, f"Missing timestamp in {cell_id}/{sensor_id}"
                assert "value" in payload, f"Missing value in {cell_id}/{sensor_id}"
                assert isinstance(
                    payload["value"], (int, float)
                ), f"Invalid value type in {cell_id}/{sensor_id}"
