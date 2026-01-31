"""Tests for spec_refinement.core.gap_queue module."""

from __future__ import annotations

from scripts.spec_manager.spec_manager.core.gaps import Severity
from scripts.spec_refinement.core.gap import Gap, GapEvidence, GapType
from scripts.spec_refinement.core.gap_queue import GapQueue


def _make_gap(gap_id: str, status: str = "open") -> Gap:
    evidence = GapEvidence(
        invariant_family="coverage",
        description="Missing section",
        details={
            "source": "file_001::INTRO",
            "derived_artifact_target": "libraries/lib_001/spec.md",
            "severity": "warning",
            "gap_type": "coverage_failure",
        },
    )
    return Gap(
        id=gap_id,
        gap_type=GapType.coverage_failure,
        severity=Severity.WARNING,
        source=["file_001::INTRO"],
        derived_artifact_target="libraries/lib_001/spec.md",
        description="Missing section",
        evidence=[evidence],
        status=status,  # type: ignore[arg-type]
    )


def test_gap_queue_initialization():
    """Verify default GapQueue initialization."""
    queue = GapQueue()
    assert queue.gaps == []
    assert queue.stagnation_count == 0
    assert queue.stagnation_threshold == 3
    assert queue.last_content_hash == ""
    assert queue.is_stagnant is False


def test_gap_queue_stagnation_detection():
    """Detect stagnation across repeated updates."""
    queue = GapQueue(stagnation_threshold=2)
    gap = _make_gap("GAP-1")

    queue.update([gap])
    assert queue.stagnation_count == 0
    assert queue.is_stagnant is False

    queue.update([gap])
    assert queue.stagnation_count == 1
    assert queue.is_stagnant is False

    queue.update([gap])
    assert queue.stagnation_count == 2
    assert queue.is_stagnant is True


def test_gap_queue_duplicate_detection():
    """Ensure duplicate gaps don't affect stagnation hash."""
    queue = GapQueue(stagnation_threshold=2)
    gap = _make_gap("GAP-dup")

    queue.update([gap, gap])
    first_hash = queue.last_content_hash

    queue.update([gap])
    second_hash = queue.last_content_hash

    assert first_hash == second_hash
    assert queue.stagnation_count == 1


def test_gap_queue_coverage_metrics():
    """Verify coverage metrics and convergence ratio."""
    gaps = [_make_gap("GAP-open", "open"), _make_gap("GAP-closed", "integrated")]
    queue = GapQueue(gaps=gaps)
    metrics = queue.get_coverage_metrics()

    assert metrics["total_gaps"] == 2
    assert metrics["open_gaps"] == 1
    assert metrics["closed_gaps"] == 1
    assert metrics["convergence_ratio"] == 0.5


def test_gap_queue_status_transitions():
    """Verify open to integrated transitions update metrics."""
    gap = _make_gap("GAP-transition", "open")
    queue = GapQueue(gaps=[gap])
    metrics = queue.get_coverage_metrics()
    assert metrics["open_gaps"] == 1
    assert metrics["closed_gaps"] == 0

    queue.update([_make_gap("GAP-transition", "integrated")])
    metrics = queue.get_coverage_metrics()
    assert metrics["open_gaps"] == 0
    assert metrics["closed_gaps"] == 1


def test_gap_queue_convergence_ratio_empty():
    """Verify empty queue defaults to full convergence."""
    queue = GapQueue()
    metrics = queue.get_coverage_metrics()
    assert metrics["total_gaps"] == 0
    assert metrics["convergence_ratio"] == 1.0


def test_gap_queue_serialization_round_trip():
    """Verify serialization and deserialization."""
    gaps = [_make_gap("GAP-1"), _make_gap("GAP-2", "integrated")]
    queue = GapQueue(gaps=gaps, stagnation_count=1, stagnation_threshold=4, last_content_hash="abcd")
    data = queue.to_dict()
    restored = GapQueue.from_dict(data)

    assert restored.stagnation_count == queue.stagnation_count
    assert restored.stagnation_threshold == queue.stagnation_threshold
    assert restored.last_content_hash == queue.last_content_hash
    assert restored.is_stagnant == queue.is_stagnant
    assert [gap.id for gap in restored.gaps] == [gap.id for gap in queue.gaps]
