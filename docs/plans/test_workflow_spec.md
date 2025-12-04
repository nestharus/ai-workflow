# Test Automation Workflow Specification

## Overview

An outer-loop workflow that orchestrates test strategy creation, planning, writing,
debugging, and coverage validation. Implements iterative feedback loops until coverage
thresholds are met.

**Workflow Summary**:
```
files → strategy → plan ⇄ strategy-review → writer → debugger → plan-review → coverage → loop
```

---

## State Machine

### States

| State | Description | Agent(s) |
|-------|-------------|----------|
| `INIT` | Entry point with target files | Python orchestrator |
| `STRATEGY` | Generate testing strategy | test-strategy |
| `PLANNING` | Create actionable test plan | test-planner |
| `STRATEGY_REVIEW` | Review plan against strategy | test-strategy |
| `WRITING` | Write tests (no debugging) | test-writer-nodebug |
| `DEBUGGING` | Fix failing tests | test-debugger |
| `PLAN_REVIEW` | Review written tests vs plan | test-planner |
| `COVERAGE` | Run coverage and analyze gaps | Python orchestrator |
| `STRATEGY_UPDATE` | Request strategy revision | test-strategy |
| `COMPLETE` | Coverage threshold met | Terminal state |
| `BLOCKED` | Unrecoverable failure | Terminal state |

### Transitions

```
INIT
  │
  ├──[files provided]──────────────────────────────────────► STRATEGY
  │
STRATEGY
  │
  ├──[STRATEGY: <doc>]─────────────────────────────────────► PLANNING
  ├──[BLOCKED: <reason>]───────────────────────────────────► BLOCKED
  │
PLANNING
  │
  ├──[PLAN: <doc>]─────────────────────────────────────────► STRATEGY_REVIEW
  ├──[BLOCKED: <reason>]───────────────────────────────────► BLOCKED
  │
STRATEGY_REVIEW                              ┌───────────────────────┐
  │                                          │                       │
  ├──[APPROVED]────────────────────────────────► WRITING             │
  ├──[FEEDBACK: <issues>]───────────────────►  PLANNING ◄────────────┘
  │                                            (with feedback)
  ├──[BLOCKED: <reason>]───────────────────────────────────► BLOCKED
  │
WRITING
  │
  ├──[WRITTEN: <summary>]──────────────────────────────────► DEBUGGING
  ├──[BLOCKED: <reason>]───────────────────────────────────► BLOCKED
  │
DEBUGGING
  │
  ├──[FIXED: <summary>]────────────────────────────────────► PLAN_REVIEW
  ├──[PARTIAL: <issues>]───────────────────────────────────► DEBUGGING (retry N times)
  ├──[BLOCKED: <reason>]───────────────────────────────────► BLOCKED
  │
PLAN_REVIEW
  │
  ├──[COMPLETE: plan satisfied]────────────────────────────► COVERAGE
  ├──[INCOMPLETE: <gaps>]──────────────────────────────────► WRITING
  │                                                          (with gaps)
  ├──[BLOCKED: <reason>]───────────────────────────────────► BLOCKED
  │
COVERAGE
  │
  ├──[PASS: threshold met]─────────────────────────────────► COMPLETE
  ├──[GAPS: <functions>]───────────────────────────────────► PLANNING
  │                                                          (with gaps + strategy)
  ├──[STRATEGY_NEEDED: <reason>]───────────────────────────► STRATEGY_UPDATE
  │
STRATEGY_UPDATE
  │
  ├──[STRATEGY: <revised_doc>]─────────────────────────────► PLANNING
  ├──[BLOCKED: <reason>]───────────────────────────────────► BLOCKED
  │
COMPLETE ──► EXIT(0)
BLOCKED  ──► EXIT(1)
```

---

## Agent Definitions

### Existing Agents (Unchanged)

| Agent | Location | Tools | Purpose |
|-------|----------|-------|---------|
| `test-strategy` | `.tasks/agents/test-strategy.md` | bash (read-only) | Produce testing strategy |
| `test-planner` | `.tasks/agents/test-planner.md` | bash (read-only) | Create actionable test plans |
| `test-debugger` | `.tasks/agents/test-debugger.md` | read, edit, bash | Fix failing tests |

