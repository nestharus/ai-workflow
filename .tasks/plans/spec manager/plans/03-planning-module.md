# Implementation Plan: Planning Module (New Work Ingestion)

## Overview

Build the planning module that turns intentions into pseudocode comments inserted into algorithmic code files, replaces the current `planning/` and `decomposition/` modules with the edit-in-place paradigm from the algorithmic projection model, and integrates with hollowed-out spec evidence for ambiguity resolution.

## Current State (Problems)

### Existing `planning/` module (`scripts/spec_manager/spec_manager/planning/`)
- **operations.py**: Focused on ID comparison, sequence checking, batch creation for moving spec IDs between registry/libraries. This is a *discovery-phase* tool for managing spec document IDs -- it has nothing to do with inserting pseudocode comments into code.
- Two files total (`__init__.py`, `operations.py`). Data structures: `IdComparison`, `SequenceIssue`, `Batch`, `PlanningResult`. All operate on `LibsRegistry` and `SectionExtractor` -- spec-document primitives, not code-level primitives.

### Existing `decomposition/` module (`scripts/spec_manager/spec_manager/decomposition/`)
- 10 files: entity_index, extract, finalize, id_generator, staging, tagging, workspace, recompose, execution, cli.
- Focuses on breaking spec documents into entities, staging snippets, tagging facts, recomposing -- all operating on spec documents, not on code files.
- `execution.py` tracks implementation against decomposed specs via a ledger (`SpecEntry`, `SpecStatus`), but has no concept of pseudocode comments or code-level insertion.

### Existing `tasks.py` workflow (`scripts/spec_manager/spec_manager/refinement/workflows/tasks.py`)
- Builds task planning context from spec indexes, edge lists, architecture mappings.
- Generates task plans via LLM agent (`opus-task-planner`), validates coverage, writes task artifacts.
- Task plans are JSON objects with element/edge/decision coverage -- they do not produce pseudocode comments in code files.

### Gap summary
None of the existing modules implement:
1. Parsing real code to find insertion points for new pseudocode comments
2. Reverse-translating existing code back to pseudocode comments
3. Decomposing plans into micro-unit comments (one comment = one logical step)
4. Adjacent detail discovery via call graph analysis
5. Integration with hollowed-out spec evidence for ambiguity resolution

## Target State

A `planning_v2/` module that:
1. **Inserts** pseudocode comments at context-appropriate locations in algorithmic code files
2. **Reverse-translates** existing code into pseudocode comments for replanning sections
3. **Decomposes** high-level intentions into micro-unit comments (single responsibility each)
4. **Discovers** adjacent details via call graph + store-touch analysis
5. **Integrates** with hollowed-out spec evidence to resolve ambiguities during planning
6. Provides CLI commands for all operations
7. Replaces the conceptual role of `planning/` and `decomposition/` for the new paradigm (existing modules remain for backward compatibility with spec-document workflows)

## Additional Info

### Conventions (from `docs/development/`)
- Agents are invoked via `run_agent()` in `refinement/agent_utils.py` using `uv run agents <agent-name> --file <prompt-file> --project <root>`
- Schemas use Pydantic `BaseModel` (see `schemas/` directory)
- Workspace state is managed via `WorkspaceManager` with `Phase` enum in `refinement/workspace/state.py`
- LLM output parsing handles code fences, single-quote JSON, repair loops
- All IDs follow patterns: `ATOM-F####-R####-L####`, `PIN-####`, `LIB-####`, etc.

### Key design decisions from Section 4 of algorithmic-projection-patch.md
- Comments ARE the spec. No separate planning document.
- Each comment is a micro-plan sitting in context relative to existing code.
- Reverse translation reopens completed sections for redesign.
- Call graph analysis reveals adjacent details after comment insertion.
- Hollowed-out specs serve as evidence stores for ambiguity resolution (Section 8).

### Language-specific from day one
- Pseudocode comments live inside real function signatures in a real language (Python first).
- Every stage is parseable. The gap between spec and code is zero.

