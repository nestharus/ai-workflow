"""Edit-in-place engine: treats Python source files as living specifications.

Comments are unimplemented spec elements, stubs are incomplete implementations,
and "no comments in production" is the completeness invariant. This module
provides mechanical, deterministic source analysis using Python's ``ast`` and
``tokenize`` modules.

Primary entry points:
    - ``analyze_file(filepath)`` -> ``FileTranslationState``
    - ``analyze_project(root)`` -> ``ProjectTranslationState``
    - ``find_gaps(state)`` -> list of ``SpecComment`` gaps
    - ``format_gap_report(state)`` -> human-readable report string
"""

from __future__ import annotations

import ast
import enum
import hashlib
import io
import re
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# =============================================================================
# Plan 1: Core Data Structures
# =============================================================================


class TranslationState(enum.Enum):
    """Lifecycle state of a spec element (comment or function)."""

    UNRESOLVED = "unresolved"  # Pure pseudocode comment, no code yet
    STUB = "stub"  # Function exists but body is pass/NotImplementedError/...
    PARTIAL = "partial"  # Function has some code but still has spec comments
    IMPLEMENTED = "implemented"  # Function has code, no remaining spec comments
    VERIFIED = "verified"  # Function has code + tests pass


class CommentKind(enum.Enum):
    """Classification of a comment token."""

    SPEC = "spec"  # Unimplemented spec element (IS a gap)
    TODO = "todo"  # Explicit TODO/FIXME marker (IS a gap)
    INFRASTRUCTURE = "infra"  # Type-ignore, noqa, pragma, encoding, shebang
    SECTION_MARKER = "section"  # Visual separator (# ---- ... ----)


@dataclass(frozen=True)
class SpecComment:
    """A single comment token classified as a spec element."""

    file: str
    line: int
    col_offset: int
    text: str  # Comment text without leading '# '
    raw: str  # Full token string including '#'
    kind: CommentKind
    enclosing_function: str | None  # Qualified name of enclosing function, or None if module-level


@dataclass(frozen=True)
class FunctionInfo:
    """Information about a parsed function definition."""

    name: str  # Simple name
    qualified_name: str  # Dotted path: module.Class.method
    file: str
    line_start: int
    line_end: int
    col_offset: int
    is_async: bool
    decorators: list[str]  # Decorator names
    args: list[str]  # Parameter names (no types, just names for addressing)
    return_annotation: str | None  # Return type annotation as string, if present
    docstring: str | None  # First string expression in body, if present
    body_line_count: int  # Number of lines in the function body
    translation_state: TranslationState
    spec_comments: list[SpecComment]  # Spec comments inside this function
    stub_reason: str | None  # If STUB: "pass", "ellipsis", "not_implemented"

    def __hash__(self) -> int:
        return hash((self.qualified_name, self.file, self.line_start))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FunctionInfo):
            return NotImplemented
        return (
            self.qualified_name == other.qualified_name
            and self.file == other.file
            and self.line_start == other.line_start
        )


@dataclass
class FileTranslationState:
    """Complete translation state snapshot for a single Python file.

    This is the primary output of the edit-in-place engine.
    It replaces the old Phase 0 extraction output.
    """

    file: str
    content_hash: str  # SHA-256 of file content for change detection
    functions: list[FunctionInfo]  # All function/method definitions found
    module_comments: list[SpecComment]  # Spec comments at module level (not inside any function)
    all_comments: list[SpecComment]  # Every comment token in the file, classified

    # Computed summaries
    total_spec_comments: int  # Count of SPEC + TODO comments
    total_functions: int
    stub_count: int  # Functions in STUB state
    partial_count: int  # Functions in PARTIAL state
    implemented_count: int  # Functions in IMPLEMENTED state
    unresolved_count: int  # Functions in UNRESOLVED state (all comments, no code)

    @property
    def is_complete(self) -> bool:
        """True when no spec comments remain and no stubs exist."""
        return self.total_spec_comments == 0 and self.stub_count == 0

    @property
    def completion_ratio(self) -> float:
        """Ratio of implemented functions to total functions."""
        if self.total_functions == 0:
            return 1.0
        return self.implemented_count / self.total_functions

    @property
    def gaps(self) -> list[SpecComment]:
        """All spec comments that represent gaps (SPEC + TODO kinds)."""
        return [c for c in self.all_comments if c.kind in (CommentKind.SPEC, CommentKind.TODO)]


