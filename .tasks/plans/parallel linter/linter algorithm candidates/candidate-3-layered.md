# Candidate 3: Layered Architecture Decomposition

## Overview

This analysis decomposes the parallel linter algorithm into five horizontal layers, each with a single responsibility and clear abstraction boundaries. The layers stack from low-level operations (Git/Filesystem) to high-level orchestration (CLI), with strict dependencies flowing upward only.

## Layer Definitions

### Layer 1: Git/Filesystem Layer

**Single Responsibility**: Provide file discovery and path operations as primitive abstractions.

**Core Operations**:
- `_get_changed_files(commit?)`: Query git for changed/untracked files
  - Staged + unstaged: `git diff HEAD --name-only --diff-filter=d`
  - Untracked: `git ls-files --others --exclude-standard`
  - Specific commit: `git diff-tree --no-commit-id --name-only --diff-filter=d -r <commit>`
- `_get_repo_files()`: Query entire repository file set
  - `git ls-files -co --exclude-standard`
- `_filter_existing_files(files)`: Validate file existence via `os.path.exists`
- Path normalization: `os.path.relpath(path, repo_root)`
- Deduplication: Preserve order while removing duplicates
- Sorting: Deterministic path ordering

**Abstraction Provided to Upper Layers**:
- **File list abstraction**: Returns sorted, normalized, deduplicated, validated file paths
- **Commit abstraction**: Treats commit SHA as opaque identifier for file state
- **Repository abstraction**: Hides .git internal structure behind file list queries

**Dependencies from Lower Layers**: None (底层/foundation layer)

**Abstractions Consumed**: None

**Error Handling**:
- **Git command failures**: Propagate OSError/RuntimeError with stderr details
- **Invalid commit SHA**: Propagate git error message
- **File not found**: Silent filtering via `os.path.exists` (not an error)
- **Path encoding issues**: Handle via `errors='backslashreplace'` during decode

**Error Propagation to Upper Layers**:
```
OSError/RuntimeError → Orchestration Layer → CLI Layer → meta.errors
```

---

### Layer 2: Execution Layer

**Single Responsibility**: Manage subprocess lifecycle, resource isolation, and output capture.

**Core Operations**:
- `_run_linter_safe(linter, fileset_chunk, chunk_id, snapshot_path)`:
  - Build command from linter spec + fileset chunk
  - Create process tree isolation (POSIX: `setsid`; Windows: Job Object)
  - Execute subprocess with timeout
  - Capture stdout/stderr separately with size limits
  - Decode output with `errors='backslashreplace'`
  - Strip ANSI escape codes for YAML safety
  - Normalize paths to repo-relative
  - Return `LinterResult{status, exit_code, stdout, stderr, file_list, files_modified, chunk_id}`
- Process group termination:
  - POSIX: Kill process group via `os.killpg`
  - Windows: Close Job Object to terminate all processes
- Snapshot management for mutators:
  - Create temp copy of fileset before execution
  - Atomic restore via `os.replace`/rename on crash/cancel
- Timeout enforcement: Kill entire process tree on expiry

**Abstraction Provided to Upper Layers**:
- **Linter result abstraction**: Uniform `LinterResult` object regardless of linter type
- **Process isolation abstraction**: Hides platform-specific process tree management
- **Output safety abstraction**: All output is decoded, ANSI-stripped, path-normalized
- **Crash recovery abstraction**: Automatic snapshot restore for mutating linters

**Dependencies from Lower Layers**: Git/Filesystem Layer (for path normalization)

**Abstractions Consumed**:
- Path normalization from Git/Filesystem Layer

**Error Handling**:
- **Timeout**: Return `LinterResult{status=timeout}` (not an exception)
- **FileNotFoundError** (input files vanished): Return `LinterResult{status=skipped, skip_reason=input_files_vanished}`
- **Subprocess crash**: Catch all exceptions, return `LinterResult{status=crashed}` with traceback
- **Encoding errors**: Handle via `errors='backslashreplace'` (never propagate UnicodeDecodeError)
- **Snapshot restore failure**: Propagate OSError to Orchestration Layer

