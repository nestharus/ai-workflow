# Coupling Analysis: Parallel Linter Algorithm

## Executive Summary

This analysis identifies coupling patterns, dependencies, and shared state across the algorithm's subgraphs. The algorithm exhibits **high coupling** through shared state variables, with several hotspots and circular dependencies that create complexity.

### Key Findings:
- **7 primary state variables** accessed by multiple subgraphs
- **4 high-coupling hotspots** (state accessed by 5+ components)
- **2 circular dependency cycles** identified
- **3 natural seam boundaries** for potential splitting

---

## 1. Subgraph State Analysis

### 1.1 Initialization (Init)

**State Variables Written:**
- `errors_by_linter` (map: linter → diagnostics with file paths + `<PROJECT>`)
- `passed_linters` (map: file → set of linters)
- `investigation_futures` (map: target → future + start hash/fingerprint)
- `pending_investigation_targets` (map: target → {error_snapshot, agent_output_snapshot})
- `unlintable_targets` (map: target → reason)
- `stale_linters` (map: linter → status + blocked_by set)
- `seen_hashes` (map: target → set of hashes/fingerprints)

**State Variables Read:**
- None (initialization only)

**Direct Transitions To:**
- MainLoop (G)

**Hidden Coupling:**
- Establishes all shared state containers
- No coupling yet (first subgraph)

---

### 1.2 Check Completed Investigations (InvCheck)

**State Variables Read:**
- `investigation_futures` (check completion)
- `stale_linters` (check blocked_by sets)
- `seen_hashes` (verify hash/fingerprint matches investigation start)
- `errors_by_linter` (for NOOP/FAILURE paths)
- `passed_linters` (for NOOP/FAILURE paths)

**State Variables Written:**
- `investigation_futures` (remove completed)
- `stale_linters` (update blocked_by, mark PENDING_REFRESH)
- `seen_hashes` (record new hashes for MODIFIED path, clear for STALE/external change)
- `changed_files` (transient: set modified files)
- `project_changed` (transient: set if `<PROJECT>` modified)
- `candidate_stalled_*` (clear for external changes)
- `unlintable_targets` (add NO_OP/FAILURE targets, clear for external changes)
- `pending_investigation_targets` (clear for external changes)
- `errors_by_linter` (remove diagnostics for NOOP/FAILURE)
- `passed_linters` (clear for NOOP/FAILURE targets)

**Direct Transitions To:**
- Self (H loop for multiple investigations)
- ErrorCheck (N)
- ProcessLinters (AC via JDROP/K3)
- Cleanup (ABORT for `<PROJECT>` UNLINTABLE)

**Hidden Coupling:**
- Writes transient state (`changed_files`, `project_changed`) consumed by ProcessLinters
- Modifies `stale_linters` that gate ErrorCheck and UpdateState behavior
- Hash verification creates implicit dependency on hash stability

---

### 1.3 Check Error Files (ErrorCheck)

**State Variables Read:**
- `stale_linters` (check PENDING_REFRESH, filter actionable errors)
- `investigation_futures` (get locked files)
- `unlintable_targets` (filter actionable targets)
- `pending_investigation_targets` (filter actionable targets)
- `errors_by_linter` (build actionable_errors_by_linter)

**State Variables Written:**
- `changed_files` (transient: set to empty for refresh-only tick)
- `project_changed` (transient: set to false for refresh-only tick)
- `candidate_stalled_files` (transient: set to empty for refresh-only tick)
- `candidate_stalled_targets` (transient: set to empty for refresh-only tick)
- `investigation_futures` (reserve pending targets, snapshot hashes)
- `pending_investigation_targets` (clear when dispatching)
- `seen_hashes` (update for external changes via EXT path)
- `candidate_stalled_*` (clear for external changes via EXT path)
- `unlintable_targets` (clear changed files via EXT path)

**Direct Transitions To:**
- ProcessLinters (AC via NREF0)
- Self (G loop if waiting/pending)
- UpdateState (SUCCESS)
- Cleanup (FATAL, ABORT)
- AgentPhase (R0 if actionable targets exist)

**Hidden Coupling:**
- Derives `actionable_errors_by_linter` from multiple state sources
- Computes `actionable_targets` using set operations on 4 state variables
- Refresh-only tick modifies transient state consumed by ProcessLinters
- WAIT2 external change path writes same state as InvCheck JDROP

