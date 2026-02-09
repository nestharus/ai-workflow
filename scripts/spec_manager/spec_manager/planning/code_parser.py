"""Code parser using spec_manager.core.code_analysis for structure extraction.

Delegates all structural analysis to the language-agnostic code_analysis
module (LLM-based in production, AST test double in tests).
"""

from __future__ import annotations

from pathlib import Path

from spec_manager.core.code_analysis import (
    RawCommentInfo,
    RawFunctionInfo,
    SourceAnalysis,
    analyze_source,
)
from spec_manager.planning.models import (
    CodeFile,
    CommentKind,
    FunctionInfo,
    InsertionPoint,
    PseudocodeComment,
)

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
# Helpers: convert code_analysis types to planning.models types
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

    Delegates structural analysis to code_analysis.analyze_source().

    Args:
        source: Source code string.
        file_path: Path for attribution in results.

    Returns:
        CodeFile with functions, comments, imports, and classes.
    """
    analysis: SourceAnalysis = analyze_source(source, file_path)
    lines = source.splitlines()

    # Convert RawFunctionInfo -> FunctionInfo
    functions: list[FunctionInfo] = []
    for raw_func in analysis.functions:
        functions.append(_raw_func_to_function_info(raw_func, file_path, lines))

    # Convert RawCommentInfo -> PseudocodeComment
    all_comments: list[PseudocodeComment] = []
    for raw_comment in analysis.comments:
        all_comments.append(_raw_comment_to_pseudocode(raw_comment, file_path))

    # Assign comments to functions
    assigned_comments, top_level_comments = _assign_comments_to_functions(all_comments, functions)

    # Group assigned comments by function and rebuild FunctionInfo with comments
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


def find_insertion_points(code_file: CodeFile, function_name: str) -> list[InsertionPoint]:
    """Find valid insertion points within a function.

    Insertion points are between statements, respecting control flow.
    Each point knows its context (what comes before/after).

    Args:
        code_file: Parsed code file.
        function_name: Name of the target function.

    Returns:
        List of InsertionPoint objects.

    Raises:
        ValueError: If function_name is not found in the code file.
    """
    func = _find_function(code_file, function_name)
    if func is None:
        raise ValueError(f"Function '{function_name}' not found in {code_file.file_path}")

    source = Path(code_file.file_path).read_text(encoding="utf-8")
    return _find_insertion_points_from_source(source, func, code_file.file_path)


def _find_insertion_points_from_source(
    source: str,
    func: FunctionInfo,
    file_path: str,
) -> list[InsertionPoint]:
    """Find insertion points within a function from source text.

    Uses analyze_source() for function metadata and line-based heuristics
    for statement boundary detection.  Language-agnostic.

    Args:
        source: Full file source.
        func: Function info.
        file_path: File path for attribution.

    Returns:
        List of InsertionPoint objects.
    """
    lines = source.splitlines()
    points: list[InsertionPoint] = []

    # Use analyze_source to locate the function
    analysis = analyze_source(source, file_path)
    raw_func = None
    for rf in analysis.functions:
        if rf.name == func.name:
            raw_func = rf
            break
    if raw_func is None:
        return points

    body_indent = func.indent_level + 4  # Standard Python indentation

    # Determine body start: body_start_line from analysis, accounting for docstring
    body_start = raw_func.body_start_line
    body_end = raw_func.end_line

    if body_start <= 0 or body_end <= 0:
        return points

    # Find top-level statement boundaries within the function body.
    # A top-level statement starts at exactly body_indent spaces (not deeper).
    # We skip docstring lines (the first string literal) if present.
    stmt_ranges = _find_statement_ranges(
        lines, body_start, body_end, body_indent, raw_func.has_docstring
    )

    if not stmt_ranges:
        return points

    # --- Start of function body (after docstring or def line) ---
    first_range = stmt_ranges[0]
    # insert_after: the line before the first real statement
    insert_after_line = first_range[0] - 1
    if insert_after_line < 1:
        insert_after_line = raw_func.start_line

    preceding = lines[insert_after_line - 1] if insert_after_line <= len(lines) else ""
    following = lines[first_range[0] - 1] if first_range[0] <= len(lines) else ""

    points.append(
        InsertionPoint(
            file_path=file_path,
            line_no=insert_after_line,
            indent_level=body_indent,
            function_name=func.name,
            preceding_code=preceding.strip(),
            following_code=following.strip(),
            rationale="Start of function body",
        )
    )

    # --- Between statements ---
    for i in range(len(stmt_ranges) - 1):
        current_end = stmt_ranges[i][1]
        next_start = stmt_ranges[i + 1][0]

        preceding = lines[current_end - 1] if current_end <= len(lines) else ""
        following = lines[next_start - 1] if next_start <= len(lines) else ""

        points.append(
            InsertionPoint(
                file_path=file_path,
                line_no=current_end,
                indent_level=body_indent,
                function_name=func.name,
                preceding_code=preceding.strip(),
                following_code=following.strip(),
                rationale="Between statements",
            )
        )

    # --- End of function body ---
    last_end = stmt_ranges[-1][1]
    preceding = lines[last_end - 1] if last_end <= len(lines) else ""

    points.append(
        InsertionPoint(
            file_path=file_path,
            line_no=last_end,
            indent_level=body_indent,
            function_name=func.name,
            preceding_code=preceding.strip(),
            following_code="",
            rationale="End of function body",
        )
    )

    return points


def _find_statement_ranges(
    lines: list[str],
    body_start: int,
    body_end: int,
    body_indent: int,
    has_docstring: bool,
) -> list[tuple[int, int]]:
    """Identify top-level statement ranges within a function body.

    A statement starts on a line whose indentation equals *body_indent*
    (the function body indent level).  Continuation lines (deeper indent,
    blank lines, or lines inside multi-line strings) are folded into the
    preceding statement.

    Args:
        lines: All source lines (0-indexed list).
        body_start: 1-based line where the body begins.
        body_end: 1-based last line of the function.
        body_indent: Expected indent level for top-level body statements.
        has_docstring: Whether to skip a leading docstring.

    Returns:
        List of (start_line, end_line) tuples, 1-based inclusive.
    """
    ranges: list[tuple[int, int]] = []
    current_start: int | None = None
    current_end: int | None = None

    # Track whether we're inside a docstring to skip
    skip_until_line = 0
    if has_docstring:
        # Find the end of the docstring starting at body_start
        skip_until_line = _find_docstring_end(lines, body_start)

    for line_no in range(body_start, body_end + 1):
        # Skip docstring lines
        if line_no <= skip_until_line:
            continue

        idx = line_no - 1
        if idx >= len(lines):
            break

        line = lines[idx]
        stripped = line.rstrip()

        # Skip blank lines
        if not stripped:
            continue

        # Calculate indent
        indent = len(line) - len(line.lstrip())

        if indent == body_indent:
            # This is a new top-level statement
            if current_start is not None:
                ranges.append((current_start, current_end or current_start))
            current_start = line_no
            current_end = line_no
        elif current_start is not None:
            # Continuation of current statement (deeper indent or comment)
            current_end = line_no

    # Close final statement
    if current_start is not None:
        ranges.append((current_start, current_end or current_start))

    return ranges


def _find_docstring_end(lines: list[str], start: int) -> int:
    """Find the last line of a docstring starting at *start* (1-based).

    Handles single-line and multi-line triple-quoted strings.

    Returns:
        1-based line number of the docstring's closing line,
        or *start* if no docstring is found.
    """
    idx = start - 1
    if idx >= len(lines):
        return start

    line = lines[idx].strip()

    # Check for triple-quote opening
    for quote in ('"""', "'''"):
        if quote in line:
            # Single-line docstring: """text""" on one line
            if line.count(quote) >= 2:
                return start
            # Multi-line: scan forward for closing triple-quote
            for j in range(start, len(lines)):
                if quote in lines[j].strip() and j > idx:
                    return j + 1  # 1-based
            return start

    return start