**Error Propagation to Upper Layers**:
```
Subprocess failures → LinterResult.status (timeout/crashed/skipped)
Snapshot restore OSError → Orchestration Layer → CLI Layer → meta.errors
```

---

### Layer 3: Scheduling Layer

**Single Responsibility**: Determine execution phases, task chunking, and concurrency constraints.

**Core Operations**:
- `schedule_linters(linter_instances, files)`:
  - Classify linters: mutating vs read-only (sequential vs parallel-safe)
  - Sort mutating linters deterministically: by priority (asc), then name
  - Pack mutators into phases using resource disjointness (scope: File vs Directory)
    - Same phase: Disjoint file/directory sets
    - Separate phase: Overlapping resources
  - Create read-only sequential phases (one linter per phase)
  - Create read-only parallel phase (all parallel-safe linters)
  - Tag phases: `is_mutating` boolean
  - Order: All mutating phases before all read-only phases
- Applicability pre-scan:
  - `calculate_fileset(files)` for each linter (cached in `fileset_by_linter`)
  - Skip linters with empty filesets: `all_results[linter] = skipped(no_matching_files)`
- Preflight validation:
  - Run `linter.test()` in parallel for applicable linters only
  - Worker count: `min(len(selected), min(32, max(1, available_cpus * 2)))`
  - Per-linter timeout enforcement
  - Drop failing linters (unless explicitly requested by user)
- Task chunking:
  - `_chunk_fileset_for_arg_max(fileset, base_cmd_len, env_len, safety_margin=2KB)`
  - Account for: fixed command args + environment size + 2KB margin
  - Assign sequential `chunk_id` to each task

**Abstraction Provided to Upper Layers**:
- **Phase abstraction**: Ordered list of phases with mutating-ness metadata
- **Phase item abstraction**: `(linter, fileset_chunk, chunk_id)` tuples ready for execution
- **Fileset cache abstraction**: Pre-computed `fileset_by_linter` for reuse
- **Concurrency plan abstraction**: Which linters run together, which run sequentially

**Dependencies from Lower Layers**:
- Git/Filesystem Layer: File list input for `calculate_fileset`

**Abstractions Consumed**:
- File list from Git/Filesystem Layer

**Error Handling**:
- **Unknown linter**: Record in `meta.errors`, abort scheduling
- **Invalid linter spec**: Record in `meta.errors`, abort scheduling
- **Mutating linter with --commit**: Record in `meta.errors`, abort scheduling
- **No applicable linters**: Return empty phases (Orchestration decides exit code)
- **Preflight failure (explicit linter)**: Record in `meta.errors`, abort scheduling
- **Preflight failure (non-explicit linter)**: Add to `meta.warnings`, skip linter, continue
- **All linters fail preflight**: Record in `meta.errors`, abort scheduling

**Error Propagation to Upper Layers**:
```
Scheduling errors → meta.errors → CLI Layer → exit 1
Preflight warnings → meta.warnings → CLI Layer → YAML output
```

---

### Layer 4: Orchestration Layer

**Single Responsibility**: Coordinate phase execution, result aggregation, and inter-phase state management.

**Core Operations**:
- Phase execution loop:
  - Iterate through scheduled phases in order
  - Build `phase_items` from cached `fileset_by_linter`
  - Delegate to `execute_phase(phase_items, yaml_output, fail_fast)`
  - Aggregate chunk results per linter
  - Deduplicate diagnostics by `hash(file, line, col, rule_id)`
  - Store results in `all_results`
- `execute_phase(phase_items, yaml_output, fail_fast)`:
  - Single item: `_execute_single_linter()` (sequential)
  - Multiple items: `_execute_parallel_linters()` (ProcessPoolExecutor)
    - Worker count: `min(len(phase_items), max_concurrency or max(1, available_cpus))`
    - Submit all tasks with snapshots for mutators
    - Collect via `as_completed` (no head-of-line blocking)
    - Text mode: Buffer output by `chunk_id`, flush via sliding window
    - YAML mode: Suppress stdout printing
    - Fail-fast: Set `shutdown_event`, hard-stop tasks, restore snapshots
