# Review Implementation Command

---

description: Review implementation against a plan with state tracking and auto-repair
allowed-tools: Task, Read, Glob, Bash, TodoWrite, TaskOutput

---

Review implementation against the following plan: $ARGUMENTS

## Overview

This command reviews an implementation against a plan, identifies issues, and fixes them iteratively.

**Two modes:**
- **Local mode** (no ticket/worktree): Reviews implementation in current directory
- **Worktree mode** (with ticket or worktree): Reviews implementation in a worktree

## Arguments

The first part of arguments may contain flags:
- `--ticket <id>`: Worktree mode - work in worktree for Linear ticket
- `--worktree <path>`: Worktree mode - work in specified worktree

Everything after flags is the plan text.

Examples:
- `/review-implementation <plan text>` - local mode
- `/review-implementation --ticket NES-123 <plan text>` - worktree mode for ticket
- `/review-implementation --worktree .worktrees/my-branch <plan text>` - worktree mode

## CRITICAL: Synchronization Rules

**EVERY agent command MUST complete before proceeding to the next step.**

- If a bash command goes to background, call `TaskOutput(task_id=<id>, block=true, timeout=600000)` to wait
- If TaskOutput times out but task is still running, call TaskOutput again (task continues in background)
- Repeat until status shows completed/failed
- NEVER read output files until the writing agent has completed
- NEVER skip ahead while an agent is still running

## Worktree Rules

When `--ticket` or `--worktree` is present:
1. Commands run from repo root (scripts/agents live there)
2. Workspace is created INSIDE the worktree (`{working_dir}/.tmp/implementation-review/`)
3. All file paths in agent calls use `{working_dir}/...`
4. All agents receive `working_dir` parameter
5. Git operations happen in the worktree
6. The review-loop call passes `--worktree {working_dir}`

## Execution

### Step 0: Parse Arguments and Determine Working Directory

Parse `$ARGUMENTS` to extract flags and plan text:

1. If `--ticket <id>` is present:
   - Extract ticket ID
   - Get branch name: `uv run pr get-expected-branch-name <ticket_id>`
   - Set `working_dir` = `.worktrees/{branch_name}`
   - Ensure worktree exists: `uv run pr setup-worktree <ticket_id>`
   - Remove `--ticket <id>` from arguments, remainder is plan text

2. If `--worktree <path>` is present:
   - Set `working_dir` = `<path>`
   - Verify path exists
   - Remove `--worktree <path>` from arguments, remainder is plan text

3. Otherwise (local mode):
   - Set `working_dir` = `.` (current directory)
   - All of `$ARGUMENTS` is plan text

Define paths:
- `workspace` = `{working_dir}/.tmp/implementation-review`
- `plan_file` = `{workspace}/plan.txt`
- `scope_state_file` = `{workspace}/scope_state.json`
- `conclusions_file` = `{workspace}/conclusions.json`
- `review_file` = `{workspace}/review.txt`
- `state_file` = `{workspace}/state.json`

### Step 1: Setup Workspace

Clean any stale data from previous runs and create fresh workspace:

```bash
rm -rf {workspace} && mkdir -p {workspace}
```

Save the plan text to a file:

```bash
cat > {plan_file} << 'EOF'
{plan_text}
EOF
```

### Step 2: Run Scope Agent (ONCE)

Analyze the plan to find the starting commit:

```bash
uv run python -m scripts.agents implementation-scope '{"plan_file": "{plan_file}", "working_dir": "{working_dir}"}'
```

**WAIT**: If this goes to background, call TaskOutput and wait until status is completed/failed.

Parse the output to extract `start_commit`. Save to state file:

```bash
# Extract start_commit from agent output and save to state
echo '{"start_commit": "{start_commit}", "iteration": 0}' > {state_file}
```

**NOTE**: The scope agent only runs ONCE per review session. It finds the commit boundary.

### Step 3: Discover Scope Files

Use Python to discover files changed since start_commit:

```bash
uv run pr discover-scope-files --working-dir {working_dir} --start-commit {start_commit} --state-file {scope_state_file}
```

This returns a list of files in scope. Parse the JSON output to get the `files` array.

### Step 4: Run Reviewer Agent

