"""Tests for per-phase evaluators."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spec_manager.refinement.evals.inputs.ground_truth import PhaseGroundTruth
from spec_manager.refinement.evals.loop_detector import LoopDetector
from spec_manager.refinement.evals.phase_evals import (
    eval_library_synthesis,
    eval_sectionization,
    eval_spec_building,
    eval_summarization,
    eval_tasks,
)
from spec_manager.refinement.evals.phase_evals.sectionization import (
    SectionizationResult,
    compute_section_state_hash,
    extract_sectionization_outputs,
)
from spec_manager.refinement.evals.phase_evals.synthesis import (
    SynthesisResult,
    compute_synthesis_state_hash,
)
from spec_manager.refinement.evals.phase_evals.spec_building import (
    SpecBuildingResult,
)
from spec_manager.refinement.evals.phase_evals.tasks import (
    TasksResult,
)


class TestSectionizationResult:
    """Tests for SectionizationResult dataclass."""

    def test_create_result(self) -> None:
        """Test creating sectionization result."""
        result = SectionizationResult(
            sections_detected=["Introduction", "Methods"],
            atoms_emitted=10,
            terms_extracted=5,
            file_count=2,
        )

        assert len(result.sections_detected) == 2
        assert result.atoms_emitted == 10
        assert result.terms_extracted == 5

    def test_empty_result(self) -> None:
        """Test creating empty result."""
        result = SectionizationResult(sections_detected=[])

        assert result.sections_detected == []
        assert result.atoms_emitted == 0


class TestSynthesisResult:
    """Tests for SynthesisResult dataclass."""

    def test_create_result(self) -> None:
        """Test creating synthesis result."""
        result = SynthesisResult(
            libraries_synthesized=["lib_a", "lib_b"],
            functions_defined=15,
            types_defined=5,
        )

        assert len(result.libraries_synthesized) == 2
        assert result.functions_defined == 15


class TestSpecBuildingResult:
    """Tests for SpecBuildingResult dataclass."""

    def test_create_result(self) -> None:
        """Test creating spec building result."""
        result = SpecBuildingResult(
            requirements_captured=["REQ-001", "REQ-002"],
            citations_found=["REF-1"],
            decisions_made=["Use algorithm X"],
        )

        assert len(result.requirements_captured) == 2
        assert len(result.citations_found) == 1

    def test_defaults(self) -> None:
        """Test default values."""
        result = SpecBuildingResult(requirements_captured=[])

        assert result.citations_found == []
        assert result.decisions_made == []
        assert result.constraints_identified == []


class TestTasksResult:
    """Tests for TasksResult dataclass."""

    def test_create_result(self) -> None:
        """Test creating tasks result."""
        result = TasksResult(
            tasks_generated=["Task 1", "Task 2"],
            task_ids=["T-001", "T-002"],
            dependencies_mapped=3,
        )

        assert len(result.tasks_generated) == 2
        assert result.dependencies_mapped == 3


class TestStateHashComputation:
    """Tests for state hash computation."""

    def test_section_hash_deterministic(self) -> None:
        """Test that section hash is deterministic."""
        result = SectionizationResult(
            sections_detected=["A", "B", "C"],
        )

        hash1 = compute_section_state_hash(result)
        hash2 = compute_section_state_hash(result)

        assert hash1 == hash2

    def test_section_hash_different_for_different_results(self) -> None:
        """Test that different results produce different hashes."""
        result1 = SectionizationResult(sections_detected=["A", "B"])
        result2 = SectionizationResult(sections_detected=["A", "C"])

        hash1 = compute_section_state_hash(result1)
        hash2 = compute_section_state_hash(result2)

        assert hash1 != hash2

    def test_synthesis_hash_deterministic(self) -> None:
        """Test that synthesis hash is deterministic."""
        result = SynthesisResult(
            libraries_synthesized=["lib_a"],
            functions_defined=5,
        )

        hash1 = compute_synthesis_state_hash(result)
        hash2 = compute_synthesis_state_hash(result)

        assert hash1 == hash2


class TestEvalSectionization:
    """Tests for sectionization evaluator."""

    def test_eval_with_mock_manager(self) -> None:
        """Test evaluation with mocked workspace manager."""
        # Create mock manager
        manager = MagicMock()
        manager.structure.manifest_sections_dir = Path("/fake/sections")
        manager.structure.manifest_atoms_dir = Path("/fake/atoms")
        manager.structure.manifest_terms_dir = Path("/fake/terms")

        # Mock that directories don't exist (empty extraction)
        with patch.object(Path, "exists", return_value=False):
            ground_truth = PhaseGroundTruth(
                expected_sections=["Section A", "Section B"],
            )
            loop_detector = LoopDetector()

            metrics = eval_sectionization(
                manager,
                ground_truth,
                loop_detector,
                max_iterations=2,
            )

            assert metrics.phase_name == "sectionization"
            assert metrics.iterations >= 1
            assert metrics.duration_ms > 0


class TestEvalSummarization:
    """Tests for summarization evaluator."""

    def test_eval_with_mock_manager(self) -> None:
        """Test evaluation with mocked workspace manager."""
        manager = MagicMock()
        manager.structure.manifest_dir = Path("/fake/manifest")

        with patch.object(Path, "exists", return_value=False):
            ground_truth = PhaseGroundTruth(
                expected_elements=["Summary A"],
                expected_requirements=["Key point 1"],
            )
            loop_detector = LoopDetector()

            metrics = eval_summarization(
                manager,
                ground_truth,
                loop_detector,
                max_iterations=2,
            )

            assert metrics.phase_name == "summarization"


class TestEvalLibrarySynthesis:
    """Tests for library synthesis evaluator."""

    def test_eval_with_mock_manager(self) -> None:
        """Test evaluation with mocked workspace manager."""
        manager = MagicMock()
        manager.structure.manifest_dir = Path("/fake/manifest")

        with patch.object(Path, "exists", return_value=False):
            ground_truth = PhaseGroundTruth(
                expected_libraries=["fibonacci_lib", "math_utils"],
            )
            loop_detector = LoopDetector()

            metrics = eval_library_synthesis(
                manager,
                ground_truth,
                loop_detector,
                max_iterations=2,
            )

            assert metrics.phase_name == "library_synthesis"


class TestEvalSpecBuilding:
    """Tests for spec building evaluator."""

    def test_eval_with_mock_manager(self) -> None:
        """Test evaluation with mocked workspace manager."""
        manager = MagicMock()
        manager.structure.manifest_dir = Path("/fake/manifest")

        with patch.object(Path, "exists", return_value=False):
            ground_truth = PhaseGroundTruth(
                expected_requirements=["REQ-001"],
                expected_citations=["RFC-123"],
                expected_decisions=["Use approach A"],
            )
            loop_detector = LoopDetector()

            metrics = eval_spec_building(
                manager,
                ground_truth,
                loop_detector,
                max_iterations=2,
            )

            assert metrics.phase_name == "spec_building"


class TestEvalTasks:
    """Tests for tasks evaluator."""

    def test_eval_with_mock_manager(self) -> None:
        """Test evaluation with mocked workspace manager."""
        manager = MagicMock()
        manager.structure.manifest_dir = Path("/fake/manifest")

        with patch.object(Path, "exists", return_value=False):
            ground_truth = PhaseGroundTruth(
                expected_tasks=["Implement function X", "Write tests for Y"],
            )
            loop_detector = LoopDetector()

            metrics = eval_tasks(
                manager,
                ground_truth,
                loop_detector,
                max_iterations=2,
            )

            assert metrics.phase_name == "tasks"


class TestPhaseEvaluatorConvergence:
    """Tests for convergence behavior in phase evaluators."""

    def test_early_convergence(self) -> None:
        """Test that evaluator stops early on convergence."""
        manager = MagicMock()
        manager.structure.manifest_dir = Path("/fake/manifest")

        # Mock to simulate perfect extraction
        with patch.object(Path, "exists", return_value=False):
            ground_truth = PhaseGroundTruth(
                expected_tasks=[],  # Empty expectations = instant convergence
            )
            loop_detector = LoopDetector()

            metrics = eval_tasks(
                manager,
                ground_truth,
                loop_detector,
                max_iterations=10,
            )

            # Should converge quickly with empty expectations
            assert metrics.converged is True


class TestPhaseEvaluatorLoopDetection:
    """Tests for loop detection in phase evaluators."""

    def test_stagnation_detected(self) -> None:
        """Test that stagnation is detected and stops evaluation."""
        manager = MagicMock()
        manager.structure.manifest_dir = Path("/fake/manifest")

        with patch.object(Path, "exists", return_value=False):
            ground_truth = PhaseGroundTruth(
                expected_tasks=["Task that won't be found"],
            )
            loop_detector = LoopDetector(stagnation_threshold=2)

            metrics = eval_tasks(
                manager,
                ground_truth,
                loop_detector,
                max_iterations=10,
            )

            # Should stop due to stagnation (same empty result each time)
            assert metrics.iterations <= 3
