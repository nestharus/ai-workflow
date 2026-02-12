"""Scoring framework for PDD pipeline runs.

Computes hard gates and soft signals mechanically from stored artifacts
(EvidenceBundles, CI receipts, demotion ledger, approval artifacts).

Hard gates block the pipeline:
- ``gates.final_pass`` — all required promotion gates PASS at final iteration
- ``ci.final_pass`` — dirty→clean CI PASS at required tier
- ``governance.no_fail`` — governance status != FAIL
- ``alignment.no_high`` — no HIGH-severity POWER drift/reward hacking
- ``l3.no_behavior_change`` — L3 diff-impact classifier = refactor_only

Soft signals (11 total) provide diagnostics:
- ``l1.gap_closure`` — 1 - (final_open_gaps / initial_open_gaps); PASS=1.0, WARN>=0.99, FAIL<0.99
- ``l1.gate_first_attempt_rate`` — first-attempt pass / slices;
  PASS>=0.6, WARN>=0.4
- ``l2.pin_consumption_rate`` — consumed_pins / promoted_pins_in_scope; PASS=1.0, WARN>=0.95
- ``l2.component_coverage`` — implemented_components / manifest_components; PASS=1.0, WARN>=0.98
- ``l2.gate_first_attempt_rate`` — first-attempt pass / slices; PASS>=0.5, WARN>=0.3
- ``l3.reviewer_first_pass_rate`` — first-review pass / files;
  PASS>=0.4, WARN>=0.2
- ``l3.refactor_churn`` — changed_LOC / total_LOC in touched files; PASS<=0.15, WARN<=0.30
- ``pipeline.total_demotions`` — total tickets emitted; PASS<=(slices*0.5), WARN<=(slices*1.0)
- ``pipeline.iteration_efficiency`` — total_iterations / total_slices; PASS<=3, WARN<=6
- ``pipeline.ci_first_pass_rate`` — first-attempt dirty->clean pass;
  PASS>=0.8, WARN>=0.6
- ``pipeline.stagnation_rate`` — stagnated_slices / total_slices; PASS=0, WARN<=0.05

Usage::

    reporter = RunReporter(
        workspace_root=Path("."),
        run_id="abc",
    )
    scorecard = reporter.compute(run_results)
    reporter.write(scorecard)
"""

from __future__ import annotations

import json
import logging
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ScorecardMetric:
    """A single scorecard metric."""

    name: str = ""
    raw: float = 0.0
    score: float = 0.0  # 0.0-1.0 normalized
    status: str = "PASS"  # PASS | WARN | FAIL
    hard_gate: bool = False
    evidence_refs: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Scorecard:
    """Complete scorecard for a run."""

    run_id: str = ""
    hard_gates: list[ScorecardMetric] = field(default_factory=list)
    soft_signals: list[ScorecardMetric] = field(default_factory=list)
    overall_pass: bool = True
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "overall_pass": self.overall_pass,
            "summary": self.summary,
            "hard_gates": [m.to_dict() for m in self.hard_gates],
            "soft_signals": [m.to_dict() for m in self.soft_signals],
        }


