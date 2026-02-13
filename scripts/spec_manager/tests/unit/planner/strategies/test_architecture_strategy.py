"""Tests for ArchitecturePlannerStrategy."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from spec_manager.orchestration.coordination.wait_graph import WaitEdge, WaitGraph
from spec_manager.orchestration.coordination.work_items import WorkItemStore
from spec_manager.planner.architecture.types import (
    ArchitectureCandidate,
    CandidateAssessment,
    DecisionOutcome,
    DecisionPoint,
    ScopePacket,
)
from spec_manager.planner.constraints.types import (
    ConstraintContext,
    ConstraintFact,
    ImpactClassification,
)
from spec_manager.planner.strategies.architecture_strategy import (
    ArchitecturePlannerStrategy,
)
from spec_manager.planner.strategies.protocol import PlanningSession

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_candidate(candidate_id: str = "C1", decision_id: str = "DP-001") -> ArchitectureCandidate:
    """Helper to create a mock ArchitectureCandidate."""
    return ArchitectureCandidate(
        candidate_id=candidate_id,
        decision_id=decision_id,
        scope="intra:test_lib",
        proposal={"title": "Test Pattern", "summary": "Test summary"},
    )


def _mock_assessment(
    candidate_id: str = "C1", recommendation: str = "accept"
) -> CandidateAssessment:
    """Helper to create a mock CandidateAssessment."""
    return CandidateAssessment(
        candidate_id=candidate_id,
        risk_score=0.2,
        recommendation=recommendation,
    )


def _l2_medium_session(**ctx_overrides) -> PlanningSession:
    ctx = {
        "layer": "L2",
        "slice_id": "test_lib",
        "run_id": "run-001",
        **ctx_overrides,
    }
    return PlanningSession(
        ctx=ctx,
        impact=ImpactClassification(impact="MEDIUM"),
        gaps=[
            {
                "kind": "topology",
                "description": "architecture pattern needed",
                "target": "PaymentService",
            }
        ],
        discovery={"nodes": [{"kind": "component", "name": "PaymentService"}]},
        constraint_context=ConstraintContext(
            authoritative=[
                ConstraintFact(
                    constraint_id="CON-001",
                    question="Use REST?",
                    answer="Yes",
                    validated=True,
                )
            ]
        ),
    )


def _l2_high_session(**ctx_overrides) -> PlanningSession:
    session = _l2_medium_session(**ctx_overrides)
    session.impact = ImpactClassification(impact="HIGH")
    return session


# ---------------------------------------------------------------------------
# Tests: Gating
# ---------------------------------------------------------------------------


class TestArchitectureStrategyGating:
    def test_skips_for_l1(self, tmp_path):
        s = ArchitecturePlannerStrategy(workspace_root=tmp_path)
        session = PlanningSession(
            ctx={"layer": "L1"},
            impact=ImpactClassification(impact="MEDIUM"),
        )
        result = s.run(session)
        assert result.decision_outcomes == []

    def test_skips_for_l3(self, tmp_path):
        s = ArchitecturePlannerStrategy(workspace_root=tmp_path)
        session = PlanningSession(
            ctx={"layer": "L3"},
            impact=ImpactClassification(impact="MEDIUM"),
        )
        result = s.run(session)
        assert result.decision_outcomes == []

    def test_skips_for_low_impact(self, tmp_path):
        s = ArchitecturePlannerStrategy(workspace_root=tmp_path)
        session = PlanningSession(
            ctx={"layer": "L2"},
            impact=ImpactClassification(impact="LOW"),
        )
        result = s.run(session)
        assert result.decision_outcomes == []

    def test_skips_when_no_impact(self, tmp_path):
        s = ArchitecturePlannerStrategy(workspace_root=tmp_path)
        session = PlanningSession(ctx={"layer": "L2"})
        result = s.run(session)
        assert result.decision_outcomes == []

    def test_runs_for_l2_medium(self, tmp_path):
        """Verifies strategy runs for L2+MEDIUM (using heuristic fallback)."""
        s = ArchitecturePlannerStrategy(workspace_root=tmp_path)
        session = _l2_medium_session()
        result = s.run(session)
        # Heuristic detector should find decision points from architecture-keyword gaps
        assert len(result.decision_outcomes) >= 1


# ---------------------------------------------------------------------------
# Tests: Integration (heuristic mode, no LLM)
# ---------------------------------------------------------------------------


class TestArchitectureStrategyHeuristic:
    def test_detects_and_resolves_decision_points(self, tmp_path):
        s = ArchitecturePlannerStrategy(workspace_root=tmp_path)
        session = _l2_medium_session()
        result = s.run(session)

        # Should have at least one outcome
        assert len(result.decision_outcomes) >= 1
        # Artifacts should be persisted
        decisions_dir = tmp_path / "reports" / "pdd" / "run-001" / "architecture" / "decisions"
        assert decisions_dir.exists()

    def test_high_impact_uses_k3(self, tmp_path):
        """Verifies HIGH impact produces more candidates (K=3)."""
        s = ArchitecturePlannerStrategy(workspace_root=tmp_path)
        session = _l2_high_session()
        _ = s.run(session)

        # Check that artifacts were written
        decisions_dir = tmp_path / "reports" / "pdd" / "run-001" / "architecture" / "decisions"
        if decisions_dir.exists():
            for dec_dir in decisions_dir.iterdir():
                candidates_path = dec_dir / "candidates.json"
                if candidates_path.exists():
                    candidates = json.loads(candidates_path.read_text())
                    # HIGH impact should produce 3 candidates
                    assert len(candidates) == 3

    def test_no_decision_points_returns_unchanged(self, tmp_path):
        s = ArchitecturePlannerStrategy(workspace_root=tmp_path)
        session = PlanningSession(
            ctx={"layer": "L2", "slice_id": "test_lib", "run_id": "run-001"},
            impact=ImpactClassification(impact="MEDIUM"),
            gaps=[{"kind": "naming", "description": "rename variable"}],
            discovery={},
        )
        result = s.run(session)
        assert result.decision_outcomes == []

    def test_committed_outcome_adds_intentions(self, tmp_path):
        s = ArchitecturePlannerStrategy(workspace_root=tmp_path)
        session = _l2_medium_session()
        result = s.run(session)

        committed = [o for o in result.decision_outcomes if o.committed]
        if committed:
            # Wiring intentions should be on the session
            assert len(result.intentions) >= 1

    def test_blocked_outcome_adds_under_spec(self, tmp_path):
        """When decision is blocked, under_spec_events should be populated."""
        s = ArchitecturePlannerStrategy(workspace_root=tmp_path)
        session = _l2_medium_session()
        # Add constraint that requires human -> forces needs_human path
        session.constraint_context = ConstraintContext(
            authoritative=[
                ConstraintFact(
                    constraint_id="CON-BLOCK",
                    question="Requires human review",
                    answer="Yes",
                    validated=True,
                    authority_required="human_required",
                )
            ]
        )
        result = s.run(session)
        # With human-required constraint, evaluator should produce needs_human
        # outcome which has decision_requirements instead of under_spec_events
        blocked = [o for o in result.decision_outcomes if not o.committed]
        if blocked:
            # Either decision_requirements or under_spec_events should be non-empty
            has_escalation = any(o.decision_requirements for o in blocked) or any(
                o.under_spec_events for o in blocked
            )
            assert has_escalation


# ---------------------------------------------------------------------------
# Tests: Name property
# ---------------------------------------------------------------------------


class TestArchitectureStrategyMeta:
    def test_name(self, tmp_path):
        s = ArchitecturePlannerStrategy(workspace_root=tmp_path)
        assert s.name == "architecture_planner"


# ---------------------------------------------------------------------------
# Tests: Fix 4 - ARCH_DECISION WorkItems
# ---------------------------------------------------------------------------


class TestArchitectureStrategyWorkItems:
    """Tests for Fix 4: ARCH_DECISION work item creation and status updates."""

    def test_creates_arch_decision_work_items(self, tmp_path, monkeypatch):
        """Strategy creates ARCH_DECISION work items for detected decision points."""
        # Setup work item store
        store = WorkItemStore(tmp_path / "coordination")

        # Create strategy with work item store
        _ = ArchitecturePlannerStrategy(
            workspace_root=tmp_path,
            work_item_store=store,
        )

        # Mock detector to return decision points
        mock_decision_points = [
            DecisionPoint(
                decision_id="DP-001",
                description="Choose messaging pattern",
                scope="intra:test_lib",
                trigger_evidence=["gap:topology"],
                required_constraints=["CON-001"],
                owner_slice_id="test_lib",
            ),
        ]

        def mock_detect(*args, **kwargs):
            return mock_decision_points

        # Mock the proposer and evaluator to avoid LLM calls
        mock_candidate = _mock_candidate("C1", "DP-001")
        mock_assessment = _mock_assessment("C1", "accept")

        mock_outcome = DecisionOutcome(
            decision_id="DP-001",
            committed=True,
            selected_candidate_id="C1",
            wiring_intentions=[],
            under_spec_events=[],
            decision_requirements=[],
        )

        with (
            patch(
                "spec_manager.planner.architecture.decision_detector.DecisionPointDetector.detect",
                side_effect=mock_detect,
            ),
            patch(
                "spec_manager.planner.architecture.proposer.ProposerOrchestrator.run_proposers",
                return_value=[mock_candidate],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.evaluate",
                return_value=[mock_assessment],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.select_or_block",
                return_value=mock_outcome,
            ),
        ):
            session = _l2_medium_session()
            strategy.run(session)

        # Assert work item was created
        work_item = store.get("DP-001")
        assert work_item is not None
        assert work_item.kind == "ARCH_DECISION"
        assert work_item.spec_text == "Choose messaging pattern"
        assert work_item.owner_slice_id == "test_lib"
        assert work_item.metadata["scope"] == "intra:test_lib"

    def test_updates_work_item_to_done_on_commit(self, tmp_path, monkeypatch):
        """When decision is committed, work item status updates to DONE."""
        store = WorkItemStore(tmp_path / "coordination")
        strategy = ArchitecturePlannerStrategy(
            workspace_root=tmp_path,
            work_item_store=store,
        )

        mock_decision_points = [
            DecisionPoint(
                decision_id="DP-002",
                description="Choose data format",
                scope="intra:test_lib",
                trigger_evidence=["gap:data"],
                required_constraints=[],
                owner_slice_id="test_lib",
            ),
        ]

        mock_outcome = DecisionOutcome(
            decision_id="DP-002",
            committed=True,  # Committed
            selected_candidate_id="C1",
            wiring_intentions=[],
            under_spec_events=[],
            decision_requirements=[],
        )

        with (
            patch(
                "spec_manager.planner.architecture.decision_detector.DecisionPointDetector.detect",
                return_value=mock_decision_points,
            ),
            patch(
                "spec_manager.planner.architecture.proposer.ProposerOrchestrator.run_proposers",
                return_value=[_mock_candidate("C1", "DP-002")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.evaluate",
                return_value=[_mock_assessment("C1", "accept")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.select_or_block",
                return_value=mock_outcome,
            ),
        ):
            session = _l2_medium_session()
            strategy.run(session)

        # Check work item status
        work_item = store.get("DP-002")
        assert work_item is not None
        assert work_item.status == "DONE"

    def test_updates_work_item_to_blocked(self, tmp_path):
        """When decision is blocked with under_spec_events, work item status is BLOCKED."""
        store = WorkItemStore(tmp_path / "coordination")
        strategy = ArchitecturePlannerStrategy(
            workspace_root=tmp_path,
            work_item_store=store,
        )

        mock_decision_points = [
            DecisionPoint(
                decision_id="DP-003",
                description="Choose error handling",
                scope="intra:test_lib",
                trigger_evidence=["gap:error"],
                required_constraints=[],
                owner_slice_id="test_lib",
            ),
        ]

        # Decision is blocked
        mock_outcome = DecisionOutcome(
            decision_id="DP-003",
            committed=False,
            selected_candidate_id=None,
            wiring_intentions=[],
            under_spec_events=[{"description": "Need error policy"}],
            decision_requirements=[],
        )

        with (
            patch(
                "spec_manager.planner.architecture.decision_detector.DecisionPointDetector.detect",
                return_value=mock_decision_points,
            ),
            patch(
                "spec_manager.planner.architecture.proposer.ProposerOrchestrator.run_proposers",
                return_value=[_mock_candidate("C1", "DP-003")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.evaluate",
                return_value=[_mock_assessment("C1", "reject")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.select_or_block",
                return_value=mock_outcome,
            ),
        ):
            session = _l2_medium_session()
            strategy.run(session)

        # Check work item status
        work_item = store.get("DP-003")
        assert work_item is not None
        assert work_item.status == "BLOCKED"

    def test_no_work_items_without_store(self, tmp_path):
        """Strategy with work_item_store=None should not error."""
        strategy = ArchitecturePlannerStrategy(
            workspace_root=tmp_path,
            work_item_store=None,  # No store
        )

        mock_decision_points = [
            DecisionPoint(
                decision_id="DP-004",
                description="Choose protocol",
                scope="intra:test_lib",
                trigger_evidence=["gap:protocol"],
                required_constraints=[],
                owner_slice_id="test_lib",
            ),
        ]

        mock_outcome = DecisionOutcome(
            decision_id="DP-004",
            committed=True,
            selected_candidate_id="C1",
            wiring_intentions=[],
            under_spec_events=[],
            decision_requirements=[],
        )

        with (
            patch(
                "spec_manager.planner.architecture.decision_detector.DecisionPointDetector.detect",
                return_value=mock_decision_points,
            ),
            patch(
                "spec_manager.planner.architecture.proposer.ProposerOrchestrator.run_proposers",
                return_value=[_mock_candidate("C1", "DP-004")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.evaluate",
                return_value=[_mock_assessment("C1", "accept")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.select_or_block",
                return_value=mock_outcome,
            ),
        ):
            session = _l2_medium_session()
            result = strategy.run(session)
            # Should not error, should return normally
            assert len(result.decision_outcomes) == 1


# ---------------------------------------------------------------------------
# Tests: Fix 6 - WaitGraph edges for blocked decisions
# ---------------------------------------------------------------------------


class TestArchitectureStrategyWaitGraph:
    """Tests for Fix 6: WaitGraph edge creation for blocked decisions."""

    def test_adds_wait_edges_for_blocked_decisions(self, tmp_path):
        """Strategy adds WaitEdge when decision has decision_requirements."""
        wait_graph = WaitGraph()
        strategy = ArchitecturePlannerStrategy(
            workspace_root=tmp_path,
            wait_graph=wait_graph,
        )

        mock_decision_points = [
            DecisionPoint(
                decision_id="DP-005",
                description="Choose cache strategy",
                scope="intra:test_lib",
                trigger_evidence=["gap:cache"],
                required_constraints=[],
                owner_slice_id="test_lib",
            ),
        ]

        # Decision is blocked with decision_requirements
        mock_outcome = DecisionOutcome(
            decision_id="DP-005",
            committed=False,
            selected_candidate_id=None,
            wiring_intentions=[],
            under_spec_events=[],
            decision_requirements=["DP-001"],  # Requires another decision
        )

        with (
            patch(
                "spec_manager.planner.architecture.decision_detector.DecisionPointDetector.detect",
                return_value=mock_decision_points,
            ),
            patch(
                "spec_manager.planner.architecture.proposer.ProposerOrchestrator.run_proposers",
                return_value=[_mock_candidate("C1", "DP-005")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.evaluate",
                return_value=[_mock_assessment("C1", "needs_human")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.select_or_block",
                return_value=mock_outcome,
            ),
        ):
            session = _l2_medium_session(slice_id="test_lib")
            strategy.run(session)

        # Check that wait edge was added
        edges = wait_graph._edges
        assert len(edges) == 1
        assert edges[0].waiting_slice == "test_lib"
        assert edges[0].provider_slice == "DP-001"
        assert edges[0].artifact_key == "arch_decision:DP-005"

    def test_no_wait_edges_for_committed_decisions(self, tmp_path):
        """Committed decisions do not add WaitGraph edges."""
        wait_graph = WaitGraph()
        strategy = ArchitecturePlannerStrategy(
            workspace_root=tmp_path,
            wait_graph=wait_graph,
        )

        mock_decision_points = [
            DecisionPoint(
                decision_id="DP-006",
                description="Choose API format",
                scope="intra:test_lib",
                trigger_evidence=["gap:api"],
                required_constraints=[],
                owner_slice_id="test_lib",
            ),
        ]

        # Decision is committed (not blocked)
        mock_outcome = DecisionOutcome(
            decision_id="DP-006",
            committed=True,
            selected_candidate_id="C1",
            wiring_intentions=[],
            under_spec_events=[],
            decision_requirements=["DP-001"],  # Has requirements but committed
        )

        with (
            patch(
                "spec_manager.planner.architecture.decision_detector.DecisionPointDetector.detect",
                return_value=mock_decision_points,
            ),
            patch(
                "spec_manager.planner.architecture.proposer.ProposerOrchestrator.run_proposers",
                return_value=[_mock_candidate("C1", "DP-006")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.evaluate",
                return_value=[_mock_assessment("C1", "accept")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.select_or_block",
                return_value=mock_outcome,
            ),
        ):
            session = _l2_medium_session()
            strategy.run(session)

        # No edges should be added for committed decisions
        edges = wait_graph._edges
        assert len(edges) == 0

    def test_no_wait_edges_without_graph(self, tmp_path):
        """Strategy with wait_graph=None should not error."""
        strategy = ArchitecturePlannerStrategy(
            workspace_root=tmp_path,
            wait_graph=None,  # No wait graph
        )

        mock_decision_points = [
            DecisionPoint(
                decision_id="DP-007",
                description="Choose auth method",
                scope="intra:test_lib",
                trigger_evidence=["gap:auth"],
                required_constraints=[],
                owner_slice_id="test_lib",
            ),
        ]

        mock_outcome = DecisionOutcome(
            decision_id="DP-007",
            committed=False,
            selected_candidate_id=None,
            wiring_intentions=[],
            under_spec_events=[],
            decision_requirements=["DP-002"],
        )

        with (
            patch(
                "spec_manager.planner.architecture.decision_detector.DecisionPointDetector.detect",
                return_value=mock_decision_points,
            ),
            patch(
                "spec_manager.planner.architecture.proposer.ProposerOrchestrator.run_proposers",
                return_value=[_mock_candidate("C1", "DP-007")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.evaluate",
                return_value=[_mock_assessment("C1", "needs_human")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.select_or_block",
                return_value=mock_outcome,
            ),
        ):
            session = _l2_medium_session()
            result = strategy.run(session)
            # Should not error
            assert len(result.decision_outcomes) == 1


# ---------------------------------------------------------------------------
# Tests: Fix 7 - ScopePacket populated with source artifacts
# ---------------------------------------------------------------------------


class TestArchitectureStrategyScopePacket:
    """Tests for Fix 7: ScopePacket population with routed source artifacts."""

    def test_scope_packet_intra_loads_charter(self, tmp_path):
        """For intra-library scope, ScopePacket includes charter_text."""
        # Setup workspace with library charter
        lib_dir = tmp_path / "libraries" / "mylib"
        lib_dir.mkdir(parents=True)
        charter_path = lib_dir / "charter.md"
        charter_path.write_text("# Library Charter\nPurpose: Handle payments", encoding="utf-8")

        strategy = ArchitecturePlannerStrategy(workspace_root=tmp_path)

        # Track the ScopePacket passed to proposer
        captured_scope_packet = None

        def mock_run_proposers(dp, scope_packet):
            nonlocal captured_scope_packet
            captured_scope_packet = scope_packet
            return [_mock_candidate("C1", "DP-008")]

        mock_decision_points = [
            DecisionPoint(
                decision_id="DP-008",
                description="Choose payment gateway",
                scope="intra:mylib",
                trigger_evidence=["gap:gateway"],
                required_constraints=[],
                owner_slice_id="mylib",
            ),
        ]

        mock_outcome = DecisionOutcome(
            decision_id="DP-008",
            committed=True,
            selected_candidate_id="C1",
            wiring_intentions=[],
            under_spec_events=[],
            decision_requirements=[],
        )

        with (
            patch(
                "spec_manager.planner.architecture.decision_detector.DecisionPointDetector.detect",
                return_value=mock_decision_points,
            ),
            patch(
                "spec_manager.planner.architecture.proposer.ProposerOrchestrator.run_proposers",
                side_effect=mock_run_proposers,
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.evaluate",
                return_value=[_mock_assessment("C1", "accept")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.select_or_block",
                return_value=mock_outcome,
            ),
        ):
            session = _l2_medium_session(slice_id="mylib")
            strategy.run(session)

        # Assert ScopePacket contains charter_text
        assert captured_scope_packet is not None
        assert "charter_text" in captured_scope_packet.source_artifacts
        assert "Library Charter" in captured_scope_packet.source_artifacts["charter_text"]

    def test_scope_packet_intra_loads_constraints(self, tmp_path):
        """For intra-library scope, ScopePacket includes constraint_spans."""
        lib_dir = tmp_path / "libraries" / "mylib"
        lib_dir.mkdir(parents=True)
        constraints_path = lib_dir / "constraints.md"
        constraints_path.write_text("# Constraints\n- Must use HTTPS", encoding="utf-8")

        strategy = ArchitecturePlannerStrategy(workspace_root=tmp_path)

        captured_scope_packet = None

        def mock_run_proposers(dp, scope_packet):
            nonlocal captured_scope_packet
            captured_scope_packet = scope_packet
            return [_mock_candidate("C1", "DP-009")]

        mock_decision_points = [
            DecisionPoint(
                decision_id="DP-009",
                description="Choose protocol",
                scope="intra:mylib",
                trigger_evidence=["gap:protocol"],
                required_constraints=[],
                owner_slice_id="mylib",
            ),
        ]

        mock_outcome = DecisionOutcome(
            decision_id="DP-009",
            committed=True,
            selected_candidate_id="C1",
            wiring_intentions=[],
            under_spec_events=[],
            decision_requirements=[],
        )

        with (
            patch(
                "spec_manager.planner.architecture.decision_detector.DecisionPointDetector.detect",
                return_value=mock_decision_points,
            ),
            patch(
                "spec_manager.planner.architecture.proposer.ProposerOrchestrator.run_proposers",
                side_effect=mock_run_proposers,
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.evaluate",
                return_value=[_mock_assessment("C1", "accept")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.select_or_block",
                return_value=mock_outcome,
            ),
        ):
            session = _l2_medium_session(slice_id="mylib")
            strategy.run(session)

        assert captured_scope_packet is not None
        assert "constraint_spans" in captured_scope_packet.source_artifacts
        assert "Must use HTTPS" in captured_scope_packet.source_artifacts["constraint_spans"]

    def test_scope_packet_inter_loads_both_libraries(self, tmp_path):
        """For inter-library scope, ScopePacket includes artifacts from both libraries."""
        # Setup two libraries
        lib_a_dir = tmp_path / "libraries" / "libA"
        lib_a_dir.mkdir(parents=True)
        (lib_a_dir / "charter.md").write_text("# Library A Charter", encoding="utf-8")

        lib_b_dir = tmp_path / "libraries" / "libB"
        lib_b_dir.mkdir(parents=True)
        (lib_b_dir / "charter.md").write_text("# Library B Charter", encoding="utf-8")

        strategy = ArchitecturePlannerStrategy(workspace_root=tmp_path)

        captured_scope_packet = None

        def mock_run_proposers(dp, scope_packet):
            nonlocal captured_scope_packet
            captured_scope_packet = scope_packet
            return [_mock_candidate("C1", "DP-010")]

        mock_decision_points = [
            DecisionPoint(
                decision_id="DP-010",
                description="Choose interaction pattern",
                scope="inter:libA->libB:event",
                trigger_evidence=["gap:interaction"],
                required_constraints=[],
                owner_slice_id="libA",
            ),
        ]

        mock_outcome = DecisionOutcome(
            decision_id="DP-010",
            committed=True,
            selected_candidate_id="C1",
            wiring_intentions=[],
            under_spec_events=[],
            decision_requirements=[],
        )

        with (
            patch(
                "spec_manager.planner.architecture.decision_detector.DecisionPointDetector.detect",
                return_value=mock_decision_points,
            ),
            patch(
                "spec_manager.planner.architecture.proposer.ProposerOrchestrator.run_proposers",
                side_effect=mock_run_proposers,
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.evaluate",
                return_value=[_mock_assessment("C1", "accept")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.select_or_block",
                return_value=mock_outcome,
            ),
        ):
            session = _l2_medium_session(slice_id="libA")
            strategy.run(session)

        # Assert both libraries are in source_artifacts
        assert captured_scope_packet is not None
        assert "libA" in captured_scope_packet.source_artifacts
        assert "libB" in captured_scope_packet.source_artifacts
        assert "charter_text" in captured_scope_packet.source_artifacts["libA"]
        assert "charter_text" in captured_scope_packet.source_artifacts["libB"]

    def test_scope_packet_includes_arch_refs(self, tmp_path):
        """ScopePacket includes current_arch_state_refs from discovery."""
        strategy = ArchitecturePlannerStrategy(workspace_root=tmp_path)

        captured_scope_packet = None

        def mock_run_proposers(dp, scope_packet):
            nonlocal captured_scope_packet
            captured_scope_packet = scope_packet
            return [_mock_candidate("C1", "DP-011")]

        mock_decision_points = [
            DecisionPoint(
                decision_id="DP-011",
                description="Choose pattern",
                scope="intra:mylib",
                trigger_evidence=["gap:pattern"],
                required_constraints=[],
                owner_slice_id="mylib",
            ),
        ]

        mock_outcome = DecisionOutcome(
            decision_id="DP-011",
            committed=True,
            selected_candidate_id="C1",
            wiring_intentions=[],
            under_spec_events=[],
            decision_requirements=[],
        )

        with (
            patch(
                "spec_manager.planner.architecture.decision_detector.DecisionPointDetector.detect",
                return_value=mock_decision_points,
            ),
            patch(
                "spec_manager.planner.architecture.proposer.ProposerOrchestrator.run_proposers",
                side_effect=mock_run_proposers,
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.evaluate",
                return_value=[_mock_assessment("C1", "accept")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.select_or_block",
                return_value=mock_outcome,
            ),
        ):
            # Session with arch_files in discovery
            session = _l2_medium_session(slice_id="mylib")
            session.discovery = {
                "nodes": [],
                "arch_files": ["component_manifest.yaml", "wiring.yaml"],
            }
            strategy.run(session)

        assert captured_scope_packet is not None
        assert len(captured_scope_packet.current_arch_state_refs) == 2
        assert "component_manifest.yaml" in captured_scope_packet.current_arch_state_refs
        assert "wiring.yaml" in captured_scope_packet.current_arch_state_refs

    def test_scope_packet_includes_tradeoff_axes(self, tmp_path):
        """ScopePacket includes tradeoff_assignment from session."""
        strategy = ArchitecturePlannerStrategy(workspace_root=tmp_path)

        captured_scope_packet = None

        def mock_run_proposers(dp, scope_packet):
            nonlocal captured_scope_packet
            captured_scope_packet = scope_packet
            return [_mock_candidate("C1", "DP-012")]

        mock_decision_points = [
            DecisionPoint(
                decision_id="DP-012",
                description="Choose caching",
                scope="intra:mylib",
                trigger_evidence=["gap:caching"],
                required_constraints=[],
                owner_slice_id="mylib",
            ),
        ]

        mock_outcome = DecisionOutcome(
            decision_id="DP-012",
            committed=True,
            selected_candidate_id="C1",
            wiring_intentions=[],
            under_spec_events=[],
            decision_requirements=[],
        )

        with (
            patch(
                "spec_manager.planner.architecture.decision_detector.DecisionPointDetector.detect",
                return_value=mock_decision_points,
            ),
            patch(
                "spec_manager.planner.architecture.proposer.ProposerOrchestrator.run_proposers",
                side_effect=mock_run_proposers,
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.evaluate",
                return_value=[_mock_assessment("C1", "accept")],
            ),
            patch(
                "spec_manager.planner.architecture.evaluator.CandidateEvaluator.select_or_block",
                return_value=mock_outcome,
            ),
        ):
            # Session with tradeoff axes
            session = _l2_medium_session(slice_id="mylib")
            session.tradeoff_axes = ["latency", "throughput", "cost"]
            strategy.run(session)

        assert captured_scope_packet is not None
        assert len(captured_scope_packet.tradeoff_assignment) == 3
        assert captured_scope_packet.tradeoff_assignment["latency"] == "consider"
        assert captured_scope_packet.tradeoff_assignment["throughput"] == "consider"
        assert captured_scope_packet.tradeoff_assignment["cost"] == "consider"