### New Agent: `test-writer-nodebug`

**Location**: `.tasks/agents/test-writer-nodebug.md`

**Rationale**: The existing `test-writer.md` includes debugging in its workflow. Per
constraint "writer must not debug", we create a dedicated agent that writes tests but
stops before running/debugging them.

```yaml
---
description: Writes tests according to test plan without debugging. Use when test plans are ready for implementation.
tools: Read, Edit, Bash, Grep, Glob, TodoWrite, mcp__firecrawl__firecrawl_search, mcp__firecrawl__firecrawl_scrape
model: opus
provider: claude
routing_thresholds:
  - max_chars: null
    model: opus
    provider: claude
---

<system prompt for write-only test implementation - no debugging>
```

**Output Contract**:
```
WRITTEN: <summary of test files written>
BLOCKED: <reason implementation cannot proceed>
```

### Agent Modifications

#### `test-strategy.md` - Add Review Mode

The current agent only generates strategies. Add a **review mode** that accepts
`{plan}` and `{strategy}` inputs and outputs:

```
APPROVED
FEEDBACK: <list of issues>
BLOCKED: <reason>
```

**Implementation**: Add conditional prompt section triggered by presence of plan input.

#### `test-planner.md` - Add Review Mode

Add ability to review written tests against the plan. Accepts `{plan}` and `{tests}`
inputs and outputs:

```
COMPLETE: plan satisfied
INCOMPLETE: <list of gaps>
BLOCKED: <reason>
```

**Implementation**: Add conditional prompt section triggered by presence of test files input.

---

## Workflow Inputs/Outputs

### INIT → STRATEGY

**Input** (from Python orchestrator):
```
Files: [list of file paths to test]
Context: <optional description of what changed>
Existing Tests: [paths to existing test files, if any]
```

**Prompt Template**:
```
Analyze the following files and produce a comprehensive testing strategy.

## Target Files
{files_list}

## Context
{context}

## Existing Tests (for pattern reference)
{existing_tests}

## Instructions
Follow your analysis workflow to produce a testing strategy document.
```

### STRATEGY → PLANNING

**Input**:
```
Strategy: {strategy_document}
Git Diff: {git_diff_output}
Files: {target_files}
```

**Prompt Template**:
```
Create an actionable test plan based on the following strategy.

## Testing Strategy
{strategy_document}

## Git Diff
{git_diff}

## Target Files
{files_list}

## Instructions
Follow your workflow to produce a file-by-file test plan.
```

### PLANNING → STRATEGY_REVIEW

**Input** (test-strategy in review mode):
```
Strategy: {original_strategy}
Plan: {test_plan}
Mode: review
```

**Prompt Template**:
```
Review the following test plan against the original strategy.

## Original Strategy
{strategy_document}

## Proposed Test Plan
{test_plan}

## Instructions
Verify the plan adequately covers the strategy requirements:
1. Tier assignments match strategy recommendations
2. Use-case coverage goals are addressed
3. Testing patterns align with strategy guidance
4. Edge cases from strategy are planned

Output one of:
- APPROVED (if plan satisfies strategy)
- FEEDBACK: <specific issues to address>
- BLOCKED: <reason review cannot proceed>
```

### STRATEGY_REVIEW → PLANNING (feedback loop)

**Input** (test-planner with feedback):
```
Strategy: {original_strategy}
Previous Plan: {test_plan}
Feedback: {strategy_review_feedback}
Git Diff: {git_diff_output}
```

**Prompt Template**:
```
Update the test plan to address the following feedback.

## Testing Strategy
{strategy_document}

## Previous Plan
{previous_plan}

## Feedback to Address
{feedback}

## Git Diff
{git_diff}

## Instructions
Revise the plan to address each feedback item while maintaining coverage goals.
```

### STRATEGY_REVIEW → WRITING

