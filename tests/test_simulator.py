"""Tests for the main Simulator class."""

import pytest
from unittest.mock import MagicMock, patch

from metalfab_uns_sim.complexity import ComplexityLevel
from metalfab_uns_sim.config import Config
from metalfab_uns_sim.generators import PackMLState, JobStatus
from metalfab_uns_sim.simulator import Simulator, CellState


class TestSimulator:
    """Tests for Simulator class."""

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

    def test_init_creates_cells(self, simulator):
        # Default config has cells from multiple areas
        assert len(simulator._cells) > 0
        assert "laser_01" in simulator._cells
        assert "press_brake_01" in simulator._cells

    def test_init_creates_sensor_generators(self, simulator):
        laser = simulator._cells["laser_01"]
        assert "laser_power_pct" in laser.sensors
        assert "power_kw" in laser.sensors

    def test_level_property(self, simulator):
        assert simulator.level == ComplexityLevel.LEVEL_2_STATEFUL

    def test_set_level(self, simulator, mock_mqtt):
        simulator.level = ComplexityLevel.LEVEL_3_ERP_MES

        assert simulator._level == ComplexityLevel.LEVEL_3_ERP_MES
        mock_mqtt.set_level.assert_called_with(ComplexityLevel.LEVEL_3_ERP_MES)

    def test_generate_initial_jobs(self, simulator):
        simulator._generate_initial_jobs()

        assert len(simulator._jobs) == 5

    def test_generate_new_job(self, simulator):
        initial_count = len(simulator._jobs)
        simulator._generate_new_job()

        assert len(simulator._jobs) == initial_count + 1

    def test_job_limit(self, simulator):
        # Generate jobs up to the limit
        for _ in range(25):
            simulator._generate_new_job()

        # Should not exceed 20
        assert len(simulator._jobs) <= 20


class TestCellState:
    """Tests for CellState."""

    def test_initial_state_is_idle(self):
        from metalfab_uns_sim.config import CellConfig

        cell_config = CellConfig(
            id="test_cell",
            name="Test Cell",
            cell_type="laser_cutter",
        )
        cell = CellState(config=cell_config)

        assert cell.state == PackMLState.IDLE

    def test_cycle_count_starts_at_zero(self):
        from metalfab_uns_sim.config import CellConfig

        cell_config = CellConfig(
            id="test_cell",
            name="Test Cell",
            cell_type="press_brake",
        )
        cell = CellState(config=cell_config)

        assert cell.cycle_count == 0
        assert cell.parts_produced == 0
        assert cell.parts_scrap == 0


class TestSimulatorStateTransitions:
    """Tests for state machine transitions."""

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
        sim = Simulator(config, mqtt_client=mock_mqtt)
        sim._generate_initial_jobs()
        return sim

    def test_idle_to_starting_with_job(self, simulator):
        cell = simulator._cells["laser_01"]
        cell.state = PackMLState.IDLE
        cell.current_job = None

        # Queue a job for this cell
        job = simulator._job_generator.generate_job()
        job.routing = ["laser_01"]
        job.status = JobStatus.QUEUED
        simulator._jobs[job.job_id] = job

        simulator._update_machine_states()

        # Cell should transition to STARTING
        assert cell.state == PackMLState.STARTING
        assert cell.current_job is not None

    def test_get_sub_state_for_type(self, simulator):
        from metalfab_uns_sim.generators import MachineSubState

        assert simulator._get_sub_state_for_type("laser_cutter") == MachineSubState.CUTTING
        assert simulator._get_sub_state_for_type("press_brake") == MachineSubState.BENDING
        assert simulator._get_sub_state_for_type("robot_weld") == MachineSubState.WELDING
        assert simulator._get_sub_state_for_type("paint_booth") == MachineSubState.PAINTING
        assert simulator._get_sub_state_for_type("unknown") == MachineSubState.NONE
