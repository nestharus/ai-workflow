"""Comment scanner for executable gap detection.

Tokenizes Python files and extracts comments as unimplemented spec elements.
In algorithmic code, every comment IS spec -- a description of behavior
that should be implemented, not described.
"""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def _build_function_line_map(source: str) -> list[tuple[int, int, str]]:
    """Build a mapping from line ranges to enclosing function names.

    Returns a sorted list of (start_line, end_line, qualified_name) tuples.
    Handles both top-level functions and methods within classes.
    Nested functions get qualified names like "outer.inner".
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    ranges: list[tuple[int, int, str]] = []

    def _walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                class_prefix = f"{prefix}{child.name}." if not prefix else f"{prefix}{child.name}."
                if not prefix:
                    class_prefix = f"{child.name}."
                _walk(child, class_prefix)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = f"{prefix}{child.name}"
                end_line = child.end_lineno or child.lineno
                ranges.append((child.lineno, end_line, qualified))
                _walk(child, f"{qualified}.")

    _walk(tree, "")
    ranges.sort(key=lambda r: (r[0], -r[1]))
    return ranges


def _find_enclosing_function(
    line: int,
    function_ranges: list[tuple[int, int, str]],
) -> str | None:
    """Find the most specific (innermost) enclosing function for a given line."""
    best: str | None = None
    best_size = float("inf")
    for start, end, name in function_ranges:
        if start <= line <= end:
            size = end - start
            if size < best_size:
                best_size = size
                best = name
    return best


def scan_comments(filepath: Path) -> list[CommentGap]:
    """Tokenize a Python file and return all spec comments.

    Uses tokenize.generate_tokens to find COMMENT tokens.
    Filters out excluded prefixes (type: ignore, noqa, pragma, etc.).
    Resolves enclosing function via ast.parse + line range lookup.

    Args:
        filepath: Path to the Python file.

    Returns:
        List of CommentGap for each spec comment found.
    """
    source = filepath.read_text(encoding="utf-8")
    function_ranges = _build_function_line_map(source)

    gaps: list[CommentGap] = []
    readline = io.StringIO(source).readline

    try:
        tokens = list(tokenize.generate_tokens(readline))
    except tokenize.TokenError:
        return gaps

    source_lines = source.splitlines()

    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue

        comment_text = tok.string
        line_no = tok.start[0]
        col = tok.start[1]

        # Strip the leading '#' and optional space
        stripped = comment_text.lstrip("#").strip()

        # Check if it is a shebang
        if comment_text.startswith("#!") and line_no <= 2:
            continue

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
        if line_no <= len(source_lines):
            line_text = source_lines[line_no - 1]
            before_comment = line_text[:col].strip()
            if before_comment:
                is_inline = True

        enclosing = _find_enclosing_function(line_no, function_ranges)

        gaps.append(
            CommentGap(
                file_path=str(filepath),
                line=line_no,
                col_int=col,
                text=stripped,
                enclosing_function=enclosing,
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
