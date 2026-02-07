# Implementation Plan: Edit-in-Place Engine

## Overview

Build the core engine that treats Python source files as living specifications. Comments are unimplemented spec elements, stubs are incomplete implementations, and "no comments in production" is the completeness invariant. This replaces the extraction-based Phase 0 pipeline with a mechanical, deterministic source analysis system using Python's `ast` and `tokenize` modules.

## Current State (Problems)

1. **Extraction pipeline creates drift.** The current system (Phase 1 sectionization in `scripts/spec_manager/spec_manager/refinement/workflows/phase_01_sectionization.py`) reads source/spec documents and uses LLM agents to extract section spans, build section maps, and emit atoms. The spec is a *separate artifact* derived from source material. This separation means the spec and code can drift apart.

2. **Line-range indexing is fragile.** The current `SectionExtractor` (`scripts/spec_manager/spec_manager/core/sections.py`) uses `([=ID])` markdown declarations to delimit sections. The `ProvenanceTracker` (`scripts/spec_manager/spec_manager/core/provenance.py`) tracks `SourceLocation` with line ranges. These break when files are edited.

3. **Gap detection requires LLM inference.** Current gaps (`scripts/spec_manager/spec_manager/refinement/core/gap.py` and `gap_queue.py`) are discovered through multi-phase LLM workflows. The design document (Section 7) shows that gaps can be detected *mechanically* -- every comment is a gap, every stub is a gap.

4. **No function-level addressing.** The current `TrackedUnit` in `provenance.py` tracks content at section granularity with `UnitType` enum values (ALGORITHM, CLAIM, etc.). There is no concept of a Python function as the addressable unit, and no `ast`-based parsing.

5. **Translation state is not tracked.** There is no data structure that records whether a given comment has been translated to code, whether a function is a stub, or what the lifecycle stage of each spec element is.

## Target State

A Python module (`scripts/spec_manager/spec_manager/core/edit_in_place.py`) that:

- Parses any Python source file and produces a structured inventory of all functions, comments, and stubs
- Classifies every comment as either a **spec comment** (gap) or an **infrastructure comment** (docstring, type-ignore, pragma)
- Tracks translation state per function: `unresolved` -> `stub` -> `partial` -> `implemented` -> `verified`
- Produces a `FileTranslationState` snapshot that is the mechanical, deterministic gap report for one file
- Integrates with the existing refinement workflow as a replacement for Phase 0 extraction
- Provides the completeness detector: count of remaining spec comments = count of gaps

## Additional Info

### Design Constraints (from algorithmic-projection-patch.md)

- **Language-specific from day one**: tied to Python, using `ast` and `tokenize` modules (Section 1)
- **Comments = gaps, period**: no heuristics, no LLM inference for gap detection (Section 7)
- **Stubs are gaps**: functions containing only `pass`, `raise NotImplementedError`, or `...` (Section 7)
- **Pin-functions are real functions**: atoms are extracted functions with names, signatures, line numbers (Section 5)
- **Every stage is parseable and executable** (Section 1)

### Comment Classification Rules

Not all comments are spec elements. The engine must distinguish:

| Category | Example | Is Gap? |
|---|---|---|
| Spec comment | `# validate payment against fraud rules` | YES |
| Docstring | `"""Validates payment data."""` | NO (parsed by `ast`, not `tokenize`) |
| Type annotation comment | `# type: ignore[attr-defined]` | NO |
| Pragma/directive | `# noqa: E501`, `# pragma: no cover` | NO |
| Section marker | `# ---- Atom functions ----` | NO |
| TODO/FIXME | `# TODO: implement retry logic` | YES (explicit gap marker) |
| Shebang | `#!/usr/bin/env python` | NO |
| Encoding declaration | `# -*- coding: utf-8 -*-` | NO |

The classifier uses a **denylist** of known non-spec patterns. Anything not in the denylist is a spec comment (gap). This is intentionally aggressive -- false positives (flagging a non-spec comment as a gap) are acceptable because the rule is "no comments in production."

### Integration Strategy

The edit-in-place engine does NOT delete the existing refinement workflow. It provides an *alternative entry point* that can be used instead of Phase 1 sectionization for Python-native specs. The existing markdown-based workflow continues to work for document-based specs.

## Plans