def _find_function(code_file: CodeFile, function_name: str) -> FunctionInfo | None:
    """Find a function by name in a CodeFile.

    Args:
        code_file: Parsed code file.
        function_name: Name of the function to find.

    Returns:
        FunctionInfo or None if not found.
    """
    for func in code_file.functions:
        if func.name == function_name:
            return func
    return None


def extract_comments(file_path: str) -> list[PseudocodeComment]:
    """Extract all pseudocode comments from a file.

    Delegates to code_analysis.analyze_source() for comment extraction.
    Classifies each as PLAN, REVERSE, or ANNOTATION based on heuristics.

    Args:
        file_path: Absolute path to the source file.

    Returns:
        List of PseudocodeComment objects.
    """
    path = Path(file_path)
    source = path.read_text(encoding="utf-8")
    analysis = analyze_source(source, file_path)

    comments: list[PseudocodeComment] = []
    for raw_comment in analysis.comments:
        comments.append(_raw_comment_to_pseudocode(raw_comment, file_path))
    return comments


def extract_function_calls(function: FunctionInfo) -> list[str]:
    """Extract all function calls within a function body.

    Returns the calls list from the FunctionInfo (deduplicated).
    Note: calls are currently set to [] as the adjacency module is
    being deprecated.

    Args:
        function: FunctionInfo to analyze.

    Returns:
        List of function names called (deduplicated).
    """
    return list(dict.fromkeys(function.calls))


def detect_stubs(code_file: CodeFile) -> list[FunctionInfo]:
    """Find stub functions (pass, raise NotImplementedError, Ellipsis body).

    Uses the is_stub flag from code_analysis.analyze_source() results.

    Args:
        code_file: Parsed code file.

    Returns:
        List of FunctionInfo objects that are stubs.
    """
    source = Path(code_file.file_path).read_text(encoding="utf-8")
    analysis = analyze_source(source, code_file.file_path)

    stub_names: set[str] = set()
    for raw_func in analysis.functions:
        if raw_func.is_stub:
            stub_names.add(raw_func.name)

    return [func for func in code_file.functions if func.name in stub_names]


def detect_stubs_from_source(source: str, file_path: str) -> list[FunctionInfo]:
    """Find stub functions from source code string.

    Uses the is_stub flag from code_analysis.analyze_source() results.

    Args:
        source: Source code.
        file_path: Path for attribution.

    Returns:
        List of FunctionInfo objects that are stubs.
    """
    code_file = parse_source(source, file_path)
    analysis = analyze_source(source, file_path)

    stub_names: set[str] = set()
    for raw_func in analysis.functions:
        if raw_func.is_stub:
            stub_names.add(raw_func.name)

    return [func for func in code_file.functions if func.name in stub_names]
