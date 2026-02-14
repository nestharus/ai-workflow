"""Final report generator for PDD pipeline runs.

Produces a consolidated ``final_report.md`` and ``scorecard.json``
under ``reports/pdd/<run_id>/``.

Sections:
- Executive summary
- Architecture topology
- Scorecard (from scoring.py)
- Demotion summary
- Known risks / unresolved issues
- Evidence links

Usage::

    gen = FinalReportGenerator(
        workspace_root=Path("."),
        run_id="abc",
    )
    gen.generate(run_results, scorecard)
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FinalReportGenerator:
    """Generates the consolidated final report for a PDD run."""

    def __init__(self, workspace_root: Path, run_id: str) -> None:
        self.workspace_root = workspace_root
        self.run_id = run_id
        self._run_dir = workspace_root / ".pdd_runs" / run_id
        self._reports_dir = workspace_root / "reports" / "pdd" / run_id

    def generate(
        self,
        run_results: dict[str, Any],
        scorecard: Any | None = None,
    ) -> tuple[Path, Path]:
        """Generate final_report.md and scorecard.json.

        Args:
            run_results: Full results dict from PddLifecycle.run().
            scorecard: Optional Scorecard object from RunReporter.

        Returns:
            Tuple of (final_report.md path, scorecard.json path).
        """
        self._reports_dir.mkdir(parents=True, exist_ok=True)

        report_md = self._render_report(run_results, scorecard)
        report_path = self._reports_dir / "final_report.md"
        report_path.write_text(report_md, encoding="utf-8")

        scorecard_data = scorecard.to_dict() if scorecard and hasattr(scorecard, "to_dict") else {}
        scorecard_path = self._reports_dir / "scorecard.json"
        scorecard_path.write_text(json.dumps(scorecard_data, indent=2), encoding="utf-8")

        logger.info("Final report written to %s", report_path)
        return report_path, scorecard_path

    def _render_report(self, run_results: dict[str, Any], scorecard: Any | None) -> str:
        """Render the full report as markdown."""
        sections: list[str] = []

        sections.append(self._executive_summary(run_results, scorecard))
        sections.append(self._architecture_topology(run_results))
        sections.append(self._scorecard_section(scorecard))
        sections.append(self._power_alignment())
        sections.append(self._approval_checkpoints())
        quality_scorecard = self._load_quality_scorecard()
        if quality_scorecard:
            sections.append(self._architecture_quality(quality_scorecard))
            sections.append(self._code_quality(quality_scorecard))
            sections.append(self._spec_fidelity(quality_scorecard))
        sections.append(self._demotion_summary(run_results))
        sections.append(self._known_risks(run_results))
        sections.append(self._evidence_links())

        return "\n\n---\n\n".join(sections)

    def _executive_summary(self, run_results: dict[str, Any], scorecard: Any | None) -> str:
        """Generate executive summary section."""
        lines = [
            f"# PDD Pipeline Final Report — Run `{self.run_id}`",
            "",
            "## Executive Summary",
            "",
        ]

        # Gather stats
        layers_info: list[str] = []
        for layer_key in ("l1", "l2", "l3"):
            layer = run_results.get(layer_key, {})
            slices = layer.get("slices", {}).get("slices", [])
            complete = sum(1 for s in slices if s.get("status") == "COMPLETE")
            total = len(slices)
            layers_info.append(f"- **{layer_key.upper()}**: {complete}/{total} slices complete")

        lines.extend(layers_info)

        if scorecard and hasattr(scorecard, "overall_pass"):
            status = "PASS" if scorecard.overall_pass else "FAIL"
            lines.append(f"\n**Overall Status**: {status}")
            if hasattr(scorecard, "summary"):
                lines.append(f"**Summary**: {scorecard.summary}")

        # Transitions
        for trans_key in ("l1_l2_transition", "l2_l3_transition"):
            trans = run_results.get(trans_key, {})
            stuck = trans.get("transition_stuck", False)
            rounds = len(trans.get("rework_rounds", []))
            if stuck:
                lines.append(f"- **{trans_key}**: STUCK after {rounds} rounds")
            elif rounds > 0:
                lines.append(f"- **{trans_key}**: resolved in {rounds} round(s)")

        return "\n".join(lines)

    def _architecture_topology(self, run_results: dict[str, Any]) -> str:
        """Generate architecture topology section."""
        lines = [
            "## Architecture Topology",
            "",
        ]

        # Run-scoped manifest only (no global fallback).
        manifest_path = self._reports_dir / "component_manifest.json"
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                components = data.get("components", [])
                lines.append(f"**Components**: {len(components)}")
                for comp in components[:10]:
                    comp_id = comp.get("component_id", comp.get("id", "unknown"))
                    lines.append(f"- `{comp_id}`")
            except (json.JSONDecodeError, OSError):
                lines.append("Component manifest could not be read.")
        else:
            lines.append("No component manifest found.")

        # Run-scoped architecture proposals only.
        proposals_path = self._reports_dir / "architecture_proposals.json"
        if proposals_path.exists():
            try:
                proposals_data = json.loads(proposals_path.read_text(encoding="utf-8"))
                candidates = proposals_data.get("candidates", [])
                issues = proposals_data.get("issues", [])
                lines.append("")
                lines.append(f"**Architecture Proposals**: {len(candidates)}")
                lines.append(f"**Architectural Issues**: {len(issues)}")
            except (json.JSONDecodeError, OSError):
                lines.append("Architecture proposals could not be read.")
        else:
            lines.append("No architecture proposals found for this run.")

        lines.append("")
        lines.append(f"**Pins consumed**: {self._pins_consumed(run_results, manifest_path)}")
        flows = self._key_flows(manifest_path=manifest_path, proposals_path=proposals_path)
        lines.append("**Key flows**:")
        if flows:
            for flow in flows:
                lines.append(f"- {flow}")
        else:
            lines.append("- No key flow data found in run artifacts.")

        return "\n".join(lines)

    def _scorecard_section(self, scorecard: Any | None) -> str:
        """Generate scorecard section."""
        lines = ["## Scorecard", ""]

        if not scorecard:
            lines.append("Scorecard not computed.")
            return "\n".join(lines)

        if hasattr(scorecard, "hard_gates"):
            lines.extend(
                [
                    "### Hard Gates",
                    "",
                    "| Gate | Status |",
                    "|------|--------|",
                ]
            )
            for g in scorecard.hard_gates:
                lines.append(f"| {g.name} | {g.status} |")

        if hasattr(scorecard, "soft_signals"):
            lines.extend(
                [
                    "",
                    "### Soft Signals",
                    "",
                    "| Signal | Status | Score |",
                    "|--------|--------|-------|",
                ]
            )
            for s in scorecard.soft_signals:
                lines.append(f"| {s.name} | {s.status} | {s.score:.2f} |")

        grouped = self._group_scorecard_by_layer(scorecard)
        lines.extend(["", "### Per-Layer + Cross-Layer View", ""])
        for layer in ("L1", "L2", "L3", "Cross-Layer"):
            metrics = grouped.get(layer, [])
            lines.extend([f"#### {layer}", ""])
            if not metrics:
                lines.append("No metrics recorded.")
                lines.append("")
                continue
            lines.extend(
                [
                    "| Metric | Type | Status | Score |",
                    "|--------|------|--------|-------|",
                ]
            )
            for metric in metrics:
                metric_type = "Hard Gate" if metric.hard_gate else "Soft Signal"
                lines.append(
                    f"| {metric.name} | {metric_type} | {metric.status} | {metric.score:.2f} |"
                )
            lines.append("")

        return "\n".join(lines)

    def _power_alignment(self) -> str:
        """Render POWER alignment summary section."""
        lines = ["## POWER Alignment", ""]
        alignment_path = self._reports_dir / "alignment_report.json"
        if not alignment_path.exists():
            lines.append("No alignment artifact found for this run.")
            lines.append(f"- Expected artifact: `{self._display_path(alignment_path)}`")
            return "\n".join(lines)

        try:
            payload = json.loads(alignment_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            lines.append("Alignment artifact could not be read.")
            lines.append(f"- Artifact path: `{self._display_path(alignment_path)}`")
            return "\n".join(lines)

        drift_findings = int(payload.get("drift_findings", 0) or 0)
        reward_findings = int(payload.get("reward_hacking_findings", 0) or 0)
        high_severity = drift_findings + reward_findings
        lines.append(f"- Libraries checked: {int(payload.get('libraries_checked', 0) or 0)}")
        lines.append(f"- Drift findings: {drift_findings}")
        lines.append(f"- Reward-hacking findings: {reward_findings}")
        lines.append(f"- High severity findings: {high_severity}")
        errors = payload.get("errors", [])
        if isinstance(errors, list) and errors:
            lines.append(f"- Checker errors: {len(errors)}")
            for item in errors[:5]:
                if isinstance(item, dict):
                    lib_id = item.get("lib_id", "?")
                    error = item.get("error", "unknown error")
                    lines.append(f"- Error detail ({lib_id}): {error}")
        lines.append("")
        lines.append(f"Detailed artifact: `{self._display_path(alignment_path)}`")
        return "\n".join(lines)

    def _approval_checkpoints(self) -> str:
        """Render L1/L2/L3 approval checkpoints from artifacts."""
        lines = ["## Approval Checkpoints", ""]
        approval_rows = self._approval_rows()
        if not approval_rows:
            lines.append("No approval artifacts found.")
            return "\n".join(lines)

        lines.extend(
            [
                "| Checkpoint | Approved | Mode | Iteration | Decision Artifact |",
                "|------------|----------|------|-----------|-------------------|",
            ]
        )
        for row in approval_rows:
            lines.append(
                "| "
                f"{row['checkpoint']} | {row['approved']} | {row['mode']} | "
                f"{row['iteration']} | `{row['artifact']}` |"
            )
        return "\n".join(lines)

    def _load_quality_scorecard(self) -> dict[str, Any] | None:
        """Load quality_scorecard.json when available."""
        path = self._reports_dir / "quality_scorecard.json"
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to read quality scorecard at %s", path, exc_info=True)
            return None
        return payload if isinstance(payload, dict) else None

    def _architecture_quality(self, scorecard: dict[str, Any]) -> str:
        """Render Architecture Quality section from quality scorecard."""
        lines = ["## Architecture Quality", ""]
        arch_score = _safe_float(scorecard.get("arch_quality_score"), default=0.0)
        lines.append(f"**Quality Score**: {arch_score:.3f}")

        metrics = self._metrics(scorecard.get("architecture"))
        if metrics:
            lines.extend(
                [
                    "",
                    "### Mechanical Stats",
                    "",
                    "| Metric | Status | Score | Detail |",
                    "|--------|--------|-------|--------|",
                ]
            )
            for metric in metrics:
                name = str(metric.get("name", ""))
                status = str(metric.get("status", ""))
                score = _safe_float(metric.get("score"), default=0.0)
                detail = str(metric.get("detail", ""))
                lines.append(f"| {name} | {status} | {score:.3f} | {detail} |")
        else:
            lines.append("No architecture metrics available.")

        judge_dims = scorecard.get("architecture_judge_dimensions")
        if isinstance(judge_dims, list) and judge_dims:
            lines.extend(["", "### Judge Dimensions", ""])
            for item in judge_dims:
                lines.append(f"- {item}")
        else:
            quality_metric = next(
                (m for m in metrics if m.get("name") == "arch.quality_score"), None
            )
            detail = str((quality_metric or {}).get("detail", "")).strip()
            lines.append("")
            if detail:
                lines.append(f"**Judge Dimensions**: {detail}")
            else:
                lines.append("**Judge Dimensions**: not available in quality scorecard.")

        risks = self._collect_risks(
            explicit=scorecard.get("architecture_risks"),
            fallback_metrics=[m for m in metrics if str(m.get("name", "")).startswith("arch.")],
        )
        lines.extend(["", "### Top Risks", ""])
        if risks:
            for risk in risks[:5]:
                lines.append(f"- {risk}")
        else:
            lines.append("- No architecture risks reported.")

        return "\n".join(lines)

    def _code_quality(self, scorecard: dict[str, Any]) -> str:
        """Render Code Quality section from quality scorecard."""
        lines = ["## Code Quality", ""]
        code_score = _safe_float(scorecard.get("code_quality_score"), default=0.0)
        lines.append(f"**Quality Score**: {code_score:.3f}")

        sampled_files = scorecard.get("code_sampled_files")
        if isinstance(sampled_files, list) and sampled_files:
            lines.extend(
                [
                    "",
                    "### Sampled File Table",
                    "",
                    "| File | LOC | Note |",
                    "|------|-----|------|",
                ]
            )
            for item in sampled_files[:15]:
                if not isinstance(item, dict):
                    continue
                file_path = str(item.get("path", item.get("file", "")))
                loc = item.get("loc", "")
                note = str(item.get("note", item.get("detail", "")))
                lines.append(f"| {file_path} | {loc} | {note} |")
        else:
            lines.extend(
                [
                    "",
                    "### Sampled File Table",
                    "",
                    "No sampled files recorded in quality scorecard.",
                ]
            )

        metrics = self._metrics(scorecard.get("code"))
        if metrics:
            lines.extend(
                [
                    "",
                    "### Mechanical Stats",
                    "",
                    "| Metric | Status | Score | Detail |",
                    "|--------|--------|-------|--------|",
                ]
            )
            for metric in metrics:
                name = str(metric.get("name", ""))
                status = str(metric.get("status", ""))
                score = _safe_float(metric.get("score"), default=0.0)
                detail = str(metric.get("detail", ""))
                lines.append(f"| {name} | {status} | {score:.3f} | {detail} |")

        risks = self._collect_risks(
            explicit=scorecard.get("code_risks"),
            fallback_metrics=[m for m in metrics if str(m.get("name", "")).startswith("code.")],
        )
        lines.extend(["", "### Top Risks", ""])
        if risks:
            for risk in risks[:5]:
                lines.append(f"- {risk}")
        else:
            lines.append("- No code risks reported.")

        return "\n".join(lines)

    def _spec_fidelity(self, scorecard: dict[str, Any]) -> str:
        """Render Spec Fidelity section from quality scorecard."""
        lines = ["## Spec Fidelity", ""]
        spec_score = _safe_float(scorecard.get("spec_fidelity_score"), default=0.0)
        lines.append(f"**Coverage Estimate**: {spec_score:.3f}")

        missing_items = scorecard.get("spec_missing_items")
        if not isinstance(missing_items, list):
            missing_items = scorecard.get("spec_missing")
        if not isinstance(missing_items, list):
            missing_items = scorecard.get("missing")
        if not isinstance(missing_items, list):
            missing_items = []

        lines.extend(["", "### Missing Items", ""])
        if missing_items:
            for item in missing_items[:20]:
                lines.append(f"- {item}")
        else:
            lines.append("- No missing-item list present in quality scorecard.")

        return "\n".join(lines)

    def _metrics(self, payload: Any) -> list[dict[str, Any]]:
        """Normalize metric payload to a list of dicts."""
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _collect_risks(self, explicit: Any, fallback_metrics: list[dict[str, Any]]) -> list[str]:
        """Collect human-readable top risks from explicit or metric-derived sources."""
        if isinstance(explicit, list) and explicit:
            collected: list[str] = []
            for risk in explicit:
                if isinstance(risk, dict):
                    severity = str(risk.get("severity", "")).upper()
                    text = str(risk.get("risk", risk.get("title", risk.get("description", ""))))
                    collected.append(f"{severity}: {text}" if severity else text)
                else:
                    collected.append(str(risk))
            return [r for r in collected if r]

        collected = []
        for metric in fallback_metrics:
            status = str(metric.get("status", "")).upper()
            if status not in {"WARN", "FAIL"}:
                continue
            name = str(metric.get("name", ""))
            detail = str(metric.get("detail", ""))
            if detail:
                collected.append(f"{status}: {name} ({detail})")
            else:
                collected.append(f"{status}: {name}")
        return collected

    def _demotion_summary(self, run_results: dict[str, Any]) -> str:
        """Generate demotion summary from ledger."""
        lines = ["## Demotion Summary", ""]

        ledger_path = self._run_dir / "demotions" / "ledger.jsonl"
        if not ledger_path.exists():
            lines.append("No demotion ledger found.")
            return "\n".join(lines)

        entries: list[dict[str, Any]] = []
        try:
            for line in ledger_path.read_text(encoding="utf-8").strip().split("\n"):
                if line:
                    entries.append(json.loads(line))
        except Exception:
            # C03: Surface errors — log the root cause
            logger.warning("Failed to read demotion ledger at %s", ledger_path, exc_info=True)
            lines.append("Failed to read demotion ledger.")
            return "\n".join(lines)

        lines.append(f"**Total tickets**: {len(entries)}")

        # Group by target layer
        by_layer: dict[str, int] = {}
        by_source: dict[str, int] = {}
        by_disposition: dict[str, int] = {}
        ticket_records = self._load_ticket_records()
        slice_statuses = self._slice_status_by_id(run_results)
        ticket_rows: list[tuple[str, str, str, str, str]] = []
        for e in entries:
            tl = e.get("target_layer", "?")
            by_layer[tl] = by_layer.get(tl, 0) + 1
            src = e.get("source", "?")
            by_source[src] = by_source.get(src, 0) + 1
            ticket_id = str(e.get("ticket_id", ""))
            diagnosis = str(e.get("diagnosis", "")).replace("\n", " ").strip()
            diagnosis = diagnosis or "No diagnosis recorded"
            disposition = self._demotion_disposition(
                entry=e,
                ticket_record=ticket_records.get(ticket_id, {}),
                slice_statuses=slice_statuses,
            )
            by_disposition[disposition] = by_disposition.get(disposition, 0) + 1
            ticket_rows.append(
                (ticket_id, str(tl), diagnosis, disposition, str(e.get("severity", "")))
            )

        if by_layer:
            lines.append("\n**By target layer**:")
            for layer, count in sorted(by_layer.items()):
                lines.append(f"- {layer}: {count}")

        if by_source:
            lines.append("\n**By source**:")
            for source, count in sorted(by_source.items()):
                lines.append(f"- {source}: {count}")

        if by_disposition:
            lines.append("\n**Final disposition**:")
            for disposition, count in sorted(by_disposition.items()):
                lines.append(f"- {disposition}: {count}")

        if ticket_rows:
            lines.extend(
                [
                    "",
                    "### Ticket Details",
                    "",
                    "| Ticket | Target | Severity | Why | Final disposition |",
                    "|--------|--------|----------|-----|-------------------|",
                ]
            )
            for ticket_id, target_layer, diagnosis, disposition, severity in ticket_rows[:25]:
                truncated_diagnosis = diagnosis[:160]
                lines.append(
                    f"| {ticket_id} | {target_layer} | {severity} | "
                    f"{truncated_diagnosis} | {disposition} |"
                )

        return "\n".join(lines)

    def _known_risks(self, run_results: dict[str, Any]) -> str:
        """Generate known risks section."""
        lines = ["## Known Risks / Unresolved Issues", ""]

        risks: list[str] = []

        # Check for stuck transitions
        for trans_key in ("l1_l2_transition", "l2_l3_transition"):
            trans = run_results.get(trans_key, {})
            if trans.get("transition_stuck"):
                risks.append(f"Transition {trans_key} stuck with unresolved demotions")

        # Check for stagnated/failed slices
        for layer_key in ("l1", "l2", "l3"):
            layer = run_results.get(layer_key, {})
            slices = layer.get("slices", {}).get("slices", [])
            for s in slices:
                if s.get("status") == "STAGNATED":
                    risks.append(f"Slice {s.get('slice_id', '?')} stagnated at {layer_key}")
                elif s.get("status") == "BLOCKED":
                    risks.append(f"Slice {s.get('slice_id', '?')} blocked at {layer_key}")
                elif s.get("status") == "FAILED":
                    risks.append(f"Slice {s.get('slice_id', '?')} failed at {layer_key}")

        # Check QA
        qa = run_results.get("qa", {})
        if qa.get("error"):
            risks.append(f"QA failed: {qa['error']}")

        if not risks:
            lines.append("No known risks.")
        else:
            for risk in risks:
                lines.append(f"- {risk}")

        return "\n".join(lines)

    def _evidence_links(self) -> str:
        """Generate evidence links section."""
        lines = ["## Evidence Links", ""]
        artifacts = [
            ("Run directory", self._run_dir),
            ("Approval artifacts", self._run_dir / "approvals"),
            ("Snapshot manifest", self._run_dir / "snapshot" / "manifest.json"),
            ("Snapshot files", self._run_dir / "snapshot" / "files"),
            ("Evidence bundles", self._run_dir / "slices"),
            ("Demotion ledger", self._run_dir / "demotions" / "ledger.jsonl"),
            ("CI receipts", self._run_dir / "ci"),
            ("Architecture digest", self._reports_dir / "architecture_digest.json"),
            ("Code digest", self._reports_dir / "code_digest.json"),
            ("Pipeline scorecard", self._reports_dir / "scores.json"),
            ("Planner scorecard", self._reports_dir / "planner_scorecard.json"),
            ("Quality scorecard", self._reports_dir / "quality_scorecard.json"),
            ("POWER alignment report", self._reports_dir / "alignment_report.json"),
            ("Reports directory", self._reports_dir),
        ]
        for label, path in artifacts:
            lines.append(self._artifact_link(label, path))
        lines.extend(
            [
                "",
                "All evidence references are run-scoped; no global fallback artifacts are used.",
            ]
        )
        return "\n".join(lines)

    def _artifact_link(self, label: str, path: Path) -> str:
        rel = self._display_path(path)
        if path.exists():
            return f"- {label}: `{rel}`"
        return f"- {label}: MISSING (`{rel}`)"

    def _display_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.workspace_root.resolve()).as_posix()
        except Exception:
            return str(path)

    def _group_scorecard_by_layer(self, scorecard: Any) -> dict[str, list[Any]]:
        grouped: dict[str, list[Any]] = defaultdict(list)
        hard_gates = getattr(scorecard, "hard_gates", []) if scorecard else []
        soft_signals = getattr(scorecard, "soft_signals", []) if scorecard else []
        for metric in [*hard_gates, *soft_signals]:
            name = str(getattr(metric, "name", ""))
            grouped[self._scorecard_scope(name)].append(metric)
        return grouped

    @staticmethod
    def _scorecard_scope(metric_name: str) -> str:
        lowered = metric_name.lower()
        if lowered.startswith("l1."):
            return "L1"
        if lowered.startswith("l2."):
            return "L2"
        if lowered.startswith("l3."):
            return "L3"
        return "Cross-Layer"

    def _approval_rows(self) -> list[dict[str, str]]:
        approvals_root = self._run_dir / "approvals"
        rows: list[dict[str, str]] = [
            {
                "checkpoint": "L1 Mandatory Approval",
                "approved": "MISSING",
                "mode": "",
                "iteration": "",
                "artifact": self._display_path(approvals_root / "l1"),
            },
            {
                "checkpoint": "L2 Architecture Checkpoint",
                "approved": "OPTIONAL",
                "mode": "",
                "iteration": "-",
                "artifact": self._display_path(approvals_root / "l2" / "decision.json"),
            },
            {
                "checkpoint": "L3 Release Signoff",
                "approved": "PENDING",
                "mode": "",
                "iteration": "-",
                "artifact": self._display_path(approvals_root / "l3" / "decision.json"),
            },
        ]

        l1_dir = approvals_root / "l1"
        if l1_dir.exists():
            l1_decisions = sorted(
                l1_dir.glob("iteration_*/decision.json"),
                key=self._iteration_sort_key,
            )
            if l1_decisions:
                latest = l1_decisions[-1]
                payload = self._read_json_dict(latest)
                rows[0] = {
                    "checkpoint": "L1 Mandatory Approval",
                    "approved": "YES" if payload.get("approved") else "NO",
                    "mode": str(payload.get("mode", "")),
                    "iteration": str(payload.get("iteration", "")),
                    "artifact": self._display_path(latest),
                }

        l2_path = approvals_root / "l2" / "decision.json"
        if l2_path.exists():
            payload = self._read_json_dict(l2_path)
            rows[1] = {
                "checkpoint": "L2 Architecture Checkpoint",
                "approved": "YES" if payload.get("approved") else "NO",
                "mode": str(payload.get("mode", "")),
                "iteration": str(payload.get("iteration", "-")),
                "artifact": self._display_path(l2_path),
            }

        l3_path = approvals_root / "l3" / "decision.json"
        if l3_path.exists():
            payload = self._read_json_dict(l3_path)
            rows[2] = {
                "checkpoint": "L3 Release Signoff",
                "approved": "YES" if payload.get("approved") else "NO",
                "mode": str(payload.get("mode", "")),
                "iteration": str(payload.get("iteration", "-")),
                "artifact": self._display_path(l3_path),
            }

        return rows

    def _pins_consumed(self, run_results: dict[str, Any], manifest_path: Path) -> int:
        total_from_slices = 0
        l2_slices = run_results.get("l2", {}).get("slices", {}).get("slices", [])
        if isinstance(l2_slices, list):
            for item in l2_slices:
                if not isinstance(item, dict):
                    continue
                consumed = item.get("consumed_pins")
                if isinstance(consumed, int):
                    total_from_slices += consumed
                elif isinstance(consumed, list):
                    total_from_slices += len(consumed)

        total_from_manifest = 0
        manifest = self._read_json_dict(manifest_path) if manifest_path.exists() else {}
        components = manifest.get("components", [])
        if isinstance(components, list):
            for component in components:
                if not isinstance(component, dict):
                    continue
                for key in ("consumed_pins", "pins_consumed", "pin_refs", "pins", "consumes"):
                    value = component.get(key)
                    if isinstance(value, int):
                        total_from_manifest += value
                    elif isinstance(value, (list, dict)):
                        total_from_manifest += len(value)
        return max(total_from_slices, total_from_manifest)

    def _key_flows(self, *, manifest_path: Path, proposals_path: Path) -> list[str]:
        flows: list[str] = []

        manifest = self._read_json_dict(manifest_path) if manifest_path.exists() else {}
        components = manifest.get("components", [])
        if isinstance(components, list):
            for component in components:
                if not isinstance(component, dict):
                    continue
                source = str(component.get("component_id", component.get("id", ""))).strip()
                depends = component.get("depends_on", [])
                if source and isinstance(depends, list):
                    for target in depends:
                        target_str = str(target).strip()
                        if target_str:
                            flows.append(f"{source} -> {target_str}")
        for edge in manifest.get("edges", []) if isinstance(manifest.get("edges"), list) else []:
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("from", edge.get("source", ""))).strip()
            target = str(edge.get("to", edge.get("target", ""))).strip()
            kind = str(edge.get("kind", edge.get("type", ""))).strip()
            if not source and not target:
                continue
            label = f"{source} -> {target}".strip()
            if kind:
                label = f"{label} ({kind})"
            flows.append(label)

        proposals = self._read_json_dict(proposals_path) if proposals_path.exists() else {}
        candidates = proposals.get("candidates", [])
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                for key in (
                    "key_flows",
                    "flows",
                    "edges",
                    "communication_patterns",
                    "communications",
                ):
                    flows.extend(self._flow_values(candidate.get(key)))

        deduped: list[str] = []
        seen: set[str] = set()
        for flow in flows:
            flow_clean = str(flow).strip()
            if not flow_clean or flow_clean in seen:
                continue
            seen.add(flow_clean)
            deduped.append(flow_clean)
            if len(deduped) >= 10:
                break
        return deduped

    def _flow_values(self, payload: Any) -> list[str]:
        values: list[str] = []
        if isinstance(payload, str):
            if payload.strip():
                values.append(payload.strip())
            return values
        if isinstance(payload, list):
            for item in payload:
                values.extend(self._flow_values(item))
            return values
        if isinstance(payload, dict):
            source = str(payload.get("from", payload.get("source", ""))).strip()
            target = str(payload.get("to", payload.get("target", ""))).strip()
            kind = str(payload.get("kind", payload.get("type", ""))).strip()
            if source or target:
                label = f"{source} -> {target}".strip()
                values.append(f"{label} ({kind})" if kind else label)
                return values
            for nested_key in ("summary", "description", "text", "pattern"):
                nested = payload.get(nested_key)
                if isinstance(nested, str) and nested.strip():
                    values.append(nested.strip())
            return values
        return values

    def _load_ticket_records(self) -> dict[str, dict[str, Any]]:
        tickets_dir = self._run_dir / "demotions" / "tickets"
        if not tickets_dir.exists():
            return {}
        records: dict[str, dict[str, Any]] = {}
        for ticket_path in sorted(tickets_dir.glob("*.json")):
            payload = self._read_json_dict(ticket_path)
            ticket_id = str(payload.get("ticket", {}).get("ticket_id", "")).strip()
            if ticket_id:
                records[ticket_id] = payload
        return records

    def _slice_status_by_id(self, run_results: dict[str, Any]) -> dict[str, str]:
        status_by_slice: dict[str, str] = {}
        for layer in ("l1", "l2", "l3"):
            slices = run_results.get(layer, {}).get("slices", {}).get("slices", [])
            if not isinstance(slices, list):
                continue
            for item in slices:
                if not isinstance(item, dict):
                    continue
                slice_id = str(item.get("slice_id", "")).strip()
                if not slice_id:
                    continue
                status_by_slice[slice_id] = str(item.get("status", ""))
        return status_by_slice

    def _demotion_disposition(
        self,
        *,
        entry: dict[str, Any],
        ticket_record: dict[str, Any],
        slice_statuses: dict[str, str],
    ) -> str:
        ticket_payload = ticket_record.get("ticket", {}) if isinstance(ticket_record, dict) else {}
        slice_id = str(ticket_payload.get("slice_id", "")).strip()
        if slice_id and slice_id in slice_statuses:
            status = slice_statuses[slice_id]
            if status in {"COMPLETE", "PROMOTED"}:
                return "RESOLVED"
            if status in {"FAILED", "BLOCKED", "STAGNATED"}:
                return f"UNRESOLVED ({status})"
            return f"PENDING ({status})"

        apply_status = str(entry.get("apply_status", "")).upper()
        if apply_status == "APPLIED" or bool(entry.get("applied")):
            return "APPLIED (verification pending)"
        if apply_status in {"BLOCKED", "REJECTED"}:
            return apply_status
        return "UNKNOWN"

    @staticmethod
    def _read_json_dict(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _iteration_sort_key(path: Path) -> int:
        try:
            return int(path.parent.name.split("_")[-1])
        except (TypeError, ValueError):
            return -1


def _safe_float(value: Any, *, default: float) -> float:
    """Convert value to float with fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
