"""Executable gap inventory builder for algorithmic code.

This module is the canonical source for algorithmic gap inventory records.
It consumes language-agnostic source analysis and emits span+reason gap rows
that downstream graph/promotion stages can consume directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from spec_manager.core.code_analysis import analyze_source
from spec_manager.core.gap import GapEvidence


@dataclass
class CommentGap:
    """A comment identified as unimplemented spec."""

    file_path: str
    line: int
    col_int: int
    text: str
    enclosing_function: str | None
    is_inline: bool


@dataclass
class StubFunction:
    """A function identified as a stub (not implemented)."""

    file_path: str
    line: int
    end_line: int
    name: str
    stub_type: Literal["pass", "ellipsis", "not_implemented"]
    has_docstring: bool
    args: list[str]
    return_annotation: str | None


@dataclass
class GapInventoryItem:
    """Canonical gap inventory item emitted by branch gap detection."""

    kind: Literal["comment_gap", "stub_gap", "runtime_gap"]
    file: str
    description: str
    reason: str
    span: dict[str, int]
    severity: str = "MAJOR"
    required_change_type: str = "behavior_change"
    confidence: float = 1.0
    detector: str = "gap_detection"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to promotion-loop-compatible gap row."""
        normalized_span = _normalize_span(self.span)
        return {
            "kind": self.kind,
            "file": self.file,
            "description": self.description,
            "reason": self.reason,
            "severity": self.severity,
            "required_change_type": self.required_change_type,
            "confidence": max(0.0, min(1.0, float(self.confidence))),
            "detector": self.detector,
            "span": normalized_span,
            "location": {"file": self.file, **normalized_span},
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GapInventoryItem:
        """Deserialize from dictionary."""
        confidence_raw = data.get("confidence", 1.0)
        if confidence_raw is None:
            confidence_raw = 1.0
        return cls(
            kind=str(data.get("kind", "comment_gap")),
            file=str(data.get("file", "")),
            description=str(data.get("description", "")),
            reason=str(data.get("reason", "")),
            span=_normalize_span(data.get("span", {})),
            severity=str(data.get("severity", "MAJOR")),
            required_change_type=str(data.get("required_change_type", "behavior_change")),
            confidence=float(confidence_raw),
            detector=str(data.get("detector", "gap_detection")),
            metadata=data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {},
        )


EXCLUDED_PREFIXES: tuple[str, ...] = (
    "type: ignore",
    "noqa",
    "pragma",
    "fmt:",
    "pylint:",
    "mypy:",
    "pyright:",
    "ruff:",
    "isort:",
    "!",
    "-*- coding",
)

_RUNTIME_ERROR_RE = re.compile(r"^\s*raise\s+RuntimeError\s*\(", re.MULTILINE)

_STUB_TYPE_LABELS: dict[str, str] = {
    "pass": "pass",
    "ellipsis": "Ellipsis",
    "not_implemented": "NotImplementedError",
}


def _normalize_span(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    span: dict[str, int] = {}
    start_line = raw.get("start_line")
    end_line = raw.get("end_line")
    start_col = raw.get("start_col")
    end_col = raw.get("end_col")
    if isinstance(start_line, int) and start_line > 0:
        span["start_line"] = start_line
    if isinstance(end_line, int) and end_line > 0:
        span["end_line"] = end_line
    elif "start_line" in span:
        span["end_line"] = span["start_line"]
    if isinstance(start_col, int) and start_col >= 0:
        span["start_col"] = start_col
    if isinstance(end_col, int) and end_col >= 0:
        span["end_col"] = end_col
    return span


def _map_stub_reason(reason: str | None) -> Literal["pass", "ellipsis", "not_implemented"]:
    """Map code-analysis ``stub_reason`` into canonical stub labels."""
    if reason is None:
        return "pass"
    lower = reason.lower()
    if "ellipsis" in lower or reason == "...":
        return "ellipsis"
    if "notimplemented" in lower.replace(" ", "").replace("_", ""):
        return "not_implemented"
    return "pass"


def scan_comments(filepath: Path) -> list[CommentGap]:
    """Scan one source file for unresolved spec comments."""
    source = filepath.read_text(encoding="utf-8")
    analysis = analyze_source(source, str(filepath))

    source_lines = source.splitlines()
    gaps: list[CommentGap] = []

    for comment in analysis.comments:
        if comment.raw.startswith("#!") and comment.line <= 2:
            continue

        stripped = comment.text.strip()
        if not stripped:
            continue

        if any(stripped.lower().startswith(prefix.lower()) for prefix in EXCLUDED_PREFIXES):
            continue

        is_inline = False
        if comment.line <= len(source_lines):
            line_text = source_lines[comment.line - 1]
            before_comment = line_text[: comment.col_offset].strip()
            if before_comment:
                is_inline = True

        gaps.append(
            CommentGap(
                file_path=str(filepath),
                line=comment.line,
                col_int=comment.col_offset,
                text=stripped,
                enclosing_function=comment.enclosing_function,
                is_inline=is_inline,
            )
        )

    return gaps


def scan_stubs(filepath: Path) -> list[StubFunction]:
    """Scan one source file for unimplemented function stubs."""
    try:
        source = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    analysis = analyze_source(source, str(filepath))

    stubs: list[StubFunction] = []
    for func in analysis.functions:
        if not func.is_stub:
            continue
        stubs.append(
            StubFunction(
                file_path=str(filepath),
                line=func.start_line,
                end_line=func.end_line,
                name=func.qualified_name or func.name,
                stub_type=_map_stub_reason(func.stub_reason),
                has_docstring=func.has_docstring,
                args=list(func.args),
                return_annotation=func.return_annotation,
            )
        )
    return stubs


def comments_to_gap_evidence(comments: list[CommentGap]) -> list[GapEvidence]:
    """Project comment gaps into canonical evidence entries."""
    evidence: list[GapEvidence] = []
    for comment in comments:
        details: dict[str, Any] = {
            "enclosing_function": comment.enclosing_function,
            "is_inline": comment.is_inline,
            "derived_artifact_target": comment.file_path,
            "source": [comment.file_path],
            "gap_kind": "comment_gap",
            "reason": "unimplemented_comment",
            "span": {
                "start_line": comment.line,
                "end_line": comment.line,
                "start_col": comment.col_int,
            },
        }
        evidence.append(
            GapEvidence(
                invariant_family="executable_comment",
                description=comment.text,
                details=details,
                confidence=1.0,
                location=f"{comment.file_path}:{comment.line}",
                detector="gap_detection",
            )
        )
    return evidence


def stubs_to_gap_evidence(stubs: list[StubFunction]) -> list[GapEvidence]:
    """Project stub gaps into canonical evidence entries."""
    evidence: list[GapEvidence] = []
    for stub in stubs:
        details: dict[str, Any] = {
            "stub_type": stub.stub_type,
            "args": stub.args,
            "return_annotation": stub.return_annotation,
            "has_docstring": stub.has_docstring,
            "derived_artifact_target": stub.file_path,
            "source": [stub.file_path],
            "gap_kind": "stub_gap",
            "reason": "stub_function",
            "span": {
                "start_line": stub.line,
                "end_line": stub.end_line,
            },
        }
        label = _STUB_TYPE_LABELS.get(stub.stub_type, stub.stub_type)
        evidence.append(
            GapEvidence(
                invariant_family="executable_stub",
                description=f"Stub function: {stub.name} ({label})",
                details=details,
                confidence=1.0,
                location=f"{stub.file_path}:{stub.line}-{stub.end_line}",
                detector="gap_detection",
            )
        )
    return evidence


def build_gap_inventory_for_file(filepath: Path) -> list[GapInventoryItem]:
    """Build canonical gap inventory rows for one source file."""
    items: list[GapInventoryItem] = []

    try:
        comments = scan_comments(filepath)
    except (OSError, UnicodeDecodeError):
        comments = []
    for comment in comments:
        items.append(
            GapInventoryItem(
                kind="comment_gap",
                file=comment.file_path,
                description=comment.text,
                reason="unimplemented_comment",
                severity="MAJOR",
                required_change_type="behavior_change",
                span={
                    "start_line": comment.line,
                    "end_line": comment.line,
                    "start_col": comment.col_int,
                },
                metadata={
                    "enclosing_function": comment.enclosing_function,
                    "is_inline": comment.is_inline,
                },
            )
        )

    stubs = scan_stubs(filepath)
    for stub in stubs:
        label = _STUB_TYPE_LABELS.get(stub.stub_type, stub.stub_type)
        items.append(
            GapInventoryItem(
                kind="stub_gap",
                file=stub.file_path,
                description=f"Stub function: {stub.name} ({label})",
                reason="stub_function",
                severity="MAJOR",
                required_change_type="behavior_change",
                span={"start_line": stub.line, "end_line": stub.end_line},
                metadata={
                    "stub_type": stub.stub_type,
                    "args": list(stub.args),
                    "return_annotation": stub.return_annotation,
                    "has_docstring": stub.has_docstring,
                },
            )
        )

    try:
        source = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        source = ""

    if source:
        for match in _RUNTIME_ERROR_RE.finditer(source):
            line_no = source[: match.start()].count("\n") + 1
            items.append(
                GapInventoryItem(
                    kind="runtime_gap",
                    file=str(filepath),
                    description="RuntimeError placeholder",
                    reason="runtime_placeholder",
                    severity="BLOCKER",
                    required_change_type="behavior_change",
                    span={"start_line": line_no, "end_line": line_no},
                )
            )

    return items


def build_gap_inventory(algorithmic_dir: Path) -> list[dict[str, Any]]:
    """Build canonical gap inventory for an algorithmic branch directory."""
    detector = GapDetector()
    return [item.to_dict() for item in detector.scan_branch(algorithmic_dir)]


class GapDetector:
    """Branch-level gap inventory detector for algorithmic code."""

    def find_unimplemented_comments(self, filepath: Path) -> list[GapInventoryItem]:
        """Project unresolved comments in one file to inventory rows."""
        return [
            item for item in build_gap_inventory_for_file(filepath) if item.kind == "comment_gap"
        ]

    def detect_stubs(self, filepath: Path) -> list[GapInventoryItem]:
        """Project stub functions in one file to inventory rows."""
        return [item for item in build_gap_inventory_for_file(filepath) if item.kind == "stub_gap"]

    def detect_runtime_errors(self, filepath: Path) -> list[GapInventoryItem]:
        """Project runtime placeholder raises in one file to inventory rows."""
        return [
            item for item in build_gap_inventory_for_file(filepath) if item.kind == "runtime_gap"
        ]

    def scan_branch(self, algorithmic_dir: Path) -> list[GapInventoryItem]:
        """Scan all source files under an algorithmic directory."""
        from spec_manager.core.language import is_package_marker, source_rglob

        if not algorithmic_dir.exists():
            return []

        items: list[GapInventoryItem] = []
        for source_file in source_rglob(algorithmic_dir):
            if is_package_marker(source_file.name):
                continue
            items.extend(build_gap_inventory_for_file(source_file))
        return items


__all__ = [
    "EXCLUDED_PREFIXES",
    "CommentGap",
    "GapDetector",
    "GapInventoryItem",
    "StubFunction",
    "build_gap_inventory",
    "build_gap_inventory_for_file",
    "comments_to_gap_evidence",
    "scan_comments",
    "scan_stubs",
    "stubs_to_gap_evidence",
]
