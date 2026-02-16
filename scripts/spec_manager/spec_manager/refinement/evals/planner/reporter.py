"""Compute and write the PlannerScorecard from trace data and ground truth verdicts.

Produces four output files under ``reports/pdd/{run_id}/``:

- ``planner_scorecard.json`` -- machine-readable scorecard
- ``planner_scorecard.md`` -- human-readable tables
- ``planner_decisions.jsonl`` -- one line per decision with verdict
- ``planner_eval.jsonl`` -- one line per decision with eval inputs/outputs/scoring

Hard gates (5) are mechanical pass/fail checks derived from traces:

1. ``planner.trace_integrity`` -- every planner call has request + decision
2. ``planner.no_error_status`` -- zero ERROR-status traces
3. ``planner.under_spec_safety`` -- zero false-unblock events
4. ``planner.schema_validity`` -- all outputs conform to capability schema
5. ``planner.no_oos_intentions`` -- no out-of-scope intentions in PLAN step

Soft signals (~18) are computed from verdicts (GT comparison) and traces
(efficiency / epistemic hygiene).
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_STABLE_COMPARISON_METRIC_NAMES = {
    "planner.under_spec_safety",
    "planner.must_include_coverage",
    "planner.out_of_scope_rate",
    "planner.unsafe_resolution_rate",
    "planner.evidence_first_rate",
    "planner.tokens_per_decision",
    "planner.latency_per_decision",
    "planner.iterations_per_slice",
    "planner.demotions_per_slice",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PlannerMetric:
    """A single planner scorecard metric.

    Attributes:
        name: Dot-separated metric name (e.g. ``planner.trace_integrity``).
        raw: Raw computed value before normalization.
        score: Internal normalized score between 0.0 and 1.0.
        status: One of ``PASS``, ``WARN``, or ``FAIL``.
        hard_gate: Whether this metric is a hard gate (blocks pipeline).
        detail: Human-readable explanation.
        evidence_refs: Trace IDs or artifact paths supporting the value.
    """

    name: str = ""
    raw: float = 0.0
    score: float = 0.0
    status: str = "PASS"
    hard_gate: bool = False
    detail: str = ""
    evidence_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_export_dict(self) -> dict[str, Any]:
        """Return artifact representation with score normalized to 0-100."""
        payload = asdict(self)
        payload["score"] = max(0.0, min(float(self.score), 1.0)) * 100.0
        return payload


@dataclass
class PlannerSliceAggregate:
    """Per-slice planner evaluation summary."""

    slice_id: str = ""
    decisions_total: int = 0
    decisions_evaluated: int = 0
    decisions_passed: int = 0
    decisions_failed: int = 0
    pass_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlannerScorecard:
    """Complete scorecard for a planner evaluation run.

    Attributes:
        run_id: Unique identifier for the evaluation run.
        model_id: Model identifier used for the planner decisions.
        hard_gates: List of hard-gate metrics (all must pass).
        soft_signals: List of soft-signal metrics (diagnostic).
        slice_aggregates: Per-slice decision aggregates.
        overall_pass: True when every hard gate has status PASS.
        decisions_evaluated: Number of decisions that had GT verdicts.
        decisions_total: Total number of decision traces loaded.
        summary: Human-readable one-line summary.
    """

    run_id: str = ""
    model_id: str = ""
    hard_gates: list[PlannerMetric] = field(default_factory=list)
    soft_signals: list[PlannerMetric] = field(default_factory=list)
    slice_aggregates: list[PlannerSliceAggregate] = field(default_factory=list)
    overall_pass: bool = True
    decisions_evaluated: int = 0
    decisions_total: int = 0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "model_id": self.model_id,
            "overall_pass": self.overall_pass,
            "decisions_evaluated": self.decisions_evaluated,
            "decisions_total": self.decisions_total,
            "summary": self.summary,
            "hard_gates": [m.to_dict() for m in self.hard_gates],
            "soft_signals": [m.to_dict() for m in self.soft_signals],
            "slice_aggregates": [a.to_dict() for a in self.slice_aggregates],
        }

    def to_export_dict(self) -> dict[str, Any]:
        """Return artifact representation with metric scores on a 0-100 scale."""
        return {
            "run_id": self.run_id,
            "model_id": self.model_id,
            "overall_pass": self.overall_pass,
            "decisions_evaluated": self.decisions_evaluated,
            "decisions_total": self.decisions_total,
            "summary": self.summary,
            "hard_gates": [m.to_export_dict() for m in self.hard_gates],
            "soft_signals": [m.to_export_dict() for m in self.soft_signals],
            "slice_aggregates": [a.to_dict() for a in self.slice_aggregates],
        }


# ---------------------------------------------------------------------------
# Percentile helper (no numpy dependency)
# ---------------------------------------------------------------------------


def _percentile(values: list[float], pct: float) -> float:
    """Compute *pct*-th percentile from a sorted list.

    Uses nearest-rank interpolation.  Returns 0.0 for an empty list.
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = max(0, min(int(len(sorted_vals) * pct / 100.0 + 0.5) - 1, len(sorted_vals) - 1))
    return sorted_vals[k]


# ---------------------------------------------------------------------------
# PlannerReporter
# ---------------------------------------------------------------------------