---

## Plans

### Plan 1: Core Data Structures and Code Parser

**Goal**: Define the foundational data structures and build a Python-specific code parser that can identify insertion points, extract function structures, and detect existing pseudocode comments.

**Files to create**:

1. `scripts/spec_manager/spec_manager/planning_v2/__init__.py`
2. `scripts/spec_manager/spec_manager/planning_v2/models.py`
3. `scripts/spec_manager/spec_manager/planning_v2/code_parser.py`

**Data structures** (`models.py`):

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CommentKind(str, Enum):
    """Classification of a pseudocode comment."""
    PLAN = "plan"               # New plan comment (unimplemented)
    REVERSE = "reverse"         # Reverse-translated from existing code
    ANNOTATION = "annotation"   # Non-spec comment (docstring, TODO, etc.)


@dataclass(frozen=True)
class PseudocodeComment:
    """A single pseudocode comment in algorithmic code.

    Each comment is a micro-plan: one logical step, single responsibility.
    """
    file_path: str               # Absolute path to source file
    line_no: int                 # 1-based line number
    text: str                    # Comment text (stripped of '# ')
    kind: CommentKind            # Classification
    indent_level: int            # Number of leading spaces
    function_name: str | None    # Enclosing function name, if any
    class_name: str | None       # Enclosing class name, if any


@dataclass(frozen=True)
class InsertionPoint:
    """A location in code where a new pseudocode comment can be inserted.

    Context-aware: knows what comes before and after.
    """
    file_path: str
    line_no: int                 # Line number AFTER which to insert
    indent_level: int
    function_name: str | None
    preceding_code: str          # The code line before this point
    following_code: str          # The code line after this point
    rationale: str               # Why this is a valid insertion point


@dataclass(frozen=True)
class FunctionInfo:
    """Extracted information about a function in the code."""
    name: str
    file_path: str
    start_line: int              # 1-based
    end_line: int                # 1-based, inclusive
    indent_level: int
    parameters: list[str]
    return_annotation: str | None
    docstring: str | None
    body_lines: list[str]        # Raw body lines
    calls: list[str]             # Function names called within this function
    comments: list[PseudocodeComment]  # Existing comments in the body
    class_name: str | None       # Enclosing class, if any
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
    source_intention: str        # The high-level intention being decomposed
    evidence_refs: list[str]     # References to spec evidence used


@dataclass
class ReversePlan:
    """A plan to reverse-translate code back to pseudocode comments."""
    file_path: str
    function_name: str
    start_line: int
    end_line: int
    generated_comments: list[PseudocodeComment]
    original_code: str           # The code that was reverse-translated


@dataclass
class AdjacentDetail:
    """An adjacent detail discovered via call graph or store analysis."""
    source_function: str         # The function being planned
    related_function: str        # The adjacent function
    relationship: str            # "calls", "called_by", "shared_store", "shared_event"
    store_or_event: str | None   # Name of shared store/event if applicable
    has_test_coverage: bool      # Whether the related function has tests
    needs_plan: bool             # Whether this needs its own planning pass
```

**Code parser** (`code_parser.py`):

```python
def parse_file(file_path: str) -> CodeFile:
    """Parse a Python file into a CodeFile structure using ast + tokenize."""

def find_insertion_points(code_file: CodeFile, function_name: str) -> list[InsertionPoint]:
    """Find valid insertion points within a function.

    Insertion points are between statements, respecting control flow.
    Each point knows its context (what comes before/after).
    """

def extract_comments(file_path: str) -> list[PseudocodeComment]:
    """Extract all pseudocode comments from a file using tokenize.

    Uses tokenize.generate_tokens to find COMMENT tokens.
    Classifies each as PLAN, REVERSE, or ANNOTATION based on heuristics.
    """

def extract_function_calls(function: FunctionInfo) -> list[str]:
    """Extract all function calls within a function body using ast.walk."""

