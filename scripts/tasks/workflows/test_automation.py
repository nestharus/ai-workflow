"""Test automation workflow for orchestrating test generation with coverage validation.

This module implements an outer-loop workflow that orchestrates test strategy creation,
planning, writing, debugging, and coverage validation. It implements iterative feedback
loops until coverage thresholds are met.

Workflow Summary:
    files -> strategy -> plan <-> strategy-review -> writer -> debugger
    -> plan-review -> coverage -> loop

State Machine:
    INIT -> STRATEGY -> PLANNING <-> STRATEGY_REVIEW -> WRITING -> DEBUGGING -> PLAN_REVIEW
    -> COVERAGE -> COMPLETE | STRATEGY_UPDATE -> PLANNING

All agent invocations use _run_tasks_agent() which calls agents from .tasks/agents/.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Type alias for workflow states
TestWorkflowState = Literal[
    "init",
    "strategy",
    "planning",
    "strategy_review",
    "writing",
    "debugging",
    "plan_review",
    "coverage",
    "strategy_update",
    "complete",
    "blocked",
]


@dataclass
class WorkflowContext:
    """Accumulated context through workflow execution.

    Attributes:
        target_files: List of file paths to generate tests for.
        strategy_document: Generated testing strategy, if any.
        test_plan: Current test plan document.
        written_tests: List of test file paths written.
        coverage_gaps: List of functions below coverage threshold.
        feedback_history: History of feedback from strategy reviews.
        iteration_count: Current iteration through coverage loop.
        max_iterations: Maximum coverage->planning loops.
        debug_retry_count: Current debug retry count.
        max_debug_retries: Maximum debugging retries per cycle.
    """

    target_files: list[str]
    strategy_document: str | None = None
    test_plan: str | None = None
    written_tests: list[str] | None = None
    coverage_gaps: list[dict[str, Any]] | None = None
    feedback_history: list[str] = field(default_factory=list)
    iteration_count: int = 0
    max_iterations: int = 5
    debug_retry_count: int = 0
    max_debug_retries: int = 3


@dataclass
class StateResult:
    """Result from a state handler.

    Attributes:
        next_state: The next state to transition to.
        context_updates: Dictionary of context fields to update.
        message: Human-readable message describing the result.
    """

    next_state: TestWorkflowState
    context_updates: dict[str, Any]
    message: str


@dataclass
class WorkflowResult:
    """Final workflow result.

    Attributes:
        success: Whether the workflow completed successfully.
        state: Final state of the workflow.
        message: Summary message.
        context: Final workflow context.
    """

    success: bool
    state: TestWorkflowState
    message: str
    context: WorkflowContext


@dataclass
class CoverageResult:
    """Coverage analysis result.

    Attributes:
        all_passing: Whether all coverage thresholds are met.
        gaps: List of functions below threshold.
        needs_strategy_revision: Whether a strategy revision is needed.
    """

    all_passing: bool
    gaps: list[dict[str, Any]] | None
    needs_strategy_revision: bool


# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------


def _run(
    command: list[str], *, cwd: Path = PROJECT_ROOT, check: bool = False
) -> subprocess.CompletedProcess[str]:
    """Execute a command and stream output to stdout/stderr.

    Args:
        command: Command and arguments to execute.
        cwd: Working directory for the command.
        check: Whether to raise on non-zero exit code.

    Returns:
        CompletedProcess result from subprocess execution.
    """
    result = subprocess.run(command, capture_output=True, text=True, cwd=cwd, check=check)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    return result


def _run_tasks_agent(agent_name: str, prompt: str) -> subprocess.CompletedProcess[str]:
    """Run a .tasks system agent with the specified prompt.

    Invokes tasks_agent_runner.py with the specified agent and prompt.

    Args:
        agent_name: Name of the agent to run (without .md extension).
        prompt: Prompt to pass to the agent.

    Returns:
        CompletedProcess result from subprocess execution.
    """
    runner = PROJECT_ROOT / "scripts" / "dev" / "tasks_agent_runner.py"
    command = [sys.executable, str(runner), "--agent", agent_name, "--prompt", prompt]
    return _run(command)


# -----------------------------------------------------------------------------
# Prompt formatters
# -----------------------------------------------------------------------------


def format_strategy_prompt(target_files: list[str]) -> str:
    """Format prompt for strategy generation.

    Args:
        target_files: List of target file paths.

    Returns:
        Formatted prompt string for the test-strategy agent.
    """
    files_list = "\n".join(f"- {f}" for f in target_files)
    return f"""Analyze the following files and produce a comprehensive testing strategy.

