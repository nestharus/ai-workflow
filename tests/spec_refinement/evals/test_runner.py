"""Tests for evaluation runner."""

from __future__ import annotations

from pathlib import Path

import pytest
from spec_manager.refinement.evals.inputs.ground_truth import GroundTruth, PhaseGroundTruth
from spec_manager.refinement.evals.inputs.sequence_spec import SequenceRule, SequenceSpec
from spec_manager.refinement.evals.runner import (
    EVAL_PHASES,
    EvalConfig,
    EvalRunner,
    EvalState,
)

FIXTURES_DIR = Path("scripts/spec_manager/spec_manager/refinement/evals/inputs/fixtures")


class TestEvalConfig:
    """Tests for EvalConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = EvalConfig()

        assert config.spec_ids is None
        assert config.max_iterations_per_phase == 10
        assert config.stagnation_threshold == 3
        assert config.convergence_threshold == 0.95
        assert config.fuzzy_match_threshold == 0.6
        assert config.parallel is False

    def test_custom_config(self) -> None:
        """Test custom configuration."""
        config = EvalConfig(
            spec_ids=["spec1", "spec2"],
            max_iterations_per_phase=20,
            stagnation_threshold=5,
        )

        assert config.spec_ids == ["spec1", "spec2"]
        assert config.max_iterations_per_phase == 20
        assert config.stagnation_threshold == 5

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        config = EvalConfig(
            spec_ids=["spec1"],
            max_iterations_per_phase=15,
        )

        data = config.to_dict()

        assert data["spec_ids"] == ["spec1"]
        assert data["max_iterations_per_phase"] == 15
        assert "checkpoint_dir" in data


class TestEvalState:
    """Tests for EvalState."""

    def test_initial_state(self) -> None:
        """Test initial evaluation state."""
        spec = SequenceSpec(
            spec_id="test",
            title="Test",
            description="Test spec",
            sections={},
            rules=[],
            ground_truth=GroundTruth(),
        )

        state = EvalState(spec=spec)

        assert state.spec == spec
        assert state.current_phase is None
        assert state.iteration == 0
        assert state.convergence_trajectory == []
        assert state.bottlenecks == []
        assert state.errors == []

    def test_run_id_generated(self) -> None:
        """Test that run ID is auto-generated."""
        spec = SequenceSpec(
            spec_id="test",
            title="Test",
            description="Test spec",
            sections={},
            rules=[],
            ground_truth=GroundTruth(),
        )

        state = EvalState(spec=spec)

        assert state.run_id is not None
        assert len(state.run_id) == 8


class TestEvalPhases:
    """Tests for evaluation phase definitions."""

    def test_all_phases_defined(self) -> None:
        """Test that all expected phases are defined."""
        expected = {
            "sectionization",
            "summarization",
            "library_synthesis",
            "evidence_expansion",
            "spec_building",
            "architecture",
            "interfaces",
            "tasks",
        }

        assert set(EVAL_PHASES) == expected

    def test_phase_order(self) -> None:
        """Test that phases are in expected order."""
        assert EVAL_PHASES[0] == "sectionization"
        assert EVAL_PHASES[-1] == "tasks"


class TestEvalRunner:
    """Tests for EvalRunner."""

    def test_runner_initialization(self, tmp_path: Path) -> None:
        """Test runner initialization."""
        config = EvalConfig(
            checkpoint_dir=tmp_path / "checkpoints",
            output_dir=tmp_path / "reports",
        )

        runner = EvalRunner(config, fixtures_dir=tmp_path / "fixtures")

        assert runner.config == config
        assert runner.fixtures_dir == tmp_path / "fixtures"

    def test_run_single_nonexistent_spec(self, tmp_path: Path) -> None:
        """Test running evaluation on nonexistent spec."""
        config = EvalConfig(
            checkpoint_dir=tmp_path / "checkpoints",
            output_dir=tmp_path / "reports",
        )

        runner = EvalRunner(config, fixtures_dir=tmp_path / "fixtures")
        result = runner.run_single("nonexistent")

        assert result.success is False
        assert "not found" in result.errors[0].lower()

    @pytest.mark.skipif(
        not FIXTURES_DIR.exists(),
        reason="Fixtures directory not found",
    )
    def test_run_with_fixture(self, tmp_path: Path) -> None:
        """Test running evaluation with actual fixture."""
        config = EvalConfig(
            spec_ids=["fibonacci_modular"],
            checkpoint_dir=tmp_path / "checkpoints",
            output_dir=tmp_path / "reports",
            max_iterations_per_phase=3,  # Reduce for test speed
        )

        runner = EvalRunner(config, fixtures_dir=FIXTURES_DIR)
        report = runner.run()

        assert report.specs_evaluated >= 1
        assert len(report.results) >= 1

        # Check result structure
        result = report.results[0]
        assert result.spec_id == "fibonacci_modular"
        assert result.phases_total == len(EVAL_PHASES)

    @pytest.mark.skipif(
        not FIXTURES_DIR.exists(),
        reason="Fixtures directory not found",
    )
    def test_run_single_spec(self, tmp_path: Path) -> None:
        """Test running single spec evaluation."""
        config = EvalConfig(
            checkpoint_dir=tmp_path / "checkpoints",
            output_dir=tmp_path / "reports",
            max_iterations_per_phase=2,
        )

        runner = EvalRunner(config, fixtures_dir=FIXTURES_DIR)
        result = runner.run_single("fibonacci_modular")

        assert result.spec_id == "fibonacci_modular"
        assert result.phases_completed > 0

    def test_load_specs_with_filter(self, tmp_path: Path) -> None:
        """Test loading specs with ID filter."""
        # Create a mock fixture
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()

        # Create minimal YAML files
        (fixtures / "spec1.yaml").write_text("""
