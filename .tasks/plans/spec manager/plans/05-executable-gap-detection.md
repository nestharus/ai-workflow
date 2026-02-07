# Implementation Plan

## Overview

Build an executable gap detection system that mechanically identifies unimplemented spec elements by running the algorithmic code -- scanning comments, detecting stub functions, executing code to catch `NotImplementedError`, building call graphs for adjacency detection, and analyzing path coverage -- all without LLM inference.

## Current State (Problems)

The existing gap detection system is entirely LLM-driven and text-analytic:

1. **Gap detection is LLM-dependent**: `GapSynthesizer` in `scripts/spec_manager/spec_manager/refinement/core/gap.py` clusters `GapEvidence` produced by LLM-based "gap judges" that read spec text and infer missing elements. This is inherently probabilistic -- it can miss gaps the LLM does not notice and hallucinate gaps that do not exist.

2. **No mechanical verification**: The compliance module (`scripts/spec_manager/spec_manager/compliance/`) validates schema conformance (`validation.py`), evidence field formatting (`evidence_field_lint.py`), coverage accounting (`coverage_gate.py`), and hardcoding policy (`hardcoding_scanner.py`). None of these detect unimplemented algorithmic code.

3. **Verification is structural, not behavioral**: The verification module (`scripts/spec_manager/spec_manager/verification/operations.py`) checks for duplicate IDs, empty stubs in spec markdown, and content drift between plan.md and libraries. It does not analyze actual Python code.

4. **Drift detection is projection-level**: `AtomAwareDriftComparator` in `scripts/spec_manager/spec_manager/projection/drift.py` compares projection artifacts against spec indexes using atom fingerprints. It detects drift between spec layers but not between spec and implementation.

5. **Gap types are spec-centric**: The `GapType` enum covers `missing_detail`, `ambiguity`, `contradiction`, etc. There are no gap types for `unimplemented_comment`, `stub_function`, `runtime_not_implemented`, or `uncovered_path` -- the mechanical gap categories that executable detection would produce.

## Target State

A new `detection` subpackage under `compliance` that provides five scanners and a unified orchestrator:

1. **Comment scanner**: Tokenizes Python files, extracts all comments as unimplemented spec elements (in algorithmic code, every comment IS spec).
2. **Stub scanner**: AST-parses files, finds functions whose bodies are only `pass`, `raise NotImplementedError`, or `Ellipsis (...)`.
3. **Runtime gap detector**: Imports and executes algorithmic code with test inputs in a subprocess sandbox, catches `NotImplementedError` at runtime as proof of gaps.
4. **Call graph builder**: Static analysis of `import` and `ast.Call` nodes to build a function-level call graph, detect disconnected subgraphs (potential missed adjacencies).
5. **Coverage analyzer**: Wraps `coverage.py` execution, reports which functions/branches are exercised vs. not.

All scanners emit `GapEvidence` objects compatible with the existing `GapSynthesizer`. The orchestrator runs all five and feeds results into the existing gap queue for unified tracking.

## Additional Info

### Design Principles (from algorithmic-projection-patch.md Section 7)

- "Every comment in algorithmic code is an unimplemented spec element" -- comments = gaps, period.
- "Functions that raise NotImplementedError or return sentinel values are gaps" -- runtime verification.
- "Build a call graph. Two subgraphs that are disconnected in the UNION of (call graph + event graph) are truly isolated" -- adjacency detection.
- The system is Python-only from day one (no language-agnostic abstraction needed).

### Comment Discrimination Convention

The design doc states "no comments in production" for algorithmic code. However, real-world Python has docstrings, type ignore comments, and tooling markers. The convention:
- **Spec comments**: Lines starting with `#` inside function bodies or at module level describing behavior. These are gaps.
- **Excluded**: `# type: ignore`, `# noqa`, `# pragma`, `# fmt:`, `# pylint:`, `# TODO` (handled separately as uncertainty markers), shebangs, encoding declarations.
- **Docstrings**: NOT comments. Docstrings describe what a function does (contracts). Comments describe what it SHOULD do (unimplemented spec).

### Sandbox Strategy for Runtime Detection

The runtime detector must not corrupt the host process:
- Use `subprocess.run()` with a generated runner script that imports the target module, calls the target function, and catches `NotImplementedError`.
- Timeout per function (default 5 seconds).
- No network access needed (algorithmic code is pure logic).
- Capture stderr for `NotImplementedError` tracebacks.

### Call Graph Representation

