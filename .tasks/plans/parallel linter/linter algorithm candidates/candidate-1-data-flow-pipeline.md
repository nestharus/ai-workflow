# Candidate 1: Data Flow Pipeline Architecture

## Overview

The parallel linter algorithm exhibits a clear data flow pipeline where different data types flow through transformation stages. The algorithm can be decomposed into a pipeline with distinct stages, each consuming inputs, performing transformations, and producing outputs for downstream stages.

### Primary Data Flow

```
CLI Args → Files List → Linter Specs → Linter Instances → Phases → Phase Items → Execution Results → Aggregated Results → Output
```

## Main Data Types

### 1. Files (`List[str]`)
- Repo-relative file paths flowing through the pipeline
- Transformations: git queries → normalization → deduplication → filtering → sorting → chunking
- Consumed by: linter applicability checks, fileset calculations, execution tasks
- Modified by: mutating phases (files may be deleted, requiring refresh)

### 2. Linters (`List[LinterSpec]` → `List[LinterInstance]`)
- Linter specifications with operators (>=, >, <=, <, none)
- Transformed into concrete linter instances with unique instance_ids
- Enriched with: preflight status, applicability (matching filesets), configuration
- Consumed by: scheduler, phase builder, executor

### 3. Phases (`List[Phase]`)
- Structured execution units: `Phase{linters: List[LinterInstance], is_mutating: bool}`
- Built from: linter classification (mutating/read-only, sequential/parallel-safe)
- Ordered: mutating phases → read-only phases
- Consumed by: phase execution loop

### 4. Phase Items (`List[PhaseItem]`)
- Execution tasks: `PhaseItem{linter, fileset_chunk, chunk_id, snapshot_path?}`
- Generated from: phases + cached fileset calculations + ARG_MAX chunking
- Sequential chunk_ids enable deterministic output ordering
- Consumed by: executor (single/parallel)

### 5. Results (`Dict[LinterInstance, LinterResult]`)
- Execution outcomes: `LinterResult{status, exit_code, stdout, stderr, file_list, files_modified, chunk_id}`
- Aggregated from: chunk results (deduplicated diagnostics)
- Accumulated in: `all_results` dictionary
- Transformed into: YAML or text output

### 6. Meta (`Dict{warnings: List, errors: List}`)
- Operational metadata flowing alongside results
- Accumulated from: validation errors, warnings, preflight failures
- Merged into: final output structure

## Identified Pipeline Stages

### Stage 1: Argument Processing
**Input:** `sys.argv`
**Output:** `ParsedArgs{files_option, linter_specs, output_format, fail_fast, commit, ...}`

**Pure function candidate:**
```python
def parse_arguments(argv: List[str]) -> ParsedArgs:
    """Parse CLI arguments into structured configuration."""
```

**Transformations:**
- Parse CLI flags
- Detect output format (yaml/text)
- Extract file selection mode
- Extract linter specifications

**Coupling:** None (pure parsing)

---

### Stage 2: File Discovery
**Input:** `ParsedArgs.files_option`
**Output:** `FileList{files: List[str], warnings: List[str]}`

**Pure function candidate:**
```python
def discover_files(
    option: FileOption,
    repo_root: str
) -> FileList:
    """Discover files based on selection mode (changed/commit/explicit/all)."""
```

**Transformations:**
- Git queries (diff, ls-files, diff-tree)
- Path normalization (repo-relative)
- Deduplication (preserve order)
- Existence filtering (os.path.exists)
- Sorting

**Coupling:**
- Git state (external)
- Filesystem state (external)
- Returns warnings for missing explicit files

---

### Stage 3: Linter Selection & Expansion
**Input:** `ParsedArgs.linter_specs` or default (all linters)
**Output:** `SelectedLinters{instances: List[LinterInstance], errors: List[str]}`

**Pure function candidate:**
```python
def expand_linter_specs(
    specs: Optional[List[str]],
    linter_registry: LinterRegistry
) -> SelectedLinters:
    """Expand linter specs with operators into concrete instances."""
```

**Transformations:**
- Parse operator specs (>=, >, <=, <, none)
- Expand against LINTER_NAMES
- Validate linter names
- Assign unique instance_ids
- Track explicitly requested linters

**Coupling:**
- Global linter registry (LINTER_NAMES, configurations)
- Returns errors for unknown linters

---