spec_id: spec1
title: Spec 1
description: Test spec 1
sections: {}
rules: []
ground_truth:
  phases: {}
complexity_score: 1
tags: []
""")

        (fixtures / "spec2.yaml").write_text("""
spec_id: spec2
title: Spec 2
description: Test spec 2
sections: {}
rules: []
ground_truth:
  phases: {}
complexity_score: 1
tags: []
""")

        config = EvalConfig(
            spec_ids=["spec1"],
            checkpoint_dir=tmp_path / "checkpoints",
            output_dir=tmp_path / "reports",
        )

        runner = EvalRunner(config, fixtures_dir=fixtures)
        specs = runner._load_specs()

        assert len(specs) == 1
        assert specs[0].spec_id == "spec1"


class TestEvalRunnerSimulation:
    """Tests for evaluation simulation behavior."""

    @pytest.mark.skipif(
        not FIXTURES_DIR.exists(),
        reason="Fixtures directory not found",
    )
    def test_convergence_trajectory_tracked(self, tmp_path: Path) -> None:
        """Test that convergence trajectory is tracked."""
        config = EvalConfig(
            spec_ids=["fibonacci_modular"],
            checkpoint_dir=tmp_path / "checkpoints",
            output_dir=tmp_path / "reports",
            max_iterations_per_phase=5,
        )

        runner = EvalRunner(config, fixtures_dir=FIXTURES_DIR)
        result = runner.run_single("fibonacci_modular")

        # Should have convergence analysis
        assert result.convergence_analysis is not None
        assert result.convergence_analysis.final_ratio >= 0.0

    @pytest.mark.skipif(
        not FIXTURES_DIR.exists(),
        reason="Fixtures directory not found",
    )
    def test_phase_metrics_captured(self, tmp_path: Path) -> None:
        """Test that phase metrics are captured."""
        config = EvalConfig(
            spec_ids=["fibonacci_modular"],
            checkpoint_dir=tmp_path / "checkpoints",
            output_dir=tmp_path / "reports",
            max_iterations_per_phase=3,
        )

        runner = EvalRunner(config, fixtures_dir=FIXTURES_DIR)
        result = runner.run_single("fibonacci_modular")

        # Should have metrics for each completed phase
        assert len(result.phase_results) > 0

        for phase_name, metrics in result.phase_results.items():
            assert metrics.phase_name == phase_name
            assert metrics.iterations >= 1
            assert metrics.duration_ms >= 0