- Fileset drift management:
  - After mutating phase: `_filter_existing_files(files)`
  - Prune deleted paths from `fileset_by_linter`
- Mutating linter crash recovery:
  - Restore snapshot for crashed task only (atomic)
  - Record crash in `all_results` with traceback
  - Abort immediately (no further phases)
- Signal handling:
  - `setup_signal_handlers()`: Register SIGINT handler
  - On SIGINT: Set `shutdown_event`, shutdown executors, terminate process groups, restore snapshots

**Abstraction Provided to Upper Layers**:
- **Result aggregation abstraction**: Single `all_results` dict with per-linter outcomes
- **Execution state abstraction**: Transparent handling of parallel vs sequential execution
- **Crash recovery abstraction**: Automatic rollback of failed mutating operations
- **Output streaming abstraction**: Real-time, ordered text output despite parallel execution

**Dependencies from Lower Layers**:
- Scheduling Layer: Phases, phase items, fileset cache
- Execution Layer: `_run_linter_safe()`, process termination, snapshot restore
- Git/Filesystem Layer: `_filter_existing_files()` for drift management

**Abstractions Consumed**:
- Phase abstraction from Scheduling Layer
- LinterResult abstraction from Execution Layer
- File filtering from Git/Filesystem Layer

**Error Handling**:
- **Mutating linter crash**: Restore snapshot, record in `meta.errors`, abort
- **Non-mutating linter failure**: Continue to next phase (unless fail-fast)
- **Fail-fast trigger**: Cancel pending, hard-stop running, return partial results
- **SIGINT**: Graceful shutdown with snapshot restore, exit 130
- **Empty phase items**: Skip phase silently
- **Snapshot restore failure**: Record in `meta.errors`, abort

**Error Propagation to Upper Layers**:
```
Mutating crash → meta.errors → CLI Layer → exit 1
Non-mutating failure → all_results[linter].status → CLI Layer → exit 1 if any failure
SIGINT → CLI Layer → exit 130
```

---

### Layer 5: CLI Layer

**Single Responsibility**: Parse arguments, format output, determine exit codes.

**Core Operations**:
- `_parse_args()`: Parse command-line arguments into structured options
- `_get_available_cpus()`: Detect CPU count via `os.sched_getaffinity(0)` or `os.cpu_count()`
- File option validation:
  - Mutual exclusivity: `--changed-only`, `--files`, `--commit`
  - Record violations in `meta.errors`
- File option routing:
  - `--changed-only` → `_get_changed_files()`
  - `--commit SHA` → `_get_changed_files(commit)`
  - `--files` → `_filter_existing_files(args.files)` + dropped file warnings
  - None → `_get_repo_files()`
- Empty file set handling:
  - No changes/commit files: Print to stderr, exit 0
  - Explicit files not found: Record in `meta.errors`, exit 1
- Linter selection:
  - `_expand_linter_spec(spec)` for each user-provided spec
  - Track explicitly requested linters (for preflight error handling)
- Output formatting:
  - YAML mode: `_output_yaml_results(all_results, meta)` to stdout
  - Text mode: Real-time phase headers, sliding-window chunk output to stdout
  - Suppress stderr messages in YAML mode
- Exit code calculation:
  - `any_failure = (len(meta.errors) > 0) OR any(!r.success)`
  - Exit 1 if any failure
  - Exit 0 if no failures
  - Exit 130 on SIGINT

**Abstraction Provided to Upper Layers**: None (top layer)

**Dependencies from Lower Layers**:
- All layers: Orchestration → Scheduling → Execution → Git/Filesystem

**Abstractions Consumed**:
- File list from Git/Filesystem Layer
- Phases from Scheduling Layer
- Result aggregation from Orchestration Layer

