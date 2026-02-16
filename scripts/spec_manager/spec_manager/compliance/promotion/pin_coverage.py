"""Pin coverage checker for layer promotion gating."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.compliance.promotion.config import GateId, GateSpec
from spec_manager.compliance.promotion.result import GateCheckResult, GateStatus
from spec_manager.core.code_analysis import SourceAnalysis, analyze_source
from spec_manager.schemas.pin_functions import PinFunctionRegistry

if TYPE_CHECKING:
    from spec_manager.compliance.promotion.evidence_loader import AnalyzedFile


@dataclass
class PinCoverageItem:
    """Coverage status of a single architectural block span."""

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
    missing_architecture_files: list[str] = field(default_factory=list)


@dataclass
class _ArchBlock:
    block_id: str
    line_start: int
    line_end: int
    kind: str
    confidence: float = 1.0


def _coerce_arch_blocks(*, analysis: SourceAnalysis) -> list[_ArchBlock]:
    """Resolve architecture blocks from analysis facets only."""
    raw_blocks = analysis.facets.get("arch_blocks")

    blocks: list[_ArchBlock] = []
    if isinstance(raw_blocks, list):
        for idx, block in enumerate(raw_blocks):
            if not isinstance(block, dict):
                continue
            start = int(block.get("line_start") or block.get("start_line") or 0)
            end = int(block.get("line_end") or block.get("end_line") or start)
            if start <= 0:
                continue
            if end < start:
                end = start
            block_id = str(block.get("id") or block.get("block_id") or f"block_{idx + 1}").strip()
            kind = str(block.get("kind") or "ARCH_BLOCK").strip().upper()
            confidence_raw = block.get("confidence", 1.0)
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                confidence = 1.0
            blocks.append(
                _ArchBlock(
                    block_id=block_id,
                    line_start=start,
                    line_end=end,
                    kind=kind,
                    confidence=max(0.0, min(1.0, confidence)),
                )
            )
    return blocks


def _comments_in_range(analysis: SourceAnalysis, start_line: int, end_line: int) -> list[str]:
    comments: list[str] = []
    for comment in analysis.comments:
        if comment.line < start_line or comment.line > end_line:
            continue
        text = comment.text.strip()
        if text and not text.startswith("!") and "coding" not in text and "type:" not in text:
            comments.append(text)
    return comments


def build_pin_coverage_report(
    registry: PinFunctionRegistry,
    architectural_files: list[Path],
    analyzed: list[AnalyzedFile] | None = None,
) -> PinCoverageReport:
    """Build pin coverage report over architecture block spans."""
    introduction_edges: set[str] = set()
    for edge in registry.import_edges:
        if str(edge.projection_type).lower() == "introduction":
            introduction_edges.add(edge.arch_location)

    analyzed_lookup: dict[str, AnalyzedFile] = {}
    if analyzed is not None:
        for af in analyzed:
            analyzed_lookup[af.path] = af

    items: list[PinCoverageItem] = []
    missing_architecture_files: list[str] = []

    for arch_file in architectural_files:
        file_str = str(arch_file)
        af = analyzed_lookup.get(file_str)
        if af is not None:
            source = af.content
            analysis = af.analysis
        else:
            try:
                source = arch_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            analysis = analyze_source(source, file_str)

        blocks = _coerce_arch_blocks(analysis=analysis)
        if not blocks:
            missing_architecture_files.append(file_str)
            continue

        for block in blocks:
            block_location = f"{file_str}:{block.block_id}"
            in_span_edges = [
                edge
                for edge in registry.import_edges
                if (
                    edge.arch_file_path == file_str
                    and block.line_start <= edge.arch_line <= block.line_end
                )
            ]
            pin_func_ids = sorted({edge.pin_func_id for edge in in_span_edges})
            has_pin = bool(pin_func_ids)

            comments = _comments_in_range(analysis, block.line_start, block.line_end)

            explicit_intro = block.kind == "INTRODUCTION" or block_location in introduction_edges
            is_introduction = explicit_intro
            intro_confidence = block.confidence if is_introduction else 1.0

            items.append(
                PinCoverageItem(
                    arch_location=block_location,
                    arch_file_path=file_str,
                    arch_line=block.line_start,
                    arch_line_end=block.line_end,
                    has_pin=has_pin,
                    pin_func_ids=pin_func_ids,
                    is_introduction=is_introduction,
                    introduction_has_spec=bool(comments),
                    introduction_confidence=intro_confidence,
                )
            )

    total = len(items)
    pinned = sum(1 for item in items if item.has_pin)
    introductions = sum(1 for item in items if item.is_introduction)
    unpinned = total - pinned - introductions

    denominator = total - introductions
    coverage_ratio = (pinned / denominator) if denominator > 0 else 1.0

    return PinCoverageReport(
        total_locations=total,
        pinned_locations=pinned,
        introduction_locations=introductions,
        unpinned_locations=unpinned,
        coverage_ratio=coverage_ratio,
        items=items,
        missing_architecture_files=missing_architecture_files,
    )


def check_pin_coverage(
    registry: PinFunctionRegistry,
    architectural_files: list[Path],
    gate_spec: GateSpec,
    analyzed: list[AnalyzedFile] | None = None,
) -> GateCheckResult:
    """Gate: every architecture block span is covered by a pin or introduction."""
    start = time.monotonic()
    threshold = gate_spec.threshold if gate_spec.threshold > 0 else 1.0

    report = build_pin_coverage_report(
        registry=registry,
        architectural_files=architectural_files,
        analyzed=analyzed,
    )

    duration = (time.monotonic() - start) * 1000
    if report.missing_architecture_files:
        findings = [
            {
                "reason": "missing_architecture_nodes",
                "arch_file_path": file_path,
            }
            for file_path in sorted(report.missing_architecture_files)
        ]
        return GateCheckResult(
            gate_id=GateId.PIN_COVERAGE.value,
            mode=gate_spec.mode.value,
            status=GateStatus.STALE_EVIDENCE,
            score=0.0,
            findings=findings,
            summary=(
                "Architecture-node evidence missing for one or more files; "
                "pin coverage requires pre-built architecture blocks."
            ),
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
                    "reason": "Architecture block span has no pin projection coverage",
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
            f"Pin span coverage: {report.coverage_ratio:.1%} "
            f"({report.pinned_locations} pinned, "
            f"{report.introduction_locations} introductions, "
            f"{report.unpinned_locations} uncovered of {report.total_locations})"
        ),
        duration_ms=duration,
    )
