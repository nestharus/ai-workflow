# Ticket 4: State Management

Implements: [TASK-02](plan.md#task-02--define-state-schemas)

## Implements

- Components: [IAR-01](design-map.md#internal-artifact--boundary-iar-01-session-state), [IAR-02](design-map.md#internal-artifact--boundary-iar-02-cycle-state), [IAR-05](design-map.md#internal-artifact--boundary-iar-05-file-state)
- PRD Rules: STATE-01, STATE-02, STATE-04, INV-04

## Dependencies

- Requires: None

## Files to Create/Modify

| Action | Path |
|--------|------|
| create | `.agents/agents/pr-review-state.md` |

## Acceptance Criteria

- [ ] State schema documented
- [ ] SESSION-STATE fields defined
- [ ] CYCLE-STATE fields defined
- [ ] FILE-STATE fields defined
- [ ] Context JSON format specified

## State Schemas

### SESSION-STATE

```json
{
  "mode": "local | worktree",
  "working_dir": "/path/to/dir",
  "initial_commit": "abc123",
  "commits_made": 0,
  "all_modified_files": [],
  "cycle_summaries": [],
  "loop_start_time": "2025-01-01T00:00:00Z"
}
```

### CYCLE-STATE

```json
{
  "cycle": 1,
  "cycle_start_time": "2025-01-01T00:01:00Z",
  "files": ["path/to/file.py"],
  "tasks_count": 5,
  "status": "in_progress | complete | error"
}
```

### FILE-STATE

```json
{
  "file_path": "path/to/file.py",
  "tasks": [...],
  "changes_made": true,
  "deferred_reply": "Optional reply text"
}
```

## Context Passing

State is passed between agents via the `context` field in SPAWN-AGENT:

```json
{
  "instruction_file": ".agents/agents/pr-inner-cycle.md",
  "context": {
    "session": { ... },
    "cycle": { ... }
  }
}
```
