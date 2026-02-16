"""Edit-in-place engine: treats source files as living specifications.

Comments are unimplemented spec elements, stubs are incomplete implementations,
and "no comments in production" is the completeness invariant. This module
provides language-agnostic source analysis via LLM-based code structure
extraction (``code_analysis`` module).

Primary entry points:
    - ``analyze_file(filepath)`` -> ``FileTranslationState``
    - ``analyze_project(root)`` -> ``ProjectTranslationState``
    - ``find_gaps(state)`` -> list of ``SpecComment`` gaps
    - ``format_gap_report(state)`` -> human-readable report string
"""

from __future__ import annotations

import enum
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from spec_manager.core.code_analysis import analyze_source
from spec_manager.core.language import INFRASTRUCTURE_COMMENT_PATTERNS

# =============================================================================
# Plan 1: Core Data Structures
# =============================================================================


class TranslationState(enum.Enum):
    """Lifecycle state of a spec element (comment or function)."""

    UNRESOLVED = "unresolved"  # Pure pseudocode comment, no code yet
    STUB = "stub"  # Function exists but body is a placeholder
    PARTIAL = "partial"  # Function has some code but still has spec comments
    IMPLEMENTED = "implemented"  # Function has code, no remaining spec comments
    VERIFIED = "verified"  # Function has code + tests pass


class CommentKind(enum.Enum):
    """Classification of a comment token."""

    SPEC = "spec"  # Unimplemented spec element (IS a gap)
    TODO = "todo"  # Explicit TODO/FIXME marker (IS a gap)
    INFRASTRUCTURE = "infra"  # Type-ignore, noqa, pragma, encoding, shebang
    SECTION_MARKER = "section"  # Visual separator (---- ... ----)