## Target Files
{files_list}

## Instructions
Follow your analysis workflow to produce a testing strategy document.
Output must start with STRATEGY: followed by the document, or BLOCKED: with a reason.
"""


def format_planning_prompt(
    strategy: str | None,
    target_files: list[str],
    feedback_history: list[str] | None = None,
    coverage_gaps: list[dict[str, Any]] | None = None,
) -> str:
    """Format prompt for test planning.

    Args:
        strategy: Testing strategy document.
        target_files: List of target file paths.
        feedback_history: List of previous feedback items.
        coverage_gaps: List of coverage gap dictionaries.

    Returns:
        Formatted prompt string for the test-planner agent.
    """
    files_list = "\n".join(f"- {f}" for f in target_files)
    prompt_parts = [
        "Create an actionable test plan based on the following strategy.",
        "",
        "## Testing Strategy",
        strategy or "(No strategy provided)",
        "",
        "## Target Files",
        files_list,
    ]

    if feedback_history:
        prompt_parts.extend(
            [
                "",
                "## Previous Feedback to Address",
                "\n".join(f"- {fb}" for fb in feedback_history),
            ]
        )

    if coverage_gaps:
        gaps_formatted = "\n".join(
            f"- {g.get('function', 'unknown')}: line={g.get('line_coverage', 0):.1f}%, "
            f"branch={g.get('branch_coverage', 0):.1f}%"
            for g in coverage_gaps
        )
        prompt_parts.extend(
            [
                "",
                "## Coverage Gaps to Address",
                gaps_formatted,
            ]
        )

    prompt_parts.extend(
        [
            "",
            "## Instructions",
            "Follow your workflow to produce a file-by-file test plan.",
            "Output must start with PLAN: followed by the document, or BLOCKED: with a reason.",
        ]
    )

    return "\n".join(prompt_parts)


def format_strategy_review_prompt(strategy: str | None, plan: str | None) -> str:
    """Format prompt for strategy review of a plan.

    Args:
        strategy: Original testing strategy document.
        plan: Test plan to review.

    Returns:
        Formatted prompt string for the test-strategy agent in review mode.
    """
    return f"""Mode: review

Review the following test plan against the original strategy.

## Original Strategy
{strategy or "(No strategy)"}

## Proposed Test Plan
{plan or "(No plan)"}

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
"""


def format_writing_prompt(plan: str | None, gaps: str | None = None) -> str:
    """Format prompt for test writing.

    Args:
        plan: Approved test plan document.
        gaps: Optional description of gaps to address.

    Returns:
        Formatted prompt string for the test-writer-nodebug agent.
    """
    prompt_parts = [
        "Write tests according to the following approved test plan.",
        "",
        "## Test Plan",
        plan or "(No plan provided)",
    ]

    if gaps:
        prompt_parts.extend(
            [
                "",
                "## Gaps to Address",
                gaps,
            ]
        )

    prompt_parts.extend(
        [
            "",
            "## Instructions",
            "1. Read the test plan thoroughly",
            "2. Update use-case registry if needed",
            "3. Examine existing test patterns",
            "4. Write all test files specified in the plan",
            "5. DO NOT run or debug tests - stop after writing",
            "",
            "Output:",
            "- WRITTEN: <summary of files written, test count>",
            "- BLOCKED: <reason if unable to write>",
        ]
    )

    return "\n".join(prompt_parts)


def format_debugging_prompt(plan: str | None, written_tests: list[str] | None) -> str:
    """Format prompt for test debugging.

    Args:
        plan: Test plan document.
        written_tests: List of written test file paths.

    Returns:
        Formatted prompt string for the test-debugger agent.
    """
    tests_list = ", ".join(written_tests or [])
    return f"""Task: Verify and fix the newly written tests.

Plan: {plan or "(No plan)"}

Failing Tests: [{tests_list}]

Instructions: Run all tests written in the plan. Debug and fix any failures.
Prefer fixing implementation bugs; only modify tests if they are incorrect.

