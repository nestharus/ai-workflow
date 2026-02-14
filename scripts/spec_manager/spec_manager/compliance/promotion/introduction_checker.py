"""Introduced algorithm spec checker for layer promotion gating."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.pin_coverage import PinCoverageReport
from spec_manager.compliance.promotion.result import GateCheckResult, GateStatus
from spec_manager.core.code_analysis import SourceAnalysis, analyze_source

if TYPE_CHECKING:
    from spec_manager.compliance.promotion.evidence_loader import AnalyzedFile

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
    """An architectural algorithm with no algorithmic origin."""

    function_name: str
    file_path: str
    line_start: int
    line_end: int
    has_spec_comments: bool = False
    spec_comment_count: int = 0
    has_docstring: bool = False
    category: str = "unknown"
    introduction_confidence: float = 1.0


def _classify_category(function_name: str, file_path: str) -> str:
    lower_name = function_name.lower()
    lower_path = file_path.lower()
    combined = f"{lower_name} {lower_path}"

    for keywords, category in _CATEGORY_PATTERNS:
        if any(kw in combined for kw in keywords):
            return category

    if "infrastructure" in lower_path:
        return "infrastructure"

    return "unknown"


def _count_spec_comments_from_analysis(
    analysis: SourceAnalysis,
    start_line: int,
    end_line: int,
) -> int:
    count = 0
    for comment in analysis.comments:
        if comment.line < start_line or comment.line > end_line:
            continue
        text = comment.text.strip()
        if text and not text.startswith("!") and "coding" not in text and "type:" not in text:
            count += 1
    return count


def find_introduced_algorithms(
    pin_coverage: PinCoverageReport,
    architectural_files: list[Path],
    analyzed: list[AnalyzedFile] | None = None,
) -> list[IntroducedAlgorithm]:
    """Find introduced algorithms from pin coverage block-level evidence."""
    introductions_by_file: dict[str, list[dict[str, Any]]] = {}
    for item in pin_coverage.items:
        if not item.is_introduction:
            continue
        introductions_by_file.setdefault(item.arch_file_path, []).append(
            {
                "line_start": item.arch_line,
                "line_end": item.arch_line_end,
                "location": item.arch_location,
                "confidence": item.introduction_confidence,
            }
        )

    if not introductions_by_file:
        return []

    analyzed_lookup: dict[str, AnalyzedFile] = {}
    if analyzed is not None:
        for af in analyzed:
            analyzed_lookup[af.path] = af

    results: list[IntroducedAlgorithm] = []

    for arch_file in architectural_files:
        file_str = str(arch_file)
        intro_entries = introductions_by_file.get(file_str)
        if not intro_entries:
            continue

        af = analyzed_lookup.get(file_str)
        if af is not None:
            analysis = af.analysis
        else:
            try:
                source = arch_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            analysis = analyze_source(source, file_str)

        for intro in intro_entries:
            start_line = int(intro.get("line_start", 0) or 0)
            end_line = int(intro.get("line_end", start_line) or start_line)
            confidence = float(intro.get("confidence", 1.0) or 0.0)
            matching_func = None
            for func in analysis.functions:
                if func.start_line == start_line and func.end_line == end_line:
                    matching_func = func
                    break
                if func.start_line == start_line:
                    matching_func = func
                    break

            if matching_func is None:
                function_name = str(intro.get("location") or f"{file_str}:{start_line}")
                has_docstring = False
            else:
                function_name = matching_func.qualified_name or matching_func.name
                has_docstring = bool(matching_func.has_docstring)
                start_line = matching_func.start_line
                end_line = matching_func.end_line

            spec_count = _count_spec_comments_from_analysis(analysis, start_line, end_line)
            category = _classify_category(function_name, file_str)

            results.append(
                IntroducedAlgorithm(
                    function_name=function_name,
                    file_path=file_str,
                    line_start=start_line,
                    line_end=end_line,
                    has_spec_comments=spec_count > 0,
                    spec_comment_count=spec_count,
                    has_docstring=has_docstring,
                    category=category,
                    introduction_confidence=max(0.0, min(1.0, confidence)),
                )
            )

    return results


def check_introduced_algorithm_specs(
    pin_coverage: PinCoverageReport,
    architectural_files: list[Path],
    gate_spec: GateSpec,
    analyzed: list[AnalyzedFile] | None = None,
) -> GateCheckResult:
    """Gate: introduced algorithms should include local spec documentation."""
    start = time.monotonic()
    require_docstring = bool(gate_spec.params.get("require_docstring", True))
    min_spec_comments = int(gate_spec.params.get("min_spec_comments", 1))
    confidence_threshold = float(gate_spec.params.get("introduction_confidence_threshold", 0.75))

    introduced = find_introduced_algorithms(pin_coverage, architectural_files, analyzed=analyzed)

    strict_findings: list[dict[str, Any]] = []
    uncertain_findings: list[dict[str, Any]] = []

    for algo in introduced:
        issues: list[str] = []
        if algo.spec_comment_count < min_spec_comments:
            issues.append(
                f"Missing spec comments (found {algo.spec_comment_count}, need {min_spec_comments})"
            )
        if require_docstring and not algo.has_docstring:
            issues.append("Missing docstring")

        payload = {
            "function_name": algo.function_name,
            "file_path": algo.file_path,
            "line_start": algo.line_start,
            "line_end": algo.line_end,
            "category": algo.category,
            "issues": issues,
            "spec_comment_count": algo.spec_comment_count,
            "has_docstring": algo.has_docstring,
            "introduction_confidence": algo.introduction_confidence,
        }

        if algo.introduction_confidence < confidence_threshold:
            uncertain_findings.append(payload)
            continue

        if issues:
            strict_findings.append(payload)

    if strict_findings:
        status = GateStatus.FAILED
    elif uncertain_findings:
        status = GateStatus.AMBIGUOUS
    else:
        status = GateStatus.PASSED

    findings: list[dict[str, Any]] = []
    if strict_findings:
        findings.append({"violations": strict_findings})
    if uncertain_findings:
        findings.append({"uncertain_introductions": uncertain_findings})

    total_introduced = len(introduced)
    compliant = total_introduced - len(strict_findings)
    score = (compliant / total_introduced) if total_introduced > 0 else 1.0
    duration = (time.monotonic() - start) * 1000

    if status == GateStatus.PASSED:
        summary = f"All {total_introduced} introduced algorithm(s) have required specs"
    elif status == GateStatus.AMBIGUOUS:
        summary = (
            "Introduction classification is uncertain for some blocks; "
            "manual review required before strict enforcement"
        )
    else:
        summary = (
            f"{len(strict_findings)} of {total_introduced} introduced algorithm(s) "
            "missing required specs"
        )

    return GateCheckResult(
        gate_id=GateId.INTRODUCED_ALGORITHM_SPECS.value,
        mode=gate_spec.mode.value,
        status=status,
        score=score,
        findings=findings,
        summary=summary,
        duration_ms=duration,
    )
