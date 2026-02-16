"""Core data structures and factory functions for the planning module.

Defines the foundational types used across all planning submodules:
pseudocode comments, insertion points, function info, code files,
insertion plans, reverse plans, and adjacent details.

Also provides ``parse_source`` / ``parse_file`` factory functions for
standalone tooling, plus canonical source-index adapters used by the
workflow integration path.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import (
    RawCommentInfo,
    RawFunctionInfo,
    SourceAnalysis,
    analyze_file_facts,
)


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


# ---------------------------------------------------------------------------
# Comment classification helpers
# ---------------------------------------------------------------------------

# Verbs that indicate a PLAN-kind comment (intent to do something)
_PLAN_VERBS = frozenset(
    {
        "validate",
        "check",
        "apply",
        "send",
        "compute",
        "calculate",
        "build",
        "create",
        "update",
        "delete",
        "remove",
        "insert",
        "fetch",
        "load",
        "save",
        "store",
        "process",
        "transform",
        "convert",
        "parse",
        "extract",
        "filter",
        "merge",
        "sort",
        "iterate",
        "loop",
        "return",
        "raise",
        "emit",
        "dispatch",
        "invoke",
        "call",
        "initialize",
        "configure",
        "register",
        "normalize",
        "aggregate",
        "map",
        "reduce",
        "resolve",
        "determine",
        "ensure",
        "verify",
        "handle",
        "retry",
        "propagate",
        "collect",
        "accumulate",
        "generate",
        "render",
        "format",
        "serialize",
        "deserialize",
        "encode",
        "decode",
        "encrypt",
        "decrypt",
        "compress",
        "decompress",
        "schedule",
        "execute",
        "run",
        "start",
        "stop",
        "reset",
        "flush",
        "sync",
        "wait",
        "poll",
        "listen",
        "subscribe",
        "publish",
        "notify",
        "log",
        "track",
        "measure",
        "allocate",
        "release",
        "open",
        "close",
        "read",
        "write",
        "set",
        "get",
    }
)

# Reverse-translation markers
_REVERSE_MARKERS = frozenset(
    {
        "[reverse-translated]",
        "reverse-translated:",
        "reverse translated:",
        "[reversed]",
    }
)


def _classify_comment(text: str) -> CommentKind:
    """Classify a comment as PLAN, REVERSE, or ANNOTATION.

    Args:
        text: The comment text (stripped of '# ' prefix).

    Returns:
        CommentKind classification.
    """
    lower = text.lower().strip()

    # Check for reverse-translation markers
    for marker in _REVERSE_MARKERS:
        if marker in lower:
            return CommentKind.REVERSE

    # Check for plan verbs at word boundaries
    words = lower.split()
    if words:
        first_word = words[0].rstrip(":")
        if first_word in _PLAN_VERBS:
            return CommentKind.PLAN

    # Check for verbs anywhere in the comment (with weaker signal)
    for word in words:
        clean = word.strip("(),.:;!?")
        if clean in _PLAN_VERBS:
            return CommentKind.PLAN

    return CommentKind.ANNOTATION


# ---------------------------------------------------------------------------
# Conversion helpers: code_analysis types -> planning.models types
# ---------------------------------------------------------------------------


def _parse_qualified_name(qualified_name: str) -> tuple[str | None, str]:
    """Parse a qualified name into (class_name, function_name).

    Args:
        qualified_name: e.g. "ClassName.method_name" or "func_name".

    Returns:
        Tuple of (class_name or None, function_name).
    """
    parts = qualified_name.rsplit(".", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, parts[0]


def _raw_func_to_function_info(
    raw: RawFunctionInfo,
    file_path: str,
    lines: list[str],
) -> FunctionInfo:
    """Convert a RawFunctionInfo to a FunctionInfo.

    Args:
        raw: Function info from code_analysis.
        file_path: Source file path.
        lines: Source lines (0-indexed).

    Returns:
        FunctionInfo for use in the planning module.
    """
    class_name, _ = _parse_qualified_name(raw.qualified_name)

    # Compute body_lines from source text
    body_lines = lines[raw.start_line - 1 : raw.end_line]

    # Compute indent_level from leading spaces at the function's start_line
    if raw.start_line - 1 < len(lines):
        line = lines[raw.start_line - 1]
        indent_level = len(line) - len(line.lstrip())
    else:
        indent_level = 0

    return FunctionInfo(
        name=raw.name,
        file_path=file_path,
        start_line=raw.start_line,
        end_line=raw.end_line,
        indent_level=indent_level,
        parameters=list(raw.args),
        return_annotation=raw.return_annotation,
        docstring=raw.docstring,
        body_lines=body_lines,
        calls=[],  # Adjacency module is being deprecated
        comments=[],  # Filled in by _assign_comments_to_functions
        class_name=class_name,
        decorators=list(raw.decorators),
    )


def _raw_comment_to_pseudocode(
    raw: RawCommentInfo,
    file_path: str,
) -> PseudocodeComment:
    """Convert a RawCommentInfo to a PseudocodeComment.

    Args:
        raw: Comment info from code_analysis.
        file_path: Source file path.

    Returns:
        PseudocodeComment for use in the planning module.
    """
    # Parse enclosing_function for class_name if it contains "."
    function_name: str | None = None
    class_name: str | None = None
    if raw.enclosing_function:
        class_name, function_name = _parse_qualified_name(raw.enclosing_function)

    kind = _classify_comment(raw.text)

    return PseudocodeComment(
        file_path=file_path,
        line_no=raw.line,
        text=raw.text.strip(),
        kind=kind,
        indent_level=raw.col_offset,
        function_name=function_name,
        class_name=class_name,
    )


def _assign_comments_to_functions(
    comments: list[PseudocodeComment],
    functions: list[FunctionInfo],
) -> tuple[list[PseudocodeComment], list[PseudocodeComment]]:
    """Assign comments to their enclosing functions.

    Returns:
        Tuple of (function_comments, top_level_comments).
        Function comments have their function_name and class_name filled in.
    """
    assigned: list[PseudocodeComment] = []
    top_level: list[PseudocodeComment] = []

    for comment in comments:
        found = False
        for func in functions:
            if func.start_line <= comment.line_no <= func.end_line:
                # Re-create with function context (frozen dataclass)
                assigned.append(
                    PseudocodeComment(
                        file_path=comment.file_path,
                        line_no=comment.line_no,
                        text=comment.text,
                        kind=comment.kind,
                        indent_level=comment.indent_level,
                        function_name=func.name,
                        class_name=func.class_name,
                    )
                )
                found = True
                break
        if not found:
            top_level.append(comment)

    return assigned, top_level


# ---------------------------------------------------------------------------
# Factory functions: build CodeFile from source text
# ---------------------------------------------------------------------------


def parse_file(file_path: str) -> CodeFile:
    """Parse a source file into a CodeFile structure.

    Delegates structural analysis to code_analysis.analyze_source().

    Args:
        file_path: Absolute path to the source file.

    Returns:
        CodeFile with functions, comments, imports, and classes.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    path = Path(file_path)
    source = path.read_text(encoding="utf-8")
    return parse_source(source, file_path)