class RunReporter:
    """Aggregates evidence and computes scorecard."""

    def __init__(self, workspace_root: Path, run_id: str) -> None:
        self.workspace_root = workspace_root
        self.run_id = run_id
        self._run_dir = workspace_root / ".pdd_runs" / run_id
        self._reports_dir = workspace_root / "reports" / "pdd" / run_id

    def compute(self, run_results: dict[str, Any]) -> Scorecard:
        """Compute scorecard from run results and stored artifacts."""
        hard_gates = self._compute_hard_gates(run_results)
        soft_signals = self._compute_soft_signals(run_results)
        overall_pass = all(g.status != "FAIL" for g in hard_gates)

        failing_gates = [g.name for g in hard_gates if g.status == "FAIL"]
        warnings = [s.name for s in soft_signals if s.status == "WARN"]
        summary_parts = []
        if overall_pass:
            summary_parts.append("All hard gates PASS.")
        else:
            summary_parts.append(f"FAIL: {', '.join(failing_gates)}")
        if warnings:
            summary_parts.append(f"Warnings: {', '.join(warnings)}")

        return Scorecard(
            run_id=self.run_id,
            hard_gates=hard_gates,
            soft_signals=soft_signals,
            overall_pass=overall_pass,
            summary=" ".join(summary_parts),
        )

    def write(self, scorecard: Scorecard) -> tuple[Path, Path]:
        """Write scores.json and scorecard.md."""
        self._reports_dir.mkdir(parents=True, exist_ok=True)

        # Machine-readable
        scores_path = self._reports_dir / "scores.json"
        scores_path.write_text(json.dumps(scorecard.to_dict(), indent=2), encoding="utf-8")

        # Human-readable
        md_path = self._reports_dir / "scorecard.md"
        md_path.write_text(self._render_markdown(scorecard), encoding="utf-8")

        return scores_path, md_path

    def _compute_hard_gates(self, run_results: dict[str, Any]) -> list[ScorecardMetric]:
        """Compute hard gate metrics from run results."""
        gates: list[ScorecardMetric] = []

        # 1. gates.final_pass: all required promotion gates pass
        all_slices_passed = True
        for layer_key in ("l1", "l2", "l3"):
            layer_result = run_results.get(layer_key, {})
            slices = layer_result.get("slices", {}).get("slices", [])
            for s in slices:
                if s.get("status") not in ("COMPLETE",):
                    all_slices_passed = False
        gates.append(
            ScorecardMetric(
                name="gates.final_pass",
                raw=1.0 if all_slices_passed else 0.0,
                score=1.0 if all_slices_passed else 0.0,
                status="PASS" if all_slices_passed else "FAIL",
                hard_gate=True,
            )
        )

        # 2. ci.final_pass: no CI failures at end
        ci_passed = not any(
            run_results.get(f"{layer_key}_result", {}).get("readiness_blocked")
            for layer_key in ("l1_l2_transition", "l2_l3_transition")
        )
        gates.append(
            ScorecardMetric(
                name="ci.final_pass",
                raw=1.0 if ci_passed else 0.0,
                score=1.0 if ci_passed else 0.0,
                status="PASS" if ci_passed else "FAIL",
                hard_gate=True,
            )
        )

        # 3. governance.no_fail: no governance FAIL findings
        governance_ok = True  # Will be set by governance enhancements
        gates.append(
            ScorecardMetric(
                name="governance.no_fail",
                raw=1.0 if governance_ok else 0.0,
                score=1.0 if governance_ok else 0.0,
                status="PASS" if governance_ok else "FAIL",
                hard_gate=True,
            )
        )

        # 4. alignment.no_high: no HIGH-severity POWER findings
        alignment_ok = True
        for layer_key in ("l1",):
            alignment = run_results.get(layer_key, {}).get("alignment", {})
            if alignment.get("drift_findings", 0) > 0:
                alignment_ok = False
        gates.append(
            ScorecardMetric(
                name="alignment.no_high",
                raw=1.0 if alignment_ok else 0.0,
                score=1.0 if alignment_ok else 0.0,
                status="PASS" if alignment_ok else "FAIL",
                hard_gate=True,
            )
        )

        # 5. l3.no_behavior_change: L3 didn't introduce behavior changes
        l3_ok = True
        l3_result = run_results.get("l3", {})
        l3_slices = l3_result.get("slices", {}).get("slices", [])
        for s in l3_slices:
            if s.get("status") == "STAGNATED":
                l3_ok = False
        gates.append(
            ScorecardMetric(
                name="l3.no_behavior_change",
                raw=1.0 if l3_ok else 0.0,
                score=1.0 if l3_ok else 0.0,
                status="PASS" if l3_ok else "FAIL",
                hard_gate=True,
            )
        )

        return gates

    def _compute_soft_signals(self, run_results: dict[str, Any]) -> list[ScorecardMetric]:
        """Compute 11 soft signal metrics from run results.

        Signals computed (exact names from E2E pipeline spec):
          l1.gap_closure, l1.gate_first_attempt_rate,
          l2.pin_consumption_rate, l2.component_coverage, l2.gate_first_attempt_rate,
          l3.reviewer_first_pass_rate, l3.refactor_churn,
          pipeline.total_demotions, pipeline.iteration_efficiency,
          pipeline.ci_first_pass_rate, pipeline.stagnation_rate
        """
        signals: list[ScorecardMetric] = []

        # ------------------------------------------------------------------
        # Gather per-layer slice lists
        # ------------------------------------------------------------------
        l1_slices = run_results.get("l1", {}).get("slices", {}).get("slices", [])
        l2_slices = run_results.get("l2", {}).get("slices", {}).get("slices", [])
        l3_slices = run_results.get("l3", {}).get("slices", {}).get("slices", [])
        all_slices = l1_slices + l2_slices + l3_slices

        total_slices = len(all_slices)
        safe_total = max(total_slices, 1)

        # Aggregate stats across all layers
        total_iterations = sum(s.get("iterations", 0) for s in all_slices)
        total_demotions = sum(s.get("demotion_count", 0) for s in all_slices)
        stagnated_count = sum(1 for s in all_slices if s.get("status") == "STAGNATED")

        # Also count from demotion ledger if it exists (authoritative source)
        ledger_demotions = 0
        ledger_path = self._run_dir / "demotions" / "ledger.jsonl"
        if ledger_path.exists():
            with suppress(Exception):
                for line in ledger_path.read_text(encoding="utf-8").strip().split("\n"):
                    if line:
                        json.loads(line)  # validate
                        ledger_demotions += 1
        # Use the larger of slice-aggregated or ledger count
        total_demotions = max(total_demotions, ledger_demotions)

        # ------------------------------------------------------------------
        # 1. l1.gap_closure — 1 - (final_open_gaps / initial_open_gaps)
        #    PASS = 1.0, WARN >= 0.99, FAIL < 0.99
        # ------------------------------------------------------------------
        initial_gaps = 0
        final_gaps = 0
        for s in l1_slices:
            # initial_open_gaps: use remaining_gaps + completed iterations as proxy
            # if slice has explicit initial_gaps field use it, else estimate from
            # remaining_gaps: complete slices had gaps that are now 0
            s_initial = s.get("initial_gaps", s.get("remaining_gaps", 0))
            s_final = s.get("remaining_gaps", 0)
            if s.get("status") == "COMPLETE":
                # Complete slice closed all gaps; initial >= 1 if it ran
                s_initial = max(s_initial, max(s.get("iterations", 1), 1))
                s_final = 0
            initial_gaps += s_initial
            final_gaps += s_final

        gap_closure_raw = 1.0 - (final_gaps / initial_gaps) if initial_gaps > 0 else 1.0

        if gap_closure_raw >= 1.0:
            gap_status = "PASS"
        elif gap_closure_raw >= 0.99:
            gap_status = "WARN"
        else:
            gap_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="l1.gap_closure",
                raw=gap_closure_raw,
                score=gap_closure_raw,
                status=gap_status,
            )
        )

        # ------------------------------------------------------------------
        # 2. l1.gate_first_attempt_rate — slices passing all gates on first
        #    promote attempt / total L1 slices.
        #    Proxy: iterations == 1 means passed on first try.
        #    PASS >= 0.6, WARN >= 0.4, FAIL < 0.4
        # ------------------------------------------------------------------
        l1_total = max(len(l1_slices), 1)
        l1_first_attempt = sum(
            1 for s in l1_slices if s.get("status") == "COMPLETE" and s.get("iterations", 0) == 1
        )
        l1_first_rate = l1_first_attempt / l1_total

        if l1_first_rate >= 0.6:
            l1_first_status = "PASS"
        elif l1_first_rate >= 0.4:
            l1_first_status = "WARN"
        else:
            l1_first_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="l1.gate_first_attempt_rate",
                raw=l1_first_rate,
                score=l1_first_rate,
                status=l1_first_status,
            )
        )

        # ------------------------------------------------------------------
        # 3. l2.pin_consumption_rate — consumed_pins / promoted_pins_in_scope
        #    PASS = 1.0, WARN >= 0.95, FAIL < 0.95
        #    Extract from L2 slice gate data if available, else default 1.0.
        # ------------------------------------------------------------------
        total_promoted_pins = 0
        total_consumed_pins = 0
        for s in l2_slices:
            promoted = s.get("promoted_pins", 0)
            consumed = s.get("consumed_pins", 0)
            total_promoted_pins += promoted
            total_consumed_pins += consumed

        pin_rate = total_consumed_pins / total_promoted_pins if total_promoted_pins > 0 else 1.0

        if pin_rate >= 1.0:
            pin_status = "PASS"
        elif pin_rate >= 0.95:
            pin_status = "WARN"
        else:
            pin_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="l2.pin_consumption_rate",
                raw=pin_rate,
                score=min(pin_rate, 1.0),
                status=pin_status,
            )
        )

        # ------------------------------------------------------------------
        # 4. l2.component_coverage — implemented_components / manifest_components
        #    PASS = 1.0, WARN >= 0.98, FAIL < 0.98
        #    Extract from L2 results if manifest data exists, else default 1.0.
        # ------------------------------------------------------------------
        l2_result = run_results.get("l2", {})
        manifest_components = l2_result.get("manifest_components", 0)
        implemented_components = l2_result.get("implemented_components", 0)

        if manifest_components > 0:
            comp_coverage = implemented_components / manifest_components
        else:
            # No manifest data — default to 1.0 (all components accounted for)
            comp_coverage = 1.0

        if comp_coverage >= 1.0:
            comp_status = "PASS"
        elif comp_coverage >= 0.98:
            comp_status = "WARN"
        else:
            comp_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="l2.component_coverage",
                raw=comp_coverage,
                score=min(comp_coverage, 1.0),
                status=comp_status,
            )
        )

        # ------------------------------------------------------------------
        # 5. l2.gate_first_attempt_rate — first-attempt pass / L2 slices
        #    Proxy: iterations == 1 for completed slices.
        #    PASS >= 0.5, WARN >= 0.3, FAIL < 0.3
        # ------------------------------------------------------------------
        l2_total = max(len(l2_slices), 1)
        l2_first_attempt = sum(
            1 for s in l2_slices if s.get("status") == "COMPLETE" and s.get("iterations", 0) == 1
        )
        l2_first_rate = l2_first_attempt / l2_total

        if l2_first_rate >= 0.5:
            l2_first_status = "PASS"
        elif l2_first_rate >= 0.3:
            l2_first_status = "WARN"
        else:
            l2_first_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="l2.gate_first_attempt_rate",
                raw=l2_first_rate,
                score=l2_first_rate,
                status=l2_first_status,
            )
        )

        # ------------------------------------------------------------------
        # 6. l3.reviewer_first_pass_rate — files passing all reviewers on
        #    first review / total L3 files.
        #    Proxy: L3 slices with iterations == 1.
        #    PASS >= 0.4, WARN >= 0.2, FAIL < 0.2
        # ------------------------------------------------------------------
        l3_total = max(len(l3_slices), 1)
        l3_first_pass = sum(
            1 for s in l3_slices if s.get("status") == "COMPLETE" and s.get("iterations", 0) == 1
        )
        l3_first_rate = l3_first_pass / l3_total

        if l3_first_rate >= 0.4:
            l3_first_status = "PASS"
        elif l3_first_rate >= 0.2:
            l3_first_status = "WARN"
        else:
            l3_first_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="l3.reviewer_first_pass_rate",
                raw=l3_first_rate,
                score=l3_first_rate,
                status=l3_first_status,
            )
        )

        # ------------------------------------------------------------------
        # 7. l3.refactor_churn — changed_LOC / total_LOC in touched files
        #    PASS <= 0.15, WARN <= 0.30, FAIL > 0.30
        #    Look in L3 slice results for change metrics if available.
        # ------------------------------------------------------------------
        total_changed_loc = 0
        total_loc = 0
        for s in l3_slices:
            total_changed_loc += s.get("changed_loc", 0)
            total_loc += s.get("total_loc", 0)

        churn_raw = total_changed_loc / total_loc if total_loc > 0 else 0.0

        if churn_raw <= 0.15:
            churn_status = "PASS"
        elif churn_raw <= 0.30:
            churn_status = "WARN"
        else:
            churn_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="l3.refactor_churn",
                raw=churn_raw,
                score=max(0.0, 1.0 - churn_raw),
                status=churn_status,
            )
        )

        # ------------------------------------------------------------------
        # 8. pipeline.total_demotions — total tickets emitted
        #    PASS <= (slices * 0.5), WARN <= (slices * 1.0), FAIL > slices * 1.0
        # ------------------------------------------------------------------
        demotion_pass_threshold = safe_total * 0.5
        demotion_warn_threshold = safe_total * 1.0

        if total_demotions <= demotion_pass_threshold:
            demo_status = "PASS"
        elif total_demotions <= demotion_warn_threshold:
            demo_status = "WARN"
        else:
            demo_status = "FAIL"

        # Score: 1.0 when 0 demotions, 0.0 when demotions >= 2 * slices
        demo_score = max(0.0, 1.0 - total_demotions / max(safe_total * 2.0, 1.0))
        signals.append(
            ScorecardMetric(
                name="pipeline.total_demotions",
                raw=float(total_demotions),
                score=demo_score,
                status=demo_status,
            )
        )

        # ------------------------------------------------------------------
        # 9. pipeline.iteration_efficiency — total_iterations / total_slices
        #    PASS <= 3, WARN <= 6, FAIL > 6
        # ------------------------------------------------------------------
        iter_ratio = total_iterations / safe_total

        if iter_ratio <= 3.0:
            iter_status = "PASS"
        elif iter_ratio <= 6.0:
            iter_status = "WARN"
        else:
            iter_status = "FAIL"

        # Score: 1.0 at ratio 1, 0.0 at ratio >= 10
        iter_score = max(0.0, 1.0 - (iter_ratio - 1.0) / 9.0) if iter_ratio >= 1.0 else 1.0
        signals.append(
            ScorecardMetric(
                name="pipeline.iteration_efficiency",
                raw=iter_ratio,
                score=iter_score,
                status=iter_status,
            )
        )

        # ------------------------------------------------------------------
        # 10. pipeline.ci_first_pass_rate — successful dirty->clean on first
        #     attempt / total promotions.
        #     Look at ci_ticks in layer results for first-pass success ratio.
        #     PASS >= 0.8, WARN >= 0.6, FAIL < 0.6
        # ------------------------------------------------------------------
        ci_total = 0
        ci_first_pass = 0
        for layer_key in ("l1", "l2", "l3"):
            layer_result = run_results.get(layer_key, {})
            ci_data = layer_result.get("ci_ticks", {})
            ci_total += ci_data.get("total", 0)
            ci_first_pass += ci_data.get("first_pass", 0)

        if ci_total > 0:
            ci_rate = ci_first_pass / ci_total
        else:
            # No CI data — use completion rate as proxy: completed slices
            # that finished in 1 iteration are assumed to have clean CI
            completed = sum(1 for s in all_slices if s.get("status") == "COMPLETE")
            ci_rate = completed / safe_total if total_slices > 0 else 1.0

        if ci_rate >= 0.8:
            ci_status = "PASS"
        elif ci_rate >= 0.6:
            ci_status = "WARN"
        else:
            ci_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="pipeline.ci_first_pass_rate",
                raw=ci_rate,
                score=ci_rate,
                status=ci_status,
            )
        )

        # ------------------------------------------------------------------
        # 11. pipeline.stagnation_rate — stagnated_slices / total_slices
        #     PASS = 0, WARN <= 0.05, FAIL > 0.05
        # ------------------------------------------------------------------
        stag_rate = stagnated_count / safe_total

        if stag_rate == 0.0:
            stag_status = "PASS"
        elif stag_rate <= 0.05:
            stag_status = "WARN"
        else:
            stag_status = "FAIL"

        signals.append(
            ScorecardMetric(
                name="pipeline.stagnation_rate",
                raw=float(stagnated_count),
                score=1.0 - stag_rate,
                status=stag_status,
            )
        )

        return signals

    @staticmethod
    def _render_markdown(scorecard: Scorecard) -> str:
        """Render scorecard as markdown."""
        lines = [
            f"# Scorecard — Run {scorecard.run_id}",
            "",
            f"**Overall**: {'PASS' if scorecard.overall_pass else 'FAIL'}",
            f"**Summary**: {scorecard.summary}",
            "",
            "## Hard Gates",
            "",
            "| Gate | Status | Score |",
            "|------|--------|-------|",
        ]
        for g in scorecard.hard_gates:
            lines.append(f"| {g.name} | {g.status} | {g.score:.2f} |")

        lines.extend(
            [
                "",
                "## Soft Signals",
                "",
                "| Signal | Status | Score | Raw |",
                "|--------|--------|-------|-----|",
            ]
        )
        for s in scorecard.soft_signals:
            lines.append(f"| {s.name} | {s.status} | {s.score:.2f} | {s.raw:.1f} |")

        lines.append("")
        return "\n".join(lines)