### Plan 1: Core Data Structures

**Goal**: Define the data structures that represent parsed Python source as a spec.

**File to create**: `scripts/spec_manager/spec_manager/core/edit_in_place.py`

**Data structures**:

```python
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class TranslationState(enum.Enum):
    """Lifecycle state of a spec element (comment or function)."""
    UNRESOLVED = "unresolved"      # Pure pseudocode comment, no code yet
    STUB = "stub"                  # Function exists but body is pass/NotImplementedError/...
    PARTIAL = "partial"            # Function has some code but still has spec comments
    IMPLEMENTED = "implemented"    # Function has code, no remaining spec comments
    VERIFIED = "verified"          # Function has code + tests pass


class CommentKind(enum.Enum):
    """Classification of a comment token."""
    SPEC = "spec"                  # Unimplemented spec element (IS a gap)
    TODO = "todo"                  # Explicit TODO/FIXME marker (IS a gap)
    INFRASTRUCTURE = "infra"       # Type-ignore, noqa, pragma, encoding, shebang
    SECTION_MARKER = "section"     # Visual separator (# ---- ... ----)


@dataclass(frozen=True)
class SpecComment:
    """A single comment token classified as a spec element."""
    file: str
    line: int
    col_offset: int
    text: str                      # Comment text without leading '# '
    raw: str                       # Full token string including '#'
    kind: CommentKind
    enclosing_function: str | None  # Qualified name of enclosing function, or None if module-level


@dataclass(frozen=True)
class FunctionInfo:
    """Information about a parsed function definition."""
    name: str                       # Simple name
    qualified_name: str             # Dotted path: module.Class.method
    file: str
    line_start: int
    line_end: int
    col_offset: int
    is_async: bool
    decorators: list[str]           # Decorator names
    args: list[str]                 # Parameter names (no types, just names for addressing)
    return_annotation: str | None   # Return type annotation as string, if present
    docstring: str | None           # First string expression in body, if present
    body_line_count: int            # Number of lines in the function body
    translation_state: TranslationState
    spec_comments: list[SpecComment]  # Spec comments inside this function
    stub_reason: str | None         # If STUB: "pass", "ellipsis", "not_implemented"


@dataclass
class FileTranslationState:
    """Complete translation state snapshot for a single Python file.
    
    This is the primary output of the edit-in-place engine.
    It replaces the old Phase 0 extraction output.
    """
    file: str
    content_hash: str               # SHA-256 of file content for change detection
    functions: list[FunctionInfo]    # All function/method definitions found
    module_comments: list[SpecComment]  # Spec comments at module level (not inside any function)
    all_comments: list[SpecComment]  # Every comment token in the file, classified
    
    # Computed summaries
    total_spec_comments: int         # Count of SPEC + TODO comments
    total_functions: int
    stub_count: int                  # Functions in STUB state
    partial_count: int               # Functions in PARTIAL state
    implemented_count: int           # Functions in IMPLEMENTED state
    unresolved_count: int            # Functions in UNRESOLVED state (all comments, no code)

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
```

**What this replaces**: Nothing directly. These are new data structures. But they will eventually replace the role of `TrackedUnit` from `provenance.py` for Python source files, and `GapElement`/`DetectorFinding` from `gaps.py` for gap detection in algorithmic code.

**Tests to create**: `scripts/spec_manager/spec_manager/core/tests/test_edit_in_place.py`

- Test `TranslationState` enum values
- Test `CommentKind` enum values
- Test `SpecComment` frozen dataclass construction
- Test `FunctionInfo` frozen dataclass construction
- Test `FileTranslationState.is_complete` property (true when no gaps, no stubs)
- Test `FileTranslationState.completion_ratio` calculation
- Test `FileTranslationState.gaps` filtering
- Test `ProjectTranslationState` aggregation

---

### Plan 2: Comment Classifier

**Goal**: Implement the tokenize-based comment scanner and classifier.

**File**: `scripts/spec_manager/spec_manager/core/edit_in_place.py` (add to same module)

**Function signatures**:

```python
# ---- Denylist patterns for non-spec comments ----

_INFRASTRUCTURE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^#\s*type:\s*ignore"),           # type: ignore[...]
    re.compile(r"^#\s*noqa"),                      # noqa: E501
    re.compile(r"^#\s*pragma:\s*no\s*cover"),      # pragma: no cover
    re.compile(r"^#\s*pylint:\s*(disable|enable)"), # pylint directives
    re.compile(r"^#\s*fmt:\s*(on|off)"),           # black/ruff format directives
    re.compile(r"^#\s*isort:\s*(skip|on|off)"),    # isort directives
    re.compile(r"^#!"),                             # shebang
    re.compile(r"^#\s*-\*-\s*coding"),             # encoding declarations
    re.compile(r"^#\s*mypy:\s*"),                  # mypy directives
    re.compile(r"^#\s*ruff:\s*"),                  # ruff directives
]

_SECTION_MARKER_PATTERN: re.Pattern[str] = re.compile(
    r"^#\s*[-=]{4,}"                               # # ---- ... ---- or # ==== ... ====
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
    ...


def scan_comments(filepath: str) -> list[SpecComment]:
    """Scan a Python file and return all comments with classification.
    
    Uses tokenize.generate_tokens to find every COMMENT token.
    For each, determines the enclosing function (if any) by cross-referencing
    with ast.parse results.
    
    Args:
        filepath: Path to a Python source file.
        
    Returns:
        List of SpecComment objects for every comment in the file.
    """
    ...
```

**Implementation details**:

1. Use `tokenize.generate_tokens(f.readline)` to get every `COMMENT` token
2. For each token, run through `_INFRASTRUCTURE_PATTERNS` -- if any match, classify as `INFRASTRUCTURE`
3. Check `_SECTION_MARKER_PATTERN` -- if match, classify as `SECTION_MARKER`
4. Check `_TODO_PATTERN` -- if match, classify as `TODO`
5. Otherwise classify as `SPEC`
6. To determine `enclosing_function`, pre-parse with `ast.parse()` and build a line-range map of all `FunctionDef`/`AsyncFunctionDef` nodes. For each comment's line number, find the innermost enclosing function.

**Tests**:

- `test_classify_comment_spec`: plain comment -> SPEC
- `test_classify_comment_type_ignore`: `# type: ignore` -> INFRASTRUCTURE
- `test_classify_comment_noqa`: `# noqa: E501` -> INFRASTRUCTURE
- `test_classify_comment_pragma`: `# pragma: no cover` -> INFRASTRUCTURE
- `test_classify_comment_shebang`: `#!/usr/bin/env python` -> INFRASTRUCTURE
- `test_classify_comment_encoding`: `# -*- coding: utf-8 -*-` -> INFRASTRUCTURE
- `test_classify_comment_section_marker`: `# ---- atoms ----` -> SECTION_MARKER
- `test_classify_comment_todo`: `# TODO: implement this` -> TODO
- `test_classify_comment_fixme`: `# FIXME: broken logic` -> TODO
- `test_scan_comments_simple_file`: scan a file with mixed comment types
- `test_scan_comments_enclosing_function`: verify enclosing function detection
- `test_scan_comments_nested_class_method`: verify qualified name for class methods
- `test_scan_comments_empty_file`: no comments -> empty list

---

### Plan 3: Function Analyzer (Stub and State Detection)

**Goal**: Implement the `ast`-based function analyzer that detects stubs and determines translation state.

**File**: `scripts/spec_manager/spec_manager/core/edit_in_place.py` (add to same module)

**Function signatures**:

```python
def _is_stub_body(body: list[ast.stmt]) -> tuple[bool, str | None]:
    """Check if a function body is a stub.
    
    A function is a stub if its body consists entirely of:
    - pass statement(s)
    - Ellipsis literal (...)
    - raise NotImplementedError(...)
    - A docstring followed by any of the above
    
    Args:
        body: The body of an ast.FunctionDef node.
        
    Returns:
        (is_stub, reason) where reason is "pass", "ellipsis", or "not_implemented"
    """
    ...


def _get_docstring(body: list[ast.stmt]) -> str | None:
    """Extract docstring from function body (first Expr node with Constant str)."""
    ...


def _compute_qualified_name(node: ast.FunctionDef | ast.AsyncFunctionDef, 
                             parents: list[ast.AST]) -> str:
    """Compute dotted qualified name from AST node and its parent chain.
    
    Examples:
        - Top-level function: "validate_payment"
        - Method: "PaymentService.validate"
        - Nested class method: "Outer.Inner.method"
    """
    ...


def _determine_translation_state(func_node: ast.FunctionDef | ast.AsyncFunctionDef,
                                  spec_comments: list[SpecComment],
                                  is_stub: bool) -> TranslationState:
    """Determine the translation state of a function.
    
    Logic:
    - If is_stub and has spec comments: UNRESOLVED
    - If is_stub and no spec comments: STUB  
    - If not stub and has spec comments: PARTIAL
    - If not stub and no spec comments: IMPLEMENTED
    
    Note: VERIFIED requires external test results, not determined here.
    """
    ...


def analyze_functions(filepath: str, 
                       comments: list[SpecComment]) -> list[FunctionInfo]:
    """Analyze all function definitions in a Python file.
    
    Uses ast.parse to walk the AST. For each FunctionDef/AsyncFunctionDef:
    1. Extract name, qualified name, line range, decorators, args, return annotation
    2. Check if body is a stub
    3. Cross-reference with comments to find spec comments inside this function
    4. Determine translation state
    
    Args:
        filepath: Path to Python source file.
        comments: Pre-scanned comments from scan_comments().
        
    Returns:
        List of FunctionInfo for every function/method in the file.
    """
    ...
```

**Implementation details**:

- Walk the AST using `ast.walk()` but maintain parent chain for qualified name computation
- Use a custom `ast.NodeVisitor` subclass that tracks class nesting for qualified names
- For each function, get the line range from `node.lineno` to `node.end_lineno`
- Filter `comments` list to those whose `line` falls within the function's range
- Decorators are extracted as simple name strings from `node.decorator_list`

**Tests**:

- `test_is_stub_pass`: body with `pass` -> `(True, "pass")`
- `test_is_stub_ellipsis`: body with `...` -> `(True, "ellipsis")`
- `test_is_stub_not_implemented`: body with `raise NotImplementedError()` -> `(True, "not_implemented")`
- `test_is_stub_docstring_plus_pass`: docstring then pass -> `(True, "pass")`
- `test_is_stub_real_code`: body with actual logic -> `(False, None)`
- `test_determine_state_unresolved`: stub + comments -> UNRESOLVED
- `test_determine_state_stub`: stub + no comments -> STUB
- `test_determine_state_partial`: real code + comments -> PARTIAL
- `test_determine_state_implemented`: real code + no comments -> IMPLEMENTED
- `test_analyze_functions_mixed`: file with stubs, partials, and implemented functions
- `test_analyze_functions_class_methods`: qualified names for class methods
- `test_analyze_functions_async`: async functions correctly detected
- `test_analyze_functions_nested`: nested functions handled correctly
- `test_analyze_functions_decorators`: decorator names extracted

---

### Plan 4: File-Level Orchestrator

**Goal**: Wire together comment scanning and function analysis into the `FileTranslationState` and `ProjectTranslationState` outputs.

**File**: `scripts/spec_manager/spec_manager/core/edit_in_place.py` (add to same module)

**Function signatures**:

```python
import hashlib


def analyze_file(filepath: str) -> FileTranslationState:
    """Analyze a single Python file and produce its translation state.
    
    This is the main entry point for single-file analysis.
    
    Steps:
    1. Read file content and compute content_hash
    2. scan_comments() to get all classified comments
    3. analyze_functions() to get all function info with states
    4. Separate module-level spec comments (not inside any function)
    5. Compute summary counts
    6. Return FileTranslationState
    
    Args:
        filepath: Absolute path to a Python source file.
        
    Returns:
        FileTranslationState snapshot.
        
    Raises:
        FileNotFoundError: If filepath does not exist.
        SyntaxError: If the file cannot be parsed (not valid Python).
    """
    ...


def analyze_project(root: str, 
                     include: list[str] | None = None,
                     exclude: list[str] | None = None) -> ProjectTranslationState:
    """Analyze all Python files in a project directory.
    
    Args:
        root: Root directory to scan.
        include: Glob patterns to include (default: ["**/*.py"]).
        exclude: Glob patterns to exclude (default: ["**/test_*", "**/__pycache__/**"]).
        
    Returns:
        ProjectTranslationState with per-file states.
    """
    ...


def find_gaps(state: FileTranslationState | ProjectTranslationState) -> list[SpecComment]:
    """Extract all gap-type comments from a translation state.
    
    This is the completeness detector. Returns every comment that
    represents unimplemented spec.
    
    Args:
        state: Either a single file or project translation state.
        
    Returns:
        List of SpecComment objects with kind SPEC or TODO.
    """
    ...


def format_gap_report(state: ProjectTranslationState) -> str:
    """Format a human-readable gap report from project translation state.
    
    Output format:
    
    ```
    # Gap Report
    
    ## Summary
    - Files analyzed: 15
    - Total functions: 87
    - Implemented: 62 (71.3%)
    - Partial: 12 (13.8%)
    - Stubs: 8 (9.2%)
    - Unresolved: 5 (5.7%)
    - Remaining spec comments: 34
    
    ## Gaps by File
    
    ### path/to/module.py (7 gaps)
    - L23 [process_order] # validate payment against fraud rules
    - L24 [process_order] # apply discount based on customer tier
    - L45 [module-level] # TODO: add retry configuration
    ...
    ```
    """
    ...
```