### Stage 4: Applicability Pre-scan
**Input:** `SelectedLinters.instances`, `FileList.files`
**Output:** `ApplicabilityMap{fileset_by_linter: Dict[LinterInstance, List[str]], skipped: Dict[LinterInstance, SkipReason]}`

**Pure function candidate:**
```python
def calculate_applicability(
    linters: List[LinterInstance],
    files: List[str]
) -> ApplicabilityMap:
    """Calculate which files each linter applies to (cached)."""
```

**Transformations:**
- Call `linter.calculate_fileset(files)` for each linter
- Cache results in `fileset_by_linter`
- Identify linters with empty filesets (skip with reason)

**Coupling:**
- Linter-specific file pattern matching logic
- May access filesystem for extension/path checks

---

### Stage 5: Preflight Validation
**Input:** `ApplicabilityMap.fileset_by_linter.keys()` (applicable linters)
**Output:** `PreflightResults{healthy: List[LinterInstance], failed: Dict[LinterInstance, str]}`

**Parallel execution stage:**
```python
def preflight_linters(
    linters: List[LinterInstance],
    max_workers: int
) -> PreflightResults:
    """Test linter executability in parallel."""
```

**Transformations:**
- Parallel ThreadPoolExecutor calls to `linter.test()`
- Strict timeout enforcement
- Categorize pass/fail

**Coupling:**
- External executables (linter binaries)
- System PATH, environment

---

### Stage 6: Phase Scheduling
**Input:** `PreflightResults.healthy`, `ApplicabilityMap`
**Output:** `PhaseSchedule{phases: List[Phase], commit_mode_errors: List[str]}`

**Pure function candidate:**
```python
def schedule_phases(
    linters: List[LinterInstance],
    fileset_by_linter: Dict[LinterInstance, List[str]],
    commit_mode: bool
) -> PhaseSchedule:
    """Organize linters into execution phases."""
```

**Transformations:**
- Classify linters: mutating vs read-only, sequential vs parallel-safe
- Sort mutators by priority, then name
- Pack mutators into phases (greedy disjoint resource allocation)
- Build read-only sequential phases (one per linter)
- Build final parallel read-only phase
- Order: mutating phases first
- Validate: forbid mutators in commit mode

**Coupling:**
- Linter metadata (mutates_files, parallel_safe, priority, scope)
- Business rule: mutators before read-only

---

### Stage 7: Phase Item Generation
**Input:** `PhaseSchedule.phases`, `ApplicabilityMap.fileset_by_linter`
**Output:** `PhaseItemsList{items_by_phase: Dict[Phase, List[PhaseItem]]}`

**Pure function candidate:**
```python
def generate_phase_items(
    phases: List[Phase],
    fileset_by_linter: Dict[LinterInstance, List[str]],
    arg_max_budget: int
) -> PhaseItemsList:
    """Generate execution tasks with ARG_MAX chunking."""
```

**Transformations:**
- For each phase's linters, retrieve cached fileset
- Chunk filesets to fit ARG_MAX budget (exe + flags + config + env + margin)
- Assign sequential chunk_ids across all phase items
- Tag mutators with snapshot_path placeholders

**Coupling:**
- System ARG_MAX limits
- Environment size calculation
- Linter command structure (fixed args)

---

### Stage 8: Phase Execution
**Input:** `PhaseItemsList.items_by_phase` (per-phase)
**Output:** `PhaseResults{results: Dict[LinterInstance, List[LinterResult]], phase_modified: bool}`

**Parallel execution stage:**
```python
def execute_phase(
    phase_items: List[PhaseItem],
    is_mutating: bool,
    max_workers: int,
    fail_fast: bool,
    yaml_output: bool
) -> PhaseResults:
    """Execute phase items in parallel/sequential."""
```

**Transformations:**
- Single item → sequential execution
- Multiple items → ProcessPoolExecutor parallel execution
- For mutators: snapshot fileset_chunk before execution
- Subprocess execution: build command, run with timeout, capture stdout/stderr
- Strip ANSI, normalize paths, decode with backslashreplace
- Collect via as_completed (no head-of-line blocking)
- Buffer output with sliding window (text mode)
- Fail-fast: set shutdown_event, hard-stop tasks, restore snapshots

**Coupling:**
- Subprocess spawning (process groups, Job Objects)
- Filesystem snapshots (temp files, atomic rename)
- Signal handling (shutdown_event)
- Output buffering state (next_expected_chunk_id)
- External linter executables

---

