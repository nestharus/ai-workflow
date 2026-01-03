# Candidate 3: Responsibility-Based Split (Domain-Driven)

## Philosophy
Split by **domain concerns** and **reasons for change**. Each component handles a distinct problem domain and can evolve independently.

## Identified Domains

### 1. Concurrency Control
**Problem:** Preventing concurrent modifications to the same target
**Owns:** `investigation_futures` (as locks), reservation logic

**Responsibilities:**
- Reserve targets before dispatching investigations
- Prevent agent from touching locked targets
- Release locks on investigation completion
- Query lock status

**Interface:**
```python
class ConcurrencyControl:
    def acquire(target: Target, snapshot: Snapshot) -> bool
    def release(target: Target) -> None
    def is_locked(target: Target) -> bool
    def get_locked_targets() -> Set[Target]
    def poll_released() -> List[Tuple[Target, InvestigationResult]]
```

**Coupling:** Low - only needs to know about targets and results

### 2. Change Tracking
**Problem:** Detecting when files change (before/after agent, external changes)
**Owns:** `seen_hashes`, hashing logic, fingerprinting

**Responsibilities:**
- Hash files and project configs
- Detect changes between snapshots
- CAS verification (unchanged since snapshot)
- External change detection (file watcher integration)

**Interface:**
```python
class ChangeTracking:
    def snapshot(targets: Set[Target]) -> Snapshot
    def diff(before: Snapshot, after: Snapshot) -> ChangeSet
    def verify_unchanged(snapshot: Snapshot) -> bool
    def record_seen(target: Target, hash: Hash) -> None
    def forget(targets: Set[Target]) -> None
    def get_project_fingerprint() -> Fingerprint
```

**Coupling:** Low - only needs filesystem access

### 3. Diagnostic Store
**Problem:** Managing error/diagnostic data from linters
**Owns:** `errors_by_linter`, diagnostic filtering

**Responsibilities:**
- Store diagnostics by linter and target
- Filter by exclusion criteria (stale, unlintable)
- Extract targets with errors
- Update/clear diagnostics

**Interface:**
```python
class DiagnosticStore:
    def update(linter: Linter, diagnostics: List[Diagnostic], preserve: Set[Target]) -> None
    def clear(target: Target) -> None
    def query(exclude_linters: Set[Linter], exclude_targets: Set[Target]) -> DiagnosticsByLinter
    def get_targets(exclude_stale: bool) -> Set[Target]
    def is_empty() -> bool
```

**Coupling:** Low - pure data storage

### 4. Target Classification
**Problem:** Determining a target's status and actionability
**Owns:** `unlintable_targets`, `passed_linters`

**Responsibilities:**
- Classify targets (actionable, locked, unlintable, pending)
- Track linter pass/fail per target
- Record why targets became unlintable

**Interface:**
```python
class TargetClassification:
    def mark_unlintable(target: Target, reason: Reason) -> None
    def mark_passed(target: Target, linter: Linter) -> None
    def clear_passed(targets: Set[Target]) -> None
    def clear_all_passed() -> None
    def classify(target: Target) -> TargetStatus
    def get_unlintable() -> Dict[Target, Reason]
    def is_project_unlintable() -> bool
```

**Coupling:** Low - classification logic only

### 5. Linter Staleness
**Problem:** Tracking which linters have stale/suspended diagnostics
**Owns:** `stale_linters`, blocked_by tracking, refresh gating

**Responsibilities:**
- Mark linters as stale with blocking reason
- Update blocked_by when investigations complete
- Manage PENDING_REFRESH state
- Determine if linter is actionable

**Interface:**
```python
class LinterStaleness:
    def mark_stale(linter: Linter, blocked_by: Set[Target]) -> None
    def unblock(target: Target) -> Set[Linter]  # returns newly unblocked
    def clear(linter: Linter) -> None
    def needs_refresh() -> Set[Linter]
    def is_stale(linter: Linter) -> bool
    def get_blocking_targets(linter: Linter) -> Set[Target]
```

