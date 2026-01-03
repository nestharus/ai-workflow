# Candidate 2: Domain-Driven Components

## Overview

This analysis identifies natural domain boundaries in the parallel linter algorithm by grouping responsibilities into cohesive components with clear interfaces. Each domain owns specific state and operations while depending on well-defined contracts from other domains.

## Domain Boundaries

### 1. File Discovery Domain

**Core Responsibility**: Git-based file identification and filesystem path management

**Exclusive Responsibilities**:
- Execute git commands for file discovery (`git ls-files`, `git diff`, `git diff-tree`)
- Normalize paths to repository-relative format
- Deduplicate file lists while preserving order
- Filter files by existence (`os.path.exists`)
- Apply optional global ignore patterns
- Sort file lists deterministically
- Handle --changed-only, --commit, --files, and whole-repo modes
- Detect and report empty file sets

**Public Interface**:
```python
class FileDiscoveryDomain:
    def get_files(
        mode: FileMode,  # CHANGED_ONLY | COMMIT | EXPLICIT | WHOLE_REPO
        commit: Optional[str] = None,
        explicit_files: Optional[List[str]] = None
    ) -> FileDiscoveryResult

    def filter_existing_files(files: List[str]) -> List[str]

    def normalize_path(path: str, repo_root: str) -> str

# Result type
FileDiscoveryResult:
    files: List[str]
    warnings: List[str]  # e.g., "Some explicit file args not found"
    errors: List[str]    # e.g., "Requested files not found"
    mode: FileMode
```

**Dependencies**:
- None (leaf domain)
- Only uses: subprocess, os.path, filesystem

**Owned State**:
- Repository root path
- Global ignore patterns (if configured)
- Git command execution context

**Borrowed State**:
- None

**Key Characteristics**:
- Pure computation domain
- No state mutation
- Idempotent operations
- No knowledge of linters or scheduling

---

### 2. Linter Configuration Domain

**Core Responsibility**: Linter specification parsing, expansion, validation, and instance management

**Exclusive Responsibilities**:
- Parse linter spec strings with operators (>=, >, <=, <, none)
- Expand specs to concrete linter lists using LINTER_NAMES ordering
- Validate linter names against known registry
- Track explicitly requested linters (operator == none)
- Convert linter names to linter instances
- Assign unique instance_id to each linter instance
- Calculate filesets for linters (`calculate_fileset`)
- Execute preflight tests (`linter.test()`)
- Manage linter metadata (mutates_files, parallel_safe, priority, scope)

**Public Interface**:
```python
class LinterConfigDomain:
    def expand_linter_specs(
        specs: Optional[List[str]]
    ) -> LinterExpansionResult

    def create_instances(
        linter_names: List[str]
    ) -> List[LinterInstance]

    def run_preflight(
        instances: List[LinterInstance],
        workers: int
    ) -> PreflightResult

    def calculate_filesets(
        instances: List[LinterInstance],
        files: List[str]
    ) -> Dict[LinterInstance, List[str]]

    def filter_filesets_by_existence(
        fileset_cache: Dict[LinterInstance, List[str]]
    ) -> Dict[LinterInstance, List[str]]

# Result types
LinterExpansionResult:
    linter_names: List[str]
    explicit_linters: Set[str]
    warnings: List[str]  # e.g., "spec expands to empty list"
    errors: List[str]    # e.g., "Invalid linter specification"

PreflightResult:
    passed: List[LinterInstance]
    failed: List[LinterInstance]
    warnings: List[str]
    errors: List[str]    # Set if explicit linter fails
```

**Dependencies**:
- File Discovery Domain: uses `filter_existing_files()` for fileset pruning

**Owned State**:
- LINTER_NAMES registry (ordered list of all known linters)
- Linter metadata registry (mutates_files, parallel_safe, priority, scope)
- Linter instance ID counter
- Preflight test results cache

**Borrowed State**:
- File list (from File Discovery Domain)

**Key Characteristics**:
- Configuration-centric domain
- Owns linter registry and metadata
- No execution knowledge
- Validation and preflight are concerns of this domain

---

### 3. Scheduling Domain

**Core Responsibility**: Phase construction, resource conflict resolution, and execution ordering

