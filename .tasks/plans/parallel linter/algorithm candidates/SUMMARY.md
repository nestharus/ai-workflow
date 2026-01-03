# Algorithm Decomposition Summary

## Executive Summary

The parallel linter algorithm has been analyzed through 5 decomposition candidates and 4 specialized sub-agent analyses. This document synthesizes the findings to recommend an optimal splitting strategy.

## Key Findings

### Critical Bugs Discovered

| ID | Severity | Description | Location |
|----|----------|-------------|----------|
| 6.4 | **HIGH** | Refresh-only tick race condition - stale linter may run before all blocking targets complete | ProcessLinters subgraph |
| 6.5 | **HIGH** | Linter failure causes deadlock - failed linter stays in PENDING_REFRESH forever | ProcessLinters → UpdateState |
| 6.3 | **MEDIUM** | `required_linter` ambiguity - undefined behavior when target has errors from multiple linters | StallDetection |

### High-Coupling Hotspots

1. **`errors_by_linter`** - Read by 6+ locations, written by 3
2. **`stale_linters`** - Read by 8+ locations, written by 5
3. **`investigation_futures`** - Both lock and result management
4. **Transient state** (`changed_files`, `candidate_stalled_*`) - Scattered mutations

### Circular Dependencies

1. **Staleness ↔ Investigation** cycle: Investigations block linters → Linters determine stalls → Stalls create investigations
2. **Error ↔ Target** cycle: Errors define targets → Target status filters errors

### Natural Seam Boundaries (Recommended Split Points)

| Seam | Split Potential | Rationale |
|------|-----------------|-----------|
| Investigation Management | **HIGH** | Self-contained lifecycle with clear entry/exit |
| Lint Execution | MEDIUM | Clear input (files) and output (diagnostics) |
| Agent Invocation | MEDIUM-HIGH | Isolated with CAS protection boundary |

## Candidate Comparison Matrix

| Criterion | State-Centric | Lifecycle | Responsibility | Event-Driven | Layered |
|-----------|--------------|-----------|----------------|--------------|---------|
| Component count | 6 | 8 | 8 | 10+ | 5 layers |
| Coupling reduction | Medium | Medium | High | High | High |
| Testability | High | Medium | High | High | High |
| Implementation complexity | Low | Low | Medium | High | Medium |
| Matches algorithm structure | Medium | High | Medium | Low | Medium |
| Cross-cutting concern handling | Poor | Poor | Good | Good | Medium |
| Bug isolation | Medium | Low | High | High | Medium |

## Recommended Approach: Hybrid Strategy

Based on the analysis, a **hybrid approach** combining elements from multiple candidates provides the best balance:

### Phase 1: Extract High-Isolation Boundaries

Extract these components first (highest ROI, lowest risk):

```
┌─────────────────────────────────────────────────────────────┐
│  1. InvestigationManager (from Responsibility candidate)    │
│     - Owns: investigation_futures, pending_investigation    │
│     - Clear lifecycle: reserve → dispatch → poll → complete │
│     - Fixes: Bugs 6.4, 6.5 isolation                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  2. StalenessTracker (from State-Centric candidate)         │
│     - Owns: stale_linters, blocked_by tracking              │
│     - Addresses: Bugs 6.4, 6.5 directly                     │
│     - Clean state machine: ACTIVE → STALE → PENDING → ACTIVE│
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  3. ChangeDetector (from State-Centric candidate)           │
│     - Owns: seen_hashes, project fingerprint                │
│     - Provides: CAS verification, diff detection            │
│     - Low coupling to rest of system                        │
└─────────────────────────────────────────────────────────────┘
```

### Phase 2: Apply Layered Architecture

Once components are extracted, organize them into layers (from Candidate 5):

```
┌─────────────────────────────────────────────────────────────┐
│                    APPLICATION LAYER                         │
│             Orchestrator (minimal, sequencing only)          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      POLICY LAYER                            │
│  ActionabilityPolicy | StalenessPolicy | TerminationPolicy  │
│  (Pure decision logic, no state mutation)                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       STATE LAYER                            │
│  ErrorStore | TargetStore | StalenessTracker | ChangeDetector│
│  InvestigationManager (extracted components)                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   INFRASTRUCTURE LAYER                       │
│           Linters | FileSystem | Agent | AsyncExecutor       │
└─────────────────────────────────────────────────────────────┘
```

### Phase 3: Introduce Event-Driven for Cross-Cutting Concerns

For concerns that span multiple components, use events (from Candidate 4):

```python
# Key events to introduce
FilesChanged(files, source: Agent|External)
InvestigationCompleted(target, result)
LinterUnblocked(linter)
TerminationConditionMet(reason)
```

## Priority Order for Decoupling

1. **Immediate** (fixes critical bugs):
   - Extract `StalenessTracker` with explicit state machine
   - Add FAILURE state to handle Bug 6.5
   - Add "all blockers complete" gate for Bug 6.4

2. **High Priority** (reduces coupling):
   - Extract `InvestigationManager` with complete lifecycle
   - Extract `ChangeDetector` for CAS and diff logic

3. **Medium Priority** (improves testability):
   - Create `ActionabilityPolicy` for decision logic
   - Create `ErrorStore` with clean query interface

4. **Lower Priority** (optimization):
   - Event-based coordination
   - Full layer separation

## Cross-Cutting Concern Strategies

| Concern | Recommended Strategy |
|---------|---------------------|
| Staleness checking | Explicit state machine in StalenessTracker |
| Target normalization | Utility module, called at boundary entry points |
| Investigation lifecycle | State machine in InvestigationManager |
| Candidate stall debouncing | Encapsulate in StallDetector component |
| Unlintable management | Part of TargetStore, event-driven updates |
| passed_linters tracking | Part of TargetStore |

## Files Created

| File | Description |
|------|-------------|
| `candidate-1-state-centric.md` | State ownership-based decomposition (6 components) |
| `candidate-2-lifecycle.md` | Target lifecycle-based decomposition (8 stages) |
| `candidate-3-responsibility.md` | Domain-driven decomposition (8 responsibilities) |
| `candidate-4-event-driven.md` | Event/message-passing architecture |
| `candidate-5-layered.md` | Layered architecture (5 abstraction levels) |
| `analysis-coupling.md` | Coupling matrix and dependency analysis |
| `analysis-crosscutting.md` | Cross-cutting concerns with isolation strategies |
| `analysis-investigation.md` | Investigation lifecycle state machine |
| `analysis-staleness.md` | Stale linter management analysis with bugs |

## Next Steps

1. **Address Bug 6.5 immediately** - Add FAILURE state to stale linter tracking
2. **Extract StalenessTracker** - First component to isolate
3. **Add integration tests** - Before extraction, ensure behavior is captured
4. **Extract InvestigationManager** - Second component
5. **Define clear interfaces** - Use the API surfaces from candidates as starting point