def detect_stubs(code_file: CodeFile) -> list[FunctionInfo]:
    """Find stub functions (pass, raise NotImplementedError, Ellipsis body)."""
```

**Implementation details**:
- Uses `ast` module to parse Python files and walk the AST for function definitions, calls, class structures.
- Uses `tokenize` module to extract comments (since `ast` strips comments).
- Combines both to produce `CodeFile` with full function info including comments.
- Comment classification heuristic: comments containing verbs like "validate", "check", "apply", "send", "compute" etc. are classified as `PLAN`; comments starting with "Reverse-translated:" or similar marker are `REVERSE`; everything else is `ANNOTATION`.

**Tests**: `scripts/spec_manager/tests/planning_v2/test_models.py`, `scripts/spec_manager/tests/planning_v2/test_code_parser.py`

---

### Plan 2: Comment Insertion Engine

**Goal**: Build the engine that inserts pseudocode comments at the right locations in code files, with context-aware placement logic.

**Files to create**:

1. `scripts/spec_manager/spec_manager/planning_v2/inserter.py`

**Public API** (`inserter.py`):

```python
def plan_insertions(
    intention: str,
    code_file: CodeFile,
    function_name: str,
    evidence_store: EvidenceStore | None = None,
) -> InsertionPlan:
    """Decompose an intention into micro-unit comments and determine placement.

    Steps:
    1. Parse the intention into micro-units via LLM (one comment per logical step)
    2. Analyze the target function to find valid insertion points
    3. Match each micro-unit to the best insertion point based on context
    4. Query evidence store for ambiguity resolution if details are unclear

    Args:
        intention: High-level description of new work (e.g. "add fraud detection to payment flow")
        code_file: Parsed code file
        function_name: Target function to insert into
        evidence_store: Optional hollowed-out spec evidence for ambiguity resolution

    Returns:
        InsertionPlan with ordered (InsertionPoint, comment_text) pairs
    """

def apply_insertion_plan(plan: InsertionPlan) -> str:
    """Apply an InsertionPlan to produce modified file content.

    Reads the file, inserts comments at specified locations,
    returns the modified content as a string. Does NOT write to disk.

    Insertions are applied bottom-up to preserve line numbers.
    """

def decompose_intention(
    intention: str,
    function_context: FunctionInfo,
    agent_name: str = "opus-plan-decomposer",
) -> list[str]:
    """Decompose a high-level intention into micro-unit comment texts via LLM.

    Each returned string is a single-responsibility pseudocode comment.
    The LLM sees the function context (signature, existing code, existing comments)
    to produce contextually relevant decomposition.

    Returns:
        List of comment text strings (without '# ' prefix)
    """

def match_comments_to_insertion_points(
    comments: list[str],
    insertion_points: list[InsertionPoint],
    function: FunctionInfo,
) -> list[tuple[InsertionPoint, str]]:
    """Match decomposed comments to the best insertion points.

    Uses semantic similarity between comment text and surrounding code context
    to determine optimal placement. Falls back to sequential ordering when
    context is ambiguous.
    """