### Stage 9: Result Aggregation
**Input:** `PhaseResults` (from each phase)
**Output:** `AggregatedResults{all_results: Dict[LinterInstance, LinterResult], meta: Meta}`

**Pure function candidate:**
```python
def aggregate_results(
    phase_results: List[PhaseResults],
    initial_meta: Meta
) -> AggregatedResults:
    """Merge chunk results, deduplicate diagnostics, accumulate metadata."""
```

**Transformations:**
- Merge chunk results per linter (concatenate)
- Deduplicate diagnostics by hash(file, line, col, rule_id)
- Accumulate warnings/errors into meta
- Track files_modified flags

**Coupling:**
- Deduplication logic (hash strategy)

---

### Stage 10: Fileset Refresh (conditional)
**Input:** `FileList.files`, `ApplicabilityMap.fileset_by_linter`, `phase_modified: bool`
**Output:** `RefreshedFileset{files: List[str], fileset_by_linter: Dict[...]}`

**Pure function candidate:**
```python
def refresh_fileset(
    files: List[str],
    fileset_by_linter: Dict[LinterInstance, List[str]]
) -> RefreshedFileset:
    """Filter deleted files after mutating phase."""
```

**Transformations:**
- Filter files through os.path.exists
- Prune each cached fileset

**Coupling:**
- Filesystem state (external)

---

### Stage 11: Output Formatting
**Input:** `AggregatedResults{all_results, meta}`, `output_format: str`
**Output:** `FormattedOutput{text: str, exit_code: int}`

**Pure function candidate:**
```python
def format_output(
    all_results: Dict[LinterInstance, LinterResult],
    meta: Meta,
    output_format: str
) -> FormattedOutput:
    """Format results as YAML or text."""
```

**Transformations:**
- YAML: serialize all_results + meta structure
- Text: format diagnostics, summaries, errors
- Calculate exit code (meta.errors or any failure → 1)

**Coupling:**
- YAML serialization library
- Text formatting conventions

---

## Coupling Points Requiring Interfaces

### 1. **File System Interface**
**Used by:** File Discovery, Applicability Pre-scan, Fileset Refresh, Execution
**Operations:** git queries, os.path.exists, file snapshots, path normalization

**Suggested Interface:**
```python
class FileSystemAdapter(Protocol):
    def get_changed_files(self, commit: Optional[str]) -> List[str]: ...
    def get_repo_files(self) -> List[str]: ...
    def file_exists(self, path: str) -> bool: ...
    def normalize_path(self, path: str, repo_root: str) -> str: ...
    def snapshot_files(self, files: List[str]) -> SnapshotHandle: ...
    def restore_snapshot(self, handle: SnapshotHandle) -> None: ...
```

---

### 2. **Linter Registry Interface**
**Used by:** Linter Selection, Applicability Pre-scan, Phase Scheduling, Execution
**Operations:** lookup linters, access metadata, calculate filesets

**Suggested Interface:**
```python
class LinterRegistry(Protocol):
    def get_linter_names(self) -> List[str]: ...
    def get_linter_instance(self, name: str, instance_id: int) -> LinterInstance: ...
    def calculate_fileset(self, linter: LinterInstance, files: List[str]) -> List[str]: ...
    def get_metadata(self, linter: LinterInstance) -> LinterMetadata: ...
```

**LinterMetadata:**
```python
@dataclass
class LinterMetadata:
    mutates_files: bool
    parallel_safe: bool
    priority: int
    scope: Literal["File", "Directory"]
```

---

### 3. **Execution Environment Interface**
**Used by:** Preflight, Phase Execution
**Operations:** subprocess spawning, process management, signal handling

**Suggested Interface:**
```python
class ExecutionAdapter(Protocol):
    def execute_subprocess(
        self,
        command: List[str],
        timeout: int,
        process_group: bool
    ) -> SubprocessResult: ...

    def create_snapshot(self, files: List[str]) -> SnapshotHandle: ...
    def restore_snapshot(self, handle: SnapshotHandle) -> None: ...

    def set_shutdown_event(self) -> None: ...
    def is_shutdown_requested(self) -> bool: ...

    def terminate_process_tree(self, pid: int) -> None: ...
```

---

### 4. **Output Interface**
**Used by:** All stages (for warnings/errors), Phase Execution (streaming), Final Output
**Operations:** buffered output, streaming, formatting

