# Update PR Command

---

description: Handle code review comments with optional worktree support
allowed-tools: Task, Read, Glob, Bash, TodoWrite, TaskOutput

---

Process code review comments: $ARGUMENTS

## Overview

This command processes code review comments using the review-loop Python script.

**Two modes:**
- **Local mode** (no ticket/worktree): Reviews uncommitted code or most recent commit in current directory
- **Worktree mode** (with ticket or worktree): Works in a worktree, pulls PR comments first

## Arguments

- Empty: Local mode - review uncommitted code in current directory
- `--ticket <id>`: Worktree mode - work in worktree for Linear ticket, pull PR comments
- `--worktree <path>`: Worktree mode - work in specified worktree (no ticket)
- `--tasks-file <path>`: Load tasks from file (tasks separated by --- or review.txt format)
- Text after flags: Treated as local tasks (use --- to separate multiple)

Examples:
- `/update-pr` - local mode, review current directory
- `/update-pr --ticket NES-123` - worktree mode for ticket
- `/update-pr --ticket NES-123 fix the bug` - worktree mode + local task
- `/update-pr --worktree .worktrees/my-branch` - worktree mode without ticket
- `/update-pr --tasks-file .tmp/tasks.txt` - local mode with tasks from file
- `/update-pr fix typo --- add docstring` - local mode with multiple local tasks

## CRITICAL: Synchronization Rules

**The command MUST complete before proceeding.**

- If the bash command goes to background, call `TaskOutput(task_id=<id>, block=true, timeout=600000)` to wait
- If TaskOutput times out but task is still running, call TaskOutput again (task continues in background)
- Repeat until status shows completed/failed

## Worktree Rules

When `--ticket` or `--worktree` is present:
1. Commands run from repo root (scripts/agents live there)
2. The review-loop script handles worktree setup internally
3. Workspace is created INSIDE the worktree (`{worktree}/.tmp/pr-review/`)
4. All file operations target the worktree
5. Git operations happen in the worktree
6. Cleanup is handled by the Python script

## Execution

### Step 0: Normalize Input

Before passing to the Python script, YOU (Claude) must check if `$ARGUMENTS` matches the expected format and rewrite if necessary.

**Expected formats the Python script understands:**
- Empty (no arguments)
- Starts with `--ticket`, `--worktree`, or `--tasks-file` flag
- Clean local task text (concise descriptions, `---` separators between multiple tasks)

**If input is freeform/unstructured (e.g., issue descriptions, review comments, multi-paragraph text):**

YOU must rewrite the input into actionable task text before calling the script:

1. **Extract the core task(s)** from the freeform input
2. **Rewrite each task** as a clear, actionable instruction
3. **Separate multiple tasks** with `---` on its own line
4. **Preserve `folder: "..."` prefix** if present (indicates which files to target)

**Examples:**

Input:
```
folder: ".tasks/plans/foo"

### 2.9 Issue Title
**Location**: Section 6.4
**Issue**: Something is unclear
**Recommendation**: Clarify X, Y, Z
```

Rewritten:
```
folder: ".tasks/plans/foo"

Clarify X, Y, Z in section 6.4. The issue is that something is unclear. Add explicit rules for X, Y, and Z.
```

Input:
```
The validation doesn't handle edge cases properly. See lines 42-50 in validator.py.
Also the error messages are confusing.
```

Rewritten:
```
Fix validation edge case handling in validator.py lines 42-50
---
Improve error messages in validator.py to be clearer
```

**Key principle:** The Python script expects task text it can act on directly. Verbose issue descriptions, recommendations, and context must be distilled into clear instructions.

### Step 1: Run PR Review Loop

```bash
uv run pr review-loop $ARGUMENTS
```

Pass through normalized arguments. The Python script handles:
- Mode detection (local vs worktree)
- Worktree setup (if --ticket provided)
- Workspace creation in correct location
- Task importing and processing
- Cleanup on completion

**WAIT**: If this goes to background, call TaskOutput and wait until status is completed/failed.

### Step 2: Check Completion

**Check review-loop result:**
- If output contains "no tasks found" or "0 tasks": All tasks were evaluated and deemed non-actionable. Workflow is complete.
- If tasks were handled: Workflow is complete.
- If error occurred: Go to Error Handling.

## Error Handling

When the command fails, invoke workflow-repair to fix the *tooling* (not content):

```bash
uv run agents workflow-repair '{
  "workflow": "pr-review",
  "step": "review-loop",
  "state_file": ".tmp/pr-review/state/session.json",
  "failed_command": "uv run pr review-loop ...",
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