Review the implementation against the plan:

```bash
uv run python -m scripts.agents implementation-reviewer '{
  "plan_file": "{plan_file}",
  "files": {files_json_array},
  "review_file": "{review_file}",
  "conclusions_file": "{conclusions_file}",
  "working_dir": "{working_dir}"
}'
```

**WAIT**: If this goes to background, call TaskOutput and wait until status is completed/failed. Do NOT proceed until complete.

### Step 5: Check Review Status

Only after Step 4 has fully completed:

```bash
head -1 {review_file}
```

- If `[CLEAN]`: Go to Step 8: Finalization (clean review path)
- If `[OPEN]` issues exist: Continue to Step 6

### Step 6: Run PR Review Loop to Fix Issues

Build the review-loop command based on mode:

**Local mode:**
```bash
uv run pr review-loop --tasks-file {review_file}
```

**Worktree mode:**
```bash
uv run pr review-loop --worktree {working_dir} --tasks-file {review_file}
```

**WAIT**: If this goes to background, call TaskOutput and wait until status is completed/failed.

**Check review-loop result:**
- If output contains "no tasks found" or "0 tasks": All issues were evaluated and deemed non-actionable. **Set review.txt to [CLEAN] and go to Step 8** - workflow is complete.
- If tasks were fixed: Continue to Step 7 to verify fixes.

### Step 7: Re-run Review Cycle

Only if review-loop actually fixed tasks (not "no tasks found").

Repeat Steps 3-6 up to 3 times until clean.

**Iteration Counter Mechanism:**
- The iteration count is stored in `{state_file}` under the key `iteration`
- At the start of each Step 7 cycle, read `{state_file}` to get the current iteration count
- Before re-running the cycle, the count is incremented and persisted back to `{state_file}`
- The loop condition is checked as `while iteration < 3` to decide whether to continue

On each iteration:
1. Run discover-scope-files (checks for new commits/files) - captures new files automatically
2. Run reviewer with files list and conclusions_file - WAIT for completion
3. If still `[OPEN]` issues and iterations < 3, run review-loop again - WAIT for completion
4. **If review-loop reports "no tasks found" or "0 tasks"**: All remaining issues are non-actionable. **Set review.txt to [CLEAN] and go to Step 8** - workflow is complete.

### Step 8: Finalization

**On clean review:**

```bash
rm -rf {workspace}
```

Output:
```
=== Implementation Review Complete ===
Status: CLEAN
Iterations: {count}
Working Directory: {working_dir}
```

**On max iterations:**

Preserve workspace for inspection:
```
=== Implementation Review Incomplete ===
Status: ISSUES REMAIN
Iterations: 3
Workspace preserved: {workspace}
```

## Error Handling

When any step fails, invoke workflow-repair to fix the *tooling* (not content):

```bash
uv run python -m scripts.agents workflow-repair '{
  "workflow": "implementation-review",
  "step": "{current_step}",
  "state_file": "{state_file}",
  "failed_command": "...",
  "exit_code": 1,
  "stdout": "{captured_stdout}",
  "stderr": "{captured_stderr}",
  "workspace": "{workspace}",
  "working_dir": "{working_dir}"
}'
```

**Note**: When constructing the JSON payload, ensure stdout/stderr are properly escaped:
- Use `jq -Rs` to JSON-encode captured output, or
- Use Python's `json.dumps()` to safely construct the payload

**If `status: "repaired"`**: Use `tool_output` as the result, continue
**If `status: "failed"`**: Preserve workspace, output diagnosis, exit

## State Tracking

All state lives in `{workspace}/`:
- `state.json` - Current step, iteration count, start_commit
- `scope_state.json` - Files discovered, last HEAD tracked
- `conclusions.json` - Reviewer reasoning about each file
- `review.txt` - Issues in review format
- `plan.txt` - The plan being reviewed against

## Rules

1. Save state before running each step
2. On failure, invoke workflow-repair with failed command details
3. Workflow-repair fixes tooling, not content
4. Maximum 3 review iterations
5. Preserve workspace on unrecoverable failure
6. Always pass `working_dir` to agents in worktree mode
7. Scope agent runs ONCE - Python discovers files on each cycle