@dataclass
class ProjectTranslationState:
    """Translation state across an entire project (multiple files)."""

    files: dict[str, FileTranslationState]  # path -> state

    @property
    def total_gaps(self) -> int:
        return sum(f.total_spec_comments for f in self.files.values())

    @property
    def total_functions(self) -> int:
        return sum(f.total_functions for f in self.files.values())

    @property
    def is_complete(self) -> bool:
        return all(f.is_complete for f in self.files.values())

    def get_gaps_by_file(self) -> dict[str, list[SpecComment]]:
        return {path: state.gaps for path, state in self.files.items() if state.gaps}


# =============================================================================
# Plan 2: Comment Classifier
# =============================================================================

_INFRASTRUCTURE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^#\s*type:\s*ignore"),  # type: ignore[...]
    re.compile(r"^#\s*noqa"),  # noqa: E501
    re.compile(r"^#\s*pragma:\s*no\s*cover"),  # pragma: no cover
    re.compile(r"^#\s*pylint:\s*(disable|enable)"),  # pylint directives
    re.compile(r"^#\s*fmt:\s*(on|off)"),  # black/ruff format directives
    re.compile(r"^#\s*isort:\s*(skip|on|off)"),  # isort directives
    re.compile(r"^#!"),  # shebang
    re.compile(r"^#\s*-\*-\s*coding"),  # encoding declarations
    re.compile(r"^#\s*mypy:\s*"),  # mypy directives
    re.compile(r"^#\s*ruff:\s*"),  # ruff directives
]

_SECTION_MARKER_PATTERN: re.Pattern[str] = re.compile(
    r"^#\s*[-=]{4,}"  # # ---- ... ---- or # ==== ... ====
)

_TODO_PATTERN: re.Pattern[str] = re.compile(
    r"^#\s*(TODO|FIXME|HACK|XXX|WORKAROUND)\b", re.IGNORECASE
)


def classify_comment(token_string: str) -> CommentKind:
    """Classify a single comment token.

    Args:
        token_string: The full token string including '#' prefix.

    Returns:
        CommentKind indicating whether this is a spec comment, TODO,
        infrastructure comment, or section marker.
    """
    stripped = token_string.strip()

    # Check infrastructure patterns first
    for pattern in _INFRASTRUCTURE_PATTERNS:
        if pattern.search(stripped):
            return CommentKind.INFRASTRUCTURE

    # Check section marker pattern
    if _SECTION_MARKER_PATTERN.search(stripped):
        return CommentKind.SECTION_MARKER

    # Check TODO/FIXME pattern
    if _TODO_PATTERN.search(stripped):
        return CommentKind.TODO

    # Default: spec comment (gap)
    return CommentKind.SPEC


