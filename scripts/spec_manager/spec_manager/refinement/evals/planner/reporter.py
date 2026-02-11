"""Compute and write the PlannerScorecard from trace data and ground truth verdicts.

Produces three output files under ``reports/pdd/{run_id}/``:

- ``planner_scorecard.json`` -- machine-readable scorecard
- ``planner_scorecard.md`` -- human-readable tables
- ``planner_decisions.jsonl`` -- one line per decision with verdict

Hard gates (5) are mechanical pass/fail checks derived from traces:

1. ``planner.trace_integrity`` -- every planner call has request + decision
2. ``planner.no_error_status`` -- zero ERROR-status traces
3. ``planner.under_spec_safety`` -- zero false-unblock events
4. ``planner.schema_validity`` -- all outputs conform to capability schema
5. ``planner.no_oos_intentions`` -- no out-of-scope intentions in PLAN step

Soft signals (~12) are computed from verdicts (GT comparison) and traces
(efficiency / epistemic hygiene).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PlannerMetric:
    """A single planner scorecard metric.

    Attributes:
        name: Dot-separated metric name (e.g. ``planner.trace_integrity``).
        raw: Raw computed value before normalization.
        score: Normalized score between 0.0 and 1.0.
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


@dataclass
class PlannerScorecard:
    """Complete scorecard for a planner evaluation run.

    Attributes:
        run_id: Unique identifier for the evaluation run.
        model_id: Model identifier used for the planner decisions.
        hard_gates: List of hard-gate metrics (all must pass).
        soft_signals: List of soft-signal metrics (diagnostic).
        overall_pass: True when every hard gate has status PASS.
        decisions_evaluated: Number of decisions that had GT verdicts.
        decisions_total: Total number of decision traces loaded.
        summary: Human-readable one-line summary.
    """

    run_id: str = ""
    model_id: str = ""
    hard_gates: list[PlannerMetric] = field(default_factory=list)
    soft_signals: list[PlannerMetric] = field(default_factory=list)
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
        hard_gates = self._compute_hard_gates(verdicts, traces)
        soft_signals = self._compute_soft_signals(verdicts, traces)
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
            overall_pass=overall_pass,
            decisions_evaluated=len(verdicts),
            decisions_total=len(traces),
            summary=" ".join(summary_parts),
        )

    def write(self, scorecard: PlannerScorecard) -> None:
        """Write planner_scorecard.json, planner_scorecard.md, planner_decisions.jsonl.

        All files are written under ``reports/pdd/{run_id}/``.

        Args:
            scorecard: The scorecard to persist.
        """
        self._reports_dir.mkdir(parents=True, exist_ok=True)

        # Machine-readable JSON
        json_path = self._reports_dir / "planner_scorecard.json"
        json_path.write_text(
            json.dumps(scorecard.to_dict(), indent=2),
            encoding="utf-8",
        )

        # Human-readable markdown
        md_path = self._reports_dir / "planner_scorecard.md"
        md_path.write_text(self._render_markdown(scorecard), encoding="utf-8")

        # Per-decision JSONL (verdicts only -- no scorecard-level info)
        jsonl_path = self._reports_dir / "planner_decisions.jsonl"
        lines: list[str] = []
        for m in scorecard.hard_gates + scorecard.soft_signals:
            for ref in m.evidence_refs:
                lines.append(json.dumps({"metric": m.name, "evidence": ref}))
        jsonl_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

        logger.info(
            "Planner scorecard written: json=%s md=%s jsonl=%s",
            json_path,
            md_path,
            jsonl_path,
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
            artifacts = getattr(t, "artifacts", None) or {}
            has_request = bool(artifacts.get("request"))
            has_decision = bool(getattr(t, "decision", None) or artifacts.get("decision"))
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
        false_unblock_refs: list[str] = []
        for v in verdicts:
            cap = getattr(v, "capability", "")
            if str(cap).lower() in ("under_spec",):
                failures = getattr(v, "hard_gate_failures", []) or []
                for f in failures:
                    if "false_unblock" in str(f).lower():
                        false_unblock_refs.append(
                            getattr(v, "trace_id", "") or getattr(v, "decision_key", "")
                        )

        ok = len(false_unblock_refs) == 0
        return PlannerMetric(
            name="planner.under_spec_safety",
            raw=float(len(false_unblock_refs)),
            score=1.0 if ok else 0.0,
            status="PASS" if ok else "FAIL",
            hard_gate=True,
            detail=f"{len(false_unblock_refs)} false-unblock event(s)",
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
        oos_refs: list[str] = []
        for t in traces:
            decision_key = str(getattr(t, "decision_key", ""))
            # Only applies to PLAN capability
            if ":PLAN:" not in decision_key.upper() and not decision_key.upper().startswith("PLAN:"):
                continue

            artifacts = getattr(t, "artifacts", None) or {}
            outputs = artifacts.get("outputs", {}) or {}
            intentions = outputs.get("intentions", []) or []
            scope_files = set(outputs.get("scope_files", []) or [])
            scope_functions = set(outputs.get("scope_functions", []) or [])

            # If scope info is not available, skip the check for this trace
            if not scope_files and not scope_functions:
                continue

            for intention in intentions:
                if not isinstance(intention, dict):
                    continue
                target_file = intention.get("file", "")
                target_fn = intention.get("function_name", "")

                out_of_scope = False
                if scope_files and target_file and target_file not in scope_files:
                    out_of_scope = True
                if scope_functions and target_fn and target_fn not in scope_functions:
                    out_of_scope = True

                if out_of_scope:
                    oos_refs.append(str(getattr(t, "trace_id", "")))
                    break  # one per trace is enough

        ok = len(oos_refs) == 0
        return PlannerMetric(
            name="planner.no_oos_intentions",
            raw=float(len(oos_refs)),
            score=1.0 if ok else 0.0,
            status="PASS" if ok else "FAIL",
            hard_gate=True,
            detail=f"{len(oos_refs)} trace(s) with out-of-scope intentions",
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
        signals: list[PlannerMetric] = []

        # -- Decision quality (from verdicts) --
        signals.append(self._signal_resolve_accuracy(verdicts))
        signals.append(self._signal_gap_recall(verdicts))
        signals.append(self._signal_gap_precision(verdicts))
        signals.append(self._signal_plan_coverage(verdicts))
        signals.append(self._signal_plan_redundancy(verdicts))
        signals.append(self._signal_integration_risk_recall(verdicts))

        # -- Epistemic hygiene (from traces) --
        signals.append(self._signal_unsafe_resolution_rate(verdicts))
        signals.append(self._signal_evidence_first_rate(traces))

        # -- Efficiency (from traces) --
        signals.append(self._signal_model_calls_p50(traces))
        signals.append(self._signal_model_calls_p95(traces))
        signals.append(self._signal_tool_calls_per_decision(traces))

        # -- Convergence (informational) --
        signals.append(self._signal_iterations_per_slice(traces))

        return signals

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

    def _signal_plan_coverage(self, verdicts: list[Any]) -> PlannerMetric:
        """must_include recall. PASS >= 0.9, WARN >= 0.75, FAIL < 0.75."""
        return self._aggregate_verdict_score(
            verdicts,
            capability="plan",
            metric_name="planner.plan.coverage",
            score_key="coverage",
            pass_=0.9,
            warn=0.75,
        )

    def _signal_plan_redundancy(self, verdicts: list[Any]) -> PlannerMetric:
        """PASS <= 0.05, WARN <= 0.15, FAIL > 0.15."""
        plan_verdicts = [
            v for v in verdicts if str(getattr(v, "capability", "")).lower() == "plan"
        ]
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

    # -- Efficiency --

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
                try:
                    iteration = int(parts[3])
                except (ValueError, TypeError):
                    pass
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
            v
            for v in verdicts
            if str(getattr(v, "capability", "")).lower() == capability.lower()
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

    # ------------------------------------------------------------------
    # Markdown rendering
    # ------------------------------------------------------------------

    @staticmethod
    def _render_markdown(scorecard: PlannerScorecard) -> str:
        """Render scorecard as a human-readable markdown document."""
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
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
            lines.append(
                f"| {g.name} | {g.status} | {g.raw:.2f} | {g.detail} |"
            )

        lines.extend(
            [
                "",
                "## Soft Signals",
                "",
                "| Signal | Status | Score | Raw | Detail |",
                "|--------|--------|-------|-----|--------|",
            ]
        )
        for s in scorecard.soft_signals:
            lines.append(
                f"| {s.name} | {s.status} | {s.score:.2f} | {s.raw:.2f} | {s.detail} |"
            )

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