Use a simple adjacency list (`dict[str, set[str]]`) rather than networkx. The graph is small (hundreds of functions, not millions). Connected components via BFS. No external dependency required.

### Integration with Existing Compliance Module

The new `detection` package sits alongside existing compliance modules:
- `compliance/coverage_gate.py` -- atom coverage (kept, complementary)
- `compliance/detection/` -- NEW executable gap detection
- Both produce `GapEvidence` that feeds into `GapSynthesizer`
- Compliance gating (Section 12 of design doc) checks the new gap types as blockers for promotion

## Plans

### Plan 1: New GapType Variants and GapEvidence Detector Constants

Extend the existing `GapType` enum and add detector name constants.

**Files to modify:**
- `scripts/spec_manager/spec_manager/refinement/core/gap.py`

**Changes:**

Add new `GapType` members:

```python
class GapType(Enum):
    # ... existing members ...
    unimplemented_comment = "unimplemented_comment"
    stub_function = "stub_function"
    runtime_not_implemented = "runtime_not_implemented"
    disconnected_subgraph = "disconnected_subgraph"
    uncovered_path = "uncovered_path"
```

Update the `_infer_gap_type` invariant mapping:

```python
mapping = {
    # ... existing mappings ...
    "executable_comment": GapType.unimplemented_comment,
    "executable_stub": GapType.stub_function,
    "executable_runtime": GapType.runtime_not_implemented,
    "executable_adjacency": GapType.disconnected_subgraph,
    "executable_coverage": GapType.uncovered_path,
}
```

**Data structures:**

No new classes. The new gap types integrate into the existing `Gap` and `GapEvidence` dataclasses.

**Function signatures:**

None new -- existing `_infer_gap_type()` is updated in place.

**Tests:**
- Verify new `GapType` members serialize/deserialize correctly via `to_dict()`/`from_dict()`.
- Verify `_infer_gap_type` returns the new types for matching invariant families.

---

### Plan 2: Comment Scanner

Tokenize Python files and extract comments as gap evidence.

**Files to create:**
- `scripts/spec_manager/spec_manager/compliance/detection/__init__.py`
- `scripts/spec_manager/spec_manager/compliance/detection/comment_scanner.py`

**Data structures:**

```python
@dataclass
class CommentGap:
    """A comment identified as unimplemented spec."""
    file_path: str
    line: int
    col_int: int
    text: str                   # Comment text with "# " prefix stripped
    enclosing_function: str | None  # Function name if inside a function body, else None
    is_inline: bool             # True if comment is on same line as code
```

**Function signatures:**

```python
# comment_scanner.py

# Internal exclusion patterns for non-spec comments
EXCLUDED_PREFIXES: tuple[str, ...] = (
    "type: ignore", "noqa", "pragma", "fmt:", "pylint:",
    "mypy:", "pyright:", "ruff:", "isort:", "!",
    "-*- coding",
)

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
```

**Integration:**
- `GapEvidence.invariant_family = "executable_comment"` maps to `GapType.unimplemented_comment` via the mapping added in Plan 1.

**Tests:**
- Scan a file with mixed spec comments, `# type: ignore`, docstrings, and `# noqa` -- verify only spec comments are returned.
- Verify enclosing function resolution is correct for nested functions.
- Verify `comments_to_gap_evidence` produces correctly shaped `GapEvidence`.

---

### Plan 3: Stub Scanner

AST-parse files to find functions that are stubs.

**Files to create:**
- `scripts/spec_manager/spec_manager/compliance/detection/stub_scanner.py`

**Data structures:**

```python
@dataclass
class StubFunction:
    """A function identified as a stub (not implemented)."""
    file_path: str
    line: int
    end_line: int
    name: str                   # Qualified name: "ClassName.method" or "function"
    stub_type: Literal["pass", "ellipsis", "not_implemented"]
    has_docstring: bool         # True if the stub has a docstring before the stub body
    args: list[str]             # Parameter names
    return_annotation: str | None  # Return type annotation if present
```

**Function signatures:**

