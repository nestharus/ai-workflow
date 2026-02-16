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
from typing import TYPE_CHECKING, Any, Literal, Protocol

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
    coverage_state: Literal["measured", "unknown"] = "measured"


@dataclass
class CoverageDiagnostic:
    """Structured diagnostic emitted by coverage run/parse transformations."""

    stage: Literal["run", "parse", "input"]
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class CoverageRunResult:
    """Outcome of invoking ``coverage run``."""

    coverage_data_file: Path
    status: Literal["ok", "command_failed", "timeout", "error"]
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    diagnostics: list[CoverageDiagnostic] = field(default_factory=list)


@dataclass
class CoverageReport:
    """Aggregate coverage report across files and spans."""

    files: list[FileCoverage] = field(default_factory=list)
    pin_spans: list[SpanCoverage] = field(default_factory=list)
    diff_spans: list[SpanCoverage] = field(default_factory=list)
    overall_ratio: float = 0.0
    status: Literal["ok", "parse_failed"] = "ok"
    diagnostics: list[CoverageDiagnostic] = field(default_factory=list)


@dataclass
class ChangedSpanDrop:
    """Records malformed changed-span input that was not normalized."""

    file_path: str
    span_repr: str
    reason: str


@dataclass
class NormalizedChangedSpans:
    """Normalized changed span map plus dropped-entry accounting."""

    spans: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    dropped: list[ChangedSpanDrop] = field(default_factory=list)


@dataclass
class CoverageDetectionResult:
    """End-to-end coverage detection output for orchestrator consumption."""

    run_result: CoverageRunResult
    report: CoverageReport
    evidence: list[GapEvidence] = field(default_factory=list)


class CoverageGapDetector(Protocol):
    """Contract for coverage-based executable gap detectors."""

    def detect(
        self,
        *,
        test_command: list[str],
        source_dirs: list[Path],
        source_files: list[Path],
        project_root: Path,
        pin_registry: PinFunctionRegistry | None = None,
        changed_line_spans: dict[str, list[tuple[int, int]]] | None = None,
        min_uncovered_ratio: float = 0.0,
    ) -> CoverageDetectionResult: ...


