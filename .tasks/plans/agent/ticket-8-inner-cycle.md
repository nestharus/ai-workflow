# Ticket 8: Inner Cycle Agent

Implements: [TASK-06](plan.md#task-06--implement-inner-cycle-orchestrator)

## Implements

- Component: [COM-02](design-map.md#component-com-02-inner-cycle)
- Algorithms: ALG-INNER-ROOT, ALG-INNER-00, ALG-INNER-01, ALG-INNER-02, ALG-INNER-03, ALG-INNER-04, ALG-INNER-05, ALG-INNER-06
- Contracts: [CON-01](design-map.md#contract-con-01-spawn-cycle)
- PRD Rules: INV-05, INV-09, CYCLE-03, CYCLE-05, CYCLE-06, PAR-01, PAR-02

## Dependencies

- Requires:
  - [TASK-03](plan.md#task-03--implement-file-handler-agent) (FILE-HANDLER)
  - [TASK-04](plan.md#task-04--implement-test-fixer-agent) (TEST-FIXER)

## Files to Create/Modify

| Action | Path |
|--------|------|
| create | `.agents/agents/pr-inner-cycle.md` |

## Acceptance Criteria

- [ ] Agent instruction file created
- [ ] Uses GPT 5.2 Medium model (per [ROUTE-04](requirements.md#route-04))
- [ ] Runs CodeRabbit review synchronously (per [ALG-CR-02](requirements.md#alg-cr-02-execute-coderabbit-review-synchronous))
- [ ] Parses review with `uv run pr parse-coderabbit`
- [ ] Aggregates tasks with `uv run pr aggregate-tasks`
- [ ] Routes each task via COMPLEXITY-ROUTER
- [ ] Spawns FILE-HANDLER per file (parallel per [PAR-01](requirements.md#par-01))
- [ ] Spawns TEST-FIXER per .py file (parallel per [PAR-02](requirements.md#par-02))
- [ ] Commits changes if any exist
- [ ] Returns cycle result per [CYCLE-COMPLETION](plan.md#contract-cycle-completion)

## Cycle Sequence

Per [CYCLE-03](requirements.md#cycle-03):

```
review → parse → handle → test → commit
```

1. **Review**: Spawn CODERABBIT-RUNNER and wait synchronously for completion
2. **Parse**: `uv run pr parse-coderabbit` + `aggregate-tasks`
3. **Handle**: For each file, route → spawn FILE-HANDLER
4. **Test**: For each .py file, spawn TEST-FIXER
5. **Commit**: `git add -A && git commit -m "..."`

## Input Context

```json
{
  "session": {
    "mode": "local",
    "working_dir": "/path/to/repo",
    "initial_commit": "abc123"
  },
  "cycle": {
    "cycle": 1,
    "cycle_start_time": "2025-01-01T00:01:00Z"
  },
  "review_target": "--type uncommitted | --base-commit HEAD~1 | --base main"
}
```

## Output Result

```json
{
  "status": "clean | tasks_handled | error",
  "files": ["path/to/file1.py", "path/to/file2.py"],
  "tasks_processed": 5,
  "tests_passed": true,
  "committed": true,
  "error": null
}
```