```python
# stub_scanner.py

def scan_stubs(filepath: Path) -> list[StubFunction]:
    """AST-parse a Python file and return all stub functions.

    A function is a stub if its body consists of ONLY:
    1. An optional docstring (Expr(Constant(str)))
    2. Followed by one of:
       a. `pass` statement
       b. `raise NotImplementedError(...)` 
       c. Ellipsis expression (`...`)

    Handles both top-level functions and methods within classes.
    Qualified names use "ClassName.method_name" format.

    Args:
        filepath: Path to the Python file.

    Returns:
        List of StubFunction for each stub found.
    """

def stubs_to_gap_evidence(stubs: list[StubFunction]) -> list[GapEvidence]:
    """Convert StubFunction list to GapEvidence for gap synthesis.

    Each StubFunction becomes a GapEvidence with:
        invariant_family = "executable_stub"
        detector = "stub_scanner"
        location = "{file_path}:{line}-{end_line}"
        description = "Stub function: {name} ({stub_type})"
        details = {"stub_type": ..., "args": ..., "return_annotation": ...}

    Args:
        stubs: List of StubFunction from scan_stubs.

    Returns:
        List of GapEvidence objects.
    """
```

**Integration:**
- `GapEvidence.invariant_family = "executable_stub"` maps to `GapType.stub_function`.

**Tests:**
- Scan a file with: real functions, `pass` stubs, `raise NotImplementedError` stubs, `...` stubs, stubs with docstrings, class methods -- verify correct detection.
- Verify that functions with real logic after a docstring are NOT flagged.
- Verify qualified naming: `ClassName.method_name`.

---

### Plan 4: Runtime Gap Detector

Execute algorithmic code in a subprocess sandbox, catch `NotImplementedError` at runtime.

**Files to create:**
- `scripts/spec_manager/spec_manager/compliance/detection/runtime_detector.py`

**Data structures:**

```python
@dataclass
class RuntimeGap:
    """A function that raised NotImplementedError at runtime."""
    file_path: str
    function_name: str
    error_message: str          # The message from NotImplementedError
    traceback_summary: str      # Abbreviated traceback
    call_chain: list[str]       # Functions in the call stack leading to the error

@dataclass
class RuntimeProbeResult:
    """Result of probing a single function."""
    function_name: str
    module_path: str
    status: Literal["ok", "not_implemented", "error", "timeout"]
    error_message: str = ""
    traceback_summary: str = ""
    call_chain: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
```

**Function signatures:**

```python
# runtime_detector.py

def generate_probe_script(
    module_path: str,
    function_name: str,
    test_inputs: dict[str, Any] | None = None,
) -> str:
    """Generate a Python script that imports and calls the target function.

    The script:
    1. Imports the module
    2. Calls the function with test_inputs (or no args if None)
    3. Prints a JSON result: {"status": "ok"} or {"status": "not_implemented", "message": ..., "traceback": ...}
    4. Catches NotImplementedError specially, all others as "error"

    Args:
        module_path: Dotted module path (e.g., "spec_manager.labyrinth.core.bus")
        function_name: Function to call within the module
        test_inputs: Optional keyword arguments to pass

    Returns:
        Python source code string for the probe script.
    """

def probe_function(
    module_path: str,
    function_name: str,
    test_inputs: dict[str, Any] | None = None,
    timeout_seconds: float = 5.0,
    python_executable: str | None = None,
) -> RuntimeProbeResult:
    """Run a function in a subprocess and check for NotImplementedError.

    Generates a probe script, runs it via subprocess.run() with timeout,
    parses JSON output.

    Args:
        module_path: Dotted module path.
        function_name: Function name to probe.
        test_inputs: Optional arguments.
        timeout_seconds: Maximum execution time.
        python_executable: Path to Python interpreter (defaults to sys.executable).

    Returns:
        RuntimeProbeResult with status and error details.
    """

def probe_stubs(
    stubs: list[StubFunction],
    project_root: Path,
    timeout_seconds: float = 5.0,
) -> list[RuntimeProbeResult]:
    """Probe all stub functions discovered by the stub scanner.

    Converts file paths to module paths, probes each stub.
    Stubs of type "not_implemented" are prioritized (most likely to confirm).

    Args:
        stubs: List of StubFunction from stub_scanner.
        project_root: Root of the Python project for module path resolution.
        timeout_seconds: Per-function timeout.

    Returns:
        List of RuntimeProbeResult.
    """

def runtime_results_to_gap_evidence(
    results: list[RuntimeProbeResult],
) -> list[GapEvidence]:
    """Convert RuntimeProbeResult list to GapEvidence.

    Only "not_implemented" status results become gaps.
    invariant_family = "executable_runtime"
    detector = "runtime_detector"

    Args:
        results: List of RuntimeProbeResult.

    Returns:
        List of GapEvidence for confirmed runtime gaps.
    """
```

**Integration:**
- Uses `StubFunction` from Plan 3 as input to `probe_stubs`.
- `GapEvidence.invariant_family = "executable_runtime"` maps to `GapType.runtime_not_implemented`.