**Exclusive Responsibilities**:
- Classify linters by category (mutating, read-only parallel-safe, read-only sequential)
- Sort mutating linters deterministically (by priority, then name)
- Pack mutators into phases with disjoint resource sets (scope-aware: File vs Directory)
- Detect resource overlap and sequentialize conflicting mutators
- Create individual phases for read-only sequential linters
- Create final parallel phase for all read-only parallel-safe linters
- Tag phases with `is_mutating` metadata
- Order phases: all mutating phases before read-only phases
- Build phase items with chunked filesets (ARG_MAX-aware)
- Assign sequential chunk_id to tasks
- Validate --commit mode restrictions (no mutating linters)
- Drop linters with empty filesets and record skip reasons

**Public Interface**:
```python
class SchedulingDomain:
    def schedule_linters(
        instances: List[LinterInstance],
        fileset_cache: Dict[LinterInstance, List[str]],
        commit_mode: bool,
        available_cpus: int,
        env_size: int
    ) -> SchedulingResult

    def chunk_fileset_for_arg_max(
        fileset: List[str],
        base_cmd_len: int,
        env_len: int,
        safety_margin: int = 2048
    ) -> List[List[str]]

# Result types
SchedulingResult:
    phases: List[Phase]
    skipped: Dict[LinterInstance, SkipReason]
    warnings: List[str]
    errors: List[str]  # e.g., "Mutating linters forbidden with --commit"

Phase:
    linters: List[LinterInstance]
    is_mutating: bool
    items: List[PhaseItem]

PhaseItem:
    linter: LinterInstance
    fileset_chunk: List[str]
    chunk_id: int
    snapshot_path: Optional[str]  # For mutators
```

**Dependencies**:
- Linter Configuration Domain: uses linter metadata (mutates_files, parallel_safe, priority, scope)
- Linter Configuration Domain: uses `calculate_filesets()` result (via fileset_cache parameter)

**Owned State**:
- Phase construction logic
- Resource conflict detection algorithm
- ARG_MAX chunking parameters
- Sequential chunk_id counter per phase

**Borrowed State**:
- Linter instances (from Linter Configuration Domain)
- Fileset cache (from Linter Configuration Domain)
- Available CPU count (from Entry Point)
- Environment size (from system)

**Key Characteristics**:
- Pure planning domain
- No execution
- Deterministic scheduling
- Owns resource conflict resolution logic

---

### 4. Execution Domain

**Core Responsibility**: Linter process execution, concurrency management, and result collection

**Exclusive Responsibilities**:
- Calculate worker pool sizes (preflight, phase execution)
- Manage ThreadPoolExecutor for preflight
- Manage ProcessPoolExecutor for linter execution
- Create filesystem snapshots for mutating linters (before submit)
- Submit linter tasks with `_run_linter_safe()`
- Track running tasks (process groups on POSIX, Job Objects on Windows)
- Collect results via `as_completed()` (no head-of-line blocking)
- Handle shutdown_event and fail-fast cancellation
- Hard-stop running tasks (terminate process groups/close Job Objects)
- Restore snapshots for crashed/cancelled mutating tasks
- Build linter commands with chunked file arguments
- Execute linter subprocesses with timeout enforcement
- Capture stdout/stderr with size limits
- Kill entire process trees on timeout
- Decode output with backslash replacement
- Strip ANSI sequences for YAML safety
- Normalize paths in output to repo-relative
- Handle subprocess exceptions (TimeoutError, FileNotFoundError, etc.)
- Aggregate chunk results per linter
- Deduplicate diagnostics by hash(file, line, col, rule_id)

**Public Interface**:
```python
class ExecutionDomain:
    def execute_phases(
        phases: List[Phase],
        available_cpus: int,
        fail_fast: bool,
        yaml_output: bool,
        max_concurrency: Optional[int] = None
    ) -> ExecutionResult

    def execute_phase(
        phase: Phase,
        available_cpus: int,
        fail_fast: bool,
        yaml_output: bool,
        max_concurrency: Optional[int] = None
    ) -> Dict[LinterInstance, LinterResult]

    def run_linter_safe(
        linter: LinterInstance,
        fileset_chunk: List[str],
        chunk_id: int,
        snapshot_path: Optional[str]
    ) -> LinterResult

# Result types
ExecutionResult:
    all_results: Dict[LinterInstance, LinterResult]
    phase_modified: Dict[int, bool]  # phase_index -> files_modified
    errors: List[str]  # e.g., "Mutating linter crashed"

LinterResult:
    status: Status  # SUCCESS | FAILURE | SKIPPED | TIMEOUT | CRASHED
    exit_code: Optional[int]
    stdout: str
    stderr: str
    file_list: List[str]
    files_modified: bool
    chunk_id: int
    skip_reason: Optional[SkipReason]
    traceback: Optional[str]  # For crashes
```

