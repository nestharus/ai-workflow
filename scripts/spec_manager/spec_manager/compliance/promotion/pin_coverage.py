"""Pin coverage checker for layer promotion gating."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult, GateStatus
from spec_manager.schemas.pin_functions import PinFunctionRegistry, ProjectionType

if TYPE_CHECKING:
    from spec_manager.compliance.promotion.evidence_loader import AnalyzedFile


@dataclass
class PinCoverageItem:
    """Coverage status of one changed span."""

    arch_location: str
    arch_file_path: str
    arch_line: int
    arch_line_end: int
    has_pin: bool = False
    pin_func_ids: list[str] = field(default_factory=list)
    is_introduction: bool = False
    introduction_has_spec: bool = False
    introduction_confidence: float = 1.0


@dataclass
class PinCoverageReport:
    """Aggregate pin coverage report."""

    total_locations: int
    pinned_locations: int
    introduction_locations: int
    unpinned_locations: int
    coverage_ratio: float
    items: list[PinCoverageItem] = field(default_factory=list)
    missing_changed_files: list[str] = field(default_factory=list)
    evidence_issues: list[dict[str, Any]] = field(default_factory=list)


def build_pin_coverage_report(
    registry: PinFunctionRegistry,
    architectural_files: list[Path],
    *,
    changed_files: list[str] | None = None,
    changed_line_spans: dict[str, list[tuple[int, int]]] | None = None,
    analyzed: list[AnalyzedFile] | None = None,
) -> PinCoverageReport:
    """Build pin coverage report over changed spans (diff semantics)."""
    analyzed_lookup: dict[str, AnalyzedFile] = {}
    if analyzed is not None:
        for af in analyzed:
            analyzed_lookup[_normalize_path(af.path)] = af

    known_files: set[str] = set(analyzed_lookup.keys())
    known_files.update(_normalize_path(path) for path in architectural_files)
    known_files.update(_normalize_path(pin.file_path) for pin in registry.pin_functions)

    spans_by_file, missing_changed_files, evidence_issues = _resolve_changed_spans(
        changed_files=changed_files,
        changed_line_spans=changed_line_spans,
        analyzed_lookup=analyzed_lookup,
        known_files=known_files,
    )

    introduction_lines_by_file: dict[str, set[int]] = {}
    for edge in registry.import_edges:
        if edge.projection_type != ProjectionType.INTRODUCTION:
            continue
        file_key = _normalize_path(edge.arch_file_path)
        intro_lines = introduction_lines_by_file.setdefault(file_key, set())
        if edge.arch_line > 0:
            intro_lines.add(edge.arch_line)

    pins_by_file: dict[str, list[Any]] = {}
    for pin in registry.pin_functions:
        pins_by_file.setdefault(_normalize_path(pin.file_path), []).append(pin)

    items: list[PinCoverageItem] = []

    for file_path, spans in spans_by_file.items():
        file_pins = pins_by_file.get(file_path, [])
        intro_lines = introduction_lines_by_file.get(file_path, set())

        for idx, (start_line, end_line) in enumerate(spans, start=1):
            covering_pins = [
                pin
                for pin in file_pins
                if _ranges_overlap(start_line, end_line, pin.line_start, pin.line_end)
            ]
            pin_func_ids = sorted({pin.pin_func_id for pin in covering_pins})

            is_introduction = any(start_line <= line <= end_line for line in intro_lines)
            location = f"{file_path}:{start_line}-{end_line}#span{idx}"

            items.append(
                PinCoverageItem(
                    arch_location=location,
                    arch_file_path=file_path,
                    arch_line=start_line,
                    arch_line_end=end_line,
                    has_pin=bool(pin_func_ids),
                    pin_func_ids=pin_func_ids,
                    is_introduction=is_introduction,
                    introduction_has_spec=False,
                    introduction_confidence=1.0,
                )
            )

    total = len(items)
    pinned = sum(1 for item in items if item.has_pin and not item.is_introduction)
    introductions = sum(1 for item in items if item.is_introduction)
    unpinned = sum(1 for item in items if not item.has_pin and not item.is_introduction)

    denominator = total - introductions
    coverage_ratio = (pinned / denominator) if denominator > 0 else 1.0

    return PinCoverageReport(
        total_locations=total,
        pinned_locations=pinned,
        introduction_locations=introductions,
        unpinned_locations=unpinned,
        coverage_ratio=coverage_ratio,
        items=items,
        missing_changed_files=sorted(set(missing_changed_files)),
        evidence_issues=evidence_issues,
    )


def check_pin_coverage(
    registry: PinFunctionRegistry,
    architectural_files: list[Path],
    gate_spec: GateSpec,
    *,
    changed_files: list[str] | None = None,
    changed_line_spans: dict[str, list[tuple[int, int]]] | None = None,
    analyzed: list[AnalyzedFile] | None = None,
) -> GateCheckResult:
    """Gate: changed spans are covered by pin spans or introduction edges."""
    start = time.monotonic()
    threshold = gate_spec.threshold if gate_spec.threshold > 0 else 1.0

    report = build_pin_coverage_report(
        registry=registry,
        architectural_files=architectural_files,
        changed_files=changed_files,
        changed_line_spans=changed_line_spans,
        analyzed=analyzed,
    )

    duration = (time.monotonic() - start) * 1000
    if report.evidence_issues:
        return GateCheckResult(
            gate_id=GateId.PIN_COVERAGE.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=report.evidence_issues,
            summary=(
                "Changed-span evidence is incomplete or malformed; "
                "pin coverage requires valid changed span inputs."
            ),
            duration_ms=duration,
        )

    if report.total_locations == 0:
        return GateCheckResult(
            gate_id=GateId.PIN_COVERAGE.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=[{"reason": "no_changed_spans"}],
            summary="No changed spans were provided for pin coverage evaluation",
            duration_ms=duration,
        )

    findings: list[dict[str, Any]] = []
    for item in report.items:
        if not item.has_pin and not item.is_introduction:
            findings.append(
                {
                    "arch_location": item.arch_location,
                    "arch_file_path": item.arch_file_path,
                    "line_start": item.arch_line,
                    "line_end": item.arch_line_end,
                    "reason": "Changed span has no pin or introduction coverage",
                }
            )

    passed = report.coverage_ratio >= threshold

    return GateCheckResult(
        gate_id=GateId.PIN_COVERAGE.value,
        passed=passed,
        mode=gate_spec.mode.value,
        status=GateStatus.PASSED if passed else GateStatus.FAILED,
        score=report.coverage_ratio,
        findings=findings,
        summary=(
            f"Pin/diff span coverage: {report.coverage_ratio:.1%} "
            f"({report.pinned_locations} pinned, "
            f"{report.introduction_locations} introductions, "
            f"{report.unpinned_locations} uncovered of {report.total_locations})"
        ),
        duration_ms=duration,
    )


def _resolve_changed_spans(
    *,
    changed_files: list[str] | None,
    changed_line_spans: dict[str, list[tuple[int, int]]] | None,
    analyzed_lookup: dict[str, AnalyzedFile],
    known_files: set[str],
) -> tuple[dict[str, list[tuple[int, int]]], list[str], list[dict[str, Any]]]:
    spans_by_file: dict[str, list[tuple[int, int]]] = {}
    missing: list[str] = []
    evidence_issues: list[dict[str, Any]] = []

    if changed_line_spans:
        for raw_file, raw_spans in changed_line_spans.items():
            file_path = str(raw_file)
            resolved, resolution_issue = _resolve_known_file(file_path, known_files)
            if resolution_issue is not None:
                evidence_issues.append(resolution_issue)
                if resolution_issue.get("reason") == "missing_changed_file":
                    missing.append(file_path)
                continue
            if resolved is None:
                missing.append(file_path)
                continue
            if not isinstance(raw_spans, list):
                evidence_issues.append(
                    {
                        "reason": "invalid_changed_spans_payload",
                        "file_path": file_path,
                        "spans": repr(raw_spans),
                    }
                )
                continue
            valid_spans: list[tuple[int, int]] = []
            for span_idx, span in enumerate(raw_spans, start=1):
                if not isinstance(span, (tuple, list)) or len(span) != 2:
                    evidence_issues.append(
                        {
                            "reason": "invalid_changed_span_shape",
                            "file_path": file_path,
                            "span_index": span_idx,
                            "span": repr(span),
                        }
                    )
                    continue
                try:
                    start = int(span[0])
                    end = int(span[1])
                except (TypeError, ValueError):
                    evidence_issues.append(
                        {
                            "reason": "invalid_changed_span_value",
                            "file_path": file_path,
                            "span_index": span_idx,
                            "span": repr(span),
                        }
                    )
                    continue
                if start <= 0:
                    evidence_issues.append(
                        {
                            "reason": "invalid_changed_span_start",
                            "file_path": file_path,
                            "span_index": span_idx,
                            "span": repr(span),
                        }
                    )
                    continue
                if end < start:
                    evidence_issues.append(
                        {
                            "reason": "changed_span_end_before_start",
                            "file_path": file_path,
                            "span_index": span_idx,
                            "span": repr(span),
                        }
                    )
                    end = start
                valid_spans.append((start, end))
            if valid_spans:
                spans_by_file[resolved] = valid_spans
            else:
                evidence_issues.append(
                    {
                        "reason": "no_valid_changed_spans",
                        "file_path": file_path,
                    }
                )
        return spans_by_file, missing, evidence_issues

    for raw_file in changed_files or []:
        file_path = str(raw_file)
        resolved, resolution_issue = _resolve_known_file(file_path, known_files)
        if resolution_issue is not None:
            evidence_issues.append(resolution_issue)
            if resolution_issue.get("reason") == "missing_changed_file":
                missing.append(file_path)
            continue
        if resolved is None:
            missing.append(file_path)
            continue

        line_count = _line_count_for_file(resolved, analyzed_lookup)
        if line_count <= 0:
            evidence_issues.append(
                {
                    "reason": "unreadable_changed_file",
                    "file_path": file_path,
                }
            )
            missing.append(file_path)
            continue

        spans_by_file[resolved] = [(1, line_count)]

    return spans_by_file, missing, evidence_issues


def _line_count_for_file(file_path: str, analyzed_lookup: dict[str, AnalyzedFile]) -> int:
    analyzed = analyzed_lookup.get(file_path)
    if analyzed is not None:
        return len(analyzed.content.splitlines())

    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return 0
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return 0


def _resolve_known_file(
    raw_file: str,
    known_files: set[str],
) -> tuple[str | None, dict[str, Any] | None]:
    candidate = _normalize_path(raw_file)
    if candidate in known_files:
        return candidate, None

    suffix_matches = sorted(
        known for known in known_files if known.endswith(candidate) or candidate.endswith(known)
    )
    if len(suffix_matches) == 1:
        return suffix_matches[0], None
    if len(suffix_matches) > 1:
        return None, {
            "reason": "ambiguous_changed_file",
            "file_path": str(raw_file),
            "matches": suffix_matches,
        }

    if Path(candidate).exists():
        return candidate, None
    return None, {"reason": "missing_changed_file", "file_path": str(raw_file)}


def _ranges_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return not (a_end < b_start or b_end < a_start)


def _normalize_path(path: str | Path) -> str:
    return str(Path(path).resolve()).replace("\\", "/")
