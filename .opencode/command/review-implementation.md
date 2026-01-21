---
description: Review implementation against a plan with state tracking and auto-repair
agent: implementation-review-orchestrator
subtask: true
---

Review an implementation against its plan with automatic failure recovery.

## Arguments

```
/review-implementation path/to/plan.md
```

## What It Does

1. **Build Scope**: Analyzes git history, classifies files, writes shape
2. **Review**: GPT 5.2 XHigh reviews implementation, writes issues to file
3. **Fix**: PR agent reads issues from file, makes fixes
4. **Update Scope**: Incremental update (new commits only)
5. **Re-review**: Verifies fixes, marks resolved, finds new issues
6. **Iterate**: Until clean or 3 cycles

## Auto-Repair

When any step fails, `workflow-repair` (Claude Opus) fixes *bugs* in the tooling:

**Fixes bugs in:**
- Python scripts (`scripts/agents/`, `scripts/pr/`)
- Agent definitions (`.agents/agents/*.md`)
- JSON serialization logic
- CLI argument construction

**Does NOT make manual edits:**
- Won't manually create directories (fixes the code that should create them)
- Won't manually edit state files (fixes the code that writes them)
- Won't touch source code or content being processed

Flow:
1. Command fails → orchestrator captures stdout/stderr/exit_code
2. Invokes workflow-repair with failed command details
3. Workflow-repair investigates, fixes the bug, re-runs, QAs
4. Returns `tool_output` → orchestrator continues

## State Tracking

All state lives in `.tmp/implementation-review/`:
- `state.json` - Current step, history, errors
- `scope.json` - File classifications (shape)
- `review.txt` - Issues in pr-outer-loop format

State enables:
- Resume from failures
- Workflow-repair to understand context
- Debugging on unrecoverable failures

## File Flow

```
scope-agent → scope.json
                  ↓
reviewer → review.txt
                  ↓
pr-outer-loop --tasks-file review.txt
                  ↓
scope-agent → updates scope.json
                  ↓
reviewer → updates review.txt
                  ↓
[failure at any step?]
                  ↓
workflow-repair → investigates, fixes, re-runs, QAs
                  ↓
orchestrator continues
```

## Examples

```bash
/review-implementation docs/plans/feature-x.md
/review-implementation .tasks/plans/agent/plan.md
```

## Output

- **CLEAN**: All issues resolved, workspace deleted
- **ISSUES REMAIN**: After 3 iterations, workspace preserved
- **FAILED**: Unrecoverable error, workspace preserved with diagnosis
