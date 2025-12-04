# Plan

## Overview

Implement the test automation workflow as specified in `docs/plans/test_workflow_spec.md`. This creates an outer-loop orchestration system that coordinates test strategy creation, planning, writing, debugging, and coverage validation.

## Current State (Problems)

1. No automated test workflow orchestration exists
2. Existing `test-writer.md` includes debugging (violates "writer must not debug" constraint)
3. `test-strategy.md` only generates strategies, cannot review plans
4. `test-planner.md` only creates plans, cannot review written tests
5. No CLI entry point for running the complete test workflow

## Target State

1. New `test-writer-nodebug.md` agent that writes tests without debugging
2. Extended `test-strategy.md` with review mode (APPROVED/FEEDBACK output)
3. Extended `test-planner.md` with review mode (COMPLETE/INCOMPLETE output)
4. New `scripts/tasks/workflows/test_automation.py` orchestrator
5. CLI entry point `uv run test-workflow` in pyproject.toml

## Additional Info

- All agents must be in `.tasks/agents/` (not `.claude/`)
- Follow existing patterns from `implementation.py` and `testing.py`
- Use `_run_tasks_agent()` for agent invocation
- Coverage tools: `uv run coverage-summary --json`, `uv run coverage-functions --json`
- See `docs/plans/test_workflow_spec.md` for full state machine and output contracts

## Tasks

### Task 1: Create test-writer-nodebug agent

Create `.tasks/agents/test-writer-nodebug.md` based on `test-writer.md` but:
- Remove all debugging steps (Steps 6-7 in original)
- Change output contract to `WRITTEN: <summary>` or `BLOCKED: <reason>`
- Keep firecrawl tools for documentation lookup
- Description: "Writes tests according to test plan without debugging"

Output contract:
```
WRITTEN: <summary of files written>
BLOCKED: <reason>
```

### Task 2: Extend test-strategy with review mode

Modify `.tasks/agents/test-strategy.md` to add review mode:
- Add "Review Mode" section after existing workflow
- Triggered when prompt contains "Mode: review" and includes a plan
- Review mode outputs: `APPROVED`, `FEEDBACK: <issues>`, or `BLOCKED: <reason>`
- Keep existing strategy generation behavior unchanged

Add to agent prompt:
```markdown
## Review Mode

When the prompt contains "Mode: review" and includes both a strategy and plan:

1. Compare the plan against the original strategy
2. Verify tier assignments match strategy recommendations
3. Check use-case coverage goals are addressed
4. Verify testing patterns align with strategy guidance
5. Confirm edge cases from strategy are planned

Output one of:
- APPROVED (if plan satisfies strategy)
- FEEDBACK: <specific issues to address>
- BLOCKED: <reason review cannot proceed>
```

### Task 3: Extend test-planner with review mode

Modify `.tasks/agents/test-planner.md` to add review mode:
- Add "Review Mode" section after existing workflow
- Triggered when prompt contains "Mode: review" and includes written test files
- Review mode outputs: `COMPLETE: plan satisfied`, `INCOMPLETE: <gaps>`, or `BLOCKED: <reason>`
- Keep existing plan generation behavior unchanged

Add to agent prompt:
```markdown
## Review Mode

When the prompt contains "Mode: review" and includes written test files:

1. Compare written tests against the original plan
2. Verify each planned test function exists
3. Check use-case markers are correctly applied
4. Verify assertions match plan specifications
5. Confirm edge cases are covered as planned

Output one of:
- COMPLETE: plan satisfied
- INCOMPLETE: <list of missing tests or gaps>
- BLOCKED: <reason review cannot proceed>
```

### Task 4: Create test_automation.py orchestrator

Create `scripts/tasks/workflows/test_automation.py` with:

1. **Data classes** (lines 1-50):
   - `TestWorkflowState` type alias
   - `WorkflowContext` dataclass
   - `StateResult` dataclass
   - `WorkflowResult` dataclass
   - `CoverageResult` dataclass

2. **Helper functions** (lines 51-150):
   - `_run_tasks_agent()` (copy from implementation.py)
   - `_run()` subprocess helper
   - Prompt formatters for each state
   - Output parsers for each agent response

3. **State handlers** (lines 151-350):
   - `handle_init()`
   - `handle_strategy()`
   - `handle_planning()`
   - `handle_strategy_review()`
   - `handle_writing()`
   - `handle_debugging()`
   - `handle_plan_review()`
   - `handle_coverage()`
   - `handle_strategy_update()`

4. **Main workflow** (lines 351-400):
   - `run_test_automation_workflow()` function
   - State machine loop

5. **CLI entry point** (lines 401-420):
   - `main()` with argparse

Follow the implementation details in `docs/plans/test_workflow_spec.md`.

### Task 5: Add pyproject.toml entry

Add to `pyproject.toml` under `[project.scripts]`:
```toml
test-workflow = "scripts.tasks.workflows.test_automation:main"
```

### Task 6: Write unit tests

Create `scripts/tests/tasks/workflows/test_test_automation.py` with tests for:
- Output parsers (strategy, planner, writer, debugger outputs)
- State handlers (mock agent calls, verify transitions)
- WorkflowContext updates
- Coverage result parsing

Follow existing test patterns in `scripts/tests/`.

## Execution Instructions

For each task:

1. **Execute**: Use the general-purpose sub-agent to implement the task:
   ```
   Task(subagent_type="general-purpose", prompt="Implement Task N from .tasks/plans/test_workflow_implementation.md. Read the plan file first, then implement the specific task requirements. Write tests as specified. Do not modify other tasks' code.")
   ```

2. **Review**: After ***EACH INDIVIDUAL*** sub-agent completes, review the changes against the plan:
   - Verify all requirements are met
   - Check that tests pass
   - Check that existing functionality is preserved
   - Note any deviations or issues

3. **Iterate**: If review finds issues, pass feedback to sub-agent:
   ```
   Task(subagent_type="general-purpose", prompt="Review feedback for Task N: [feedback]. Fix the issues identified. The plan is in .tasks/plans/test_workflow_implementation.md.")
   ```

4. **Proceed**: Only move to next task when current task passes review

## Success Criteria

1. All 6 tasks completed without blockers
2. `uv run lint` passes
3. `uv run pytest scripts/tests/tasks/workflows/test_test_automation.py -v` passes
4. CLI `uv run test-workflow --help` works
5. Agent files have correct output contracts documented
