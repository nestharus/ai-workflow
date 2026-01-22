# Review Implementation Command

---

description: Review implementation against a plan with state tracking and auto-repair
allowed-tools: Task, Read, Glob, Bash, TodoWrite, TaskOutput

---

Review implementation against the following plan: $ARGUMENTS

## Overview

This command reviews an implementation against a plan, identifies issues, and fixes them iteratively.

## CRITICAL: Synchronization Rules

**EVERY agent command MUST complete before proceeding to the next step.**

- If a bash command goes to background, call `TaskOutput(task_id=<id>, block=true, timeout=600000)` to wait
- If TaskOutput times out but task is still running, call TaskOutput again (task continues in background)
- Repeat until status shows completed/failed
- NEVER read output files until the writing agent has completed
- NEVER skip ahead while an agent is still running

## Execution

### Step 1: Setup Workspace

Clean any stale data from previous runs and create fresh workspace:

```bash
rm -rf .tmp/implementation-review && mkdir -p .tmp/implementation-review
```

Save the plan text to a file:

```bash
cat > .tmp/implementation-review/plan.txt << 'EOF'
$ARGUMENTS
EOF
```

### Step 2: Run Scope Agent

Analyze git history to determine what files are in scope:

```bash
uv run python -m scripts.agents implementation-scope '{"plan_file": ".tmp/implementation-review/plan.txt", "workspace": ".tmp/implementation-review"}'
```

**WAIT**: If this goes to background, call TaskOutput and wait until status is completed/failed.

### Step 3: Run Reviewer Agent

Review the implementation against the plan:

```bash
uv run python -m scripts.agents implementation-reviewer '{"plan_file": ".tmp/implementation-review/plan.txt", "shape_file": ".tmp/implementation-review/scope.json", "review_file": ".tmp/implementation-review/review.txt", "previous_review_file": null, "working_dir": "."}'
```

**WAIT**: If this goes to background, call TaskOutput and wait until status is completed/failed. Do NOT proceed until complete.

For subsequent iterations, pass the previous review for comparison:

```bash
# Iteration 2+: Pass previous review for comparison
uv run python -m scripts.agents implementation-reviewer '{
  "plan_file": ".tmp/implementation-review/plan.txt",
  "shape_file": ".tmp/implementation-review/scope.json",
  "review_file": ".tmp/implementation-review/review.txt",
  "previous_review_file": ".tmp/implementation-review/review.txt.prev",
  "working_dir": "."
}'
```

### Step 4: Check Review Status

Only after Step 3 has fully completed:

```bash
head -1 .tmp/implementation-review/review.txt
```

- If `[CLEAN]`: Go to Step 7: Finalization (clean review path)
- If `[OPEN]` issues exist: Continue to Step 5

### Step 5: Run PR Outer Loop to Fix Issues

Pass arguments as a single prompt string (not CLI flags):

```bash
uv run python -m scripts.agents pr-outer-loop '--loop --tasks-file .tmp/implementation-review/review.txt'
```

**WAIT**: If this goes to background, call TaskOutput and wait until status is completed/failed.

**Check pr-outer-loop result:**
- If output contains "no tasks found" or "0 tasks": All issues were evaluated and deemed non-actionable. **Set review.txt to [CLEAN] and go to Step 7** - workflow is complete.
- If tasks were fixed: Continue to Step 6 to verify fixes.

### Step 6: Re-run Review Cycle

Only if pr-outer-loop actually fixed tasks (not "no tasks found").

Repeat Steps 2-5 up to 3 times until clean.

**Iteration Counter Mechanism:**
- The iteration count is stored in `state.json` under the key `pr_outer_loop.iteration`
- At the start of each Step 6 cycle, the pr-outer-loop reads `state.json` to get the current iteration count
- Before re-running the cycle, the count is incremented and persisted back to `state.json` (per Rule 1)
- The loop condition is checked as `while iteration < 3` to decide whether to continue

On each iteration:
1. Run scope agent (incremental update) - WAIT for completion via TaskOutput
2. Run reviewer with `previous_review_file` set to verify fixes - WAIT for completion via TaskOutput
3. If still `[OPEN]` issues and iterations < 3, run pr-outer-loop again - WAIT for completion via TaskOutput
4. **If pr-outer-loop reports "no tasks found" or "0 tasks"**: All remaining issues are non-actionable. **Set review.txt to [CLEAN] and go to Step 7** - workflow is complete.

### Step 7: Finalization

**On clean review:**

```bash
rm -rf .tmp/implementation-review
```

Output:
```
=== Implementation Review Complete ===
Status: CLEAN
Iterations: {count}
```

**On max iterations:**

Preserve workspace for inspection:
```
=== Implementation Review Incomplete ===
Status: ISSUES REMAIN
Iterations: 3
Workspace preserved: .tmp/implementation-review/
```

## Error Handling

When any step fails, invoke workflow-repair to fix the *tooling* (not content):

```bash
uv run python -m scripts.agents workflow-repair '{
  "workflow": "implementation-review",
  "step": "{current_step}",
  "state_file": ".tmp/implementation-review/state.json",
  "failed_command": "...",
  "exit_code": 1,
  "stdout": "{captured_stdout}",
  "stderr": "{captured_stderr}",
  "workspace": ".tmp/implementation-review"
}'
```

**Note**: When constructing the JSON payload, ensure stdout/stderr are properly escaped:
- Use `jq -Rs` to JSON-encode captured output, or
- Use Python's `json.dumps()` to safely construct the payload

**If `status: "repaired"`**: Use `tool_output` as the result, continue
**If `status: "failed"`**: Preserve workspace, output diagnosis, exit

## State Tracking

All state lives in `.tmp/implementation-review/`:
- `state.json` - Current step, history, errors
- `scope.json` - File classifications (shape)
- `review.txt` - Issues in pr-outer-loop format
- `plan.txt` - The plan being reviewed against

## Rules

1. Save state before running each step
2. On failure, invoke workflow-repair with failed command details
3. Workflow-repair fixes tooling, not content
4. Maximum 3 review iterations
5. Preserve workspace on unrecoverable failure
