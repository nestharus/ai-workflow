# Candidate 5: Layered Architecture Split

## Philosophy
Split by **abstraction levels**. Lower layers provide stable primitives; higher layers compose them into complex behaviors. Changes should flow downward (implementations) not upward (interfaces).

## Layer Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    APPLICATION LAYER                     │
│   Orchestrator (main loop, termination, coordination)   │
└─────────────────────────────────────────────────────────┘
                           │ uses
                           ▼
┌─────────────────────────────────────────────────────────┐
│                     WORKFLOW LAYER                       │
│   AgentWorkflow | InvestigationWorkflow | LintWorkflow  │
└─────────────────────────────────────────────────────────┘
                           │ uses
                           ▼
┌─────────────────────────────────────────────────────────┐
│                     POLICY LAYER                         │
│  ActionabilityPolicy | StalenessPolicy | StallPolicy    │
└─────────────────────────────────────────────────────────┘
                           │ uses
                           ▼
┌─────────────────────────────────────────────────────────┐
│                      STATE LAYER                         │
│   ErrorState | TargetState | HashState | LockState      │
└─────────────────────────────────────────────────────────┘
                           │ uses
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   INFRASTRUCTURE LAYER                   │
│     Linters | FileSystem | Agent | AsyncExecutor        │
└─────────────────────────────────────────────────────────┘
```

## Layer Descriptions

### Infrastructure Layer (Bottom)
**Stability:** Very High (changes rarely)
**Purpose:** External system integration

**Components:**
- **Linters**: Execute linter binaries, parse output
- **FileSystem**: Read/write files, hash computation, file watching
- **Agent**: Invoke lint-fixer agent, capture output
- **AsyncExecutor**: Manage async investigation tasks

**Coupling Rule:** No dependencies on upper layers. Pure utilities.

### State Layer
**Stability:** High (data structures stable, operations change)
**Purpose:** Store and query algorithm state

**Components:**
- **ErrorState**: Store `errors_by_linter`, query by filters
- **TargetState**: Store `unlintable_targets`, `passed_linters`
- **HashState**: Store `seen_hashes`, `changed_files`, `project_changed`
- **LockState**: Store `investigation_futures`, `pending_investigation_targets`

**Coupling Rule:** Depends only on Infrastructure. Provides query interfaces.

### Policy Layer
**Stability:** Medium (business rules change over time)
**Purpose:** Encode decision logic without execution

**Components:**
- **ActionabilityPolicy**: Given current state, which targets are actionable?
  ```python
  def get_actionable(error_state, lock_state, target_state, staleness_state) -> ActionableSet
  ```

- **StalenessPolicy**: When is a linter stale? When can it refresh?
  ```python
  def should_mark_stale(linter, locked_targets) -> bool
  def can_refresh(linter, blocked_by) -> bool
  def needs_refresh(stale_linters) -> Set[Linter]
  ```

- **StallPolicy**: When is a target stalled? When to defer vs submit?
  ```python
  def is_stalled(target, changed_files, verified_errors) -> bool
  def should_defer(target, required_linter, stale_linters) -> bool
  def should_submit(pending, stale_empty) -> bool
  ```

**Coupling Rule:** Depends on State Layer for queries. Returns decisions, not actions.

### Workflow Layer
**Stability:** Low-Medium (orchestration logic changes)
**Purpose:** Execute multi-step workflows using policies and state

**Components:**
- **AgentWorkflow**: Prepare input → Snapshot → Invoke → Detect changes → Update state
  ```python
  def run(actionable_files, errors) -> WorkflowResult:
      input = prepare_input(actionable_files, errors)
      snapshot = hash_state.snapshot(actionable_files)
      result = agent.invoke(input)
      changes = detect_changes(snapshot)
      update_state(changes)
      return WorkflowResult(changes, candidate_stalled)
  ```

- **InvestigationWorkflow**: Poll → Validate staleness → Apply result → Update state
  ```python
  def poll_and_process() -> List[ProcessedResult]:
      completed = async_executor.poll()
      for result in completed:
          if not validate_staleness(result):
              handle_stale(result)
          else:
              apply_result(result)
  ```

- **LintWorkflow**: Determine scope → Run linter → Update errors → Track passed
  ```python
  def run_all_linters(changed_files, project_changed, locked) -> None:
      for linter in configured_linters:
          if staleness_policy.should_skip(linter, locked):
              staleness_state.mark_stale(linter, locked)
          else:
              files = determine_files(linter, changed_files, project_changed)
              diagnostics = linters.run(linter, files)
              error_state.update(linter, diagnostics)
              target_state.record_passed(files - get_error_files(diagnostics))
  ```

**Coupling Rule:** Depends on Policy and State. Orchestrates but doesn't decide.

### Application Layer (Top)
**Stability:** Low (most volatile, changes frequently)
**Purpose:** Main loop, termination, high-level coordination

**Components:**
- **Orchestrator**: The main loop
  ```python
  def run():
      init()
      while not termination_policy.should_exit(state):
          if investigation_workflow.has_completed():
              investigation_workflow.poll_and_process()

          actionable = actionability_policy.get_actionable(state)
          if actionable.is_empty():
              wait_or_terminate()
              continue

          agent_result = agent_workflow.run(actionable)
          lint_workflow.run_all_linters(agent_result.changes)
          stall_workflow.detect_and_dispatch()

      cleanup()
  ```

**Coupling Rule:** Depends on Workflow Layer. Minimal logic, mostly sequencing.

## Benefits of Layering

1. **Testability**: Lower layers tested in isolation; upper layers mock lower
2. **Changeability**: Policy changes don't affect State; Workflow changes don't affect Policy
3. **Readability**: Each layer has a clear purpose
4. **Debugging**: Start from State (is data correct?), then Policy (are decisions correct?), then Workflow (is execution correct?)

## Mapping Algorithm Subgraphs to Layers

| Subgraph | Layer(s) |
|----------|----------|
| Init | Application (sequencing), State (initialization) |
| InvCheck | Workflow (InvestigationWorkflow) |
| ErrorCheck | Policy (ActionabilityPolicy, TerminationPolicy) |
| AgentPhase | Workflow (AgentWorkflow), Infrastructure (Agent) |
| ProcessLinters | Workflow (LintWorkflow), Policy (StalenessPolicy) |
| UpdateState | State Layer (pure state mutations) |
| Cleanup | Application |

## Pros
- Clear abstraction levels
- Stable lower layers reduce churn
- Easy to understand each layer's role
- Natural test boundaries

## Cons
- May introduce indirection overhead
- Policy layer can become "anemic" (just passes through)
- Some cross-cutting concerns don't fit layers well (e.g., `<PROJECT>` handling)
- Risk of over-layering for smaller problems

## Open Questions
1. Where does `<PROJECT>` pseudo-target handling live? (Spread across layers?)
2. Should TerminationPolicy be separate from the Orchestrator?
3. How to handle the "refresh-only tick" path that skips AgentWorkflow?
