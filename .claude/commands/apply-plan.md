---
description: Apply Traycer AI implementation plans by orchestrating sub-agents
argument-hint: [--tasks-dir .tasks/store/<timestamp>]
allowed-tools: Bash
---

Run the apply-plan orchestrator using the polling script (use `timeout: 600000`):

```bash
python scripts/tasks/poll_agents.py --spawn "python scripts/tasks/workflows/apply_plan.py $ARGUMENTS"
```

The script outputs JSON with status. Handle each status:
- `"status": "complete"` → Process finished, check `exit_code`, `stdout`, `stderr`
- `"status": "timeout"` → Re-run the same command to continue polling
- `"status": "output"` → Intermediate output available, re-run to continue
- `"status": "empty"` → No processes to poll

Keep re-running on timeout until status is `complete` or `empty`.
