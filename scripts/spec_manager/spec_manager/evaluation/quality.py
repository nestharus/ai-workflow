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
    architecture_judge_dimensions: list[str] = field(default_factory=list)
    architecture_risks: list[dict[str, Any] | str] = field(default_factory=list)
    code_sampled_files: list[dict[str, Any]] = field(default_factory=list)
    code_risks: list[dict[str, Any] | str] = field(default_factory=list)
    spec_missing_items: list[str] = field(default_factory=list)

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
            "architecture_judge_dimensions": self.architecture_judge_dimensions,
            "architecture_risks": self.architecture_risks,
            "code_sampled_files": self.code_sampled_files,
            "code_risks": self.code_risks,
            "spec_missing_items": self.spec_missing_items,
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

        component_ids = [
            str(component.get("id", "")) for component in components if component.get("id")
        ]
        fan_out: dict[str, int] = {component_id: 0 for component_id in component_ids}
        fan_in: dict[str, int] = {component_id: 0 for component_id in component_ids}
        for edge in edges:
            src = str(edge.get("from", ""))
            dst = str(edge.get("to", ""))
            if src:
                fan_out[src] = fan_out.get(src, 0) + 1
                fan_in.setdefault(src, fan_in.get(src, 0))
            if dst:
                fan_in[dst] = fan_in.get(dst, 0) + 1
                fan_out.setdefault(dst, fan_out.get(dst, 0))

        node_ids = sorted(set(component_ids) | set(fan_in.keys()) | set(fan_out.keys()))
        max_fan_out = max((fan_out.get(component_id, 0) for component_id in node_ids), default=0)
        max_fan_in = max((fan_in.get(component_id, 0) for component_id in node_ids), default=0)
        avg_fan_out = sum(fan_out.get(component_id, 0) for component_id in node_ids) / max(
            1, len(node_ids)
        )
        avg_fan_in = sum(fan_in.get(component_id, 0) for component_id in node_ids) / max(
            1, len(node_ids)
        )
        degree_values = [
            fan_in.get(component_id, 0) + fan_out.get(component_id, 0) for component_id in node_ids
        ]
        degree_concentration = self._gini(degree_values)

        edge_density = e / max(1, n * (n - 1)) if n > 1 else 0.0
        cycles_present, cycles_count, scc_count = self._cycle_stats(node_ids, edges)
        cycles_score = 1.0 if not cycles_present else 0.3
        density_score = _clamp01(1 - edge_density / 0.35)
        graph_health = 0.6 * density_score + 0.4 * cycles_score

        orphan_components = [
            component_id
            for component_id in component_ids
            if fan_in.get(component_id, 0) == 0 and fan_out.get(component_id, 0) == 0
        ]
        bottlenecks = [
            component_id
            for component_id, count in sorted(
                fan_in.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:3]
            if count > 0
        ]
        hub_threshold = max(3, int(len(node_ids) * 0.25))
        utility_hubs = []
        for component in components:
            component_id = str(component.get("id", ""))
            if not component_id or fan_in.get(component_id, 0) < hub_threshold:
                continue
            responsibilities = component.get("responsibilities", [])
            responsibilities_count = (
                len(responsibilities) if isinstance(responsibilities, list) else 0
            )
            if responsibilities_count <= 1:
                utility_hubs.append(component_id)
        utility_hub_ratio = len(utility_hubs) / max(1, n)

        fan_out_score = _clamp01(1 - (max_fan_out - 3) / 10)
        fan_in_score = _clamp01(1 - (max_fan_in - 5) / 10)
        coupling_risk = (
            _clamp01((max_fan_out - 3) / 10)
            + _clamp01(edge_density / 0.35)
            + _clamp01(degree_concentration)
        ) / 3.0
        coupling_score = _clamp01(1 - coupling_risk)

        # Diagnostic mechanical sub-metrics
        metrics.append(
            QualityMetric(
                name="arch.components_count",
                raw=float(n),
                score=1.0,
                status="PASS",
                detail=f"components={n}",
            )
        )
        metrics.append(
            QualityMetric(
                name="arch.edges_count",
                raw=float(e),
                score=1.0,
                status="PASS",
                detail=f"edges={e}",
            )
        )
        metrics.append(
            QualityMetric(
                name="arch.edge_density",
                raw=edge_density,
                score=density_score,
                status=_threshold_status(density_score),
                detail=f"edges={e}, nodes={n}",
            )
        )
        metrics.append(
            QualityMetric(
                name="arch.cycles",
                raw=float(cycles_count),
                score=cycles_score,
                status=_threshold_status(cycles_score),
                detail=f"present={cycles_present}, cycles={cycles_count}, scc={scc_count}",
            )
        )
        metrics.append(
            QualityMetric(
                name="arch.fan_out_max",
                raw=float(max_fan_out),
                score=fan_out_score,
                status=_threshold_status(fan_out_score),
                detail=f"max_fan_out={max_fan_out}",
            )
        )
        metrics.append(
            QualityMetric(
                name="arch.fan_in_max",
                raw=float(max_fan_in),
                score=fan_in_score,
                status=_threshold_status(fan_in_score),
                detail=f"max_fan_in={max_fan_in}",
            )
        )
        avg_fan_out_score = _clamp01(1 - (avg_fan_out - 2) / 8)
        metrics.append(
            QualityMetric(
                name="arch.fan_out_avg",
                raw=avg_fan_out,
                score=avg_fan_out_score,
                status=_threshold_status(avg_fan_out_score),
                detail=f"avg_fan_out={avg_fan_out:.2f}",
            )
        )
        avg_fan_in_score = _clamp01(1 - (avg_fan_in - 2) / 8)
        metrics.append(
            QualityMetric(
                name="arch.fan_in_avg",
                raw=avg_fan_in,
                score=avg_fan_in_score,
                status=_threshold_status(avg_fan_in_score),
                detail=f"avg_fan_in={avg_fan_in:.2f}",
            )
        )
        concentration_score = _clamp01(1 - degree_concentration)
        metrics.append(
            QualityMetric(
                name="arch.degree_concentration",
                raw=degree_concentration,
                score=concentration_score,
                status=_threshold_status(concentration_score),
                detail=f"gini={degree_concentration:.3f}",
            )
        )
        metrics.append(
            QualityMetric(
                name="arch.bottlenecks",
                raw=float(len(bottlenecks)),
                score=_clamp01(1 - len(bottlenecks) / 3),
                status="WARN" if bottlenecks else "PASS",
                detail=f"top_fan_in={','.join(bottlenecks) if bottlenecks else 'none'}",
            )
        )
        orphan_ratio = len(orphan_components) / max(1, n)
        orphan_score = _clamp01(1 - orphan_ratio)
        metrics.append(
            QualityMetric(
                name="arch.orphan_components",
                raw=float(len(orphan_components)),
                score=orphan_score,
                status=_threshold_status(orphan_score),
                detail=(
                    f"orphans={','.join(orphan_components[:5]) if orphan_components else 'none'}"
                ),
            )
        )
        utility_hub_score = _clamp01(1 - utility_hub_ratio * 2)
        metrics.append(
            QualityMetric(
                name="arch.utility_hub_ratio",
                raw=utility_hub_ratio,
                score=utility_hub_score,
                status=_threshold_status(utility_hub_score),
                detail=f"hubs={','.join(utility_hubs) if utility_hubs else 'none'}",
            )
        )

        # Core composite category: graph health
        metrics.append(
            QualityMetric(
                name="arch.graph_health",
                raw=graph_health,
                score=graph_health,
                status=_threshold_status(graph_health),
                detail=f"density={edge_density:.3f}, cycles={cycles_count}, scc={scc_count}",
            )
        )

        # Core composite category: coupling
        metrics.append(
            QualityMetric(
                name="arch.coupling",
                raw=coupling_score,
                score=coupling_score,
                status=_threshold_status(coupling_score),
                detail=(
                    f"max_fan_out={max_fan_out}, max_fan_in={max_fan_in}, "
                    f"density={edge_density:.3f}, concentration={degree_concentration:.3f}"
                ),
            )
        )

        # Core composite category: completeness
        req_total = coverage.get("requirements_total", 0)
        req_mapped = coverage.get("requirements_mapped", 0)
        mapping_rate = req_mapped / max(1, req_total)
        completeness = mapping_rate if req_total > 0 else 1.0  # Assume complete if no reqs
        metrics.append(
            QualityMetric(
                name="arch.requirement_mapping_rate",
                raw=mapping_rate,
                score=mapping_rate,
                status=_threshold_status(mapping_rate),
                detail=f"mapped={req_mapped}/{req_total}",
            )
        )
        metrics.append(
            QualityMetric(
                name="arch.completeness",
                raw=completeness,
                score=completeness,
                status=_threshold_status(completeness),
                detail=(
                    f"mapped={req_mapped}/{req_total}, "
                    f"unmapped={len(coverage.get('unmapped_requirements', []))}"
                ),
            )
        )

        # Core composite category: L2 finding severity
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

    def _cycle_stats(
        self,
        nodes: list[str],
        edges: list[dict[str, Any]],
    ) -> tuple[bool, int, int]:
        """Return cycle presence, cycle count, and SCC count."""
        sccs = self._strongly_connected_components(nodes, edges)
        cyclic_scc_count = sum(1 for component in sccs if len(component) > 1)
        self_loops = sum(
            1
            for edge in edges
            if str(edge.get("from", "")) and str(edge.get("from", "")) == str(edge.get("to", ""))
        )
        cycles_count = cyclic_scc_count + self_loops
        return cycles_count > 0, cycles_count, len(sccs)

    def _strongly_connected_components(
        self,
        nodes: list[str],
        edges: list[dict[str, Any]],
    ) -> list[list[str]]:
        """Tarjan SCC for directed graph."""
        adjacency: dict[str, list[str]] = {node: [] for node in nodes}
        for edge in edges:
            src = str(edge.get("from", ""))
            dst = str(edge.get("to", ""))
            if not src or not dst:
                continue
            adjacency.setdefault(src, [])
            adjacency.setdefault(dst, [])
            adjacency[src].append(dst)

        index = 0
        index_map: dict[str, int] = {}
        low_link: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        components: list[list[str]] = []

        def strongconnect(node: str) -> None:
            nonlocal index
            index_map[node] = index
            low_link[node] = index
            index += 1
            stack.append(node)
            on_stack.add(node)

            for neighbor in adjacency.get(node, []):
                if neighbor not in index_map:
                    strongconnect(neighbor)
                    low_link[node] = min(low_link[node], low_link[neighbor])
                elif neighbor in on_stack:
                    low_link[node] = min(low_link[node], index_map[neighbor])

            if low_link[node] == index_map[node]:
                component: list[str] = []
                while stack:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                components.append(component)

        for node in adjacency:
            if node not in index_map:
                strongconnect(node)

        return components

    @staticmethod
    def _gini(values: list[int]) -> float:
        """Compute Gini coefficient for non-negative integer values."""
        if not values:
            return 0.0
        total = sum(values)
        if total <= 0:
            return 0.0
        n = len(values)
        abs_diff_sum = 0
        for left in values:
            for right in values:
                abs_diff_sum += abs(left - right)
        return abs_diff_sum / (2 * n * n * (total / n))


