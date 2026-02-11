"""Library quality validator for Phase 0 outputs.

Validates that the libraries produced by Phase 0 meet quality thresholds
before the PromotionLoop begins.  Five dimensions are scored 0-100:

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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

    @property
    def gate_passed(self) -> bool:
        """True if all gate dimensions pass."""
        return all(d.passed for d in self.dimensions if d.mode == "gate")

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
            "library_count": self.library_count,
            "source_line_count": self.source_line_count,
            "issues": self.issues,
        }


class LibraryQualityValidator:
    """Validates Phase 0 library outputs against quality rubric.

    Args:
        workspace_root: Path to workspace containing Phase 0 outputs.
        overlap_threshold: Maximum acceptable routing overlap ratio (default 0.01).
        semantic_overlap_threshold: Maximum acceptable semantic overlap (default 0.75).
        cohesion_threshold: Minimum acceptable cohesion score (default 0.5).
    """

    def __init__(
        self,
        workspace_root: Path,
        *,
        overlap_threshold: float = 0.01,
        semantic_overlap_threshold: float = 0.75,
        cohesion_threshold: float = 0.5,
    ) -> None:
        self._workspace = workspace_root
        self._overlap_threshold = overlap_threshold
        self._semantic_overlap_threshold = semantic_overlap_threshold
        self._cohesion_threshold = cohesion_threshold

    def validate(self, phase0_output_dir: Path | None = None) -> LibraryQualityReport:
        """Run all quality checks on Phase 0 output.

        Args:
            phase0_output_dir: Override for Phase 0 output location.

        Returns:
            LibraryQualityReport with all dimension scores.
        """
        output_dir = phase0_output_dir or (self._workspace / "phase0_output")
        report = LibraryQualityReport()

        # Load Phase 0 artifacts
        route_table = self._load_route_table(output_dir)
        coverage_ledger = self._load_coverage_ledger(output_dir)
        libraries = self._load_libraries(output_dir)

        report.library_count = len(libraries)
        report.source_line_count = len(route_table)

        # 1. Completeness
        completeness = self._check_completeness(route_table, coverage_ledger)
        report.dimensions.append(completeness)

        # 2. Routing overlap
        overlap = self._check_routing_overlap(route_table)
        report.dimensions.append(overlap)

        # 3. Semantic overlap (LLM-based — stubbed for deterministic path)
        semantic = self._check_semantic_overlap(libraries)
        report.dimensions.append(semantic)

        # 4. Concern isolation (LLM-based — stubbed for deterministic path)
        isolation = self._check_concern_isolation(libraries)
        report.dimensions.append(isolation)

        # 5. Dependency minimality (advisory)
        dep_min = self._check_dependency_minimality(libraries)
        report.dimensions.append(dep_min)

        report.overall_passed = report.gate_passed
        report.issues = [
            {"dimension": d.name, "issues": d.issues} for d in report.dimensions if d.issues
        ]

        return report

    def _check_completeness(
        self,
        route_table: list[dict[str, Any]],
        coverage_ledger: list[dict[str, Any]],
    ) -> DimensionScore:
        """Check that all source lines are routed or marked noise."""
        if not route_table and not coverage_ledger:
            return DimensionScore(
                name="completeness",
                score=100.0,
                passed=True,
                details={"note": "No route table found — trivially complete"},
            )

        total = len(coverage_ledger) if coverage_ledger else len(route_table)
        routed = sum(
            1
            for entry in (coverage_ledger or route_table)
            if entry.get("status") in ("routed", "noise", None)
        )

        score = (routed / total * 100.0) if total > 0 else 100.0
        passed = score >= 100.0

        issues = []
        if not passed:
            unrouted = total - routed
            issues.append(f"{unrouted} of {total} lines not routed")

        return DimensionScore(
            name="completeness",
            score=score,
            passed=passed,
            details={"total": total, "routed": routed},
            issues=issues,
        )

    def _check_routing_overlap(self, route_table: list[dict[str, Any]]) -> DimensionScore:
        """Check for source lines routed to multiple libraries."""
        if not route_table:
            return DimensionScore(name="routing_overlap", score=100.0, passed=True)

        # Count libraries per source line
        line_libs: dict[str, set[str]] = {}
        for entry in route_table:
            line_key = f"{entry.get('source_file', '')}:{entry.get('line', 0)}"
            lib_id = entry.get("library_id", entry.get("target_library", ""))
            if lib_id:
                line_libs.setdefault(line_key, set()).add(lib_id)

        overlap_count = sum(1 for libs in line_libs.values() if len(libs) > 1)
        total = len(line_libs) if line_libs else 1
        overlap_ratio = overlap_count / total

        score = max(0.0, 100.0 * (1 - overlap_ratio / 0.02))
        passed = overlap_ratio <= self._overlap_threshold

        issues = []
        if not passed:
            issues.append(
                f"Overlap ratio {overlap_ratio:.2%} exceeds threshold {self._overlap_threshold:.2%}"
            )

        return DimensionScore(
            name="routing_overlap",
            score=score,
            passed=passed,
            details={"overlap_count": overlap_count, "overlap_ratio": overlap_ratio},
            issues=issues,
        )

    def _check_semantic_overlap(self, libraries: list[dict[str, Any]]) -> DimensionScore:
        """Check for semantic overlap between library pairs.

        Uses deterministic heuristics first; LLM judge can be added later.
        """
        if len(libraries) < 2:
            return DimensionScore(name="semantic_overlap", score=100.0, passed=True)

        # Deterministic check: compare library names/descriptions for overlap
        max_overlap = 0.0
        issues = []

        for i, lib_a in enumerate(libraries):
            for lib_b in libraries[i + 1 :]:
                name_a = lib_a.get("name", "").lower()
                name_b = lib_b.get("name", "").lower()
                desc_a = lib_a.get("description", "").lower()
                desc_b = lib_b.get("description", "").lower()

                # Simple word-overlap heuristic
                words_a = set(desc_a.split())
                words_b = set(desc_b.split())
                if words_a and words_b:
                    overlap = len(words_a & words_b) / max(len(words_a), len(words_b))
                    max_overlap = max(max_overlap, overlap)

                    if overlap > self._semantic_overlap_threshold:
                        issues.append(
                            f"Libraries '{name_a}' and '{name_b}' have "
                            f"{overlap:.0%} word overlap in descriptions"
                        )

        score = max(0.0, 100.0 * (1 - max_overlap))
        passed = max_overlap <= self._semantic_overlap_threshold

        return DimensionScore(
            name="semantic_overlap",
            score=score,
            passed=passed,
            details={"max_pair_overlap": max_overlap},
            issues=issues,
        )

    def _check_concern_isolation(self, libraries: list[dict[str, Any]]) -> DimensionScore:
        """Check that each library has a single clear purpose.

        Uses deterministic heuristics; LLM cohesion judge can be added later.
        """
        if not libraries:
            return DimensionScore(name="concern_isolation", score=100.0, passed=True)

        cohesion_scores: list[float] = []
        issues: list[str] = []

        for lib in libraries:
            name = lib.get("name", "unknown")
            desc = lib.get("description", "")

            # Heuristic: shorter descriptions tend to be more focused
            # Libraries with multiple "and"s suggest mixed concerns
            and_count = desc.lower().count(" and ")
            if and_count >= 3:
                cohesion = max(0.3, 1.0 - and_count * 0.15)
                issues.append(
                    f"Library '{name}' may have mixed concerns "
                    f"({and_count} conjunctions in description)"
                )
            else:
                cohesion = min(1.0, 0.7 + 0.1 * (3 - and_count))

            cohesion_scores.append(cohesion)

        avg_cohesion = sum(cohesion_scores) / len(cohesion_scores) if cohesion_scores else 1.0
        score = avg_cohesion * 100.0
        passed = all(c >= self._cohesion_threshold for c in cohesion_scores)

        return DimensionScore(
            name="concern_isolation",
            score=score,
            passed=passed,
            details={"avg_cohesion": avg_cohesion, "per_library": cohesion_scores},
            issues=issues,
        )

    def _check_dependency_minimality(self, libraries: list[dict[str, Any]]) -> DimensionScore:
        """Check that no library is a god-library with too many deps.

        Advisory dimension — warns but does not block.
        """
        if not libraries:
            return DimensionScore(
                name="dependency_minimality",
                score=100.0,
                passed=True,
                mode="advisory",
            )

        # Without LLM inference, use library count as a proxy
        # More libraries = more potential dependency complexity
        lib_count = len(libraries)
        avg_out_degree = max(0, lib_count - 1) / max(lib_count, 1)
        score = max(0.0, min(100.0, 100.0 - 10 * avg_out_degree))

        return DimensionScore(
            name="dependency_minimality",
            score=score,
            passed=True,  # Advisory: always passes
            mode="advisory",
            details={"library_count": lib_count, "avg_out_degree": avg_out_degree},
        )

    # ------------------------------------------------------------------
    # Artifact loading
    # ------------------------------------------------------------------

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
    def _load_libraries(output_dir: Path) -> list[dict[str, Any]]:
        """Load libraries.json from Phase 0 output."""
        path = output_dir / "libraries.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("libraries", data if isinstance(data, list) else [])
        except (json.JSONDecodeError, KeyError):
            return []


def validate_libraries(
    workspace_root: Path,
    phase0_output_dir: Path | None = None,
) -> LibraryQualityReport:
    """Convenience function: validate Phase 0 library outputs.

    Args:
        workspace_root: Repository root.
        phase0_output_dir: Override for Phase 0 output location.

    Returns:
        LibraryQualityReport.
    """
    validator = LibraryQualityValidator(workspace_root)
    return validator.validate(phase0_output_dir)