**Input** (test-writer-nodebug):
```
Plan: {approved_test_plan}
```

**Prompt Template**:
```
Write tests according to the following approved test plan.

## Test Plan
{approved_plan}

## Instructions
1. Read the test plan thoroughly
2. Update use-case registry if needed
3. Examine existing test patterns
4. Write all test files specified in the plan
5. DO NOT run or debug tests - stop after writing

Output:
- WRITTEN: <summary of files written, test count>
- BLOCKED: <reason if unable to write>
```

### WRITING → DEBUGGING

**Input** (test-debugger):
```
Task: Write tests according to plan
Plan: {test_plan}
Failing Tests: [all newly written tests]
```

**Prompt Template**:
```
Task: Verify and fix the newly written tests.

Plan: {test_plan}

Failing Tests: [{test_files}]

Instructions: Run all tests written in the plan. Debug and fix any failures.
Prefer fixing implementation bugs; only modify tests if they are incorrect.
```

### DEBUGGING → PLAN_REVIEW

**Input** (test-planner in review mode):
```
Plan: {original_test_plan}
Written Tests: {test_file_paths}
Mode: review
```

**Prompt Template**:
```
Review the written tests against the original test plan.

## Original Plan
{test_plan}

## Written Test Files
{test_files_with_content}

## Instructions
Verify all planned tests were implemented:
1. Each planned test function exists
2. Use-case markers are correctly applied
3. Assertions match plan specifications
4. Edge cases are covered as planned

Output one of:
- COMPLETE: plan satisfied
- INCOMPLETE: <list of missing tests or gaps>
- BLOCKED: <reason review cannot proceed>
```

### PLAN_REVIEW → COVERAGE

**Python orchestrator action**:
```bash
uv run test-coverage
uv run coverage-functions --json
uv run coverage-summary --json
```

**Output parsing**:
```python
def parse_coverage_output(json_output: dict) -> CoverageResult:
    """Parse coverage JSON to determine gaps."""
    functions_below = json_output.get("filtered_totals", {}).get("functions_below_threshold", 0)
    tier_summaries = json_output.get("tier_summaries", {})

    all_pass = all(tier["tier_pass"] for tier in tier_summaries.values())

    if all_pass and functions_below == 0:
        return CoverageResult(status="pass", gaps=None, needs_strategy=False)

    # Get specific gaps
    gaps = get_functions_below_threshold(...)

    # Determine if gaps indicate need for new strategy
    needs_new_strategy = determine_strategy_need(gaps, original_strategy)

    return CoverageResult(
        status="gaps",
        gaps=gaps,
        needs_strategy=needs_new_strategy
    )
```

### COVERAGE → PLANNING (with gaps)

**Input** (test-planner with coverage gaps):
```
Strategy: {original_strategy}
Previous Plan: {previous_plan}
Coverage Gaps: {functions_below_threshold}
Written Tests: {test_files}
```

**Prompt Template**:
```
Create additional tests to address coverage gaps.

## Original Strategy
{strategy_document}

## Previous Plan
{previous_plan}

## Coverage Gaps
The following functions are below 80% line/branch coverage:
{coverage_gaps_formatted}

## Existing Tests
{test_files}

## Instructions
Extend the test plan to cover the gaps. Focus on:
1. Functions with lowest coverage
2. Missing branch coverage
3. Untested edge cases
```

### COVERAGE → STRATEGY_UPDATE

**Input** (test-strategy for revision):
```
Original Strategy: {original_strategy}
Written Tests: {test_files}
Coverage Gaps: {coverage_gaps}
Mode: revise
```

**Prompt Template**:
```
Revise the testing strategy based on coverage results.

## Original Strategy
{original_strategy}

## Written Tests
{test_files}

## Coverage Gaps
{coverage_gaps}

## Why Revision Needed
{reason}

## Instructions
Update the strategy to address structural gaps that prevented coverage:
1. Identify patterns not covered by original strategy
2. Recommend additional testing approaches
3. Adjust tier assignments if needed
4. Add missing edge case categories
```

---

## Python Orchestrator Implementation

