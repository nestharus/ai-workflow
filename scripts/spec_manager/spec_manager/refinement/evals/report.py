"""Report generation for evaluation results.

Generates markdown and JSON reports from evaluation results for
bottleneck identification and system improvement analysis.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spec_manager.refinement.evals.baselines.results.comparison import ComparisonReport

from spec_manager.refinement.evals.metrics import (
    ConvergenceAnalysis,
    DetailCaptureMetrics,
    PhaseMetrics,
)


@dataclass
class EvalResult:
    """Complete result of evaluating a single spec.

    Attributes:
        spec_id: ID of the evaluated spec.
        spec_title: Title of the evaluated spec.
        success: Whether the evaluation completed successfully.
        total_duration_ms: Total evaluation time in milliseconds.
        phases_completed: Number of phases completed.
        phases_total: Total number of phases.
        detail_metrics: Aggregate detail capture metrics.
        convergence_analysis: Convergence analysis results.
        phase_results: Results for each phase.
        bottlenecks: Identified bottlenecks.
        errors: List of errors encountered.
    """

    spec_id: str
    spec_title: str
    success: bool = True
    total_duration_ms: float = 0.0
    phases_completed: int = 0
    phases_total: int = 0
    detail_metrics: DetailCaptureMetrics | None = None
    convergence_analysis: ConvergenceAnalysis | None = None
    phase_results: dict[str, PhaseMetrics] = field(default_factory=dict)
    bottlenecks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "spec_id": self.spec_id,
            "spec_title": self.spec_title,
            "success": self.success,
            "total_duration_ms": self.total_duration_ms,
            "phases_completed": self.phases_completed,
            "phases_total": self.phases_total,
            "detail_metrics": self.detail_metrics.to_dict() if self.detail_metrics else None,
            "convergence_analysis": (
                self.convergence_analysis.to_dict() if self.convergence_analysis else None
            ),
            "phase_results": {
                name: metrics.to_dict() for name, metrics in self.phase_results.items()
            },
            "bottlenecks": self.bottlenecks,
            "errors": self.errors,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalResult:
        """Deserialize from dictionary."""
        detail_data = data.get("detail_metrics")
        detail_metrics = DetailCaptureMetrics.from_dict(detail_data) if detail_data else None
        conv_data = data.get("convergence_analysis")
        convergence = ConvergenceAnalysis.from_dict(conv_data) if conv_data else None

        return cls(
            spec_id=data.get("spec_id", ""),
            spec_title=data.get("spec_title", ""),
            success=data.get("success", True),
            total_duration_ms=data.get("total_duration_ms", 0.0),
            phases_completed=data.get("phases_completed", 0),
            phases_total=data.get("phases_total", 0),
            detail_metrics=detail_metrics,
            convergence_analysis=convergence,
            phase_results={
                name: PhaseMetrics.from_dict(metrics)
                for name, metrics in data.get("phase_results", {}).items()
            },
            bottlenecks=data.get("bottlenecks", []),
            errors=data.get("errors", []),
        )


@dataclass
class EvalReport:
    """Report summarizing evaluation results across multiple specs.

    Attributes:
        run_id: Unique identifier for the evaluation run.
        generated_at: Timestamp when report was generated.
        specs_evaluated: Number of specs evaluated.
        specs_passed: Number of specs that passed.
        specs_failed: Number of specs that failed.
        results: Results for each spec.
        aggregate_metrics: Aggregate metrics across all specs.
        common_bottlenecks: Bottlenecks common across specs.
        recommendations: System improvement recommendations.
    """

    run_id: str
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    specs_evaluated: int = 0
    specs_passed: int = 0
    specs_failed: int = 0
    results: list[EvalResult] = field(default_factory=list)
    aggregate_metrics: dict[str, Any] = field(default_factory=dict)
    common_bottlenecks: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)

    def add_result(self, result: EvalResult) -> None:
        """Add a spec result to the report.

        Args:
            result: EvalResult to add.
        """
        self.results.append(result)
        self.specs_evaluated += 1
        if result.success:
            self.specs_passed += 1
        else:
            self.specs_failed += 1

    def compute_aggregates(self) -> None:
        """Compute aggregate metrics and identify common bottlenecks."""
        if not self.results:
            return

        # Aggregate precision/recall
        total_expected = 0
        total_captured = 0
        total_spurious = 0

        for result in self.results:
            if result.detail_metrics:
                total_expected += result.detail_metrics.total_details_expected
                total_captured += result.detail_metrics.total_details_captured
                total_spurious += result.detail_metrics.total_details_spurious

        self.aggregate_metrics["total_details_expected"] = total_expected
        self.aggregate_metrics["total_details_captured"] = total_captured
        self.aggregate_metrics["total_details_spurious"] = total_spurious

        if total_expected > 0:
            self.aggregate_metrics["overall_recall"] = total_captured / total_expected
        else:
            self.aggregate_metrics["overall_recall"] = 1.0

        total_actual = total_captured + total_spurious
        if total_actual > 0:
            self.aggregate_metrics["overall_precision"] = total_captured / total_actual
        else:
            self.aggregate_metrics["overall_precision"] = 1.0

        # Collect bottlenecks
        bottleneck_counts: dict[str, int] = {}
        for result in self.results:
            for bottleneck in result.bottlenecks:
                bottleneck_counts[bottleneck] = bottleneck_counts.get(bottleneck, 0) + 1

        # Bottlenecks appearing in >50% of specs
        threshold = max(1, len(self.results) // 2)
        self.common_bottlenecks = [
            bottleneck
            for bottleneck, count in sorted(bottleneck_counts.items(), key=lambda x: -x[1])
            if count >= threshold
        ]

        # Generate recommendations
        self._generate_recommendations()

    def _generate_recommendations(self) -> None:
        """Generate improvement recommendations based on results."""
        self.recommendations.clear()

        # Check overall precision
        precision = self.aggregate_metrics.get("overall_precision", 1.0)
        if precision < 0.8:
            self.recommendations.append(
                f"Low precision ({precision:.1%}): Consider stricter output validation "
                "to reduce hallucinated details."
            )

        # Check overall recall
        recall = self.aggregate_metrics.get("overall_recall", 1.0)
        if recall < 0.8:
            self.recommendations.append(
                f"Low recall ({recall:.1%}): Consider improving extraction coverage "
                "to capture more expected details."
            )

        # Check for convergence issues
        non_converged = sum(
            1
            for result in self.results
            if result.convergence_analysis and not result.convergence_analysis.converged
        )
        if non_converged > 0:
            self.recommendations.append(
                f"{non_converged} spec(s) did not converge: Consider increasing "
                "iteration limits or improving gap resolution."
            )

        # Check common bottlenecks
        if self.common_bottlenecks:
            self.recommendations.append(
                f"Common bottlenecks detected: {', '.join(self.common_bottlenecks[:3])}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "specs_evaluated": self.specs_evaluated,
            "specs_passed": self.specs_passed,
            "specs_failed": self.specs_failed,
            "results": [result.to_dict() for result in self.results],
            "aggregate_metrics": self.aggregate_metrics,
            "common_bottlenecks": self.common_bottlenecks,
            "recommendations": self.recommendations,
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalReport:
        """Deserialize from dictionary."""
        report = cls(
            run_id=data.get("run_id", ""),
            generated_at=data.get("generated_at", datetime.now().isoformat()),
            specs_evaluated=data.get("specs_evaluated", 0),
            specs_passed=data.get("specs_passed", 0),
            specs_failed=data.get("specs_failed", 0),
            aggregate_metrics=data.get("aggregate_metrics", {}),
            common_bottlenecks=data.get("common_bottlenecks", []),
            recommendations=data.get("recommendations", []),
            config=data.get("config", {}),
        )
        for result_data in data.get("results", []):
            report.results.append(EvalResult.from_dict(result_data))
        return report


def generate_markdown_report(report: EvalReport) -> str:
    """Generate a markdown report from evaluation results.

    Args:
        report: EvalReport to convert.

    Returns:
        Markdown formatted report string.
    """
    lines = [
        "# Spec Refinement Evaluation Report",
        "",
        f"**Run ID:** {report.run_id}",
        f"**Generated:** {report.generated_at}",
        "",
        "## Summary",
        "",
        f"- **Specs Evaluated:** {report.specs_evaluated}",
        f"- **Passed:** {report.specs_passed}",
        f"- **Failed:** {report.specs_failed}",
        f"- **Pass Rate:** "
        f"{_format_percentage(report.specs_passed / max(1, report.specs_evaluated))}",
    ]

    if report.config.get("use_judge"):
        lines.append("- **Scoring Method:** LLM Judge (semantic matching)")
    else:
        lines.append("- **Scoring Method:** Fuzzy string matching")

    lines.append("")

    # Aggregate metrics
    if report.aggregate_metrics:
        lines.extend(
            [
                "## Aggregate Metrics",
                "",
                "| Metric | Value |",
                "| --- | --- |",
            ]
        )
        recall = report.aggregate_metrics.get("overall_recall", 0)
        precision = report.aggregate_metrics.get("overall_precision", 0)
        f1 = 2 * recall * precision / (recall + precision) if (recall + precision) > 0 else 0

        lines.append(f"| Overall Recall | {_format_percentage(recall)} |")
        lines.append(f"| Overall Precision | {_format_percentage(precision)} |")
        lines.append(f"| Overall F1 | {_format_percentage(f1)} |")
        lines.append(
            f"| Total Details Expected | "
            f"{report.aggregate_metrics.get('total_details_expected', 0)} |"
        )
        lines.append(
            f"| Total Details Captured | "
            f"{report.aggregate_metrics.get('total_details_captured', 0)} |"
        )
        lines.append(
            f"| Total Spurious Details | "
            f"{report.aggregate_metrics.get('total_details_spurious', 0)} |"
        )
        lines.append("")

    # Per-spec results
    lines.extend(
        [
            "## Per-Spec Results",
            "",
            "| Spec | Status | Recall | Precision | F1 | Phases | Bottlenecks |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )

    for result in report.results:
        status = "✅" if result.success else "❌"
        recall = precision = f1 = 0.0
        if result.detail_metrics:
            recall = result.detail_metrics.recall
            precision = result.detail_metrics.precision
            f1 = result.detail_metrics.f1

        phases = f"{result.phases_completed}/{result.phases_total}"
        bottlenecks = ", ".join(result.bottlenecks[:2]) if result.bottlenecks else "-"

        lines.append(
            f"| {result.spec_id} | {status} | "
            f"{_format_percentage(recall)} | {_format_percentage(precision)} | "
            f"{_format_percentage(f1)} | {phases} | {bottlenecks} |"
        )

    lines.append("")

    # Ambiguity detection metrics (sparse-to-dense results)
    sparse_results = [r for r in report.results if "(sparse-to-dense)" in r.spec_title]
    if sparse_results:
        lines.extend(
            [
                "## Sparse-to-Dense Steering Results",
                "",
                "| Spec | Recall | Precision | Duration |",
                "| --- | --- | --- | --- |",
            ]
        )
        for result in sparse_results:
            recall = precision = 0.0
            if result.detail_metrics:
                recall = result.detail_metrics.recall
                precision = result.detail_metrics.precision
            duration = f"{result.total_duration_ms:.0f}ms"
            lines.append(
                f"| {result.spec_id} | {_format_percentage(recall)} | "
                f"{_format_percentage(precision)} | {duration} |"
            )
        lines.append("")

    # Bottlenecks
    if report.common_bottlenecks:
        lines.extend(
            [
                "## Common Bottlenecks",
                "",
            ]
        )
        for bottleneck in report.common_bottlenecks:
            lines.append(f"- {bottleneck}")
        lines.append("")

    # Recommendations
    if report.recommendations:
        lines.extend(
            [
                "## Recommendations",
                "",
            ]
        )
        for rec in report.recommendations:
            lines.append(f"- {rec}")
        lines.append("")

    # Errors
    all_errors = [error for result in report.results for error in result.errors]
    if all_errors:
        lines.extend(
            [
                "## Errors",
                "",
            ]
        )
        for error in all_errors[:10]:  # Limit to first 10 errors
            lines.append(f"- {error}")
        if len(all_errors) > 10:
            lines.append(f"- ... and {len(all_errors) - 10} more errors")
        lines.append("")

    return "\n".join(lines)


def _format_percentage(value: float) -> str:
    """Format a float as a percentage string."""
    return f"{value * 100:.1f}%"


def generate_labyrinth_report(comparison: ComparisonReport) -> str:
    """Generate markdown report for labyrinth baseline comparison.

    Args:
        comparison: ComparisonReport from baselines.results.comparison.

    Returns:
        Markdown formatted report string.
    """
    lines = ["# Labyrinth Evaluation Report", ""]

    model_summaries = comparison.summary.get("by_model", {})
    level_summaries = comparison.summary.get("by_level", {})

    lines.append(f"**Models:** {len(model_summaries)}")
    lines.append(f"**Levels:** {len(level_summaries)}")
    lines.append("")

    # By model
    lines.append("## Results by Model")
    lines.append("")
    lines.append("| Model | Avg Rule Accuracy | Avg Integration | Broken Levels |")
    lines.append("|-------|-------------------|-----------------|---------------|")
    for model, summary in sorted(model_summaries.items()):
        lines.append(
            f"| {model} | {summary.get('avg_rule_accuracy', 0):.1%} "
            f"| {summary.get('avg_integration', 0):.1%} "
            f"| {summary.get('broken_count', 0)} |"
        )
    lines.append("")

    # By level - compute averages from results since by_level only has broken/passed lists
    by_level_results: dict[int, list] = {}
    for r in comparison.results:
        by_level_results.setdefault(r.level, []).append(r)

    lines.append("## Results by Level")
    lines.append("")
    lines.append("| Level | Avg Rule Accuracy | Avg Integration | Models Broken |")
    lines.append("|-------|-------------------|-----------------|---------------|")
    for level in sorted(by_level_results.keys()):
        results = by_level_results[level]
        avg_rule = sum(r.rule_accuracy for r in results) / len(results) if results else 0
        avg_integ = (
            sum(r.integration_completeness for r in results) / len(results) if results else 0
        )
        level_summary = level_summaries.get(str(level), {})
        broken_count = len(level_summary.get("models_broken", []))
        lines.append(f"| L{level} | {avg_rule:.1%} | {avg_integ:.1%} | {broken_count} |")
    lines.append("")

    return "\n".join(lines)


def save_report(
    report: EvalReport, output_dir: Path, report_name: str = "eval_report"
) -> dict[str, Path]:
    """Save report in both JSON and markdown formats.

    Args:
        report: EvalReport to save.
        output_dir: Directory to save reports to.
        report_name: Base name for report files.

    Returns:
        Dictionary mapping format to file path.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save JSON
    json_path = output_dir / f"{report_name}.json"
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2),
        encoding="utf-8",
    )

    # Save markdown
    md_path = output_dir / f"{report_name}.md"
    md_path.write_text(generate_markdown_report(report), encoding="utf-8")

    return {"json": json_path, "markdown": md_path}


def load_report(path: Path) -> EvalReport:
    """Load a report from a JSON file.

    Args:
        path: Path to the JSON report file.

    Returns:
        Loaded EvalReport.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file format is invalid.
    """
    if not path.exists():
        raise FileNotFoundError(f"Report file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return EvalReport.from_dict(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid report format: {exc}") from exc