Output one of:
- FIXED: All tests now pass
- PARTIAL: <remaining issues>
- BLOCKED: <reason>
"""


def format_plan_review_prompt(plan: str | None, written_tests: list[str] | None) -> str:
    """Format prompt for plan review of written tests.

    Args:
        plan: Original test plan document.
        written_tests: List of written test file paths.

    Returns:
        Formatted prompt string for the test-planner agent in review mode.
    """
    tests_formatted = "\n".join(f"- {t}" for t in (written_tests or []))
    return f"""Mode: review

Review the written tests against the original test plan.

## Original Plan
{plan or "(No plan)"}

## Written Test Files
{tests_formatted}

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
"""


def format_strategy_update_prompt(
    strategy: str | None,
    written_tests: list[str] | None,
    coverage_gaps: list[dict[str, Any]] | None,
) -> str:
    """Format prompt for strategy revision.

    Args:
        strategy: Original strategy document.
        written_tests: List of written test file paths.
        coverage_gaps: List of coverage gap dictionaries.

    Returns:
        Formatted prompt string for the test-strategy agent in revise mode.
    """
    tests_formatted = "\n".join(f"- {t}" for t in (written_tests or []))
    gaps_formatted = "\n".join(
        f"- {g.get('function', 'unknown')}: line={g.get('line_coverage', 0):.1f}%, "
        f"branch={g.get('branch_coverage', 0):.1f}%"
        for g in (coverage_gaps or [])
    )

    return f"""Mode: revise

Revise the testing strategy based on coverage results.

## Original Strategy
{strategy or "(No strategy)"}

## Written Tests
{tests_formatted}

## Coverage Gaps
{gaps_formatted}

## Why Revision Needed
Coverage gaps persist after multiple planning iterations. Strategy may need structural changes.

## Instructions
Update the strategy to address structural gaps that prevented coverage:
1. Identify patterns not covered by original strategy
2. Recommend additional testing approaches
3. Adjust tier assignments if needed
4. Add missing edge case categories