### File Location

```
scripts/tasks/workflows/test_automation.py
```

### Data Classes

```python
from dataclasses import dataclass
from typing import Literal

TestWorkflowState = Literal[
    "init", "strategy", "planning", "strategy_review",
    "writing", "debugging", "plan_review", "coverage",
    "strategy_update", "complete", "blocked"
]

@dataclass
class WorkflowContext:
    """Accumulated context through workflow execution."""
    target_files: list[str]
    strategy_document: str | None = None
    test_plan: str | None = None
    written_tests: list[str] | None = None
    coverage_gaps: list[dict] | None = None
    feedback_history: list[str] | None = None
    iteration_count: int = 0
    max_iterations: int = 5
    debug_retry_count: int = 0
    max_debug_retries: int = 3

@dataclass
class StateResult:
    """Result from a state handler."""
    next_state: TestWorkflowState
    context_updates: dict
    message: str

@dataclass
class WorkflowResult:
    """Final workflow result."""
    success: bool
    state: TestWorkflowState
    message: str
    context: WorkflowContext
```

### State Handlers

```python
def handle_init(ctx: WorkflowContext) -> StateResult:
    """Entry point - validate inputs and proceed to strategy."""
    if not ctx.target_files:
        return StateResult("blocked", {}, "No target files provided")
    return StateResult("strategy", {}, f"Starting strategy for {len(ctx.target_files)} files")


def handle_strategy(ctx: WorkflowContext) -> StateResult:
    """Generate testing strategy via test-strategy agent."""
    prompt = format_strategy_prompt(ctx.target_files)
    result = _run_tasks_agent("test-strategy", prompt)

    status, content = parse_strategy_output(result.stdout)

    if status == "blocked":
        return StateResult("blocked", {}, content)

    return StateResult("planning", {"strategy_document": content}, "Strategy generated")


def handle_planning(ctx: WorkflowContext) -> StateResult:
    """Create test plan via test-planner agent."""
    prompt = format_planning_prompt(
        ctx.strategy_document,
        ctx.target_files,
        ctx.feedback_history,
        ctx.coverage_gaps
    )
    result = _run_tasks_agent("test-planner", prompt)

    status, content = parse_planner_output(result.stdout)

    if status == "blocked":
        return StateResult("blocked", {}, content)

    return StateResult("strategy_review", {"test_plan": content}, "Plan created")


def handle_strategy_review(ctx: WorkflowContext) -> StateResult:
    """Review plan against strategy via test-strategy agent (review mode)."""
    prompt = format_strategy_review_prompt(ctx.strategy_document, ctx.test_plan)
    result = _run_tasks_agent("test-strategy", prompt)

    status, content = parse_strategy_review_output(result.stdout)

    if status == "approved":
        return StateResult("writing", {}, "Plan approved by strategy review")

    if status == "feedback":
        feedback_history = (ctx.feedback_history or []) + [content]
        return StateResult(
            "planning",
            {"feedback_history": feedback_history},
            f"Feedback received: {content[:100]}..."
        )

    return StateResult("blocked", {}, content)


def handle_writing(ctx: WorkflowContext) -> StateResult:
    """Write tests via test-writer-nodebug agent."""
    prompt = format_writing_prompt(ctx.test_plan)
    result = _run_tasks_agent("test-writer-nodebug", prompt)

    status, content = parse_writer_output(result.stdout)

    if status == "blocked":
        return StateResult("blocked", {}, content)

    written_files = extract_written_files(content)
    return StateResult(
        "debugging",
        {"written_tests": written_files},
        f"Tests written: {len(written_files)} files"
    )


def handle_debugging(ctx: WorkflowContext) -> StateResult:
    """Debug tests via test-debugger agent."""
    prompt = format_debugging_prompt(ctx.test_plan, ctx.written_tests)
    result = _run_tasks_agent("test-debugger", prompt)

    status, message = parse_debugger_output(result.stdout)

    if status == "fixed":
        return StateResult("plan_review", {"debug_retry_count": 0}, "All tests fixed")

    if status == "partial":
        if ctx.debug_retry_count >= ctx.max_debug_retries:
            return StateResult("blocked", {}, f"Max debug retries exceeded: {message}")
        return StateResult(
            "debugging",
            {"debug_retry_count": ctx.debug_retry_count + 1},
            f"Partial fix, retrying: {message}"
        )

    return StateResult("blocked", {}, message)


def handle_plan_review(ctx: WorkflowContext) -> StateResult:
    """Review written tests via test-planner agent (review mode)."""
    prompt = format_plan_review_prompt(ctx.test_plan, ctx.written_tests)
    result = _run_tasks_agent("test-planner", prompt)

    status, content = parse_plan_review_output(result.stdout)

    if status == "complete":
        return StateResult("coverage", {}, "All planned tests implemented")

    if status == "incomplete":
        return StateResult("writing", {}, f"Gaps found: {content}")

    return StateResult("blocked", {}, content)


def handle_coverage(ctx: WorkflowContext) -> StateResult:
    """Run coverage and analyze gaps."""
    # Run coverage tools
    run_command(["uv", "run", "test-coverage"])
    summary = run_command(["uv", "run", "coverage-summary", "--json"])
    functions = run_command(["uv", "run", "coverage-functions", "--json"])

    coverage_result = parse_coverage_results(summary, functions)

    if coverage_result.all_passing:
        return StateResult("complete", {}, "Coverage thresholds met")

    ctx.iteration_count += 1
    if ctx.iteration_count >= ctx.max_iterations:
        return StateResult("blocked", {}, f"Max iterations ({ctx.max_iterations}) exceeded")

    if coverage_result.needs_strategy_revision:
        return StateResult(
            "strategy_update",
            {"coverage_gaps": coverage_result.gaps},
            "Strategy revision needed"
        )

    return StateResult(
        "planning",
        {"coverage_gaps": coverage_result.gaps},
        f"Coverage gaps: {len(coverage_result.gaps)} functions below threshold"
    )


def handle_strategy_update(ctx: WorkflowContext) -> StateResult:
    """Request strategy revision via test-strategy agent."""
    prompt = format_strategy_update_prompt(
        ctx.strategy_document,
        ctx.written_tests,
        ctx.coverage_gaps
    )
    result = _run_tasks_agent("test-strategy", prompt)

    status, content = parse_strategy_output(result.stdout)

    if status == "blocked":
        return StateResult("blocked", {}, content)

    return StateResult(
        "planning",
        {"strategy_document": content, "feedback_history": None},
        "Strategy revised"
    )
```

