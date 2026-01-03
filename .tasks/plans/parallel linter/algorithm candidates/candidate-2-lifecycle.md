# Candidate 2: Lifecycle-Based Split

## Philosophy
Split by **stages of a target's lifecycle** through the system. A target flows through distinct phases, and each phase is handled by a dedicated component.

## Target Lifecycle

```
[Discovery] → [Actionable] → [Agent Processing] → [Linting] → [Stall Detection] → [Investigation] → [Resolution]
     ↑                                                              │
     └──────────────────────────────────────────────────────────────┘
                              (re-enter on modification)
```

## Identified Components

### 1. TargetDiscovery
**Phase:** Extracting targets from linter output
**Responsibilities:**
- Parse linter output to extract error targets
- Normalize target identifiers (paths, casing)
- Distinguish file targets from `<PROJECT>` pseudo-target
- Track which linter produced which errors

**Triggers:** Initial lint, refresh-only tick, external change
**Outputs:** `errors_by_linter`, `all_error_targets`

### 2. ActionabilityGate
**Phase:** Determining what can be acted upon
**Responsibilities:**
- Filter targets by lock status (investigation_futures)
- Filter targets by unlintable status
- Filter targets by pending investigation status
- Filter linters by staleness status
- Determine if <PROJECT> can be acted upon

**Triggers:** Each main loop tick
**Outputs:** `actionable_targets`, `actionable_files`, `actionable_errors_by_linter`

### 3. AgentProcessor
**Phase:** Fixing errors via lint-fixer agent
**Responsibilities:**
- Prepare agent input (files + errors + context)
- Snapshot before agent invocation
- Invoke agent with CAS protection
- Detect changes after agent run
- Identify candidate stalled targets

**Triggers:** When actionable_targets is non-empty
**Outputs:** `changed_files`, `project_changed`, `candidate_stalled_targets`, agent output snapshot

### 4. LinterExecutor
**Phase:** Re-linting after agent changes
**Responsibilities:**
- Determine files to check per linter (scope: PROJECT vs FILES)
- Handle blocking files for project-scoped linters
- Run linters and ingest diagnostics
- Track passed_linters
- Mark stale linters when blocked

**Triggers:** After AgentProcessor or refresh tick
**Outputs:** Updated `errors_by_linter`, `passed_linters`, `stale_linters`

### 5. StallDetector
**Phase:** Detecting targets that didn't change after agent
**Responsibilities:**
- Compare candidate_stalled_targets with verified errors
- Partition into defer vs submit based on stale linters
- Store deferred targets with their snapshots

**Triggers:** After LinterExecutor
**Outputs:** `stalled_targets_ready`, `targets_to_defer`, `targets_to_submit`

### 6. InvestigationDispatcher
**Phase:** Launching investigations for stalled targets
**Responsibilities:**
- Reserve targets in investigation_futures
- Snapshot start hashes for staleness protection
- Build investigation payloads
- Dispatch async investigations

**Triggers:** When targets_to_submit is non-empty, or pending dispatch
**Outputs:** Reserved `investigation_futures`, dispatched investigations

### 7. InvestigationResolver
**Phase:** Handling completed investigations
**Responsibilities:**
- Poll for completed investigations
- Handle MODIFIED results (verify diff, apply or discard)
- Handle NO_OP results (mark unlintable)
- Handle FAILURE results (mark unlintable)
- Handle staleness (discard if hash changed)
- Update blocked_by for stale linters
- Trigger PENDING_REFRESH state

**Triggers:** Investigation future completion
**Outputs:** `unlintable_targets` updates, `changed_files`, `stale_linters` updates

### 8. TerminationChecker
**Phase:** Determining when to exit
**Responsibilities:**
- Check for success (no actionable errors, no investigations)
- Check for abort conditions (<PROJECT> unlintable)
- Check for invariant violations
- Generate final report

**Triggers:** Each tick after state updates
**Outputs:** Exit signals (SUCCESS, ABORT, FATAL)

## Data Flow Diagram

```
┌─────────────────┐
│TargetDiscovery  │──────► errors_by_linter
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ActionabilityGate│──────► actionable_targets
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ AgentProcessor  │──────► changed_files, candidate_stalled
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ LinterExecutor  │──────► errors_by_linter (updated)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  StallDetector  │──────► targets_to_submit
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│InvestigationDisp│──────► investigation_futures
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│InvestigationRes │──────► unlintable, changed_files (loop back)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│TerminationCheck │──────► EXIT / LOOP
└─────────────────┘
```

## Pros
- Follows natural flow of data through the system
- Each component has a clear "when" it runs
- Easy to reason about ordering
- Matches the flowchart structure

## Cons
- Components are tightly sequenced (less parallelism opportunity)
- State must be passed between phases
- Some phases are tiny (TerminationChecker)
- Cross-cutting concerns (staleness) span multiple phases

## Open Questions
1. Should ActionabilityGate be merged with StallDetector?
2. How to handle the "external change" path that short-circuits the flow?
3. Is InvestigationResolver better as async callbacks or polled?