**Suggested Interface:**
```python
class OutputAdapter(Protocol):
    def emit_warning(self, message: str) -> None: ...
    def emit_error(self, message: str) -> None: ...
    def emit_chunk_output(self, chunk_id: int, output: str) -> None: ...
    def flush_buffered_output(self) -> None: ...
```

---

### 5. **State Management Interface**
**Used by:** Result Aggregation, Fileset Refresh, Phase Loop
**Operations:** maintain all_results, meta, fileset_by_linter cache

**Suggested Interface:**
```python
class StateManager(Protocol):
    def record_result(self, linter: LinterInstance, result: LinterResult) -> None: ...
    def get_result(self, linter: LinterInstance) -> Optional[LinterResult]: ...
    def record_warning(self, warning: str) -> None: ...
    def record_error(self, error: str) -> None: ...
    def cache_fileset(self, linter: LinterInstance, fileset: List[str]) -> None: ...
    def get_cached_fileset(self, linter: LinterInstance) -> List[str]: ...
    def refresh_filesets(self, file_filter: Callable[[str], bool]) -> None: ...
```

---

## Shared State Creating Coupling

### 1. **`all_results: Dict[LinterInstance, LinterResult]`**
- **Mutated by:** Applicability Pre-scan (skipped linters), Preflight (failed linters), Phase Execution, Result Aggregation
- **Read by:** Failure checking, Final Output, Exit code calculation
- **Coupling issue:** Global mutable state accessed across stages
- **Solution:** StateManager interface with transactional updates

### 2. **`meta: {warnings: List, errors: List}`**
- **Mutated by:** File validation, linter selection errors, preflight warnings, execution failures
- **Read by:** Final Output, Exit code calculation
- **Coupling issue:** Accumulator pattern requires thread-safe writes
- **Solution:** StateManager with synchronized append operations

### 3. **`fileset_by_linter: Dict[LinterInstance, List[str]]`**
- **Written by:** Applicability Pre-scan
- **Read by:** Phase Item Generation, Fileset Refresh
- **Mutated by:** Fileset Refresh (after mutating phases)
- **Coupling issue:** Cache invalidation logic tied to phase execution
- **Solution:** Immutable cache per phase, recreate on refresh

### 4. **`shutdown_event: bool`**
- **Written by:** Signal handler (SIGINT), Fail-fast logic
- **Read by:** Phase Execution (as_completed loop), Future processing
- **Coupling issue:** Cross-thread communication, requires synchronization
- **Solution:** ExecutionAdapter with thread-safe event primitives

### 5. **`yaml_output: bool`**
- **Set by:** Argument processing
- **Read by:** All reporting stages (suppress stderr in YAML mode)
- **Coupling issue:** Mode switch affects control flow across stages
- **Solution:** Pass as parameter through pipeline or use OutputAdapter strategy pattern

### 6. **`available_cpus: int`**
- **Computed once:** At startup
- **Read by:** Preflight worker calculation, Parallel execution worker calculation
- **Coupling issue:** Global read-only config, minor
- **Solution:** Pass through pipeline context or config object

### 7. **Output Buffer (`output_buffer`, `next_expected_chunk_id`)**
- **Mutated by:** Phase Execution (as_completed loop)
- **Read by:** Sliding window flush logic
- **Coupling issue:** Stateful output ordering tied to chunk_id scheme
- **Solution:** Encapsulate in OutputAdapter with internal buffer management

---

## Pipeline Stage Dependencies

```
┌─────────────────────┐
│ Argument Processing │ (pure)
└──────────┬──────────┘
           │
           ├─────────────────┐
           │                 │
           v                 v
┌──────────────────┐  ┌─────────────────┐
│ File Discovery   │  │ Linter Selection│ (pure + registry)
└─────────┬────────┘  └────────┬────────┘
          │                    │
          └────────┬───────────┘
                   │
                   v
       ┌───────────────────────┐
       │ Applicability Pre-scan│ (cached)
       └───────────┬───────────┘
                   │
                   v
       ┌───────────────────────┐
       │ Preflight Validation  │ (parallel I/O)
       └───────────┬───────────┘
                   │
                   v
       ┌───────────────────────┐
       │  Phase Scheduling     │ (pure + metadata)
       └───────────┬───────────┘
                   │
                   v
       ┌───────────────────────┐
       │ Phase Item Generation │ (pure)
       └───────────┬───────────┘
                   │
           ┌───────┴───────────────────┐
           │ Phase Execution Loop      │
           │  ┌─────────────────────┐  │
           │  │ Execute Phase (I/O) │  │ ◄──┐
           │  └──────────┬──────────┘  │    │
           │             │              │    │
           │             v              │    │
           │  ┌─────────────────────┐  │    │
           │  │ Result Aggregation  │  │    │
           │  └──────────┬──────────┘  │    │
           │             │              │    │
           │             v              │    │
           │  ┌─────────────────────┐  │    │
           │  │ Fileset Refresh?    │──┼────┘ (if mutating & modified)
           │  └─────────────────────┘  │
           └───────────┬───────────────┘
                       │
                       v
           ┌───────────────────────┐
           │  Output Formatting    │ (pure)
           └───────────────────────┘
```