**Dependencies**:
- File Discovery Domain: uses `filter_existing_files()` for deleted file detection
- Linter Configuration Domain: uses `filter_filesets_by_existence()` after mutating phases
- Scheduling Domain: uses Phase and PhaseItem structures

**Owned State**:
- Worker pool executors (ThreadPoolExecutor, ProcessPoolExecutor)
- Running task registry (process groups/Job Objects)
- Snapshot storage and recovery logic
- Output buffers for sliding-window flush
- shutdown_event flag
- next_expected_chunk_id counter
- Generation counter for fail-fast cancellation

**Borrowed State**:
- Phases (from Scheduling Domain)
- Available CPU count (from Entry Point)

**Key Characteristics**:
- Concurrency-heavy domain
- Process lifecycle management
- Snapshot/restore for fault tolerance
- Real-time output streaming in text mode
- No knowledge of output formatting

---

### 5. Output Domain

**Core Responsibility**: Result formatting, exit code calculation, and structured output generation

**Exclusive Responsibilities**:
- Detect output format mode (yaml vs text)
- Format text output (phase headers, progress, warnings, errors)
- Format YAML output with structured meta + results
- Aggregate warnings and errors into meta structure
- Calculate exit codes (0=success, 1=failure, 130=SIGINT)
- Flush stdout/stderr buffers
- Coordinate sliding-window output in text mode (delegates buffering to Execution Domain)
- Format skip reasons (no_matching_files, preflight_failed, input_files_vanished)
- Format linter results (status, exit_code, stdout, stderr, file_list, files_modified)
- Include traceback in output for crashes

**Public Interface**:
```python
class OutputDomain:
    def __init__(self, yaml_output: bool):
        pass

    def report_file_count(self, count: int, mode: FileMode) -> None

    def report_no_files(self, mode: FileMode) -> None

    def report_phase_header(self, phase: Phase) -> None

    def report_warning(self, message: str) -> None

    def report_error(self, message: str) -> None

    def output_final_results(
        self,
        all_results: Dict[LinterInstance, LinterResult],
        meta: OutputMeta
    ) -> None

    def calculate_exit_code(
        self,
        all_results: Dict[LinterInstance, LinterResult],
        meta: OutputMeta
    ) -> int

# Data types
OutputMeta:
    warnings: List[str]
    errors: List[str]
```

**Dependencies**:
- All domains: aggregates warnings/errors from all domains
- Execution Domain: receives LinterResult structures

**Owned State**:
- Output format mode (yaml vs text)
- Meta accumulator (warnings, errors)
- Text mode: whether to suppress output

**Borrowed State**:
- All results (from Execution Domain)
- Warnings/errors from all domains

**Key Characteristics**:
- Presentation-only domain
- No business logic
- Format-specific rendering
- Exit code is owned by this domain

---

## Cross-Domain Interfaces

### File Discovery → Linter Configuration
```python
# Linter Configuration uses normalized file lists
files = file_discovery.get_files(mode, commit, explicit_files)
fileset_cache = linter_config.calculate_filesets(instances, files.files)

# Linter Configuration uses file existence filter
pruned_filesets = linter_config.filter_filesets_by_existence(fileset_cache)
# which internally calls:
# file_discovery.filter_existing_files(fileset)
```

### Linter Configuration → Scheduling
```python
# Scheduling uses linter instances and fileset cache
scheduling_result = scheduling.schedule_linters(
    instances=linter_config.create_instances(linter_names),
    fileset_cache=linter_config.calculate_filesets(instances, files),
    commit_mode=args.commit,
    available_cpus=available_cpus,
    env_size=env_size
)
```

### Scheduling → Execution
```python
# Execution uses phases from scheduling
execution_result = execution.execute_phases(
    phases=scheduling_result.phases,
    available_cpus=available_cpus,
    fail_fast=args.fail_fast,
    yaml_output=yaml_output,
    max_concurrency=args.max_concurrency
)
```

