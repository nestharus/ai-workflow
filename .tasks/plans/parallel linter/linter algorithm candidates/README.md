# Linter Algorithm Decomposition Candidates

This directory contains analysis of different decomposition strategies for the parallel linter algorithm.

## Candidates Overview

| # | Candidate | Focus | Best For |
|---|-----------|-------|----------|
| 1 | [Data Flow Pipeline](candidate-1-data-flow-pipeline.md) | Transformation stages | Testability, explicit data flow |
| 2 | [Domain-Driven](candidate-2-domain-driven.md) | Business boundaries | Clear ownership, maintainability |
| 3 | [Layered Architecture](candidate-3-layered.md) | Horizontal abstractions | Replaceability, error isolation |
| 4 | [State Machine](candidate-4-state-machine.md) | Control flow states | Observability, recovery |
| 5 | [Process-Centric](candidate-5-process-centric.md) | Process management | Reliability, platform abstraction |

## Supporting Documents

- [Cross-Cutting Concerns](cross-cutting-concerns.md) - Shared abstractions needed across all candidates

---

## Candidate 1: Data Flow Pipeline Architecture

**Approach**: Decompose into 11 pipeline stages with clear input/output data types.

**Stages Identified**:
1. Argument Processing → 2. File Discovery → 3. Linter Selection → 4. Applicability Pre-scan → 5. Preflight Validation → 6. Phase Scheduling → 7. Phase Item Generation → 8. Phase Execution → 9. Result Aggregation → 10. Fileset Refresh → 11. Output Formatting

**Strengths**:
- Clear data transformation boundaries
- Pure stages (1-3, 6-7, 9, 11) highly testable
- Explicit caching opportunities

**Weaknesses**:
- Phase execution loop breaks pure pipeline model
- 5+ interfaces may feel over-abstracted
- Snapshot complexity doesn't decompose cleanly

**Key Interfaces**: `FileSystemAdapter`, `LinterRegistry`, `ExecutionAdapter`, `OutputAdapter`, `StateManager`

---

## Candidate 2: Domain-Driven Components

**Approach**: Identify 5 natural domain boundaries with clear ownership.

**Domains Identified**:
1. **File Discovery** - Git operations, path normalization (leaf domain)
2. **Linter Configuration** - Specs, instances, preflight, metadata
3. **Scheduling** - Phases, resource conflicts, ARG_MAX chunking
4. **Execution** - Process management, result collection
5. **Output** - Formatting, exit codes

**Strengths**:
- Single responsibility per domain
- Unidirectional data flow (mostly acyclic)
- Formalizes existing implicit structure

**Weaknesses**:
- Execution → File Discovery creates minor cycle (for deleted file detection)
- fileset_cache passed explicitly between domains

**Key Insight**: The current algorithm *already exhibits these boundaries implicitly*. This candidate formalizes them.

---

## Candidate 3: Layered Architecture

**Approach**: 5 horizontal layers with strict upward-only dependencies.

**Layers** (bottom to top):
1. **Git/Filesystem** - File discovery, path operations
2. **Execution** - Subprocess lifecycle, output capture
3. **Scheduling** - Phase planning, preflight, chunking
4. **Orchestration** - Phase loop, result aggregation
5. **CLI** - Arguments, output formatting, exit codes

**Strengths**:
- Well-defined abstraction boundaries
- Layer N replaceable without modifying N-1
- Consistent error propagation via `meta` and `LinterResult`

**Weaknesses**:
- Orchestration reaches into Scheduling's cache (violation)
- Snapshot management split across layers
- Output buffering logic leaks from CLI into Orchestration

**Refactoring Priority**: 1) Move phase item generation to Scheduling, 2) Consolidate snapshot lifecycle in Execution, 3) Consider separate Output layer

---

## Candidate 4: State Machine Decomposition

**Approach**: 6 explicit states with well-defined transitions.