---

### 1.4 Agent Phase (AgentPhase)

**State Variables Read:**
- `actionable_files` (from ErrorCheck transient state)
- `actionable_targets` (from ErrorCheck transient state)
- `errors_by_linter` (build agent input)
- `stale_linters` (filter errors for agent input)
- `seen_hashes` (verify pre-write safety, check for duplicates)

**State Variables Written:**
- `seen_hashes` (record pre-agent hashes, record post-agent hashes)
- `changed_files` (transient: set modified files)
- `project_changed` (transient: set if project fingerprint changed)
- `candidate_stalled_files` (transient: actionable_files - changed_files)
- `candidate_stalled_targets` (transient: includes `<PROJECT>` if unchanged)

**Direct Transitions To:**
- ProcessLinters (AC)
- ErrorCheck (EXT via S0 pre-write check failure)

**Hidden Coupling:**
- Reads transient state from ErrorCheck (`actionable_files`, `actionable_targets`)
- Writes transient state (`changed_files`, `project_changed`, `candidate_stalled_*`) consumed by ProcessLinters
- Hash verification (S0) creates implicit dependency on InvCheck/ErrorCheck hash management
- Duplicate hash detection in R1/U1 prevents processing same content twice

---

### 1.5 Process Each Linter's Errors (ProcessLinters)

**State Variables Read:**
- `changed_files` (transient: from AgentPhase or InvCheck)
- `project_changed` (transient: from AgentPhase or InvCheck)
- `candidate_stalled_files` (transient: from AgentPhase)
- `candidate_stalled_targets` (transient: from AgentPhase)
- `errors_by_linter` (copy to new_errors)
- `passed_linters` (preserve for unchanged files)
- `investigation_futures` (get locked files)
- `unlintable_targets` (filter files to check)
- `stale_linters` (read, then clear for refreshed linters)

**State Variables Written:**
- `passed_linters` (clear for changed files/project; record new passes)
- `errors_by_linter` (update via new_errors)
- `stale_linters` (clear for refreshed linters, upsert for blocked linters)

**Direct Transitions To:**
- UpdateState (AS)

**Hidden Coupling:**
- Depends on transient state from AgentPhase or InvCheck
- Reads 5+ persistent state variables for linting logic
- Modifies `stale_linters` that gates ErrorCheck and UpdateState
- `passed_linters` clearing logic depends on `project_changed` (global impact)

---

### 1.6 Update State (UpdateState)

**State Variables Read:**
- `errors_by_linter` (from ProcessLinters via new_errors)
- `stale_linters` (filter verified errors)
- `candidate_stalled_targets` (transient: from AgentPhase)
- `pending_investigation_targets` (filter, read snapshots for investigation)

**State Variables Written:**
- `errors_by_linter` (assign new_errors)
- `pending_investigation_targets` (upsert deferrals, remove submitted targets, filter resolved)
- `candidate_stalled_targets` (clear for deferred/submitted targets)
- `investigation_futures` (add submitted investigations, snapshot start hashes)
- `passed_linters` (clear for submitted targets, clear all for `<PROJECT>` submission)

**Direct Transitions To:**
- MainLoop (G)
- Cleanup (SUCCESS)

**Hidden Coupling:**
- Computes multiple derived sets from persistent state
- Granular gating logic couples to `stale_linters` state
- `<PROJECT>` submission triggers global `passed_linters` clear (hidden global side effect)
- Manages investigation lifecycle (submit, defer, track)

---

### 1.7 Cleanup

**State Variables Read:**
- `unlintable_targets` (for final report)

**State Variables Written:**
- None

**Direct Transitions To:**
- None (terminal)

**Hidden Coupling:**
- Read-only reporting phase
- No coupling with other subgraphs

---

## 2. Coupling Matrix

### 2.1 State Variable Access Matrix

