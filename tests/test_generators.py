"""Tests for data generators."""

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


class TestSensorGenerator:
    """Tests for SensorGenerator."""

    def test_generate_returns_value_in_range(self):
        gen = SensorGenerator(
            sensor_id="test",
            base_value=50.0,
            min_value=0.0,
            max_value=100.0,
            noise_stddev=5.0,
        )

        for _ in range(100):
            reading = gen.generate()
            assert 0.0 <= reading["value"] <= 100.0
            assert "timestamp_ms" in reading

    def test_generate_idle_state_returns_min_value(self):
        gen = SensorGenerator(
            sensor_id="test",
            base_value=50.0,
            min_value=0.0,
            max_value=100.0,
            noise_stddev=0.0,  # No noise for deterministic test
        )

        reading = gen.generate(state=PackMLState.IDLE)
        assert reading["value"] == 0.0

    def test_generate_extended_includes_metadata(self):
        gen = SensorGenerator(
            sensor_id="power_kw",
            base_value=10.0,
            unit="kW",
        )

        reading = gen.generate_extended()
        assert reading["sensor_id"] == "power_kw"
        assert reading["unit"] == "kW"
        assert reading["quality"] == "GOOD"


class TestCreateSensorGenerators:
    """Tests for sensor generator factory."""

    def test_laser_cutter_has_expected_sensors(self):
        sensors = create_sensor_generators("laser_cutter")

        assert "laser_power_pct" in sensors
        assert "cutting_speed_mmpm" in sensors
        assert "power_kw" in sensors

    def test_press_brake_has_expected_sensors(self):
        sensors = create_sensor_generators("press_brake")

        assert "tonnage_t" in sensors
        assert "bend_angle_deg" in sensors

    def test_robot_weld_has_expected_sensors(self):
        sensors = create_sensor_generators("robot_weld")

        assert "weld_current_a" in sensors
        assert "weld_voltage_v" in sensors
        assert "wire_feed_mpm" in sensors

    def test_unknown_type_still_has_power_sensor(self):
        sensors = create_sensor_generators("unknown_type")

        assert "power_kw" in sensors


class TestJob:
    """Tests for Job dataclass."""

    def test_to_state_dict(self):
        job = Job(
            job_id="JOB_001",
            job_number="WO-001",
            job_name="Test Job",
            customer="Test Customer",
            qty_target=100,
            qty_complete=50,
            routing=["laser_01", "press_brake_01"],
        )

        state = job.to_state_dict()

        assert state["job_id"] == "JOB_001"
        assert state["progress_pct"] == 50.0
        assert state["routing"] == ["laser_01", "press_brake_01"]

    def test_to_erp_dict(self):
        job = Job(
            job_id="JOB_002",
            job_number="WO-002",
            job_name="Test Job 2",
            customer="Test Customer",
            status=JobStatus.IN_PROGRESS,
            estimated_hours=10.0,
            actual_hours=8.0,
            margin_pct=35.0,
        )

        erp = job.to_erp_dict()

        assert erp["est_vs_actual_hours"] == -2.0
        assert erp["margin_pct"] == 35.0
        assert erp["status"] == "IN_PROGRESS"


class TestJobGenerator:
    """Tests for JobGenerator."""

    def test_generate_job_creates_valid_job(self):
        templates = [
            {"name": "Test Part", "routing": ["laser_01"], "qty_range": (10, 20)}
        ]
        customers = ["Customer A"]

        gen = JobGenerator(templates, customers)
        job = gen.generate_job()

        assert job.job_id.startswith("JOB_")
        assert job.customer == "Customer A"
        assert 10 <= job.qty_target <= 20

    def test_generate_job_increments_counter(self):
        gen = JobGenerator([], [])

        job1 = gen.generate_job()
        job2 = gen.generate_job()

        # Jobs should have sequential IDs
        id1 = int(job1.job_id.split("_")[1])
        id2 = int(job2.job_id.split("_")[1])
        assert id2 == id1 + 1


class TestERPMESGenerator:
    """Tests for ERPMESGenerator."""

    def test_generate_energy_metrics(self):
        gen = ERPMESGenerator()
        cells = [{"power_kw": 10}, {"power_kw": 20}]

        metrics = gen.generate_energy_metrics(cells)

        assert "kwh_today" in metrics
        assert "total_cost_today_eur" in metrics
        assert metrics["cost_per_kwh_eur"] == 0.15

    def test_generate_quality_metrics(self):
        gen = ERPMESGenerator()

        metrics = gen.generate_quality_metrics("laser_01")

        assert metrics["cell_id"] == "laser_01"
        assert 90.0 <= metrics["quality_pct"] <= 100.0
        assert 0.0 <= metrics["defect_rate_pct"] <= 10.0
        assert "first_pass_yield_pct" in metrics

    def test_generate_oee_metrics(self):
        gen = ERPMESGenerator()

        metrics = gen.generate_oee_metrics("press_brake_01")

        assert metrics["cell_id"] == "press_brake_01"
        assert 0 <= metrics["oee_pct"] <= 100
        assert metrics["period"] == "SHIFT"

    def test_generate_delivery_metrics(self):
        gen = ERPMESGenerator()
        jobs = [
            Job("J1", "WO1", "Job 1", "C1"),
            Job("J2", "WO2", "Job 2", "C2"),
        ]

        metrics = gen.generate_delivery_metrics(jobs)

        assert "on_time_pct" in metrics
        assert "late_orders" in metrics

    def test_generate_machine_utilization(self):
        gen = ERPMESGenerator()
        states = {
            "laser_01": PackMLState.EXECUTE,
            "laser_02": PackMLState.IDLE,
            "press_01": PackMLState.EXECUTE,
        }

        metrics = gen.generate_machine_utilization(states)

        assert metrics["machines_running"] == 2
        assert metrics["machines_total"] == 3
        assert metrics["fleet_utilization_pct"] == pytest.approx(66.7, rel=0.1)
