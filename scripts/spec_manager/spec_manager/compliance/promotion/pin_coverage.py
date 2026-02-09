"""Pin coverage checker for layer promotion gating.

Verifies that every architectural location pins back to an algorithmic origin,
except for classified introduction nodes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult
from spec_manager.core.code_analysis import analyze_source
from spec_manager.schemas.pin_functions import PinFunctionRegistry

# Default marker comment that classifies a function as an introduction
_DEFAULT_INTRODUCTION_MARKERS = ["# @introduced", "# @infrastructure"]


@dataclass
class PinCoverageItem:
    """Coverage status of a single architectural location.

    Attributes:
        arch_location: The architectural file:class.method or file:function.
        arch_file_path: Relative path to the architectural file.
        arch_line: Line number.
        has_pin: Whether this location has a pin-function import.
        pin_func_ids: Pin-function IDs it imports (empty if no pin).
        is_introduction: Whether this is a classified introduction.
        introduction_has_spec: If is_introduction, whether it has spec comments.
    """

    arch_location: str
    arch_file_path: str
    arch_line: int
    has_pin: bool = False
    pin_func_ids: list[str] = field(default_factory=list)
    is_introduction: bool = False
    introduction_has_spec: bool = False


@dataclass
class PinCoverageReport:
    """Aggregate pin coverage report.

    Attributes:
        total_locations: Number of architectural locations scanned.
        pinned_locations: Number with pin-function imports.
        introduction_locations: Number classified as introductions.
        unpinned_locations: Number with neither pin nor introduction classification.
        coverage_ratio: pinned / (total - introductions), or 1.0 if no non-introductions.
        items: Per-location details.
    """

    total_locations: int
    pinned_locations: int
    introduction_locations: int
    unpinned_locations: int
    coverage_ratio: float
    items: list[PinCoverageItem] = field(default_factory=list)


def _extract_functions_from_file(file_path: Path) -> list[dict[str, Any]]:
    """Extract all function/method definitions from a source file.

    Returns a list of dicts with keys: name, qualified_name, line, is_method,
    body_source_lines (the raw source lines of the function body).
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    analysis = analyze_source(source, str(file_path))
    lines = source.splitlines()
    results: list[dict[str, Any]] = []

    for func in analysis.functions:
        body_lines = lines[func.start_line - 1 : func.end_line]
        is_method = "." in func.qualified_name
        results.append(
            {
                "name": func.name,
                "qualified_name": func.qualified_name,
                "line": func.start_line,
                "is_method": is_method,
                "body_source_lines": body_lines,
            }
        )

    return results


def _has_introduction_marker(
    body_lines: list[str],
    markers: list[str],
) -> bool:
    """Check if function body contains an introduction marker comment."""
    for line in body_lines:
        stripped = line.strip()
        for marker in markers:
            if marker in stripped:
                return True
    return False


def _is_infrastructure_path(file_path: str) -> bool:
    """Check if the file is in an infrastructure directory."""
    return "infrastructure" in file_path.split("/")


