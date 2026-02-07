"""Executable gap detection for algorithmic code (design doc Section 7).

Detects gaps in algorithmic code mechanically by scanning for:
- Unimplemented comments (every comment in algorithmic code is a spec element)
- Stub functions (pass, raise NotImplementedError, Ellipsis)
- Runtime error raises used as placeholders

Delegates comment scanning and stub detection to the canonical modules
in ``compliance.detection``.  Runtime error detection is kept in-place
(the canonical ``runtime_detector`` probes at runtime via subprocess,
which is a different approach).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spec_manager.compliance.detection.comment_scanner import (
    CommentGap,
    scan_comments,
)
from spec_manager.compliance.detection.stub_scanner import (
    StubFunction,
    scan_stubs,
)


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


def _stub_to_gap_item(sf: StubFunction) -> GapItem:
    """Convert a canonical StubFunction to the branches GapItem format."""
    return GapItem(
        file=sf.file_path,
        line=sf.line,
        text=f"Stub function: {sf.name} ({sf.stub_type})",
        gap_type="stub_function",
    )


class GapDetector:
    """Detects gaps in algorithmic code mechanically.

    Delegates to canonical scanners in ``compliance.detection`` for
    comment and stub detection.  Runtime error detection is kept
    in-place.
    """

    def find_unimplemented_comments(self, filepath: Path) -> list[GapItem]:
        """Every comment in algorithmic code is an unimplemented spec element.

        Delegates to ``compliance.detection.comment_scanner.scan_comments``.

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

        Delegates to ``compliance.detection.stub_scanner.scan_stubs``.

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

    def detect_runtime_errors(self, filepath: Path) -> list[GapItem]:
        """Find raise RuntimeError used as placeholders.

        Kept in-place -- the canonical ``runtime_detector`` probes at
        runtime via subprocess, which is a different approach.

        Args:
            filepath: Path to the Python source file.

        Returns:
            List of GapItems for each runtime error placeholder found.
        """
        gaps: list[GapItem] = []
        try:
            source = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return gaps

        try:
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError:
            return gaps

        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and node.exc is not None:
                if isinstance(node.exc, ast.Call) and isinstance(node.exc.func, ast.Name):
                    if node.exc.func.id == "RuntimeError":
                        gaps.append(
                            GapItem(
                                file=str(filepath),
                                line=node.lineno,
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