**Tests:**
- Create a temp module with a function that raises `NotImplementedError`, probe it, verify detection.
- Create a temp module with a working function, probe it, verify `status = "ok"`.
- Verify timeout handling.
- Verify call chain capture.

---

### Plan 5: Call Graph Builder and Adjacency Detector

Build a static call graph from AST analysis, detect disconnected subgraphs.

**Files to create:**
- `scripts/spec_manager/spec_manager/compliance/detection/call_graph.py`

**Data structures:**

```python
@dataclass
class FunctionNode:
    """A function in the call graph."""
    qualified_name: str         # "module.ClassName.method" or "module.function"
    file_path: str
    line: int
    is_stub: bool               # Cross-reference with stub scanner results

@dataclass
class CallEdge:
    """A call relationship between two functions."""
    caller: str                 # Qualified name of the calling function
    callee: str                 # Qualified name of the called function
    call_site_line: int
    file_path: str

@dataclass
class CallGraph:
    """Function-level call graph with adjacency detection."""
    nodes: dict[str, FunctionNode]      # qualified_name -> FunctionNode
    edges: dict[str, set[str]]          # caller -> set of callee qualified names
    reverse_edges: dict[str, set[str]]  # callee -> set of caller qualified names

    def get_connected_components(self) -> list[set[str]]:
        """Find connected components via BFS on undirected view."""

    def get_disconnected_subgraphs(self) -> list[set[str]]:
        """Return components that have no edges to other components.
        
        These are potential missed adjacencies per design doc Section 7.
        """

    def get_callers(self, function_name: str) -> set[str]:
        """Get all functions that call the given function."""

    def get_callees(self, function_name: str) -> set[str]:
        """Get all functions called by the given function."""

    def get_reachable(self, function_name: str) -> set[str]:
        """Get all functions reachable from the given function (transitive)."""
```

**Function signatures:**

```python
# call_graph.py

def build_call_graph(
    filepaths: list[Path],
    project_root: Path | None = None,
) -> CallGraph:
    """Build a function-level call graph from Python source files.

    For each file:
    1. AST-parse to find all function/method definitions
    2. Walk function bodies to find ast.Call nodes
    3. Resolve call targets to qualified names where possible
    4. Unresolved calls (dynamic dispatch, closures) are ignored

    Args:
        filepaths: Python files to analyze.
        project_root: Root for module path resolution.

    Returns:
        CallGraph with nodes and edges.
    """

def detect_adjacency_gaps(
    call_graph: CallGraph,
    min_component_size: int = 2,
) -> list[GapEvidence]:
    """Detect disconnected subgraphs that may indicate missed adjacencies.

    Per design doc Section 7: "Two subgraphs that are disconnected in the
    UNION of (call graph + event graph) are truly isolated."

    Since we only have the call graph (no event graph yet), disconnected
    components are flagged as POTENTIAL missed adjacencies with lower
    confidence.

    Args:
        call_graph: The CallGraph to analyze.
        min_component_size: Minimum size of a component to report (ignore singletons).

    Returns:
        List of GapEvidence with invariant_family = "executable_adjacency".
    """
```

**Integration:**
- `GapEvidence.invariant_family = "executable_adjacency"` maps to `GapType.disconnected_subgraph`.
- Call graph can be enriched later with event graph from the labyrinth `AsyncMessageBus` subscriptions.

**Tests:**
- Build a call graph from files with known call relationships, verify edges.
- Create two disconnected function clusters, verify they are detected as separate components.
- Verify that singletons (isolated utility functions) are filtered by `min_component_size`.

---

### Plan 6: Coverage Analyzer

Wrap `coverage.py` to identify unexercised paths in algorithmic code.

**Files to create:**
- `scripts/spec_manager/spec_manager/compliance/detection/coverage_analyzer.py`

**Data structures:**

```python
@dataclass
class FileCoverage:
    """Coverage data for a single file."""
    file_path: str
    total_statements: int
    covered_statements: int
    missing_lines: list[int]        # Line numbers not covered
    coverage_ratio: float           # 0.0-1.0

@dataclass 
class FunctionCoverage:
    """Coverage data for a single function."""
    file_path: str
    function_name: str
    line_start: int
    line_end: int
    total_statements: int
    covered_statements: int
    coverage_ratio: float

@dataclass
class CoverageReport:
    """Aggregate coverage report across files."""
    files: list[FileCoverage]
    functions: list[FunctionCoverage]
    overall_ratio: float
    uncovered_functions: list[FunctionCoverage]  # Functions with 0% coverage
```