### Execution → File Discovery (for drift handling)
```python
# After mutating phase, execution uses file discovery to detect deleted files
if phase.is_mutating and execution_result.phase_modified[phase_index]:
    files = file_discovery.filter_existing_files(files)
    fileset_cache = linter_config.filter_filesets_by_existence(fileset_cache)
    # (which internally calls file_discovery.filter_existing_files)
```

### All Domains → Output
```python
# Output aggregates warnings/errors from all domains
meta = OutputMeta(warnings=[], errors=[])
meta.warnings.extend(file_discovery_result.warnings)
meta.errors.extend(file_discovery_result.errors)
meta.errors.extend(linter_expansion_result.errors)
meta.warnings.extend(preflight_result.warnings)
meta.errors.extend(preflight_result.errors)
meta.errors.extend(scheduling_result.errors)
meta.errors.extend(execution_result.errors)

output.output_final_results(execution_result.all_results, meta)
exit_code = output.calculate_exit_code(execution_result.all_results, meta)
```

---

## Domain Dependency Graph

```
┌─────────────────────┐
│ File Discovery      │ (leaf - no dependencies)
└──────────┬──────────┘
           │
           │ uses filter_existing_files()
           ↓
┌─────────────────────┐
│ Linter Config       │
└──────────┬──────────┘
           │
           │ provides instances + fileset_cache
           ↓
┌─────────────────────┐
│ Scheduling          │
└──────────┬──────────┘
           │
           │ provides phases
           ↓
┌─────────────────────┐
│ Execution           │ ←──┐ uses filter_existing_files()
└──────────┬──────────┘    │ (for deleted file detection)
           │                │
           │                │
           │        ┌───────┴──────────┐
           │        │ File Discovery   │
           │        └──────────────────┘
           │
           │ provides results
           ↓
┌─────────────────────┐
│ Output              │ (receives from all domains)
└─────────────────────┘
```

**Dependency Flow**:
1. File Discovery (leaf)
2. Linter Configuration (depends on File Discovery)
3. Scheduling (depends on Linter Configuration)
4. Execution (depends on Scheduling + File Discovery + Linter Configuration)
5. Output (receives from all)

**Cycle**: Execution → File Discovery (for deleted file detection) is acceptable because it's a utility call, not a structural dependency.

---

## State Ownership Analysis

### File Discovery Domain

**Owned**:
- Repository root path (immutable after init)
- Global ignore patterns (immutable configuration)
- Git command results (transient)

**Borrowed**:
- None

**Shared**:
- None

### Linter Configuration Domain

**Owned**:
- LINTER_NAMES registry (immutable)
- Linter metadata registry (immutable)
- Linter instance ID counter (mutable, sequential)
- Preflight results cache (mutable, write-once per linter)
- Fileset cache (mutable, refreshed after mutating phases)

**Borrowed**:
- File list (from File Discovery, read-only)

**Shared**:
- None

### Scheduling Domain

**Owned**:
- Phase structures (immutable after construction)
- PhaseItem structures (immutable after construction)
- chunk_id counter (mutable, sequential)
- Resource conflict detection state (transient)

**Borrowed**:
- Linter instances (from Linter Configuration, read-only)
- Fileset cache (from Linter Configuration, read-only)

**Shared**:
- None

### Execution Domain

**Owned**:
- Worker pool executors (mutable, lifecycle-managed)
- Running task registry (mutable, tracking in-flight tasks)
- Snapshot storage (mutable, created/restored per task)
- Output buffers (mutable, sliding window in text mode)
- shutdown_event flag (mutable, set on fail-fast/SIGINT)
- next_expected_chunk_id (mutable, incremented during output flush)
- Generation counter (mutable, incremented on cancellation)
- Aggregated results (mutable, built during execution)

**Borrowed**:
- Phases (from Scheduling, read-only)
- available_cpus (from Entry Point, read-only)

**Shared**:
- None (snapshots are task-local, cleanup is domain-owned)

### Output Domain

**Owned**:
- Output format mode (immutable)
- Meta accumulator (mutable, aggregates warnings/errors)
- Text mode suppression flag (immutable)