---

## Pros of Pipeline Decomposition

### 1. **Clear Separation of Concerns**
Each stage has a well-defined responsibility: parsing, file discovery, scheduling, execution, formatting. This makes the algorithm easier to understand and reason about.

### 2. **Testability**
Pure function stages (Argument Processing, Linter Selection, Phase Scheduling, Phase Item Generation, Output Formatting) can be unit tested in isolation with mock inputs. No need for complex test fixtures.

### 3. **Composability**
Stages can be composed in different orders or replaced with alternative implementations (e.g., swap git-based file discovery for manual file list input).

### 4. **Parallelization Opportunities**
Stages 4 (Applicability) and 5 (Preflight) are naturally parallel within themselves. Stage 8 (Execution) is the main parallelization point. The pipeline makes these boundaries explicit.

### 5. **State Isolation**
By formalizing interfaces between stages, we reduce implicit coupling. Each stage's inputs/outputs are explicit, making data flow transparent.

### 6. **Incremental Development**
Stages can be developed and refined independently. For example, ARG_MAX chunking logic (Stage 7) can be improved without touching execution logic (Stage 8).

### 7. **Error Propagation**
Each stage can return errors explicitly (e.g., `SelectedLinters.errors`, `FileList.warnings`). The pipeline can short-circuit on critical errors while accumulating non-fatal warnings.

### 8. **Caching Opportunities**
Stage 4 (Applicability Pre-scan) caches `fileset_by_linter`, which is reused by Stage 7 (Phase Item Generation). The pipeline makes this cache explicit and controllable.

---

## Cons of Pipeline Decomposition

### 1. **Verbosity**
Formalizing each stage with explicit data structures (ParsedArgs, FileList, SelectedLinters, ApplicabilityMap, etc.) increases code volume and may feel over-engineered for a linear algorithm.

### 2. **Data Structure Overhead**
Each stage boundary requires serialization into intermediate data structures. For large file lists or many linters, this could add memory overhead (though likely negligible in practice).

### 3. **Loop-back Complexity**
The phase execution loop (Stage 8 → 9 → 10 → 8) breaks the pure pipeline model. Fileset Refresh creates a feedback loop that complicates the linear flow. This would require special handling (e.g., recursive pipeline invocation or explicit loop construct).

### 4. **Interface Proliferation**
Five interfaces (FileSystemAdapter, LinterRegistry, ExecutionAdapter, OutputAdapter, StateManager) may feel like over-abstraction. Small projects might resist this level of indirection.

### 5. **Performance Concerns**
Passing large data structures (e.g., `fileset_by_linter`) between stages may involve copying. Python's reference semantics mitigate this, but the concern exists for deep copies or serialization.

### 6. **Hidden Dependencies**
Some stages depend on global state (e.g., `shutdown_event`, `yaml_output`) that isn't captured in the pipeline flow. These would need to be threaded through as context or config objects, adding parameter noise.

### 7. **Mutating Phase Complexity**
Stage 8 (Execution) includes snapshot creation, restoration on crash/fail-fast, and hard-stopping process trees. This complexity doesn't decompose cleanly into the pipeline model; it's tightly coupled to the execution environment.

### 8. **Debugging Difficulty**
With many small pure functions, debugging a full run may require stepping through many function boundaries. The monolithic approach allows setting one breakpoint and following the flow directly.

---

## Suggested Interfaces Between Stages

### Stage Boundary 1-2: **Argument Processing → File Discovery**
```python
@dataclass
class ParsedArgs:
    files_option: FileOption  # Union[ChangedOnly, Commit, Explicit, WholeRepo]
    linter_specs: Optional[List[str]]
    output_format: Literal["yaml", "text"]
    fail_fast: bool
    max_concurrency: Optional[int]
    repo_root: str
```