**Tests**:

- `test_analyze_file_simple`: analyze a simple Python file with known structure
- `test_analyze_file_all_implemented`: file with no comments -> `is_complete == True`
- `test_analyze_file_all_stubs`: file with all stubs -> counts correct
- `test_analyze_file_mixed`: file with mix of states -> correct counts
- `test_analyze_file_not_found`: raises FileNotFoundError
- `test_analyze_file_syntax_error`: invalid Python raises SyntaxError
- `test_analyze_project`: directory with multiple files
- `test_analyze_project_exclude`: exclude patterns work
- `test_find_gaps_file`: gaps extracted from file state
- `test_find_gaps_project`: gaps extracted from project state
- `test_format_gap_report`: report formatting matches expected output

---

### Plan 5: Integration Bridge to Existing Refinement Workflow

**Goal**: Create adapter functions that bridge the edit-in-place engine output to the existing refinement data structures, enabling gradual adoption.

**File to create**: `scripts/spec_manager/spec_manager/core/edit_in_place_bridge.py`

**Function signatures**:

```python
from spec_manager.core.edit_in_place import (
    FileTranslationState,
    FunctionInfo,
    ProjectTranslationState,
    SpecComment,
)
from spec_manager.refinement.core.gap import Gap, GapEvidence, GapType
from spec_manager.refinement.core.gap_queue import GapQueue
from spec_manager.core.provenance import TrackedUnit, UnitType, SourceLocation, UnitStatus


def spec_comment_to_gap(comment: SpecComment) -> Gap:
    """Convert a SpecComment into a refinement Gap.
    
    Maps:
    - SpecComment.kind SPEC -> GapType.missing_detail
    - SpecComment.kind TODO -> GapType.ambiguity
    - Evidence is the comment text + location
    - Source is file:line
    - Severity is always 'error' (spec comments = must-resolve)
    """
    ...


def function_info_to_tracked_unit(func: FunctionInfo) -> TrackedUnit:
    """Convert a FunctionInfo into a TrackedUnit for provenance tracking.
    
    Maps:
    - FunctionInfo -> TrackedUnit with UnitType.ALGORITHM
    - SourceLocation from function's file + line range
    - Status based on translation state:
        UNRESOLVED/STUB -> UnitStatus.PENDING
        PARTIAL -> UnitStatus.PENDING
        IMPLEMENTED -> UnitStatus.PROCESSED
        VERIFIED -> UnitStatus.MAPPED
    """
    ...


def file_state_to_gap_queue(state: FileTranslationState) -> GapQueue:
    """Convert a FileTranslationState into a GapQueue for the existing workflow.
    
    Creates a Gap for each spec comment and each stub function,
    wraps them in a GapQueue with stagnation tracking.
    """
    ...


def project_state_to_gap_queue(state: ProjectTranslationState) -> GapQueue:
    """Convert ProjectTranslationState to a single GapQueue."""
    ...
```

**What this replaces/integrates with**:

- `spec_manager.core.gap_compat.py` -- similar adapter pattern (v1 -> v2 gap conversion). The bridge follows the same pattern but for edit-in-place -> refinement gaps.
- `spec_manager.refinement.workflows.phase_01_sectionization.py` -- the bridge allows Phase 1 to be *skipped* for Python-native specs. Instead of running LLM-based sectionization, call `analyze_project()` and pipe through the bridge.
- The `Phase` enum in `scripts/spec_manager/spec_manager/refinement/workspace/state.py` will need a new value `EDIT_IN_PLACE = "edit_in_place"` to represent this alternative entry point.

**Tests**:

- `test_spec_comment_to_gap`: conversion produces valid Gap with correct fields
- `test_function_info_to_tracked_unit`: conversion produces valid TrackedUnit
- `test_file_state_to_gap_queue`: GapQueue has correct gap count
- `test_project_state_to_gap_queue`: aggregation across files

---

### Plan 6: CLI Integration

**Goal**: Add a CLI command to run the edit-in-place analysis and produce gap reports.

**File to modify**: `scripts/spec_manager/spec_manager/cli.py`

**New command**:

```
uv run python -m spec_manager analyze <path> [--exclude PATTERN] [--format json|text] [--output FILE]
```

**Implementation**:

- Add `analyze` subcommand to the existing CLI argument parser
- Calls `analyze_file()` for a single `.py` file or `analyze_project()` for a directory
- `--format text` (default): calls `format_gap_report()`
- `--format json`: serializes `ProjectTranslationState` to JSON
- `--output FILE`: writes to file instead of stdout

**File to modify**: `scripts/spec_manager/spec_manager/cli.py` (add the `analyze` subcommand handler)

**Tests**:

- Integration test: run CLI on a test fixture directory, verify output
- Test `--format json` produces valid JSON
- Test `--format text` produces readable report

## Execution Instructions

Execute plans in strict sequential order (1 through 6). Each plan builds on the previous.

**Plan 1** (Data Structures): Create the file `scripts/spec_manager/spec_manager/core/edit_in_place.py` with all dataclass definitions. Create test file. Run tests.

**Plan 2** (Comment Classifier): Add `classify_comment()` and `scan_comments()` to the module. Add tests. Run tests.

**Plan 3** (Function Analyzer): Add `_is_stub_body()`, `_determine_translation_state()`, and `analyze_functions()`. Add tests. Run tests.

**Plan 4** (File-Level Orchestrator): Add `analyze_file()`, `analyze_project()`, `find_gaps()`, and `format_gap_report()`. Add tests. Run tests.

**Plan 5** (Integration Bridge): Create `scripts/spec_manager/spec_manager/core/edit_in_place_bridge.py`. Add `EDIT_IN_PLACE` to the `Phase` enum. Add tests. Run tests.

**Plan 6** (CLI Integration): Add `analyze` subcommand to CLI. Add integration tests. Run tests.

After all plans, run the full test suite to verify no regressions: `uv run pytest scripts/spec_manager/ -p no:randomly`

## Success Criteria

1. **Mechanical gap detection**: `analyze_file()` on a Python file with 5 spec comments returns `FileTranslationState` with `total_spec_comments == 5` -- no LLM call required.

2. **Stub detection**: A file containing `def foo(): pass` produces `FunctionInfo` with `translation_state == TranslationState.STUB`.

3. **Comment classification accuracy**: Infrastructure comments (`type: ignore`, `noqa`, `pragma`, shebang, encoding) are never classified as spec comments. All tests in Plan 2 pass.

4. **Completeness invariant**: A file with zero comments and zero stubs produces `FileTranslationState.is_complete == True`.

5. **State transitions**: Functions with mixed code and comments are classified as `PARTIAL`. Functions with only comments in a stub body are `UNRESOLVED`. Functions with code and no comments are `IMPLEMENTED`.

6. **Bridge compatibility**: `spec_comment_to_gap()` produces a `Gap` object that is accepted by the existing `GapQueue`. `function_info_to_tracked_unit()` produces a `TrackedUnit` compatible with `ProvenanceTracker`.

7. **No regressions**: Existing test suite continues to pass after all changes. No modifications to existing workflow files except adding the `Phase.EDIT_IN_PLACE` enum value.

8. **CLI works**: `uv run python -m spec_manager analyze scripts/spec_manager/spec_manager/core/edit_in_place.py` produces a gap report for the engine itself (eating our own dogfood).