| State Variable | Init | InvCheck | ErrorCheck | AgentPhase | ProcessLinters | UpdateState | Cleanup |
|----------------|------|----------|------------|------------|----------------|-------------|---------|
| `errors_by_linter` | W | R+W | R | R | R+W | R+W | - |
| `passed_linters` | W | R+W | - | - | R+W | W | - |
| `investigation_futures` | W | R+W | R+W | - | R | W | - |
| `pending_investigation_targets` | W | W | R+W | - | - | R+W | - |
| `unlintable_targets` | W | W | R | - | R | - | R |
| `stale_linters` | W | R+W | R | R | R+W | R | - |
| `seen_hashes` | W | R+W | W | R+W | - | - | - |
| `changed_files` (transient) | - | W | W | W | R | - | - |
| `project_changed` (transient) | - | W | W | W | R | - | - |
| `candidate_stalled_*` (transient) | - | W | W | W | R | R+W | - |

**Legend:**
- R = Read
- W = Write
- R+W = Read and Write
- `-` = Not accessed

---

### 2.2 Subgraph Transition Matrix

| From Subgraph | To Subgraphs | Condition |
|---------------|--------------|-----------|
| Init | MainLoop (G) | Always |
| InvCheck | InvCheck (H loop) | More investigations to check |
| InvCheck | ErrorCheck (N) | No more investigations |
| InvCheck | ProcessLinters (AC) | MODIFIED/STALE detected |
| InvCheck | Cleanup (ABORT) | `<PROJECT>` UNLINTABLE |
| ErrorCheck | ProcessLinters (AC) | PENDING_REFRESH tick |
| ErrorCheck | AgentPhase (R0) | Actionable targets exist |
| ErrorCheck | MainLoop (G) | Waiting/pending/stale |
| ErrorCheck | UpdateState (SUCCESS) | No actionable errors |
| ErrorCheck | Cleanup (FATAL/ABORT) | Invariant violation / `<PROJECT>` UNLINTABLE |
| AgentPhase | ProcessLinters (AC) | Always (or EXT via S0 failure) |
| ProcessLinters | UpdateState (AS) | Always |
| UpdateState | MainLoop (G) | Errors/investigations remain |
| UpdateState | Cleanup (SUCCESS) | No errors/investigations |

---

## 3. High-Coupling Hotspots

### 3.1 Hotspot: `errors_by_linter`
**Accessed by:** 5 subgraphs (Init, InvCheck, ErrorCheck, AgentPhase, ProcessLinters, UpdateState)

**Coupling Type:** Read-Write by multiple components

**Risk:**
- Central data structure for algorithm state
- Modified by InvCheck (NOOP/FAILURE removal), ProcessLinters (lint updates), UpdateState (assignment)
- Read by ErrorCheck (actionable filtering), AgentPhase (input building)
- Changes ripple through all dependent subgraphs

**Mitigation Opportunities:**
- Consider immutable snapshots for reads
- Separate read path from write path

---

### 3.2 Hotspot: `stale_linters`
**Accessed by:** 5 subgraphs (Init, InvCheck, ErrorCheck, AgentPhase, ProcessLinters, UpdateState)

**Coupling Type:** Read-Write with complex state machine (STALE → SUSPENDED → PENDING_REFRESH)

**Risk:**
- Gates behavior across multiple subgraphs (ErrorCheck filters, AgentPhase filters, ProcessLinters refresh, UpdateState granular gating)
- State transitions (blocked_by updates, PENDING_REFRESH marking) create temporal coupling
- Incorrect state management could cause deadlocks or missed refreshes

**Mitigation Opportunities:**
- Extract stale linter state machine into separate component
- Formalize state transition rules

---

### 3.3 Hotspot: Transient State (`changed_files`, `project_changed`, `candidate_stalled_*`)
**Written by:** 3 subgraphs (InvCheck, ErrorCheck, AgentPhase)
**Read by:** 2 subgraphs (ProcessLinters, UpdateState)

**Coupling Type:** Producer-consumer through transient variables

**Risk:**
- Implicit data flow not visible in state variable declarations
- Multiple writers (InvCheck for external changes, ErrorCheck for refresh-only, AgentPhase for normal flow)
- ProcessLinters assumes transient state is correctly populated
- No explicit "handoff" mechanism

**Mitigation Opportunities:**
- Formalize transient state as explicit message passing
- Single writer per transient variable per path

---

### 3.4 Hotspot: `investigation_futures`
**Accessed by:** 4 subgraphs (Init, InvCheck, ErrorCheck, ProcessLinters, UpdateState)

**Coupling Type:** Lifecycle management (create, check, remove)