---

### Stage Boundary 2-3: **File Discovery → Linter Selection**
```python
@dataclass
class FileList:
    files: List[str]  # Repo-relative, sorted, existing
    warnings: List[str]  # e.g., "Explicit file foo.py not found"
```

---

### Stage Boundary 3-4: **Linter Selection → Applicability Pre-scan**
```python
@dataclass
class SelectedLinters:
    instances: List[LinterInstance]  # With unique instance_ids
    explicit_requests: Set[str]  # Linter names explicitly requested by user
    errors: List[str]  # e.g., "Unknown linter: foo"
```

---

### Stage Boundary 4-5: **Applicability Pre-scan → Preflight Validation**
```python
@dataclass
class ApplicabilityMap:
    fileset_by_linter: Dict[LinterInstance, List[str]]  # Cached filesets
    skipped: Dict[LinterInstance, SkipReason]  # Linters with empty filesets
    applicable_linters: List[LinterInstance]  # Non-empty filesets
```

---

### Stage Boundary 5-6: **Preflight Validation → Phase Scheduling**
```python
@dataclass
class PreflightResults:
    healthy: List[LinterInstance]  # Passed preflight
    failed: Dict[LinterInstance, str]  # Failed with reason
    explicit_failures: List[str]  # Explicitly requested linters that failed
```

---

### Stage Boundary 6-7: **Phase Scheduling → Phase Item Generation**
```python
@dataclass
class PhaseSchedule:
    phases: List[Phase]  # Ordered: mutating phases first
    commit_mode_errors: List[str]  # Error if mutators in --commit mode

@dataclass
class Phase:
    linters: List[LinterInstance]
    is_mutating: bool
```

---

### Stage Boundary 7-8: **Phase Item Generation → Phase Execution**
```python
@dataclass
class PhaseItemsList:
    items_by_phase: Dict[Phase, List[PhaseItem]]

@dataclass
class PhaseItem:
    linter: LinterInstance
    fileset_chunk: List[str]
    chunk_id: int  # Sequential across all phase items
    snapshot_path: Optional[str]  # For mutators
```

---

### Stage Boundary 8-9: **Phase Execution → Result Aggregation**
```python
@dataclass
class PhaseResults:
    results: Dict[LinterInstance, List[LinterResult]]  # Chunk results
    phase_modified: bool  # True if mutating phase modified files
    failures: List[Tuple[LinterInstance, LinterResult]]  # Failed linters
```

---

### Stage Boundary 9-10: **Result Aggregation → Fileset Refresh** (conditional)
```python
@dataclass
class AggregatedResults:
    all_results: Dict[LinterInstance, LinterResult]  # Merged & deduplicated
    meta: Meta  # Accumulated warnings/errors
    files_modified: bool  # Any mutating phase modified files
```

---

### Stage Boundary 10-11: **Fileset Refresh → Output Formatting**
```python
@dataclass
class RefreshedFileset:
    files: List[str]  # Filtered (deleted removed)
    fileset_by_linter: Dict[LinterInstance, List[str]]  # Pruned cache
```

---

### Stage Boundary 11-Exit: **Output Formatting → Exit**
```python
@dataclass
class FormattedOutput:
    text: str  # YAML or text formatted output
    exit_code: int  # 0 = success, 1 = failure, 130 = interrupted
```

---

## Conclusion

The **Data Flow Pipeline Architecture** decomposes the parallel linter algorithm into 11 distinct stages with clear data transformations. This approach excels at:

- Making data flow explicit and transparent
- Enabling unit testing of pure function stages
- Isolating I/O and side effects to specific stages (Discovery, Preflight, Execution)
- Providing clear extension points via interfaces

However, it introduces:

- Verbosity from intermediate data structures
- Complexity in handling the phase execution loop (feedback loop)
- Potential over-abstraction for a relatively linear algorithm

**Recommendation:** This decomposition is most valuable if the project prioritizes testability, maintainability, and future extensibility (e.g., adding new file discovery modes, output formats, or execution strategies). For a simpler codebase with fewer anticipated changes, a less formal decomposition may suffice.

The key insight is that **stages 1-3, 6-7, 9, and 11 are pure or nearly pure functions**, making them ideal candidates for extraction. **Stages 4, 5, 8, and 10** involve I/O and side effects, requiring adapter interfaces for testability and flexibility.
