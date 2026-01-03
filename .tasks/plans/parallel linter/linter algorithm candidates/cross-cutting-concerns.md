# Cross-Cutting Concerns in Linter Algorithm

These concerns span multiple components and will influence any decomposition strategy.

## 1. Shutdown Coordination

**Locations in algorithm:**
- `SETUP_SIGNALS` - Signal handler registration
- `CHECK_SHUTDOWN` - Shutdown event check in as_completed loop
- `CANCEL_FUTURES` - Executor shutdown, process termination
- `EX_SIGINT_HANDLE` - SIGINT cleanup

**Coupling created:**
- Main process must coordinate with worker processes
- Snapshot restoration requires access to snapshot paths
- Executor shutdown requires access to all executors
- Output buffering must flush on shutdown

**Abstraction needed:**
- `ShutdownCoordinator` with registration pattern
- Components register cleanup callbacks
- Centralized shutdown event propagation

---

## 2. Error/Warning Accumulation (Meta)

**Locations in algorithm:**
- `INIT_META` - Initialize meta dict
- `MUTUAL_ERR`, `INVALID_SPEC`, `UNKNOWN_ERR` - Add errors
- `WARN_DROPPED`, `PREFLIGHT_DROP` - Add warnings
- `OUTPUT_YAML` - Include in output
- `CALC_EXIT` - Influence exit code

**Coupling created:**
- Every component needs access to meta
- Text vs YAML mode affects whether errors print immediately
- Exit code calculation needs to aggregate from meta + results

**Abstraction needed:**
- `DiagnosticCollector` with typed diagnostics
- Separation of accumulation from presentation
- Clear ownership: who adds, who reads

---

## 3. Output Mode (YAML vs Text)

**Locations in algorithm:**
- `YAML_CHECK` - Mode detection
- `SHOULD_PRINT_PHASE` - Conditional phase headers
- `BUFFER_OUTPUT` vs `NO_PRINT` - Different result handling
- `FINAL_OUTPUT` - Different formatters

**Coupling created:**
- Conditional behavior scattered throughout
- Text mode needs sliding window buffering
- YAML mode suppresses stderr messages

**Abstraction needed:**
- `OutputStrategy` interface
- `TextOutputStrategy` with buffering
- `YamlOutputStrategy` with structured accumulation
- Commands emit to strategy, not directly to stdout/stderr

---

## 4. File State Tracking

**Locations in algorithm:**
- `files` - Initial file list
- `fileset_by_linter` - Cached per-linter filesets
- `PRUNE_DELETED` / `PRUNE_FILESET_CACHE` - Post-mutation refresh
- `EXISTS_UNCOMMITTED` / `EXISTS_COMMIT` - Existence filtering

**Coupling created:**
- Multiple components read/write file lists
- Mutation detection triggers cache invalidation
- Existence checks at multiple points

**Abstraction needed:**
- `FileRegistry` with immutable snapshots
- Clear ownership of file list mutations
- Event-driven cache invalidation

---

## 5. Process Lifecycle Management

**Locations in algorithm:**
- `PROCESS_POOL` - Executor creation
- `SUBMIT_ALL` - Task submission with snapshot tracking
- `LINTER_RUN` - Subprocess execution with process groups
- `CANCEL_FUTURES` - Process termination

**Coupling created:**
- Main process tracks snapshot paths per task
- Platform-specific termination (POSIX vs Windows)
- Timeout handling interleaved with normal execution

**Abstraction needed:**
- `ProcessManager` with task lifecycle
- Platform abstraction for termination
- Snapshot association with tasks

---

## 6. Result Aggregation

**Locations in algorithm:**
- `all_results` - Global results dict
- `COLLECT_RESULTS` - Chunk aggregation
- `PHASE_MODIFIED` - Mutation detection from results
- `CHECK_FAILURES` - Failure detection from results

**Coupling created:**
- Multiple access points to results dict
- Chunk results need aggregation before storage
- Deduplication logic embedded in aggregation

**Abstraction needed:**
- `ResultCollector` with typed results
- Separation of raw results from aggregated results
- Clear aggregation boundaries

---

## 7. Linter Instance Identity

**Locations in algorithm:**
- `ASSIGN_INSTANCE_ID` - ID assignment
- `fileset_by_linter` - Keyed by linter instance
- `all_results` - Keyed by linter instance
- Phase items contain linter references

**Coupling created:**
- Instance ID in `__hash__/__eq__`
- Same linter config with different IDs are distinct
- Results must correlate with original instances

**Abstraction needed:**
- `LinterRegistry` with identity management
- Stable IDs across phase boundaries
- Clear association of results to instances

---

## Summary: Shared Abstractions Needed

| Concern | Abstraction | Pattern |
|---------|-------------|---------|
| Shutdown | `ShutdownCoordinator` | Observer/Callback |
| Diagnostics | `DiagnosticCollector` | Accumulator |
| Output | `OutputStrategy` | Strategy |
| Files | `FileRegistry` | Immutable Snapshot |
| Processes | `ProcessManager` | Lifecycle |
| Results | `ResultCollector` | Accumulator |
| Linters | `LinterRegistry` | Identity Map |

These abstractions should be designed before choosing a decomposition strategy, as they form the integration points between components.
