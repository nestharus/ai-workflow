# Candidate 1: State-Centric Split

## Philosophy
Isolate components by the **state they own and mutate**. Each component has exclusive ownership of specific state variables and exposes a clean API for queries and mutations.

## Identified Components

### 1. ErrorRegistry
**Owns:** `errors_by_linter`, `new_errors`
**Responsibilities:**
- Store and retrieve errors by linter and target
- Filter errors (exclude stale linters, exclude unlintable)
- Extract targets from errors
- Clear/update diagnostics for specific targets

**API Surface:**
```
get_actionable_errors(exclude_linters, exclude_targets) -> ErrorsByLinter
get_error_targets(exclude_stale=True) -> Set[Target]
update_linter_diagnostics(linter, diagnostics, preserve_targets)
clear_target_diagnostics(target)
has_errors() -> bool
```

### 2. TargetTracker
**Owns:** `unlintable_targets`, `passed_linters`
**Responsibilities:**
- Track which targets are unlintable (with reasons)
- Track which linters each target has passed
- Clear passed state on changes

**API Surface:**
```
mark_unlintable(target, reason)
is_unlintable(target) -> bool
get_unlintable_targets() -> Dict[Target, Reason]
record_passed(target, linter)
clear_passed(targets)
clear_all_passed()
get_passed_linters(target) -> Set[Linter]
```

### 3. InvestigationManager
**Owns:** `investigation_futures`, `pending_investigation_targets`
**Responsibilities:**
- Reserve targets for investigation (prevent concurrent edits)
- Track pending investigations with their snapshots
- Dispatch investigations asynchronously
- Poll for completed investigations

**API Surface:**
```
reserve(targets, start_hashes)
dispatch(targets, payloads)
get_locked_targets() -> Set[Target]
get_pending_targets() -> Set[Target]
poll_completed() -> List[InvestigationResult]
is_blocking_target(target) -> bool
defer_target(target, error_snapshot, agent_snapshot)
submit_deferred(targets)
```

### 4. StalenessTracker
**Owns:** `stale_linters`, (influences) `seen_hashes`
**Responsibilities:**
- Track which linters are stale/suspended and why
- Manage blocked_by sets for stale linters
- Handle refresh gating (PENDING_REFRESH state)

**API Surface:**
```
mark_stale(linter, blocked_by)
update_blocked_by(target_completed)
get_pending_refresh_linters() -> Set[Linter]
is_stale(linter) -> bool
clear_staleness(linter)
get_stale_linters() -> Dict[Linter, StaleState]
```

### 5. ChangeDetector
**Owns:** `seen_hashes`, `changed_files`, `project_changed`
**Responsibilities:**
- Snapshot file hashes and project fingerprint
- Detect changes via diff
- CAS protection (verify unchanged before write)
- Track seen hashes within processing window

**API Surface:**
```
snapshot(files) -> Snapshot
diff(before, after) -> (changed_files, project_changed)
has_hash_changed(target) -> bool
verify_unchanged(snapshot) -> bool
record_seen_hash(target, hash)
clear_seen_hashes(targets)
get_project_fingerprint() -> Fingerprint
```

### 6. AgentCoordinator
**Owns:** `candidate_stalled_files`, `candidate_stalled_targets`
**Responsibilities:**
- Prepare agent input (files + errors + context)
- Invoke lint-fixer agent with CAS protection
- Capture agent output for investigator context
- Determine candidate stalled targets after agent run

**API Surface:**
```
prepare_input(actionable_files, actionable_targets, errors) -> AgentInput
invoke(input, snapshot) -> (output, success)
get_candidate_stalled() -> (files, targets)
clear_candidate_stalled()
```

## Component Interaction Diagram

```
                    ┌─────────────────┐
                    │  Main Loop      │
                    │  (Orchestrator) │
                    └────────┬────────┘
                             │
      ┌──────────────────────┼──────────────────────┐
      │                      │                      │
      ▼                      ▼                      ▼
┌───────────┐        ┌──────────────┐       ┌────────────┐
│ ErrorReg  │◄──────►│ TargetTracker│◄─────►│ Staleness  │
└───────────┘        └──────────────┘       │ Tracker    │
      ▲                      ▲              └────────────┘
      │                      │                     ▲
      │              ┌───────┴───────┐             │
      │              │               │             │
      ▼              ▼               ▼             │
┌───────────┐  ┌───────────┐  ┌─────────────┐     │
│ Agent     │  │ Change    │  │Investigation│◄────┘
│Coordinator│◄►│ Detector  │◄►│  Manager    │
└───────────┘  └───────────┘  └─────────────┘
```

## Pros
- Clear ownership boundaries
- Each component has a focused responsibility
- State mutations are encapsulated
- Easy to test components in isolation

## Cons
- High coupling through queries (everyone reads ErrorRegistry)
- Main loop still orchestrates all interactions
- "God object" risk in orchestrator
- Some state naturally crosses boundaries (e.g., `seen_hashes` affects both ChangeDetector and InvestigationManager)

## Open Questions
1. Should ErrorRegistry own target extraction or delegate to TargetTracker?
2. How should the orchestrator coordinate between InvestigationManager and StalenessTracker on completion?
3. Is ChangeDetector responsible for the "external change" detection or should that be separate?
