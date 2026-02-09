"""Comment scanner for executable gap detection.

Uses LLM-based code analysis to extract comments as unimplemented spec
elements.  In algorithmic code, every comment IS spec -- a description
of behavior that should be implemented, not described.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