**Risk:**
- Locks/unlocks targets across algorithm
- ErrorCheck and ProcessLinters read to filter actionable targets
- InvCheck removes completed futures
- UpdateState adds new futures
- Incorrect lifecycle management causes target leaks or double-processing

**Mitigation Opportunities:**
- Encapsulate investigation lifecycle in separate component
- Enforce strict ownership model (reserve → process → release)

---

## 4. Low-Coupling Boundaries (Natural Seams)

### 4.1 Seam: Investigation Management
**Components:** InvCheck, UpdateState, ErrorCheck (reserve/dispatch logic)

**Boundary Characteristics:**
- Investigation lifecycle is self-contained (futures, pending targets, snapshots)
- Clear inputs: completed futures
- Clear outputs: modified files, unlintable targets
- Interface: Investigation status (MODIFIED/NO_OP/FAILURE), hashes/fingerprints

**Split Potential:** HIGH
- Could extract into "Investigation Manager" component
- Interface: submit investigation, check status, handle results
- Reduces coupling in main loop

---

### 4.2 Seam: Lint Execution
**Components:** ProcessLinters

**Boundary Characteristics:**
- ProcessLinters is largely isolated
- Reads transient state from AgentPhase
- Writes to `errors_by_linter`, `passed_linters`, `stale_linters`
- Does not directly interact with investigations or agent

**Split Potential:** MEDIUM
- Could extract into "Linter Orchestrator" component
- Interface: lint targets, return new errors
- Still tightly coupled to `errors_by_linter` schema

---

### 4.3 Seam: Agent Invocation
**Components:** AgentPhase

**Boundary Characteristics:**
- Single responsibility: run agent, detect changes
- Inputs: actionable targets, errors
- Outputs: changed files, stalled candidates
- Minimal state dependencies (reads `errors_by_linter`, `stale_linters`, `seen_hashes`)

**Split Potential:** MEDIUM-HIGH
- Could extract into "Agent Runner" component
- Interface: run agent on targets, return change detection results
- Hash management (seen_hashes) creates coupling

---

## 5. Circular Dependencies

### 5.1 Cycle: Investigation → ProcessLinters → UpdateState → Investigation

**Path:**
1. InvCheck completes investigation (writes `changed_files`)
2. Flow goes to ProcessLinters (AC) (reads `changed_files`)
3. ProcessLinters updates `errors_by_linter`
4. Flow goes to UpdateState (reads `errors_by_linter`)
5. UpdateState submits new investigations (writes `investigation_futures`)
6. Flow returns to MainLoop, eventually InvCheck checks new futures

**Risk:**
- Loop can stall if investigations keep producing same errors
- No max retry limit (Concept 16 explicitly allows ping-pong)
- Infinite loop potential if Investigator produces MODIFIED with no actual diff (mitigated by Concept 16 UNLINTABLE marking)

**Mitigation:**
- Concept 16 mitigates (MODIFIED without diff → UNLINTABLE)
- `seen_hashes` provides cycle detection
- Consider adding explicit loop counter for safety

---

### 5.2 Cycle: ErrorCheck WAIT2 → External Change → ProcessLinters → UpdateState → ErrorCheck

**Path:**
1. ErrorCheck WAIT2 detects external change
2. Writes `changed_files`, goes to ProcessLinters (AC via EXT)
3. ProcessLinters updates `errors_by_linter`
4. Flow goes to UpdateState
5. UpdateState returns to MainLoop (G)
6. MainLoop returns to ErrorCheck
7. ErrorCheck may enter WAIT2 again

**Risk:**
- External changes during waiting can cause rapid re-linting
- File watcher churn could create hot loop
- Concept 17 mitigates (non-blocking wait, yield/sleep)

**Mitigation:**
- WAIT2 is non-blocking with yield/sleep
- File watcher should debounce/batch changes
- Consider rate limiting refresh cycles

---

## 6. Shared State Deep Dive

### 6.1 `errors_by_linter` (Critical Shared State)

**Writers:**
- InvCheck (removes diagnostics for NOOP/FAILURE targets)
- ProcessLinters (assigns new_errors after lint run)
- UpdateState (assigns new_errors from ProcessLinters)

**Readers:**
- ErrorCheck (builds actionable_errors_by_linter)
- AgentPhase (builds agent input with errors)