**Error Handling**:
- **Mutually exclusive options**: Record in `meta.errors`, exit 1
- **Invalid linter spec**: Record in `meta.errors`, exit 1
- **Empty file set (explicit --files)**: Record in `meta.errors`, exit 1
- **Empty file set (--changed-only/--commit)**: Print to stderr, exit 0
- **No linters to run**: Print to stderr, exit 0
- **YAMLError**: Record in `meta.errors`, exit 1
- **RuntimeError/OSError**: Record in `meta.errors`, exit 1
- **All lower layer errors**: Accumulate in `meta.errors`, exit 1 if non-empty

**Error Propagation**: Terminal layer (no upward propagation, only exit code)

---

## Abstraction Boundaries

### Layer 1 → Layer 2

**Provided**: Normalized, validated file paths
**Consumed by**: Execution Layer for subprocess input

### Layer 2 → Layer 3

**Provided**: `LinterResult` abstraction (status, exit_code, output, chunk_id)
**Consumed by**: Scheduling Layer for preflight validation

### Layer 3 → Layer 4

**Provided**: Phases, phase items, fileset cache
**Consumed by**: Orchestration Layer for execution loop

### Layer 4 → Layer 5

**Provided**: Aggregated `all_results`, `meta` (warnings/errors)
**Consumed by**: CLI Layer for output formatting and exit code

---

## Error Flow Diagram

```
Git/Filesystem Layer
    ↓ OSError/RuntimeError (git failures)
Execution Layer
    ↓ LinterResult.status (timeout/crashed/skipped)
    ↓ OSError (snapshot restore failure)
Scheduling Layer
    ↓ meta.errors (unknown linter, invalid spec, preflight failures)
    ↓ meta.warnings (preflight failures for non-explicit linters)
Orchestration Layer
    ↓ meta.errors (mutating crashes, snapshot restore failures)
    ↓ all_results[linter].status (per-linter outcomes)
CLI Layer
    ↓ Exit code (1 = any failure, 0 = success, 130 = SIGINT)
```

---

## Error Handling Contracts

### Git/Filesystem Layer

**Throws**:
- `OSError`: Git command failures, filesystem errors
- `RuntimeError`: Git returns non-zero exit code

**Never Throws**:
- File not found (silent filter via `os.path.exists`)
- Path encoding issues (handled via `errors='backslashreplace'`)

### Execution Layer

**Returns (Never Throws)**:
- `LinterResult{status=timeout}` on timeout
- `LinterResult{status=crashed}` on subprocess exception
- `LinterResult{status=skipped, skip_reason=input_files_vanished}` on FileNotFoundError

**Throws (Only Fatal)**:
- `OSError`: Snapshot restore failure (propagates to Orchestration)

### Scheduling Layer

**Returns via meta**:
- `meta.errors`: Unknown linter, invalid spec, mutating + --commit, all preflights failed
- `meta.warnings`: Non-explicit linter preflight failures

**Never Throws**: All errors recorded in `meta`, empty phases returned on failure

### Orchestration Layer

**Returns via meta/all_results**:
- `meta.errors`: Mutating linter crash, snapshot restore failure
- `all_results[linter]`: Per-linter status (success/failure/skipped/timeout/crashed)

**Throws (Only on SIGINT)**:
- `KeyboardInterrupt`: Caught by CLI Layer, exit 130

### CLI Layer

**Never Throws**: All exceptions caught, recorded in `meta.errors`, exit 1

---

## Cross-Cutting Concerns

### 1. Path Normalization

**Owner**: Git/Filesystem Layer
**Consumers**: All layers use normalized paths
**Implementation**: Early normalization at layer boundary (git output → normalized list)

### 2. YAML vs Text Output

**Owner**: CLI Layer
**Affected Layers**:
- Orchestration Layer: Suppress/enable real-time output
- CLI Layer: Choose `_output_yaml_results()` vs text streaming

### 3. Fail-Fast

**Owner**: Orchestration Layer
**Mechanism**: `shutdown_event` flag, checked in `as_completed` loop
**Impact**: Triggers hard-stop of running tasks, cancellation of pending tasks

### 4. Shutdown Event (SIGINT)

**Owner**: CLI Layer (setup), Orchestration Layer (enforcement)
**Mechanism**: Shared `shutdown_event` across executors
**Impact**: All layers participate in graceful shutdown

