---
description: Handle code review comments with optional worktree support
---

Run the PR review workflow.

## Arguments

- Empty: Local mode - review uncommitted code in current directory
- `--loop`: Local mode with continuous cycles until clean (no outstanding review comments and all automated checks (e.g., tests, linters, CI) pass)
- Ticket ID (e.g., `NES-123`): Worktree mode - work in worktree, pull PR comments
- Text after identifier: Treated as local tasks (both modes)

Examples:
- `/update-pr` - local mode, single cycle
- `/update-pr --loop` - local mode, continuous loop
- `/update-pr NES-123` - worktree mode for ticket
- `/update-pr NES-123 ## Fix the bug...` - worktree mode + local tasks
- `/update-pr --loop ## Add tests...` - local mode + local tasks

## Execution

1. Create workspace:

```bash
mkdir -p .tmp/pr-review
```

2. Run the pr-outer-loop agent:

```bash
uv run python -m scripts.agents pr-outer-loop $ARGUMENTS
```

## Error Handling

When the command fails, invoke workflow-repair to fix the *tooling* (not content):

```bash
uv run python -m scripts.agents workflow-repair '{
  "workflow": "pr-review",
  "step": "pr-outer-loop",
  "state_file": ".tmp/pr-review/state.json",
  "failed_command": "uv run python -m scripts.agents pr-outer-loop ...",
  "exit_code": 1,
  "stdout": "{captured_stdout}",
  "stderr": "{captured_stderr}",
  "workspace": ".tmp/pr-review"
}'
```

**If `status: "repaired"`**: Use `tool_output` as the result, continue
**If `status: "failed"`**: Preserve workspace, output diagnosis, exit
