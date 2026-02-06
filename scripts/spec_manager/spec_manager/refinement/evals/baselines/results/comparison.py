"""Comparison report across models and levels."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.refinement.evals.baselines.results.baseline_result import BaselineResult


@dataclass
class ComparisonReport:
    """Comparison of baseline results across models and levels.

    Attributes:
        results: All baseline results indexed by (model, level).
        summary: Summary statistics.
    """
    results: list[BaselineResult] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def add_result(self, result: BaselineResult) -> None:
        self.results.append(result)

    def compute_summary(self) -> None:
        """Compute summary statistics."""
        by_model: dict[str, list[BaselineResult]] = {}
        by_level: dict[int, list[BaselineResult]] = {}

        for r in self.results:
            by_model.setdefault(r.model_name, []).append(r)
            by_level.setdefault(r.level, []).append(r)

        self.summary["by_model"] = {}
        for model, results in by_model.items():
            self.summary["by_model"][model] = {
                "avg_rule_accuracy": sum(r.rule_accuracy for r in results) / len(results),
                "avg_integration": sum(r.integration_completeness for r in results) / len(results),
                "broken_count": sum(1 for r in results if r.broken),
                "levels_tested": sorted(r.level for r in results),
            }

        self.summary["by_level"] = {}
        for level, results in by_level.items():
            self.summary["by_level"][str(level)] = {
                "models_broken": [r.model_name for r in results if r.broken],
                "models_passed": [r.model_name for r in results if not r.broken],
            }

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "summary": self.summary,
        }

    def to_markdown(self) -> str:
        """Generate markdown comparison table."""
        lines = [
            "# Labyrinth Baseline Comparison",
            "",
            "## Results Matrix",
            "",
            "| Model | Level | Rule Accuracy | Integration | Broken |",
            "| --- | --- | --- | --- | --- |",
        ]

        for r in sorted(self.results, key=lambda x: (x.model_name, x.level)):
            broken_icon = "YES" if r.broken else "no"
            lines.append(
                f"| {r.model_name} | {r.level} | "
                f"{r.rule_accuracy:.1%} | {r.integration_completeness:.1%} | "
                f"{broken_icon} |"
            )

        lines.append("")

        if self.summary.get("by_model"):
            lines.append("## By Model")
            lines.append("")
            for model, stats in self.summary["by_model"].items():
                lines.append(f"### {model}")
                lines.append(f"- Avg Rule Accuracy: {stats['avg_rule_accuracy']:.1%}")
                lines.append(f"- Avg Integration: {stats['avg_integration']:.1%}")
                lines.append(f"- Broken at levels: {stats['broken_count']}")
                lines.append("")

        return "\n".join(lines)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        md_path = path.with_suffix(".md")
        md_path.write_text(self.to_markdown(), encoding="utf-8")
