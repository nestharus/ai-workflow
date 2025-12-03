---
description: Apply Traycer AI implementation plans by orchestrating sub-agents
argument-hint: [--tasks-dir .tasks/<timestamp>]
allowed-tools: Bash, Read, Write, Edit, Glob, Grep, Task, TodoWrite
---

# Apply Plan Orchestrator

Automates execution of Traycer AI implementation plans by orchestrating sub-agents.

## Usage

- `/apply-plan` - Parse plan from clipboard, create timestamped folder under `.tasks/`
- `/apply-plan --tasks-dir .tasks/<timestamp>` - Resume from existing tasks directory

## Workflow

### Step 1: Initialize Tasks Directory

If `--tasks-dir` is provided in `$ARGUMENTS`, use that directory. Otherwise:

1. Run `python scripts/clipboard_to_plan.py` to create a new tasks directory
2. The script outputs the path to the created directory (e.g., `.tasks/20241203_120000/`)
3. Capture and use this path for subsequent operations

### Step 2: Load or Initialize Status

Read `status.yml` from the tasks directory. If it doesn't exist, initialize it by:

1. Collecting all `task_*.md` files from the directory
2. Creating status entries for each task with `status: pending`
3. Computing a plan hash from the outline

### Step 3: Process Each Pending Task

For each task where `status != completed`:

1. Mark task as `in_progress` in `status.yml`
2. Read the task file content
3. Invoke the **implementor** sub-agent via OpenCode:
   ```bash
   python scripts/dev/opencode_agent_runner.py --agent implementor --prompt "<task_file_path>"
   ```

4. Parse the implementor output:
   - **SUCCESS**: Proceed to review phase
   - **TESTS: [test1, test2, ...]**: Invoke test-debugger, keep task pending
   - **FAIL: <reason>**: Create `.changes` files, invoke implementation-analyzer

### Step 4: Handle Outcomes

#### On SUCCESS:
1. Run reviewer via OpenCode:
   ```bash
   python scripts/dev/opencode_agent_runner.py --agent reviewer --prompt "Review the implementation in <task_path> against the plan"
   ```
2. Run test-fixer sub-agent: `Task(subagent_type="test-fixer", prompt="")`
3. Mark task as `completed` in `status.yml`

#### On TESTS:
1. Run test-debugger via Claude:
   ```bash
   python scripts/dev/claude_agent_runner.py --agent test-debugger --prompt "Task: <content>\nFailing Tests: [<tests>]\nInstructions: Debug and fix the failing tests."
   ```
2. Keep task as `pending`

#### On FAIL:
1. Create `.changes` files by running `git diff` for each modified file
2. Run implementation-analyzer via Claude:
   ```bash
   python scripts/dev/claude_agent_runner.py --agent implementation-analyzer --prompt "Task: <content>\nChanges Made: <diffs>\nFailure: <reason>\nInstructions: Analyze and determine next steps."
   ```
3. Check for `.conclusion` files - if found, pause for human decision
4. Update status accordingly

### Step 5: Check for Completion

After processing all tasks:
- If any `.conclusion` file exists: Report that human intervention is required
- If any tasks remain incomplete: Report remaining tasks
- If all tasks completed: Report success

## Sub-agents Used

- **implementor** (OpenCode): Implements the task
- **reviewer** (OpenCode): Reviews the implementation
- **test-fixer** (Claude): Fixes test failures and ensures coverage
- **test-debugger** (Claude): Debugs specific test failures
- **implementation-analyzer** (Claude): Analyzes failures and determines next steps
- **task-patcher** (Claude): Patches incomplete tasks when plan changes

## Status File Format

```yaml
plan_hash: <sha256_hash>
tasks:
  - task_file: task_001.md
    file: <header from task file>
    status: pending|in_progress|completed
    conclusion_file: null
    changes_file: null
```

## Important Notes

1. Always update `status.yml` immediately after each status change
2. Process tasks sequentially - do not parallelize
3. Stop processing if a `.conclusion` file is detected
4. Use the TodoWrite tool to track progress through tasks