### 5. Snapshot Management

**Owner**: Execution Layer (creation/restoration)
**Triggered by**: Orchestration Layer (on mutating task submission, crash, cancel)
**Scope**: Per-task isolation (only crashed task's snapshot restored)

---

## Layer Independence

### Can Layer N function without Layer N+1?

| Layer | Independent? | Notes |
|-------|--------------|-------|
| Git/Filesystem | Yes | Pure I/O operations, no upward dependencies |
| Execution | Yes | Can run single linter without scheduling |
| Scheduling | No | Requires Execution Layer for preflight, Orchestration for phase execution |
| Orchestration | No | Top-level coordinator, useless without CLI to invoke it |
| CLI | No | Entry point, depends on all layers |

### Can Layer N be replaced without modifying Layer N-1?

| Layer | Replaceable? | Interface Contract |
|-------|--------------|-------------------|
| Git/Filesystem | Yes | Return `List[str]` (normalized paths) |
| Execution | Yes | Return `LinterResult` object |
| Scheduling | Yes | Return `List[Phase]` with phase items |
| Orchestration | Partially | Tightly coupled to Scheduling's phase structure |
| CLI | Yes | Depends on Orchestration's `all_results` + `meta` |

---

## Layering Violations (Current Design)

### 1. Fileset Cache Ownership

**Issue**: `fileset_by_linter` created in Scheduling Layer, consumed in Orchestration Layer
**Violation**: Orchestration reaches into Scheduling's cache for phase item generation
**Fix**: Move phase item generation to Scheduling Layer, return complete phase items

### 2. Snapshot Creation

**Issue**: Snapshots created in Orchestration Layer (main process) before Execution Layer submission
**Violation**: Orchestration knows about Execution's snapshot mechanism
**Fix**: Move snapshot creation to Execution Layer, return snapshot handle to Orchestration

### 3. Output Buffering Logic

**Issue**: Orchestration Layer manages sliding-window output buffering (text mode)
**Violation**: Orchestration knows about CLI's output format requirements
**Fix**: Return ordered results to CLI Layer, let CLI handle buffering/streaming

---

## Recommendations

### 1. Strengthen Layer 3 → Layer 4 Boundary

**Current**: Orchestration generates phase items from cached fileset
**Proposed**: Scheduling Layer returns fully-formed phase items
**Benefit**: Clear ownership of task chunking and fileset application

### 2. Move Snapshot Management to Execution Layer

**Current**: Orchestration creates snapshots before submit
**Proposed**: Execution Layer creates/restores snapshots, returns handle to Orchestration
**Benefit**: Execution Layer fully owns subprocess lifecycle

### 3. Separate Output Layer

**Current**: Orchestration manages output buffering for CLI
**Proposed**: New Output Layer between Orchestration and CLI
**Benefit**: Decouple result ordering from execution coordination

### 4. Formalize Error Types

**Current**: Mix of exceptions, `meta.errors`, `LinterResult.status`
**Proposed**: Typed error hierarchy with layer-specific error classes
**Benefit**: Explicit error contracts at each layer boundary

---

## Summary

The parallel linter algorithm exhibits a **mostly clean layered architecture** with five distinct layers:

1. **Git/Filesystem**: Foundation I/O operations
2. **Execution**: Subprocess lifecycle and isolation
3. **Scheduling**: Concurrency planning and task preparation
4. **Orchestration**: Phase execution and result aggregation
5. **CLI**: Argument parsing and output formatting

**Strengths**:
- Clear vertical separation of concerns
- Well-defined abstraction boundaries for layers 1-3
- Consistent error handling propagation via `meta` and `LinterResult`

**Weaknesses**:
- Orchestration Layer reaches into Scheduling's cache (phase item generation)
- Snapshot management split between Orchestration (creation) and Execution (restoration)
- Output buffering logic leaks from CLI into Orchestration

**Refactoring Priority**:
1. Move phase item generation to Scheduling Layer
2. Consolidate snapshot lifecycle in Execution Layer
3. Consider separate Output Layer for result formatting