### Main Entry Point

```python
def run_test_automation_workflow(
    target_files: list[str],
    *,
    max_iterations: int = 5,
    max_debug_retries: int = 3,
) -> WorkflowResult:
    """Execute the test automation workflow.

    Args:
        target_files: List of file paths to generate tests for.
        max_iterations: Maximum coverage→planning loops.
        max_debug_retries: Maximum debugging retries per cycle.

    Returns:
        WorkflowResult with final state and context.
    """
    ctx = WorkflowContext(
        target_files=target_files,
        max_iterations=max_iterations,
        max_debug_retries=max_debug_retries,
    )

    state: TestWorkflowState = "init"

    state_handlers = {
        "init": handle_init,
        "strategy": handle_strategy,
        "planning": handle_planning,
        "strategy_review": handle_strategy_review,
        "writing": handle_writing,
        "debugging": handle_debugging,
        "plan_review": handle_plan_review,
        "coverage": handle_coverage,
        "strategy_update": handle_strategy_update,
    }

    while state not in ("complete", "blocked"):
        handler = state_handlers[state]
        result = handler(ctx)

        # Update context
        for key, value in result.context_updates.items():
            setattr(ctx, key, value)

        print(f"[{state}] → [{result.next_state}]: {result.message}")
        state = result.next_state

    return WorkflowResult(
        success=(state == "complete"),
        state=state,
        message=f"Workflow finished in state: {state}",
        context=ctx,
    )
```

### CLI Entry Point

