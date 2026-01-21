---
description: Handle code review comments with optional worktree support
agent: pr-orchestrator
subtask: true
---

Run the PR review workflow agent.

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

## Workflow

Run the pr-outer-loop agent with the provided arguments:

```bash
uv run python -m scripts.agents pr-outer-loop "$ARGUMENTS"
```

Pass through all arguments exactly as provided.
