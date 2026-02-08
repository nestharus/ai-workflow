"""Tests for WorkspaceManager gap persistence and audit tracking."""

from __future__ import annotations

from pathlib import Path

import pytest
from spec_manager.core.gap import Gap, GapEvidence, GapType
from spec_manager.core.gaps import Severity
from spec_manager.refinement.workspace import WorkspaceManager
from spec_manager.refinement.workspace.state import Phase


def _make_gap(gap_id: str, artifact: str) -> Gap:
    evidence = GapEvidence(
        invariant_family="coverage",
        description="Missing requirement",
        details={
            "derived_artifact_target": artifact,
            "source": ["F0001::INTRO"],
            "gap_type": "coverage_failure",
            "severity": "warning",
        },
        confidence=0.9,
        location="spec.md:10",
        detector="coverage_detector",
    )
    return Gap(
        id=gap_id,
        gap_type=GapType.coverage_failure,
        severity=Severity.WARNING,
        source=["F0001::INTRO"],
        derived_artifact_target=artifact,
        description="Missing requirement",
        evidence=[evidence],
        status="open",
        resolution_pointer=None,
        created_at="2024-01-01T00:00:00",
        resolved_at=None,
        resolution_notes=None,
    )


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WorkspaceManager:
    """Create a workspace manager rooted in a temp directory."""
    monkeypatch.chdir(tmp_path)
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "spec.md").write_text("# Spec\n\n## Intro\nContent\n", encoding="utf-8")
    workspace = WorkspaceManager(run_id="run1", input_folder=input_dir)
    workspace.initialize()
    return workspace


def test_write_read_library_gaps(manager: WorkspaceManager) -> None:
    """Verify library gaps persist round-trip."""
    gap = _make_gap("GAP-lib", "libs/lib-a/spec.md")
    manager.write_library_gaps("lib-a", [gap], update_queue=True)

    loaded = manager.read_library_gaps("lib-a")
    assert len(loaded) == 1
    assert loaded[0].id == gap.id
    assert loaded[0].derived_artifact_target == gap.derived_artifact_target


def test_write_read_task_gaps(manager: WorkspaceManager) -> None:
    """Verify task gaps persist round-trip."""
    gap = _make_gap("GAP-task", "tasks/task-a/spec.md")
    manager.write_task_gaps("task-a", [gap])

    loaded = manager.read_task_gaps("task-a")
    assert len(loaded) == 1
    assert loaded[0].id == gap.id


def test_get_all_gaps(manager: WorkspaceManager) -> None:
    """Verify aggregation across libraries and tasks."""
    manager.write_library_gaps(
        "lib-a",
        [_make_gap("GAP-lib", "libs/lib-a/spec.md")],
        update_queue=True,
    )
    manager.write_task_gaps("task-a", [_make_gap("GAP-task", "tasks/task-a/spec.md")])

    all_gaps = manager.get_all_gaps("run1")
    assert "lib-a" in all_gaps
    assert "task-a" in all_gaps
    assert all_gaps["lib-a"][0].id == "GAP-lib"


def test_record_gap_audit(manager: WorkspaceManager) -> None:
    """Verify audit tracking updates state."""
    gap = _make_gap("GAP-audit", "libs/lib-a/spec.md")
    manager.record_gap_audit(Phase.SPEC_BUILDING, [gap], converged=False)

    result = manager.state.phases[Phase.SPEC_BUILDING.value]
    assert result.gap_audit_iterations == 1
    assert result.gap_audit_converged is False
    assert result.open_gaps_count == 1


def test_gap_audit_convergence(manager: WorkspaceManager) -> None:
    """Verify convergence status tracking."""
    gap = _make_gap("GAP-conv", "libs/lib-a/spec.md")
    manager.record_gap_audit(Phase.AUDIT, [gap], converged=True)

    status = manager.get_gap_audit_status(Phase.AUDIT)
    assert status["iterations"] == 1
    assert status["converged"] is True
    assert status["open_gaps_count"] == 1
