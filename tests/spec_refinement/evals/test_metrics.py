"""Tests for evaluation metrics computation."""

from __future__ import annotations

import pytest

from spec_manager.refinement.evals.metrics import (
    ConvergenceAnalysis,
    DetailCaptureMetrics,
    DetailScore,
    PhaseMetrics,
    analyze_convergence,
    score_detail_capture,
)


class TestDetailScore:
    """Tests for DetailScore dataclass."""

    def test_create_perfect_score(self) -> None:
        """Test creating a perfect score."""
        # DetailScore requires recall and precision to be provided
        score = DetailScore(
            expected_count=10,
            actual_count=10,
            matched_count=10,
            recall=1.0,
            precision=1.0,
        )

        assert score.recall == 1.0
        assert score.precision == 1.0
        assert score.f1 == 1.0

    def test_create_partial_score(self) -> None:
        """Test creating a partial score."""
        score = DetailScore(
            expected_count=10,
            actual_count=8,
            matched_count=6,
            recall=0.6,  # 6/10
            precision=0.75,  # 6/8
        )

        assert score.recall == 0.6
        assert score.precision == 0.75
        assert 0.66 < score.f1 < 0.67  # 2*0.6*0.75/(0.6+0.75)

    def test_zero_expected(self) -> None:
        """Test score when nothing expected."""
        score = DetailScore(
            expected_count=0,
            actual_count=5,
            matched_count=0,
            recall=1.0,  # Nothing to miss
            precision=0.0,  # All spurious
        )

        assert score.recall == 1.0
        assert score.precision == 0.0

    def test_zero_actual(self) -> None:
        """Test score when nothing actual."""
        score = DetailScore(
            expected_count=5,
            actual_count=0,
            matched_count=0,
            recall=0.0,  # Missed everything
            precision=1.0,  # No spurious
        )

        assert score.recall == 0.0
        assert score.precision == 1.0

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        score = DetailScore(
            expected_count=10,
            actual_count=8,
            matched_count=6,
            recall=0.6,
            precision=0.75,
        )

        data = score.to_dict()

        assert data["expected_count"] == 10
        assert data["actual_count"] == 8
        assert data["matched_count"] == 6
        assert "recall" in data
        assert "precision" in data
        assert "f1" in data


class TestScoreDetailCapture:
    """Tests for score_detail_capture function."""

    def test_exact_matches(self) -> None:
        """Test scoring with exact matches."""
        expected = ["item1", "item2", "item3"]
        actual = ["item1", "item2", "item3"]

        score = score_detail_capture(expected, actual)

        assert score.matched_count == 3
        assert score.recall == 1.0
        assert score.precision == 1.0

    def test_partial_matches(self) -> None:
        """Test scoring with partial matches."""
        expected = ["item1", "item2", "item3"]
        actual = ["item1", "item2", "other"]

        # "item1" and "item2" match exactly (ratio=1.0 > 0.8)
        # "item3" vs "other" has low similarity
        score = score_detail_capture(expected, actual, fuzzy_threshold=0.8)

        assert score.matched_count == 2
        assert score.recall == pytest.approx(2 / 3)
        assert score.precision == pytest.approx(2 / 3)

    def test_fuzzy_matching(self) -> None:
        """Test fuzzy string matching."""
        expected = ["compute fibonacci sequence"]
        actual = ["compute the fibonacci sequences"]

        score = score_detail_capture(expected, actual, fuzzy_threshold=0.7)

        # Should match due to high similarity
        assert score.matched_count == 1

    def test_fuzzy_threshold_respected(self) -> None:
        """Test that fuzzy threshold is respected."""
        expected = ["compute fibonacci"]
        actual = ["calculate primes"]

        # High threshold - shouldn't match
        score_high = score_detail_capture(expected, actual, fuzzy_threshold=0.9)
        assert score_high.matched_count == 0

    def test_empty_expected(self) -> None:
        """Test with empty expected list."""
        score = score_detail_capture([], ["item1", "item2"])

        assert score.expected_count == 0
        assert score.actual_count == 2
        # When expected is empty, recall = 0/max(1,0) = 0.0 in the implementation
        assert score.recall == 0.0

    def test_empty_actual(self) -> None:
        """Test with empty actual list."""
        score = score_detail_capture(["item1", "item2"], [])

        assert score.expected_count == 2
        assert score.actual_count == 0
        assert score.recall == 0.0

    def test_case_insensitive_by_default(self) -> None:
        """Test that matching is case-insensitive."""
        expected = ["Item One"]
        actual = ["item one"]

        score = score_detail_capture(expected, actual)

        assert score.matched_count == 1