**Function signatures:**

```python
# coverage_analyzer.py

def run_coverage(
    test_command: list[str],
    source_dirs: list[Path],
    project_root: Path,
    coverage_data_file: Path | None = None,
) -> Path:
    """Run a test command with coverage.py instrumentation.

    Executes: coverage run --source=<dirs> <test_command>
    Returns path to the .coverage data file.

    Args:
        test_command: Command to run (e.g., ["pytest", "tests/"]).
        source_dirs: Directories to measure coverage for.
        project_root: Working directory for the command.
        coverage_data_file: Optional path for .coverage file.

    Returns:
        Path to the .coverage data file.
    """

def parse_coverage_report(
    coverage_data_file: Path,
    source_files: list[Path],
) -> CoverageReport:
    """Parse a .coverage data file into structured coverage data.

    Uses coverage.py's API to load data and analyze per-file and
    per-function coverage.

    Args:
        coverage_data_file: Path to .coverage file.
        source_files: Files to analyze coverage for.

    Returns:
        CoverageReport with file and function-level data.
    """

def coverage_to_gap_evidence(
    report: CoverageReport,
    min_function_coverage: float = 0.0,
) -> list[GapEvidence]:
    """Convert uncovered functions to GapEvidence.

    Only functions with coverage_ratio <= min_function_coverage are gaps.
    Default threshold is 0.0 (only completely uncovered functions).

    invariant_family = "executable_coverage"
    detector = "coverage_analyzer"

    Args:
        report: CoverageReport from parse_coverage_report.
        min_function_coverage: Threshold below which a function is a gap.

    Returns:
        List of GapEvidence for uncovered functions.
    """
```

**Integration:**
- `GapEvidence.invariant_family = "executable_coverage"` maps to `GapType.uncovered_path`.
- Coverage analysis is optional -- it requires tests to exist. If no tests, this scanner is skipped.

**Tests:**
- Create a simple module and test, run coverage, verify report structure.
- Verify that a function with zero coverage appears in `uncovered_functions`.
- Verify gap evidence generation threshold logic.

---

### Plan 7: Unified Orchestrator and Compliance Integration

Wire all five scanners into a single orchestrator callable from CLI and compliance scoring.

**Files to create:**
- `scripts/spec_manager/spec_manager/compliance/detection/orchestrator.py`

**Files to modify:**
- `scripts/spec_manager/spec_manager/compliance/__init__.py` -- export new public API
- `scripts/spec_manager/spec_manager/compliance/scorer.py` -- add executable gap checks to compliance scoring

**Data structures:**

```python
@dataclass
class ExecutableGapReport:
    """Unified report from all executable gap scanners."""
    comment_gaps: list[CommentGap]
    stub_gaps: list[StubFunction]
    runtime_gaps: list[RuntimeProbeResult]
    adjacency_gaps: list[GapEvidence]     # Already GapEvidence from call_graph
    coverage_gaps: list[GapEvidence]      # Already GapEvidence from coverage_analyzer
    all_evidence: list[GapEvidence]       # All scanners' GapEvidence combined
    call_graph: CallGraph                 # The computed call graph (for downstream use)
    scan_duration_ms: float               # Total scan time

@dataclass
class ScanConfig:
    """Configuration for which scanners to run."""
    enable_comments: bool = True
    enable_stubs: bool = True
    enable_runtime: bool = False          # Off by default (requires test inputs)
    enable_call_graph: bool = True
    enable_coverage: bool = False         # Off by default (requires test suite)
    comment_excluded_prefixes: tuple[str, ...] = EXCLUDED_PREFIXES
    runtime_timeout_seconds: float = 5.0
    coverage_min_threshold: float = 0.0
    call_graph_min_component_size: int = 2
```

**Function signatures:**