def _build_function_line_map(
    tree: ast.Module,
) -> list[tuple[int, int, str]]:
    """Build a list of (line_start, line_end, qualified_name) for all functions.

    Returns the list sorted by line_start so we can efficiently look up
    which function encloses a given line. Innermost (most deeply nested)
    functions appear later, so we iterate in reverse for enclosing lookup.
    """
    result: list[tuple[int, int, str]] = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._name_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._name_stack.append(node.name)
            self.generic_visit(node)
            self._name_stack.pop()

        def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            qualified = ".".join([*self._name_stack, node.name])
            end_line = node.end_lineno if node.end_lineno is not None else node.lineno
            result.append((node.lineno, end_line, qualified))
            self._name_stack.append(node.name)
            self.generic_visit(node)
            self._name_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_func(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_func(node)

    _Visitor().visit(tree)
    # Sort by start line, then by end line descending (larger ranges first)
    result.sort(key=lambda t: (t[0], -t[1]))
    return result


def _find_enclosing_function(
    line: int,
    func_map: list[tuple[int, int, str]],
) -> str | None:
    """Find the innermost enclosing function for a given line number.

    Iterates the function map in reverse to find the most specific (innermost)
    function that contains the line.
    """
    best: str | None = None
    best_size = float("inf")
    for start, end, name in func_map:
        if start <= line <= end:
            size = end - start
            if size < best_size:
                best_size = size
                best = name
    return best


def scan_comments(filepath: str) -> list[SpecComment]:
    """Scan a Python file and return all comments with classification.

    Uses ``tokenize.generate_tokens`` to find every COMMENT token.
    For each, determines the enclosing function (if any) by cross-referencing
    with ``ast.parse`` results.

    Args:
        filepath: Path to a Python source file.

    Returns:
        List of SpecComment objects for every comment in the file.
    """
    source = Path(filepath).read_text(encoding="utf-8")

    # Parse AST for function line ranges
    tree = ast.parse(source, filename=filepath)
    func_map = _build_function_line_map(tree)

    # Tokenize to find all COMMENT tokens
    comments: list[SpecComment] = []
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            raw = tok.string
            kind = classify_comment(raw)
            # Strip leading '# ' or '#' to get text
            text = raw.lstrip("#").strip()
            enclosing = _find_enclosing_function(tok.start[0], func_map)
            comments.append(
                SpecComment(
                    file=filepath,
                    line=tok.start[0],
                    col_offset=tok.start[1],
                    text=text,
                    raw=raw,
                    kind=kind,
                    enclosing_function=enclosing,
                )
            )

    return comments


# =============================================================================
# Plan 3: Function Analyzer (Stub and State Detection)
# =============================================================================


def _is_stub_body(body: list[ast.stmt]) -> tuple[bool, str | None]:
    """Check if a function body is a stub.

    A function is a stub if its body consists entirely of:
    - ``pass`` statement(s)
    - Ellipsis literal (``...``)
    - ``raise NotImplementedError(...)``
    - A docstring followed by any of the above

    Args:
        body: The body of an ``ast.FunctionDef`` node.

    Returns:
        ``(is_stub, reason)`` where reason is ``"pass"``, ``"ellipsis"``,
        or ``"not_implemented"``.
    """
    # Filter out the docstring if present
    effective_body = list(body)
    if (
        effective_body
        and isinstance(effective_body[0], ast.Expr)
        and isinstance(effective_body[0].value, ast.Constant)
        and isinstance(effective_body[0].value.value, str)
    ):
        effective_body = effective_body[1:]

    if not effective_body:
        # Only a docstring, treat as stub
        return True, "pass"

    # Check each statement
    for stmt in effective_body:
        if isinstance(stmt, ast.Pass):
            continue
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            if stmt.value.value is ...:
                continue
            else:
                return False, None
        elif isinstance(stmt, ast.Raise):
            # Check if it's raise NotImplementedError(...)
            if stmt.exc is not None:
                if isinstance(stmt.exc, ast.Call) and isinstance(stmt.exc.func, ast.Name):
                    if stmt.exc.func.id == "NotImplementedError":
                        continue
                elif isinstance(stmt.exc, ast.Name):
                    if stmt.exc.id == "NotImplementedError":
                        continue
            return False, None
        else:
            return False, None

    # Determine the reason from the first effective statement
    if not effective_body:
        return True, "pass"

    first = effective_body[0]
    if isinstance(first, ast.Pass):
        return True, "pass"
    elif isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and first.value.value is ...:
        return True, "ellipsis"
    elif isinstance(first, ast.Raise):
        return True, "not_implemented"
    else:
        return True, "pass"


def _get_docstring(body: list[ast.stmt]) -> str | None:
    """Extract docstring from function body (first Expr node with Constant str)."""
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[0].value.value
    return None


def _compute_qualified_name(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    parents: list[str],
) -> str:
    """Compute dotted qualified name from AST node and its parent chain.

    Examples:
        - Top-level function: ``"validate_payment"``
        - Method: ``"PaymentService.validate"``
        - Nested class method: ``"Outer.Inner.method"``
    """
    return ".".join([*parents, node.name])


def _determine_translation_state(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
    spec_comments: list[SpecComment],
    is_stub: bool,
) -> TranslationState:
    """Determine the translation state of a function.

    Logic:
    - If is_stub and has spec comments: UNRESOLVED
    - If is_stub and no spec comments: STUB
    - If not stub and has spec comments: PARTIAL
    - If not stub and no spec comments: IMPLEMENTED

    Note: VERIFIED requires external test results, not determined here.
    """
    has_gaps = any(c.kind in (CommentKind.SPEC, CommentKind.TODO) for c in spec_comments)

    if is_stub and has_gaps:
        return TranslationState.UNRESOLVED
    if is_stub and not has_gaps:
        return TranslationState.STUB
    if not is_stub and has_gaps:
        return TranslationState.PARTIAL
    return TranslationState.IMPLEMENTED


def _extract_decorator_name(decorator: ast.expr) -> str:
    """Extract a readable name from a decorator AST node."""
    if isinstance(decorator, ast.Name):
        return decorator.id
    if isinstance(decorator, ast.Attribute):
        parts: list[str] = []
        node: ast.expr = decorator
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))
    if isinstance(decorator, ast.Call):
        return _extract_decorator_name(decorator.func)
    return ast.dump(decorator)