class TestAnalyzeConvergence:
    """Tests for convergence analysis."""

    def test_perfect_convergence(self) -> None:
        """Test analysis of perfect convergence."""
        trajectory = [0.5, 0.7, 0.85, 0.95, 1.0]

        analysis = analyze_convergence(trajectory)

        assert analysis.converged is True
        assert analysis.iterations_to_converge == 4
        assert analysis.final_ratio == 1.0

    def test_non_convergence(self) -> None:
        """Test analysis of non-convergence."""
        trajectory = [0.3, 0.4, 0.45, 0.5, 0.55]

        analysis = analyze_convergence(trajectory, convergence_threshold=0.95)

        assert analysis.converged is False
        assert analysis.final_ratio == 0.55

    def test_stagnation_detection(self) -> None:
        """Test detection of stagnation plateau."""
        trajectory = [0.5, 0.6, 0.7, 0.7, 0.7, 0.7]

        analysis = analyze_convergence(trajectory, stagnation_delta=0.01, stagnation_window=3)

        assert analysis.plateau_start is not None
        # Plateau starts when 3 consecutive stagnant values are detected

    def test_bottleneck_identification(self) -> None:
        """Test identification of bottleneck."""
        trajectory = [0.5, 0.6, 0.65, 0.65, 0.65, 0.65]

        analysis = analyze_convergence(trajectory)

        assert analysis.bottleneck is not None
        assert "iteration" in analysis.bottleneck

    def test_empty_trajectory(self) -> None:
        """Test analysis of empty trajectory."""
        analysis = analyze_convergence([])

        # Empty trajectory is considered converged with 1.0 ratio
        assert analysis.converged is True
        assert analysis.final_ratio == 1.0

    def test_single_point_trajectory(self) -> None:
        """Test analysis of single-point trajectory."""
        analysis = analyze_convergence([0.5])

        assert analysis.final_ratio == 0.5

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        analysis = ConvergenceAnalysis(
            converged=True,
            iterations_to_converge=5,
            final_ratio=0.98,
            plateau_start=None,
            bottleneck=None,
        )

        data = analysis.to_dict()

        assert data["converged"] is True
        assert data["iterations_to_converge"] == 5
        assert data["final_ratio"] == 0.98


class TestDetailCaptureMetrics:
    """Tests for aggregate detail capture metrics."""

    def test_initial_state(self) -> None:
        """Test initial aggregate state."""
        metrics = DetailCaptureMetrics()

        assert metrics.total_details_expected == 0
        assert metrics.total_details_captured == 0
        assert metrics.total_details_spurious == 0

    def test_add_phase_metrics(self) -> None:
        """Test adding phase metrics."""
        metrics = DetailCaptureMetrics()

        phase = PhaseMetrics(
            phase_name="test",
            detail_score=DetailScore(
                expected_count=10,
                actual_count=12,
                matched_count=8,
                recall=0.8,
                precision=8/12,
            ),
            iterations=3,
            converged=True,
            duration_ms=100.0,
        )

        metrics.add_phase_metrics(phase)

        assert metrics.total_details_expected == 10
        assert metrics.total_details_captured == 8
        assert metrics.total_details_spurious == 4  # 12 - 8

    def test_aggregate_multiple_phases(self) -> None:
        """Test aggregating multiple phases."""
        metrics = DetailCaptureMetrics()

        for i in range(3):
            phase = PhaseMetrics(
                phase_name=f"phase_{i}",
                detail_score=DetailScore(
                    expected_count=10,
                    actual_count=10,
                    matched_count=8,
                    recall=0.8,
                    precision=0.8,
                ),
                iterations=1,
                converged=True,
                duration_ms=50.0,
            )
            metrics.add_phase_metrics(phase)

        assert metrics.total_details_expected == 30
        assert metrics.total_details_captured == 24
        assert metrics.recall == pytest.approx(24 / 30)


class TestPhaseMetrics:
    """Tests for phase-level metrics."""

    def test_create_metrics(self) -> None:
        """Test creating phase metrics."""
        metrics = PhaseMetrics(
            phase_name="sectionization",
            detail_score=DetailScore(
                expected_count=5,
                actual_count=5,
                matched_count=5,
                recall=1.0,
                precision=1.0,
            ),
            iterations=3,
            converged=True,
            duration_ms=150.5,
            gaps_open=0,
            gaps_closed=5,
        )

        assert metrics.phase_name == "sectionization"
        assert metrics.iterations == 3
        assert metrics.converged is True

    def test_to_dict(self) -> None:
        """Test serialization."""
        metrics = PhaseMetrics(
            phase_name="test",
            detail_score=DetailScore(
                expected_count=10,
                actual_count=10,
                matched_count=10,
                recall=1.0,
                precision=1.0,
            ),
            iterations=5,
            converged=True,
            duration_ms=200.0,
        )

        data = metrics.to_dict()

        assert data["phase_name"] == "test"
        assert data["iterations"] == 5
        assert data["converged"] is True
        assert "detail_score" in data

    def test_from_dict(self) -> None:
        """Test deserialization."""
        data = {
            "phase_name": "test",
            "detail_score": {
                "expected_count": 10,
                "actual_count": 10,
                "matched_count": 8,
            },
            "iterations": 3,
            "converged": False,
            "duration_ms": 100.0,
            "gaps_open": 2,
            "gaps_closed": 8,
        }

        metrics = PhaseMetrics.from_dict(data)

        assert metrics.phase_name == "test"
        assert metrics.iterations == 3
        assert metrics.detail_score.matched_count == 8
