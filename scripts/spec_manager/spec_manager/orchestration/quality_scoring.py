"""Quality scoring framework for architecture and code evaluation.

Computes quality metrics by blending mechanical graph/text metrics with
LLM judge scores to produce a unified quality scorecard.

Architecture quality:
    arch.quality_score = 0.35 * mechanical + 0.65 * judge

Code quality:
    code.quality_score = 0.40 * mechanical + 0.60 * judge

Thresholds:
    PASS: score >= 0.80 and no CRITICAL risks
    WARN: 0.65 <= score < 0.80 or any MAJOR risks
    FAIL: score < 0.65 or any CRITICAL risks

Usage::

    reporter = QualityReporter(
        workspace_root=Path("."),
        run_id="abc",
    )
    scorecard = reporter.compute(arch_digest, code_digest, judges=True)
    reporter.write(scorecard)
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QualityMetric:
    """A single quality metric."""

    name: str = ""
    raw: float = 0.0
    score: float = 0.0  # 0.0-1.0 normalized
    status: str = "PASS"  # PASS | WARN | FAIL
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QualityScorecard:
    """Complete quality scorecard for a run."""

    run_id: str = ""
    architecture: list[QualityMetric] = field(default_factory=list)
    code: list[QualityMetric] = field(default_factory=list)
    spec_fidelity: list[QualityMetric] = field(default_factory=list)
    arch_quality_score: float = 0.0
    code_quality_score: float = 0.0
    spec_fidelity_score: float = 0.0
    composite_score: float = 0.0
    composite_status: str = ""
    overall_status: str = "PASS"
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "arch_quality_score": self.arch_quality_score,
            "code_quality_score": self.code_quality_score,
            "spec_fidelity_score": self.spec_fidelity_score,
            "composite_score": self.composite_score,
            "composite_status": self.composite_status,
            "overall_status": self.overall_status,
            "summary": self.summary,
            "architecture": [m.to_dict() for m in self.architecture],
            "code": [m.to_dict() for m in self.code],
            "spec_fidelity": [m.to_dict() for m in self.spec_fidelity],
        }


# ---------------------------------------------------------------------------
# Mechanical scorers
# ---------------------------------------------------------------------------


class ArchitectureQualityScorer:
    """Compute mechanical architecture metrics from digest."""

    def compute(self, digest: dict[str, Any]) -> list[QualityMetric]:
        """Compute mechanical architecture metrics.

        Returns list of QualityMetric for:
        - coupling_score
        - graph_health_score
        - completeness_proxy_score
        - l2_finding_severity_score
        """
        topology = digest.get("topology", {})
        components = topology.get("components", [])
        edges = topology.get("edges", [])
        coverage = digest.get("coverage", {})
        l2_findings = digest.get("l2_review", {}).get("final_findings", {})

        n = len(components)
        e = len(edges)

        metrics: list[QualityMetric] = []

        # Graph health
        edge_density = e / max(1, n * (n - 1)) if n > 1 else 0.0
        has_cycles = self._detect_cycles(components, edges)
        graph_health = 0.5 * _clamp01(1 - edge_density * 5) + 0.5 * (1.0 if not has_cycles else 0.3)
        metrics.append(
            QualityMetric(
                name="arch.graph_health",
                raw=graph_health,
                score=graph_health,
                status=_threshold_status(graph_health),
                detail=f"density={edge_density:.3f}, cycles={has_cycles}",
            )
        )

        # Coupling
        fan_outs = {c.get("id", ""): len(c.get("depends_on", [])) for c in components}
        max_fan_out = max(fan_outs.values()) if fan_outs else 0
        fan_out_score = _clamp01(1 - (max_fan_out - 3) / 10)

        fan_ins: dict[str, int] = {}
        for c in components:
            for dep in c.get("depends_on", []):
                fan_ins[dep] = fan_ins.get(dep, 0) + 1
        max_fan_in = max(fan_ins.values()) if fan_ins else 0
        fan_in_score = _clamp01(1 - (max_fan_in - 5) / 10)

        coupling_score = 0.5 * fan_out_score + 0.5 * fan_in_score
        metrics.append(
            QualityMetric(
                name="arch.coupling",
                raw=coupling_score,
                score=coupling_score,
                status=_threshold_status(coupling_score),
                detail=f"max_fan_out={max_fan_out}, max_fan_in={max_fan_in}",
            )
        )

        # Completeness proxy
        req_total = coverage.get("requirements_total", 0)
        req_mapped = coverage.get("requirements_mapped", 0)
        mapping_rate = req_mapped / max(1, req_total)
        completeness = mapping_rate if req_total > 0 else 1.0  # Assume complete if no reqs
        metrics.append(
            QualityMetric(
                name="arch.completeness",
                raw=completeness,
                score=completeness,
                status=_threshold_status(completeness),
                detail=f"mapped={req_mapped}/{req_total}",
            )
        )

        # L2 finding severity
        blockers = l2_findings.get("BLOCKER", 0)
        majors = l2_findings.get("MAJOR", 0)
        minors = l2_findings.get("MINOR", 0)
        severity_weighted = 5 * blockers + 2 * majors + minors
        severity_score = _clamp01(1 - severity_weighted / 20)
        metrics.append(
            QualityMetric(
                name="arch.l2_severity",
                raw=float(severity_weighted),
                score=severity_score,
                status=_threshold_status(severity_score),
                detail=f"BLOCKER={blockers}, MAJOR={majors}, MINOR={minors}",
            )
        )

        return metrics

    def mechanical_score(self, metrics: list[QualityMetric]) -> float:
        """Compute blended mechanical architecture score."""
        by_name = {m.name: m.score for m in metrics}
        return (
            0.30 * by_name.get("arch.coupling", 0.0)
            + 0.20 * by_name.get("arch.graph_health", 0.0)
            + 0.25 * by_name.get("arch.completeness", 0.0)
            + 0.25 * by_name.get("arch.l2_severity", 0.0)
        )

    def _detect_cycles(self, components: list[dict], edges: list[dict]) -> bool:
        """Simple DFS cycle detection."""
        adj: dict[str, list[str]] = {}
        for e in edges:
            src = e.get("from", "")
            dst = e.get("to", "")
            if src not in adj:
                adj[src] = []
            adj[src].append(dst)

        visited: set[str] = set()
        in_stack: set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            in_stack.add(node)
            for neighbor in adj.get(node, []):
                if neighbor in in_stack:
                    return True
                if neighbor not in visited and dfs(neighbor):
                    return True
            in_stack.discard(node)
            return False

        for c in components:
            cid = c.get("id", "")
            if cid not in visited and dfs(cid):
                return True
        return False


class CodeQualityScorer:
    """Compute mechanical code metrics from digest."""

    def compute(self, digest: dict[str, Any]) -> list[QualityMetric]:
        """Compute mechanical code metrics.

        Returns list of QualityMetric for:
        - code.issue_density
        - code.file_size_outliers
        - code.churn (placeholder)
        """
        codebase = digest.get("codebase", {})
        files = codebase.get("files", [])
        totals = codebase.get("totals", {})
        l3_findings = digest.get("l3_review", {}).get("final_findings", {})

        total_loc = totals.get("loc", 0)
        metrics: list[QualityMetric] = []

        # Issue density
        blockers = l3_findings.get("BLOCKER", 0)
        majors = l3_findings.get("MAJOR", 0)
        minors = l3_findings.get("MINOR", 0)
        weighted = 5 * blockers + 2 * majors + minors
        density = weighted / max(1, total_loc / 1000)
        density_score = _clamp01(1 - density / 10)
        metrics.append(
            QualityMetric(
                name="code.issue_density",
                raw=density,
                score=density_score,
                status=_threshold_status(density_score),
                detail=f"weighted_issues={weighted}, kloc={total_loc / 1000:.1f}",
            )
        )

        # File size outliers
        if files:
            locs = [f.get("loc", 0) for f in files]
            if locs:
                sorted_locs = sorted(locs)
                p95_idx = int(len(sorted_locs) * 0.95)
                p95 = sorted_locs[min(p95_idx, len(sorted_locs) - 1)]
                threshold = p95 * 2 if p95 > 0 else 500
                outlier_count = sum(1 for loc in locs if loc > threshold)
                outlier_ratio = outlier_count / max(1, len(files))
            else:
                outlier_ratio = 0.0
                outlier_count = 0
        else:
            outlier_ratio = 0.0
            outlier_count = 0
        outlier_score = _clamp01(1 - outlier_ratio * 5)
        metrics.append(
            QualityMetric(
                name="code.file_size_outliers",
                raw=float(outlier_count),
                score=outlier_score,
                status=_threshold_status(outlier_score),
                detail=f"outliers={outlier_count}/{len(files)}",
            )
        )

        # Churn placeholder (reuse l3.refactor_churn if available)
        churn_score = 1.0  # Default healthy
        metrics.append(
            QualityMetric(
                name="code.churn",
                raw=0.0,
                score=churn_score,
                status="PASS",
                detail="placeholder — integrate with l3.refactor_churn",
            )
        )

        return metrics

    def mechanical_score(self, metrics: list[QualityMetric]) -> float:
        """Compute blended mechanical code score."""
        by_name = {m.name: m.score for m in metrics}
        return (
            0.35 * by_name.get("code.issue_density", 0.0)
            + 0.25 * by_name.get("code.churn", 0.0)
            + 0.20 * by_name.get("code.file_size_outliers", 0.0)
            + 0.20 * 1.0  # duplication placeholder
        )


class SpecFidelityScorer:
    """Score from spec fidelity judge (no mechanical component)."""

    def compute(self, judge_output: dict[str, Any] | None) -> list[QualityMetric]:
        """Extract spec fidelity score from judge output."""
        if not judge_output:
            return [
                QualityMetric(
                    name="spec.fidelity",
                    raw=0.0,
                    score=0.0,
                    status="FAIL",
                    detail="No judge output available",
                )
            ]

        coverage = judge_output.get("coverage_estimate", 0.0)
        missing = judge_output.get("missing", [])
        hallucinated = judge_output.get("hallucinated", [])

        status = _threshold_status(coverage)
        if hallucinated:
            status = "WARN" if status == "PASS" else status

        return [
            QualityMetric(
                name="spec.fidelity",
                raw=coverage,
                score=coverage,
                status=status,
                detail=f"missing={len(missing)}, hallucinated={len(hallucinated)}",
            )
        ]


# ---------------------------------------------------------------------------
# QualityReporter
# ---------------------------------------------------------------------------


class QualityReporter:
    """Orchestrates quality scoring and report generation."""

    def __init__(self, workspace_root: Path, run_id: str) -> None:
        self.workspace_root = workspace_root
        self.run_id = run_id
        self._reports_dir = workspace_root / "reports" / "pdd" / run_id

    def compute(
        self,
        arch_digest: dict[str, Any],
        code_digest: dict[str, Any],
        arch_judge_output: dict[str, Any] | None = None,
        code_judge_output: dict[str, Any] | None = None,
        spec_judge_output: dict[str, Any] | None = None,
    ) -> QualityScorecard:
        """Compute quality scorecard.

        Args:
            arch_digest: Architecture digest.
            code_digest: Code digest.
            arch_judge_output: Optional ArchJudgeOutput dict.
            code_judge_output: Optional CodeJudgeOutput dict.
            spec_judge_output: Optional SpecFidelityOutput dict.

        Returns:
            QualityScorecard with all metrics.
        """
        # Architecture
        arch_scorer = ArchitectureQualityScorer()
        arch_metrics = arch_scorer.compute(arch_digest)
        arch_mechanical = arch_scorer.mechanical_score(arch_metrics)

        arch_judge_score = 0.5  # default middle
        if arch_judge_output:
            overall = arch_judge_output.get("overall", 3)
            arch_judge_score = (overall - 1) / 4

        arch_quality = 0.35 * arch_mechanical + 0.65 * arch_judge_score

        # Check for critical risks
        arch_has_critical = False
        arch_has_major = False
        if arch_judge_output:
            for risk in arch_judge_output.get("risks", []):
                sev = risk.get("severity", "").upper()
                if sev == "CRITICAL":
                    arch_has_critical = True
                elif sev == "MAJOR":
                    arch_has_major = True

        arch_status = _quality_status(arch_quality, arch_has_critical, arch_has_major)
        arch_metrics.append(
            QualityMetric(
                name="arch.quality_score",
                raw=arch_quality,
                score=arch_quality,
                status=arch_status,
                detail=f"mechanical={arch_mechanical:.3f}, judge={arch_judge_score:.3f}",
            )
        )

        # Code
        code_scorer = CodeQualityScorer()
        code_metrics = code_scorer.compute(code_digest)
        code_mechanical = code_scorer.mechanical_score(code_metrics)

        code_judge_score = 0.5  # default middle
        if code_judge_output:
            overall = code_judge_output.get("overall", 3)
            code_judge_score = (overall - 1) / 4

        code_quality = 0.40 * code_mechanical + 0.60 * code_judge_score

        code_has_critical = False
        code_has_major = False
        if code_judge_output:
            for risk in code_judge_output.get("systemic_risks", []):
                sev = risk.get("severity", "").upper()
                if sev == "CRITICAL":
                    code_has_critical = True
                elif sev == "MAJOR":
                    code_has_major = True

        code_status = _quality_status(code_quality, code_has_critical, code_has_major)
        code_metrics.append(
            QualityMetric(
                name="code.quality_score",
                raw=code_quality,
                score=code_quality,
                status=code_status,
                detail=f"mechanical={code_mechanical:.3f}, judge={code_judge_score:.3f}",
            )
        )

        # Spec fidelity
        spec_scorer = SpecFidelityScorer()
        spec_metrics = spec_scorer.compute(spec_judge_output)
        spec_fidelity_score = spec_metrics[0].score if spec_metrics else 0.0

        # Overall
        overall_status = "PASS"
        if arch_status == "FAIL" or code_status == "FAIL":
            overall_status = "FAIL"
        elif arch_status == "WARN" or code_status == "WARN":
            overall_status = "WARN"
        for m in spec_metrics:
            if m.status == "FAIL":
                overall_status = "FAIL"
            elif m.status == "WARN" and overall_status == "PASS":
                overall_status = "WARN"

        # Composite score (Section 7.3)
        # quality_overall = avg of arch + code (or whichever exists)
        if arch_quality > 0 and code_quality > 0:
            quality_overall = (arch_quality + code_quality) / 2
        elif arch_quality > 0:
            quality_overall = arch_quality
        else:
            quality_overall = code_quality

        spec_fidelity_for_composite = spec_fidelity_score  # 0.0 if no judge
        pipeline_efficiency = 1.0  # placeholder
        planner_quality = 1.0  # placeholder

        composite_score = (
            0.45 * quality_overall
            + 0.20 * spec_fidelity_for_composite
            + 0.20 * pipeline_efficiency
            + 0.15 * planner_quality
        )
        composite_status = _threshold_status(composite_score)

        summary_parts = [
            f"arch={arch_quality:.2f}({arch_status})",
            f"code={code_quality:.2f}({code_status})",
            f"spec={spec_fidelity_score:.2f}",
            f"composite={composite_score:.2f}({composite_status})",
        ]

        return QualityScorecard(
            run_id=self.run_id,
            architecture=arch_metrics,
            code=code_metrics,
            spec_fidelity=spec_metrics,
            arch_quality_score=arch_quality,
            code_quality_score=code_quality,
            spec_fidelity_score=spec_fidelity_score,
            composite_score=composite_score,
            composite_status=composite_status,
            overall_status=overall_status,
            summary=", ".join(summary_parts),
        )

    def write(self, scorecard: QualityScorecard) -> tuple[Path, Path]:
        """Write quality scorecard as JSON and markdown.

        Returns:
            Tuple of (json_path, md_path).
        """
        self._reports_dir.mkdir(parents=True, exist_ok=True)

        # JSON
        json_path = self._reports_dir / "quality_scorecard.json"
        json_path.write_text(json.dumps(scorecard.to_dict(), indent=2), encoding="utf-8")

        # Markdown
        md_path = self._reports_dir / "quality_scorecard.md"
        md_path.write_text(self._render_markdown(scorecard), encoding="utf-8")

        logger.info("Quality scorecard written to %s", self._reports_dir)
        return json_path, md_path

    def _render_markdown(self, scorecard: QualityScorecard) -> str:
        """Render scorecard as markdown."""
        lines = [
            f"# Quality Scorecard — Run `{scorecard.run_id}`",
            "",
            f"**Overall Status**: {scorecard.overall_status}",
            f"**Composite Score**: {scorecard.composite_score:.3f} ({scorecard.composite_status})",
            f"**Summary**: {scorecard.summary}",
            "",
            "## Architecture Quality",
            "",
            f"**Score**: {scorecard.arch_quality_score:.3f}",
            "",
            "| Metric | Raw | Score | Status | Detail |",
            "|--------|-----|-------|--------|--------|",
        ]
        for m in scorecard.architecture:
            lines.append(f"| {m.name} | {m.raw:.3f} | {m.score:.3f} | {m.status} | {m.detail} |")

        lines.extend(
            [
                "",
                "## Code Quality",
                "",
                f"**Score**: {scorecard.code_quality_score:.3f}",
                "",
                "| Metric | Raw | Score | Status | Detail |",
                "|--------|-----|-------|--------|--------|",
            ]
        )
        for m in scorecard.code:
            lines.append(f"| {m.name} | {m.raw:.3f} | {m.score:.3f} | {m.status} | {m.detail} |")

        lines.extend(
            [
                "",
                "## Spec Fidelity",
                "",
                f"**Score**: {scorecard.spec_fidelity_score:.3f}",
                "",
                "| Metric | Raw | Score | Status | Detail |",
                "|--------|-----|-------|--------|--------|",
            ]
        )
        for m in scorecard.spec_fidelity:
            lines.append(f"| {m.name} | {m.raw:.3f} | {m.score:.3f} | {m.status} | {m.detail} |")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp01(value: float) -> float:
    """Clamp a value to [0, 1]."""
    return max(0.0, min(1.0, value))


def _threshold_status(score: float) -> str:
    """Map score to status: PASS >= 0.80, WARN >= 0.65, FAIL < 0.65."""
    if score >= 0.80:
        return "PASS"
    if score >= 0.65:
        return "WARN"
    return "FAIL"


def _quality_status(score: float, has_critical: bool, has_major: bool) -> str:
    """Map quality score + risk flags to status."""
    if has_critical or score < 0.65:
        return "FAIL"
    if has_major or score < 0.80:
        return "WARN"
    return "PASS"