class CodeQualityScorer:
    """Compute mechanical code metrics from digest."""

    def compute(
        self,
        digest: dict[str, Any],
        *,
        refactor_churn: float | None = None,
    ) -> list[QualityMetric]:
        """Compute mechanical code metrics.

        Returns list of QualityMetric for:
        - code.issue_density
        - code.file_size_outliers
        - code.churn
        - code.duplication_ratio
        """
        codebase = digest.get("codebase", {})
        files = codebase.get("files", [])
        totals = codebase.get("totals", {})
        codebase_metrics = codebase.get("metrics", {})
        l3_findings = digest.get("l3_review", {}).get("final_findings", {})

        total_loc = totals.get("loc", 0)
        total_files = totals.get("files", len(files))
        metrics: list[QualityMetric] = []

        metrics.append(
            QualityMetric(
                name="code.loc_total",
                raw=float(total_loc),
                score=1.0,
                status="PASS",
                detail=f"loc={total_loc}",
            )
        )
        metrics.append(
            QualityMetric(
                name="code.files_total",
                raw=float(total_files),
                score=1.0,
                status="PASS",
                detail=f"files={total_files}",
            )
        )

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

        churn_raw = float(refactor_churn) if isinstance(refactor_churn, int | float) else 0.0
        churn_score = _clamp01(1 - churn_raw)
        metrics.append(
            QualityMetric(
                name="code.churn",
                raw=churn_raw,
                score=churn_score,
                status=_threshold_status(churn_score),
                detail=f"l3.refactor_churn={churn_raw:.3f}",
            )
        )

        duplication_ratio = (
            float(codebase_metrics.get("duplication_ratio", 0.0))
            if isinstance(codebase_metrics, dict)
            else 0.0
        )
        duplication_ratio = _clamp01(duplication_ratio)
        duplication_score = _clamp01(1 - duplication_ratio)
        metrics.append(
            QualityMetric(
                name="code.duplication_ratio",
                raw=duplication_ratio,
                score=duplication_score,
                status=_threshold_status(duplication_score),
                detail=f"duplication_ratio={duplication_ratio:.3f}",
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
            + 0.20 * by_name.get("code.duplication_ratio", 0.0)
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
        missing = judge_output.get("missing_requirements", [])
        hallucinated = judge_output.get("hallucinated_features", [])

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
        pipeline_scorecard: Any | None = None,
        planner_scorecard: Any | None = None,
        pipeline_efficiency: float | None = None,
        planner_quality: float | None = None,
    ) -> QualityScorecard:
        """Compute quality scorecard.

        Args:
            arch_digest: Architecture digest.
            code_digest: Code digest.
            arch_judge_output: Optional ArchJudgeOutput dict.
            code_judge_output: Optional CodeJudgeOutput dict.
            spec_judge_output: Optional SpecFidelityOutput dict.
            pipeline_scorecard: Optional RunReporter scorecard object/dict.
            planner_scorecard: Optional PlannerReporter scorecard object/dict.
            pipeline_efficiency: Optional precomputed pipeline efficiency score [0,1].
            planner_quality: Optional precomputed planner quality score [0,1].

        Returns:
            QualityScorecard with all metrics.
        """
        # Architecture
        arch_scorer = ArchitectureQualityScorer()
        arch_metrics = arch_scorer.compute(arch_digest)
        arch_mechanical = arch_scorer.mechanical_score(arch_metrics)

        arch_judge_score: float | None = None
        architecture_judge_dimensions: list[str] = []
        architecture_risks: list[dict[str, Any] | str] = []
        if arch_judge_output:
            overall = arch_judge_output.get("overall", 3)
            arch_judge_score = (overall - 1) / 4
            scores = arch_judge_output.get("scores", {})
            if isinstance(scores, dict):
                for name in sorted(scores):
                    architecture_judge_dimensions.append(f"{name}={scores[name]}")
            risks = arch_judge_output.get("risks", [])
            if isinstance(risks, list):
                architecture_risks = [risk for risk in risks if risk]

        if arch_judge_score is None:
            arch_quality = arch_mechanical
        else:
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
        if arch_judge_score is None and arch_status == "PASS":
            arch_status = "WARN"

        judge_detail = "missing" if arch_judge_score is None else f"{arch_judge_score:.3f}"
        arch_metrics.append(
            QualityMetric(
                name="arch.quality_score",
                raw=arch_quality,
                score=arch_quality,
                status=arch_status,
                detail=f"mechanical={arch_mechanical:.3f}, judge={judge_detail}",
            )
        )

        # Code
        code_scorer = CodeQualityScorer()
        refactor_churn = _metric_raw_by_name(
            _field(pipeline_scorecard, "soft_signals"),
            "l3.refactor_churn",
        )
        code_metrics = code_scorer.compute(code_digest, refactor_churn=refactor_churn)
        code_mechanical = code_scorer.mechanical_score(code_metrics)

        code_judge_score: float | None = None
        code_sampled_files: list[dict[str, Any]] = []
        code_risks: list[dict[str, Any] | str] = []
        if code_judge_output:
            overall = code_judge_output.get("overall", 3)
            code_judge_score = (overall - 1) / 4
            sampled_entries = code_judge_output.get("files", [])
            if isinstance(sampled_entries, list):
                by_path = {
                    str(file_data.get("path", "")): int(file_data.get("loc", 0) or 0)
                    for file_data in code_digest.get("codebase", {}).get("files", [])
                    if isinstance(file_data, dict)
                }
                for entry in sampled_entries:
                    if not isinstance(entry, dict):
                        continue
                    path = str(entry.get("path", ""))
                    notes = entry.get("notes", [])
                    note = ""
                    if isinstance(notes, list):
                        note = "; ".join(str(item) for item in notes if item)
                    code_sampled_files.append(
                        {
                            "path": path,
                            "loc": by_path.get(path, 0),
                            "overall": entry.get("overall", 0),
                            "note": note,
                        }
                    )
            risks = code_judge_output.get("systemic_risks", [])
            if isinstance(risks, list):
                code_risks = [risk for risk in risks if risk]

        if code_judge_score is None:
            code_quality = code_mechanical
        else:
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
        if code_judge_score is None and code_status == "PASS":
            code_status = "WARN"
        code_judge_detail = "missing" if code_judge_score is None else f"{code_judge_score:.3f}"
        code_metrics.append(
            QualityMetric(
                name="code.quality_score",
                raw=code_quality,
                score=code_quality,
                status=code_status,
                detail=f"mechanical={code_mechanical:.3f}, judge={code_judge_detail}",
            )
        )

        # Spec fidelity
        spec_scorer = SpecFidelityScorer()
        spec_metrics = spec_scorer.compute(spec_judge_output)
        spec_fidelity_score = spec_metrics[0].score if spec_metrics else 0.0
        spec_missing_items: list[str] = []
        if spec_judge_output:
            missing = spec_judge_output.get("missing_requirements", [])
            if isinstance(missing, list):
                spec_missing_items = [str(item) for item in missing if item]

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
        if pipeline_efficiency is None:
            pipeline_efficiency = self._pipeline_efficiency_from_scorecard(pipeline_scorecard)

        if planner_quality is None:
            planner_quality = self._planner_quality_from_scorecard(planner_scorecard)

        composite_inputs: list[tuple[float, float]] = [
            (quality_overall, 0.45),
            (spec_fidelity_for_composite, 0.20),
        ]
        missing_composite_inputs: list[str] = []

        if pipeline_efficiency is None:
            missing_composite_inputs.append("pipeline_efficiency")
        else:
            composite_inputs.append((_clamp01(float(pipeline_efficiency)), 0.20))

        if planner_quality is None:
            missing_composite_inputs.append("planner_quality")
        else:
            composite_inputs.append((_clamp01(float(planner_quality)), 0.15))

        total_weight = sum(weight for _, weight in composite_inputs)
        if total_weight > 0:
            composite_score = (
                sum(value * weight for value, weight in composite_inputs) / total_weight
            )
        else:
            composite_score = 0.0
        composite_status = _threshold_status(composite_score)
        if missing_composite_inputs and composite_status == "PASS":
            composite_status = "WARN"
        if missing_composite_inputs and overall_status == "PASS":
            overall_status = "WARN"

        summary_parts = [
            f"arch={arch_quality:.2f}({arch_status})",
            f"code={code_quality:.2f}({code_status})",
            f"spec={spec_fidelity_score:.2f}",
            f"composite={composite_score:.2f}({composite_status})",
        ]
        if missing_composite_inputs:
            summary_parts.append(f"missing_inputs={','.join(sorted(missing_composite_inputs))}")

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
            architecture_judge_dimensions=architecture_judge_dimensions,
            architecture_risks=architecture_risks,
            code_sampled_files=code_sampled_files,
            code_risks=code_risks,
            spec_missing_items=spec_missing_items,
        )

    def _pipeline_efficiency_from_scorecard(self, scorecard: Any | None) -> float | None:
        """Derive pipeline efficiency from RunReporter soft signals."""
        soft_signals = _field(scorecard, "soft_signals")
        scores = _metric_scores(soft_signals)
        if scores:
            return sum(scores) / len(scores)
        return None

    def _planner_quality_from_scorecard(self, scorecard: Any | None) -> float | None:
        """Derive planner quality from planner scorecard metrics."""
        soft_signals = _field(scorecard, "soft_signals")
        hard_gates = _field(scorecard, "hard_gates")
        soft_scores = _metric_scores(soft_signals)
        hard_scores = _metric_scores(hard_gates)

        if soft_scores and hard_scores:
            return (sum(soft_scores) + sum(hard_scores)) / (len(soft_scores) + len(hard_scores))
        if soft_scores:
            return sum(soft_scores) / len(soft_scores)
        if hard_scores:
            return sum(hard_scores) / len(hard_scores)

        overall_pass = _field(scorecard, "overall_pass")
        if isinstance(overall_pass, bool):
            return 1.0 if overall_pass else 0.0
        return None

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


def _field(obj: Any, key: str) -> Any:
    """Read key from dict-like or attribute-like objects."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _metric_scores(metrics: Any) -> list[float]:
    """Extract normalized metric scores from metric dicts/objects."""
    if not isinstance(metrics, list):
        return []
    scores: list[float] = []
    for metric in metrics:
        raw = _field(metric, "score")
        if isinstance(raw, int | float):
            scores.append(_clamp01(float(raw)))
    return scores


def _metric_raw_by_name(metrics: Any, metric_name: str) -> float | None:
    """Return the raw value for a named metric from list payloads."""
    if not isinstance(metrics, list):
        return None
    for metric in metrics:
        name = _field(metric, "name")
        if name != metric_name:
            continue
        raw = _field(metric, "raw")
        if isinstance(raw, int | float):
            return float(raw)
        return None
    return None
