"""Introduced algorithm spec checker for layer promotion gating.

Verifies that infrastructure algorithms (retry, circuit breaking, etc.) that
have no algorithmic origin carry their own spec comments.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.pin_coverage import PinCoverageReport
from spec_manager.compliance.promotion.result import GateCheckResult
from spec_manager.core.code_analysis import SourceAnalysis, analyze_source

# Category classification heuristics based on function name patterns
_CATEGORY_PATTERNS: list[tuple[list[str], str]] = [
    (["retry", "backoff"], "retry"),
    (["circuit", "breaker"], "circuit_breaker"),
    (["route", "dispatch"], "routing"),
    (["serial", "deserial", "marshal"], "serialization"),
    (["cache", "memoize"], "caching"),
    (["rate_limit", "throttle"], "rate_limiting"),
    (["health", "heartbeat", "probe"], "health_check"),
    (["auth", "authenticate", "authorize"], "authentication"),
    (["log", "trace", "span"], "observability"),
]


@dataclass
class IntroducedAlgorithm:
    """An architectural algorithm with no algorithmic origin.

    Attributes:
        function_name: Qualified name of the introduced function.
        file_path: File where the function is defined.
        line_start: First line.
        line_end: Last line.
        has_spec_comments: Whether the function body contains spec comments.
        spec_comment_count: Number of spec comments found.
        has_docstring: Whether it has a docstring.
        category: Classification of the introduced algorithm type.
    """

    function_name: str
    file_path: str
    line_start: int
    line_end: int
    has_spec_comments: bool = False
    spec_comment_count: int = 0
    has_docstring: bool = False
    category: str = "unknown"


def _classify_category(function_name: str, file_path: str) -> str:
    """Classify the category of an introduced algorithm by name/path heuristics."""
    lower_name = function_name.lower()
    lower_path = file_path.lower()
    combined = f"{lower_name} {lower_path}"

    for keywords, category in _CATEGORY_PATTERNS:
        if any(kw in combined for kw in keywords):
            return category

    # Default based on path
    if "infrastructure" in lower_path:
        return "infrastructure"

    return "unknown"


def _count_spec_comments_from_analysis(
    analysis: SourceAnalysis,
    func_name: str,
    start_line: int,
    end_line: int,
) -> int:
    """Count spec-style comments in a function using analyze_source() data.

    Uses the comments already extracted by analyze_source() and filters them
    to the function's line range.

    Args:
        analysis: SourceAnalysis containing all comments for the file.
        func_name: Name of the enclosing function.
        start_line: First line of the function.
        end_line: Last line of the function.

    Returns:
        Count of spec-style comments in the function body.
    """
    count = 0
    for comment in analysis.comments:
        # Filter to comments within the function's line range
        if comment.line < start_line or comment.line > end_line:
            continue
        # Also accept comments matched by enclosing_function
        # Skip shebangs, encodings, type comments, and blank comments
        text = comment.text.strip()
        if text and not text.startswith("!") and "coding" not in text and "type:" not in text:
            count += 1
    return count


def find_introduced_algorithms(
    pin_coverage: PinCoverageReport,
    architectural_files: list[Path],
) -> list[IntroducedAlgorithm]:
    """Find all introduced algorithms in the architectural layer.

    An introduced algorithm is a function/method in the architectural layer
    that has no pin-function import (identified via PinCoverageReport).

    For each introduced algorithm:
    1. Analyze the file to extract the function body.
    2. Scan the body for spec comments.
    3. Classify the algorithm category by heuristics.

    Args:
        pin_coverage: Coverage report identifying introduction locations.
        architectural_files: Architectural files to scan.

    Returns:
        List of IntroducedAlgorithm with spec status.
    """
    # Build set of introduction locations from pin coverage report
    introduction_locations: dict[str, dict[str, Any]] = {}
    for item in pin_coverage.items:
        if item.is_introduction:
            introduction_locations[item.arch_location] = {
                "file_path": item.arch_file_path,
                "line": item.arch_line,
            }

    if not introduction_locations:
        return []

    results: list[IntroducedAlgorithm] = []

    # Group introduction locations by file
    file_locations: dict[str, list[tuple[str, int]]] = {}
    for loc, info in introduction_locations.items():
        fp = info["file_path"]
        file_locations.setdefault(fp, []).append((loc, info["line"]))

    for arch_file in architectural_files:
        file_str = str(arch_file)
        if file_str not in file_locations:
            continue

        try:
            source = arch_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        analysis = analyze_source(source, file_str)
        location_lines = {line for _, line in file_locations[file_str]}

        for func in analysis.functions:
            if func.start_line not in location_lines:
                continue

            spec_count = _count_spec_comments_from_analysis(
                analysis, func.name, func.start_line, func.end_line
            )
            category = _classify_category(func.qualified_name, file_str)

            results.append(
                IntroducedAlgorithm(
                    function_name=func.qualified_name,
                    file_path=file_str,
                    line_start=func.start_line,
                    line_end=func.end_line,
                    has_spec_comments=spec_count > 0,
                    spec_comment_count=spec_count,
                    has_docstring=func.has_docstring,
                    category=category,
                )
            )

    return results


def check_introduced_algorithm_specs(
    pin_coverage: PinCoverageReport,
    architectural_files: list[Path],
    gate_spec: GateSpec,
) -> GateCheckResult:
    """Gate: Introduced algorithms must have spec comments.

    Per design doc Section 12: "architectural algorithms (retry, circuit
    breaking) that have no algorithmic origin must have their own spec
    comments (they are their own mini algorithmic layer for infrastructure)."

    gate_spec.params:
        - require_docstring (bool, default True): Also require docstrings.
        - min_spec_comments (int, default 1): Minimum spec comments required.

    Args:
        pin_coverage: PinCoverageReport from pin_coverage.py.
        architectural_files: Architectural layer files.
        gate_spec: Gate configuration.

    Returns:
        GateCheckResult with findings for each introduced algorithm
        missing spec comments.
    """
    start = time.monotonic()
    require_docstring = gate_spec.params.get("require_docstring", True)
    min_spec_comments = gate_spec.params.get("min_spec_comments", 1)

    introduced = find_introduced_algorithms(pin_coverage, architectural_files)

    findings: list[dict[str, Any]] = []
    for algo in introduced:
        issues: list[str] = []
        if algo.spec_comment_count < min_spec_comments:
            issues.append(
                f"Missing spec comments (found {algo.spec_comment_count}, need {min_spec_comments})"
            )
        if require_docstring and not algo.has_docstring:
            issues.append("Missing docstring")

        if issues:
            findings.append(
                {
                    "function_name": algo.function_name,
                    "file_path": algo.file_path,
                    "line_start": algo.line_start,
                    "line_end": algo.line_end,
                    "category": algo.category,
                    "issues": issues,
                    "spec_comment_count": algo.spec_comment_count,
                    "has_docstring": algo.has_docstring,
                }
            )

    passed = len(findings) == 0
    duration = (time.monotonic() - start) * 1000

    total_introduced = len(introduced)
    compliant = total_introduced - len(findings)

    return GateCheckResult(
        gate_id=GateId.INTRODUCED_ALGORITHM_SPECS.value,
        passed=passed,
        mode=gate_spec.mode.value,
        score=(compliant / total_introduced) if total_introduced > 0 else 1.0,
        findings=findings,
        summary=(
            f"All {total_introduced} introduced algorithm(s) have required specs"
            if passed
            else (
                f"{len(findings)} of {total_introduced} introduced algorithm(s) "
                f"missing required specs"
            )
        ),
        duration_ms=duration,
    )
