"""Tests for spec_manager.planner.architecture.artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from spec_manager.planner.architecture.artifacts import (
    load_committed_decisions,
    persist_decision_artifacts,
)
from spec_manager.planner.architecture.types import (
    ArchitectureCandidate,
    CandidateAssessment,
    DecisionOutcome,
)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def sample_candidates() -> list[ArchitectureCandidate]:
    return [
        ArchitectureCandidate(
            candidate_id="CAND-001",
            decision_id="DEC-001",
            scope="intra:LIB",
            proposal={"approach": "cache", "details": "LRU"},
        ),
        ArchitectureCandidate(
            candidate_id="CAND-002",
            decision_id="DEC-001",
            scope="intra:LIB",
            proposal={"approach": "redis", "details": "Distributed"},
        ),
    ]


@pytest.fixture()
def sample_assessments() -> list[CandidateAssessment]:
    return [
        CandidateAssessment(candidate_id="CAND-001", recommendation="accept", risk_score=0.1),
        CandidateAssessment(candidate_id="CAND-002", recommendation="reject", risk_score=0.8),
    ]


@pytest.fixture()
def committed_outcome() -> DecisionOutcome:
    return DecisionOutcome(
        decision_id="DEC-001",
        committed=True,
        selected_candidate_id="CAND-001",
        wiring_intentions=[{"source": "DEC-001", "approach": "cache"}],
        new_constraints=["cache-ttl"],
    )


@pytest.fixture()
def blocked_outcome() -> DecisionOutcome:
    return DecisionOutcome(
        decision_id="DEC-002",
        committed=False,
        decision_requirements=["Human review needed"],
    )


# ---------------------------------------------------------------------------
# Persist
# ---------------------------------------------------------------------------


class TestPersist:
    def test_creates_directory_structure(
        self, workspace: Path, sample_candidates, sample_assessments, committed_outcome
    ):
        result_dir = persist_decision_artifacts(
            workspace,
            "run-1",
            "DEC-001",
            sample_candidates,
            sample_assessments,
            committed_outcome,
        )
        assert result_dir.is_dir()
        assert (result_dir / "candidates.json").exists()
        assert (result_dir / "assessments.json").exists()
        assert (result_dir / "outcome.json").exists()

    def test_path_structure(
        self, workspace: Path, sample_candidates, sample_assessments, committed_outcome
    ):
        result_dir = persist_decision_artifacts(
            workspace,
            "run-1",
            "DEC-001",
            sample_candidates,
            sample_assessments,
            committed_outcome,
        )
        expected = (
            workspace / "reports" / "pdd" / "run-1" / "architecture" / "decisions" / "DEC-001"
        )
        assert result_dir == expected

    def test_candidates_json_content(
        self, workspace: Path, sample_candidates, sample_assessments, committed_outcome
    ):
        result_dir = persist_decision_artifacts(
            workspace,
            "run-1",
            "DEC-001",
            sample_candidates,
            sample_assessments,
            committed_outcome,
        )
        data = json.loads((result_dir / "candidates.json").read_text())
        assert len(data) == 2
        assert data[0]["candidate_id"] == "CAND-001"

    def test_outcome_json_content(
        self, workspace: Path, sample_candidates, sample_assessments, committed_outcome
    ):
        result_dir = persist_decision_artifacts(
            workspace,
            "run-1",
            "DEC-001",
            sample_candidates,
            sample_assessments,
            committed_outcome,
        )
        data = json.loads((result_dir / "outcome.json").read_text())
        assert data["committed"] is True
        assert data["selected_candidate_id"] == "CAND-001"

    def test_persist_twice_overwrites(
        self, workspace: Path, sample_candidates, sample_assessments, committed_outcome
    ):
        persist_decision_artifacts(
            workspace,
            "run-1",
            "DEC-001",
            sample_candidates,
            sample_assessments,
            committed_outcome,
        )
        # Persist again with different outcome
        new_outcome = DecisionOutcome(decision_id="DEC-001", committed=False)
        result_dir = persist_decision_artifacts(
            workspace,
            "run-1",
            "DEC-001",
            sample_candidates,
            sample_assessments,
            new_outcome,
        )
        data = json.loads((result_dir / "outcome.json").read_text())
        assert data["committed"] is False


# ---------------------------------------------------------------------------
# Load committed
# ---------------------------------------------------------------------------


class TestLoadCommitted:
    def test_load_committed_only(
        self,
        workspace: Path,
        sample_candidates,
        sample_assessments,
        committed_outcome,
        blocked_outcome,
    ):
        persist_decision_artifacts(
            workspace,
            "run-1",
            "DEC-001",
            sample_candidates,
            sample_assessments,
            committed_outcome,
        )
        persist_decision_artifacts(
            workspace,
            "run-1",
            "DEC-002",
            [],
            [],
            blocked_outcome,
        )
        results = load_committed_decisions(workspace, "run-1")
        assert len(results) == 1
        assert results[0].decision_id == "DEC-001"
        assert results[0].committed is True

    def test_no_decisions_dir(self, workspace: Path):
        results = load_committed_decisions(workspace, "no-run")
        assert results == []

    def test_corrupted_json_skipped(self, workspace: Path):
        decision_dir = (
            workspace / "reports" / "pdd" / "run-x" / "architecture" / "decisions" / "DEC-BAD"
        )
        decision_dir.mkdir(parents=True)
        (decision_dir / "outcome.json").write_text("not json", encoding="utf-8")
        results = load_committed_decisions(workspace, "run-x")
        assert results == []