Output must start with STRATEGY: followed by the revised document, or BLOCKED: with a reason.
"""


# -----------------------------------------------------------------------------
# Output parsers
# -----------------------------------------------------------------------------


def parse_strategy_output(output: str) -> tuple[str, str]:
    """Parse test-strategy agent output.

    Args:
        output: Stdout from test-strategy agent.

    Returns:
        Tuple of (status, content) where status is "strategy" or "blocked".
    """
    blocked_match = re.search(r"BLOCKED:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if blocked_match:
        return "blocked", blocked_match.group(1).strip()

    strategy_match = re.search(r"STRATEGY:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if strategy_match:
        return "strategy", strategy_match.group(1).strip()

    return "blocked", "Unrecognized test-strategy response"


def parse_planner_output(output: str) -> tuple[str, str]:
    """Parse test-planner agent output.

    Args:
        output: Stdout from test-planner agent.

    Returns:
        Tuple of (status, content) where status is "plan" or "blocked".
    """
    blocked_match = re.search(r"BLOCKED:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if blocked_match:
        return "blocked", blocked_match.group(1).strip()

    plan_match = re.search(r"PLAN:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if plan_match:
        return "plan", plan_match.group(1).strip()

    return "blocked", "Unrecognized test-planner response"


def parse_strategy_review_output(output: str) -> tuple[str, str]:
    """Parse test-strategy agent review mode output.

    Args:
        output: Stdout from test-strategy agent in review mode.

    Returns:
        Tuple of (status, content) where status is "approved", "feedback", or "blocked".
    """
    if re.search(r"\bAPPROVED\b", output, re.IGNORECASE):
        return "approved", ""

    feedback_match = re.search(r"FEEDBACK:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if feedback_match:
        return "feedback", feedback_match.group(1).strip()

    blocked_match = re.search(r"BLOCKED:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if blocked_match:
        return "blocked", blocked_match.group(1).strip()

    return "blocked", "Unrecognized strategy review response"


def parse_writer_output(output: str) -> tuple[str, str]:
    """Parse test-writer-nodebug agent output.

    Args:
        output: Stdout from test-writer-nodebug agent.

    Returns:
        Tuple of (status, content) where status is "written" or "blocked".
    """
    written_match = re.search(r"WRITTEN:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if written_match:
        return "written", written_match.group(1).strip()

    blocked_match = re.search(r"BLOCKED:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if blocked_match:
        return "blocked", blocked_match.group(1).strip()

    return "blocked", "Unrecognized test-writer response"


def parse_debugger_output(output: str) -> tuple[str, str]:
    """Parse test-debugger agent output.

    Args:
        output: Stdout from test-debugger agent.

    Returns:
        Tuple of (status, message) where status is "fixed", "partial", or "blocked".
    """
    fixed_match = re.search(r"FIXED:\s*(.+)", output, re.IGNORECASE)
    if fixed_match:
        return "fixed", fixed_match.group(1).strip()

    partial_match = re.search(r"PARTIAL:\s*(.+)", output, re.IGNORECASE)
    if partial_match:
        return "partial", partial_match.group(1).strip()

    blocked_match = re.search(r"BLOCKED:\s*(.+)", output, re.IGNORECASE)
    if blocked_match:
        return "blocked", blocked_match.group(1).strip()

    return "blocked", "Unrecognized test-debugger response"


def parse_plan_review_output(output: str) -> tuple[str, str]:
    """Parse test-planner agent review mode output.

    Args:
        output: Stdout from test-planner agent in review mode.

    Returns:
        Tuple of (status, content) where status is "complete", "incomplete", or "blocked".
    """
    complete_match = re.search(r"COMPLETE:\s*(.+)", output, re.IGNORECASE)
    if complete_match:
        return "complete", complete_match.group(1).strip()

    incomplete_match = re.search(r"INCOMPLETE:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if incomplete_match:
        return "incomplete", incomplete_match.group(1).strip()

    blocked_match = re.search(r"BLOCKED:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if blocked_match:
        return "blocked", blocked_match.group(1).strip()

    return "blocked", "Unrecognized plan review response"


def extract_written_files(writer_output: str) -> list[str]:
    """Extract file paths from writer output.

    Args:
        writer_output: The content portion of WRITTEN output.

    Returns:
        List of file paths mentioned in the output.
    """
    # Look for patterns like: tests/unit/test_foo.py or - tests/integration/test_bar.py
    file_pattern = re.compile(r"[\w/\\._-]*tests?/[\w/\\._-]+\.py", re.IGNORECASE)
    matches = file_pattern.findall(writer_output)
    # Clean up and deduplicate
    files = list(dict.fromkeys(m.strip("- ") for m in matches))
    return files if files else ["(unknown test files)"]


def parse_coverage_results(
    summary_result: subprocess.CompletedProcess[str],
    functions_result: subprocess.CompletedProcess[str],
) -> CoverageResult:
    """Parse coverage command outputs to determine gaps.

    Args:
        summary_result: Result from coverage-summary command.
        functions_result: Result from coverage-functions command.

    Returns:
        CoverageResult with gap analysis.
    """
    try:
        summary_data = json.loads(summary_result.stdout) if summary_result.stdout else {}
        functions_data = json.loads(functions_result.stdout) if functions_result.stdout else {}
    except json.JSONDecodeError:
        # If JSON parsing fails, assume gaps exist
        return CoverageResult(all_passing=False, gaps=None, needs_strategy_revision=False)

    # Check tier summaries for pass/fail
    tier_summaries = summary_data.get("tier_summaries", {})
    all_tiers_pass = all(tier.get("tier_pass", False) for tier in tier_summaries.values())

    # Check for functions below threshold
    functions_below = functions_data.get("filtered_totals", {}).get("functions_below_threshold", 0)

    if all_tiers_pass and functions_below == 0:
        return CoverageResult(all_passing=True, gaps=None, needs_strategy_revision=False)

    # Extract gap details
    gaps: list[dict[str, Any]] = []
    for file_data in functions_data.get("files", {}).values():
        for func_data in file_data.get("functions", []):
            if not func_data.get("meets_threshold", True):
                gaps.append(
                    {
                        "function": func_data.get("name", "unknown"),
                        "file": file_data.get("path", "unknown"),
                        "line_coverage": func_data.get("line_coverage", 0),
                        "branch_coverage": func_data.get("branch_coverage", 0),
                    }
                )

    # Determine if strategy revision is needed (heuristic: many gaps or repeated failures)
    needs_strategy = len(gaps) > 10  # Simple heuristic

    return CoverageResult(all_passing=False, gaps=gaps, needs_strategy_revision=needs_strategy)


# -----------------------------------------------------------------------------
# State handlers
# -----------------------------------------------------------------------------


def handle_init(ctx: WorkflowContext) -> StateResult:
    """Entry point - validate inputs and proceed to strategy.

    Args:
        ctx: Current workflow context.

    Returns:
        StateResult transitioning to strategy or blocked state.
    """
    if not ctx.target_files:
        return StateResult("blocked", {}, "No target files provided")
    return StateResult("strategy", {}, f"Starting strategy for {len(ctx.target_files)} files")


def handle_strategy(ctx: WorkflowContext) -> StateResult:
    """Generate testing strategy via test-strategy agent.

    Args:
        ctx: Current workflow context.

    Returns:
        StateResult transitioning to planning or blocked state.
    """
    prompt = format_strategy_prompt(ctx.target_files)
    result = _run_tasks_agent("test-strategy", prompt)

    status, content = parse_strategy_output(result.stdout or "")

    if status == "blocked":
        return StateResult("blocked", {}, content)

    return StateResult("planning", {"strategy_document": content}, "Strategy generated")


def handle_planning(ctx: WorkflowContext) -> StateResult:
    """Create test plan via test-planner agent.

    Args:
        ctx: Current workflow context.

    Returns:
        StateResult transitioning to strategy_review or blocked state.
    """
    prompt = format_planning_prompt(
        ctx.strategy_document, ctx.target_files, ctx.feedback_history, ctx.coverage_gaps
    )
    result = _run_tasks_agent("test-planner", prompt)

    status, content = parse_planner_output(result.stdout or "")

    if status == "blocked":
        return StateResult("blocked", {}, content)

    return StateResult("strategy_review", {"test_plan": content}, "Plan created")


def handle_strategy_review(ctx: WorkflowContext) -> StateResult:
    """Review plan against strategy via test-strategy agent (review mode).

    Args:
        ctx: Current workflow context.

    Returns:
        StateResult transitioning to writing, planning (with feedback), or blocked state.
    """
    prompt = format_strategy_review_prompt(ctx.strategy_document, ctx.test_plan)
    result = _run_tasks_agent("test-strategy", prompt)

    status, content = parse_strategy_review_output(result.stdout or "")

    if status == "approved":
        return StateResult("writing", {}, "Plan approved by strategy review")

    if status == "feedback":
        feedback_history = [*ctx.feedback_history, content]
        return StateResult(
            "planning",
            {"feedback_history": feedback_history},
            f"Feedback received: {content[:100]}...",
        )

    return StateResult("blocked", {}, content)


def handle_writing(ctx: WorkflowContext) -> StateResult:
    """Write tests via test-writer-nodebug agent.

    Args:
        ctx: Current workflow context.

    Returns:
        StateResult transitioning to debugging or blocked state.
    """
    prompt = format_writing_prompt(ctx.test_plan)
    result = _run_tasks_agent("test-writer-nodebug", prompt)

    status, content = parse_writer_output(result.stdout or "")

    if status == "blocked":
        return StateResult("blocked", {}, content)

    written_files = extract_written_files(content)
    return StateResult(
        "debugging", {"written_tests": written_files}, f"Tests written: {len(written_files)} files"
    )


def handle_debugging(ctx: WorkflowContext) -> StateResult:
    """Debug tests via test-debugger agent.

    Args:
        ctx: Current workflow context.

    Returns:
        StateResult transitioning to plan_review, debugging (retry), or blocked state.
    """
    prompt = format_debugging_prompt(ctx.test_plan, ctx.written_tests)
    result = _run_tasks_agent("test-debugger", prompt)

    status, message = parse_debugger_output(result.stdout or "")

    if status == "fixed":
        return StateResult("plan_review", {"debug_retry_count": 0}, "All tests fixed")

    if status == "partial":
        if ctx.debug_retry_count >= ctx.max_debug_retries:
            return StateResult("blocked", {}, f"Max debug retries exceeded: {message}")
        return StateResult(
            "debugging",
            {"debug_retry_count": ctx.debug_retry_count + 1},
            f"Partial fix, retrying: {message}",
        )

    return StateResult("blocked", {}, message)


def handle_plan_review(ctx: WorkflowContext) -> StateResult:
    """Review written tests via test-planner agent (review mode).

    Args:
        ctx: Current workflow context.

    Returns:
        StateResult transitioning to coverage, writing (with gaps), or blocked state.
    """
    prompt = format_plan_review_prompt(ctx.test_plan, ctx.written_tests)
    result = _run_tasks_agent("test-planner", prompt)

    status, content = parse_plan_review_output(result.stdout or "")

    if status == "complete":
        return StateResult("coverage", {}, "All planned tests implemented")

    if status == "incomplete":
        return StateResult("writing", {}, f"Gaps found: {content}")

    return StateResult("blocked", {}, content)


def handle_coverage(ctx: WorkflowContext) -> StateResult:
    """Run coverage and analyze gaps.

    Args:
        ctx: Current workflow context.

    Returns:
        StateResult transitioning to complete, planning (with gaps), strategy_update, or blocked.
    """
    # Run coverage tools
    _run(["uv", "run", "test-coverage"])
    summary_result = _run(["uv", "run", "coverage-summary", "--json"])
    functions_result = _run(["uv", "run", "coverage-functions", "--json"])

    coverage_result = parse_coverage_results(summary_result, functions_result)

    if coverage_result.all_passing:
        return StateResult("complete", {}, "Coverage thresholds met")

    new_iteration_count = ctx.iteration_count + 1
    if new_iteration_count >= ctx.max_iterations:
        return StateResult("blocked", {}, f"Max iterations ({ctx.max_iterations}) exceeded")

    if coverage_result.needs_strategy_revision:
        return StateResult(
            "strategy_update",
            {"coverage_gaps": coverage_result.gaps, "iteration_count": new_iteration_count},
            "Strategy revision needed",
        )

    gap_count = len(coverage_result.gaps) if coverage_result.gaps else 0
    return StateResult(
        "planning",
        {"coverage_gaps": coverage_result.gaps, "iteration_count": new_iteration_count},
        f"Coverage gaps: {gap_count} functions below threshold",
    )


def handle_strategy_update(ctx: WorkflowContext) -> StateResult:
    """Request strategy revision via test-strategy agent.

    Args:
        ctx: Current workflow context.

    Returns:
        StateResult transitioning to planning or blocked state.
    """
    prompt = format_strategy_update_prompt(
        ctx.strategy_document, ctx.written_tests, ctx.coverage_gaps
    )
    result = _run_tasks_agent("test-strategy", prompt)

    status, content = parse_strategy_output(result.stdout or "")

    if status == "blocked":
        return StateResult("blocked", {}, content)

    return StateResult(
        "planning",
        {"strategy_document": content, "feedback_history": []},
        "Strategy revised",
    )


# -----------------------------------------------------------------------------
# Main workflow
# -----------------------------------------------------------------------------


def run_test_automation_workflow(
    target_files: list[str],
    *,
    max_iterations: int = 5,
    max_debug_retries: int = 3,
) -> WorkflowResult:
    """Execute the test automation workflow.

    This workflow:
    1. Generates a testing strategy for the target files
    2. Creates a test plan from the strategy
    3. Reviews the plan against the strategy
    4. Writes tests according to the plan
    5. Debugs any failing tests
    6. Reviews written tests against the plan
    7. Validates coverage and loops if needed

    Args:
        target_files: List of file paths to generate tests for.
        max_iterations: Maximum coverage->planning loops.
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

    state_handlers: dict[str, Any] = {
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

        print(f"[{state}] -> [{result.next_state}]: {result.message}")
        state = result.next_state

    return WorkflowResult(
        success=(state == "complete"),
        state=state,
        message=f"Workflow finished in state: {state}",
        context=ctx,
    )


# -----------------------------------------------------------------------------
# CLI entry point
# -----------------------------------------------------------------------------


def main() -> int:
    """CLI entry point for test automation workflow.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    parser = argparse.ArgumentParser(
        description="Run test automation workflow for generating and validating tests."
    )
    parser.add_argument("files", nargs="+", help="Target files to generate tests for")
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        help="Maximum coverage->planning loop iterations (default: 5)",
    )
    parser.add_argument(
        "--max-debug-retries",
        type=int,
        default=3,
        help="Maximum debugging retries per cycle (default: 3)",
    )
    args = parser.parse_args()

    result = run_test_automation_workflow(
        args.files,
        max_iterations=args.max_iterations,
        max_debug_retries=args.max_debug_retries,
    )

    print(f"\n{result.message}")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
