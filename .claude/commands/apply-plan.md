---
description: Apply Traycer AI implementation plans by orchestrating sub-agents
argument-hint: [--tasks-dir .tasks/store/<timestamp>]
allowed-tools: Bash
---

Run the apply-plan orchestrator using the MCP client (use `timeout: 600000`):

```bash
uv run agent.mcp wait --command "python scripts/tasks/workflows/apply_plan.py $ARGUMENTS" --max-seconds 600
```

The `agent.mcp wait` command handles all polling internally and returns a final status.
No re-running is required in the normal case.

Handle each status:
- `"status": "completed"` → Process finished, check `exit_code`, `stdout`, `stderr`
- `"status": "failed"` → Check `error` field and `stderr` for details
- `"status": "timeout"` → Job exceeded time limit. Options:
  1. Increase `--max-seconds` and re-run if more time is needed
  2. Check agent logs for stuck processes
  3. Manually intervene if the task is inherently too long
- `"status": "killed"` → Job was externally terminated