def parse_source(source: str, file_path: str) -> CodeFile:
    """Parse source code into a CodeFile structure.

    Delegates structural analysis to the canonical file-facts provider.

    Args:
        source: Source code string.
        file_path: Path for attribution in results.

    Returns:
        CodeFile with functions, comments, imports, and classes.
    """
    file_path_str = str(file_path)
    source_path = Path(file_path_str)
    workspace_root = source_path.parent if source_path.parent else Path(".")
    file_facts = analyze_file_facts(source, file_path_str, workspace=workspace_root)
    analysis: SourceAnalysis = file_facts.source_analysis
    lines = source.splitlines()
    return _code_file_from_analysis(analysis=analysis, file_path=file_path_str, lines=lines)


def _code_file_from_analysis(
    *,
    analysis: SourceAnalysis,
    file_path: str,
    lines: list[str],
) -> CodeFile:
    """Convert canonical SourceAnalysis into the planning CodeFile view."""

    functions: list[FunctionInfo] = []
    for raw_func in analysis.functions:
        functions.append(_raw_func_to_function_info(raw_func, file_path, lines))

    all_comments: list[PseudocodeComment] = []
    for raw_comment in analysis.comments:
        all_comments.append(_raw_comment_to_pseudocode(raw_comment, file_path))

    assigned_comments, top_level_comments = _assign_comments_to_functions(all_comments, functions)

    comments_by_func: dict[str, list[PseudocodeComment]] = {}
    for comment in assigned_comments:
        key = f"{comment.class_name or ''}.{comment.function_name}"
        comments_by_func.setdefault(key, []).append(comment)

    enriched_functions: list[FunctionInfo] = []
    for func in functions:
        key = f"{func.class_name or ''}.{func.name}"
        func_comments = comments_by_func.get(key, [])
        enriched_functions.append(
            FunctionInfo(
                name=func.name,
                file_path=func.file_path,
                start_line=func.start_line,
                end_line=func.end_line,
                indent_level=func.indent_level,
                parameters=func.parameters,
                return_annotation=func.return_annotation,
                docstring=func.docstring,
                body_lines=func.body_lines,
                calls=func.calls,
                comments=func_comments,
                class_name=func.class_name,
                decorators=func.decorators,
            )
        )

    return CodeFile(
        file_path=file_path,
        functions=enriched_functions,
        top_level_comments=top_level_comments,
        imports=[],  # Deprecated: only used for counting in orchestrator
        classes=[],  # Deprecated: only used for counting in orchestrator
    )


