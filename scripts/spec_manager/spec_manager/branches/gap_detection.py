"""Executable gap detection for algorithmic code (design doc Section 7).

Detects gaps in algorithmic code mechanically by scanning for:
- Unimplemented comments (every comment in algorithmic code is a spec element)
- Stub functions (pass, raise NotImplementedError, Ellipsis)
- Runtime error raises used as placeholders

Comment scanning and stub detection are implemented here using
``analyze_source`` from ``spec_manager.core.code_analysis``.
Runtime error detection uses text-based pattern matching.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from spec_manager.core.code_analysis import analyze_source
from spec_manager.core.gap import GapEvidence

# ---------------------------------------------------------------------------
# Comment scanning
# ---------------------------------------------------------------------------


@dataclass
class CommentGap:
    """A comment identified as unimplemented spec."""

    file_path: str
    line: int
    col_int: int
    text: str
    enclosing_function: str | None
    is_inline: bool


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


def scan_comments(filepath: Path) -> list[CommentGap]:
    """Scan a source file and return all spec comments.

    Delegates structural analysis to ``analyze_source`` (language-agnostic).
    Filters out excluded prefixes (type: ignore, noqa, pragma, etc.).

    Args:
        filepath: Path to the source file.

    Returns:
        List of CommentGap for each spec comment found.
    """
    source = filepath.read_text(encoding="utf-8")
    analysis = analyze_source(source, str(filepath))

    source_lines = source.splitlines()
    gaps: list[CommentGap] = []

    for comment in analysis.comments:
        # Check if it is a shebang
        if comment.raw.startswith("#!") and comment.line <= 2:
            continue

        stripped = comment.text

        # Check excluded prefixes
        skip = False
        for prefix in EXCLUDED_PREFIXES:
            if stripped.lower().startswith(prefix.lower()):
                skip = True
                break
        if skip:
            continue

        # Skip empty comments
        if not stripped:
            continue

        # Determine if inline (code before the comment on the same line)
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


def comments_to_gap_evidence(comments: list[CommentGap]) -> list[GapEvidence]:
    """Convert CommentGap list to GapEvidence for gap synthesis.

    Each CommentGap becomes a GapEvidence with:
        invariant_family = "executable_comment"
        detector = "comment_scanner"
        location = "{file_path}:{line}"
        description = comment text
        details = {"enclosing_function": ..., "is_inline": ...}

    Args:
        comments: List of CommentGap from scan_comments.

    Returns:
        List of GapEvidence objects.
    """
    evidence: list[GapEvidence] = []
    for comment in comments:
        details: dict[str, Any] = {
            "enclosing_function": comment.enclosing_function,
            "is_inline": comment.is_inline,
        }
        evidence.append(
            GapEvidence(
                invariant_family="executable_comment",
                description=comment.text,
                details=details,
                confidence=1.0,
                location=f"{comment.file_path}:{comment.line}",
                detector="comment_scanner",
            )
        )
    return evidence


# ---------------------------------------------------------------------------
# Stub scanning
# ---------------------------------------------------------------------------


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


def _map_stub_reason(reason: str | None) -> Literal["pass", "ellipsis", "not_implemented"]:
    """Map a ``stub_reason`` from code analysis to a stub_type literal.

    The analyzer may return various reason strings depending on the backend
    (LLM or AST test double).  This function normalises them into the three
    canonical categories used by ``StubFunction.stub_type``.
    """
    if reason is None:
        return "pass"
    lower = reason.lower()
    if "ellipsis" in lower or reason == "...":
        return "ellipsis"
    if "notimplemented" in lower.replace(" ", "").replace("_", ""):
        return "not_implemented"
    # "pass", "placeholder", or any other unknown reason
    return "pass"


def scan_stubs(filepath: Path) -> list[StubFunction]:
    """Scan a source file and return all stub functions.

    Uses ``analyze_source()`` from ``spec_manager.core.code_analysis`` to
    perform language-agnostic structural analysis, then filters for functions
    whose ``is_stub`` flag is ``True``.

    Handles both top-level functions and methods within classes.
    Qualified names use ``ClassName.method_name`` format.

    Args:
        filepath: Path to the source file.

    Returns:
        List of StubFunction for each stub found.
    """
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
                name=func.qualified_name,
                stub_type=_map_stub_reason(func.stub_reason),
                has_docstring=func.has_docstring,
                args=list(func.args),
                return_annotation=func.return_annotation,
            )
        )
    return stubs


def stubs_to_gap_evidence(stubs: list[StubFunction]) -> list[GapEvidence]:
    """Convert StubFunction list to GapEvidence for gap synthesis.

    Each StubFunction becomes a GapEvidence with:
        invariant_family = "executable_stub"
        detector = "stub_scanner"
        location = "{file_path}:{line}-{end_line}"
        description = "Stub function: {name} ({stub_type})"
        details = {"stub_type": ..., "args": ..., "return_annotation": ...}

    Args:
        stubs: List of StubFunction from scan_stubs.

    Returns:
        List of GapEvidence objects.
    """
    evidence: list[GapEvidence] = []
    for stub in stubs:
        details: dict[str, Any] = {
            "stub_type": stub.stub_type,
            "args": stub.args,
            "return_annotation": stub.return_annotation,
            "has_docstring": stub.has_docstring,
        }
        evidence.append(
            GapEvidence(
                invariant_family="executable_stub",
                description=f"Stub function: {stub.name} ({stub.stub_type})",
                details=details,
                confidence=1.0,
                location=f"{stub.file_path}:{stub.line}-{stub.end_line}",
                detector="stub_scanner",
            )
        )
    return evidence


# ---------------------------------------------------------------------------
# GapItem (branches-layer adapter)
# ---------------------------------------------------------------------------


@dataclass
class GapItem:
    """A detected gap in algorithmic code (design doc Section 7)."""

    file: str
    line: int
    text: str
    gap_type: str  # "unimplemented_comment", "stub_function", "runtime_error"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "file": self.file,
            "line": self.line,
            "text": self.text,
            "gap_type": self.gap_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GapItem:
        """Deserialize from dictionary."""
        return cls(
            file=data["file"],
            line=data["line"],
            text=data["text"],
            gap_type=data["gap_type"],
        )


# ---- Adapter helpers ----


def _comment_gap_to_gap_item(cg: CommentGap) -> GapItem:
    """Convert a canonical CommentGap to the branches GapItem format."""
    return GapItem(
        file=cg.file_path,
        line=cg.line,
        text=cg.text,
        gap_type="unimplemented_comment",
    )


_STUB_TYPE_LABELS: dict[str, str] = {
    "pass": "pass",
    "ellipsis": "Ellipsis",
    "not_implemented": "NotImplementedError",
}


def _stub_to_gap_item(sf: StubFunction) -> GapItem:
    """Convert a canonical StubFunction to the branches GapItem format."""
    if sf.has_docstring and sf.stub_type == "pass":
        label = "docstring only"
    else:
        label = _STUB_TYPE_LABELS.get(sf.stub_type, sf.stub_type)
    return GapItem(
        file=sf.file_path,
        line=sf.line,
        text=f"Stub function: {sf.name} ({label})",
        gap_type="stub_function",
    )


class GapDetector:
    """Detects gaps in algorithmic code mechanically.

    Comment and stub detection use ``analyze_source`` from
    ``spec_manager.core.code_analysis``.  Runtime error detection is kept
    in-place.
    """

    def find_unimplemented_comments(self, filepath: Path) -> list[GapItem]:
        """Every comment in algorithmic code is an unimplemented spec element.

        Args:
            filepath: Path to the Python source file.

        Returns:
            List of GapItems for each comment found.
        """
        try:
            canonical_gaps = scan_comments(filepath)
        except (OSError, UnicodeDecodeError):
            return []
        return [_comment_gap_to_gap_item(cg) for cg in canonical_gaps]

    def detect_stubs(self, filepath: Path) -> list[GapItem]:
        """Functions containing only pass, raise NotImplementedError, or Ellipsis.

        Args:
            filepath: Path to the Python source file.

        Returns:
            List of GapItems for each stub function found.
        """
        try:
            canonical_stubs = scan_stubs(filepath)
        except (OSError, UnicodeDecodeError, SyntaxError):
            return []
        return [_stub_to_gap_item(sf) for sf in canonical_stubs]

    # Pattern matches "raise RuntimeError(" at any indentation level
    _RUNTIME_ERROR_RE = re.compile(r"^\s*raise\s+RuntimeError\s*\(", re.MULTILINE)

    def detect_runtime_errors(self, filepath: Path) -> list[GapItem]:
        """Find raise RuntimeError used as placeholders.

        Uses text-based pattern matching (language-agnostic for Python-like
        raise syntax).  The canonical ``runtime_detector`` probes at
        runtime via subprocess, which is a different approach.

        Args:
            filepath: Path to the source file.

        Returns:
            List of GapItems for each runtime error placeholder found.
        """
        gaps: list[GapItem] = []
        try:
            source = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return gaps

        for match in self._RUNTIME_ERROR_RE.finditer(source):
            line_no = source[: match.start()].count("\n") + 1
            gaps.append(
                GapItem(
                    file=str(filepath),
                    line=line_no,
                    text="RuntimeError placeholder",
                    gap_type="runtime_error",
                )
            )

        return gaps

    def scan_branch(self, algorithmic_dir: Path) -> list[GapItem]:
        """Scan the entire algorithmic branch for gaps.

        Walks all ``.py`` files under the given directory and aggregates
        results from all detection methods.

        Args:
            algorithmic_dir: Root directory of the algorithmic branch.

        Returns:
            All detected gap items.
        """
        gaps: list[GapItem] = []
        if not algorithmic_dir.exists():
            return gaps

        for py_file in sorted(algorithmic_dir.rglob("*.py")):
            if py_file.name == "__init__.py":
                continue
            gaps.extend(self.find_unimplemented_comments(py_file))
            gaps.extend(self.detect_stubs(py_file))
            gaps.extend(self.detect_runtime_errors(py_file))

        return gaps
