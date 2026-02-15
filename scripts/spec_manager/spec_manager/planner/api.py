"""Core types and Planner API for the planning module.

Defines the public data types (PlanningContext, PlanningRequest,
PlanningResult) and the Planner class that serves as the single
auto-mode decision authority.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from spec_manager.planner.router import CapabilityRouter, LayerRouter

logger = logging.getLogger(__name__)
PLANNER_VERSION = "1"
_VALID_INGEST_TAXONOMY = frozenset({"INTENT", "CONSTRAINT", "TRADEOFF", "SCOPE", "VALIDATION"})
_VALID_UNDER_SPEC_DIMENSIONS = frozenset(
    {"software", "legal", "economic", "organizational", "temporal", "operational"}
)
_VALID_UNDER_SPEC_DECISION_TYPES = frozenset(
    {"dependency", "infrastructure", "data_policy", "security", "performance", "architecture"}
)

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Layer = Literal["l1", "l2", "l3", "any"]
Capability = Literal[
    "RESOLVE_SIGNAL",  # interactive refinement + under-spec questions
    "GAP",  # gap understanding / clustering / prioritization
    "PLAN",  # plan synthesis (intentions / wiring / refactor)
    "UNDER_SPEC",  # resolve or block; produce constraints + routing + monitors
    "INTEGRATION_ANALYSIS",
    "TRIAGE_SIGNAL",  # reactive triage of coordination signals
    "INGEST_USER_ANSWER",  # planner-mediated answer ingestion
]


# ---------------------------------------------------------------------------
# Core data types
# ---------------------------------------------------------------------------


@dataclass
class PlanningContext:
    """Per-request context passed through all planner operations."""

    run_id: str = ""
    slice_id: str = ""
    iteration: int = 0
    layer: Layer = "any"
    mode: Literal["auto", "interactive"] = "auto"
    workspace_root: str = ""
    slice_root: str = ""
    bundle_ref: Any = None  # EvidenceBundle or lightweight view
    signal_ref: Any = None  # InputSignal or Ambiguity
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanningRequest:
    """A typed request dispatched to the planner."""

    capability: Capability
    context: PlanningContext
    inputs: dict[str, Any] = field(default_factory=dict)
    constraints_hint: dict[str, Any] | None = None


@dataclass
class PlanningResult:
    """Outcome of a planner invocation."""

    status: Literal["OK", "BLOCKED", "NEEDS_INPUT", "NOOP", "ERROR", "WAITING"]
    outputs: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class Planner:
    """Single auto-mode decision authority across the spec manager lifecycle.

    Routes each ``PlanningRequest`` to the appropriate layer planner
    (L1/L2/L3) via a ``LayerRouter``, then dispatches by capability
    through a ``CapabilityRouter``.  Every invocation is tagged with a
    trace id for observability.

    If *register_defaults* is True (the default), real L1/L2/L3 planners
    are registered automatically.  Pass False and call
    ``register_layer_planner`` manually for testing.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        mode: str = "auto",
        *,
        register_defaults: bool = True,
        research_tool: Any = None,
        integration_tool: Any = None,
        evidence_tool: Any = None,
        constraints_tool: Any = None,
        override_provider: Callable[[PlanningRequest], PlanningResult | None] | None = None,
        model_id: str = "",
        work_item_store: Any = None,
        wait_graph: Any = None,
        on_constraint_saved: Callable | None = None,
        on_decision_recorded: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._workspace_root = Path(workspace_root)
        self._mode = mode
        self._model_id = model_id
        self._constraints_tool = constraints_tool
        self._layer_router = LayerRouter()
        self._capability_router = CapabilityRouter()
        self._override_provider = override_provider
        self._work_item_store = work_item_store
        self._wait_graph = wait_graph
        self._on_decision_recorded = on_decision_recorded

        # Build a shared ConstraintStoreAdapter for L1/L2 planners
        from spec_manager.planner.constraints.store_adapter import ConstraintStoreAdapter

        self._constraints_adapter = ConstraintStoreAdapter(
            self._workspace_root,
            on_constraint_saved=on_constraint_saved,
        )

        if register_defaults:
            self._register_default_planners(
                research_tool=research_tool,
                integration_tool=integration_tool,
                evidence_tool=evidence_tool,
                constraints_tool=constraints_tool,
            )

    def _register_default_planners(
        self,
        research_tool: Any = None,
        integration_tool: Any = None,
        evidence_tool: Any = None,
        constraints_tool: Any = None,
    ) -> None:
        """Register real L1/L2/L3 planners with injected tools."""
        from spec_manager.planner.layers.l1 import L1Planner
        from spec_manager.planner.layers.l2 import L2Planner
        from spec_manager.planner.layers.l3 import L3Planner

        self._layer_router.register(
            "l1",
            L1Planner(
                research_tool=research_tool,
                integration_tool=integration_tool,
                evidence_tool=evidence_tool,
                constraints_tool=constraints_tool,
                constraints_store_adapter=self._constraints_adapter,
            ),
        )
        self._layer_router.register(
            "l2",
            L2Planner(
                research_tool=research_tool,
                integration_tool=integration_tool,
                evidence_tool=evidence_tool,
                constraints_tool=constraints_tool,
                constraints_store_adapter=self._constraints_adapter,
                work_item_store=self._work_item_store,
                wait_graph=self._wait_graph,
            ),
        )
        self._layer_router.register(
            "l3",
            L3Planner(
                research_tool=research_tool,
                integration_tool=integration_tool,
                evidence_tool=evidence_tool,
                constraints_tool=constraints_tool,
            ),
        )

    def register_layer_planner(self, layer: str, planner: Any) -> None:
        """Register a custom planner for a layer (useful for testing)."""
        self._layer_router.register(layer, planner)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def plan(self, req: PlanningRequest) -> PlanningResult:
        """Route *req* to the correct layer planner and capability handler.

        Returns a ``PlanningResult`` with a unique ``trace_id`` for
        every invocation regardless of outcome.  Every call persists a
        trace (including errors) and appends to ``index.jsonl``.
        """
        from spec_manager.planner.trace import (
            DecisionRecord,
            ModelCallRecord,
            PlannerTrace,
            ToolCallRecord,
            canonical_json,
            compute_decision_key,
            compute_input_hash,
            content_hash,
        )

        trace_id = _new_trace_id()
        layer = req.context.layer
        ctx = req.context

        decision_key = compute_decision_key(
            layer=str(layer),
            capability=req.capability,
            slice_id=ctx.slice_id,
            iteration=ctx.iteration,
            inputs=req.inputs,
        )
        input_hash = compute_input_hash(req.capability, req.inputs)

        trace = PlannerTrace.start(
            trace_id,
            _request_snapshot(
                req,
                input_hash=input_hash,
                decision_key=decision_key,
                model_id=self._model_id,
                planner_version=PLANNER_VERSION,
            ),
            decision_key=decision_key,
            run_id=ctx.run_id,
            model_id=self._model_id,
            planner_version=PLANNER_VERSION,
            layer=str(layer),
            capability=req.capability,
            slice_id=ctx.slice_id,
        )

        logger.debug(
            "planner.plan  trace=%s  key=%s  capability=%s  layer=%s  slice=%s",
            trace_id,
            decision_key,
            req.capability,
            layer,
            ctx.slice_id,
        )

        from spec_manager.planner.constraints.store_adapter import ConstraintStoreAdapter

        context_token = ConstraintStoreAdapter.push_planner_update_context(
            run_id=ctx.run_id,
            layer=str(layer),
            capability=req.capability,
        )
        try:
            # Override hook (for counterfactual testing / ground truth injection)
            if self._override_provider is not None:
                override_result = self._override_provider(req)
                if override_result is not None:
                    override_result.trace_id = trace_id
                    trace.status = override_result.status
                    trace.overridden = True
                    trace.set_decision(
                        DecisionRecord(
                            decision_text=f"OVERRIDDEN: {override_result.status}",
                        )
                    )
                    trace.add_artifact("override_outputs", override_result.outputs)
                    self._persist_trace(trace)
                    self._emit_decision_recorded_event(
                        trace=trace,
                        context=ctx,
                        capability=req.capability,
                        decision_key=decision_key,
                        outputs=override_result.outputs,
                    )
                    return override_result

            route_start = time.perf_counter()
            if req.capability == "INGEST_USER_ANSWER":
                result = self._handle_ingest_user_answer(req)
            else:
                planner = self._layer_router.select(layer)
                result = self._capability_router.route(planner, req)
            duration_ms = (time.perf_counter() - route_start) * 1000.0
            result.trace_id = trace_id
            trace.status = result.status
            outputs_payload = result.outputs if isinstance(result.outputs, dict) else {}
            decision_text = str(outputs_payload.get("decision_text", "")).strip() or result.status
            trace.set_decision(DecisionRecord(decision_text=decision_text))
            trace.add_artifact("outputs", result.outputs)
            usage_tokens = _extract_tokens(result.outputs)
            trace.record_model_call(
                ModelCallRecord(
                    agent_name=f"{str(layer).lower()}:{req.capability}",
                    model=self._model_id,
                    duration_ms=duration_ms,
                    tokens_in=usage_tokens[0],
                    tokens_out=usage_tokens[1],
                    model_params={
                        "mode": self._mode,
                        "capability": req.capability,
                        "layer": str(layer),
                        "planner_version": PLANNER_VERSION,
                    },
                    prompt_text=canonical_json(req.inputs),
                    response_text=canonical_json(result.outputs),
                )
            )
            trace.record_tool_call(
                ToolCallRecord(
                    tool_name=f"planner.route.{str(req.capability).lower()}",
                    inputs_hash=content_hash(canonical_json(req.inputs)),
                    output_summary=result.status,
                    duration_ms=duration_ms,
                    tokens_in=usage_tokens[0],
                    tokens_out=usage_tokens[1],
                    tool_params={"layer": str(layer)},
                )
            )
            self._persist_trace(trace)
            self._emit_decision_recorded_event(
                trace=trace,
                context=ctx,
                capability=req.capability,
                decision_key=decision_key,
                outputs=result.outputs,
            )
            return result
        except Exception as exc:
            logger.exception("planner.plan failed  trace=%s", trace_id)
            result = PlanningResult(
                status="ERROR",
                trace_id=trace_id,
                error=str(exc),
            )
            trace.status = "ERROR"
            trace.set_decision(
                DecisionRecord(
                    decision_text=f"ERROR: {exc}",
                )
            )
            self._persist_trace(trace)
            self._emit_decision_recorded_event(
                trace=trace,
                context=ctx,
                capability=req.capability,
                decision_key=decision_key,
                outputs={},
            )
            return result
        finally:
            ConstraintStoreAdapter.pop_planner_update_context(context_token)

    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return False

    @staticmethod
    def _coerce_id_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            text = value.strip()
            return [text] if text else []
        if isinstance(value, (list, tuple, set)):
            ids: list[str] = []
            for item in value:
                text = str(item).strip()
                if text:
                    ids.append(text)
            return ids
        return []

    @staticmethod
    def _dedupe_preserve(items: list[str]) -> list[str]:
        seen: set[str] = set()
        deduped: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    @staticmethod
    def _extract_decision_requirements(outputs: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract decision requirements from top-level and intention payloads."""
        requirements: list[dict[str, Any]] = []

        top_level = outputs.get("decision_requirements")
        if isinstance(top_level, list):
            for requirement in top_level:
                if isinstance(requirement, dict):
                    requirements.append(requirement)

        intentions = outputs.get("intentions")
        if isinstance(intentions, list):
            for intention in intentions:
                if not isinstance(intention, dict):
                    continue
                embedded_requirements = intention.get("decision_requirements", [])
                if not isinstance(embedded_requirements, list):
                    continue
                for requirement in embedded_requirements:
                    if isinstance(requirement, dict):
                        requirements.append(requirement)

        return requirements

    @staticmethod
    def _extract_update_identifiers(
        outputs: dict[str, Any],
    ) -> tuple[list[str], list[str], list[str]]:
        decision_ids = Planner._coerce_id_list(outputs.get("decision_ids"))
        decision_ids.extend(Planner._coerce_id_list(outputs.get("decision_id")))
        constraint_ids = Planner._coerce_id_list(outputs.get("constraint_ids"))
        constraint_ids.extend(Planner._coerce_id_list(outputs.get("constraint_id")))
        canonical_keys = Planner._coerce_id_list(outputs.get("canonical_keys"))
        canonical_keys.extend(Planner._coerce_id_list(outputs.get("canonical_key")))

        under_spec_events = outputs.get("under_spec_events")
        if isinstance(under_spec_events, list):
            for event in under_spec_events:
                if not isinstance(event, dict):
                    continue
                decision_ids.extend(Planner._coerce_id_list(event.get("decision_id")))
                decision_ids.extend(Planner._coerce_id_list(event.get("decision_ids")))
                constraint_ids.extend(Planner._coerce_id_list(event.get("constraint_id")))
                constraint_ids.extend(Planner._coerce_id_list(event.get("constraint_ids")))
                canonical_keys.extend(Planner._coerce_id_list(event.get("canonical_key")))
                canonical_keys.extend(Planner._coerce_id_list(event.get("canonical_keys")))

        for requirement in Planner._extract_decision_requirements(outputs):
            decision_ids.extend(Planner._coerce_id_list(requirement.get("decision_id")))
            decision_ids.extend(Planner._coerce_id_list(requirement.get("decision_ids")))
            canonical_keys.extend(Planner._coerce_id_list(requirement.get("canonical_key")))
            canonical_keys.extend(Planner._coerce_id_list(requirement.get("canonical_keys")))

        return (
            Planner._dedupe_preserve(decision_ids),
            Planner._dedupe_preserve(constraint_ids),
            Planner._dedupe_preserve(canonical_keys),
        )

    @staticmethod
    def _extract_review_questions(outputs: dict[str, Any]) -> list[dict[str, Any]]:
        review_questions: list[dict[str, Any]] = []

        for requirement in Planner._extract_decision_requirements(outputs):
            requirement_authority = str(requirement.get("authority_required", "")).strip().lower()
            if requirement_authority not in {"human_required", "user_required"}:
                continue
            question_text = (
                str(
                    requirement.get("question")
                    or requirement.get("user_question")
                    or requirement.get("question_text")
                    or "",
                ).strip()
                or "Planner requires user authority for a decision."
            )
            reason = (
                str(requirement.get("reason", "")).strip()
                or f"authority_required={requirement_authority}"
            )
            payload: dict[str, Any] = {}
            requirement_ids = Planner._coerce_id_list(requirement.get("decision_requirement_id"))
            requirement_ids.extend(
                Planner._coerce_id_list(requirement.get("decision_requirement_ids"))
            )
            requirement_ids.extend(Planner._coerce_id_list(requirement.get("requirement_id")))
            requirement_ids.extend(Planner._coerce_id_list(requirement.get("requirement_ids")))
            requirement_ids = Planner._dedupe_preserve(requirement_ids)
            if requirement_ids:
                payload["decision_requirement_ids"] = requirement_ids
            requirement_decision_ids = Planner._coerce_id_list(requirement.get("decision_id"))
            requirement_decision_ids.extend(
                Planner._coerce_id_list(requirement.get("decision_ids"))
            )
            requirement_decision_ids = Planner._dedupe_preserve(requirement_decision_ids)
            if requirement_decision_ids:
                payload["decision_ids"] = requirement_decision_ids
            requirement_canonical_keys = Planner._coerce_id_list(requirement.get("canonical_key"))
            requirement_canonical_keys.extend(
                Planner._coerce_id_list(requirement.get("canonical_keys"))
            )
            requirement_canonical_keys = Planner._dedupe_preserve(requirement_canonical_keys)
            if requirement_canonical_keys:
                payload["canonical_keys"] = requirement_canonical_keys
            review_questions.append(
                {
                    "question_text": question_text,
                    "reason": reason,
                    "payload": payload,
                }
            )

        under_spec_events = outputs.get("under_spec_events")
        if isinstance(under_spec_events, list):
            for event in under_spec_events:
                if not isinstance(event, dict):
                    continue
                event_type = str(event.get("type", "")).strip().lower()
                event_authority = str(event.get("authority_required", "")).strip().lower()
                if event_type not in {
                    "authority_required",
                    "decision_required",
                } and event_authority not in {
                    "human_required",
                    "user_required",
                }:
                    continue
                question_text = str(event.get("question", "")).strip()
                if not question_text:
                    question_text = "Planner requires user authority for an under-spec decision."
                reason = str(event.get("reason", "")).strip() or "human authority required"
                payload: dict[str, Any] = {}
                under_spec_event_id = str(event.get("event_id", "")).strip()
                if under_spec_event_id:
                    payload["under_spec_event_id"] = under_spec_event_id
                review_questions.append(
                    {
                        "question_text": question_text,
                        "reason": reason,
                        "payload": payload,
                    }
                )

        explicit_flags = (
            "review_required",
            "requires_review",
            "needs_review",
            "needs_human_review",
            "human_authority_required",
        )
        authority_required = str(outputs.get("authority_required", "")).strip().lower()
        authority_payload = outputs.get("authority")
        if not authority_required and isinstance(authority_payload, dict):
            authority_required = (
                str(
                    authority_payload.get(
                        "required", authority_payload.get("authority_required", "")
                    ),
                )
                .strip()
                .lower()
            )
        if review_questions:
            return review_questions

        review_required = any(Planner._coerce_bool(outputs.get(flag)) for flag in explicit_flags)
        if not review_required and authority_required in {"human_required", "user_required"}:
            review_required = True
        if not review_required:
            return []

        question_text = ""
        for key in ("review_question_text", "user_question", "question"):
            candidate = str(outputs.get(key, "")).strip()
            if candidate:
                question_text = candidate
                break
        if not question_text:
            question_text = "Planner reached a decision that requires user authority review."

        reason = str(outputs.get("review_reason", "")).strip()
        if not reason:
            if authority_required in {"human_required", "user_required"}:
                reason = f"authority_required={authority_required}"
            else:
                reason = "planner flagged review_required"

        return [
            {
                "question_text": question_text,
                "reason": reason,
                "payload": {},
            }
        ]

    @staticmethod
    def _build_review_signal_payload(
        *,
        run_id: str,
        trace_id: str,
        slice_id: str,
        layer: str,
        decision_key: str,
        canonical_keys: list[str],
        decision_ids: list[str],
        constraint_ids: list[str],
        signal_sequence: int,
        question_text: str,
        reason: str,
        extra_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if trace_id:
            signal_id = f"{trace_id}:review:{signal_sequence}"
        else:
            signal_id = f"planner-review-{uuid.uuid4().hex[:12]}"
        token = re.sub(r"[^a-zA-Z0-9._-]+", "_", decision_key or signal_id).strip("._-")
        canonical_key_hint = f"planner.review.{token}" if token else "planner.review"
        payload = {
            "event_kind": "decision_review_required",
            "reason": reason,
            "decision_key": decision_key,
            "decision_ids": list(decision_ids),
            "constraint_ids": list(constraint_ids),
            "canonical_keys": list(canonical_keys),
        }
        if extra_payload:
            payload.update(extra_payload)
        return {
            "uq_version": 1,
            "uq_id": f"uq_{uuid.uuid4().hex[:12]}",
            "run_id": run_id,
            "created_at": datetime.now(UTC).isoformat(),
            "source": {
                "kind": "PLANNER",
                "trace_id": trace_id,
                "slice_id": slice_id,
                "layer": layer,
                "signal_id": signal_id,
            },
            "question": {
                "text": question_text,
                "taxonomy_hint": "VALIDATION",
                "canonical_key_hint": canonical_key_hint,
                "answer_spec_hint": {
                    "preferred_kind": "choice",
                    "choices": [
                        {"id": "accept_auto", "label": "Accept planner decision"},
                        {"id": "revise_decision", "label": "Revise decision with planner"},
                        {"id": "manual_resolution", "label": "Require manual resolution"},
                    ],
                },
            },
            "context": {
                "blocking": {
                    "severity": "BLOCKING",
                    "blocked_slices": [slice_id] if slice_id else [],
                },
                "spec_refs": [],
                "code_refs": [],
            },
            "payload": payload,
        }

    def _emit_decision_recorded_event(
        self,
        *,
        trace: Any,
        context: PlanningContext,
        capability: str,
        decision_key: str,
        outputs: dict[str, Any],
    ) -> None:
        safe_outputs = outputs if isinstance(outputs, dict) else {}
        decision_ids, constraint_ids, canonical_keys = self._extract_update_identifiers(
            safe_outputs
        )
        review_questions = self._extract_review_questions(safe_outputs)
        review_required = bool(review_questions)
        review_reason = review_questions[0]["reason"] if review_questions else ""
        decision_record_tags = self._dedupe_preserve(
            self._coerce_id_list(safe_outputs.get("decision_record_tags", []))
        )

        decision = getattr(trace, "decision", None)
        decision_text = ""
        if decision is not None:
            decision_text = str(getattr(decision, "decision_text", "") or "")
        base_event: dict[str, Any] = {
            "event_kind": "decision_recorded",
            "event_id": str(getattr(trace, "trace_id", "") or ""),
            "trace_id": str(getattr(trace, "trace_id", "") or ""),
            "created_at": datetime.now(UTC).isoformat(),
            "run_id": context.run_id,
            "slice_id": context.slice_id,
            "layer": str(getattr(trace, "layer", "") or context.layer),
            "capability": capability,
            "decision_key": decision_key,
            "status": str(getattr(trace, "status", "") or ""),
            "decision_text": decision_text,
            "decision_ids": decision_ids,
            "constraint_ids": constraint_ids,
            "canonical_keys": canonical_keys,
            "review_required": review_required,
            "review_reason": review_reason,
        }
        if decision_record_tags:
            base_event["decision_record_tags"] = decision_record_tags
        events_to_emit: list[dict[str, Any]] = []
        if review_questions:
            for sequence, review_question in enumerate(review_questions, start=1):
                event = dict(base_event)
                event["event_id"] = (
                    f"{base_event['event_id']}:{sequence}"
                    if base_event["event_id"]
                    else f"planner-review-event-{uuid.uuid4().hex[:12]}"
                )
                event["created_at"] = datetime.now(UTC).isoformat()
                event["review_reason"] = str(review_question["reason"]).strip()
                event["user_question_signal"] = self._build_review_signal_payload(
                    run_id=context.run_id,
                    trace_id=event["trace_id"],
                    slice_id=context.slice_id,
                    layer=event["layer"],
                    decision_key=decision_key,
                    canonical_keys=canonical_keys,
                    decision_ids=decision_ids,
                    constraint_ids=constraint_ids,
                    signal_sequence=sequence,
                    question_text=str(review_question["question_text"]).strip(),
                    reason=str(review_question["reason"]).strip() or "human authority required",
                    extra_payload=(
                        review_question["payload"]
                        if isinstance(review_question.get("payload"), dict)
                        else {}
                    ),
                )
                events_to_emit.append(event)
        else:
            events_to_emit.append(base_event)

        for event in events_to_emit:
            self._append_planner_update(context.run_id, event)
            if self._on_decision_recorded is not None:
                try:
                    self._on_decision_recorded(event)
                except Exception:
                    logger.warning(
                        "on_decision_recorded callback failed for trace=%s",
                        event["trace_id"],
                        exc_info=True,
                    )

    def _persist_trace(self, trace: Any) -> None:
        """Persist trace artifacts; failure is a hard planner error."""
        trace.persist(self._workspace_root)
        try:
            self._persist_planner_state(trace)
        except Exception:
            logger.debug("Failed to persist planner_state for %s", trace.trace_id, exc_info=True)

    def _persist_planner_state(self, trace: Any) -> None:
        """Persist a per-layer planner decision digest for attribution/debugging."""
        run_id = str(getattr(trace, "run_id", "") or "")
        layer = str(getattr(trace, "layer", "") or "")
        slice_id = str(getattr(trace, "slice_id", "") or "")
        if not run_id or not layer or not slice_id:
            return
        if layer not in {"l1", "l2", "l3"}:
            return

        state_dir = self._workspace_root / "analysis" / "planner_state" / run_id / layer
        state_dir.mkdir(parents=True, exist_ok=True)

        outputs = {}
        artifacts = getattr(trace, "artifacts", {}) or {}
        override_outputs = artifacts.get("override_outputs")
        if isinstance(override_outputs, dict):
            outputs = override_outputs
        else:
            regular_outputs = artifacts.get("outputs")
            if isinstance(regular_outputs, dict):
                outputs = regular_outputs

        decision_text = ""
        decision = getattr(trace, "decision", None)
        if decision is not None:
            decision_text = str(getattr(decision, "decision_text", "") or "")

        payload = {
            "updated_at": datetime.now(tz=UTC).isoformat(),
            "run_id": run_id,
            "layer": layer,
            "slice_id": slice_id,
            "trace_id": str(getattr(trace, "trace_id", "") or ""),
            "decision_key": str(getattr(trace, "decision_key", "") or ""),
            "capability": str(getattr(trace, "capability", "") or ""),
            "status": str(getattr(trace, "status", "") or ""),
            "decision_text": decision_text,
            "overridden": bool(getattr(trace, "overridden", False)),
            "outputs": outputs,
        }
        safe_slice_id = slice_id.replace("/", "__").replace("\\", "__")
        out_path = state_dir / f"{safe_slice_id}.json"
        out_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _append_planner_update(self, run_id: str, event: dict[str, Any]) -> None:
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            logger.debug(
                "Planner update not written because run_id is missing (event_kind=%s)",
                event.get("event_kind", ""),
            )
            return
        updates_path = (
            self._workspace_root
            / ".pdd_runs"
            / normalized_run_id
            / "coordination"
            / "planner_updates.jsonl"
        )
        try:
            updates_path.parent.mkdir(parents=True, exist_ok=True)
            with updates_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        except OSError:
            logger.warning(
                "Failed to append planner update event_kind=%s run_id=%s",
                event.get("event_kind", ""),
                normalized_run_id,
                exc_info=True,
            )

    def ingest_user_answer(
        self,
        translation: Any,
        *,
        context: PlanningContext | None = None,
        slice_id: str = "",
    ) -> PlanningResult:
        """Ingest an Intent-Agent answer translation through Planner.plan()."""
        inputs: dict[str, Any] = {}
        run_id_hint = ""
        if isinstance(translation, Path):
            inputs["translation_path"] = str(translation)
            run_id_hint = self._infer_run_id_from_translation_path(translation)
        elif isinstance(translation, str):
            inputs["translation_path"] = translation
            run_id_hint = self._infer_run_id_from_translation_path(Path(translation))
        elif isinstance(translation, dict):
            inputs["translation"] = translation
            run_id_hint = str(translation.get("run_id", "")).strip()
        elif hasattr(translation, "to_dict") and callable(translation.to_dict):
            payload = translation.to_dict()
            inputs["translation"] = payload
            run_id_hint = str(payload.get("run_id", "")).strip()
        else:
            inputs["translation"] = translation

        if slice_id:
            inputs["slice_id"] = slice_id

        if context is None:
            context = PlanningContext(
                run_id=run_id_hint,
                slice_id=slice_id,
                layer="any",
                mode=self._mode if self._mode in {"auto", "interactive"} else "auto",
                workspace_root=str(self._workspace_root),
            )

        req = PlanningRequest(
            capability="INGEST_USER_ANSWER",
            context=context,
            inputs=inputs,
        )
        return self.plan(req)

    def _handle_ingest_user_answer(self, req: PlanningRequest) -> PlanningResult:
        from spec_manager.orchestration.intent_agent.answer_translation import AnswerTranslation
        from spec_manager.planner.constraints.types import ConstraintFact

        payload, source_ref, payload_errors = self._resolve_ingest_translation_payload(req.inputs)
        if payload is None:
            return PlanningResult(
                status="ERROR",
                outputs={
                    "validation_errors": payload_errors,
                    "decision_record_tags": ["answer_ingestion"],
                    "decision_text": "INGEST_USER_ANSWER rejected invalid payload",
                },
                error="invalid answer translation payload",
            )

        validation_errors = self._validate_ingest_translation_payload(payload)
        if validation_errors:
            return PlanningResult(
                status="ERROR",
                outputs={
                    "validation_errors": validation_errors,
                    "translation_id": str(payload.get("translation_id", "")).strip(),
                    "decision_record_tags": ["answer_ingestion"],
                    "decision_text": "INGEST_USER_ANSWER rejected invalid schema",
                },
                error="invalid answer translation schema",
            )

        try:
            translation = AnswerTranslation.from_dict(payload)
        except Exception as exc:
            return PlanningResult(
                status="ERROR",
                outputs={
                    "translation_id": str(payload.get("translation_id", "")).strip(),
                    "validation_errors": [f"translation deserialization failed: {exc}"],
                    "decision_record_tags": ["answer_ingestion"],
                    "decision_text": "INGEST_USER_ANSWER failed to deserialize translation",
                },
                error=f"translation deserialization failed: {exc}",
            )

        if translation.translation_status != "succeeded":
            return PlanningResult(
                status="NOOP",
                outputs={
                    "translation_id": translation.translation_id,
                    "question_id": translation.question_id,
                    "answer_id": translation.answer_id,
                    "source_ref": source_ref,
                    "translation_status": translation.translation_status,
                    "translation_failures": list(translation.extracted.translation_failures),
                    "decision_record_tags": ["answer_ingestion"],
                    "decision_text": "INGEST_USER_ANSWER skipped failed translation",
                },
            )

        target_slice_id = (
            str(req.inputs.get("slice_id") or req.context.slice_id or "__system__").strip()
            or "__system__"
        )

        authoritative_facts = self._constraints_adapter.load_merged(target_slice_id)
        existing_by_canonical: dict[str, list[Any]] = {}
        existing_by_question: dict[str, list[Any]] = {}
        for fact in authoritative_facts:
            canonical_key = self._extract_trace_tag(getattr(fact, "trace", []), "canonical_key")
            canonical_norm = self._normalize_for_compare(canonical_key)
            if canonical_norm:
                existing_by_canonical.setdefault(canonical_norm, []).append(fact)
            question_norm = self._normalize_for_compare(getattr(fact, "question", ""))
            if question_norm:
                existing_by_question.setdefault(question_norm, []).append(fact)

        proposals: list[dict[str, Any]] = []
        candidate_validation_errors: list[str] = []
        fallback_key = str(
            translation.canonical_key_hint or translation.question_id or "answer"
        ).strip()

        for idx, candidate in enumerate(translation.extracted.constraint_candidates):
            question = str(candidate.question).strip()
            answer = str(candidate.answer).strip() or str(translation.user_answer.raw_text).strip()
            canonical_key = str(candidate.canonical_key_hint).strip() or fallback_key
            if not question:
                question = f"Constraint answer for {canonical_key or translation.question_id}"
            if not answer:
                candidate_validation_errors.append(
                    f"constraint_candidates[{idx}] missing answer text",
                )
                continue
            scope_kind = str(candidate.scope_kind).strip().upper()
            scope = "system" if scope_kind == "SYSTEM_WIDE" else "intra:LIB"
            proposals.append(
                {
                    "taxonomy": "CONSTRAINT",
                    "canonical_key": canonical_key,
                    "question": question,
                    "answer": answer,
                    "confidence": self._clamp_confidence(candidate.confidence),
                    "scope": scope,
                }
            )

        for idx, candidate in enumerate(translation.extracted.tradeoff_candidates):
            axis = str(candidate.axis).strip()
            preference = str(candidate.preference).strip()
            if not (axis and preference):
                candidate_validation_errors.append(
                    f"tradeoff_candidates[{idx}] requires axis and preference",
                )
                continue
            canonical_suffix = re.sub(r"[^a-z0-9]+", "_", axis.lower()).strip("_") or f"axis_{idx}"
            proposals.append(
                {
                    "taxonomy": "TRADEOFF",
                    "canonical_key": f"{fallback_key}.tradeoff.{canonical_suffix}",
                    "question": f"Tradeoff preference for {axis}",
                    "answer": preference,
                    "confidence": self._clamp_confidence(candidate.confidence),
                    "scope": "intra:LIB",
                }
            )

        for idx, candidate in enumerate(translation.extracted.scope_candidates):
            scope_in = [str(item).strip() for item in candidate.scope_in if str(item).strip()]
            scope_out = [str(item).strip() for item in candidate.scope_out if str(item).strip()]
            if not scope_in and not scope_out:
                candidate_validation_errors.append(
                    f"scope_candidates[{idx}] empty scope_in and scope_out",
                )
                continue
            if scope_in:
                proposals.append(
                    {
                        "taxonomy": "SCOPE",
                        "canonical_key": f"{fallback_key}.scope.in",
                        "question": "In-scope items from user answer",
                        "answer": ", ".join(scope_in),
                        "confidence": 1.0,
                        "scope": "intra:LIB",
                    }
                )
            if scope_out:
                proposals.append(
                    {
                        "taxonomy": "SCOPE",
                        "canonical_key": f"{fallback_key}.scope.out",
                        "question": "Out-of-scope items from user answer",
                        "answer": ", ".join(scope_out),
                        "confidence": 1.0,
                        "scope": "intra:LIB",
                    }
                )

        for idx, candidate in enumerate(translation.extracted.validation_candidates):
            acceptance_statement = str(candidate.acceptance_statement).strip()
            if not acceptance_statement:
                candidate_validation_errors.append(
                    f"validation_candidates[{idx}] missing acceptance_statement",
                )
                continue
            proposals.append(
                {
                    "taxonomy": "VALIDATION",
                    "canonical_key": f"{fallback_key}.validation.{idx + 1}",
                    "question": "Validation criterion from user answer",
                    "answer": acceptance_statement,
                    "confidence": 1.0,
                    "scope": "intra:LIB",
                }
            )

        accepted_facts: list[ConstraintFact] = []
        accepted_constraint_ids: list[str] = []
        accepted_canonical_keys: list[str] = []
        decision_requirements: list[dict[str, Any]] = []
        under_spec_events: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        seen_candidates: set[tuple[str, str, str]] = set()
        seen_canonical_answers: dict[str, str] = {}

        for proposal in proposals:
            taxonomy = str(proposal.get("taxonomy", "")).strip().upper()
            if taxonomy not in _VALID_INGEST_TAXONOMY:
                candidate_validation_errors.append(
                    f"invalid taxonomy {taxonomy!r}; expected one of "
                    f"{sorted(_VALID_INGEST_TAXONOMY)}",
                )
                continue

            canonical_key = str(proposal.get("canonical_key", "")).strip()
            canonical_norm = self._normalize_for_compare(canonical_key)
            question = str(proposal.get("question", "")).strip()
            question_norm = self._normalize_for_compare(question)
            answer = str(proposal.get("answer", "")).strip()
            answer_norm = self._normalize_for_compare(answer)
            if not question_norm or not answer_norm:
                candidate_validation_errors.append(
                    f"{taxonomy} candidate requires non-empty question and answer",
                )
                continue

            dedupe_key = (canonical_norm, question_norm, answer_norm)
            if dedupe_key in seen_candidates:
                continue
            seen_candidates.add(dedupe_key)

            if canonical_norm:
                existing_candidate_answer = seen_canonical_answers.get(canonical_norm, "")
                if existing_candidate_answer and existing_candidate_answer != answer_norm:
                    decision_id = self._build_ingest_decision_id(
                        canonical_key,
                        question,
                        answer,
                        existing_candidate_answer,
                    )
                    conflict_question = (
                        f"User answer provided conflicting values for {canonical_key}. "
                        "Which value should be authoritative?"
                    )
                    decision_requirements.append(
                        {
                            "decision_id": decision_id,
                            "question": conflict_question,
                            "kind": "answer_conflict",
                            "dimension": "software",
                            "scope": "intra:LIB",
                            "impact": "MEDIUM",
                            "options": ["first_value", "latest_value", "manual_resolution"],
                            "needed_for": [target_slice_id],
                            "authority_required": "human_required",
                            "reason": "conflicting answers in same ingestion batch",
                            "canonical_key": canonical_key,
                        }
                    )
                    under_spec_events.append(
                        {
                            "type": "decision_required",
                            "event_id": decision_id,
                            "decision_id": decision_id,
                            "question": conflict_question,
                            "reason": "conflicting answers in same ingestion batch",
                            "canonical_key": canonical_key,
                            "authority_required": "human_required",
                        }
                    )
                    conflicts.append(
                        {
                            "canonical_key": canonical_key,
                            "reason": "batch_conflict",
                        }
                    )
                    continue
                seen_canonical_answers[canonical_norm] = answer_norm

            existing_matches: list[Any] = []
            if canonical_norm:
                existing_matches.extend(existing_by_canonical.get(canonical_norm, []))
            if not existing_matches and question_norm:
                existing_matches.extend(existing_by_question.get(question_norm, []))

            if existing_matches:
                same_answer = any(
                    self._normalize_for_compare(getattr(existing, "answer", "")) == answer_norm
                    for existing in existing_matches
                )
                if same_answer:
                    continue

                existing = existing_matches[0]
                existing_constraint_id = str(getattr(existing, "constraint_id", "")).strip()
                decision_id = self._build_ingest_decision_id(
                    canonical_key,
                    question,
                    answer,
                    existing_constraint_id,
                )
                conflict_question = (
                    f"User answer conflicts with existing authoritative constraint "
                    f"{existing_constraint_id} for '{question}'. Which should apply?"
                )
                decision_requirements.append(
                    {
                        "decision_id": decision_id,
                        "question": conflict_question,
                        "kind": "answer_conflict",
                        "dimension": "software",
                        "scope": "intra:LIB",
                        "impact": "MEDIUM",
                        "options": ["keep_existing", "accept_user_answer", "manual_resolution"],
                        "needed_for": [target_slice_id],
                        "authority_required": "human_required",
                        "reason": "proposed answer conflicts with authoritative constraint",
                        "canonical_key": canonical_key,
                        "existing_constraint_id": existing_constraint_id,
                    }
                )
                under_spec_events.append(
                    {
                        "type": "decision_required",
                        "event_id": decision_id,
                        "decision_id": decision_id,
                        "question": conflict_question,
                        "reason": "proposed answer conflicts with authoritative constraint",
                        "canonical_key": canonical_key,
                        "constraint_id": existing_constraint_id,
                        "authority_required": "human_required",
                    }
                )
                conflicts.append(
                    {
                        "canonical_key": canonical_key,
                        "existing_constraint_id": existing_constraint_id,
                        "reason": "authoritative_conflict",
                    }
                )
                continue

            constraint_id = self._build_ingest_constraint_id(canonical_key, question, answer)
            fact = ConstraintFact(
                constraint_id=constraint_id,
                question=question,
                answer=answer,
                source="user",
                confidence=self._clamp_confidence(proposal.get("confidence", 1.0)),
                validated=True,
                dimension="software",
                authority_required="planner_ok",
                scope=str(proposal.get("scope", "intra:LIB")),
                status="ACTIVE",
                trace=[
                    "ingest_capability=INGEST_USER_ANSWER",
                    f"translation_id={translation.translation_id}",
                    f"answer_id={translation.answer_id}",
                    f"question_id={translation.question_id}",
                    f"taxonomy={taxonomy.lower()}",
                    f"canonical_key={canonical_key}",
                    "authority_input=user_answer",
                    "authority_policy=planner_validated",
                ],
            )
            accepted_facts.append(fact)
            accepted_constraint_ids.append(constraint_id)
            if canonical_key:
                accepted_canonical_keys.append(canonical_key)

        persisted_path = ""
        if accepted_facts:
            persisted_path = str(
                self._constraints_adapter.save_facts(target_slice_id, accepted_facts)
            )

        decision_ids = self._dedupe_preserve(
            [
                str(item.get("decision_id", "")).strip()
                for item in decision_requirements
                if str(item.get("decision_id", "")).strip()
            ]
        )

        outputs: dict[str, Any] = {
            "translation_id": translation.translation_id,
            "question_id": translation.question_id,
            "answer_id": translation.answer_id,
            "source_ref": source_ref,
            "ingest_slice_id": target_slice_id,
            "constraint_ids": self._dedupe_preserve(accepted_constraint_ids),
            "canonical_keys": self._dedupe_preserve(accepted_canonical_keys),
            "decision_ids": decision_ids,
            "decision_requirements": decision_requirements,
            "under_spec_events": under_spec_events,
            "accepted_constraints": [fact.to_dict() for fact in accepted_facts],
            "conflicts": conflicts,
            "validation_errors": candidate_validation_errors,
            "persisted_constraints_path": persisted_path,
            "decision_record_tags": ["answer_ingestion"],
            "decision_text": (
                "INGEST_USER_ANSWER "
                f"accepted={len(accepted_facts)} "
                f"conflicts={len(conflicts)} "
                f"validation_errors={len(candidate_validation_errors)}"
            ),
        }
        if not accepted_facts and not decision_requirements:
            return PlanningResult(status="NOOP", outputs=outputs)
        return PlanningResult(status="OK", outputs=outputs)

    def _resolve_ingest_translation_payload(
        self,
        inputs: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str, list[str]]:
        payload_errors: list[str] = []
        source_ref = ""
        raw_translation = inputs.get("translation")
        raw_translation_path = inputs.get("translation_path")

        if raw_translation_path:
            path = Path(str(raw_translation_path))
            source_ref = str(path)
            if not path.exists():
                return None, source_ref, [f"translation_path does not exist: {path}"]
            try:
                raw_payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return None, source_ref, [f"failed to read translation_path: {exc}"]
            if not isinstance(raw_payload, dict):
                return None, source_ref, ["translation_path JSON payload must be an object"]
            return raw_payload, source_ref, payload_errors

        if isinstance(raw_translation, dict):
            source_ref = f"translation:{raw_translation.get('translation_id', '')}"
            return raw_translation, source_ref, payload_errors

        if hasattr(raw_translation, "to_dict") and callable(raw_translation.to_dict):
            payload = raw_translation.to_dict()
            if not isinstance(payload, dict):
                return None, source_ref, ["translation.to_dict() must return an object"]
            source_ref = f"translation:{payload.get('translation_id', '')}"
            return payload, source_ref, payload_errors

        if isinstance(raw_translation, (str, Path)):
            path = Path(str(raw_translation))
            source_ref = str(path)
            if not path.exists():
                return None, source_ref, [f"translation path does not exist: {path}"]
            try:
                raw_payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return None, source_ref, [f"failed to read translation path: {exc}"]
            if not isinstance(raw_payload, dict):
                return None, source_ref, ["translation path JSON payload must be an object"]
            return raw_payload, source_ref, payload_errors

        payload_errors.append(
            "INGEST_USER_ANSWER requires translation payload or translation_path input",
        )
        return None, source_ref, payload_errors

    @staticmethod
    def _validate_ingest_translation_payload(payload: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        required_fields = ("translation_id", "question_id", "created_at", "extracted")
        for field_name in required_fields:
            if field_name not in payload:
                errors.append(f"missing required field: {field_name}")

        translation_id = payload.get("translation_id")
        if not isinstance(translation_id, str) or not translation_id.strip():
            errors.append("translation_id must be a non-empty string")

        question_id = payload.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            errors.append("question_id must be a non-empty string")

        extracted = payload.get("extracted")
        if not isinstance(extracted, dict):
            errors.append("extracted must be an object")
            return errors

        extracted_list_fields = (
            "constraint_candidates",
            "scope_candidates",
            "tradeoff_candidates",
            "validation_candidates",
            "followup_question_drafts",
            "followup_omissions",
            "translation_failures",
        )
        for field_name in extracted_list_fields:
            value = extracted.get(field_name, [])
            if not isinstance(value, list):
                errors.append(f"extracted.{field_name} must be a list")

        for idx, followup in enumerate(extracted.get("followup_question_drafts", [])):
            if not isinstance(followup, dict):
                errors.append(f"extracted.followup_question_drafts[{idx}] must be an object")
                continue
            taxonomy_type = str(followup.get("taxonomy_type", "")).strip().upper()
            if taxonomy_type and taxonomy_type not in _VALID_INGEST_TAXONOMY:
                errors.append(
                    "extracted.followup_question_drafts"
                    f"[{idx}].taxonomy_type {taxonomy_type!r} is invalid",
                )

        return errors

    @staticmethod
    def _extract_trace_tag(trace_entries: Any, key: str) -> str:
        key_prefix = f"{key}="
        if not isinstance(trace_entries, list):
            return ""
        for entry in trace_entries:
            entry_text = str(entry)
            if entry_text.startswith(key_prefix):
                return entry_text.split("=", 1)[1].strip()
        return ""

    @staticmethod
    def _normalize_for_compare(value: Any) -> str:
        return " ".join(str(value or "").strip().lower().split())

    @staticmethod
    def _clamp_confidence(value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = 0.0
        return max(0.0, min(1.0, confidence))

    @staticmethod
    def _build_ingest_constraint_id(canonical_key: str, question: str, answer: str) -> str:
        seed = f"{canonical_key}|{question}|{answer}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
        token = re.sub(r"[^a-zA-Z0-9]+", "-", canonical_key).strip("-").upper()[:24]
        if token:
            return f"ANS-{token}-{digest[:6]}"
        return f"ANS-{digest}"

    @staticmethod
    def _build_ingest_decision_id(
        canonical_key: str,
        question: str,
        proposed_answer: str,
        conflict_ref: str,
    ) -> str:
        seed = f"{canonical_key}|{question}|{proposed_answer}|{conflict_ref}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
        return f"DEC-{digest}"

    @staticmethod
    def _infer_run_id_from_translation_path(path: Path) -> str:
        parts = list(path.parts)
        for idx, part in enumerate(parts):
            if part != ".pdd_runs":
                continue
            run_idx = idx + 1
            if run_idx < len(parts):
                return str(parts[run_idx]).strip()
        return ""

    # ------------------------------------------------------------------
    # Convenience adapters for existing call sites
    # ------------------------------------------------------------------

    def resolve_signal(self, signal: Any, context: PlanningContext) -> Any:
        """Resolve an ambiguity signal.

        Returns the layer planner's response (typically a dict or None).
        """
        context.signal_ref = signal
        req = PlanningRequest(
            capability="RESOLVE_SIGNAL",
            context=context,
            inputs={"signal": signal},
        )
        result = self.plan(req)
        return result.outputs.get("response")

    def plan_from_gaps(
        self, context: PlanningContext, gaps: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Generate a PLAN output payload from a gap list.

        Returns the full planner outputs dict (intentions plus any
        strategy-pipeline artifacts such as decision_requirements).
        """
        req = PlanningRequest(
            capability="PLAN",
            context=context,
            inputs={"gaps": gaps},
        )
        result = self.plan(req)
        if not isinstance(result.outputs, dict):
            return {}
        return dict(result.outputs)

    def resolve_under_spec(
        self, context: PlanningContext, events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Resolve or block under-spec events.

        Returns an explicit contract with:
        ``blocked``, ``constraints``, ``questions``, ``resolved``,
        ``routing`` (work items), ``monitors``, and ``expansions``.
        """
        req = PlanningRequest(
            capability="UNDER_SPEC",
            context=context,
            inputs={"events": events},
        )
        result = self.plan(req)
        outputs = result.outputs if isinstance(result.outputs, dict) else {}
        return self._normalize_under_spec_outputs(
            context=context,
            events=events,
            outputs=outputs,
            status=result.status,
        )

    def persist_under_spec_constraints(
        self,
        *,
        run_id: str,
        layer: str,
        slice_id: str,
        constraints: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Persist validated under-spec constraints through Planner authority."""
        from spec_manager.planner.constraints.store_adapter import ConstraintStoreAdapter
        from spec_manager.planner.constraints.types import ConstraintFact

        facts: list[ConstraintFact] = []
        canonical_keys: list[str] = []
        constraint_ids: list[str] = []
        target_slice = str(slice_id or "__system__").strip() or "__system__"
        layer_token = str(layer or "any").strip().lower()
        default_layers = [layer_token.upper()] if layer_token in {"l1", "l2", "l3"} else []
        run_token = str(run_id or "").strip()
        authoritative_facts = self._constraints_adapter.load_merged(target_slice)

        existing_active_by_canonical: dict[str, list[ConstraintFact]] = {}
        existing_active_by_question: dict[str, list[ConstraintFact]] = {}
        for existing_fact in authoritative_facts:
            if str(getattr(existing_fact, "status", "ACTIVE")).strip().upper() != "ACTIVE":
                continue
            existing_canonical_key = self._extract_trace_tag(
                getattr(existing_fact, "trace", []), "canonical_key"
            )
            existing_canonical_norm = self._normalize_for_compare(existing_canonical_key)
            if existing_canonical_norm:
                existing_active_by_canonical.setdefault(existing_canonical_norm, []).append(
                    existing_fact
                )
            existing_question_norm = self._normalize_for_compare(
                getattr(existing_fact, "question", "")
            )
            if existing_question_norm:
                existing_active_by_question.setdefault(existing_question_norm, []).append(
                    existing_fact
                )

        for row in constraints:
            if not isinstance(row, dict):
                continue
            constraint_id = str(row.get("constraint_id", "")).strip()
            question = str(row.get("question", "")).strip()
            answer = str(row.get("answer", "")).strip()
            if not (constraint_id and question and answer):
                continue
            raw_trace = row.get("trace", [])
            trace = [str(item).strip() for item in raw_trace if str(item).strip()]
            canonical_key = self._extract_trace_tag(trace, "canonical_key")
            if not canonical_key:
                canonical_key = f"underspec.{constraint_id}"
                trace.append(f"canonical_key={canonical_key}")
            canonical_key_norm = self._normalize_for_compare(canonical_key)
            question_norm = self._normalize_for_compare(question)
            confidence = self._clamp_confidence(row.get("confidence", 0.7))
            authority_required = str(row.get("authority_required", "planner_ok")).strip().lower()
            if authority_required == "user_required":
                authority_required = "human_required"
            if authority_required not in {"planner_ok", "human_required"}:
                authority_required = "planner_ok"
            if authority_required != "planner_ok":
                continue
            dimension = str(row.get("dimension", "software")).strip().lower()
            if dimension not in _VALID_UNDER_SPEC_DIMENSIONS:
                dimension = "software"
            decision_type = str(row.get("decision_type", "performance")).strip().lower()
            if decision_type not in _VALID_UNDER_SPEC_DECISION_TYPES:
                decision_type = "performance"
            status = str(row.get("status", "ACTIVE")).strip().upper() or "ACTIVE"
            if status not in {"ACTIVE", "SUPERSEDED"}:
                status = "ACTIVE"
            raw_supersedes = row.get("supersedes", [])
            if isinstance(raw_supersedes, list):
                supersedes = [str(item).strip() for item in raw_supersedes if str(item).strip()]
            elif isinstance(raw_supersedes, str):
                supersedes = [raw_supersedes.strip()] if raw_supersedes.strip() else []
            else:
                supersedes = []

            if not supersedes:
                prior_facts: list[ConstraintFact] = []
                if canonical_key_norm:
                    prior_facts = list(existing_active_by_canonical.get(canonical_key_norm, []))
                if not prior_facts and question_norm:
                    prior_facts = list(existing_active_by_question.get(question_norm, []))
                supersedes = [
                    str(existing.constraint_id).strip()
                    for existing in prior_facts
                    if str(existing.constraint_id).strip()
                    and str(existing.constraint_id).strip() != constraint_id
                ]
            supersedes = self._dedupe_preserve(supersedes)

            source = self._coerce_under_spec_constraint_source(row.get("source", "research"))
            applies_to_layers = self._normalize_constraint_layers(
                row.get("applies_to_layers", default_layers),
                fallback=default_layers,
            )
            fact = ConstraintFact(
                constraint_id=constraint_id,
                question=question,
                answer=answer,
                source=source,
                confidence=confidence,
                validated=bool(row.get("validated", True)),
                dimension=dimension,
                authority_required=authority_required,
                decision_type=decision_type,
                scope=str(row.get("scope", "intra:LIB") or "intra:LIB"),
                applies_to_layers=applies_to_layers,
                status=status,
                supersedes=supersedes,
                trace=[
                    *trace,
                    "ingest_capability=UNDER_SPEC",
                    f"layer={layer_token}",
                    f"slice_id={target_slice}",
                ],
            )
            facts.append(fact)
            constraint_ids.append(constraint_id)
            canonical_keys.append(canonical_key)

        if not facts:
            return {"constraints_path": "", "constraint_ids": [], "canonical_keys": []}

        context_token = ConstraintStoreAdapter.push_planner_update_context(
            run_id=run_token,
            layer=layer_token,
            capability="UNDER_SPEC",
        )
        try:
            saved_path = self._constraints_adapter.save_facts(target_slice, facts)
        finally:
            ConstraintStoreAdapter.pop_planner_update_context(context_token)

        return {
            "constraints_path": str(saved_path),
            "constraint_ids": self._dedupe_preserve(constraint_ids),
            "canonical_keys": self._dedupe_preserve(canonical_keys),
        }

    def _normalize_under_spec_outputs(
        self,
        *,
        context: PlanningContext,
        events: list[dict[str, Any]],
        outputs: dict[str, Any],
        status: str,
    ) -> dict[str, Any]:
        blocked = bool(outputs.get("blocked", False) or status == "BLOCKED")
        constraints_raw = outputs.get("constraints", {})
        constraints = constraints_raw if isinstance(constraints_raw, dict) else {}
        questions_raw = outputs.get("questions", [])
        questions = (
            [str(q).strip() for q in questions_raw if str(q).strip()]
            if isinstance(questions_raw, list)
            else []
        )
        resolved_raw = outputs.get("resolved", [])
        resolved = (
            [row for row in resolved_raw if isinstance(row, dict)]
            if isinstance(resolved_raw, list)
            else []
        )
        routing_raw = outputs.get("routing", [])
        routing = (
            [row for row in routing_raw if isinstance(row, dict)]
            if isinstance(routing_raw, list)
            else []
        )
        monitors_raw = outputs.get("monitors", [])
        monitors = (
            [row for row in monitors_raw if isinstance(row, dict)]
            if isinstance(monitors_raw, list)
            else []
        )

        expansions: list[dict[str, Any]] = []
        expansions_raw = outputs.get("expansions", [])
        if isinstance(expansions_raw, list):
            expansions.extend(row for row in expansions_raw if isinstance(row, dict))
        single_expansion = outputs.get("expansion")
        if isinstance(single_expansion, dict):
            expansions.append(single_expansion)

        # When UNDER_SPEC remains blocked with no routable payload, synthesize
        # spec expansion work-items via TRIAGE_SIGNAL so callers can route
        # provider work and register monitors explicitly.
        if blocked and not routing and events:
            triage_payload = self._expand_under_spec_via_triage(context=context, events=events)
            routing.extend(triage_payload["routing"])
            monitors.extend(triage_payload["monitors"])
            expansions.extend(triage_payload["expansions"])

        contradictions_raw = outputs.get("contradictions", [])
        contradictions = (
            [str(item) for item in contradictions_raw if str(item).strip()]
            if isinstance(contradictions_raw, list)
            else []
        )

        confidence_raw = outputs.get("confidence", outputs.get("score", 0.0))
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.0

        return {
            "blocked": blocked,
            "constraints": constraints,
            "questions": questions,
            "resolved": resolved,
            "routing": routing,
            "monitors": monitors,
            "expansions": expansions,
            "confidence": max(0.0, min(1.0, confidence)),
            "contradictions": contradictions,
        }

    @staticmethod
    def _coerce_under_spec_constraint_source(
        value: Any,
    ) -> Literal["user", "research", "steering", "existing"]:
        source = str(value or "").strip().lower()
        if source in {"user", "steering", "existing"}:
            return source
        return "research"

    @staticmethod
    def _normalize_constraint_layers(value: Any, *, fallback: list[str]) -> list[str]:
        raw_values: list[str]
        if isinstance(value, str):
            raw_values = [value]
        elif isinstance(value, list):
            raw_values = [str(item) for item in value]
        else:
            raw_values = []

        normalized: list[str] = []
        for raw in raw_values:
            for token in raw.replace("|", ",").split(","):
                layer = token.strip().upper()
                if layer in {"L1", "L2", "L3"} and layer not in normalized:
                    normalized.append(layer)
        if normalized:
            return normalized

        fallback_layers: list[str] = []
        for raw in fallback:
            layer = str(raw).strip().upper()
            if layer in {"L1", "L2", "L3"} and layer not in fallback_layers:
                fallback_layers.append(layer)
        return fallback_layers

    def _expand_under_spec_via_triage(
        self,
        *,
        context: PlanningContext,
        events: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        routing: list[dict[str, Any]] = []
        monitors: list[dict[str, Any]] = []
        expansions: list[dict[str, Any]] = []

        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue

            signal = self._synthesize_under_spec_signal(
                context=context,
                event=event,
                event_index=index,
            )
            triage_ctx = PlanningContext(
                run_id=context.run_id,
                slice_id=context.slice_id,
                iteration=context.iteration,
                layer="l1",
                mode=context.mode,
                workspace_root=context.workspace_root,
                slice_root=context.slice_root,
                bundle_ref=context.bundle_ref,
                signal_ref=signal,
                metadata={"source": "UNDER_SPEC_EXPANSION"},
            )

            triage_result = self.triage_signal(triage_ctx, signal)
            triage_outputs = (
                triage_result.outputs
                if hasattr(triage_result, "outputs") and isinstance(triage_result.outputs, dict)
                else {}
            )
            triage_routing = triage_outputs.get("routing", [])
            triage_monitors = triage_outputs.get("monitors", [])
            confidence_raw = triage_outputs.get("confidence", 0.0)
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                confidence = 0.0
            proposal_models_raw = triage_outputs.get("proposal_models", [])
            proposal_models = (
                [str(model) for model in proposal_models_raw if str(model).strip()]
                if isinstance(proposal_models_raw, list)
                else []
            )

            triage_routing_dicts = (
                [row for row in triage_routing if isinstance(row, dict)]
                if isinstance(triage_routing, list)
                else []
            )
            triage_monitor_dicts = (
                [row for row in triage_monitors if isinstance(row, dict)]
                if isinstance(triage_monitors, list)
                else []
            )

            consistency_passed = self._consistency_check(
                signal=signal,
                routing_payloads=triage_routing_dicts,
            )
            contradictions_raw = triage_outputs.get("contradictions", [])
            contradictions = (
                [str(item) for item in contradictions_raw if str(item).strip()]
                if isinstance(contradictions_raw, list)
                else []
            )

            for payload in triage_routing_dicts:
                metadata = payload.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata = dict(metadata)
                metadata["event_id"] = str(event.get("event_id", "")).strip()
                metadata["signal_id"] = signal["signal_id"]
                metadata["spec_refs"] = list(signal["spec_refs"])
                metadata["provenance"] = (
                    f"Expansion created to resolve signal_id {signal['signal_id']}."
                )
                metadata["confidence"] = confidence
                metadata["proposal_models"] = proposal_models
                metadata["consistency_passed"] = consistency_passed
                payload["metadata"] = metadata
                routing.append(payload)

            for payload in triage_monitor_dicts:
                payload = dict(payload)
                payload.setdefault("signal_id", signal["signal_id"])
                monitors.append(payload)

            expansions.append(
                {
                    "event_id": str(event.get("event_id", "")).strip(),
                    "signal_id": signal["signal_id"],
                    "action": str(triage_outputs.get("action", "NOOP")).strip().upper() or "NOOP",
                    "confidence": max(0.0, min(1.0, confidence)),
                    "proposal_models": proposal_models,
                    "consistency_passed": consistency_passed,
                    "contradictions": contradictions,
                    "spec_refs": list(signal["spec_refs"]),
                    "routing": triage_routing_dicts,
                    "monitors": triage_monitor_dicts,
                    "why": str(triage_outputs.get("why", "")).strip(),
                    "missing_detail": str(triage_outputs.get("missing_detail", "")).strip(),
                }
            )

        return {
            "routing": routing,
            "monitors": monitors,
            "expansions": expansions,
        }

    @staticmethod
    def _synthesize_under_spec_signal(
        *,
        context: PlanningContext,
        event: dict[str, Any],
        event_index: int,
    ) -> dict[str, Any]:
        question = str(event.get("question", "")).strip() or "Under-specification detected"
        raw_event_id = str(event.get("event_id", "")).strip()
        event_id = raw_event_id or hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]
        source_line_raw = event.get("source_line", 0)
        try:
            source_line = int(source_line_raw or 0)
        except (TypeError, ValueError):
            source_line = 0

        ctx_payload = event.get("context", {})
        artifact_key = ""
        if isinstance(ctx_payload, dict):
            artifact_key = str(
                ctx_payload.get("needed_for")
                or ctx_payload.get("artifact_key")
                or ctx_payload.get("context")
                or ""
            ).strip()
        if not artifact_key:
            artifact_key = str(event.get("needed_for", "")).strip()
        if not artifact_key:
            artifact_key = str(event.get("source_file", event.get("file", ""))).strip()
        signal_id = f"{context.slice_id}:{context.iteration}:{event_id}:{event_index}"
        spec_refs = Planner._extract_spec_refs_from_event(
            event=event,
            question=question,
            source_line=source_line,
        )

        return {
            "signal_version": 1,
            "signal_id": signal_id,
            "run_id": context.run_id,
            "layer": context.layer,
            "slice_id": context.slice_id,
            "iteration": context.iteration,
            "status": "HALT",
            "classification": "AMBIGUOUS_SPEC",
            "need": {
                "summary": question,
                "artifact_key": artifact_key,
            },
            "spec_refs": spec_refs,
            "search_hints": {
                "keywords": [token for token in re.split(r"[^a-zA-Z0-9]+", artifact_key) if token],
                "possible_owner_slices": [],
            },
            "payload": {"under_spec_event": event},
        }

    @staticmethod
    def _extract_spec_refs_from_event(
        *,
        event: dict[str, Any],
        question: str,
        source_line: int,
    ) -> list[dict[str, Any]]:
        context_payload = event.get("context", {})
        if isinstance(context_payload, dict):
            refs = context_payload.get("spec_refs", [])
            if isinstance(refs, list):
                normalized: list[dict[str, Any]] = []
                for raw in refs:
                    if not isinstance(raw, dict):
                        continue
                    text = str(raw.get("spec_text", "")).strip()
                    source_file = str(raw.get("source_file", "")).strip()
                    source_symbol = str(raw.get("source_symbol", "")).strip()
                    line_hint_raw = raw.get("source_line_hint", source_line)
                    try:
                        line_hint = int(line_hint_raw or 0)
                    except (TypeError, ValueError):
                        line_hint = 0
                    if not (text or source_file):
                        continue
                    normalized.append(
                        {
                            "spec_text": text or question,
                            "source_file": source_file,
                            "source_symbol": source_symbol,
                            "source_line_hint": line_hint,
                        }
                    )
                if normalized:
                    return normalized

        return [
            {
                "spec_text": question,
                "source_file": str(event.get("source_file", event.get("file", ""))).strip(),
                "source_symbol": "",
                "source_line_hint": source_line,
            }
        ]

    @staticmethod
    def _consistency_check(
        *,
        signal: dict[str, Any],
        routing_payloads: list[dict[str, Any]],
    ) -> bool:
        spec_text = " ".join(
            str(ref.get("spec_text", "")).strip().lower()
            for ref in signal.get("spec_refs", [])
            if isinstance(ref, dict)
        ).strip()
        routed_text = " ".join(
            str(payload.get("spec_text", "")).strip().lower() for payload in routing_payloads
        ).strip()
        if not spec_text or not routed_text:
            return False
        spec_tokens = {t for t in re.split(r"[^a-z0-9]+", spec_text) if t}
        routed_tokens = {t for t in re.split(r"[^a-z0-9]+", routed_text) if t}
        if not spec_tokens or not routed_tokens:
            return False
        return len(spec_tokens & routed_tokens) > 0

    def triage_signal(
        self,
        context: PlanningContext,
        signal: dict[str, Any],
    ) -> PlanningResult:
        """Triage a coordination signal from a halted agent.

        The planner searches work items, classifies the need, and returns
        routing decisions + monitor specs.
        """
        req = PlanningRequest(
            capability="TRIAGE_SIGNAL",
            context=context,
            inputs={"signal": signal},
        )
        return self.plan(req)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_trace_id() -> str:
    """Return a short unique trace identifier."""
    return uuid.uuid4().hex[:12]


def _request_snapshot(
    req: PlanningRequest,
    *,
    input_hash: str = "",
    decision_key: str = "",
    model_id: str = "",
    planner_version: str = "",
) -> dict[str, Any]:
    """Build a JSON-safe snapshot of the request for trace storage."""
    ctx = req.context
    return {
        "capability": req.capability,
        "layer": ctx.layer,
        "run_id": ctx.run_id,
        "slice_id": ctx.slice_id,
        "iteration": ctx.iteration,
        "mode": ctx.mode,
        "workspace_root": ctx.workspace_root,
        "slice_root": ctx.slice_root,
        "metadata": _safe_deepcopy(ctx.metadata),
        "inputs": _safe_deepcopy(req.inputs),
        "inputs_keys": sorted(req.inputs.keys()),
        "input_hash": input_hash,
        "decision_key": decision_key,
        "model_id": model_id,
        "planner_version": planner_version,
        "constraints_hint": _safe_deepcopy(req.constraints_hint),
        "has_constraints_hint": req.constraints_hint is not None,
    }


def _safe_deepcopy(value: Any) -> Any:
    """Best-effort deep copy for trace snapshots."""
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


def _extract_tokens(outputs: dict[str, Any]) -> tuple[int, int]:
    """Best-effort extraction of token usage metadata from planner outputs."""
    if not isinstance(outputs, dict):
        return 0, 0
    usage = outputs.get("usage")
    if not isinstance(usage, dict):
        return 0, 0
    raw_in = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    raw_out = usage.get("output_tokens", usage.get("completion_tokens", 0))
    try:
        tokens_in = int(raw_in or 0)
    except (TypeError, ValueError):
        tokens_in = 0
    try:
        tokens_out = int(raw_out or 0)
    except (TypeError, ValueError):
        tokens_out = 0
    return max(tokens_in, 0), max(tokens_out, 0)