def parse_source_index_entry(entry: dict[str, Any], source_root: Path) -> CodeFile:
    """Build ``CodeFile`` from canonical source-index entry data.

    This is the preferred planning input path: consume evidence already
    produced in the shared bundle instead of reparsing source independently.
    """
    rel_path = str(entry.get("path", "")).strip()
    if not rel_path:
        raise ValueError("source-index entry missing path")

    analysis_block = entry.get("analysis")
    if not isinstance(analysis_block, dict):
        raise TypeError(f"source-index entry for {rel_path} missing analysis payload")

    raw_functions = analysis_block.get("functions", [])
    raw_comments = analysis_block.get("comments", [])
    if not isinstance(raw_functions, list) or not isinstance(raw_comments, list):
        raise TypeError(f"source-index entry for {rel_path} has invalid analysis lists")

    source_path = source_root / rel_path
    try:
        source_text = source_path.read_text(encoding="utf-8")
    except OSError:
        source_text = ""
    lines = source_text.splitlines()

    analysis = SourceAnalysis(
        functions=[
            _dict_to_raw_function_info(item) for item in raw_functions if isinstance(item, dict)
        ],
        comments=[
            _dict_to_raw_comment_info(item) for item in raw_comments if isinstance(item, dict)
        ],
        facets=analysis_block.get("facets", {})
        if isinstance(analysis_block.get("facets", {}), dict)
        else {},
    )
    return _code_file_from_analysis(analysis=analysis, file_path=str(source_path), lines=lines)


def _dict_to_raw_function_info(data: dict[str, Any]) -> RawFunctionInfo:
    """Coerce source-index function dictionary to ``RawFunctionInfo``."""
    decorators_raw = data.get("decorators", [])
    args_raw = data.get("args", [])
    try:
        start_line = int(data.get("start_line", 1) or 1)
    except (TypeError, ValueError):
        start_line = 1
    try:
        end_line = int(data.get("end_line", start_line) or start_line)
    except (TypeError, ValueError):
        end_line = start_line
    if end_line < start_line:
        end_line = start_line
    try:
        body_start_line = int(data.get("body_start_line", start_line) or start_line)
    except (TypeError, ValueError):
        body_start_line = start_line
    try:
        body_line_count = int(data.get("body_line_count", 0) or 0)
    except (TypeError, ValueError):
        body_line_count = 0
    return RawFunctionInfo(
        name=str(data.get("name", "")),
        qualified_name=str(data.get("qualified_name") or data.get("name") or ""),
        start_line=start_line,
        end_line=end_line,
        is_async=bool(data.get("is_async", False)),
        is_stub=bool(data.get("is_stub", False)),
        stub_reason=str(data.get("stub_reason")) if data.get("stub_reason") is not None else None,
        has_docstring=bool(data.get("has_docstring", False)),
        docstring=str(data.get("docstring")) if data.get("docstring") is not None else None,
        decorators=tuple(
            str(item).strip() for item in decorators_raw if isinstance(item, str) and item.strip()
        ),
        args=tuple(
            str(item).strip() for item in args_raw if isinstance(item, str) and item.strip()
        ),
        return_annotation=(
            str(data.get("return_annotation"))
            if data.get("return_annotation") is not None
            else None
        ),
        body_start_line=max(start_line, body_start_line),
        body_line_count=max(body_line_count, 0),
    )


def _dict_to_raw_comment_info(data: dict[str, Any]) -> RawCommentInfo:
    """Coerce source-index comment dictionary to ``RawCommentInfo``."""
    try:
        line = int(data.get("line", 1) or 1)
    except (TypeError, ValueError):
        line = 1
    try:
        col_offset = int(data.get("col_offset", 0) or 0)
    except (TypeError, ValueError):
        col_offset = 0
    enclosing = data.get("enclosing_function")
    return RawCommentInfo(
        line=max(line, 1),
        col_offset=max(col_offset, 0),
        text=str(data.get("text", "")),
        raw=str(data.get("raw", "")),
        enclosing_function=str(enclosing) if enclosing is not None else None,
    )
