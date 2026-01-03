# Candidate 4: Event-Driven / Message-Passing Split

## Philosophy
Replace the tightly-coupled state machine with **loosely-coupled components** that communicate via **events/messages**. Each component reacts to events and emits new events, with minimal direct state sharing.

## Core Insight
The algorithm's complexity comes from:
1. Many places updating the same state (errors_by_linter, passed_linters, etc.)
2. Complex conditionals checking multiple state sources
3. "Refresh" and "external change" paths that jump across subgraphs

An event-driven approach can:
- Decouple state updates from decision logic
- Make the control flow explicit as event handlers
- Allow components to subscribe to only relevant events

## Event Types

```
# Initial/Discovery Events
InitializationComplete(errors_by_linter)
LinterOutputReceived(linter, diagnostics)

# Change Events
FilesChanged(files, source: Agent|External)
ProjectConfigChanged(source: Agent|External)
ExternalChangeDetected(files, project_changed)

# Investigation Events
InvestigationRequested(target, payload)
InvestigationDispatched(target, start_snapshot)
InvestigationCompleted(target, result: Modified|NoOp|Failure)
InvestigationDiscarded(target, reason: Stale)

# Target Status Events
TargetMarkedUnlintable(target, reason)
TargetReactivated(target)  # when external change clears unlintable
LinterPassed(target, linter)
LinterPassedCleared(targets, linter)

# Linter Staleness Events
LinterMarkedStale(linter, blocked_by)
LinterUnblocked(linter)
LinterRefreshRequested(linter)
LinterRefreshCompleted(linter)

# Agent Events
AgentInvoked(files, errors)
AgentCompleted(changed_files, output)
AgentWriteRejected(reason: CasFailed)

# Termination Events
SuccessConditionMet()
AbortConditionMet(reason)
InvariantViolation(context)
```

## Components as Event Handlers

### 1. EventBus (Infrastructure)
Central message broker. Components subscribe to event types and publish events.

```python
class EventBus:
    def subscribe(event_type, handler)
    def publish(event)
    def publish_many(events)
```

### 2. ErrorStore (Stateful)
**Subscribes to:** `LinterOutputReceived`, `FilesChanged`, `TargetMarkedUnlintable`
**Publishes:** (none - pure data store, queried on demand)

Stores `errors_by_linter`. Updates on lint output, clears for changed/unlintable files.

### 3. TargetStatusStore (Stateful)
**Subscribes to:** `TargetMarkedUnlintable`, `TargetReactivated`, `LinterPassed`, `LinterPassedCleared`
**Publishes:** (none - pure data store)

Stores `unlintable_targets`, `passed_linters`.

### 4. InvestigationCoordinator (Stateful + Active)
**Subscribes to:** `InvestigationRequested`, `FilesChanged`, `ExternalChangeDetected`
**Publishes:** `InvestigationDispatched`, `InvestigationCompleted`, `InvestigationDiscarded`, `LinterUnblocked`

Manages `investigation_futures`, `pending_investigation_targets`. Handles dispatch and completion polling.

### 5. StalenessManager (Stateful)
**Subscribes to:** `InvestigationDispatched`, `InvestigationCompleted`, `LinterRefreshCompleted`
**Publishes:** `LinterMarkedStale`, `LinterUnblocked`, `LinterRefreshRequested`

Manages `stale_linters`. Updates blocked_by, handles refresh gating.

### 6. ChangeDetector (Stateful + Active)
**Subscribes to:** `AgentCompleted`, (external file watcher)
**Publishes:** `FilesChanged`, `ProjectConfigChanged`, `ExternalChangeDetected`

Manages `seen_hashes`. Detects changes via hash comparison.

### 7. StallMonitor (Stateful)
**Subscribes to:** `AgentCompleted`, `LinterOutputReceived`
**Publishes:** `InvestigationRequested`

Manages `candidate_stalled_*`. Confirms stalls after lint, requests investigations.

### 8. AgentRunner (Active)
**Subscribes to:** (triggered by orchestrator)
**Publishes:** `AgentInvoked`, `AgentCompleted`, `AgentWriteRejected`

Invokes lint-fixer agent with CAS protection.

### 9. LinterRunner (Active)
**Subscribes to:** (triggered by orchestrator)
**Publishes:** `LinterOutputReceived`

Runs linters with appropriate scope and file sets.

### 10. Orchestrator (Coordinator)
**Subscribes to:** All events
**Publishes:** Termination events

Coordinates the overall flow. Decides when to run agent, which files to lint, when to check termination.

## Event Flow Example: Normal Tick

```
1. Orchestrator triggers AgentRunner
2. AgentRunner publishes AgentInvoked(files, errors)
3. AgentRunner publishes AgentCompleted(changed_files, output)
4. ChangeDetector receives AgentCompleted, updates seen_hashes
5. ChangeDetector publishes FilesChanged(files, source=Agent)
6. ErrorStore receives FilesChanged, clears diagnostics for changed files
7. TargetStatusStore receives FilesChanged via LinterPassedCleared
8. Orchestrator triggers LinterRunner for each linter
9. LinterRunner publishes LinterOutputReceived(linter, diagnostics)
10. ErrorStore receives and stores diagnostics
11. StallMonitor receives, compares to candidate_stalled, confirms stalls
12. StallMonitor publishes InvestigationRequested(target, payload)
13. InvestigationCoordinator reserves and dispatches
14. InvestigationCoordinator publishes InvestigationDispatched
15. StalenessManager receives, updates blocked_by
16. Orchestrator checks termination conditions
```

## Pros
- Loose coupling through events
- Easy to add new handlers without changing existing code
- Natural logging/debugging (log all events)
- Components are small and focused
- Easy to test (publish event, verify response)

## Cons
- More indirection (harder to trace full flow)
- Event ordering can be tricky
- Orchestrator may still be complex
- Need to ensure events are processed in correct order
- Potential for event storms (one event triggers many)

## Open Questions
1. Should EventBus be synchronous or async?
2. How to handle event ordering dependencies?
3. Should some state be shared or all via events?
4. How to avoid the "callback hell" problem?