**Coupling Issues:**
- Multiple mutation points create temporal dependencies
- ErrorCheck filtering logic duplicated (exclude stale_linters, unlintable, locked)
- No ownership model (multiple components assume authority)

**Recommendations:**
- Single writer pattern: Only ProcessLinters writes full state
- InvCheck should send "remove diagnostics" command rather than direct write
- Consider immutable updates with versioning

---

### 6.2 `stale_linters` (Complex State Machine)

**State Transitions:**
- `empty` → `STALE/SUSPENDED` (ProcessLinters AG2A: linter blocked by locks)
- `STALE/SUSPENDED` → `PENDING_REFRESH` (InvCheck I2C: locks cleared)
- `PENDING_REFRESH` → `empty` (ProcessLinters AI0A: refresh completed)

**Writers:**
- InvCheck (updates blocked_by, marks PENDING_REFRESH)
- ProcessLinters (clears on refresh, upserts on block)

**Readers:**
- ErrorCheck (PENDING_REFRESH check, actionable filter)
- AgentPhase (error filter)
- ProcessLinters (check status)
- UpdateState (filter verified errors, granular gating)

**Coupling Issues:**
- State machine is implicit (not formalized)
- Multiple components assume knowledge of state transitions
- PENDING_REFRESH gating (ErrorCheck NREF) forces refresh-only tick (side effect)

**Recommendations:**
- Formalize state machine with explicit transitions
- Encapsulate in "StaleLinterManager" component
- Event-based notifications for state changes

---

### 6.3 `investigation_futures` (Lifecycle Coupling)

**Lifecycle Stages:**
1. Reserve (ErrorCheck O4B: snapshot hashes, add to futures)
2. Dispatch (ErrorCheck O4B: async send)
3. Check (InvCheck H: poll completion)
4. Remove (InvCheck I2: completed)
5. Add new (UpdateState BG4: submit stalled targets)

**Coupling Issues:**
- ErrorCheck and UpdateState both add futures (two submission paths)
- InvCheck owns removal
- ProcessLinters and ErrorCheck read for filtering
- No explicit ownership transfer

**Recommendations:**
- Single submission entry point (unified reserve/dispatch)
- Encapsulate lifecycle in InvestigationManager
- Explicit lock/unlock API

---

### 6.4 `seen_hashes` (Deduplication State)

**Purpose:** Prevent processing same content twice, detect external changes

**Writers:**
- InvCheck (record new hashes for MODIFIED, clear for STALE/external)
- ErrorCheck (clear for external changes)
- AgentPhase (record pre-agent and post-agent hashes)
- UpdateState (snapshot investigation start hashes)

**Readers:**
- InvCheck (verify investigation staleness)
- AgentPhase (verify pre-write safety, check duplicates in R1/U1)

**Coupling Issues:**
- Multiple writers create window for race conditions
- Clearing logic duplicated (InvCheck JDROP, ErrorCheck EXT)
- No explicit "window" management (when to clear old hashes?)

**Recommendations:**
- Centralize hash management
- Explicit "processing window" with lifecycle
- Consider LRU cache for bounded memory

---

## 7. Dependency Graph Summary

### 7.1 Component Dependencies (Strong Coupling)

```
Init
  └─> MainLoop
       ├─> InvCheck
       │    ├─> Self (loop)
       │    ├─> ErrorCheck
       │    ├─> ProcessLinters ───┐
       │    └─> Cleanup           │
       │                           │
       ├─> ErrorCheck              │
       │    ├─> ProcessLinters ───┤
       │    ├─> AgentPhase        │
       │    │    └─> ProcessLinters (merge)
       │    ├─> UpdateState       │
       │    └─> Cleanup           │
       │                           │
       └─> ProcessLinters <───────┘
            └─> UpdateState
                 ├─> MainLoop (loop)
                 └─> Cleanup
```

### 7.2 State Variable Dependencies (Read/Write Graph)

**High Dependency (5+ accessors):**
- `errors_by_linter`: 6 components
- `stale_linters`: 6 components
- `investigation_futures`: 5 components
- Transient state: 5 components (3 writers, 2 readers)

**Medium Dependency (3-4 accessors):**
- `passed_linters`: 4 components
- `pending_investigation_targets`: 4 components
- `seen_hashes`: 4 components

**Low Dependency (2 accessors):**
- `unlintable_targets`: 3 components (mostly write-once)