def _extract_return_annotation(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Extract return type annotation as string."""
    if node.returns is None:
        return None
    return ast.unparse(node.returns)


def analyze_functions(
    filepath: str,
    comments: list[SpecComment],
) -> list[FunctionInfo]:
    """Analyze all function definitions in a Python file.

    Uses ``ast.parse`` to walk the AST. For each ``FunctionDef``/``AsyncFunctionDef``:
    1. Extract name, qualified name, line range, decorators, args, return annotation
    2. Check if body is a stub
    3. Cross-reference with comments to find spec comments inside this function
    4. Determine translation state

    Args:
        filepath: Path to Python source file.
        comments: Pre-scanned comments from ``scan_comments()``.

    Returns:
        List of FunctionInfo for every function/method in the file.
    """
    source = Path(filepath).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=filepath)

    functions: list[FunctionInfo] = []

    class _FuncVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._name_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._name_stack.append(node.name)
            self.generic_visit(node)
            self._name_stack.pop()

        def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            qualified = _compute_qualified_name(node, self._name_stack)
            end_line = node.end_lineno if node.end_lineno is not None else node.lineno

            # Extract decorator names
            decorators = [_extract_decorator_name(d) for d in node.decorator_list]

            # Extract argument names
            args: list[str] = []
            for arg in node.args.args:
                args.append(arg.arg)
            for arg in node.args.posonlyargs:
                args.append(arg.arg)
            for arg in node.args.kwonlyargs:
                args.append(arg.arg)
            if node.args.vararg:
                args.append(f"*{node.args.vararg.arg}")
            if node.args.kwarg:
                args.append(f"**{node.args.kwarg.arg}")

            # Check stub status
            is_stub, stub_reason = _is_stub_body(node.body)

            # Get docstring
            docstring = _get_docstring(node.body)

            # Find spec comments within this function's line range
            func_comments = [
                c
                for c in comments
                if node.lineno <= c.line <= end_line
            ]

            # Determine translation state
            state = _determine_translation_state(node, func_comments, is_stub)

            # Return annotation
            return_annotation = _extract_return_annotation(node)

            # Body line count
            body_line_count = end_line - node.lineno

            functions.append(
                FunctionInfo(
                    name=node.name,
                    qualified_name=qualified,
                    file=filepath,
                    line_start=node.lineno,
                    line_end=end_line,
                    col_offset=node.col_offset,
                    is_async=isinstance(node, ast.AsyncFunctionDef),
                    decorators=decorators,
                    args=args,
                    return_annotation=return_annotation,
                    docstring=docstring,
                    body_line_count=body_line_count,
                    translation_state=state,
                    spec_comments=func_comments,
                    stub_reason=stub_reason,
                )
            )

            # Visit nested functions/classes
            self._name_stack.append(node.name)
            self.generic_visit(node)
            self._name_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._visit_func(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._visit_func(node)

    _FuncVisitor().visit(tree)
    return functions


# =============================================================================
# Plan 4: File-Level Orchestrator
# =============================================================================


def analyze_file(filepath: str) -> FileTranslationState:
    """Analyze a single Python file and produce its translation state.

    This is the main entry point for single-file analysis.

    Steps:
    1. Read file content and compute content_hash
    2. ``scan_comments()`` to get all classified comments
    3. ``analyze_functions()`` to get all function info with states
    4. Separate module-level spec comments (not inside any function)
    5. Compute summary counts
    6. Return ``FileTranslationState``

    Args:
        filepath: Absolute path to a Python source file.

    Returns:
        FileTranslationState snapshot.

    Raises:
        FileNotFoundError: If filepath does not exist.
        SyntaxError: If the file cannot be parsed (not valid Python).
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    content = path.read_text(encoding="utf-8")

    # Validate it is parseable Python (raises SyntaxError if invalid)
    ast.parse(content, filename=filepath)

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    # Scan all comments
    all_comments = scan_comments(filepath)

    # Analyze functions
    functions = analyze_functions(filepath, all_comments)

    # Build set of line ranges covered by functions
    func_line_ranges: list[tuple[int, int]] = []
    for func in functions:
        func_line_ranges.append((func.line_start, func.line_end))

    def _is_inside_function(line: int) -> bool:
        for start, end in func_line_ranges:
            if start <= line <= end:
                return True
        return False

    # Module-level spec comments: SPEC or TODO kind and not inside any function
    module_comments = [
        c
        for c in all_comments
        if c.kind in (CommentKind.SPEC, CommentKind.TODO) and not _is_inside_function(c.line)
    ]

    # Compute summary counts
    total_spec_comments = sum(
        1 for c in all_comments if c.kind in (CommentKind.SPEC, CommentKind.TODO)
    )
    total_functions = len(functions)
    stub_count = sum(1 for f in functions if f.translation_state == TranslationState.STUB)
    partial_count = sum(1 for f in functions if f.translation_state == TranslationState.PARTIAL)
    implemented_count = sum(
        1 for f in functions if f.translation_state == TranslationState.IMPLEMENTED
    )
    unresolved_count = sum(
        1 for f in functions if f.translation_state == TranslationState.UNRESOLVED
    )

    return FileTranslationState(
        file=filepath,
        content_hash=content_hash,
        functions=functions,
        module_comments=module_comments,
        all_comments=all_comments,
        total_spec_comments=total_spec_comments,
        total_functions=total_functions,
        stub_count=stub_count,
        partial_count=partial_count,
        implemented_count=implemented_count,
        unresolved_count=unresolved_count,
    )


def analyze_project(
    root: str,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> ProjectTranslationState:
    """Analyze all Python files in a project directory.

    Args:
        root: Root directory to scan.
        include: Glob patterns to include (default: ``["**/*.py"]``).
        exclude: Glob patterns to exclude (default: ``["**/test_*", "**/__pycache__/**"]``).

    Returns:
        ProjectTranslationState with per-file states.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    include_patterns = include or ["**/*.py"]
    exclude_patterns = exclude or ["**/test_*", "**/__pycache__/**"]

    # Collect matching files
    all_files: set[Path] = set()
    for pattern in include_patterns:
        all_files.update(root_path.glob(pattern))

    # Apply exclusions
    def _matches_exclude(path: Path) -> bool:
        import fnmatch

        try:
            rel = path.relative_to(root_path)
        except ValueError:
            rel = path
        rel_str = str(rel)
        for exc in exclude_patterns:
            # Check against the full relative path
            if fnmatch.fnmatch(rel_str, exc):
                return True
            # Also check just the filename for patterns like **/test_*
            stripped = exc.lstrip("*").lstrip("/")
            if fnmatch.fnmatch(path.name, stripped):
                return True
        return False

    filtered_files = sorted(f for f in all_files if f.is_file() and not _matches_exclude(f))

    # Analyze each file
    files: dict[str, FileTranslationState] = {}
    for fpath in filtered_files:
        try:
            state = analyze_file(str(fpath))
            files[str(fpath)] = state
        except SyntaxError:
            # Skip files with syntax errors
            continue

    return ProjectTranslationState(files=files)


def find_gaps(
    state: FileTranslationState | ProjectTranslationState,
) -> list[SpecComment]:
    """Extract all gap-type comments from a translation state.

    This is the completeness detector. Returns every comment that
    represents unimplemented spec.

    Args:
        state: Either a single file or project translation state.

    Returns:
        List of SpecComment objects with kind SPEC or TODO.
    """
    if isinstance(state, FileTranslationState):
        return state.gaps

    # ProjectTranslationState
    all_gaps: list[SpecComment] = []
    for file_state in state.files.values():
        all_gaps.extend(file_state.gaps)
    return all_gaps


def format_gap_report(state: ProjectTranslationState) -> str:
    """Format a human-readable gap report from project translation state.

    Args:
        state: Project translation state to report on.

    Returns:
        Markdown-formatted gap report string.
    """
    lines: list[str] = []
    lines.append("# Gap Report")
    lines.append("")

    total_files = len(state.files)
    total_funcs = state.total_functions
    total_gaps = state.total_gaps

    # Aggregate counts
    implemented = sum(f.implemented_count for f in state.files.values())
    partial = sum(f.partial_count for f in state.files.values())
    stubs = sum(f.stub_count for f in state.files.values())
    unresolved = sum(f.unresolved_count for f in state.files.values())

    lines.append("## Summary")
    lines.append(f"- Files analyzed: {total_files}")
    lines.append(f"- Total functions: {total_funcs}")

    if total_funcs > 0:
        lines.append(f"- Implemented: {implemented} ({implemented / total_funcs:.1%})")
        lines.append(f"- Partial: {partial} ({partial / total_funcs:.1%})")
        lines.append(f"- Stubs: {stubs} ({stubs / total_funcs:.1%})")
        lines.append(f"- Unresolved: {unresolved} ({unresolved / total_funcs:.1%})")
    else:
        lines.append(f"- Implemented: {implemented}")
        lines.append(f"- Partial: {partial}")
        lines.append(f"- Stubs: {stubs}")
        lines.append(f"- Unresolved: {unresolved}")

    lines.append(f"- Remaining spec comments: {total_gaps}")
    lines.append("")

    # Gaps by file
    gaps_by_file = state.get_gaps_by_file()
    if gaps_by_file:
        lines.append("## Gaps by File")
        lines.append("")
        for fpath, file_gaps in sorted(gaps_by_file.items()):
            lines.append(f"### {fpath} ({len(file_gaps)} gaps)")
            for gap in file_gaps:
                func_label = gap.enclosing_function or "module-level"
                lines.append(f"- L{gap.line} [{func_label}] {gap.raw}")
            lines.append("")
    else:
        lines.append("## No Gaps Found")
        lines.append("")
        lines.append("All spec comments have been resolved.")
        lines.append("")

    return "\n".join(lines)
