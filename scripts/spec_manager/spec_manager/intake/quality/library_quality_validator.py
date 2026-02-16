"""Library quality validator for Phase 0 outputs.

Validates that the libraries produced by Phase 0 meet quality thresholds
before the PromotionLoop begins. Five dimensions are scored 0-100:

1. **Completeness** (hard gate) — all source lines routed or marked noise.
2. **Routing overlap** (hard gate) — no source line in multiple libraries.
3. **Semantic overlap** (LLM judge) — libraries don't duplicate concerns.
4. **Concern isolation** (LLM judge) — each library has a single purpose.
5. **Dependency minimality** (advisory) — no god-library pattern.

Dimensions 1-4 are gates (fail = block promotion).
Dimension 5 is advisory (warn-only, can be promoted to gate later).
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

import yaml

from spec_manager.core.agent_utils import run_agent
from spec_manager.core.json_extraction import _extract_json_payload

logger = logging.getLogger(__name__)

_ELEMENT_MARKER_RE = re.compile(r"\(\[=([A-Za-z0-9_-]+)\]\)")


@dataclass
class DimensionScore:
    """Score for a single quality dimension."""

    name: str
    score: float  # 0-100
    passed: bool
    mode: str = "gate"  # "gate" or "advisory"
    details: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


@dataclass
class LibraryQualityReport:
    """Full quality report for a set of libraries."""

    dimensions: list[DimensionScore] = field(default_factory=list)
    overall_passed: bool = True
    library_count: int = 0
    source_line_count: int = 0
    issues: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)

    @property
    def gate_passed(self) -> bool:
        """True if all gate dimensions pass."""
        return all(d.passed for d in self.dimensions if d.mode == "gate")

    @property
    def failed_gate_dimensions(self) -> list[str]:
        """Gate dimensions that did not pass."""
        return [d.name for d in self.dimensions if d.mode == "gate" and not d.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimensions": [
                {
                    "name": d.name,
                    "score": d.score,
                    "passed": d.passed,
                    "mode": d.mode,
                    "details": d.details,
                    "issues": d.issues,
                }
                for d in self.dimensions
            ],
            "overall_passed": self.overall_passed,
            "gate_passed": self.gate_passed,
            "failed_gate_dimensions": self.failed_gate_dimensions,
            "library_count": self.library_count,
            "source_line_count": self.source_line_count,
            "issues": self.issues,
            "artifacts": self.artifacts,
        }


class LibraryQualityValidator:
    """Validates Phase 0 library outputs against quality rubric.

    Args:
        workspace_root: Path to workspace containing Phase 0 outputs.
        overlap_threshold: Maximum acceptable routing overlap ratio (default 0.01).
        semantic_overlap_threshold: Maximum acceptable semantic overlap (default 0.75).
        cohesion_threshold: Minimum acceptable cohesion score (default 0.5).
        god_library_out_degree_threshold: Warn if out-degree exceeds this threshold.
    """

    def __init__(
        self,
        workspace_root: Path,
        *,
        overlap_threshold: float = 0.01,
        semantic_overlap_threshold: float = 0.75,
        cohesion_threshold: float = 0.5,
        god_library_out_degree_threshold: int = 3,
        semantic_judge_agent: str = "spec-intake-library-semantic-overlap-judge",
        isolation_judge_agent: str = "spec-intake-library-concern-isolation-judge",
        dependency_judge_agent: str = "spec-intake-library-dependency-judge",
    ) -> None:
        self._workspace = workspace_root
        self._overlap_threshold = overlap_threshold
        self._semantic_overlap_threshold = semantic_overlap_threshold
        self._cohesion_threshold = cohesion_threshold
        self._god_library_out_degree_threshold = god_library_out_degree_threshold
        self._semantic_judge_agent = semantic_judge_agent
        self._isolation_judge_agent = isolation_judge_agent
        self._dependency_judge_agent = dependency_judge_agent

    def validate(self, phase0_output_dir: Path | None = None) -> LibraryQualityReport:
        """Run all quality checks on Phase 0 output and persist report artifacts."""
        output_dir = phase0_output_dir or (self._workspace / "phase0_output")
        report = LibraryQualityReport()

        # Load Phase 0 artifacts
        route_table = self._load_route_table(output_dir)
        coverage_ledger = self._load_coverage_ledger(output_dir)
        catalog = self._load_library_catalog(output_dir)
        libraries = self._load_library_artifacts(output_dir, catalog)

        report.library_count = len(libraries)
        report.source_line_count = self._estimate_source_line_count(route_table, coverage_ledger)

        # 1. Completeness
        completeness = self._check_completeness(route_table, coverage_ledger, libraries)
        report.dimensions.append(completeness)

        # 2. Routing overlap
        overlap = self._check_routing_overlap(route_table)
        report.dimensions.append(overlap)

        # 3. Semantic overlap (LLM judge)
        semantic = self._check_semantic_overlap(libraries, output_dir)
        report.dimensions.append(semantic)

        # 4. Concern isolation (LLM judge)
        isolation = self._check_concern_isolation(libraries, output_dir)
        report.dimensions.append(isolation)

        # 5. Dependency minimality (advisory)
        dep_min = self._check_dependency_minimality(libraries, output_dir)
        report.dimensions.append(dep_min)

        report.overall_passed = report.gate_passed
        report.issues = [
            {
                "dimension": d.name,
                "mode": d.mode,
                "message": issue,
                "details": d.details,
            }
            for d in report.dimensions
            for issue in d.issues
        ]

        remediation_plan = self._build_remediation_plan(report)
        report.artifacts = self._write_artifacts(
            output_dir,
            report=report,
            remediation_plan=remediation_plan,
        )
        return report

    def _check_completeness(
        self,
        route_table: list[dict[str, Any]],
        coverage_ledger: list[dict[str, Any]],
        libraries: list[dict[str, Any]],
    ) -> DimensionScore:
        """Check that all source lines are routed or marked noise and assembled."""
        issues: list[str] = []
        if not route_table:
            issues.append("route_table.jsonl is missing or empty.")
        if not coverage_ledger:
            issues.append("coverage_ledger.jsonl is missing or empty.")
        if not libraries:
            issues.append("No assembled libraries found under phase0_output/libraries/.")

        total_files = 0
        incomplete_files = 0
        unresolved_lines = 0

        for entry in coverage_ledger:
            total_files += 1
            status = str(entry.get("status", "")).strip()
            if status != "fully_routed":
                incomplete_files += 1

            exceptions = entry.get("exceptions", [])
            if not isinstance(exceptions, list):
                continue
            for exception in exceptions:
                if not isinstance(exception, dict):
                    continue
                if str(exception.get("status", "")).strip() != "uncovered":
                    continue
                exc_start = int(exception.get("start", 0) or 0)
                exc_end = int(exception.get("end", 0) or 0)
                if exc_start > 0 and exc_end >= exc_start:
                    unresolved_lines += exc_end - exc_start + 1

        routed_element_ids = self._collect_routed_element_ids(route_table)
        assembled_element_ids = self._collect_assembled_element_ids(libraries)
        missing_elements = sorted(routed_element_ids - assembled_element_ids)

        if total_files == 0:
            issues.append("Coverage ledger did not contain any file records.")
        if incomplete_files > 0:
            issues.append(f"{incomplete_files} file(s) are not fully routed.")
        if unresolved_lines > 0:
            issues.append(f"{unresolved_lines} source line(s) remain uncovered.")
        if missing_elements:
            issues.append(
                f"{len(missing_elements)} routed element(s) missing from assembled output."
            )

        passed = not issues
        return DimensionScore(
            name="completeness",
            score=100.0 if passed else 0.0,
            passed=passed,
            details={
                "coverage_files": total_files,
                "incomplete_files": incomplete_files,
                "unresolved_lines": unresolved_lines,
                "routed_elements": len(routed_element_ids),
                "assembled_elements": len(assembled_element_ids),
                "missing_routed_elements": missing_elements[:100],
            },
            issues=issues,
        )

    def _check_routing_overlap(self, route_table: list[dict[str, Any]]) -> DimensionScore:
        """Check for source lines routed to multiple libraries."""
        if not route_table:
            return DimensionScore(
                name="routing_overlap",
                score=0.0,
                passed=False,
                details={"overlap_count": 0, "overlap_ratio": 1.0},
                issues=["route_table.jsonl is missing or empty; cannot verify overlap."],
            )

        line_libs: dict[str, set[str]] = {}
        for entry in route_table:
            src = entry.get("src", {})
            dest = entry.get("dest", {})
            if not isinstance(src, dict) or not isinstance(dest, dict):
                continue
            file_path = str(src.get("file", "")).strip()
            start = int(src.get("start", 0) or 0)
            end = int(src.get("end", 0) or 0)
            lib_id = str(dest.get("library", "")).strip()
            bucket = str(dest.get("bucket", "")).strip()
            if not file_path or not lib_id or not bucket or bucket == "IGNORED":
                continue
            if start <= 0 or end < start:
                continue
            for line_num in range(start, end + 1):
                line_key = f"{file_path}:{line_num}"
                line_libs.setdefault(line_key, set()).add(lib_id)

        total_lines = len(line_libs)
        if total_lines == 0:
            return DimensionScore(
                name="routing_overlap",
                score=100.0,
                passed=True,
                details={"overlap_count": 0, "overlap_ratio": 0.0, "total_lines": 0},
            )

        overlapping_lines = [line for line, libs in line_libs.items() if len(libs) > 1]
        overlap_count = len(overlapping_lines)
        overlap_ratio = overlap_count / total_lines

        score = max(0.0, 100.0 * (1 - overlap_ratio / 0.02))
        passed = overlap_ratio <= self._overlap_threshold

        issues: list[str] = []
        if not passed:
            issues.append(
                "Overlap ratio "
                f"{overlap_ratio:.2%} exceeds threshold "
                f"{self._overlap_threshold:.2%}."
            )

        return DimensionScore(
            name="routing_overlap",
            score=score,
            passed=passed,
            details={
                "overlap_count": overlap_count,
                "overlap_ratio": overlap_ratio,
                "total_lines": total_lines,
                "sample_overlapping_lines": overlapping_lines[:50],
            },
            issues=issues,
        )

    def _check_semantic_overlap(
        self,
        libraries: list[dict[str, Any]],
        output_dir: Path,
    ) -> DimensionScore:
        """Check pairwise semantic overlap using an LLM judge."""
        if len(libraries) < 2:
            return DimensionScore(name="semantic_overlap", score=100.0, passed=True)

        try:
            pair_results: list[dict[str, Any]] = []
            max_overlap = 0.0
            issues: list[str] = []

            for lib_a, lib_b in combinations(libraries, 2):
                judgment = self._judge_semantic_pair(output_dir, lib_a, lib_b)
                overlap_score = self._clamp01(judgment.get("overlap_score", 0.0))
                relationship = str(judgment.get("relationship", "distinct")).strip().lower()
                rationale = str(judgment.get("rationale", "")).strip()
                max_overlap = max(max_overlap, overlap_score)

                pair_result = {
                    "library_a": lib_a["lib_id"],
                    "library_b": lib_b["lib_id"],
                    "overlap_score": overlap_score,
                    "relationship": relationship,
                    "rationale": rationale,
                }
                pair_results.append(pair_result)

                exempt_relationships = {
                    "crosscutting intentional",
                    "crosscutting_intentional",
                }
                if (
                    overlap_score > self._semantic_overlap_threshold
                    and relationship not in exempt_relationships
                ):
                    issues.append(
                        "Library pair "
                        f"{lib_a['lib_id']}<->{lib_b['lib_id']} overlap_score={overlap_score:.2f} "
                        f"relationship={relationship!r} exceeds threshold "
                        f"{self._semantic_overlap_threshold:.2f}."
                    )

            score = max(0.0, 100.0 * (1 - max_overlap))
            return DimensionScore(
                name="semantic_overlap",
                score=score,
                passed=not issues,
                details={
                    "max_pair_overlap_score": max_overlap,
                    "pair_results": pair_results,
                    "threshold": self._semantic_overlap_threshold,
                    "judge_agent": self._semantic_judge_agent,
                },
                issues=issues,
            )
        except Exception as exc:
            return DimensionScore(
                name="semantic_overlap",
                score=0.0,
                passed=False,
                details={
                    "error": str(exc),
                    "judge_agent": self._semantic_judge_agent,
                },
                issues=[f"Semantic overlap judge failed: {exc}"],
            )

    def _check_concern_isolation(
        self,
        libraries: list[dict[str, Any]],
        output_dir: Path,
    ) -> DimensionScore:
        """Check per-library concern isolation using an LLM judge."""
        if not libraries:
            return DimensionScore(name="concern_isolation", score=0.0, passed=False)

        try:
            per_library: list[dict[str, Any]] = []
            cohesion_scores: list[float] = []
            issues: list[str] = []

            for library in libraries:
                judgment = self._judge_concern_isolation(output_dir, library)
                cohesion = self._clamp01(judgment.get("cohesion_score", 0.0))
                top_concerns = self._normalize_string_list(judgment.get("top_concerns", []))
                mixed_concerns = self._normalize_string_list(judgment.get("mixed_concerns", []))
                rationale = str(judgment.get("rationale", "")).strip()

                cohesion_scores.append(cohesion)
                per_library.append(
                    {
                        "library": library["lib_id"],
                        "cohesion_score": cohesion,
                        "top_concerns": top_concerns,
                        "mixed_concerns": mixed_concerns,
                        "rationale": rationale,
                    }
                )

                if cohesion < self._cohesion_threshold:
                    issues.append(
                        f"Library {library['lib_id']} cohesion_score={cohesion:.2f} "
                        f"below threshold {self._cohesion_threshold:.2f}."
                    )

            avg_cohesion = sum(cohesion_scores) / len(cohesion_scores) if cohesion_scores else 0.0
            return DimensionScore(
                name="concern_isolation",
                score=avg_cohesion * 100.0,
                passed=not issues,
                details={
                    "avg_cohesion": avg_cohesion,
                    "per_library": per_library,
                    "threshold": self._cohesion_threshold,
                    "judge_agent": self._isolation_judge_agent,
                },
                issues=issues,
            )
        except Exception as exc:
            return DimensionScore(
                name="concern_isolation",
                score=0.0,
                passed=False,
                details={
                    "error": str(exc),
                    "judge_agent": self._isolation_judge_agent,
                },
                issues=[f"Concern isolation judge failed: {exc}"],
            )

    def _check_dependency_minimality(
        self,
        libraries: list[dict[str, Any]],
        output_dir: Path,
    ) -> DimensionScore:
        """Check dependency minimality from LLM-inferred edges (advisory)."""
        if not libraries:
            return DimensionScore(
                name="dependency_minimality",
                score=100.0,
                passed=True,
                mode="advisory",
                details={"library_dependency_edges": []},
            )

        try:
            raw_edges = self._judge_dependency_edges(output_dir, libraries)
        except Exception as exc:
            return DimensionScore(
                name="dependency_minimality",
                score=0.0,
                passed=True,
                mode="advisory",
                details={
                    "error": str(exc),
                    "judge_agent": self._dependency_judge_agent,
                    "library_dependency_edges": [],
                },
                issues=[f"Dependency minimality judge unavailable: {exc}"],
            )

        library_ids = {lib["lib_id"] for lib in libraries}
        edges: list[dict[str, Any]] = []
        out_degree: dict[str, int] = {lib_id: 0 for lib_id in library_ids}

        for edge in raw_edges:
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            reason = str(edge.get("reason", "")).strip()
            if not source or not target or source == target:
                continue
            if source not in library_ids or target not in library_ids:
                continue
            edges.append({"source": source, "target": target, "reason": reason})
            out_degree[source] = out_degree.get(source, 0) + 1

        avg_out_degree = sum(out_degree.values()) / len(out_degree) if out_degree else 0.0
        max_out_degree = max(out_degree.values()) if out_degree else 0

        score = max(0.0, min(100.0, 100.0 - 10.0 * avg_out_degree))
        god_libraries = [
            lib_id
            for lib_id, degree in sorted(out_degree.items())
            if degree > self._god_library_out_degree_threshold
        ]

        issues: list[str] = []
        if god_libraries:
            issues.append(
                "Potential god libraries detected: "
                f"{', '.join(god_libraries)} (out-degree threshold "
                f"> {self._god_library_out_degree_threshold})."
            )

        return DimensionScore(
            name="dependency_minimality",
            score=score,
            passed=True,  # advisory only
            mode="advisory",
            details={
                "library_dependency_edges": edges,
                "avg_out_degree": avg_out_degree,
                "max_out_degree": max_out_degree,
                "out_degree": out_degree,
                "god_library_threshold": self._god_library_out_degree_threshold,
                "god_libraries": god_libraries,
                "judge_agent": self._dependency_judge_agent,
            },
            issues=issues,
        )

    # ------------------------------------------------------------------
    # LLM judge calls
    # ------------------------------------------------------------------

    def _judge_semantic_pair(
        self,
        output_dir: Path,
        lib_a: dict[str, Any],
        lib_b: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = (
            "## TASK\n"
            "Evaluate semantic overlap between two libraries.\n\n"
            "Return ONLY JSON with this schema:\n"
            "{"
            '"overlap_score": 0.0, '
            '"relationship": '
            '"distinct|subset|redundant|crosscutting intentional", '
            '"rationale": "..."'
            "}\n\n"
            "Rules:\n"
            "- overlap_score is in [0,1]\n"
            "- relationship must match the allowed set\n"
            "- Use 'crosscutting intentional' only when overlap is deliberate and healthy\n\n"
            f"## Library A\n{self._render_library_for_prompt(lib_a)}\n\n"
            f"## Library B\n{self._render_library_for_prompt(lib_b)}\n"
        )
        data = self._run_json_agent(
            agent_name=self._semantic_judge_agent,
            prompt=prompt,
            workspace=output_dir,
        )
        if not isinstance(data, dict):
            raise TypeError("Semantic judge output must be a JSON object.")
        return data

    def _judge_concern_isolation(
        self,
        output_dir: Path,
        library: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = (
            "## TASK\n"
            "Evaluate concern isolation for one library.\n\n"
            "Return ONLY JSON with this schema:\n"
            "{"
            '"cohesion_score": 0.0, '
            '"top_concerns": ["..."], '
            '"mixed_concerns": ["..."], '
            '"rationale": "..."'
            "}\n\n"
            "Rules:\n"
            "- cohesion_score is in [0,1]\n"
            "- top_concerns should list the library's primary coherent themes\n"
            "- mixed_concerns should list concerns that appear out of scope\n\n"
            f"## Library\n{self._render_library_for_prompt(library)}\n"
        )
        data = self._run_json_agent(
            agent_name=self._isolation_judge_agent,
            prompt=prompt,
            workspace=output_dir,
        )
        if not isinstance(data, dict):
            raise TypeError("Concern isolation judge output must be a JSON object.")
        return data

    def _judge_dependency_edges(
        self,
        output_dir: Path,
        libraries: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        library_blocks = "\n\n".join(self._render_library_for_prompt(lib) for lib in libraries)
        prompt = (
            "## TASK\n"
            "Infer dependency edges between libraries.\n\n"
            "Return ONLY JSON with this schema:\n"
            "{"
            '"library_dependency_edges": ['
            '{"source": "LIB-0001", "target": "LIB-0002", "reason": "..."}'
            "]"
            "}\n\n"
            "Rules:\n"
            "- Include only direct dependencies where source relies on target\n"
            "- Omit self edges\n"
            "- Use exact library ids from the input\n\n"
            f"## Libraries\n{library_blocks}\n"
        )
        data = self._run_json_agent(
            agent_name=self._dependency_judge_agent,
            prompt=prompt,
            workspace=output_dir,
        )
        if not isinstance(data, dict):
            raise TypeError("Dependency judge output must be a JSON object.")
        edges = data.get("library_dependency_edges", [])
        if not isinstance(edges, list):
            raise TypeError(
                "Dependency judge output missing list field 'library_dependency_edges'."
            )
        return edges

    @staticmethod
    def _run_json_agent(
        *,
        agent_name: str,
        prompt: str,
        workspace: Path,
        max_attempts: int = 3,
    ) -> dict[str, Any] | list[Any]:
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            raw_output = run_agent(
                agent_name=agent_name,
                prompt=prompt,
                workspace=workspace,
            )
            try:
                extracted = _extract_json_payload(raw_output)
                parsed = json.loads(extracted)
                if isinstance(parsed, (dict, list)):
                    return parsed
                raise ValueError("Judge output must be a JSON object or list.")
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "JSON parse attempt %d/%d failed for agent %s: %s",
                    attempt,
                    max_attempts,
                    agent_name,
                    exc,
                )
        raise ValueError(f"Failed to parse JSON from agent {agent_name}: {last_error}")

    # ------------------------------------------------------------------
    # Artifact persistence
    # ------------------------------------------------------------------

    def _write_artifacts(
        self,
        output_dir: Path,
        *,
        report: LibraryQualityReport,
        remediation_plan: dict[str, Any],
    ) -> dict[str, str]:
        json_path = output_dir / "library_quality.report.json"
        md_path = output_dir / "library_quality.report.md"
        issues_path = output_dir / "library_quality.issues.jsonl"

        json_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        issues_rows = report.issues
        with issues_path.open("w", encoding="utf-8") as handle:
            for row in issues_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

        md_path.write_text(self._render_markdown_report(report), encoding="utf-8")

        artifacts = {
            "report_json": str(json_path),
            "report_md": str(md_path),
            "issues_jsonl": str(issues_path),
        }

        if remediation_plan.get("required", False):
            remediation_path = output_dir / "library_quality.remediation_plan.json"
            remediation_path.write_text(
                json.dumps(remediation_plan, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            artifacts["remediation_plan_json"] = str(remediation_path)

        return artifacts

    @staticmethod
    def _render_markdown_report(report: LibraryQualityReport) -> str:
        lines = [
            "# Library Quality Report",
            "",
            f"- Overall passed: **{report.overall_passed}**",
            f"- Gate passed: **{report.gate_passed}**",
            f"- Libraries: **{report.library_count}**",
            f"- Source lines: **{report.source_line_count}**",
            "",
            "## Dimension Scores",
            "",
            "| Dimension | Mode | Score | Passed |",
            "| --- | --- | ---: | :---: |",
        ]
        for dim in report.dimensions:
            lines.append(
                f"| {dim.name} | {dim.mode} | {dim.score:.2f} | {'yes' if dim.passed else 'no'} |"
            )

        lines.extend(["", "## Top Issues", ""])
        if not report.issues:
            lines.append("No issues detected.")
            return "\n".join(lines)

        for issue in report.issues[:20]:
            lines.append(f"- [{issue['dimension']}] {issue['message']}")

        return "\n".join(lines)

    @staticmethod
    def _build_remediation_plan(report: LibraryQualityReport) -> dict[str, Any]:
        failed = report.failed_gate_dimensions
        actions: list[dict[str, Any]] = []

        for dimension in failed:
            if dimension == "completeness":
                actions.append(
                    {
                        "dimension": dimension,
                        "action": "reroute_and_reassemble",
                        "description": (
                            "Repair uncovered spans and missing assembled elements, "
                            "then rerun Phase 0 steps 3-5."
                        ),
                    }
                )
            elif dimension == "routing_overlap":
                actions.append(
                    {
                        "dimension": dimension,
                        "action": "split_or_reassign_overlaps",
                        "description": (
                            "Resolve duplicate routing lines by splitting or "
                            "reassigning overlapping boundaries."
                        ),
                    }
                )
            elif dimension == "semantic_overlap":
                actions.append(
                    {
                        "dimension": dimension,
                        "action": "split_merge_or_crosscut",
                        "description": (
                            "Re-evaluate semantic boundary conflicts and apply "
                            "split/merge/crosscutting decisions."
                        ),
                    }
                )
            elif dimension == "concern_isolation":
                actions.append(
                    {
                        "dimension": dimension,
                        "action": "split_mixed_library",
                        "description": (
                            "Split mixed libraries into cohesive responsibilities "
                            "and reroute affected spans."
                        ),
                    }
                )

        return {
            "required": bool(failed),
            "failed_gate_dimensions": failed,
            "actions": actions,
        }

    # ------------------------------------------------------------------
    # Artifact loading
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_source_line_count(
        route_table: list[dict[str, Any]],
        coverage_ledger: list[dict[str, Any]],
    ) -> int:
        """Estimate source-line volume from coverage records or route spans."""
        if not coverage_ledger:
            covered_lines: set[str] = set()
            for entry in route_table:
                src = entry.get("src", {})
                if not isinstance(src, dict):
                    continue
                file_path = str(src.get("file", "")).strip()
                start = int(src.get("start", 0) or 0)
                end = int(src.get("end", 0) or 0)
                if not file_path or start <= 0 or end < start:
                    continue
                for line_num in range(start, end + 1):
                    covered_lines.add(f"{file_path}:{line_num}")
            return len(covered_lines)

        total = 0
        for entry in coverage_ledger:
            start = int(entry.get("start", 0) or 0)
            end = int(entry.get("end", 0) or 0)
            if start > 0 and end >= start:
                total += end - start + 1
        return total

    @staticmethod
    def _load_route_table(output_dir: Path) -> list[dict[str, Any]]:
        """Load route_table.jsonl from Phase 0 output."""
        path = output_dir / "route_table.jsonl"
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                with contextlib.suppress(json.JSONDecodeError):
                    entries.append(json.loads(line))
        return entries

    @staticmethod
    def _load_coverage_ledger(output_dir: Path) -> list[dict[str, Any]]:
        """Load coverage_ledger.jsonl from Phase 0 output."""
        path = output_dir / "coverage_ledger.jsonl"
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                with contextlib.suppress(json.JSONDecodeError):
                    entries.append(json.loads(line))
        return entries

    @staticmethod
    def _load_library_catalog(output_dir: Path) -> list[dict[str, Any]]:
        """Load libraries.yaml from Phase 0 output."""
        path = output_dir / "libraries.yaml"
        if not path.exists():
            return []
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, OSError):
            return []

        if isinstance(data, dict):
            libraries = data.get("libraries", [])
            return [entry for entry in libraries if isinstance(entry, dict)]
        if isinstance(data, list):
            return [entry for entry in data if isinstance(entry, dict)]
        return []

    @staticmethod
    def _load_library_artifacts(
        output_dir: Path,
        catalog: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Load assembled per-library content used by LLM quality judges."""
        libraries_dir = output_dir / "libraries"
        catalog_by_id = {
            str(entry.get("lib_id", "")).strip(): entry
            for entry in catalog
            if str(entry.get("lib_id", "")).strip()
        }

        library_ids: set[str] = set(catalog_by_id.keys())
        if libraries_dir.exists():
            library_ids.update(path.name for path in libraries_dir.iterdir() if path.is_dir())

        artifacts: list[dict[str, Any]] = []
        for lib_id in sorted(library_ids):
            meta = catalog_by_id.get(lib_id, {})
            lib_dir = libraries_dir / lib_id

            analysis = ""
            constraints = ""
            details: dict[str, str] = {}
            if lib_dir.exists():
                analysis_path = lib_dir / "analysis.md"
                constraints_path = lib_dir / "constraints.md"
                if analysis_path.exists():
                    analysis = analysis_path.read_text(encoding="utf-8")
                if constraints_path.exists():
                    constraints = constraints_path.read_text(encoding="utf-8")

                details_dir = lib_dir / "details"
                if details_dir.exists() and details_dir.is_dir():
                    for detail_file in sorted(details_dir.glob("*.md")):
                        details[detail_file.name] = detail_file.read_text(encoding="utf-8")

            combined = "\n\n".join(
                part
                for part in [
                    f"Name: {meta.get('name', '')}".strip(),
                    f"Description: {meta.get('description', '')}".strip(),
                    analysis,
                    constraints,
                    *details.values(),
                ]
                if part.strip()
            )

            artifacts.append(
                {
                    "lib_id": lib_id,
                    "name": str(meta.get("name", "")).strip() or lib_id,
                    "description": str(meta.get("description", "")).strip(),
                    "analysis": analysis,
                    "constraints": constraints,
                    "details": details,
                    "combined_text": combined,
                }
            )

        return artifacts

    @staticmethod
    def _collect_routed_element_ids(route_table: list[dict[str, Any]]) -> set[str]:
        """Collect non-ignored destination element IDs from the route table."""
        element_ids: set[str] = set()
        for entry in route_table:
            dest = entry.get("dest", {})
            if not isinstance(dest, dict):
                continue
            if str(dest.get("bucket", "")).strip() == "IGNORED":
                continue
            element_id = str(dest.get("element_id", "")).strip()
            if element_id:
                element_ids.add(element_id)
        return element_ids

    @staticmethod
    def _collect_assembled_element_ids(libraries: list[dict[str, Any]]) -> set[str]:
        """Collect element IDs found in assembled library markdown markers."""
        element_ids: set[str] = set()
        for library in libraries:
            texts = [
                str(library.get("analysis", "")),
                str(library.get("constraints", "")),
                *(str(v) for v in (library.get("details", {}) or {}).values()),
            ]
            for text in texts:
                for match in _ELEMENT_MARKER_RE.findall(text):
                    element_ids.add(match)
        return element_ids

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clamp01(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, numeric))

    @staticmethod
    def _normalize_string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _truncate_for_prompt(text: str, limit: int = 6000) -> str:
        if len(text) <= limit:
            return text
        suffix = "\n\n[... truncated for prompt size ...]"
        return text[: max(0, limit - len(suffix))] + suffix

    def _render_library_for_prompt(self, library: dict[str, Any]) -> str:
        detail_blocks = []
        details = library.get("details", {})
        if isinstance(details, dict):
            for name, content in sorted(details.items()):
                detail_blocks.append(f"### details/{name}\n{content}")

        body = "\n\n".join(
            part
            for part in [
                f"- lib_id: {library.get('lib_id', '')}",
                f"- name: {library.get('name', '')}",
                f"- description: {library.get('description', '')}",
                "\n## analysis.md\n" + str(library.get("analysis", "")),
                "\n## constraints.md\n" + str(library.get("constraints", "")),
                *detail_blocks,
            ]
            if str(part).strip()
        )
        return self._truncate_for_prompt(body)


def validate_libraries(
    workspace_root: Path,
    phase0_output_dir: Path | None = None,
) -> LibraryQualityReport:
    """Convenience function: validate and persist Phase 0 library quality artifacts."""
    validator = LibraryQualityValidator(workspace_root)
    return validator.validate(phase0_output_dir)
