"""Tests for spec_manager.planner.api — core types and Planner class."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from spec_manager.planner.api import (
    Capability,
    Layer,
    Planner,
    PlanningContext,
    PlanningRequest,
    PlanningResult,
    _planner_ingest_authority_policy,
    _request_snapshot,
)
from spec_manager.planner.router import LayerPlanner

# ---------------------------------------------------------------------------
# Helpers — tiny mock planner that satisfies the LayerPlanner protocol
# ---------------------------------------------------------------------------


class _MockLayerPlanner:
    """Minimal LayerPlanner for routing tests."""

    def __init__(self, layer: str) -> None:
        self.layer = layer
        self.last_ctx: Any = None

    def discover(self, ctx: Any) -> dict[str, Any]:
        self.last_ctx = ctx
        return {"nodes": [], "edges": []}

    def build_plan(
        self, ctx: Any, gaps: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        self.last_ctx = ctx
        return {"intentions": [{"from": self.layer}]}

    def resolve_under_spec(
        self, ctx: Any, events: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        self.last_ctx = ctx
        return {"blocked": False, "constraints": {}}

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        self.last_ctx = ctx
        if signal is None:
            return None
        return {"resolved": True, "target": str(signal)}

    def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
        self.last_ctx = ctx
        return {"action": "NOOP", "monitors": []}


class _HumanRequiredPlanLayerPlanner(_MockLayerPlanner):
    """Layer planner that returns human-required under-spec events."""

    def build_plan(
        self, ctx: Any, gaps: list[dict[str, Any]], discovery: dict[str, Any]
    ) -> dict[str, Any]:
        self.last_ctx = ctx
        return {
            "intentions": [{"from": self.layer}],
            "under_spec_events": [
                {
                    "type": "decision_required",
                    "decision_id": "DR-001",
                    "question": "What SLA should we guarantee?",
                    "reason": "human authority required",
                }
            ],
        }


# ---------------------------------------------------------------------------
# PlanningContext
# ---------------------------------------------------------------------------


class TestPlanningContext:
    def test_planning_context_defaults(self) -> None:
        ctx = PlanningContext()
        assert ctx.run_id == ""
        assert ctx.slice_id == ""
        assert ctx.iteration == 0
        assert ctx.layer == "any"
        assert ctx.mode == "auto"
        assert ctx.workspace_root == ""
        assert ctx.slice_root == ""
        assert ctx.bundle_ref is None
        assert ctx.signal_ref is None
        assert ctx.metadata == {}


# ---------------------------------------------------------------------------
# PlanningRequest
# ---------------------------------------------------------------------------


class TestPlanningRequest:
    def test_planning_request_creation(self) -> None:
        ctx = PlanningContext(layer="l1", run_id="run-1")
        req = PlanningRequest(
            capability="GAP",
            context=ctx,
            inputs={"foo": "bar"},
        )
        assert req.capability == "GAP"
        assert req.context is ctx
        assert req.inputs == {"foo": "bar"}
        assert req.constraints_hint is None


# ---------------------------------------------------------------------------
# PlanningResult
# ---------------------------------------------------------------------------


class TestPlanningResult:
    def test_planning_result_statuses(self) -> None:
        for status in ("OK", "BLOCKED", "NEEDS_INPUT", "NOOP", "ERROR", "WAITING"):
            result = PlanningResult(status=status)
            assert result.status == status
            assert result.outputs == {}
            assert result.trace_id == ""
            assert result.error == ""


# ---------------------------------------------------------------------------
# Planner routing
# ---------------------------------------------------------------------------


class TestPlannerRouting:
    def _make_planner(self, tmp_path: Any) -> tuple[Planner, dict[str, _MockLayerPlanner]]:
        """Build a Planner with mock layer planners for each layer."""
        planner = Planner(workspace_root=tmp_path, register_defaults=False)
        mocks: dict[str, _MockLayerPlanner] = {}
        for layer in ("l1", "l2", "l3"):
            mock = _MockLayerPlanner(layer)
            planner.register_layer_planner(layer, mock)
            mocks[layer] = mock
        return planner, mocks

    def test_planner_routes_to_correct_layer(self, tmp_path: Any) -> None:
        planner, mocks = self._make_planner(tmp_path)

        for layer in ("l1", "l2", "l3"):
            ctx = PlanningContext(layer=layer, slice_id=f"slice-{layer}")
            req = PlanningRequest(capability="GAP", context=ctx)
            result = planner.plan(req)
            assert result.status == "OK"
            assert mocks[layer].last_ctx is ctx

    def test_planner_routes_any_to_l1(self, tmp_path: Any) -> None:
        planner, mocks = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="any", slice_id="slice-any")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)
        assert result.status == "OK"
        assert mocks["l1"].last_ctx is ctx

    def test_planner_plan_returns_trace_id(self, tmp_path: Any) -> None:
        planner, _ = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="l1")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)
        assert result.trace_id != ""
        assert len(result.trace_id) == 12  # uuid hex[:12]

    def test_planner_error_handling(self, tmp_path: Any) -> None:
        planner = Planner(workspace_root=tmp_path, register_defaults=False)

        class _RaisingPlanner(_MockLayerPlanner):
            def discover(self, ctx: Any) -> dict[str, Any]:
                raise RuntimeError("boom")

        planner.register_layer_planner("l1", _RaisingPlanner("l1"))
        ctx = PlanningContext(layer="l1")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)
        assert result.status == "ERROR"
        assert "boom" in result.error
        assert result.trace_id != ""


# ---------------------------------------------------------------------------
# Planner convenience methods
# ---------------------------------------------------------------------------


class TestPlannerConvenience:
    def _make_planner(self, tmp_path: Any) -> Planner:
        planner = Planner(workspace_root=tmp_path, register_defaults=False)
        planner.register_layer_planner("l1", _MockLayerPlanner("l1"))
        planner.register_layer_planner("l2", _MockLayerPlanner("l2"))
        planner.register_layer_planner("l3", _MockLayerPlanner("l3"))
        return planner

    def test_planner_resolve_signal(self, tmp_path: Any) -> None:
        planner = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="l1")
        response = planner.resolve_signal({"target": "foo"}, ctx)
        assert response is not None
        assert response["resolved"] is True

    def test_planner_resolve_signal_none(self, tmp_path: Any) -> None:
        planner = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="l1")
        response = planner.resolve_signal(None, ctx)
        assert response is None

    def test_planner_plan_from_gaps(self, tmp_path: Any) -> None:
        planner = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="l1")
        gaps = [{"target": "f1", "description": "missing impl"}]
        intentions = planner.plan_from_gaps(ctx, gaps)
        assert isinstance(intentions, list)
        # The mock build_plan returns [{"from": "l1"}]
        assert len(intentions) == 1
        assert intentions[0]["from"] == "l1"

    def test_planner_resolve_under_spec(self, tmp_path: Any) -> None:
        planner = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="l2")
        events = [{"target": "comp-A", "question": "what scope?"}]
        result = planner.resolve_under_spec(ctx, events)
        assert isinstance(result, dict)
        assert result["blocked"] is False


# ---------------------------------------------------------------------------
# Planner UserQuestionSignal emission
# ---------------------------------------------------------------------------


class TestPlannerUserQuestionSignals:
    def test_plan_emits_signal_via_callback_for_human_required_events(self, tmp_path: Any) -> None:
        captured: list[Any] = []
        planner = Planner(
            workspace_root=tmp_path,
            register_defaults=False,
            on_user_question_signal=captured.append,
        )
        planner.register_layer_planner("l2", _HumanRequiredPlanLayerPlanner("l2"))

        ctx = PlanningContext(
            layer="l2",
            run_id="run-callback",
            slice_id="slice-123",
        )
        intentions = planner.plan_from_gaps(ctx, gaps=[{"target": "component-x"}])

        assert intentions == [{"from": "l2"}]
        assert len(captured) == 1
        signal = captured[0]
        assert signal["run_id"] == "run-callback"
        assert signal["source"]["kind"] == "PLANNER"
        assert signal["source"]["slice_id"] == "slice-123"
        assert signal["source"]["layer"] == "l2"
        assert signal["source"]["signal_id"] == "DR-001"
        assert signal["question"]["text"] == "What SLA should we guarantee?"
        assert signal["question"]["canonical_key_hint"] == "planner.decision_required.DR-001"
        assert signal["context"]["blocking"]["severity"] == "BLOCKING"
        assert signal["context"]["blocking"]["blocked_slices"] == ["slice-123"]
        assert signal["payload"]["decision_id"] == "DR-001"

    def test_plan_emits_signal_to_store_when_no_callback(self, tmp_path: Any) -> None:
        planner = Planner(workspace_root=tmp_path, register_defaults=False)
        planner.register_layer_planner("l2", _HumanRequiredPlanLayerPlanner("l2"))

        ctx = PlanningContext(
            layer="l2",
            run_id="run-store",
            slice_id="slice-456",
        )
        planner.plan_from_gaps(ctx, gaps=[{"target": "component-y"}])

        path = tmp_path / ".pdd_runs" / "run-store" / "coordination" / "user_questions.jsonl"
        assert path.exists()
        signals = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line
        ]

        assert len(signals) == 1
        assert signals[0]["source"]["kind"] == "PLANNER"
        assert signals[0]["question"]["text"] == "What SLA should we guarantee?"

    def test_plan_does_not_emit_for_non_human_required_events(self, tmp_path: Any) -> None:
        class _NonHumanPlanLayerPlanner(_MockLayerPlanner):
            def build_plan(
                self, ctx: Any, gaps: list[dict[str, Any]], discovery: dict[str, Any]
            ) -> dict[str, Any]:
                self.last_ctx = ctx
                return {
                    "intentions": [{"from": self.layer}],
                    "under_spec_events": [
                        {
                            "type": "architecture_blocked",
                            "question": "What is the deployment topology?",
                            "reason": "topology evidence missing",
                        }
                    ],
                }

        captured: list[Any] = []
        planner = Planner(
            workspace_root=tmp_path,
            register_defaults=False,
            on_user_question_signal=captured.append,
        )
        planner.register_layer_planner("l2", _NonHumanPlanLayerPlanner("l2"))

        ctx = PlanningContext(
            layer="l2",
            run_id="run-noemit",
            slice_id="slice-789",
        )
        planner.plan_from_gaps(ctx, gaps=[{"target": "component-z"}])

        assert captured == []


# ---------------------------------------------------------------------------
# Planner answer ingest authority policy
# ---------------------------------------------------------------------------


class TestPlannerIngestAuthorityPolicy:
    def test_policy_user_answer_is_authoritative(self) -> None:
        decision = _planner_ingest_authority_policy(
            {"source": "user", "canonical_key_hint": "payments.timeout"}
        )
        assert decision.authoritative is True
        assert decision.reason == "user_answer_authoritative"

    def test_policy_planner_enrichment_requires_source_or_approval(self) -> None:
        decision = _planner_ingest_authority_policy(
            {"source": "planner_enrichment", "canonical_key_hint": "payments.timeout"}
        )
        assert decision.authoritative is False
        assert decision.reason == "planner_enrichment_requires_source_or_approval"

    def test_policy_planner_enrichment_becomes_authoritative_with_sources(self) -> None:
        decision = _planner_ingest_authority_policy(
            {
                "source": "planner_enrichment",
                "canonical_key_hint": "payments.timeout",
                "sources": ["spec.md#timeouts"],
            }
        )
        assert decision.authoritative is True
        assert decision.reason == "planner_enrichment_sourced_or_approved"

    def test_ingest_user_answer_applies_policy_branching(self, tmp_path: Any) -> None:
        planner = Planner(workspace_root=tmp_path, register_defaults=False)
        translation = {
            "run_id": "run-auth",
            "question_id": "Q-100",
            "translation_id": "at-100",
            "provenance": {"produced_by": "INTENT_AGENT"},
            "extracted": {
                "constraint_candidates": [
                    {
                        "canonical_key_hint": "checkout.currency",
                        "question": "Which currency?",
                        "answer": "USD",
                    },
                    {
                        "canonical_key_hint": "checkout.timeout",
                        "question": "Timeout?",
                        "answer": "30s",
                        "source": "planner_enrichment",
                    },
                    {
                        "canonical_key_hint": "checkout.retry_policy",
                        "question": "Retry policy?",
                        "answer": "3 retries",
                        "source": "planner_enrichment",
                        "approved_by_user": True,
                    },
                ],
            },
        }

        result = planner.ingest_user_answer(translation)

        assert result.status == "OK"
        authoritative = result.outputs["authoritative_candidates"]
        non_authoritative = result.outputs["non_authoritative_candidates"]
        rejected = result.outputs["rejected_candidates"]

        auth_keys = {entry["candidate"]["canonical_key_hint"] for entry in authoritative}
        non_auth_keys = {entry["candidate"]["canonical_key_hint"] for entry in non_authoritative}
        assert auth_keys == {"checkout.currency", "checkout.retry_policy"}
        assert non_auth_keys == {"checkout.timeout"}
        assert rejected == []

    def test_ingest_user_answer_rejects_taxonomy_domain_mismatches(self, tmp_path: Any) -> None:
        planner = Planner(workspace_root=tmp_path, register_defaults=False)
        translation = {
            "run_id": "run-taxonomy",
            "question_id": "Q-200",
            "translation_id": "at-200",
            "provenance": {"produced_by": "INTENT_AGENT"},
            "extracted": {
                "constraint_candidates": [
                    {
                        "canonical_key_hint": "checkout.currency",
                        "question": "Which currency?",
                        "answer": "USD",
                        "dimension": "constraint",
                    },
                    {
                        "canonical_key_hint": "checkout.timeout",
                        "question": "Timeout?",
                        "answer": "30s",
                        "dimension": "tradeoff",
                    },
                ],
                "scope_candidates": [
                    {
                        "scope_in": ["Checkout flow"],
                        "scope_out": ["Legacy admin panel"],
                        "taxonomy_hint": "scope",
                    },
                    {
                        "scope_in": ["Billing reports"],
                        "scope_out": [],
                        "taxonomy_type": "validation",
                    },
                ],
                "validation_candidates": [
                    {
                        "acceptance_statement": "P95 checkout latency < 200ms",
                        "dimension": "unknown",
                    }
                ],
            },
        }

        result = planner.ingest_user_answer(translation)

        assert result.status == "OK"
        authoritative = result.outputs["authoritative_candidates"]
        rejected = result.outputs["rejected_candidates"]

        assert len(authoritative) == 2
        assert len(rejected) == 3
        assert any(
            entry["reason"].startswith(
                "taxonomy_domain_mismatch:dimension:tradeoff;expected=constraint"
            )
            for entry in rejected
        )
        assert any(
            entry["reason"].startswith(
                "taxonomy_domain_mismatch:taxonomy_type:validation;expected=scope"
            )
            for entry in rejected
        )
        assert any(
            entry["reason"].startswith("invalid_taxonomy_domain:dimension:unknown;allowed=")
            for entry in rejected
        )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestPlannerRegistration:
    def test_planner_register_custom_planner(self, tmp_path: Any) -> None:
        planner = Planner(workspace_root=tmp_path, register_defaults=False)
        custom = _MockLayerPlanner("l2")
        planner.register_layer_planner("l2", custom)
        ctx = PlanningContext(layer="l2")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)
        assert result.status == "OK"
        assert custom.last_ctx is ctx

    def test_planner_register_defaults(self, tmp_path: Any) -> None:
        planner = Planner(workspace_root=tmp_path, register_defaults=True)
        # Verify that L1/L2/L3 planners are registered by routing to each
        for layer in ("l1", "l2", "l3"):
            ctx = PlanningContext(layer=layer)
            req = PlanningRequest(capability="GAP", context=ctx)
            result = planner.plan(req)
            assert result.status == "OK"

    def test_planner_has_constraints_adapter(self, tmp_path: Any) -> None:
        """Planner creates a ConstraintStoreAdapter in __init__."""
        from spec_manager.planner.constraints.store_adapter import ConstraintStoreAdapter

        planner = Planner(workspace_root=tmp_path, register_defaults=False)
        assert isinstance(planner._constraints_adapter, ConstraintStoreAdapter)


# ---------------------------------------------------------------------------
# Override provider
# ---------------------------------------------------------------------------


class TestPlannerOverrideProvider:
    def _make_planner(
        self,
        tmp_path: Path,
        override_provider: Any,
    ) -> Planner:
        """Build a Planner with an override_provider and mock layer planners."""
        planner = Planner(
            workspace_root=tmp_path,
            register_defaults=False,
            override_provider=override_provider,
        )
        planner.register_layer_planner("l1", _MockLayerPlanner("l1"))
        return planner

    def test_override_provider_returns_result_bypasses_routing(self, tmp_path: Path) -> None:
        """When override_provider returns a PlanningResult, routing is bypassed."""
        override_result = PlanningResult(
            status="OK",
            outputs={"overridden": True},
        )

        def provider(req: PlanningRequest) -> PlanningResult | None:
            return override_result

        planner = self._make_planner(tmp_path, provider)
        ctx = PlanningContext(layer="l1", slice_id="s1")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)

        assert result.status == "OK"
        assert result.outputs == {"overridden": True}

    def test_override_provider_returns_none_proceeds_normally(self, tmp_path: Path) -> None:
        """When override_provider returns None, normal routing proceeds."""

        def provider(req: PlanningRequest) -> PlanningResult | None:
            return None

        planner = self._make_planner(tmp_path, provider)
        ctx = PlanningContext(layer="l1", slice_id="s1")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)

        # Should succeed through normal routing to _MockLayerPlanner
        assert result.status == "OK"

    def test_override_result_has_trace_id_set(self, tmp_path: Path) -> None:
        """Overridden results get a trace_id assigned."""
        override_result = PlanningResult(status="OK", outputs={})

        def provider(req: PlanningRequest) -> PlanningResult | None:
            return override_result

        planner = self._make_planner(tmp_path, provider)
        ctx = PlanningContext(layer="l1")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)

        assert result.trace_id != ""
        assert len(result.trace_id) == 12


# ---------------------------------------------------------------------------
# Planner model_id
# ---------------------------------------------------------------------------


class TestPlannerModelId:
    def test_planner_constructor_accepts_model_id(self, tmp_path: Path) -> None:
        """Planner can be constructed with model_id keyword."""
        planner = Planner(
            workspace_root=tmp_path,
            register_defaults=False,
            model_id="opus-4",
        )
        assert planner._model_id == "opus-4"

    def test_model_id_flows_through_to_traces(self, tmp_path: Path) -> None:
        """model_id set on Planner propagates into persisted trace data."""
        planner = Planner(
            workspace_root=tmp_path,
            register_defaults=False,
            model_id="sonnet-5",
        )
        planner.register_layer_planner("l1", _MockLayerPlanner("l1"))
        ctx = PlanningContext(layer="l1", slice_id="slice-m")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)

        # Verify model_id in persisted replay.json
        trace_dir = tmp_path / "analysis" / "planner_traces" / result.trace_id
        replay_path = trace_dir / "replay.json"
        assert replay_path.exists()
        replay_data = json.loads(replay_path.read_text(encoding="utf-8"))
        assert replay_data["model_id"] == "sonnet-5"


# ---------------------------------------------------------------------------
# Auto-persist on success / error
# ---------------------------------------------------------------------------


class TestPlannerAutoPersist:
    def test_plan_persists_trace_on_success(self, tmp_path: Path) -> None:
        """plan() persists a trace directory on successful invocation."""
        planner = Planner(workspace_root=tmp_path, register_defaults=False)
        planner.register_layer_planner("l1", _MockLayerPlanner("l1"))

        ctx = PlanningContext(layer="l1", slice_id="s1")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)

        trace_dir = tmp_path / "analysis" / "planner_traces" / result.trace_id
        assert trace_dir.exists()
        assert (trace_dir / "replay.json").exists()

    def test_plan_persists_trace_on_error(self, tmp_path: Path) -> None:
        """plan() persists a trace even when the layer planner raises."""

        class _RaisingPlanner(_MockLayerPlanner):
            def discover(self, ctx: Any) -> dict[str, Any]:
                raise RuntimeError("deliberate error")

        planner = Planner(workspace_root=tmp_path, register_defaults=False)
        planner.register_layer_planner("l1", _RaisingPlanner("l1"))

        ctx = PlanningContext(layer="l1", slice_id="s-err")
        req = PlanningRequest(capability="GAP", context=ctx)
        result = planner.plan(req)

        assert result.status == "ERROR"
        assert "deliberate error" in result.error

        trace_dir = tmp_path / "analysis" / "planner_traces" / result.trace_id
        assert trace_dir.exists()
        assert (trace_dir / "replay.json").exists()

        # Verify the persisted trace records the error status
        replay_data = json.loads((trace_dir / "replay.json").read_text(encoding="utf-8"))
        assert replay_data["status"] == "ERROR"


# ---------------------------------------------------------------------------
# _request_snapshot
# ---------------------------------------------------------------------------


class TestRequestSnapshot:
    def test_captures_all_expected_fields(self) -> None:
        """_request_snapshot() includes capability, layer, run_id, slice_id, etc."""
        ctx = PlanningContext(
            layer="l2",
            run_id="run-42",
            slice_id="slice-x",
            iteration=3,
            mode="auto",
            workspace_root="/ws",
            slice_root="/ws/slice-x",
        )
        req = PlanningRequest(
            capability="PLAN",
            context=ctx,
            inputs={"gaps": [], "extra": "val"},
            constraints_hint={"max_depth": 5},
        )
        snap = _request_snapshot(req)

        assert snap["capability"] == "PLAN"
        assert snap["layer"] == "l2"
        assert snap["run_id"] == "run-42"
        assert snap["slice_id"] == "slice-x"
        assert snap["iteration"] == 3
        assert snap["mode"] == "auto"
        assert sorted(snap["inputs_keys"]) == ["extra", "gaps"]
        assert snap["has_constraints_hint"] is True

    def test_inputs_keys_sorted(self) -> None:
        """inputs_keys in the snapshot are sorted."""
        ctx = PlanningContext(layer="l1")
        req = PlanningRequest(
            capability="GAP",
            context=ctx,
            inputs={"z_key": 1, "a_key": 2, "m_key": 3},
        )
        snap = _request_snapshot(req)
        assert snap["inputs_keys"] == ["a_key", "m_key", "z_key"]

    def test_no_constraints_hint(self) -> None:
        """has_constraints_hint is False when constraints_hint is None."""
        ctx = PlanningContext(layer="l1")
        req = PlanningRequest(capability="GAP", context=ctx)
        snap = _request_snapshot(req)
        assert snap["has_constraints_hint"] is False


# ---------------------------------------------------------------------------
# TRIAGE_SIGNAL capability
# ---------------------------------------------------------------------------


class TestPlannerTriageSignal:
    def _make_planner(self, tmp_path: Any) -> tuple[Planner, dict[str, _MockLayerPlanner]]:
        planner = Planner(workspace_root=tmp_path, register_defaults=False)
        mocks: dict[str, _MockLayerPlanner] = {}
        for layer in ("l1", "l2", "l3"):
            mock = _MockLayerPlanner(layer)
            planner.register_layer_planner(layer, mock)
            mocks[layer] = mock
        return planner, mocks

    def test_triage_signal_routes_to_correct_layer(self, tmp_path: Any) -> None:
        """triage_signal convenience method routes through plan() to the layer planner."""
        planner, mocks = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="l1", slice_id="slice-triage")
        signal = {"need": {"artifact_key": "foo"}, "spec_refs": []}
        result = planner.triage_signal(ctx, signal)
        # _MockLayerPlanner.triage_signal returns NOOP
        assert result.status == "NOOP"
        assert result.outputs["action"] == "NOOP"
        assert mocks["l1"].last_ctx is ctx

    def test_triage_signal_returns_waiting_on_non_noop(self, tmp_path: Any) -> None:
        """When the layer planner returns a non-NOOP action, status is WAITING."""
        planner = Planner(workspace_root=tmp_path, register_defaults=False)

        class _WaitingPlanner(_MockLayerPlanner):
            def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
                return {"action": "WAIT_ON_WORK_ITEM", "monitors": [{"kind": "test"}]}

        planner.register_layer_planner("l1", _WaitingPlanner("l1"))
        ctx = PlanningContext(layer="l1", slice_id="slice-wait")
        result = planner.triage_signal(ctx, {"need": {}})
        assert result.status == "WAITING"
        assert result.outputs["action"] == "WAIT_ON_WORK_ITEM"

    def test_triage_signal_has_trace_id(self, tmp_path: Any) -> None:
        """triage_signal results always have a trace_id."""
        planner, _ = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="l1")
        result = planner.triage_signal(ctx, {"need": {}})
        assert result.trace_id != ""
        assert len(result.trace_id) == 12

    def test_triage_signal_routes_l2(self, tmp_path: Any) -> None:
        """triage_signal with layer=l2 routes to L2 planner."""
        planner, mocks = self._make_planner(tmp_path)
        ctx = PlanningContext(layer="l2", slice_id="slice-l2")
        result = planner.triage_signal(ctx, {"need": {}})
        assert result.status == "NOOP"
        assert mocks["l2"].last_ctx is ctx