---

## 8. Recommendations for Decoupling

### 8.1 High Priority (Critical Hotspots)

1. **Extract Investigation Manager**
   - Encapsulate `investigation_futures`, `pending_investigation_targets`
   - Single submission API (consolidate ErrorCheck O4B and UpdateState BG4A)
   - Owns investigation lifecycle and hash tracking
   - **Impact:** Reduces coupling in 4 subgraphs

2. **Formalize Stale Linter State Machine**
   - Explicit state transition component
   - Event-based notifications for state changes
   - Single source of truth for blocked_by logic
   - **Impact:** Reduces implicit coupling in 5 subgraphs

3. **Immutable `errors_by_linter` Updates**
   - Copy-on-write pattern
   - Single writer (ProcessLinters)
   - InvCheck sends removal commands instead of direct mutation
   - **Impact:** Eliminates temporal coupling, easier to reason about

### 8.2 Medium Priority (Transient State Management)

4. **Formalize Transient State Handoff**
   - Explicit "ProcessingContext" message
   - Single writer per context per path
   - Type-safe handoff to ProcessLinters
   - **Impact:** Makes data flow explicit, reduces hidden coupling

5. **Centralize Hash Management**
   - Single "HashTracker" component
   - Owns `seen_hashes` lifecycle
   - Provides verification and deduplication APIs
   - **Impact:** Eliminates duplicate clearing logic, centralizes race condition handling

### 8.3 Low Priority (Nice to Have)

6. **Extract Linter Orchestrator**
   - Encapsulate ProcessLinters logic
   - Returns immutable lint results
   - **Impact:** Moderate (still needs `errors_by_linter` schema knowledge)

7. **Extract Agent Runner**
   - Encapsulate AgentPhase logic
   - Returns change detection results
   - **Impact:** Moderate (still couples to hash management)

---

## 9. Coupling Metrics

### 9.1 Afferent Coupling (Incoming Dependencies)

| Component | Afferent Coupling | Dependent Components |
|-----------|-------------------|---------------------|
| ProcessLinters | 4 | InvCheck, ErrorCheck, AgentPhase, UpdateState |
| MainLoop | 3 | Init, UpdateState, ErrorCheck |
| Cleanup | 3 | InvCheck, ErrorCheck, UpdateState |
| ErrorCheck | 2 | InvCheck, UpdateState |
| UpdateState | 1 | ProcessLinters |
| InvCheck | 1 | MainLoop |
| AgentPhase | 1 | ErrorCheck |

**High Afferent Coupling:**
- ProcessLinters (4): Convergence point for multiple paths
- MainLoop (3): Loop control point

### 9.2 Efferent Coupling (Outgoing Dependencies)

| Component | Efferent Coupling | Dependencies |
|-----------|-------------------|--------------|
| InvCheck | 4 | ErrorCheck, ProcessLinters, Cleanup, Self |
| ErrorCheck | 5 | ProcessLinters, AgentPhase, UpdateState, Cleanup, MainLoop |
| UpdateState | 2 | MainLoop, Cleanup |
| AgentPhase | 2 | ProcessLinters, ErrorCheck |
| ProcessLinters | 1 | UpdateState |
| MainLoop | 1 | InvCheck |
| Cleanup | 0 | None (terminal) |

**High Efferent Coupling:**
- ErrorCheck (5): Fan-out to many components
- InvCheck (4): Multiple exit paths

### 9.3 Instability Metric (Ce / (Ca + Ce))

| Component | Instability | Interpretation |
|-----------|-------------|----------------|
| Cleanup | 0.00 | Stable (terminal) |
| ProcessLinters | 0.20 | Stable |
| MainLoop | 0.25 | Stable |
| UpdateState | 0.67 | Unstable |
| InvCheck | 0.80 | Unstable |
| AgentPhase | 0.67 | Unstable |
| ErrorCheck | 0.71 | Unstable |

**High Instability (>0.5):**
- ErrorCheck, InvCheck, AgentPhase, UpdateState
- These components are most sensitive to changes
- Refactoring should prioritize stabilizing these

---

## 10. Critical Coupling Patterns

### 10.1 Pattern: "Global Clear" Side Effect

**Location:** Multiple components