def run_coverage(
    test_command: list[str],
    source_dirs: list[Path],
    project_root: Path,
    coverage_data_file: Path | None = None,
) -> CoverageRunResult:
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

    try:
        completed = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        return CoverageRunResult(
            coverage_data_file=coverage_data_file,
            status="timeout",
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            diagnostics=[
                CoverageDiagnostic(
                    stage="run",
                    code="run_timeout",
                    message=f"coverage run timed out after {exc.timeout} seconds",
                )
            ],
        )
    except OSError as exc:
        return CoverageRunResult(
            coverage_data_file=coverage_data_file,
            status="error",
            diagnostics=[
                CoverageDiagnostic(
                    stage="run",
                    code="run_os_error",
                    message=f"coverage run failed to execute: {exc}",
                )
            ],
        )

    if completed.returncode != 0:
        return CoverageRunResult(
            coverage_data_file=coverage_data_file,
            status="command_failed",
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            diagnostics=[
                CoverageDiagnostic(
                    stage="run",
                    code="run_non_zero_exit",
                    message="coverage run exited with non-zero status",
                    details={"returncode": completed.returncode},
                )
            ],
        )

    return CoverageRunResult(
        coverage_data_file=coverage_data_file,
        status="ok",
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def parse_coverage_report(
    coverage_data_file: Path,
    source_files: list[Path],
) -> CoverageReport:
    """Parse a .coverage data file into structured per-file coverage data."""
    json_file = coverage_data_file.parent / "coverage.json"
    report = CoverageReport()

    try:
        command = subprocess.run(
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
    except subprocess.TimeoutExpired as exc:
        report.status = "parse_failed"
        report.diagnostics.append(
            CoverageDiagnostic(
                stage="parse",
                code="json_timeout",
                message=f"coverage json timed out after {exc.timeout} seconds",
            )
        )
        return report
    except OSError as exc:
        report.status = "parse_failed"
        report.diagnostics.append(
            CoverageDiagnostic(
                stage="parse",
                code="json_os_error",
                message=f"coverage json failed to execute: {exc}",
            )
        )
        return report

    if command.returncode != 0:
        report.status = "parse_failed"
        report.diagnostics.append(
            CoverageDiagnostic(
                stage="parse",
                code="json_non_zero_exit",
                message="coverage json exited with non-zero status",
                details={"returncode": command.returncode},
            )
        )
        return report

    if not json_file.exists():
        report.status = "parse_failed"
        report.diagnostics.append(
            CoverageDiagnostic(
                stage="parse",
                code="json_output_missing",
                message="coverage json did not produce the expected output file",
                details={"json_file": str(json_file)},
            )
        )
        return report

    try:
        cov_data = json.loads(json_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        report.status = "parse_failed"
        report.diagnostics.append(
            CoverageDiagnostic(
                stage="parse",
                code="json_decode_failed",
                message="coverage json output could not be parsed",
                details={"json_file": str(json_file)},
            )
        )
        return report
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
    report.files = file_coverages
    report.overall_ratio = overall_ratio
    return report


def coverage_diagnostics_to_gap_evidence(
    diagnostics: list[CoverageDiagnostic],
    *,
    location: str | None = None,
) -> list[GapEvidence]:
    """Project coverage diagnostics into canonical ``GapEvidence`` items."""
    evidence: list[GapEvidence] = []
    for diagnostic in diagnostics:
        details: dict[str, Any] = {
            "gap_type": "coverage_failure",
            "evidence_type": "verification_unavailable",
            "stage": diagnostic.stage,
            "code": diagnostic.code,
            "message": diagnostic.message,
        }
        if diagnostic.details:
            details["diagnostic_details"] = diagnostic.details

        evidence.append(
            GapEvidence(
                invariant_family="executable_coverage",
                description=f"Coverage verification unavailable: {diagnostic.message}",
                details=details,
                confidence=1.0,
                location=location,
                detector="coverage_analyzer",
            )
        )
    return evidence


class SubprocessCoverageDetector:
    """Concrete ``CoverageGapDetector`` that uses coverage.py subprocess calls."""

    def detect(
        self,
        *,
        test_command: list[str],
        source_dirs: list[Path],
        source_files: list[Path],
        project_root: Path,
        pin_registry: PinFunctionRegistry | None = None,
        changed_line_spans: dict[str, list[tuple[int, int]]] | None = None,
        min_uncovered_ratio: float = 0.0,
    ) -> CoverageDetectionResult:
        run_result = run_coverage(
            test_command=test_command,
            source_dirs=source_dirs,
            project_root=project_root,
        )
        report = parse_coverage_report(run_result.coverage_data_file, source_files)

        evidence = coverage_diagnostics_to_gap_evidence(
            run_result.diagnostics,
            location=str(project_root),
        )
        evidence.extend(
            coverage_diagnostics_to_gap_evidence(
                report.diagnostics,
                location=str(project_root),
            )
        )

        if report.status == "ok":
            evidence.extend(
                coverage_to_gap_evidence(
                    report,
                    pin_registry=pin_registry,
                    changed_line_spans=changed_line_spans,
                    min_uncovered_ratio=min_uncovered_ratio,
                )
            )

        return CoverageDetectionResult(
            run_result=run_result,
            report=report,
            evidence=evidence,
        )


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
    normalized_result = _normalize_changed_spans(changed_line_spans)
    normalized_changed = normalized_result.spans

    for dropped in normalized_result.dropped:
        evidence.append(
            GapEvidence(
                invariant_family="executable_coverage",
                description=(
                    "Ignored malformed changed-line span during coverage mapping "
                    f"for {dropped.file_path}"
                ),
                details={
                    "gap_type": "coverage_failure",
                    "evidence_type": "invalid_input",
                    "scope": "diff",
                    "file_path": dropped.file_path,
                    "invalid_span": dropped.span_repr,
                    "reason": dropped.reason,
                },
                confidence=1.0,
                location=dropped.file_path,
                detector="coverage_analyzer",
            )
        )

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
                uncovered_lines = []
                coverage_state: Literal["measured", "unknown"] = "unknown"
            else:
                missing_set = set(file_cov.missing_lines)
                uncovered_lines = [
                    line for line in range(pin.line_start, pin.line_end + 1) if line in missing_set
                ]
                coverage_state = "measured"

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
                coverage_state=coverage_state,
            )
            pin_span_items.append(span)

            if file_cov is None:
                evidence.append(
                    GapEvidence(
                        invariant_family="executable_coverage",
                        description=(
                            f"Coverage unknown for pin span: {pin.pin_func_id} "
                            f"({file_key}:{pin.line_start}-{pin.line_end})"
                        ),
                        details={
                            "evidence_type": "indeterminate",
                            "scope": "pin",
                            "pin_func_id": pin.pin_func_id,
                            "file_path": file_key,
                            "line_start": pin.line_start,
                            "line_end": pin.line_end,
                            "reason": "file_missing_from_coverage_report",
                        },
                        confidence=1.0,
                        location=f"{file_key}:{pin.line_start}-{pin.line_end}",
                        detector="coverage_analyzer",
                    )
                )
                continue

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
                uncovered_lines = []
                coverage_state = "unknown"
            else:
                missing_set = set(file_cov.missing_lines)
                uncovered_lines = [
                    line for line in range(start_line, end_line + 1) if line in missing_set
                ]
                coverage_state = "measured"

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
                coverage_state=coverage_state,
            )
            diff_span_items.append(span)

            if file_cov is None:
                evidence.append(
                    GapEvidence(
                        invariant_family="executable_coverage",
                        description=(
                            f"Coverage unknown for diff span in {file_key}:{start_line}-{end_line}"
                        ),
                        details={
                            "evidence_type": "indeterminate",
                            "scope": "diff",
                            "file_path": file_key,
                            "line_start": start_line,
                            "line_end": end_line,
                            "reason": "file_missing_from_coverage_report",
                        },
                        confidence=1.0,
                        location=f"{file_key}:{start_line}-{end_line}",
                        detector="coverage_analyzer",
                    )
                )
                continue

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
) -> NormalizedChangedSpans:
    if not changed_line_spans:
        return NormalizedChangedSpans()

    normalized: dict[str, list[tuple[int, int]]] = {}
    dropped: list[ChangedSpanDrop] = []
    for file_path, spans in changed_line_spans.items():
        if not isinstance(file_path, str):
            dropped.append(
                ChangedSpanDrop(
                    file_path=str(file_path),
                    span_repr=repr(spans),
                    reason="file_path_must_be_string",
                )
            )
            continue
        key = _normalize_path(file_path)
        if not isinstance(spans, list):
            dropped.append(
                ChangedSpanDrop(
                    file_path=key,
                    span_repr=repr(spans),
                    reason="span_collection_must_be_list",
                )
            )
            continue
        valid_spans: list[tuple[int, int]] = []
        for span in spans:
            if not isinstance(span, (tuple, list)) or len(span) != 2:
                dropped.append(
                    ChangedSpanDrop(
                        file_path=key,
                        span_repr=repr(span),
                        reason="span_must_be_two_item_sequence",
                    )
                )
                continue
            try:
                start = int(span[0])
                end = int(span[1])
            except (TypeError, ValueError):
                dropped.append(
                    ChangedSpanDrop(
                        file_path=key,
                        span_repr=repr(span),
                        reason="span_boundaries_must_be_integers",
                    )
                )
                continue
            if start <= 0:
                dropped.append(
                    ChangedSpanDrop(
                        file_path=key,
                        span_repr=repr(span),
                        reason="span_start_must_be_positive",
                    )
                )
                continue
            if end < start:
                end = start
            valid_spans.append((start, end))
        if valid_spans:
            normalized[key] = valid_spans
    return NormalizedChangedSpans(spans=normalized, dropped=dropped)


def _resolve_file_coverage(
    file_lookup: dict[str, FileCoverage],
    file_path: str,
) -> tuple[str, FileCoverage | None]:
    normalized = _normalize_path(file_path)
    if normalized in file_lookup:
        return normalized, file_lookup[normalized]

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
    "CoverageDetectionResult",
    "CoverageDiagnostic",
    "CoverageGapDetector",
    "CoverageReport",
    "CoverageRunResult",
    "FileCoverage",
    "SpanCoverage",
    "SubprocessCoverageDetector",
    "coverage_diagnostics_to_gap_evidence",
    "coverage_to_gap_evidence",
    "parse_coverage_report",
    "run_coverage",
]