```python
# scripts/tasks/workflows/test_automation.py

def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run test automation workflow")
    parser.add_argument("files", nargs="+", help="Target files to test")
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--max-debug-retries", type=int, default=3)
    args = parser.parse_args()

    result = run_test_automation_workflow(
        args.files,
        max_iterations=args.max_iterations,
        max_debug_retries=args.max_debug_retries,
    )

    return 0 if result.success else 1
```

### pyproject.toml Entry

```toml
[project.scripts]
test-workflow = "scripts.tasks.workflows.test_automation:main"
```

---

## Output Contracts Summary

### test-strategy

**Standard Mode**:
```
STRATEGY: <document follows>
...structured strategy document...
```
or
```
BLOCKED: <reason>
```

**Review Mode** (when plan input provided):
```
APPROVED
```
or
```
FEEDBACK: <list of issues>
```
or
```
BLOCKED: <reason>
```

### test-planner

**Standard Mode**:
```
PLAN: <document follows>
...structured test plan document...
```
or
```
BLOCKED: <reason>
```

**Review Mode** (when written tests provided):
```
COMPLETE: plan satisfied
```
or
```
INCOMPLETE: <list of gaps>
```
or
```
BLOCKED: <reason>
```

### test-writer-nodebug

```
WRITTEN: <summary>
- tests/unit/test_foo.py: 5 test functions
- tests/integration/test_bar.py: 3 test functions
```
or
```
BLOCKED: <reason>
```

### test-debugger (unchanged)

```
FIXED: All tests now pass
```
or
```
PARTIAL: <remaining issues>
```
or
```
BLOCKED: <reason>
```

---

## Implementation Tasks

### Phase 1: Agent Modifications

1. **Create `test-writer-nodebug.md`** - New agent based on test-writer but without
   debugging steps
2. **Extend `test-strategy.md`** - Add review mode with APPROVED/FEEDBACK output
3. **Extend `test-planner.md`** - Add review mode with COMPLETE/INCOMPLETE output

### Phase 2: Orchestrator Implementation

1. **Create `scripts/tasks/workflows/test_automation.py`**
   - Data classes
   - State handlers
   - Output parsers
   - Main workflow loop
   - CLI entry point

2. **Add pyproject.toml entry**

### Phase 3: Integration

1. **Write unit tests** for state handlers and parsers
2. **Write integration test** for full workflow
3. **Document usage** in `docs/testing/`

---

## Configuration

### Coverage Thresholds

From existing project configuration:
- **Unit/Component**: 80% line/branch per function
- **Integration/E2E**: 100% use-case coverage

### Iteration Limits

| Parameter | Default | Purpose |
|-----------|---------|---------|
| `max_iterations` | 5 | Maximum coverage→planning cycles |
| `max_debug_retries` | 3 | Maximum debug attempts per writing cycle |
| `max_strategy_reviews` | 3 | Maximum plan revisions before escalating |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Workflow completed successfully (COMPLETE state) |
| 1 | Workflow blocked or max iterations exceeded |

---

## Example Execution Trace

```
$ uv run test-workflow app/services/user_service.py app/api/endpoints/users.py

[init] → [strategy]: Starting strategy for 2 files
[strategy] → [planning]: Strategy generated
[planning] → [strategy_review]: Plan created
[strategy_review] → [planning]: Feedback received: Missing edge case for auth...
[planning] → [strategy_review]: Plan created
[strategy_review] → [writing]: Plan approved by strategy review
[writing] → [debugging]: Tests written: 3 files
[debugging] → [plan_review]: All tests fixed
[plan_review] → [coverage]: All planned tests implemented
[coverage] → [planning]: Coverage gaps: 2 functions below threshold
[planning] → [strategy_review]: Plan created
[strategy_review] → [writing]: Plan approved by strategy review
[writing] → [debugging]: Tests written: 1 files
[debugging] → [plan_review]: All tests fixed
[plan_review] → [coverage]: All planned tests implemented
[coverage] → [complete]: Coverage thresholds met

Workflow finished successfully.
```