**Example:**
- `passed_linters` cleared globally when `project_changed = true` (ProcessLinters AC)
- `passed_linters` cleared globally when `<PROJECT>` submitted to investigation (UpdateState BG5)

**Risk:**
- Hidden global side effect not obvious from local code
- Components far from the mutation point are affected
- Hard to trace bugs related to cleared state

**Mitigation:**
- Make global clears explicit (separate function)
- Log global state mutations
- Consider event notification for observers

---

### 10.2 Pattern: "Duplicate Filtering Logic"

**Location:** ErrorCheck, AgentPhase, ProcessLinters

**Example:**
- ErrorCheck: `actionable_errors_by_linter = errors_by_linter excluding stale_linters AND unlintable`
- AgentPhase: Build agent input excluding stale_linters
- ProcessLinters: Filter out diagnostics for inv_files + unlintable

**Risk:**
- Same filtering logic in multiple places
- If filtering rules change, must update all locations
- Inconsistent filtering creates bugs

**Mitigation:**
- Extract "getActionableErrors()" helper
- Centralize filtering rules
- Single source of truth for exclusion logic

---

### 10.3 Pattern: "Transient State Handoff"

**Location:** InvCheck → ProcessLinters, ErrorCheck → ProcessLinters, AgentPhase → ProcessLinters

**Example:**
- InvCheck writes `changed_files`, `project_changed`, clears `candidate_stalled_*`
- ProcessLinters reads these transient variables
- No explicit contract or validation

**Risk:**
- Implicit data flow
- No guarantee transient state is set correctly
- Different code paths set different subsets of transient variables

**Mitigation:**
- Formalize as ProcessingContext message
- Validation at ProcessLinters entry
- Type-safe context passing

---

### 10.4 Pattern: "Multiple Submission Paths"

**Location:** ErrorCheck O4B, UpdateState BG4A

**Example:**
- ErrorCheck: Reserve pending_investigation_targets, dispatch async
- UpdateState: Submit stalled targets, dispatch async
- Both add to `investigation_futures`

**Risk:**
- Duplicate submission logic
- Inconsistent snapshotting (ErrorCheck uses stored snapshots, UpdateState uses current tick)
- Race conditions if both paths active

**Mitigation:**
- Single "submitInvestigation()" function
- Consolidate submission logic
- Enforce mutex on submission

---

## 11. Conclusion

### Summary of Coupling Analysis:

1. **High-Coupling State Variables (4):**
   - `errors_by_linter` (6 accessors)
   - `stale_linters` (6 accessors)
   - `investigation_futures` (5 accessors)
   - Transient state (5 accessors)

2. **Circular Dependencies (2):**
   - Investigation → ProcessLinters → UpdateState → Investigation
   - ErrorCheck WAIT2 → ProcessLinters → UpdateState → ErrorCheck

3. **Natural Seam Boundaries (3):**
   - Investigation Management (HIGH split potential)
   - Lint Execution (MEDIUM split potential)
   - Agent Invocation (MEDIUM-HIGH split potential)

4. **Critical Patterns (4):**
   - Global Clear Side Effect
   - Duplicate Filtering Logic
   - Transient State Handoff
   - Multiple Submission Paths

### Architectural Recommendations:

**Phase 1 (Decouple Critical Hotspots):**
- Extract Investigation Manager component
- Formalize Stale Linter state machine
- Implement immutable `errors_by_linter` updates

**Phase 2 (Formalize Implicit Coupling):**
- Introduce ProcessingContext message for transient state
- Centralize hash management in HashTracker
- Consolidate filtering logic into helpers

**Phase 3 (Component Extraction):**
- Extract Linter Orchestrator
- Extract Agent Runner
- Evaluate further splitting based on Phase 1-2 insights

### Risk Assessment:

**Highest Risk Components (by coupling):**
- ErrorCheck (5 dependencies, 5 transient writes, 5 state reads)
- InvCheck (4 dependencies, 10 state writes, 5 state reads)
- UpdateState (complex derivation logic, 2 investigation submission paths)

**Refactoring Priority:**
1. Investigation lifecycle management (affects 4 subgraphs)
2. Stale linter state machine (affects 5 subgraphs)
3. Transient state handoff (affects 3 write paths, 2 read paths)

This coupling analysis provides a roadmap for systematic decoupling to improve maintainability, testability, and evolvability of the parallel linter algorithm.