```python
# orchestrator.py

def scan_executable_gaps(
    filepaths: list[Path],
    project_root: Path,
    config: ScanConfig | None = None,
    test_command: list[str] | None = None,
) -> ExecutableGapReport:
    """Run all configured scanners and produce a unified report.

    Orchestration order:
    1. Comment scanner (all files)
    2. Stub scanner (all files)
    3. Runtime detector (probe stubs if enabled)
    4. Call graph builder (all files)
    5. Coverage analyzer (if enabled and test_command provided)

    Collects all GapEvidence into a single list for downstream synthesis.

    Args:
        filepaths: Python files to scan.
        project_root: Project root for module resolution.
        config: Scanner configuration.
        test_command: Command for coverage analysis (e.g., ["pytest", "tests/"]).

    Returns:
        ExecutableGapReport with all findings.
    """

def integrate_with_gap_queue(
    report: ExecutableGapReport,
    gap_queue: GapQueue,
    synthesizer: GapSynthesizer | None = None,
) -> GapQueue:
    """Feed executable gap evidence into the existing gap queue.

    Uses GapSynthesizer to cluster evidence into Gaps, then merges
    into the existing GapQueue.

    Args:
        report: ExecutableGapReport from scan_executable_gaps.
        gap_queue: Existing GapQueue to merge into.
        synthesizer: Optional GapSynthesizer (uses default if None).

    Returns:
        Updated GapQueue with executable gaps merged in.
    """
```

**Changes to `compliance/__init__.py`:**

```python
# Add to imports:
from spec_manager.compliance.detection import (
    ExecutableGapReport,
    ScanConfig,
    scan_executable_gaps,
    integrate_with_gap_queue,
)

# Add to __all__:
"ExecutableGapReport",
"ScanConfig", 
"scan_executable_gaps",
"integrate_with_gap_queue",
```

**Changes to `compliance/scorer.py`:**

Add a new check method to `ComplianceScorer`:

```python
def check_executable_gaps(
    self,
    spec_folder: Path,
    algorithmic_files: list[Path] | None = None,
) -> list[dict[str, Any]]:
    """Check for executable gaps that block promotion.

    Per design doc Section 12:
    - No remaining comments (all pseudocode translated) -> blocker
    - No stub functions (all atoms implemented) -> blocker
    
    Args:
        spec_folder: Path to the spec workspace.
        algorithmic_files: Optional explicit list of algorithmic code files.

    Returns:
        List of blocker dicts for compliance scoring.
    """
```

Wire `check_executable_gaps` into `score_compliance()` alongside existing checks.

**Tests:**
- Integration test: create a temp project with comments, stubs, and real code, run the orchestrator, verify all scanner results are present.
- Verify `integrate_with_gap_queue` correctly merges new executable gaps with existing LLM-detected gaps.
- Verify compliance scorer blocks promotion when comments or stubs remain.

## Execution Instructions

Execute plans sequentially (Plan 1 through Plan 7). Each plan is independently testable:

1. **Plan 1**: Extend gap types. Run existing gap tests to verify no regression. Add tests for new types.
2. **Plan 2**: Implement comment scanner. Test in isolation with fixture files.
3. **Plan 3**: Implement stub scanner. Test in isolation with fixture files.
4. **Plan 4**: Implement runtime detector. Test with temp modules in subprocess.
5. **Plan 5**: Implement call graph builder. Test with known call structures.
6. **Plan 6**: Implement coverage analyzer. Test with simple module + test pair.
7. **Plan 7**: Wire everything together. Integration test end-to-end.

Plans 2-4 can be developed in parallel since they have no dependencies on each other (only on Plan 1's gap types). Plan 5 and 6 are also independent of 2-4. Plan 7 depends on all prior plans.

Test files should be created under `scripts/spec_manager/tests/compliance/detection/` mirroring the source structure.

## Success Criteria

1. `scan_comments()` correctly identifies spec comments and excludes tooling markers (`# type: ignore`, `# noqa`, etc.) with zero false positives on the existing `spec_manager` codebase.
2. `scan_stubs()` correctly identifies all three stub patterns (`pass`, `raise NotImplementedError`, `...`) and produces zero false positives on real implemented functions.
3. `probe_function()` detects `NotImplementedError` at runtime in a subprocess with <5 second timeout and correct exit handling.
4. `build_call_graph()` produces a graph where every direct function call in the source files has a corresponding edge.
5. `detect_adjacency_gaps()` correctly identifies disconnected components of size >= 2.
6. `coverage_to_gap_evidence()` produces gaps only for functions below the configured threshold.
7. `scan_executable_gaps()` runs all enabled scanners and produces a unified `ExecutableGapReport`.
8. `integrate_with_gap_queue()` correctly merges executable gap evidence with existing LLM-detected gaps without duplicating.
9. New `GapType` members serialize and deserialize correctly through `Gap.to_dict()`/`Gap.from_dict()` round-trip.
10. All new code has >90% test coverage.
11. `ComplianceScorer.check_executable_gaps()` returns blockers when algorithmic code has remaining comments or stubs, satisfying the gating requirements from design doc Section 12.