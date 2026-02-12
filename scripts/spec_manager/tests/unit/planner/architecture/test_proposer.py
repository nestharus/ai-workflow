"""Tests for spec_manager.planner.architecture.proposer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from spec_manager.planner.architecture.proposer import (
    ProposerOrchestrator,
    _select_axes,
)
from spec_manager.planner.architecture.types import (
    ArchitectureCandidate,
    DecisionPoint,
    ScopePacket,
)
from spec_manager.planner.constraints.types import ConstraintFact, ImpactClassification


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def decision_point() -> DecisionPoint:
    return DecisionPoint(
        decision_id="DEC-001",
        scope="intra:LIB",
        description="Choose caching strategy",
        impact=ImpactClassification(impact="MEDIUM", blast_radius="SLICE"),
        owner_slice_id="slice-1",
    )


@pytest.fixture()
def scope_packet() -> ScopePacket:
    return ScopePacket(
        decision_id="DEC-001",
        scope="intra:LIB",
        authoritative_constraints=[
            ConstraintFact(constraint_id="CON-001", question="Use Redis?", answer="Yes"),
        ],
        current_arch_state_refs=["ref-1"],
    )


# ---------------------------------------------------------------------------
# Tradeoff position assignment
# ---------------------------------------------------------------------------


class TestAssignTradeoffPositions:
    def test_returns_k_positions(self, workspace: Path, decision_point):
        proposer = ProposerOrchestrator(workspace, k=3)
        positions = proposer.assign_tradeoff_positions(decision_point)
        assert len(positions) == 3

    def test_each_position_has_axes(self, workspace: Path, decision_point):
        proposer = ProposerOrchestrator(workspace, k=2)
        positions = proposer.assign_tradeoff_positions(decision_point)
        for pos in positions:
            assert len(pos) > 0
            for axis, priority in pos.items():
                assert priority in ("prioritize", "sacrifice")

    def test_positions_are_distinct(self, workspace: Path, decision_point):
        proposer = ProposerOrchestrator(workspace, k=3)
        positions = proposer.assign_tradeoff_positions(decision_point)
        # At least 2 distinct positions
        serialized = [json.dumps(p, sort_keys=True) for p in positions]
        assert len(set(serialized)) >= 2

    def test_override_k(self, workspace: Path, decision_point):
        proposer = ProposerOrchestrator(workspace, k=3)
        positions = proposer.assign_tradeoff_positions(decision_point, k=5)
        assert len(positions) == 5

    def test_system_scope_adds_scalability(self, workspace: Path):
        dp = DecisionPoint(
            decision_id="DEC-SYS",
            scope="system",
            description="Global routing",
            impact=ImpactClassification(impact="HIGH", blast_radius="SYSTEM"),
        )
        axes = _select_axes(dp, 3)
        assert "scalability" in axes


# ---------------------------------------------------------------------------
# Stub proposer (no LLM)
# ---------------------------------------------------------------------------


class TestStubProposer:
    def test_run_proposers_no_llm(self, workspace: Path, decision_point, scope_packet):
        proposer = ProposerOrchestrator(workspace, k=2)
        candidates = proposer.run_proposers(decision_point, scope_packet)
        assert len(candidates) == 2
        for cand in candidates:
            assert cand.candidate_id.startswith("CAND-")
            assert cand.decision_id == "DEC-001"
            assert cand.proposal["approach"] == "stub_proposal"

    def test_stub_has_trace(self, workspace: Path, decision_point, scope_packet):
        proposer = ProposerOrchestrator(workspace, k=1)
        candidates = proposer.run_proposers(decision_point, scope_packet)
        assert len(candidates[0].trace) == 1
        assert "DEC-001" in candidates[0].trace[0]


# ---------------------------------------------------------------------------
# LLM proposer (mocked)
# ---------------------------------------------------------------------------


class TestLLMProposer:
    def test_run_proposers_with_llm(self, workspace: Path, decision_point, scope_packet):
        llm_response = json.dumps({
            "approach": "event-driven",
            "details": "Use message queue for decoupling",
            "constraints_introduced": {
                "software": {"async-io": "Must use async"},
                "non_software": {},
            },
            "decision_requirements": [],
            "assumptions": ["Message broker available"],
        })
        mock_agent = lambda prompt: llm_response

        proposer = ProposerOrchestrator(workspace, k=2, run_agent=mock_agent)
        candidates = proposer.run_proposers(decision_point, scope_packet)
        assert len(candidates) == 2
        for cand in candidates:
            assert cand.proposal["approach"] == "event-driven"
            assert cand.assumptions == ["Message broker available"]
            assert cand.constraints_introduced["software"]["async-io"] == "Must use async"

    def test_llm_returns_garbage(self, workspace: Path, decision_point, scope_packet):
        mock_agent = lambda prompt: "not valid json"
        proposer = ProposerOrchestrator(workspace, k=1, run_agent=mock_agent)
        candidates = proposer.run_proposers(decision_point, scope_packet)
        assert len(candidates) == 1
        assert candidates[0].proposal.get("approach") == "parse_error"

    def test_custom_tradeoff_positions(self, workspace: Path, decision_point, scope_packet):
        llm_response = json.dumps({
            "approach": "monolith",
            "details": "Single process",
            "constraints_introduced": {"software": {}, "non_software": {}},
            "decision_requirements": [],
            "assumptions": [],
        })
        mock_agent = lambda prompt: llm_response
        proposer = ProposerOrchestrator(workspace, k=3, run_agent=mock_agent)
        custom_positions = [
            {"speed": "prioritize", "quality": "sacrifice"},
        ]
        candidates = proposer.run_proposers(
            decision_point, scope_packet, tradeoff_positions=custom_positions
        )
        assert len(candidates) == 1
        assert candidates[0].position == {"speed": "prioritize", "quality": "sacrifice"}
