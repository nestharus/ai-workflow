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

        # Try run-scoped first, fall back to global
        manifest_path = self._reports_dir / "component_manifest.json"
        if not manifest_path.exists():
            manifest_path = self.workspace_root / "reports" / "component_manifest.json"
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

        # Check for architecture proposals
        proposals_path = self._reports_dir / "architecture_proposals.json"
        if not proposals_path.exists():
            proposals_path = self.workspace_root / "reports" / "architecture_proposals.json"
        if proposals_path.exists():
            lines.append(f"\nArchitecture proposals: `{proposals_path}`")

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

        return "\n".join(lines)

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
        for e in entries:
            tl = e.get("target_layer", "?")
            by_layer[tl] = by_layer.get(tl, 0) + 1
            src = e.get("source", "?")
            by_source[src] = by_source.get(src, 0) + 1

        if by_layer:
            lines.append("\n**By target layer**:")
            for layer, count in sorted(by_layer.items()):
                lines.append(f"- {layer}: {count}")

        if by_source:
            lines.append("\n**By source**:")
            for source, count in sorted(by_source.items()):
                lines.append(f"- {source}: {count}")

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
        lines = [
            "## Evidence Links",
            "",
            f"- Run directory: `.pdd_runs/{self.run_id}/`",
            f"- Evidence bundles: `.pdd_runs/{self.run_id}/slices/`",
            f"- Demotion ledger: `.pdd_runs/{self.run_id}/demotions/ledger.jsonl`",
            f"- CI receipts: `.pdd_runs/{self.run_id}/ci/`",
            f"- Reports: `reports/pdd/{self.run_id}/`",
        ]
        return "\n".join(lines)
