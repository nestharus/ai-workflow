# Update PR Command

---

description: Handle code review comments with optional worktree support
allowed-tools: Task, Read, Glob, Bash, TodoWrite, TaskOutput

---

Process code review comments: $ARGUMENTS

## Overview

This command processes code review comments using the pr-outer-loop agent.

**Two modes:**
- **Local mode** (no ticket): Reviews uncommitted code or most recent commit
- **Worktree mode** (with ticket): Works in a worktree, pulls PR comments first

## Arguments

- Empty: Local mode - review uncommitted code in current directory
- `--loop`: Local mode with continuous cycles until clean
- Ticket ID (e.g., `NES-123`): Worktree mode - work in worktree, pull PR comments
- Text after identifier: Treated as local tasks (both modes)

Examples:
- `/update-pr` - local mode, single cycle
- `/update-pr --loop` - local mode, continuous loop
- `/update-pr NES-123` - worktree mode for ticket
- `/update-pr NES-123 ## Fix the bug...` - worktree mode + local tasks
- `/update-pr --loop ## Add tests...` - local mode + local tasks

## CRITICAL: Synchronization Rules

**The agent command MUST complete before proceeding.**

- If the bash command goes to background, call `TaskOutput(task_id=<id>, block=true, timeout=600000)` to wait
- If TaskOutput times out but task is still running, call TaskOutput again (task continues in background)
- Repeat until status shows completed/failed

## Execution

### Step 1: Create Workspace

```bash
rm -rf .tmp/pr-review && mkdir -p .tmp/pr-review
```

### Step 2: Run PR Outer Loop Agent

```bash
uv run python -m scripts.agents pr-outer-loop '$ARGUMENTS'
```

Pass through all arguments exactly as provided (quoted as a single string).

**WAIT**: If this goes to background, call TaskOutput and wait until status is completed/failed.

### Step 3: Check Completion

**Check pr-outer-loop result:**
- If output contains "no tasks found" or "0 tasks": All tasks were evaluated and deemed non-actionable. Workflow is complete.
- If tasks were handled: Workflow is complete.
- If error occurred: Go to Error Handling.

Output summary and clean up:
```bash
rm -rf .tmp/pr-review
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

## Rules

- No AI co-authors (see AGENTS.md)
- Never defer - implement or challenge
- Always squash commits before pushing
- Always push at the end
- Post deferred replies only in worktree mode