class PlannerReporter:
    """Aggregates verdicts and traces into a :class:`PlannerScorecard`.

    Parameters
    ----------
    workspace_root:
        Root directory of the PDD workspace.
    run_id:
        Identifier for the evaluation run.
    """

    def __init__(self, workspace_root: Path, run_id: str) -> None:
        self._workspace = workspace_root
        self._run_id = run_id
        self._reports_dir = workspace_root / "reports" / "pdd" / run_id
        self._last_verdicts: list[Any] = []
        self._last_traces: list[Any] = []
        self._baseline_load_issue: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(
        self,
        verdicts: list[Any],
        traces: list[Any],
    ) -> PlannerScorecard:
        """Compute scorecard from verdicts (GT comparison) and traces (raw data).

        Args:
            verdicts: List of :class:`Verdict` objects from GT scoring.
            traces: List of ``LoadedTrace``-like objects from trace loading.

        Returns:
            Fully populated :class:`PlannerScorecard`.
        """
        self._last_verdicts = list(verdicts)
        self._last_traces = list(traces)
        self._baseline_load_issue = ""
        hard_gates = self._compute_hard_gates(verdicts, traces)
        soft_signals = self._compute_soft_signals(verdicts, traces)
        slice_aggregates = self._compute_slice_aggregates(verdicts, traces)
        overall_pass = all(g.status != "FAIL" for g in hard_gates)

        failing_gates = [g.name for g in hard_gates if g.status == "FAIL"]
        warnings = [s.name for s in soft_signals if s.status == "WARN"]
        failing_soft = [s.name for s in soft_signals if s.status == "FAIL"]

        summary_parts: list[str] = []
        if overall_pass:
            summary_parts.append("All hard gates PASS.")
        else:
            summary_parts.append(f"FAIL: {', '.join(failing_gates)}")
        if warnings:
            summary_parts.append(f"Warnings: {', '.join(warnings)}")
        if failing_soft:
            summary_parts.append(f"Soft failures: {', '.join(failing_soft)}")

        # Attempt to extract model_id from traces
        model_id = ""
        for t in traces:
            artifacts = getattr(t, "artifacts", None) or {}
            mid = artifacts.get("model_id", "")
            if mid:
                model_id = str(mid)
                break

        return PlannerScorecard(
            run_id=self._run_id,
            model_id=model_id,
            hard_gates=hard_gates,
            soft_signals=soft_signals,
            slice_aggregates=slice_aggregates,
            overall_pass=overall_pass,
            decisions_evaluated=len(verdicts),
            decisions_total=len(traces),
            summary=" ".join(summary_parts),
        )

    def write(self, scorecard: PlannerScorecard, *, traces: list[Any]) -> None:
        """Write scorecards and per-decision planner eval artifacts.

        All files are written under ``reports/pdd/{run_id}/``.

        Args:
            scorecard: The scorecard to persist.
            traces: Loaded traces included in this scorecard.
        """
        self._reports_dir.mkdir(parents=True, exist_ok=True)

        # Machine-readable JSON
        json_path = self._reports_dir / "planner_scorecard.json"
        json_path.write_text(
            json.dumps(scorecard.to_export_dict(), indent=2),
            encoding="utf-8",
        )

        # Human-readable markdown
        md_path = self._reports_dir / "planner_scorecard.md"
        md_path.write_text(self._render_markdown(scorecard), encoding="utf-8")

        # Per-decision JSONL (verdicts only -- no scorecard-level info)
        jsonl_path = self._reports_dir / "planner_decisions.jsonl"
        lines = [json.dumps(self._verdict_to_row(v), sort_keys=True) for v in self._last_verdicts]
        jsonl_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

        # Per-decision eval stream for downstream tooling.
        eval_jsonl_path = self._reports_dir / "planner_eval.jsonl"
        verdict_by_trace_id = self._verdicts_by_trace_id()
        eval_lines = [
            json.dumps(self._eval_row(trace=t, verdict_by_trace_id=verdict_by_trace_id))
            for t in traces
        ]
        eval_jsonl_path.write_text(
            "\n".join(eval_lines) + ("\n" if eval_lines else ""),
            encoding="utf-8",
        )

        # Planner review (FAIL/WARN/NEEDS_REVIEW decisions with trace paths)
        review_path = self._reports_dir / "planner_review.md"
        review_path.write_text(
            self._render_review(self._last_verdicts, self._trace_paths_by_id(traces)),
            encoding="utf-8",
        )

        logger.info(
            "Planner scorecard written: json=%s md=%s decisions=%s eval=%s review=%s",
            json_path,
            md_path,
            jsonl_path,
            eval_jsonl_path,
            review_path,
        )

    # ------------------------------------------------------------------
    # Hard gates
    # ------------------------------------------------------------------

    def _compute_hard_gates(
        self,
        verdicts: list[Any],
        traces: list[Any],
    ) -> list[PlannerMetric]:
        gates: list[PlannerMetric] = []

        # 1. planner.trace_integrity
        gates.append(self._gate_trace_integrity(traces))

        # 2. planner.no_error_status
        gates.append(self._gate_no_error_status(traces))

        # 3. planner.under_spec_safety
        gates.append(self._gate_under_spec_safety(verdicts))

        # 4. planner.schema_validity
        gates.append(self._gate_schema_validity(traces))

        # 5. planner.no_oos_intentions
        gates.append(self._gate_no_oos_intentions(traces))

        return gates

    def _gate_trace_integrity(self, traces: list[Any]) -> PlannerMetric:
        """Every planner call must have request.json + decision.json."""
        missing: list[str] = []
        for t in traces:
            tid = getattr(t, "trace_id", "")
            has_request = bool(getattr(t, "request_exists", False))
            has_decision = bool(getattr(t, "decision_exists", False))
            if not has_request:
                has_request = bool(getattr(t, "request", None))
            if not has_decision:
                has_decision = bool(getattr(t, "decision", None))
            if not has_request or not has_decision:
                missing.append(str(tid))

        ok = len(missing) == 0
        return PlannerMetric(
            name="planner.trace_integrity",
            raw=float(len(missing)),
            score=1.0 if ok else 0.0,
            status="PASS" if ok else "FAIL",
            hard_gate=True,
            detail=f"{len(missing)} trace(s) missing request or decision",
            evidence_refs=missing[:20],
        )

    def _gate_no_error_status(self, traces: list[Any]) -> PlannerMetric:
        """PlanningResult.status==ERROR count must be 0."""
        error_ids: list[str] = []
        for t in traces:
            status = getattr(t, "status", "") or ""
            if str(status).upper() == "ERROR":
                error_ids.append(str(getattr(t, "trace_id", "")))

        ok = len(error_ids) == 0
        return PlannerMetric(
            name="planner.no_error_status",
            raw=float(len(error_ids)),
            score=1.0 if ok else 0.0,
            status="PASS" if ok else "FAIL",
            hard_gate=True,
            detail=f"{len(error_ids)} trace(s) with ERROR status",
            evidence_refs=error_ids[:20],
        )

    def _gate_under_spec_safety(self, verdicts: list[Any]) -> PlannerMetric:
        """False-unblock rate for events GT says must block must be 0."""
        under_spec_total, false_unblock_count, false_unblock_refs = (
            self._collect_under_spec_safety_counts(verdicts)
        )
        rate = false_unblock_count / max(under_spec_total, 1)
        ok = len(false_unblock_refs) == 0
        return PlannerMetric(
            name="planner.under_spec_safety",
            raw=rate,
            score=1.0 if ok else max(0.0, 1.0 - rate),
            status="PASS" if ok else "FAIL",
            hard_gate=True,
            detail=f"{false_unblock_count}/{under_spec_total} false-unblock event(s)",
            evidence_refs=false_unblock_refs[:20],
        )

    def _gate_schema_validity(self, traces: list[Any]) -> PlannerMetric:
        """Outputs must conform to capability schema (no violations)."""
        violations: list[str] = []
        for t in traces:
            artifacts = getattr(t, "artifacts", None) or {}
            schema_errors = artifacts.get("schema_errors", [])
            if schema_errors:
                violations.append(str(getattr(t, "trace_id", "")))

        ok = len(violations) == 0
        return PlannerMetric(
            name="planner.schema_validity",
            raw=float(len(violations)),
            score=1.0 if ok else 0.0,
            status="PASS" if ok else "FAIL",
            hard_gate=True,
            detail=f"{len(violations)} trace(s) with schema violations",
            evidence_refs=violations[:20],
        )

    def _gate_no_oos_intentions(self, traces: list[Any]) -> PlannerMetric:
        """PLAN step: no intention targets outside slice scope."""
        scoped_plan_traces, oos_refs = self._collect_out_of_scope_traces(traces)
        oos_count = len(oos_refs)
        ok = len(oos_refs) == 0
        return PlannerMetric(
            name="planner.no_oos_intentions",
            raw=float(oos_count),
            score=1.0 if ok else 0.0,
            status="PASS" if ok else "FAIL",
            hard_gate=True,
            detail=f"{oos_count}/{scoped_plan_traces} scoped PLAN trace(s) out-of-scope",
            evidence_refs=oos_refs[:20],
        )

    # ------------------------------------------------------------------
    # Soft signals
    # ------------------------------------------------------------------

    def _compute_soft_signals(
        self,
        verdicts: list[Any],
        traces: list[Any],
    ) -> list[PlannerMetric]:
        signals: list[PlannerMetric] = [
            # Stable cross-run comparison contract (SEC-016)
            self._signal_under_spec_safety_rate(verdicts),
            self._signal_must_include_coverage(verdicts),
            self._signal_out_of_scope_rate(traces),
            self._signal_unsafe_resolution_rate(verdicts),
            self._signal_evidence_first_rate(traces),
            self._signal_tokens_per_decision(traces),
            self._signal_latency_per_decision(traces),
            self._signal_iterations_per_slice(traces),
            self._signal_demotions_per_slice(),
            # Additional diagnostics
            self._signal_resolve_accuracy(verdicts),
            self._signal_gap_recall(verdicts),
            self._signal_gap_precision(verdicts),
            self._signal_plan_redundancy(verdicts),
            self._signal_integration_risk_recall(verdicts),
            self._signal_block_when_uncertain_rate(traces),
            self._signal_model_calls_p50(traces),
            self._signal_model_calls_p95(traces),
            self._signal_tokens_per_decision_p50(traces),
            self._signal_tokens_per_decision_p95(traces),
            self._signal_tool_calls_per_decision(traces),
            self._signal_web_escalation_rate(traces),
            self._signal_integration_tool_used_rate(traces),
            self._signal_iterations_per_slice_delta_vs_baseline(traces),
            self._signal_demotion_rate_delta_vs_baseline(traces),
        ]
        deduped: dict[str, PlannerMetric] = {}
        for metric in signals:
            deduped[metric.name] = metric
        return list(deduped.values())

    # -- Decision quality --

    def _signal_resolve_accuracy(self, verdicts: list[Any]) -> PlannerMetric:
        """PASS >= 0.9, WARN >= 0.75, FAIL < 0.75."""
        resolve_verdicts = [
            v for v in verdicts if str(getattr(v, "capability", "")).lower() == "resolve_signal"
        ]
        if not resolve_verdicts:
            return PlannerMetric(
                name="planner.resolve_signal.accuracy",
                raw=1.0,
                score=1.0,
                status="PASS",
                detail="No RESOLVE_SIGNAL verdicts",
            )

        correct = sum(1 for v in resolve_verdicts if getattr(v, "passed", False))
        accuracy = correct / len(resolve_verdicts)
        return PlannerMetric(
            name="planner.resolve_signal.accuracy",
            raw=accuracy,
            score=accuracy,
            status=_threshold_gte(accuracy, pass_=0.9, warn=0.75),
            detail=f"{correct}/{len(resolve_verdicts)} correct",
        )

    def _signal_gap_recall(self, verdicts: list[Any]) -> PlannerMetric:
        """PASS >= 0.9, WARN >= 0.75, FAIL < 0.75."""
        return self._aggregate_verdict_score(
            verdicts,
            capability="gap",
            metric_name="planner.gap.recall",
            score_key="recall",
            pass_=0.9,
            warn=0.75,
        )

    def _signal_gap_precision(self, verdicts: list[Any]) -> PlannerMetric:
        """PASS >= 0.9, WARN >= 0.75, FAIL < 0.75."""
        return self._aggregate_verdict_score(
            verdicts,
            capability="gap",
            metric_name="planner.gap.precision",
            score_key="precision",
            pass_=0.9,
            warn=0.75,
        )

    def _signal_must_include_coverage(self, verdicts: list[Any]) -> PlannerMetric:
        """must_include recall. PASS >= 0.9, WARN >= 0.75, FAIL < 0.75."""
        return self._aggregate_verdict_score(
            verdicts,
            capability="plan",
            metric_name="planner.must_include_coverage",
            score_key="coverage",
            pass_=0.9,
            warn=0.75,
        )

    def _signal_plan_redundancy(self, verdicts: list[Any]) -> PlannerMetric:
        """PASS <= 0.05, WARN <= 0.15, FAIL > 0.15."""
        plan_verdicts = [v for v in verdicts if str(getattr(v, "capability", "")).lower() == "plan"]
        if not plan_verdicts:
            return PlannerMetric(
                name="planner.plan.redundancy",
                raw=0.0,
                score=1.0,
                status="PASS",
                detail="No PLAN verdicts",
            )

        # Extract redundancy from verdict detail or soft_signal_warnings
        redundancy_values: list[float] = []
        for v in plan_verdicts:
            detail = getattr(v, "detail", "") or ""
            # Try to parse redundancy=X.XX from detail string
            rate = _extract_float_from_detail(detail, "redundancy")
            if rate is not None:
                redundancy_values.append(rate)

        if not redundancy_values:
            # Fall back: use (1 - score) as proxy for redundancy
            scores = [getattr(v, "score", 1.0) for v in plan_verdicts]
            avg_score = sum(scores) / len(scores) if scores else 1.0
            redundancy = max(0.0, 1.0 - avg_score)
        else:
            redundancy = sum(redundancy_values) / len(redundancy_values)

        return PlannerMetric(
            name="planner.plan.redundancy",
            raw=redundancy,
            score=max(0.0, 1.0 - redundancy),
            status=_threshold_lte(redundancy, pass_=0.05, warn=0.15),
            detail=f"redundancy={redundancy:.3f}",
        )

    def _signal_integration_risk_recall(self, verdicts: list[Any]) -> PlannerMetric:
        """PASS >= 0.9, WARN >= 0.75, FAIL < 0.75."""
        return self._aggregate_verdict_score(
            verdicts,
            capability="integration_analysis",
            metric_name="planner.integration.risk_recall",
            score_key="risk_recall",
            pass_=0.9,
            warn=0.75,
        )

    # -- Epistemic hygiene --

    def _signal_under_spec_safety_rate(self, verdicts: list[Any]) -> PlannerMetric:
        """False-unblock rate for UNDER_SPEC decisions (target: 0)."""
        under_spec_total, false_unblock_count, refs = self._collect_under_spec_safety_counts(
            verdicts
        )
        rate = false_unblock_count / max(under_spec_total, 1)
        return PlannerMetric(
            name="planner.under_spec_safety",
            raw=rate,
            score=max(0.0, 1.0 - rate),
            status=_threshold_lte(rate, pass_=0.0, warn=0.01),
            detail=f"{false_unblock_count}/{under_spec_total} false-unblock events",
            evidence_refs=refs[:20],
        )

    def _signal_out_of_scope_rate(self, traces: list[Any]) -> PlannerMetric:
        """Rate of PLAN traces with out-of-scope intentions (target: 0)."""
        scoped_plan_traces, oos_refs = self._collect_out_of_scope_traces(traces)
        rate = len(oos_refs) / max(scoped_plan_traces, 1)
        return PlannerMetric(
            name="planner.out_of_scope_rate",
            raw=rate,
            score=max(0.0, 1.0 - rate),
            status=_threshold_lte(rate, pass_=0.0, warn=0.01),
            detail=f"{len(oos_refs)}/{scoped_plan_traces} scoped PLAN traces out-of-scope",
            evidence_refs=oos_refs[:20],
        )

    def _signal_unsafe_resolution_rate(self, verdicts: list[Any]) -> PlannerMetric:
        """PASS = 0, WARN <= 0.01, FAIL > 0.01.

        Unsafe resolution = resolving without citing evidence when GT says
        evidence was needed. Derived from verdicts that have
        ``soft_signal_warnings`` containing ``unsafe_resolution``.
        """
        total = len(verdicts) if verdicts else 1
        unsafe_count = 0
        refs: list[str] = []
        for v in verdicts:
            warnings = getattr(v, "soft_signal_warnings", []) or []
            for w in warnings:
                if "unsafe_resolution" in str(w).lower():
                    unsafe_count += 1
                    refs.append(getattr(v, "trace_id", "") or getattr(v, "decision_key", ""))
                    break

        rate = unsafe_count / max(total, 1)
        return PlannerMetric(
            name="planner.unsafe_resolution_rate",
            raw=rate,
            score=max(0.0, 1.0 - rate),
            status=_threshold_lte(rate, pass_=0.0, warn=0.01),
            detail=f"{unsafe_count}/{total} unsafe resolutions",
            evidence_refs=refs[:20],
        )

    def _signal_evidence_first_rate(self, traces: list[Any]) -> PlannerMetric:
        """PASS >= 0.9, WARN >= 0.75, FAIL < 0.75.

        A decision is evidence-first if at least one tool call (evidence
        retrieval) was made before the final model call that produced the
        decision.
        """
        if not traces:
            return PlannerMetric(
                name="planner.evidence_first_rate",
                raw=1.0,
                score=1.0,
                status="PASS",
                detail="No traces",
            )

        evidence_first_count = 0
        for t in traces:
            tool_calls = getattr(t, "tool_calls", 0) or 0
            if isinstance(tool_calls, (list, tuple)):
                tool_calls = len(tool_calls)
            if int(tool_calls) >= 1:
                evidence_first_count += 1

        rate = evidence_first_count / len(traces)
        return PlannerMetric(
            name="planner.evidence_first_rate",
            raw=rate,
            score=rate,
            status=_threshold_gte(rate, pass_=0.9, warn=0.75),
            detail=f"{evidence_first_count}/{len(traces)} decisions used evidence first",
        )

    def _signal_block_when_uncertain_rate(self, traces: list[Any]) -> PlannerMetric:
        """Rate of uncertain UNDER_SPEC decisions that remained blocked."""
        uncertain_total = 0
        blocked_count = 0
        refs: list[str] = []

        for trace in traces:
            if self._trace_capability(trace) != "UNDER_SPEC":
                continue
            outputs = self._trace_outputs(trace)
            questions = outputs.get("questions", [])
            constraints = outputs.get("constraints", {})
            uncertain = bool(questions) or not bool(constraints)
            if not uncertain:
                continue
            uncertain_total += 1
            blocked = bool(outputs.get("blocked", False))
            if blocked:
                blocked_count += 1
                continue
            refs.append(str(getattr(trace, "trace_id", "")))

        if uncertain_total == 0:
            return PlannerMetric(
                name="planner.block_when_uncertain_rate",
                raw=1.0,
                score=1.0,
                status="PASS",
                detail="No uncertain UNDER_SPEC traces",
            )

        rate = blocked_count / uncertain_total
        return PlannerMetric(
            name="planner.block_when_uncertain_rate",
            raw=rate,
            score=rate,
            status=_threshold_gte(rate, pass_=0.9, warn=0.75),
            detail=f"{blocked_count}/{uncertain_total} uncertain UNDER_SPEC traces blocked",
            evidence_refs=refs[:20],
        )

    # -- Efficiency --

    def _signal_tokens_per_decision(self, traces: list[Any]) -> PlannerMetric:
        """Average token consumption per decision (informational)."""
        if not traces:
            return PlannerMetric(
                name="planner.tokens_per_decision",
                raw=0.0,
                score=1.0,
                status="PASS",
                detail="No traces",
            )
        totals = [self._trace_tokens_and_latency(t)[0] for t in traces]
        avg_tokens = sum(totals) / len(totals)
        return PlannerMetric(
            name="planner.tokens_per_decision",
            raw=avg_tokens,
            score=1.0,
            status="PASS",
            detail=f"avg={avg_tokens:.1f} across {len(traces)} decisions",
        )

    def _signal_tokens_per_decision_p50(self, traces: list[Any]) -> PlannerMetric:
        """P50 token consumption per decision (informational)."""
        if not traces:
            return PlannerMetric(
                name="planner.tokens_per_decision_p50",
                raw=0.0,
                score=1.0,
                status="PASS",
                detail="No traces",
            )
        totals = [float(self._trace_tokens_and_latency(t)[0]) for t in traces]
        p50 = _percentile(totals, 50)
        return PlannerMetric(
            name="planner.tokens_per_decision_p50",
            raw=p50,
            score=1.0,
            status="PASS",
            detail=f"p50={p50:.1f} across {len(traces)} decisions",
        )

    def _signal_tokens_per_decision_p95(self, traces: list[Any]) -> PlannerMetric:
        """P95 token consumption per decision (informational)."""
        if not traces:
            return PlannerMetric(
                name="planner.tokens_per_decision_p95",
                raw=0.0,
                score=1.0,
                status="PASS",
                detail="No traces",
            )
        totals = [float(self._trace_tokens_and_latency(t)[0]) for t in traces]
        p95 = _percentile(totals, 95)
        return PlannerMetric(
            name="planner.tokens_per_decision_p95",
            raw=p95,
            score=1.0,
            status="PASS",
            detail=f"p95={p95:.1f} across {len(traces)} decisions",
        )

    def _signal_latency_per_decision(self, traces: list[Any]) -> PlannerMetric:
        """Average planner latency in milliseconds per decision (informational)."""
        if not traces:
            return PlannerMetric(
                name="planner.latency_per_decision",
                raw=0.0,
                score=1.0,
                status="PASS",
                detail="No traces",
            )
        latencies = [self._trace_tokens_and_latency(t)[1] for t in traces]
        avg_latency_ms = sum(latencies) / len(latencies)
        return PlannerMetric(
            name="planner.latency_per_decision",
            raw=avg_latency_ms,
            score=1.0,
            status="PASS",
            detail=f"avg={avg_latency_ms:.1f}ms across {len(traces)} decisions",
        )

    def _signal_model_calls_p50(self, traces: list[Any]) -> PlannerMetric:
        """PASS <= 3, WARN <= 6, FAIL > 6."""
        counts = self._extract_model_call_counts(traces)
        p50 = _percentile(counts, 50)
        return PlannerMetric(
            name="planner.model_calls_per_decision_p50",
            raw=p50,
            score=max(0.0, 1.0 - p50 / 10.0),
            status=_threshold_lte(p50, pass_=3.0, warn=6.0),
            detail=f"p50={p50:.1f} across {len(counts)} decisions",
        )

    def _signal_model_calls_p95(self, traces: list[Any]) -> PlannerMetric:
        """PASS <= 6, WARN <= 10, FAIL > 10."""
        counts = self._extract_model_call_counts(traces)
        p95 = _percentile(counts, 95)
        return PlannerMetric(
            name="planner.model_calls_per_decision_p95",
            raw=p95,
            score=max(0.0, 1.0 - p95 / 15.0),
            status=_threshold_lte(p95, pass_=6.0, warn=10.0),
            detail=f"p95={p95:.1f} across {len(counts)} decisions",
        )

    def _signal_tool_calls_per_decision(self, traces: list[Any]) -> PlannerMetric:
        """PASS >= 1, WARN >= 0.5, FAIL < 0.5."""
        if not traces:
            return PlannerMetric(
                name="planner.tool_calls_per_decision",
                raw=0.0,
                score=0.0,
                status="FAIL",
                detail="No traces",
            )

        total_tool_calls = 0
        for t in traces:
            tc = getattr(t, "tool_calls", 0) or 0
            if isinstance(tc, (list, tuple)):
                tc = len(tc)
            total_tool_calls += int(tc)

        avg = total_tool_calls / len(traces)
        return PlannerMetric(
            name="planner.tool_calls_per_decision",
            raw=avg,
            score=min(1.0, avg),
            status=_threshold_gte(avg, pass_=1.0, warn=0.5),
            detail=f"avg={avg:.2f} across {len(traces)} decisions",
        )

    def _signal_web_escalation_rate(self, traces: list[Any]) -> PlannerMetric:
        """Rate of decisions that escalated to web tooling (informational)."""
        if not traces:
            return PlannerMetric(
                name="planner.web_escalation_rate",
                raw=0.0,
                score=1.0,
                status="PASS",
                detail="No traces",
            )
        escalated = 0
        refs: list[str] = []
        for trace in traces:
            tool_calls = getattr(trace, "tool_calls", []) or []
            if any(self._is_web_tool_call(call) for call in tool_calls if isinstance(call, dict)):
                escalated += 1
                refs.append(str(getattr(trace, "trace_id", "")))

        rate = escalated / len(traces)
        return PlannerMetric(
            name="planner.web_escalation_rate",
            raw=rate,
            score=1.0,
            status="PASS",
            detail=f"{escalated}/{len(traces)} decisions used web tools",
            evidence_refs=refs[:20],
        )

    def _signal_integration_tool_used_rate(self, traces: list[Any]) -> PlannerMetric:
        """Rate of L2/L3 traces that used at least one tool call."""
        candidate_traces = [trace for trace in traces if self._trace_layer(trace) in {"L2", "L3"}]
        if not candidate_traces:
            return PlannerMetric(
                name="planner.integration_tool_used_rate",
                raw=1.0,
                score=1.0,
                status="PASS",
                detail="No L2/L3 traces",
            )

        used = 0
        refs: list[str] = []
        for trace in candidate_traces:
            tool_calls = getattr(trace, "tool_calls", []) or []
            if len(tool_calls) > 0:
                used += 1
            else:
                refs.append(str(getattr(trace, "trace_id", "")))

        rate = used / len(candidate_traces)
        return PlannerMetric(
            name="planner.integration_tool_used_rate",
            raw=rate,
            score=rate,
            status=_threshold_gte(rate, pass_=0.9, warn=0.75),
            detail=f"{used}/{len(candidate_traces)} L2/L3 decisions used tools",
            evidence_refs=refs[:20],
        )

    # -- Convergence (informational) --

    def _signal_iterations_per_slice(self, traces: list[Any]) -> PlannerMetric:
        """Informational: no threshold, always PASS."""
        # Group traces by slice
        slice_iterations: dict[str, int] = {}
        for t in traces:
            dk = str(getattr(t, "decision_key", ""))
            # decision_key format: {layer}:{capability}:{slice_id}:{iteration}:{hash}
            parts = dk.split(":")
            slice_id = parts[2] if len(parts) > 2 else dk
            iteration = 1
            if len(parts) > 3:
                with contextlib.suppress(ValueError, TypeError):
                    iteration = int(parts[3])
            current = slice_iterations.get(slice_id, 0)
            slice_iterations[slice_id] = max(current, iteration)

        if not slice_iterations:
            avg_iter = 0.0
        else:
            avg_iter = sum(slice_iterations.values()) / len(slice_iterations)

        return PlannerMetric(
            name="planner.iterations_per_slice",
            raw=avg_iter,
            score=1.0,  # informational
            status="PASS",  # informational, no threshold
            detail=f"avg={avg_iter:.1f} across {len(slice_iterations)} slice(s)",
        )

    def _signal_demotions_per_slice(self) -> PlannerMetric:
        """Average demotion tickets per slice for this run (informational)."""
        demotions_root = self._workspace / ".pdd_runs" / self._run_id / "demotions" / "tickets"
        if not self._run_id:
            return PlannerMetric(
                name="planner.demotions_per_slice",
                raw=0.0,
                score=1.0,
                status="PASS",
                detail="Run ID unavailable",
            )
        if not demotions_root.exists():
            return PlannerMetric(
                name="planner.demotions_per_slice",
                raw=0.0,
                score=1.0,
                status="PASS",
                detail="No demotion tickets",
            )

        total = 0
        by_slice: dict[str, int] = {}
        parse_failures: list[str] = []
        for ticket_path in sorted(demotions_root.glob("*.json")):
            try:
                payload = json.loads(ticket_path.read_text(encoding="utf-8"))
            except OSError as exc:
                parse_failures.append(f"unreadable:{ticket_path}:{exc}")
                logger.warning("Could not read demotion ticket %s: %s", ticket_path, exc)
                continue
            except json.JSONDecodeError as exc:
                parse_failures.append(f"invalid_json:{ticket_path}:{exc}")
                logger.warning("Could not parse demotion ticket %s: %s", ticket_path, exc)
                continue
            ticket = payload.get("ticket", {})
            if not isinstance(ticket, dict):
                parse_failures.append(f"invalid_ticket_payload:{ticket_path}")
                continue
            slice_id = str(ticket.get("slice_id", "") or "(unknown)")
            by_slice[slice_id] = by_slice.get(slice_id, 0) + 1
            total += 1

        if not by_slice:
            failure_note = f"; parse_failures={len(parse_failures)}" if parse_failures else ""
            return PlannerMetric(
                name="planner.demotions_per_slice",
                raw=0.0,
                score=1.0,
                status="PASS",
                detail=f"No parseable demotion tickets{failure_note}",
                evidence_refs=parse_failures[:20],
            )

        avg_demotions = total / len(by_slice)
        top_slices = sorted(by_slice.items(), key=lambda item: item[1], reverse=True)[:3]
        top_desc = ", ".join(f"{slice_id}:{count}" for slice_id, count in top_slices)
        failure_note = f"; parse_failures={len(parse_failures)}" if parse_failures else ""
        return PlannerMetric(
            name="planner.demotions_per_slice",
            raw=avg_demotions,
            score=1.0,
            status="PASS",
            detail=(
                f"avg={avg_demotions:.2f} across {len(by_slice)} slice(s); top={top_desc}"
                f"{failure_note}"
            ),
            evidence_refs=parse_failures[:20],
        )

    def _signal_iterations_per_slice_delta_vs_baseline(self, traces: list[Any]) -> PlannerMetric:
        """Delta in iterations-per-slice versus baseline run when available."""
        metric_name = "planner.iterations_per_slice_delta_vs_baseline"
        current = self._signal_iterations_per_slice(traces).raw
        baseline = self._baseline_metric_raw(traces, "planner.iterations_per_slice")
        if baseline is None:
            issue_detail = (
                f"; baseline_error={self._baseline_load_issue}" if self._baseline_load_issue else ""
            )
            return PlannerMetric(
                name=metric_name,
                raw=0.0,
                score=1.0,
                status="PASS",
                detail=(
                    f"Baseline unavailable; current iterations_per_slice={current:.2f} "
                    f"used as interim reference{issue_detail}"
                ),
            )

        delta = current - baseline
        return PlannerMetric(
            name=metric_name,
            raw=delta,
            score=1.0,
            status="PASS",
            detail=f"current={current:.2f}, baseline={baseline:.2f}, delta={delta:+.2f}",
        )

    def _signal_demotion_rate_delta_vs_baseline(self, traces: list[Any]) -> PlannerMetric:
        """Delta in demotions-per-slice versus baseline run when available."""
        metric_name = "planner.demotion_rate_delta_vs_baseline"
        current = self._signal_demotions_per_slice().raw
        baseline = self._baseline_metric_raw(traces, "planner.demotions_per_slice")
        if baseline is None:
            issue_detail = (
                f"; baseline_error={self._baseline_load_issue}" if self._baseline_load_issue else ""
            )
            return PlannerMetric(
                name=metric_name,
                raw=0.0,
                score=1.0,
                status="PASS",
                detail=(
                    f"Baseline unavailable; current demotions_per_slice={current:.2f} "
                    f"used as interim reference{issue_detail}"
                ),
            )

        delta = current - baseline
        return PlannerMetric(
            name=metric_name,
            raw=delta,
            score=1.0,
            status="PASS",
            detail=f"current={current:.2f}, baseline={baseline:.2f}, delta={delta:+.2f}",
        )

    def _compute_slice_aggregates(
        self,
        verdicts: list[Any],
        traces: list[Any],
    ) -> list[PlannerSliceAggregate]:
        """Build per-slice evaluation aggregates from traces and verdicts."""
        totals_by_slice: dict[str, int] = {}
        for trace in traces:
            slice_id = self._slice_id_for_record(trace)
            totals_by_slice[slice_id] = totals_by_slice.get(slice_id, 0) + 1

        evaluated_by_slice: dict[str, int] = {}
        passed_by_slice: dict[str, int] = {}
        for verdict in verdicts:
            slice_id = self._slice_id_for_record(verdict)
            evaluated_by_slice[slice_id] = evaluated_by_slice.get(slice_id, 0) + 1
            if bool(getattr(verdict, "passed", False)):
                passed_by_slice[slice_id] = passed_by_slice.get(slice_id, 0) + 1

        slice_ids = sorted(set(totals_by_slice) | set(evaluated_by_slice))
        aggregates: list[PlannerSliceAggregate] = []
        for slice_id in slice_ids:
            decisions_total = totals_by_slice.get(slice_id, 0)
            decisions_evaluated = evaluated_by_slice.get(slice_id, 0)
            decisions_passed = passed_by_slice.get(slice_id, 0)
            decisions_failed = max(decisions_evaluated - decisions_passed, 0)
            pass_rate = decisions_passed / decisions_evaluated if decisions_evaluated > 0 else 0.0
            aggregates.append(
                PlannerSliceAggregate(
                    slice_id=slice_id,
                    decisions_total=decisions_total,
                    decisions_evaluated=decisions_evaluated,
                    decisions_passed=decisions_passed,
                    decisions_failed=decisions_failed,
                    pass_rate=pass_rate,
                )
            )

        return aggregates

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _aggregate_verdict_score(
        self,
        verdicts: list[Any],
        *,
        capability: str,
        metric_name: str,
        score_key: str,
        pass_: float,
        warn: float,
    ) -> PlannerMetric:
        """Average a named score across verdicts for a given capability.

        Looks for the *score_key* in the verdict's ``detail`` string
        (format ``key=value``) or falls back to the verdict's ``.score``
        attribute.
        """
        cap_verdicts = [
            v for v in verdicts if str(getattr(v, "capability", "")).lower() == capability.lower()
        ]
        if not cap_verdicts:
            return PlannerMetric(
                name=metric_name,
                raw=1.0,
                score=1.0,
                status="PASS",
                detail=f"No {capability.upper()} verdicts",
            )

        values: list[float] = []
        for v in cap_verdicts:
            detail = getattr(v, "detail", "") or ""
            extracted = _extract_float_from_detail(detail, score_key)
            if extracted is not None:
                values.append(extracted)
            else:
                values.append(float(getattr(v, "score", 0.0)))

        avg = sum(values) / len(values) if values else 0.0
        return PlannerMetric(
            name=metric_name,
            raw=avg,
            score=avg,
            status=_threshold_gte(avg, pass_=pass_, warn=warn),
            detail=f"{score_key}={avg:.3f} across {len(cap_verdicts)} verdicts",
        )

    @staticmethod
    def _extract_model_call_counts(traces: list[Any]) -> list[float]:
        """Extract model_calls count from each trace."""
        counts: list[float] = []
        for t in traces:
            mc = getattr(t, "model_calls", 0) or 0
            if isinstance(mc, (list, tuple)):
                mc = len(mc)
            counts.append(float(mc))
        return counts

    @staticmethod
    def _trace_capability(trace: Any) -> str:
        """Resolve capability from decision key or request snapshot."""
        decision_key = str(getattr(trace, "decision_key", "") or "")
        if decision_key:
            parts = decision_key.split(":")
            if len(parts) > 1 and parts[1]:
                return str(parts[1]).upper()
        request = getattr(trace, "request", None)
        if isinstance(request, dict):
            cap = str(request.get("capability", "") or "")
            if cap:
                return cap.upper()
        return ""

    @classmethod
    def _trace_layer(cls, trace: Any) -> str:
        """Resolve layer from decision key or request snapshot."""
        decision_key = str(getattr(trace, "decision_key", "") or "")
        if decision_key:
            parts = decision_key.split(":")
            if parts and parts[0]:
                return str(parts[0]).upper()
        request = getattr(trace, "request", None)
        if isinstance(request, dict):
            layer = str(request.get("layer", "") or "")
            if layer:
                return layer.upper()
        return ""

    @staticmethod
    def _trace_outputs(trace: Any) -> dict[str, Any]:
        """Resolve structured outputs from planner artifacts."""
        artifacts = getattr(trace, "artifacts", None) or {}
        outputs = artifacts.get("outputs", {})
        if isinstance(outputs, dict):
            return outputs
        return {}

    @classmethod
    def _collect_out_of_scope_traces(cls, traces: list[Any]) -> tuple[int, list[str]]:
        """Return (scoped PLAN trace count, out-of-scope trace refs)."""
        scoped_plan_traces = 0
        oos_refs: list[str] = []
        for trace in traces:
            if cls._trace_capability(trace) != "PLAN":
                continue

            artifacts = getattr(trace, "artifacts", None) or {}
            outputs = artifacts.get("outputs", {}) or {}
            if not isinstance(outputs, dict):
                continue
            intentions = outputs.get("intentions", []) or []
            scope_files = set(outputs.get("scope_files", []) or [])
            scope_functions = set(outputs.get("scope_functions", []) or [])

            # If scope info is absent, this trace cannot be evaluated.
            if not scope_files and not scope_functions:
                continue
            scoped_plan_traces += 1

            for intention in intentions:
                if not isinstance(intention, dict):
                    continue
                target_file = str(intention.get("file", "") or "")
                target_fn = str(intention.get("function_name", "") or "")
                out_of_scope = False
                if scope_files and target_file and target_file not in scope_files:
                    out_of_scope = True
                if scope_functions and target_fn and target_fn not in scope_functions:
                    out_of_scope = True
                if out_of_scope:
                    oos_refs.append(str(getattr(trace, "trace_id", "")))
                    break
        return scoped_plan_traces, oos_refs

    @staticmethod
    def _collect_under_spec_safety_counts(verdicts: list[Any]) -> tuple[int, int, list[str]]:
        """Return (under_spec verdict count, false-unblock count, refs)."""
        under_spec_total = 0
        false_unblock_refs: list[str] = []
        for verdict in verdicts:
            capability = str(getattr(verdict, "capability", "") or "").lower()
            if capability != "under_spec":
                continue
            under_spec_total += 1
            failures = getattr(verdict, "hard_gate_failures", []) or []
            for failure in failures:
                if "false_unblock" in str(failure).lower():
                    false_unblock_refs.append(
                        getattr(verdict, "trace_id", "") or getattr(verdict, "decision_key", "")
                    )
                    break
        return under_spec_total, len(false_unblock_refs), false_unblock_refs

    @staticmethod
    def _is_web_tool_call(call: dict[str, Any]) -> bool:
        """Best-effort web-tool classifier based on tool metadata."""
        tool_name = str(call.get("tool_name", "") or "").lower()
        if any(
            token in tool_name
            for token in ("web", "search", "browser", "http", "serp", "firecrawl")
        ):
            return True
        params = call.get("tool_params")
        if isinstance(params, dict):
            for key in ("url", "urls", "domain", "domains"):
                value = params.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return True
                if isinstance(value, list) and any(
                    isinstance(item, str) and item.startswith(("http://", "https://"))
                    for item in value
                ):
                    return True
        return False

    def _baseline_metric_raw(self, traces: list[Any], metric_name: str) -> float | None:
        """Load baseline metric raw value when baseline scorecard is available."""
        baseline_scorecard = self._load_baseline_scorecard(traces)
        if not baseline_scorecard:
            return None
        metrics: list[dict[str, Any]] = []
        hard_gates = baseline_scorecard.get("hard_gates")
        soft_signals = baseline_scorecard.get("soft_signals")
        if isinstance(hard_gates, list):
            metrics.extend(item for item in hard_gates if isinstance(item, dict))
        if isinstance(soft_signals, list):
            metrics.extend(item for item in soft_signals if isinstance(item, dict))

        for metric in metrics:
            if str(metric.get("name", "") or "") != metric_name:
                continue
            raw = metric.get("raw")
            if isinstance(raw, (int, float)):
                return float(raw)
            return None
        return None

    def _load_baseline_scorecard(self, traces: list[Any]) -> dict[str, Any] | None:
        """Return baseline planner scorecard JSON when trace metadata provides a run id."""
        baseline_run_id = ""
        for trace in traces:
            request = getattr(trace, "request", None)
            if not isinstance(request, dict):
                continue
            for key in ("baseline_run_id", "reference_run_id", "comparison_run_id"):
                candidate = str(request.get(key, "") or "").strip()
                if candidate:
                    baseline_run_id = candidate
                    break
            if baseline_run_id:
                break

        if not baseline_run_id:
            return None

        path = self._workspace / "reports" / "pdd" / baseline_run_id / "planner_scorecard.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            self._baseline_load_issue = f"unreadable:{path}:{exc}"
            logger.warning("Unable to read baseline scorecard %s: %s", path, exc)
            return None
        except json.JSONDecodeError as exc:
            self._baseline_load_issue = f"invalid_json:{path}:{exc}"
            logger.warning("Unable to parse baseline scorecard %s: %s", path, exc)
            return None
        if isinstance(payload, dict):
            return payload
        self._baseline_load_issue = f"invalid_payload:{path}:top-level is not an object"
        logger.warning("Baseline scorecard %s is not a JSON object", path)
        return None

    @staticmethod
    def _trace_tokens_and_latency(trace: Any) -> tuple[int, float]:
        """Return aggregate token usage and latency for a trace."""

        def _safe_int(value: Any) -> int:
            try:
                return max(int(value or 0), 0)
            except (TypeError, ValueError):
                return 0

        def _safe_float(value: Any) -> float:
            try:
                return max(float(value or 0.0), 0.0)
            except (TypeError, ValueError):
                return 0.0

        model_calls = getattr(trace, "model_calls", []) or []
        tool_calls = getattr(trace, "tool_calls", []) or []

        token_total = 0
        model_latency_ms = 0.0
        tool_latency_ms = 0.0

        for call in model_calls:
            if not isinstance(call, dict):
                continue
            token_total += _safe_int(call.get("tokens_in")) + _safe_int(call.get("tokens_out"))
            model_latency_ms += _safe_float(call.get("duration_ms"))

        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            token_total += _safe_int(call.get("tokens_in")) + _safe_int(call.get("tokens_out"))
            tool_latency_ms += _safe_float(call.get("duration_ms"))

        # Model-call duration is the authoritative decision wall-clock metric.
        latency_ms = model_latency_ms if model_calls else tool_latency_ms
        if latency_ms <= 0.0 and tool_latency_ms > 0.0:
            latency_ms = tool_latency_ms

        return token_total, latency_ms

    @staticmethod
    def _slice_id_for_record(record: Any) -> str:
        """Extract slice_id from decision_key or fallback fields."""
        decision_key = str(getattr(record, "decision_key", "") or "")
        if decision_key:
            parts = decision_key.split(":")
            if len(parts) > 2 and parts[2]:
                return parts[2]

        request = getattr(record, "request", None)
        if isinstance(request, dict):
            slice_id = str(request.get("slice_id", "") or "")
            if slice_id:
                return slice_id

        return "(unknown)"

    @staticmethod
    def _verdict_to_row(verdict: Any) -> dict[str, Any]:
        """Serialize a verdict for planner_decisions.jsonl output."""
        raw_score = getattr(verdict, "score", 0.0)
        try:
            score = float(raw_score or 0.0)
        except (TypeError, ValueError):
            score = 0.0

        return {
            "decision_key": str(getattr(verdict, "decision_key", "") or ""),
            "trace_id": str(getattr(verdict, "trace_id", "") or ""),
            "capability": str(getattr(verdict, "capability", "") or ""),
            "passed": bool(getattr(verdict, "passed", False)),
            "score": score,
            "detail": str(getattr(verdict, "detail", "") or ""),
            "hard_gate_failures": list(getattr(verdict, "hard_gate_failures", []) or []),
            "soft_signal_warnings": list(getattr(verdict, "soft_signal_warnings", []) or []),
        }

    def _verdicts_by_trace_id(self) -> dict[str, Any]:
        by_id: dict[str, Any] = {}
        for verdict in self._last_verdicts:
            trace_id = str(getattr(verdict, "trace_id", "") or "")
            if trace_id:
                by_id[trace_id] = verdict
        return by_id

    def _trace_paths_by_id(self, traces: list[Any]) -> dict[str, str]:
        by_id: dict[str, str] = {}
        for trace in traces:
            trace_id = str(getattr(trace, "trace_id", "") or "")
            if not trace_id:
                continue
            request_path = str(getattr(trace, "request_path", "") or "")
            if request_path:
                trace_path = Path(request_path).parent
                with contextlib.suppress(ValueError):
                    trace_path = trace_path.resolve().relative_to(self._workspace.resolve())
                by_id[trace_id] = str(trace_path)
                continue
            by_id[trace_id] = str(Path("analysis") / "planner_traces" / trace_id)
        return by_id

    @classmethod
    def _eval_row(cls, *, trace: Any, verdict_by_trace_id: dict[str, Any]) -> dict[str, Any]:
        trace_id = str(getattr(trace, "trace_id", "") or "")
        verdict = verdict_by_trace_id.get(trace_id)
        verdict_row = cls._verdict_to_row(verdict) if verdict is not None else None

        artifacts = getattr(trace, "artifacts", {}) or {}
        outputs = artifacts.get("outputs")
        if not isinstance(outputs, dict):
            outputs = artifacts.get("override_outputs", {})
        if not isinstance(outputs, dict):
            outputs = {}

        decision_key = str(getattr(trace, "decision_key", "") or "")
        capability = ""
        if decision_key:
            parts = decision_key.split(":")
            if len(parts) > 1:
                capability = parts[1]

        return {
            "trace_id": trace_id,
            "decision_key": decision_key,
            "capability": capability,
            "status": str(getattr(trace, "status", "") or ""),
            "overridden": bool(getattr(trace, "overridden", False)),
            "request": getattr(trace, "request", {}) or {},
            "decision": getattr(trace, "decision", {}) or {},
            "outputs": outputs,
            "model_calls_count": len(getattr(trace, "model_calls", []) or []),
            "tool_calls_count": len(getattr(trace, "tool_calls", []) or []),
            "verdict": verdict_row,
        }

    # ------------------------------------------------------------------
    # Markdown rendering
    # ------------------------------------------------------------------

    @staticmethod
    def _render_markdown(scorecard: PlannerScorecard) -> str:
        """Render scorecard as a human-readable markdown document."""
        ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        lines = [
            f"# Planner Scorecard -- Run {scorecard.run_id}",
            "",
            f"**Generated:** {ts}",
            f"**Model:** {scorecard.model_id or '(unknown)'}",
            f"**Overall:** {'PASS' if scorecard.overall_pass else 'FAIL'}",
            f"**Decisions evaluated:** {scorecard.decisions_evaluated}"
            f" / {scorecard.decisions_total}",
            "",
            f"> {scorecard.summary}",
            "",
            "## Hard Gates",
            "",
            "| Gate | Status | Raw | Detail |",
            "|------|--------|-----|--------|",
        ]
        for g in scorecard.hard_gates:
            lines.append(f"| {g.name} | {g.status} | {g.raw:.2f} | {g.detail} |")

        stable_signals = [
            signal
            for signal in scorecard.soft_signals
            if signal.name in _STABLE_COMPARISON_METRIC_NAMES
        ]
        other_signals = [
            signal
            for signal in scorecard.soft_signals
            if signal.name not in _STABLE_COMPARISON_METRIC_NAMES
        ]

        lines.extend(
            [
                "",
                "## Stable Comparison Metrics",
                "",
                "| Metric | Status | Score (0-100) | Raw | Detail |",
                "|--------|--------|-------|-----|--------|",
            ]
        )
        for signal in stable_signals:
            lines.append(
                f"| {signal.name} | {signal.status} | {signal.score * 100.0:.1f} | "
                f"{signal.raw:.2f} | {signal.detail} |"
            )

        lines.extend(
            [
                "",
                "## Additional Soft Signals",
                "",
                "| Signal | Status | Score (0-100) | Raw | Detail |",
                "|--------|--------|-------|-----|--------|",
            ]
        )
        for signal in other_signals:
            lines.append(
                f"| {signal.name} | {signal.status} | {signal.score * 100.0:.1f} | "
                f"{signal.raw:.2f} | {signal.detail} |"
            )

        lines.extend(
            [
                "",
                "## Slice Aggregates",
                "",
                "| Slice | Evaluated | Passed | Failed | Pass Rate | Total Traces |",
                "|-------|-----------|--------|--------|-----------|--------------|",
            ]
        )
        for agg in scorecard.slice_aggregates:
            lines.append(
                f"| {agg.slice_id} | {agg.decisions_evaluated} | {agg.decisions_passed} | "
                f"{agg.decisions_failed} | {agg.pass_rate:.2f} | {agg.decisions_total} |"
            )

        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _render_review(verdicts: list[Any], trace_paths: dict[str, str] | None = None) -> str:
        """Render planner_review.md listing FAIL/WARN/NEEDS_REVIEW decisions.

        Sections:
        - **Failed Decisions**: verdicts with ``passed=False``.
        - **Warnings**: verdicts with non-empty ``soft_signal_warnings``.
        - **Needs Review**: verdicts with ``score < 0.5``.
        """
        lines: list[str] = ["# Planner Review", ""]

        # ---- Failed Decisions ----
        lines.append("## Failed Decisions")
        lines.append("")
        failed = [v for v in verdicts if not getattr(v, "passed", True)]
        if failed:
            for v in failed:
                dk = getattr(v, "decision_key", "")
                cap = getattr(v, "capability", "")
                detail = getattr(v, "detail", "")
                tid = getattr(v, "trace_id", "")
                lines.append(f"- **{dk}** ({cap}): {detail}")
                if tid:
                    lines.append(f"  - trace: `{tid}`")
                    trace_path = (trace_paths or {}).get(str(tid), "")
                    if trace_path:
                        lines.append(f"  - path: `{trace_path}`")
        else:
            lines.append("None.")
        lines.append("")

        # ---- Warnings ----
        lines.append("## Warnings")
        lines.append("")
        warned = [v for v in verdicts if getattr(v, "soft_signal_warnings", None)]
        if warned:
            for v in warned:
                dk = getattr(v, "decision_key", "")
                cap = getattr(v, "capability", "")
                warnings = getattr(v, "soft_signal_warnings", [])
                tid = getattr(v, "trace_id", "")
                lines.append(f"- **{dk}** ({cap}): {', '.join(str(w) for w in warnings)}")
                if tid:
                    lines.append(f"  - trace: `{tid}`")
                    trace_path = (trace_paths or {}).get(str(tid), "")
                    if trace_path:
                        lines.append(f"  - path: `{trace_path}`")
        else:
            lines.append("None.")
        lines.append("")

        # ---- Needs Review ----
        lines.append("## Needs Review")
        lines.append("")
        needs_review = [v for v in verdicts if getattr(v, "score", 1.0) < 0.5]
        if needs_review:
            for v in needs_review:
                dk = getattr(v, "decision_key", "")
                cap = getattr(v, "capability", "")
                score = getattr(v, "score", 0.0)
                detail = getattr(v, "detail", "")
                tid = getattr(v, "trace_id", "")
                lines.append(f"- **{dk}** ({cap}): score={score:.2f} -- {detail}")
                if tid:
                    lines.append(f"  - trace: `{tid}`")
                    trace_path = (trace_paths or {}).get(str(tid), "")
                    if trace_path:
                        lines.append(f"  - path: `{trace_path}`")
        else:
            lines.append("None.")
        lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _threshold_gte(value: float, *, pass_: float, warn: float) -> str:
    """Return status for a metric where higher is better.

    PASS when *value* >= *pass_*, WARN when >= *warn*, else FAIL.
    """
    if value >= pass_:
        return "PASS"
    if value >= warn:
        return "WARN"
    return "FAIL"


def _threshold_lte(value: float, *, pass_: float, warn: float) -> str:
    """Return status for a metric where lower is better.

    PASS when *value* <= *pass_*, WARN when <= *warn*, else FAIL.
    """
    if value <= pass_:
        return "PASS"
    if value <= warn:
        return "WARN"
    return "FAIL"


def _extract_float_from_detail(detail: str, key: str) -> float | None:
    """Extract a float value from a ``key=value`` substring in *detail*.

    Returns ``None`` if the key is not found or cannot be parsed.
    """
    # Look for patterns like "recall=0.95" or "redundancy=0.030"
    pattern = rf"\b{re.escape(key)}\s*=\s*([0-9]*\.?[0-9]+)"
    match = re.search(pattern, detail)
    if match:
        try:
            return float(match.group(1))
        except (ValueError, TypeError):
            return None
    return None
