"""Core data structures for the planning module.

Defines the foundational types used across all planning submodules:
pseudocode comments, insertion points, function info, code files,
insertion plans, reverse plans, and adjacent details.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CommentKind(str, Enum):
    """Classification of a pseudocode comment."""

    PLAN = "plan"  # New plan comment (unimplemented)
    REVERSE = "reverse"  # Reverse-translated from existing code
    ANNOTATION = "annotation"  # Non-spec comment (docstring, TODO, etc.)


@dataclass(frozen=True)
class PseudocodeComment:
    """A single pseudocode comment in algorithmic code.

    Each comment is a micro-plan: one logical step, single responsibility.
    """

    file_path: str  # Absolute path to source file
    line_no: int  # 1-based line number
    text: str  # Comment text (stripped of '# ')
    kind: CommentKind  # Classification
    indent_level: int  # Number of leading spaces
    function_name: str | None  # Enclosing function name, if any
    class_name: str | None  # Enclosing class name, if any


@dataclass(frozen=True)
class InsertionPoint:
    """A location in code where a new pseudocode comment can be inserted.

    Context-aware: knows what comes before and after.
    """

    file_path: str
    line_no: int  # Line number AFTER which to insert
    indent_level: int
    function_name: str | None
    preceding_code: str  # The code line before this point
    following_code: str  # The code line after this point
    rationale: str  # Why this is a valid insertion point


@dataclass(frozen=True)
class FunctionInfo:
    """Extracted information about a function in the code."""

    name: str
    file_path: str
    start_line: int  # 1-based
    end_line: int  # 1-based, inclusive
    indent_level: int
    parameters: list[str]
    return_annotation: str | None
    docstring: str | None
    body_lines: list[str]  # Raw body lines
    calls: list[str]  # Function names called within this function
    comments: list[PseudocodeComment]  # Existing comments in the body
    class_name: str | None  # Enclosing class, if any
    decorators: list[str]


@dataclass
class CodeFile:
    """Parsed representation of an algorithmic code file."""

    file_path: str
    functions: list[FunctionInfo]
    top_level_comments: list[PseudocodeComment]
    imports: list[str]
    classes: list[str]


@dataclass
class InsertionPlan:
    """A plan to insert pseudocode comments into code files."""

    file_path: str
    insertions: list[tuple[InsertionPoint, str]]  # (where, comment_text)
    source_intention: str  # The high-level intention being decomposed
    evidence_refs: list[str]  # References to spec evidence used


@dataclass
class ReversePlan:
    """A plan to reverse-translate code back to pseudocode comments."""

    file_path: str
    function_name: str
    start_line: int
    end_line: int
    generated_comments: list[PseudocodeComment]
    original_code: str  # The code that was reverse-translated


@dataclass
class AdjacentDetail:
    """An adjacent detail discovered via call graph or store analysis."""

    source_function: str  # The function being planned
    related_function: str  # The adjacent function
    relationship: str  # "calls", "called_by", "shared_store", "shared_event"
    store_or_event: str | None  # Name of shared store/event if applicable
    has_test_coverage: bool  # Whether the related function has tests
    needs_plan: bool  # Whether this needs its own planning pass