@dataclass(frozen=True)
class SpecComment:
    """A single comment token classified as a spec element."""

    file: str
    line: int
    col_offset: int
    text: str  # Comment text without language-specific delimiter
    raw: str  # Full token string including delimiter
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
    body_start_line: int  # 1-indexed line where body starts (after signature + docstring)
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
    """Complete translation state snapshot for a single source file.

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
        """All comments that represent actual gaps (state-aware).

        Gap logic considers function state:
        - TODO comments are always gaps regardless of context
        - Module-level SPEC comments are always gaps
        - SPEC comments inside stub/unresolved functions are gaps
        - SPEC comments inside implemented functions are NOT gaps
          (they are legitimate code comments, not unimplemented spec)
        """
        func_states = {f.qualified_name: f.translation_state for f in self.functions}
        result = []
        for c in self.all_comments:
            if c.kind == CommentKind.TODO:
                result.append(c)
            elif c.kind == CommentKind.SPEC:
                if c.enclosing_function is None:
                    result.append(c)
                else:
                    state = func_states.get(c.enclosing_function)
                    if state in (TranslationState.UNRESOLVED, TranslationState.STUB):
                        result.append(c)
        return result


@dataclass
class ProjectTranslationState:
    """Translation state across an entire project (multiple files)."""

    files: dict[str, FileTranslationState]  # path -> state
    analysis_failures: dict[str, str] = field(default_factory=dict)  # path -> failure reason

    @property
    def total_gaps(self) -> int:
        return sum(f.total_spec_comments for f in self.files.values())

    @property
    def total_functions(self) -> int:
        return sum(f.total_functions for f in self.files.values())

    @property
    def is_complete(self) -> bool:
        return all(f.is_complete for f in self.files.values()) and not self.analysis_failures

    def get_gaps_by_file(self) -> dict[str, list[SpecComment]]:
        return {path: state.gaps for path, state in self.files.items() if state.gaps}


# =============================================================================
# Plan 2: Comment Classifier (language-agnostic — operates on clean text)
# =============================================================================

# These patterns match on clean comment TEXT, not on raw tokens with delimiters.
# The LLM extracts comment text without language-specific delimiters (#, //, --, etc.)
# The canonical list lives in spec_manager.core.language.INFRASTRUCTURE_COMMENT_PATTERNS;
# this module extends it with a few edit-in-place-specific patterns (shebang, encoding).

_INFRASTRUCTURE_PATTERNS: list[re.Pattern[str]] = [
    *INFRASTRUCTURE_COMMENT_PATTERNS,
    re.compile(r"^!"),  # shebang (delimiter stripped, leading ! remains)
    re.compile(r"^-\*-\s*coding"),  # encoding declarations
]

_SECTION_MARKER_PATTERN: re.Pattern[str] = re.compile(
    r"^[-=]{4,}"  # ---- ... ---- or ==== ... ==== (delimiter already stripped)
)

_TODO_PATTERN: re.Pattern[str] = re.compile(r"^(TODO|FIXME|HACK|XXX|WORKAROUND)\b", re.IGNORECASE)


def classify_comment(text: str) -> CommentKind:
    """Classify a comment by its clean text content.

    Args:
        text: Comment text WITHOUT language-specific delimiter.
              E.g., ``"validate payment against fraud rules"`` not
              ``"# validate payment against fraud rules"``.

    Returns:
        CommentKind indicating whether this is a spec comment, TODO,
        infrastructure comment, or section marker.
    """
    stripped = text.strip()

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


# =============================================================================
# Plan 3: Translation State Determination (pure logic, no AST dependency)
# =============================================================================


def _determine_translation_state(
    spec_comments: list[SpecComment],
    is_stub: bool,
) -> TranslationState:
    """Determine the translation state of a function.

    Logic:
    - If is_stub and has spec comments (SPEC or TODO): UNRESOLVED
    - If is_stub and no spec comments: STUB
    - If not stub and has TODO comments: PARTIAL
    - If not stub and no TODO comments: IMPLEMENTED

    In stubs, ALL comments (SPEC and TODO) indicate unimplemented spec.
    In implemented functions, only TODO markers indicate remaining gaps —
    bare comments are legitimate code comments, not spec elements.

    Note: VERIFIED requires external test results, not determined here.
    """
    if is_stub:
        has_gaps = any(c.kind in (CommentKind.SPEC, CommentKind.TODO) for c in spec_comments)
        return TranslationState.UNRESOLVED if has_gaps else TranslationState.STUB
    else:
        has_todo = any(c.kind == CommentKind.TODO for c in spec_comments)
        return TranslationState.PARTIAL if has_todo else TranslationState.IMPLEMENTED


# =============================================================================
# Stub reason mapping (LLM-agnostic labels → internal labels)
# =============================================================================

_STUB_REASON_MAP: dict[str | None, str | None] = {
    "placeholder": "pass",
    "ellipsis": "ellipsis",
    "not_implemented": "not_implemented",
    None: None,
}


def _normalize_stub_reason(reason: str | None) -> str | None:
    """Map LLM stub reason labels to internal labels."""
    return _STUB_REASON_MAP.get(reason, reason)


# =============================================================================
# Plan 4: LLM-Backed Analysis Functions
# =============================================================================


def scan_comments(
    filepath: str,
    *,
    workspace: Path | None = None,
) -> list[SpecComment]:
    """Scan a source file and return all comments with classification.

    Uses LLM-based code analysis to extract comments in any language.
    Comment classification uses regex on extracted clean text (no
    language-specific delimiters).

    Args:
        filepath: Path to a source file.
        workspace: Working directory for LLM agent execution.

    Returns:
        List of SpecComment objects for every comment in the file.
    """
    content = Path(filepath).read_text(encoding="utf-8")
    analysis = analyze_source(content, filepath, workspace=workspace)

    comments: list[SpecComment] = []
    for raw_comment in analysis.comments:
        kind = classify_comment(raw_comment.text)
        comments.append(
            SpecComment(
                file=filepath,
                line=raw_comment.line,
                col_offset=raw_comment.col_offset,
                text=raw_comment.text,
                raw=raw_comment.raw,
                kind=kind,
                enclosing_function=raw_comment.enclosing_function,
            )
        )

    return comments


def analyze_functions(
    filepath: str,
    comments: list[SpecComment],
    *,
    workspace: Path | None = None,
) -> list[FunctionInfo]:
    """Analyze all function definitions in a source file.

    Uses LLM-based code analysis to extract function boundaries, stub
    detection, and metadata in any language.

    Args:
        filepath: Path to source file.
        comments: Pre-scanned comments from ``scan_comments()``.
        workspace: Working directory for LLM agent execution.

    Returns:
        List of FunctionInfo for every function/method in the file.
    """
    content = Path(filepath).read_text(encoding="utf-8")
    analysis = analyze_source(content, filepath, workspace=workspace)

    functions: list[FunctionInfo] = []
    for raw_func in analysis.functions:
        # Find spec comments within this function's line range
        func_comments = [c for c in comments if raw_func.start_line <= c.line <= raw_func.end_line]

        # Determine translation state
        state = _determine_translation_state(func_comments, raw_func.is_stub)

        functions.append(
            FunctionInfo(
                name=raw_func.name,
                qualified_name=raw_func.qualified_name,
                file=filepath,
                line_start=raw_func.start_line,
                line_end=raw_func.end_line,
                col_offset=0,
                is_async=raw_func.is_async,
                decorators=list(raw_func.decorators),
                args=list(raw_func.args),
                return_annotation=raw_func.return_annotation,
                docstring=raw_func.docstring,
                body_start_line=raw_func.body_start_line,
                body_line_count=raw_func.body_line_count,
                translation_state=state,
                spec_comments=func_comments,
                stub_reason=_normalize_stub_reason(raw_func.stub_reason),
            )
        )

    return functions


def analyze_file(
    filepath: str,
    *,
    workspace: Path | None = None,
) -> FileTranslationState:
    """Analyze a single source file and produce its translation state.

    This is the main entry point for single-file analysis. Uses LLM-based
    code analysis for language-agnostic operation.

    Steps:
    1. Read file content and compute content_hash
    2. Call LLM-based analysis (cached by content hash)
    3. Classify all comments
    4. Build function info with translation states
    5. Compute summary counts
    6. Return ``FileTranslationState``

    Args:
        filepath: Path to a source file.
        workspace: Working directory for LLM agent execution.

    Returns:
        FileTranslationState snapshot.

    Raises:
        FileNotFoundError: If filepath does not exist.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    content = path.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    # Single LLM analysis call (cached by content hash)
    analysis = analyze_source(content, filepath, workspace=workspace)

    # Classify all comments using clean text
    all_comments: list[SpecComment] = []
    for raw_comment in analysis.comments:
        kind = classify_comment(raw_comment.text)
        all_comments.append(
            SpecComment(
                file=filepath,
                line=raw_comment.line,
                col_offset=raw_comment.col_offset,
                text=raw_comment.text,
                raw=raw_comment.raw,
                kind=kind,
                enclosing_function=raw_comment.enclosing_function,
            )
        )

    # Build function info from LLM analysis
    functions: list[FunctionInfo] = []
    for raw_func in analysis.functions:
        func_comments = [
            c for c in all_comments if raw_func.start_line <= c.line <= raw_func.end_line
        ]
        state = _determine_translation_state(func_comments, raw_func.is_stub)
        functions.append(
            FunctionInfo(
                name=raw_func.name,
                qualified_name=raw_func.qualified_name,
                file=filepath,
                line_start=raw_func.start_line,
                line_end=raw_func.end_line,
                col_offset=0,
                is_async=raw_func.is_async,
                decorators=list(raw_func.decorators),
                args=list(raw_func.args),
                return_annotation=raw_func.return_annotation,
                docstring=raw_func.docstring,
                body_start_line=raw_func.body_start_line,
                body_line_count=raw_func.body_line_count,
                translation_state=state,
                spec_comments=func_comments,
                stub_reason=_normalize_stub_reason(raw_func.stub_reason),
            )
        )

    # Build set of line ranges covered by functions
    func_line_ranges: list[tuple[int, int]] = [(f.line_start, f.line_end) for f in functions]

    def _is_inside_function(line: int) -> bool:
        return any(start <= line <= end for start, end in func_line_ranges)

    # Module-level spec comments: SPEC or TODO kind and not inside any function
    module_comments = [
        c
        for c in all_comments
        if c.kind in (CommentKind.SPEC, CommentKind.TODO) and not _is_inside_function(c.line)
    ]

    # Compute state-aware gap count
    func_states_map = {f.qualified_name: f.translation_state for f in functions}
    total_spec_comments = 0
    for c in all_comments:
        if c.kind == CommentKind.TODO:
            total_spec_comments += 1
        elif c.kind == CommentKind.SPEC:
            if c.enclosing_function is None:
                total_spec_comments += 1
            else:
                state = func_states_map.get(c.enclosing_function)
                if state in (TranslationState.UNRESOLVED, TranslationState.STUB):
                    total_spec_comments += 1

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
    *,
    workspace: Path | None = None,
) -> ProjectTranslationState:
    """Analyze all source files in a project directory.

    Args:
        root: Root directory to scan.
        include: Glob patterns to include (default: ``["**/*.py"]``).
            Callers should pass language-appropriate patterns.
        exclude: Glob patterns to exclude (default: ``["**/test_*", "**/__pycache__/**"]``).
        workspace: Working directory for LLM agent execution.

    Returns:
        ProjectTranslationState with per-file states.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    from spec_manager.core.language import EXCLUDE_DIRS, SOURCE_RGLOBS

    include_patterns = include or list(SOURCE_RGLOBS)
    exclude_patterns = exclude or ["**/test_*"] + [f"**/{d}/**" for d in sorted(EXCLUDE_DIRS)]

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
            if fnmatch.fnmatch(rel_str, exc):
                return True
            stripped = exc.lstrip("*").lstrip("/")
            if fnmatch.fnmatch(path.name, stripped):
                return True
        return False

    filtered_files = sorted(f for f in all_files if f.is_file() and not _matches_exclude(f))

    # Analyze each file
    files: dict[str, FileTranslationState] = {}
    analysis_failures: dict[str, str] = {}
    for fpath in filtered_files:
        try:
            state = analyze_file(str(fpath), workspace=workspace)
            files[str(fpath)] = state
        except Exception as exc:
            analysis_failures[str(fpath)] = str(exc)

    return ProjectTranslationState(files=files, analysis_failures=analysis_failures)


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
    if state.analysis_failures:
        lines.append(f"- Files failed analysis: {len(state.analysis_failures)}")
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

    if state.analysis_failures:
        lines.append("## Analysis Failures")
        lines.append("")
        for fpath, reason in sorted(state.analysis_failures.items()):
            lines.append(f"- {fpath}: {reason}")
        lines.append("")

    return "\n".join(lines)