def build_pin_coverage_report(
    registry: PinFunctionRegistry,
    architectural_files: list[Path],
    introduction_markers: list[str] | None = None,
) -> PinCoverageReport:
    """Build a pin coverage report by scanning architectural files.

    For each function/method in each architectural file:
    1. Check if it imports any pin-functions (via registry import edges).
    2. If not, check if it is classified as an introduction.
    3. Record coverage status.

    Introduction detection:
    - Files in architectural/infrastructure/ are introduction candidates.
    - Functions with a "# @introduced" marker comment are introductions.
    - ImportEdge entries with projection_type=INTRODUCTION.
    - Optional introduction_markers list for custom patterns.

    Args:
        registry: The PinFunctionRegistry from Plan 02.
        architectural_files: Files to check coverage for.
        introduction_markers: Optional additional marker strings.

    Returns:
        PinCoverageReport with per-location coverage data.
    """
    markers = list(_DEFAULT_INTRODUCTION_MARKERS)
    if introduction_markers:
        markers.extend(introduction_markers)

    # Build lookup: arch_location -> list of pin_func_ids from import edges
    edge_lookup: dict[str, list[str]] = {}
    introduction_edges: set[str] = set()
    for edge in registry.import_edges:
        edge_lookup.setdefault(edge.arch_location, []).append(edge.pin_func_id)
        if edge.projection_type == "introduction":
            introduction_edges.add(edge.arch_location)

    items: list[PinCoverageItem] = []

    for arch_file in architectural_files:
        file_str = str(arch_file)
        functions = _extract_functions_from_file(arch_file)

        for func_info in functions:
            # Build the arch_location key: "file:qualified_name"
            arch_location = f"{file_str}:{func_info['qualified_name']}"
            pin_func_ids = edge_lookup.get(arch_location, [])
            has_pin = len(pin_func_ids) > 0

            # Check if this is an introduction
            is_introduction = False
            introduction_has_spec = False

            if arch_location in introduction_edges or (
                not has_pin
                and (
                    _is_infrastructure_path(file_str)
                    or _has_introduction_marker(
                        func_info.get("body_source_lines", []),
                        markers,
                    )
                )
            ):
                is_introduction = True

            # If it is an introduction, check for spec comments
            if is_introduction:
                body_lines = func_info.get("body_source_lines", [])
                spec_comments = [
                    line
                    for line in body_lines
                    if line.strip().startswith("#") and not line.strip().startswith("#!")
                ]
                introduction_has_spec = len(spec_comments) > 0

            items.append(
                PinCoverageItem(
                    arch_location=arch_location,
                    arch_file_path=file_str,
                    arch_line=func_info["line"],
                    has_pin=has_pin,
                    pin_func_ids=pin_func_ids,
                    is_introduction=is_introduction,
                    introduction_has_spec=introduction_has_spec,
                )
            )

    total = len(items)
    pinned = sum(1 for item in items if item.has_pin)
    introductions = sum(1 for item in items if item.is_introduction)
    unpinned = total - pinned - introductions

    # Coverage = pinned / (total - introductions)
    denominator = total - introductions
    coverage_ratio = (pinned / denominator) if denominator > 0 else 1.0

    return PinCoverageReport(
        total_locations=total,
        pinned_locations=pinned,
        introduction_locations=introductions,
        unpinned_locations=unpinned,
        coverage_ratio=coverage_ratio,
        items=items,
    )


def check_pin_coverage(
    registry: PinFunctionRegistry,
    architectural_files: list[Path],
    gate_spec: GateSpec,
    introduction_markers: list[str] | None = None,
) -> GateCheckResult:
    """Gate: Every architectural location pins to algorithmic origin.

    Builds the pin coverage report and evaluates against the gate threshold.

    gate_spec.threshold: Minimum pin coverage ratio (default 1.0 = 100%).
    gate_spec.params:
        - introduction_markers (list[str]): Additional introduction markers.
        - exclude_patterns (list[str]): File patterns to exclude from coverage.

    Args:
        registry: PinFunctionRegistry.
        architectural_files: Architectural layer files.
        gate_spec: Gate configuration.
        introduction_markers: Additional introduction markers.

    Returns:
        GateCheckResult with findings for each unpinned location.
    """
    start = time.monotonic()
    threshold = gate_spec.threshold if gate_spec.threshold > 0 else 1.0
    extra_markers = gate_spec.params.get("introduction_markers", [])
    all_markers = list(introduction_markers or []) + extra_markers

    report = build_pin_coverage_report(
        registry=registry,
        architectural_files=architectural_files,
        introduction_markers=all_markers or None,
    )

    # Build findings for unpinned locations
    findings: list[dict[str, Any]] = []
    for item in report.items:
        if not item.has_pin and not item.is_introduction:
            findings.append(
                {
                    "arch_location": item.arch_location,
                    "arch_file_path": item.arch_file_path,
                    "arch_line": item.arch_line,
                    "reason": "No pin-function import and not classified as introduction",
                }
            )

    passed = report.coverage_ratio >= threshold
    duration = (time.monotonic() - start) * 1000

    return GateCheckResult(
        gate_id=GateId.PIN_COVERAGE.value,
        passed=passed,
        mode=gate_spec.mode.value,
        score=report.coverage_ratio,
        findings=findings,
        summary=(
            f"Pin coverage: {report.coverage_ratio:.1%} "
            f"({report.pinned_locations} pinned, "
            f"{report.introduction_locations} introductions, "
            f"{report.unpinned_locations} unpinned "
            f"of {report.total_locations} total)"
        ),
        duration_ms=duration,
    )