**States**:
1. **INIT** - Parse args, detect resources, register signals
2. **FILE_DISCOVERY** - Determine files based on mode
3. **SCHEDULING** - Expand specs, preflight, build phases
4. **EXECUTING** - Run phases, collect results, handle failures
5. **OUTPUT** - Format results, calculate exit code
6. **ERROR** - Handle exceptions, cleanup, restore snapshots

**Terminal States**: SUCCESS (exit 0), FAILURE (exit 1), INTERRUPTED (exit 130)

**Strengths**:
- Explicit control flow and transitions
- Each state independently testable
- Clear hooks for monitoring and recovery
- Natural error state with centralized handling

**Weaknesses**:
- `LinterContext` is large and mutable
- EXECUTING state is internally complex (substates: RUNNING, COLLECTING, HANDLING_FAILURE, PRUNING_FILES)
- More files and indirection

**Key Insight**: The algorithm is well-suited for state machine decomposition with clear states, transitions, and decision points.

---

## Candidate 5: Process-Centric Decomposition

**Approach**: Isolate 5 major process management concerns.

**Process Concerns**:
1. **Process Lifecycle** - Pool creation, tree management, termination
2. **Signal Handling** - SIGINT coordination, shutdown callbacks
3. **Snapshot Management** - Create, track, restore for mutators
4. **Result Collection** - Aggregation, ordering, shutdown-aware streaming
5. **Resource Limits** - CPU detection, ARG_MAX chunking, worker sizing

**Proposed Components**:
- `ProcessPoolManager`, `ProcessTreeManager`, `SubprocessRunner`
- `ShutdownCoordinator`, `SignalHandler`, `CleanupOrchestrator`
- `SnapshotManager`, `FilesetSnapshot`
- `ResultCollector`, `OrderedOutputBuffer`, `ResultStreamHandler`
- `CPUDetector`, `ArgMaxChunker`, `WorkerPoolSizer`, `ResourceBudget`

**Strengths**:
- Process concerns separated from linting logic
- Platform differences (POSIX/Windows) encapsulated
- Explicit failure modes and recovery paths
- Highly testable with mocked process/file I/O

**Weaknesses**:
- Many components = many interfaces
- Coordination logic distributed across components
- Shutdown ordering critical

**Recommended Approach**: Start with pure functions (`CPUDetector`, `ArgMaxChunker`), progress to stateful infrastructure, tackle coordination last.

---

## Comparison Matrix

| Criterion | Pipeline | Domain | Layered | StateMachine | Process |
|-----------|----------|--------|---------|--------------|---------|
| **Testability** | High (pure stages) | High | Medium | High | Very High |
| **Maintainability** | Medium | High | High | Medium | High |
| **Understandability** | Medium | High | High | High | Medium |
| **Complexity Added** | High | Medium | Low | Medium | High |
| **Refactoring Effort** | High | Medium | Low | High | Medium |
| **Error Isolation** | Medium | High | High | Very High | High |
| **Platform Abstraction** | Low | Low | Low | Low | Very High |

---

## Recommendation

**For a first decomposition pass, consider a hybrid approach:**

1. **Start with Domain-Driven (Candidate 2)** - Formalizes existing structure with minimal refactoring. Create 5 modules: `file_discovery.py`, `linter_config.py`, `scheduler.py`, `executor.py`, `output.py`.

2. **Add Process-Centric components incrementally (Candidate 5)** - Extract pure functions first (`CPUDetector`, `ArgMaxChunker`), then stateful components (`SnapshotManager`, `ShutdownCoordinator`).

3. **Consider State Machine (Candidate 4) for the main orchestrator** - Make state transitions explicit for better observability and error handling.

4. **Use Cross-Cutting Concerns abstractions** - Implement `DiagnosticCollector`, `OutputStrategy`, `FileRegistry` to reduce coupling across domains.

This hybrid approach provides:
- Clear domain ownership (Domain-Driven)
- Isolated process management (Process-Centric)
- Explicit control flow (State Machine)
- Shared infrastructure (Cross-Cutting)

---

## Next Steps

1. Choose primary decomposition strategy
2. Identify first component to extract
3. Create detailed interface specifications
4. Write tests for extracted component
5. Implement and integrate incrementally