**Coupling:** Low - only needs linter and target identifiers

### 6. Stall Detection
**Problem:** Detecting when agent couldn't fix errors
**Owns:** `candidate_stalled_files`, `candidate_stalled_targets`, `pending_investigation_targets`

**Responsibilities:**
- Track candidate stalled targets after agent run
- Confirm stalls after post-agent lint
- Defer stalls when blocked by stale linters
- Store snapshots for deferred investigations

**Interface:**
```python
class StallDetection:
    def set_candidates(files: Set[Path], targets: Set[Target]) -> None
    def confirm(verified_errors: Set[Target]) -> Set[Target]  # returns confirmed stalls
    def defer(target: Target, error_snapshot, agent_snapshot) -> None
    def get_pending() -> Dict[Target, Snapshot]
    def submit(targets: Set[Target]) -> Dict[Target, Payload]
    def clear_for(targets: Set[Target]) -> None
```

**Coupling:** Medium - needs to coordinate with LinterStaleness

### 7. Linter Execution
**Problem:** Running linters with correct scope and file sets
**Owns:** Linter configuration, scope rules

**Responsibilities:**
- Determine linter scope (PROJECT vs FILES)
- Build file sets for linting
- Handle blocking file exclusions
- Execute linters and return diagnostics

**Interface:**
```python
class LinterExecution:
    def get_scope(linter: Linter) -> LinterScope
    def get_blocking_files(linter: Linter, locked: Set[Target]) -> Set[Path]
    def can_run(linter: Linter, blocking_files: Set[Path]) -> bool
    def run(linter: Linter, files: Set[Path], exclude: Set[Path]) -> List[Diagnostic]
    def get_project_context_files() -> Set[Path]
```

**Coupling:** Medium - needs filesystem and linter configs

### 8. Agent Coordination
**Problem:** Invoking the lint-fixer agent
**Owns:** Agent invocation, CAS-protected writes

**Responsibilities:**
- Build agent input (files + errors + context)
- Invoke agent with write protection
- Capture agent output for investigator context

**Interface:**
```python
class AgentCoordination:
    def build_input(files: Set[Path], errors: DiagnosticsByLinter, context_files: Set[Path]) -> AgentInput
    def invoke(input: AgentInput, snapshot: Snapshot) -> AgentResult
    def get_last_output() -> AgentOutput  # for investigator context
```

**Coupling:** Medium - needs errors, files, CAS protection

## Dependency Graph

```
                 ┌──────────────────┐
                 │   Orchestrator   │
                 └────────┬─────────┘
                          │ uses all
    ┌─────────────────────┼─────────────────────┐
    │            │        │        │            │
    ▼            ▼        ▼        ▼            ▼
┌────────┐  ┌────────┐  ┌─────┐  ┌─────┐  ┌─────────┐
│Concurr.│  │ Change │  │Diag.│  │Targ.│  │ Linter  │
│Control │  │Tracking│  │Store│  │Class│  │Staleness│
└────────┘  └────────┘  └─────┘  └─────┘  └─────────┘
    │            │                            │
    │            │        ┌───────────────────┤
    │            │        │                   │
    ▼            ▼        ▼                   ▼
┌────────┐  ┌────────┐  ┌─────────────┐  ┌────────┐
│ Stall  │◄─│ Agent  │  │   Linter    │◄─│        │
│Detect. │  │ Coord. │  │  Execution  │  │        │
└────────┘  └────────┘  └─────────────┘  └────────┘
```

## Pros
- Components have clear "reasons for change"
- Low coupling between most components
- Testable in isolation
- Matches how bugs would be categorized ("concurrency bug", "staleness bug", etc.)

## Cons
- More components than other candidates (8 vs 6)
- Some overlap with lifecycle approach
- Orchestrator still complex
- StallDetection has medium coupling

## Open Questions
1. Should DiagnosticStore and TargetClassification merge?
2. Is Linter Staleness a cross-cutting concern that should be aspect-oriented?
3. How should the orchestrator be structured to minimize its complexity?
