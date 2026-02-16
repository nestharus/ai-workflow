"""Coverage analyzer for executable gap detection.

Maps runtime coverage onto pin spans and changed diff spans.
This module does not derive function-level gaps from source parsing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from spec_manager.core.gap import GapEvidence

if TYPE_CHECKING:
    from spec_manager.schemas.pin_functions import PinFunctionRegistry


@dataclass
class FileCoverage:
    """Coverage data for a single file."""

    file_path: str
    total_statements: int
    covered_statements: int
    missing_lines: list[int]
    coverage_ratio: float


@dataclass
class SpanCoverage:
    """Coverage status for one pin span or changed diff span."""

    scope: Literal["pin", "diff"]
    file_path: str
    span_id: str
    line_start: int
    line_end: int
    total_lines: int
    uncovered_lines: list[int]
    uncovered_ratio: float


@dataclass
class CoverageReport:
    """Aggregate coverage report across files and spans."""

    files: list[FileCoverage] = field(default_factory=list)
    pin_spans: list[SpanCoverage] = field(default_factory=list)
    diff_spans: list[SpanCoverage] = field(default_factory=list)
    overall_ratio: float = 0.0


def run_coverage(
    test_command: list[str],
    source_dirs: list[Path],
    project_root: Path,
    coverage_data_file: Path | None = None,
) -> Path:
    """Run a test command with coverage.py instrumentation."""
    if coverage_data_file is None:
        coverage_data_file = project_root / ".coverage"

    source_arg = ",".join(str(d) for d in source_dirs)

    cmd = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        f"--source={source_arg}",
        f"--data-file={coverage_data_file}",
        "-m",
        *test_command,
    ]

    subprocess.run(
        cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        timeout=300,
    )

    return coverage_data_file


def parse_coverage_report(
    coverage_data_file: Path,
    source_files: list[Path],
) -> CoverageReport:
    """Parse a .coverage data file into structured per-file coverage data."""
    json_file = coverage_data_file.parent / "coverage.json"

    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "json",
                f"--data-file={coverage_data_file}",
                f"-o={json_file}",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return CoverageReport()

    if not json_file.exists():
        return CoverageReport()

    try:
        cov_data = json.loads(json_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return CoverageReport()
    finally:
        json_file.unlink(missing_ok=True)

    file_coverages: list[FileCoverage] = []
    total_stmts = 0
    total_covered = 0

    source_file_strs = {_normalize_path(f) for f in source_files}
    files_data = cov_data.get("files", {})

    for file_path_str, file_info in files_data.items():
        resolved = _normalize_path(file_path_str)
        if source_file_strs and resolved not in source_file_strs:
            continue

        summary = file_info.get("summary", {})
        num_statements = int(summary.get("num_statements", 0) or 0)
        covered = int(summary.get("covered_lines", 0) or 0)
        missing_raw = file_info.get("missing_lines", [])
        missing = sorted(
            {
                int(line)
                for line in missing_raw
                if isinstance(line, int) or (isinstance(line, str) and line.isdigit())
            }
        )
        ratio = covered / num_statements if num_statements > 0 else 1.0

        file_coverages.append(
            FileCoverage(
                file_path=resolved,
                total_statements=num_statements,
                covered_statements=covered,
                missing_lines=missing,
                coverage_ratio=ratio,
            )
        )

        total_stmts += num_statements
        total_covered += covered

    overall_ratio = total_covered / total_stmts if total_stmts > 0 else 1.0
    return CoverageReport(files=file_coverages, overall_ratio=overall_ratio)


def coverage_to_gap_evidence(
    report: CoverageReport,
    *,
    pin_registry: PinFunctionRegistry | None = None,
    changed_line_spans: dict[str, list[tuple[int, int]]] | None = None,
    min_uncovered_ratio: float = 0.0,
) -> list[GapEvidence]:
    """Map coverage gaps to pin spans and diff spans.

    A span becomes a gap when ``uncovered_ratio`` is greater than
    ``min_uncovered_ratio``.
    """
    evidence: list[GapEvidence] = []

    threshold = max(0.0, min(1.0, float(min_uncovered_ratio)))
    file_lookup = {_normalize_path(fc.file_path): fc for fc in report.files}
    normalized_changed = _normalize_changed_spans(changed_line_spans)

    pin_span_items: list[SpanCoverage] = []
    if pin_registry is not None:
        for pin in pin_registry.pin_functions:
            file_key, file_cov = _resolve_file_coverage(file_lookup, pin.file_path)
            if normalized_changed and not _pin_touches_changed_spans(
                pin.file_path, pin.line_start, pin.line_end, normalized_changed
            ):
                continue

            total_lines = max(0, pin.line_end - pin.line_start + 1)
            if total_lines <= 0:
                continue

            if file_cov is None:
                uncovered_lines = list(range(pin.line_start, pin.line_end + 1))
            else:
                missing_set = set(file_cov.missing_lines)
                uncovered_lines = [
                    line for line in range(pin.line_start, pin.line_end + 1) if line in missing_set
                ]

            uncovered_ratio = len(uncovered_lines) / total_lines
            span = SpanCoverage(
                scope="pin",
                file_path=file_key,
                span_id=pin.pin_func_id,
                line_start=pin.line_start,
                line_end=pin.line_end,
                total_lines=total_lines,
                uncovered_lines=uncovered_lines,
                uncovered_ratio=uncovered_ratio,
            )
            pin_span_items.append(span)

            if uncovered_ratio <= threshold:
                continue

            evidence.append(
                GapEvidence(
                    invariant_family="executable_coverage",
                    description=(
                        f"Uncovered changed pin span: {pin.pin_func_id} "
                        f"({uncovered_ratio:.0%} uncovered)"
                    ),
                    details={
                        "scope": "pin",
                        "pin_func_id": pin.pin_func_id,
                        "file_path": file_key,
                        "line_start": pin.line_start,
                        "line_end": pin.line_end,
                        "uncovered_lines": uncovered_lines,
                        "uncovered_ratio": uncovered_ratio,
                    },
                    confidence=0.8,
                    location=f"{file_key}:{pin.line_start}-{pin.line_end}",
                    detector="coverage_analyzer",
                )
            )

    diff_span_items: list[SpanCoverage] = []
    for file_path, spans in normalized_changed.items():
        file_key, file_cov = _resolve_file_coverage(file_lookup, file_path)
        for idx, (start_line, end_line) in enumerate(spans, start=1):
            total_lines = max(0, end_line - start_line + 1)
            if total_lines <= 0:
                continue

            if file_cov is None:
                uncovered_lines = list(range(start_line, end_line + 1))
            else:
                missing_set = set(file_cov.missing_lines)
                uncovered_lines = [
                    line for line in range(start_line, end_line + 1) if line in missing_set
                ]

            uncovered_ratio = len(uncovered_lines) / total_lines
            span = SpanCoverage(
                scope="diff",
                file_path=file_key,
                span_id=f"diff_{idx}",
                line_start=start_line,
                line_end=end_line,
                total_lines=total_lines,
                uncovered_lines=uncovered_lines,
                uncovered_ratio=uncovered_ratio,
            )
            diff_span_items.append(span)

            if uncovered_ratio <= threshold:
                continue

            evidence.append(
                GapEvidence(
                    invariant_family="executable_coverage",
                    description=(
                        f"Uncovered diff span in {file_key}:{start_line}-{end_line} "
                        f"({uncovered_ratio:.0%} uncovered)"
                    ),
                    details={
                        "scope": "diff",
                        "file_path": file_key,
                        "line_start": start_line,
                        "line_end": end_line,
                        "uncovered_lines": uncovered_lines,
                        "uncovered_ratio": uncovered_ratio,
                    },
                    confidence=0.8,
                    location=f"{file_key}:{start_line}-{end_line}",
                    detector="coverage_analyzer",
                )
            )

    report.pin_spans = pin_span_items
    report.diff_spans = diff_span_items
    return evidence


def _normalize_path(path: str | Path) -> str:
    return str(Path(path).resolve()).replace("\\", "/")


def _normalize_changed_spans(
    changed_line_spans: dict[str, list[tuple[int, int]]] | None,
) -> dict[str, list[tuple[int, int]]]:
    if not changed_line_spans:
        return {}

    normalized: dict[str, list[tuple[int, int]]] = {}
    for file_path, spans in changed_line_spans.items():
        if not isinstance(file_path, str):
            continue
        key = _normalize_path(file_path)
        valid_spans: list[tuple[int, int]] = []
        for span in spans:
            if not isinstance(span, (tuple, list)) or len(span) != 2:
                continue
            try:
                start = int(span[0])
                end = int(span[1])
            except (TypeError, ValueError):
                continue
            if start <= 0:
                continue
            if end < start:
                end = start
            valid_spans.append((start, end))
        if valid_spans:
            normalized[key] = valid_spans
    return normalized


def _resolve_file_coverage(
    file_lookup: dict[str, FileCoverage],
    file_path: str,
) -> tuple[str, FileCoverage | None]:
    normalized = _normalize_path(file_path)
    if normalized in file_lookup:
        return normalized, file_lookup[normalized]

    for candidate_path, coverage in file_lookup.items():
        if normalized.endswith(candidate_path) or candidate_path.endswith(normalized):
            return candidate_path, coverage

    return normalized, None


def _pin_touches_changed_spans(
    file_path: str,
    line_start: int,
    line_end: int,
    changed_spans: dict[str, list[tuple[int, int]]],
) -> bool:
    key = _normalize_path(file_path)
    spans = changed_spans.get(key)
    if not spans:
        return False
    for changed_start, changed_end in spans:
        if line_end < changed_start or line_start > changed_end:
            continue
        return True
    return False


__all__ = [
    "CoverageReport",
    "FileCoverage",
    "SpanCoverage",
    "coverage_to_gap_evidence",
    "parse_coverage_report",
    "run_coverage",
]