**Borrowed**:
- All results (from Execution, read-only)
- Warnings/errors from all domains (read-only, copied into meta)

**Shared**:
- None

---

## Key Insights

### Clean Separation of Concerns

Each domain has a **single, well-defined responsibility**:
- **File Discovery**: "What files should we check?"
- **Linter Configuration**: "What linters should run, and on which files?"
- **Scheduling**: "In what order, and how should we group them?"
- **Execution**: "Run the linters and collect results."
- **Output**: "Show the user what happened."

### Unidirectional Data Flow

The dependency graph is **acyclic** (except for the utility call from Execution back to File Discovery for deleted file detection, which is acceptable):

```
File Discovery → Linter Config → Scheduling → Execution → Output
                       ↑                          │
                       └──────────────────────────┘
                         (for deleted file pruning)
```

### Minimized Interface Surface

Each domain exposes a **small, focused interface**:
- File Discovery: 3 methods
- Linter Configuration: 5 methods
- Scheduling: 2 methods
- Execution: 3 methods
- Output: 6 methods

### State Ownership is Clear

- **File Discovery**: owns repo context, borrows nothing
- **Linter Configuration**: owns registry + cache, borrows file list
- **Scheduling**: owns phase plan, borrows instances + fileset cache
- **Execution**: owns runtime state, borrows phases
- **Output**: owns presentation state, borrows results

### Fault Tolerance is Localized

- **Execution Domain** exclusively owns:
  - Snapshot creation/restoration
  - Process tree termination
  - Exception handling in `_run_linter_safe()`
  - Fail-fast cancellation logic

### Concurrency is Isolated

- **Execution Domain** exclusively owns:
  - Worker pool management
  - Task submission and tracking
  - Output buffering and flush logic
  - shutdown_event coordination

No other domain needs to understand threading, multiprocessing, or process groups.

### ARG_MAX Chunking is Scheduling's Concern

The **Scheduling Domain** owns the logic for splitting filesets into ARG_MAX-safe chunks and assigning sequential chunk_ids. Execution just runs the tasks.

### Output Formatting is Separate from Execution

The **Output Domain** has no execution logic. The **Execution Domain** has no formatting logic. They communicate via structured `LinterResult` objects.

---

## Potential Refactoring Path

If this candidate is chosen, the refactoring would:

1. **Extract File Discovery Domain** into a separate module (e.g., `file_discovery.py`)
2. **Extract Linter Configuration Domain** into a separate module (e.g., `linter_config.py`)
3. **Extract Scheduling Domain** into a separate module (e.g., `scheduler.py`)
4. **Extract Execution Domain** into a separate module (e.g., `executor.py`)
5. **Extract Output Domain** into a separate module (e.g., `output.py`)
6. **Main orchestrator** (`run_linters.py`) would:
   - Parse arguments
   - Call file_discovery.get_files()
   - Call linter_config.expand_linter_specs() + create_instances()
   - Call linter_config.calculate_filesets() + run_preflight()
   - Call scheduler.schedule_linters()
   - Call executor.execute_phases()
   - Call output.output_final_results()
   - Exit with output.calculate_exit_code()

**Benefits**:
- Each domain is independently testable
- Clear contracts reduce coupling
- State ownership prevents hidden dependencies
- Easy to reason about data flow
- Natural boundaries for future extensions (e.g., adding a new domain for remote execution)

**Trade-offs**:
- More files and modules
- Some overhead from interface marshalling
- Need to pass fileset_cache explicitly between domains (instead of implicit global state)

---

## Comparison with Current Algorithm

The current algorithm **already exhibits these domain boundaries implicitly**:
- File determination logic is clustered in `_get_changed_files()`, `_get_repo_files()`, `_filter_existing_files()`
- Linter spec expansion is in `_expand_linter_spec()`
- Scheduling logic is in `schedule_linters()`
- Execution logic is in `execute_phase()`, `_run_linter_safe()`, `_execute_parallel_linters()`, `_execute_single_linter()`
- Output logic is in `_output_yaml_results()`, exit code calculation, and scattered print statements

**This candidate formalizes the existing structure** by making the boundaries explicit and extracting them into separate components with well-defined interfaces.

The **key improvement** is that dependencies become **explicit parameters** instead of being accessed via shared global state or nested helper functions. This makes testing, reuse, and modification significantly easier.
