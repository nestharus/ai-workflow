# Plan

## Overview

Enforce strict agent call boundaries so that `apply_plan` and all `.tasks` orchestration code only invoke agents defined in `.tasks/agents/*`. This removes the test-fixer call from apply_plan and ensures no `.claude/agents/*` agents are called from orchestration.

## Current State (Problems)

1. `testing.py:200` calls `_run_tasks_agent("test-fixer", "")` but test-fixer is in `.claude/agents/`, not `.tasks/agents/`
2. `testing.py:182` calls `_run_tasks_agent("test-debugger", ...)` but test-debugger is in `.claude/agents/`
3. `apply_plan.py:172` calls `_run_claude_agent("task-patcher", ...)` - directly invokes `.claude/agents/`
4. `apply_plan.py:224` calls `_run_claude_agent("implementation-analyzer", ...)` - directly invokes `.claude/agents/`

## Target State

1. `apply_plan` does NOT call `test-fixer` at all
2. No code under `.tasks/` or `scripts/tasks/` calls any `.claude/agents/*` agent
3. All orchestration dispatches only to agents in `.tasks/agents/*`
4. Agents needed by orchestration (test-debugger, task-patcher, implementation-analyzer) are migrated to `.tasks/agents/`

## Additional Info

- `.tasks.yaml` configures `agents_dir: .tasks/agents`
- `tasks_agent_runner.py` loads agents from `.tasks/agents/`
- `claude_agent_runner.py` loads agents from `.claude/agents/`
- Current `.tasks/agents/` contains: implementor, reviewer, test-strategy, test-planner, test-writer

## Tasks

### Task 1: Remove test-fixer invocation from testing.py

**File:** `scripts/tasks/workflows/testing.py`

**Changes:**
1. Remove the `run_test_fixer_workflow()` function (lines 188-203)
2. Remove the `_parse_test_fixer_output()` function (lines 117-157)
3. Remove the `TestFixerResult` dataclass (lines 44-60)
4. Remove the `TestFixerStatus` type alias (line 41)
5. Update module docstring to remove test-fixer references

**Do NOT remove:** `run_testing_workflow()`, `TestingResult`, `_parse_test_debugger_output()`, `_run_tasks_agent()` - these are still used.

### Task 2: Remove test-fixer call from apply_plan.py

**File:** `scripts/tasks/workflows/apply_plan.py`

**Changes:**
1. Remove the import of `TestFixerResult` and `run_test_fixer_workflow` from line 30-35
2. Remove the call to `run_test_fixer_workflow()` at line 200 (inside `_process_task`, in the `if mode == "success":` block)

The success block should become:
```python
if mode == "success":
    review_prompt = f"Review the implementation in {task_path} against the plan"
    _run_opencode_agent("reviewer", review_prompt)
    _update_status(status_path, status_data, task_file, status="completed")
    return "completed"
```

### Task 3: Migrate test-debugger to .tasks/agents

**Create file:** `.tasks/agents/test-debugger.md`

Copy content from `.claude/agents/test-debugger.md` and update frontmatter to match `.tasks` agent format:

```yaml
---
description: Debugs failing tests reported by implementor and attempts to fix them
mode: subagent
model: opus
provider: claude
tools:
  read: true
  edit: true
  bash: true
  grep: true
  glob: true
---
```

Keep the system prompt body unchanged.

### Task 4: Migrate task-patcher to .tasks/agents

**Create file:** `.tasks/agents/task-patcher.md`

Copy content from `.claude/agents/task-patcher.md` and update frontmatter:

```yaml
---
description: Updates task files when the source plan changes mid-execution
mode: subagent
model: opus
provider: claude
tools:
  read: true
  edit: true
---
```

Keep the system prompt body unchanged.

### Task 5: Migrate implementation-analyzer to .tasks/agents

**Create file:** `.tasks/agents/implementation-analyzer.md`

Copy content from `.claude/agents/implementation-analyzer.md` and update frontmatter:

```yaml
---
description: Analyzes implementation failures and determines recovery strategy
mode: subagent
model: opus
provider: claude
tools:
  read: true
  write: true
  bash: true
  grep: true
  glob: true
---
```

Keep the system prompt body unchanged.

### Task 6: Replace _run_claude_agent calls with _run_tasks_agent in apply_plan.py

**File:** `scripts/tasks/workflows/apply_plan.py`

**Changes:**
1. Delete the `_run_claude_agent()` function (lines 125-128)
2. Import `_run_tasks_agent` from implementation module if not already imported
3. Replace line 172: `_run_claude_agent("task-patcher", prompt)` with `_run_tasks_agent("task-patcher", prompt)`
4. Replace line 224: `_run_claude_agent("implementation-analyzer", fail_prompt)` with `_run_tasks_agent("implementation-analyzer", fail_prompt)`

Note: `_run_tasks_agent` is already imported from `implementation.py` at line 27.

### Task 7: Update tests in test_apply_plan.py

**File:** `scripts/tests/test_apply_plan.py`

**Changes:**
1. Remove tests for `_run_claude_agent` (the `TestRunClaudeAgent` class around lines 170-177)
2. Remove imports/references to `TestFixerResult` and `run_test_fixer_workflow`
3. Update `TestProcessTask` tests that mock `run_test_fixer_workflow` - remove those mocks
4. Update tests that mock `_run_claude_agent` to mock `_run_tasks_agent` instead for task-patcher and implementation-analyzer
5. Ensure all tests pass after changes

## Execution Instructions

For each task:

1. **Execute**: Use the general-purpose sub-agent to implement the task:
   ```
   Task(subagent_type="general-purpose", prompt="Implement Task N from .tasks/plans/enforce-call-boundaries.md. Read the plan file first, then implement the specific task requirements. Write tests as specified. Do not modify other tasks' code.")
   ```

2. **Review**: After sub-agent completes, review the changes against the plan:
   - Verify all requirements are met
   - Check that tests pass
   - Check that existing functionality is preserved
   - Note any deviations or issues

3. **Iterate**: If review finds issues, pass feedback to sub-agent:
   ```
   Task(subagent_type="general-purpose", prompt="Review feedback for Task N: [feedback]. Fix the issues identified. The plan is in .tasks/plans/enforce-call-boundaries.md.")
   ```

4. **Proceed**: Only move to next task when current task passes review

## Success Criteria

1. `grep -r "test-fixer" scripts/tasks/workflows/` returns NO matches
2. `grep -rn "_run_claude_agent" scripts/tasks/` returns NO matches
3. All agents called by orchestration exist in `.tasks/agents/`:
   - `.tasks/agents/implementor.md` (existing)
   - `.tasks/agents/test-debugger.md` (new)
   - `.tasks/agents/task-patcher.md` (new)
   - `.tasks/agents/implementation-analyzer.md` (new)
4. `uv run pytest scripts/tests/test_apply_plan.py -v` passes
5. `uv run lint ruff mypy` passes
