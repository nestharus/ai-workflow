# Ticket 9: Outer Loop Agent

Implements: [TASK-07](plan.md#task-07--implement-outer-loop-orchestrator)

## Implements

- Component: [COM-01](design-map.md#component-com-01-outer-loop)
- Algorithms: ALG-OUTER-ROOT, ALG-OUTER-00, ALG-OUTER-01, ALG-OUTER-02, ALG-OUTER-03, ALG-OUTER-04, ALG-LOCAL-01
- Contracts: [CON-01](design-map.md#contract-con-01-spawn-cycle), [CON-04](design-map.md#component-com-01-outer-loop), [CON-08](design-map.md#component-com-01-outer-loop)
- PRD Rules: INV-03, INV-05, INV-06, INV-09, MODE-01, MODE-02, CYCLE-01, CYCLE-02, FIN-01..FIN-07

## Dependencies

- Requires:
  - [TASK-05](plan.md#task-05--implement-lint-fixer-agent) (LINT-FIXER)
  - [TASK-06](plan.md#task-06--implement-inner-cycle-orchestrator) (INNER-CYCLE)

## Files to Create/Modify

| Action | Path |
|--------|------|
| create | `.agents/agents/pr-outer-loop.md` |

## Acceptance Criteria

- [ ] Agent instruction file created
- [ ] Uses GPT 5.2 None model (per [ROUTE-03](requirements.md#route-03))
- [ ] Detects mode from arguments (per [MODE-01/02/03](requirements.md#mode-01))
- [ ] Sets up worktree if ticket ID provided
- [ ] Initializes SESSION-STATE
- [ ] Loops up to 10 cycles (per [CYCLE-01](requirements.md#cycle-01))
- [ ] Exits when clean (per [CYCLE-02](requirements.md#cycle-02))
- [ ] Finalizes: lint, squash, push (per [FIN-01/02/03/04](requirements.md#fin-01))
- [ ] Posts deferred replies (per [FIN-05](requirements.md#fin-05))

## Mode Detection

Per [MODE-03](requirements.md#mode-03):

```python
import re
ticket_pattern = r'^[A-Z]+-\d+$'
if re.match(ticket_pattern, first_arg):
    mode = "worktree"
else:
    mode = "local"
```

## Cycle Loop

```python
while cycle <= MAX_CYCLES:
    result = spawn_inner_cycle(session, cycle)

    if result.status == "clean":
        break  # No more tasks
    elif result.status == "error":
        log_error(result.error)
        break
    else:
        # tasks_handled - continue
        session.all_modified_files.update(result.files)
        session.cycle_summaries.append(summarize(result))
        cycle += 1
```

## Finalization Sequence

Per [FIN-01](requirements.md#fin-01) through [FIN-05](requirements.md#fin-05):

1. Spawn LINT-FIXER for each file in `all_modified_files` (parallel)
2. Commit lint fixes if any
3. Squash if `commits_made > 1`
4. Push to origin
5. Post deferred replies (worktree mode only)

## Input Context

```json
{
  "arguments": "NES-123 --loop",
  "working_dir": "/path/to/repo"
}
```

## Output

Final summary printed to console:
- Mode, branch, PR number
- Cycles completed
- Files modified
- Changes summary
- Local task responses (if any)
