# Ticket 5: File Handler Agent

Implements: [TASK-03](plan.md#task-03--implement-file-handler-agent)

## Implements

- Component: [COM-03](design-map.md#component-com-03-file-handler)
- Algorithms: ALG-FILE-01, ALG-FILE-02, ALG-FILE-03
- Contracts: [CON-09](design-map.md#contract-con-09-file-isolation)
- PRD Rules: INV-02, ROUTE-06, ROUTE-07

## Dependencies

- Requires: [TASK-01](plan.md#task-01--configure-complexity-router-models), [TASK-02](plan.md#task-02--define-state-schemas)

## Files to Create/Modify

| Action | Path |
|--------|------|
| create | `.agents/agents/pr-file-handler.md` |

## Acceptance Criteria

- [ ] Agent instruction file created
- [ ] Reads tasks from context JSON
- [ ] Modifies ONLY the assigned file (per [INV-02](requirements.md#inv-02))
- [ ] Uses routed model (Minimax or Codex per [ROUTE-06/07](requirements.md#route-06))
- [ ] Returns result with status and changes
- [ ] Writes deferred reply if PR thread exists

## Model Selection

Per [ROUTE-06](requirements.md#route-06) and [ROUTE-07](requirements.md#route-07):

1. INNER-CYCLE calls COMPLEXITY-ROUTER with task text
2. Router returns `minimax` or `codex-medium`
3. FILE-HANDLER spawned with appropriate model

## Input Context

```json
{
  "file_path": "path/to/file.py",
  "tasks": [
    {
      "id": "thread_123",
      "type": "pr_comment | coderabbit",
      "content": "The review comment text...",
      "line": 42
    }
  ],
  "model": "minimax | codex-medium"
}
```

## Output Result

```json
{
  "file_path": "path/to/file.py",
  "status": "success | error",
  "changes_made": true,
  "deferred_reply": "Response to post on PR thread"
}
```