```

**Agent integration**:
- New agent: `opus-plan-decomposer` -- takes an intention + function context, returns JSON list of micro-unit comment strings.
- Agent definition file: `.agents/agents/opus-plan-decomposer.md`

**Implementation details**:
- Bottom-up insertion: when applying multiple insertions to a file, process from last line to first to avoid line-number shifting.
- Indent matching: each inserted comment matches the indent level of the surrounding code.
- Blank line handling: insert a blank line before/after comment blocks when the surrounding code has blank line conventions.

**Tests**: `scripts/spec_manager/tests/planning_v2/test_inserter.py`

---

### Plan 3: Reverse Translation Engine

**Goal**: Build the engine that translates existing code back into pseudocode comments for replanning sections.

**Files to create**:

1. `scripts/spec_manager/spec_manager/planning_v2/reverser.py`

**Public API** (`reverser.py`):

```python
def reverse_translate(
    code_file: CodeFile,
    function_name: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> ReversePlan:
    """Reverse-translate code back to pseudocode comments.

    Replaces implementation code with comments describing what it did.
    This "reopens" a completed section for redesign.

    If start_line/end_line are specified, only that range is reversed.
    Otherwise the entire function body is reversed.

    Args:
        code_file: Parsed code file
        function_name: Function to reverse-translate
        start_line: Optional start of range (1-based)
        end_line: Optional end of range (1-based)

    Returns:
        ReversePlan with generated comments and original code
    """

def apply_reverse_plan(plan: ReversePlan) -> str:
    """Apply a ReversePlan to produce modified file content.

    Replaces the specified code range with generated pseudocode comments.
    Preserves function signature, decorators, and docstring.
    Returns modified content as string. Does NOT write to disk.
    """

def _generate_pseudocode_comments(
    code_lines: list[str],
    function_context: FunctionInfo,
    agent_name: str = "opus-reverse-translator",
) -> list[str]:
    """Use LLM to generate pseudocode comments from code.

    The LLM receives:
    - The code lines to reverse-translate
    - The function signature and docstring for context
    - Instructions to produce one comment per logical step

    Returns:
        List of comment text strings preserving intent, not implementation detail
    """
```

**Agent integration**:
- New agent: `opus-reverse-translator` -- takes code + context, returns JSON list of pseudocode comment strings that preserve intent.
- Agent definition file: `.agents/agents/opus-reverse-translator.md`

**Implementation details**:
- Reverse translation preserves intent, not implementation details. "validate_payment(order.payment)" becomes "# validate payment against fraud rules", not "# call validate_payment with order.payment argument".
- Groups related code lines into single comments where they form one logical step.
- Adds `# [reverse-translated]` marker to generated comments for traceability.

**Tests**: `scripts/spec_manager/tests/planning_v2/test_reverser.py`

---

### Plan 4: Adjacent Detail Discovery

**Goal**: Build the call graph analysis and store-touch detection that discovers adjacent details when new comments are added.

**Files to create**:

1. `scripts/spec_manager/spec_manager/planning_v2/adjacency.py`

**Public API** (`adjacency.py`):

```python
def build_call_graph(code_files: list[CodeFile]) -> CallGraph:
    """Build a call graph from parsed code files.

    Nodes are function names (qualified: module.class.function or module.function).
    Edges are call relationships extracted from AST.
    """

def find_store_touches(code_files: list[CodeFile]) -> list[StoreTouchEdge]:
    """Detect store access patterns (database calls, file I/O, queue operations).

    Identifies functions that read/write shared state.
    Two functions touching the same store are adjacent even if they never call each other.
    """

def discover_adjacent_details(
    modified_function: str,
    call_graph: CallGraph,
    store_touches: list[StoreTouchEdge],
    test_coverage: dict[str, bool] | None = None,
) -> list[AdjacentDetail]:
    """Discover adjacent details that interact with the modified function.

    After adding new comments, this reveals:
    1. Functions called by the modified function (downstream impact)
    2. Functions that call the modified function (upstream impact)
    3. Functions sharing stores with the modified function (hidden coupling)
    4. Functions sharing events with the modified function (event coupling)

    For each adjacent detail, checks test coverage. Anything touched
    that lacks test coverage is flagged as needing its own plan.
    """


@dataclass
class CallGraph:
    """Directed graph of function calls."""
    nodes: set[str]                          # Qualified function names
    edges: list[tuple[str, str]]             # (caller, callee)
    reverse_edges: dict[str, set[str]]       # callee -> set of callers

    def callees(self, function: str) -> set[str]: ...
    def callers(self, function: str) -> set[str]: ...
    def transitive_callees(self, function: str, depth: int = 3) -> set[str]: ...
    def transitive_callers(self, function: str, depth: int = 3) -> set[str]: ...


@dataclass
class StoreTouchEdge:
    """A function's access to a shared store."""
    function_name: str
    store_name: str              # Inferred store identifier
    access_type: str             # "read", "write", "read_write"
    line_no: int
    file_path: str
```

**Implementation details**:
- Call graph is built from `ast.Call` nodes within function bodies. Resolves names through imports where possible.
- Store-touch detection uses heuristics: calls to known DB libraries (sqlalchemy, sqlite3, etc.), file open/write patterns, queue push/pop patterns.
- Depth-limited transitive closure prevents explosion on large codebases.
- Test coverage integration is optional -- when not provided, `has_test_coverage` defaults to `False` (conservative, flags everything).

**Tests**: `scripts/spec_manager/tests/planning_v2/test_adjacency.py`

---

### Plan 5: Evidence Store Integration (Hollowed-Out Specs)

**Goal**: Build the integration with hollowed-out spec evidence so that planning can resolve ambiguities by searching complete specification documents.

**Files to create**:

1. `scripts/spec_manager/spec_manager/planning_v2/evidence_store.py`

**Public API** (`evidence_store.py`):

```python
class EvidenceStore:
    """Interface to hollowed-out spec evidence for ambiguity resolution.

    When planning hits an ambiguity ("validate payment against fraud rules" --
    but what fraud rules?), the evidence store is searched for answers.
    """

    def __init__(
        self,
        spec_snapshot_dir: Path,
        libraries_dir: Path,
    ) -> None:
        """Initialize from workspace directories.

        Loads spec indexes and library charters for search.
        Does NOT load full spec content upfront (lazy/hollowed approach).
        """

    def search(
        self,
        query: str,
        context: str | None = None,
        max_results: int = 5,
    ) -> list[EvidenceHit]:
        """Search spec evidence for details matching a query.

        Uses keyword matching and section-level indexing.
        Loads full spec content only for matching sections (needle-in-haystack).

        Args:
            query: Search query (e.g. "fraud rules payment validation")
            context: Optional function/code context to narrow results
            max_results: Maximum number of results to return
        """

    def resolve_ambiguity(
        self,
        comment_text: str,
        function_context: FunctionInfo,
        agent_name: str = "opus-ambiguity-resolver",
    ) -> AmbiguityResolution:
        """Resolve an ambiguity in a pseudocode comment using spec evidence.

        1. Extract keywords from comment and function context
        2. Search evidence store
        3. If evidence found: use LLM to synthesize answer
        4. If no evidence: flag as genuine spec gap

        Returns:
            AmbiguityResolution with answer or gap flag
        """


@dataclass(frozen=True)
class EvidenceHit:
    """A single search result from the evidence store."""
    lib_id: str
    section_heading: str
    element_id: str | None
    excerpt: str                 # Relevant excerpt from spec
    relevance_score: float       # 0.0 to 1.0
    source_path: str             # Path to source spec file


@dataclass(frozen=True)
class AmbiguityResolution:
    """Result of ambiguity resolution."""
    resolved: bool               # Whether the ambiguity was resolved
    answer: str | None           # Synthesized answer if resolved
    evidence_refs: list[str]     # References to evidence used
    gap_description: str | None  # If not resolved, description of the spec gap
    refined_comments: list[str]  # Updated comment texts with resolved details
```

**Implementation details**:
- Lazy loading: only loads spec section content when a search matches the section heading/keywords. This is the "hollowed out" approach -- structure is indexed upfront, content is loaded on demand.
- Reuses existing `SpecIndex`, `DecisionsIndex` schemas from `schemas/spec_indexes.py`.
- Integrates with existing `_load_spec_index`, `_load_decisions_index` patterns from `tasks.py`.
- New agent: `opus-ambiguity-resolver` for synthesizing answers from evidence hits.

**Tests**: `scripts/spec_manager/tests/planning_v2/test_evidence_store.py`

---

### Plan 6: Gap Detection Integration

**Goal**: Wire the planning module into the existing gap detection system so that unimplemented comments and stubs are tracked as gaps.

**Files to create**:

1. `scripts/spec_manager/spec_manager/planning_v2/gap_bridge.py`

**Public API** (`gap_bridge.py`):

```python
def scan_for_gaps(code_files: list[CodeFile]) -> list[Gap]:
    """Scan algorithmic code files for unimplemented spec elements.

    Detects:
    1. Pseudocode comments (every comment = unimplemented spec element)
    2. Stub functions (pass, raise NotImplementedError, Ellipsis)
    3. Functions with no test coverage (if coverage data available)

    Returns Gap objects compatible with the existing gap system
    (spec_manager.refinement.core.gap.Gap).
    """

def comments_to_gaps(comments: list[PseudocodeComment]) -> list[Gap]:
    """Convert pseudocode comments to Gap objects.

    Each PLAN-kind comment becomes a Gap with:
    - gap_type: GapType.MISSING_DETAIL
    - severity: Severity.WARNING
    - description: The comment text
    - evidence: file path and line number
    """

def stubs_to_gaps(stubs: list[FunctionInfo]) -> list[Gap]:
    """Convert stub functions to Gap objects.

    Each stub becomes a Gap with:
    - gap_type: GapType.STUB_FUNCTION
    - severity: Severity.ERROR
    - description: Function name and signature
    """

def adjacencies_to_gaps(adjacencies: list[AdjacentDetail]) -> list[Gap]:
    """Convert adjacent details needing plans to Gap objects.

    Each adjacent detail where needs_plan=True becomes a Gap with:
    - gap_type: GapType.ADJACENT_DETAIL
    - severity: Severity.INFO
    - description: Relationship description
    """
```

**Integration with existing gap system**:
- Uses `Gap`, `GapType`, `GapEvidence`, `Severity` from `spec_manager.refinement.core.gap`
- Uses `GapQueue` from `spec_manager.refinement.core.gap_queue` for persistence
- Gap IDs follow existing patterns (auto-generated)

**Tests**: `scripts/spec_manager/tests/planning_v2/test_gap_bridge.py`

---

### Plan 7: CLI and Workflow Integration

**Goal**: Add CLI commands and integrate with the workspace/phase system so the planning module is usable from the command line and fits into the existing refinement workflow.

**Files to create/modify**:

1. `scripts/spec_manager/spec_manager/planning_v2/cli.py` (create)
2. `scripts/spec_manager/spec_manager/planning_v2/workflow.py` (create)
3. `scripts/spec_manager/spec_manager/cli.py` (modify -- add `plan-v2` subcommand group)
4. `scripts/spec_manager/spec_manager/refinement/workspace/state.py` (modify -- add `PLANNING_V2` to `Phase` enum)

**CLI commands** (`cli.py`):

```python
# plan-v2 insert --file <path> --function <name> --intention <text> [--evidence-dir <path>]
# plan-v2 reverse --file <path> --function <name> [--start-line N] [--end-line N]
# plan-v2 scan --directory <path>   (scan for gaps: unimplemented comments + stubs)
# plan-v2 adjacency --file <path> --function <name> --directory <path>
# plan-v2 decompose --intention <text> --file <path> --function <name>
```

**Workflow** (`workflow.py`):

```python
def run_planning_v2_phase(
    run_id: str,
    target_files: list[str],
    intentions: list[str],
    evidence_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the planning_v2 phase within the refinement workflow.

    Steps:
    1. Parse target files
    2. For each intention, decompose into micro-units
    3. Determine insertion points
    4. Resolve ambiguities via evidence store
    5. Generate InsertionPlans
    6. Discover adjacent details
    7. Convert unresolved items to gaps
    8. Write artifacts (plans, gaps, adjacency report)

    Integrates with WorkspaceManager via Phase.PLANNING_V2.
    """
```

**Phase enum addition** in `state.py`:

```python
class Phase(Enum):
    # ... existing phases ...
    PLANNING_V2 = "planning_v2"  # New: algorithmic planning (edit-in-place)
```

**Modification to main CLI** (`cli.py`):
- Add `plan-v2` as a Click/Typer subcommand group
- Wire to `planning_v2.cli` handlers

**Agent definition files to create**:
- `.agents/agents/opus-plan-decomposer.md`
- `.agents/agents/opus-reverse-translator.md`
- `.agents/agents/opus-ambiguity-resolver.md`

**Tests**: `scripts/spec_manager/tests/planning_v2/test_cli.py`, `scripts/spec_manager/tests/planning_v2/test_workflow.py`

---

## What Gets Replaced/Deleted

The existing modules are NOT deleted -- they continue to serve the spec-document workflow. The new `planning_v2/` module operates alongside them. However:

| Existing Module | New Replacement | Relationship |
|---|---|---|
| `planning/operations.py` (ID comparison, batching) | No direct replacement | Remains for spec-document ID management |
| `decomposition/` (entity extraction, staging) | `planning_v2/inserter.py` (decompose_intention) | New module decomposes into code comments, not spec entities |
| `decomposition/execution.py` (ledger tracking) | `planning_v2/gap_bridge.py` (scan_for_gaps) | Gap detection replaces ledger for tracking unimplemented items |
| `refinement/workflows/tasks.py` (task planning) | `planning_v2/workflow.py` (run_planning_v2_phase) | New workflow produces InsertionPlans, not task JSON |

When the algorithmic projection paradigm is fully adopted, `planning/` and `decomposition/` can be deprecated. That decision is outside the scope of this plan.

---

## Execution Instructions

Execute plans in order (1 through 7). Each plan is independently testable:

1. **Plan 1** has zero dependencies on other new code. Tests validate parsing against real Python files.
2. **Plan 2** depends on Plan 1 data structures. Tests use fixture code files. Agent definition can use a mock.
3. **Plan 3** depends on Plan 1 data structures. Independent of Plan 2.
4. **Plan 4** depends on Plan 1 (`CodeFile`, `FunctionInfo`). Independent of Plans 2-3.
5. **Plan 5** depends on Plan 1 (`FunctionInfo`). Uses existing spec index schemas.
6. **Plan 6** depends on Plans 1 and 4. Bridges to existing gap system.
7. **Plan 7** depends on all previous plans. Integration and CLI wiring.

Plans 2, 3, 4, and 5 can be developed in parallel after Plan 1 is complete.

---

## Success Criteria

1. `parse_file()` correctly parses Python files with functions, classes, comments, and produces `CodeFile` objects -- verified by unit tests against fixture files with known structures.
2. `plan_insertions()` produces `InsertionPlan` objects with comments placed at valid insertion points that respect control flow and indentation -- verified by snapshot tests comparing expected vs actual insertions.
3. `apply_insertion_plan()` produces syntactically valid Python when applied -- verified by running `ast.parse()` on the output.
4. `reverse_translate()` produces `ReversePlan` objects where generated comments preserve function intent -- verified by comparing against hand-written expected comments.
5. `apply_reverse_plan()` produces syntactically valid Python with comments replacing code -- verified by `ast.parse()` plus comment count assertions.
6. `build_call_graph()` correctly identifies call relationships -- verified against fixture files with known call patterns.
7. `discover_adjacent_details()` finds functions sharing stores and call paths -- verified against fixture files with known adjacencies.
8. `EvidenceStore.search()` returns relevant evidence hits from spec indexes -- verified against fixture spec data.
9. `scan_for_gaps()` detects all pseudocode comments and stubs as gaps -- verified by counting gaps against known fixture files.
10. All CLI commands execute without error on sample inputs -- verified by subprocess-based integration tests.
11. `run_planning_v2_phase()` integrates with `WorkspaceManager` and writes artifacts to the expected locations -- verified by checking artifact paths exist after execution.
12. No regressions in existing `planning/` or `decomposition/` tests -- verified by running full test suite.