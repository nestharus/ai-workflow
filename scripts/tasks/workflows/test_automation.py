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
import functools
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypedDict

import jsonschema
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCHEMAS_DIR = PROJECT_ROOT / "docs" / "schemas"


# -----------------------------------------------------------------------------
# Schema loading with caching
# -----------------------------------------------------------------------------


@functools.lru_cache(maxsize=4)
def _load_schema(schema_name: str) -> dict[str, Any]:
    """Load and cache a JSON schema file.

    Args:
        schema_name: Name of the schema file (without path).

    Returns:
        Parsed JSON schema as a dictionary.

    Raises:
        FileNotFoundError: If schema file doesn't exist.
        json.JSONDecodeError: If schema is invalid JSON.
    """
    schema_path = SCHEMAS_DIR / schema_name
    with schema_path.open() as f:
        result: dict[str, Any] = json.load(f)
        return result


def _get_output_schema_validator() -> jsonschema.Draft7Validator:
    """Get a cached Draft7Validator for the output schema.

    Returns:
        Configured Draft7Validator instance.
    """
    schema = _load_schema("test-strategy-output.schema.json")
    return jsonschema.Draft7Validator(schema)


def _get_review_schema_validator() -> jsonschema.Draft7Validator:
    """Get a cached Draft7Validator for the review schema.

    Returns:
        Configured Draft7Validator instance.
    """
    schema = _load_schema("test-strategy-review.schema.json")
    return jsonschema.Draft7Validator(schema)


def _get_plan_review_schema_validator() -> jsonschema.Draft7Validator:
    """Get a cached Draft7Validator for the plan review schema.

    Returns:
        Configured Draft7Validator instance.
    """
    schema = _load_schema("test-planner-review.schema.json")
    return jsonschema.Draft7Validator(schema)


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
        strategy_structured: Structured parsed strategy data (if available).
        test_plan: Current test plan document.
        written_tests: List of test file paths written.
        coverage_gaps: List of functions below coverage threshold.
        feedback_history: History of feedback from strategy reviews.
        iteration_count: Current iteration through coverage loop.
        max_iterations: Maximum coverage->planning loops.
        debug_retry_count: Current debug retry count.
        max_debug_retries: Maximum debugging retries per cycle.
        strategy_review_count: Current strategy review count within planning cycle.
        max_strategy_reviews: Maximum strategy reviews before escalating.
        git_diff: Git diff output for target files.
        existing_tests: List of existing test file paths for pattern reference.
        analysis_context: Optional context description of what changed.
    """

    target_files: list[str]
    strategy_document: str | None = None
    strategy_structured: dict[str, Any] | None = None
    test_plan: str | None = None
    written_tests: list[str] | None = None
    coverage_gaps: list[dict[str, Any]] | None = None
    feedback_history: list[str] = field(default_factory=list)
    iteration_count: int = 0
    max_iterations: int = 5
    debug_retry_count: int = 0
    max_debug_retries: int = 3
    strategy_review_count: int = 0
    max_strategy_reviews: int = 3
    git_diff: str | None = None
    existing_tests: list[str] | None = None
    analysis_context: str | None = None


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
# TypedDict definitions for structured output parsing
# -----------------------------------------------------------------------------

# Type aliases for test tiers and coverage types
TestTier = Literal["unit", "component", "integration", "e2e"]
CoverageType = Literal["line_branch", "use_case"]
IssueSeverity = Literal["high", "medium", "low"]
IssueCategory = Literal[
    "missing_tier",
    "wrong_coverage_type",
    "missing_edge_case",
    "pattern_mismatch",
    "insufficient_coverage",
    "wrong_tier_assignment",
    "missing_use_case",
    "incomplete_mocking",
    "missing_fixture",
]


class FunctionTestRequirement(TypedDict, total=False):
    """Test requirements for a specific function."""

    name: str
    test_type: CoverageType
    priority: IssueSeverity
    notes: str


class TierAssignment(TypedDict, total=False):
    """Test tier assignment for a specific source file."""

    file: str
    tier: TestTier
    coverage_type: CoverageType
    coverage_target: float
    rationale: str
    functions: list[FunctionTestRequirement]


class Fixture(TypedDict, total=False):
    """A pytest fixture required for testing."""

    name: str
    exists: bool
    path: str
    creation_notes: str


class MockingStrategy(TypedDict, total=False):
    """Strategy for mocking an external dependency."""

    target: str
    approach: str
    notes: str


class AssertionPattern(TypedDict, total=False):
    """Recommended assertion pattern for test validation."""

    pattern: str
    description: str


class TestingPatterns(TypedDict, total=False):
    """Recommended testing patterns, fixtures, mocking strategies."""

    fixtures_required: list[Fixture]
    mocking_strategies: list[MockingStrategy]
    assertion_patterns: list[AssertionPattern]


class UseCase(TypedDict, total=False):
    """A new use case to be implemented for integration/e2e testing."""

    id: str
    endpoint: str
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
    description: str
    test_tier: TestTier


class ExistingUseCase(TypedDict, total=False):
    """Reference to an existing use case that applies to the target files."""

    id: str
    notes: str


class UseCases(TypedDict, total=False):
    """Use case definitions for integration and e2e tests."""

    new: list[UseCase]
    existing_applicable: list[ExistingUseCase]


class EdgeCase(TypedDict, total=False):
    """An edge case or error scenario requiring test coverage."""

    scenario: str
    severity: IssueSeverity
    test_approach: str


class TestFile(TypedDict, total=False):
    """A test file and its metadata."""

    path: str
    operation: Literal["NEW", "MODIFY", "DELETE"]
    tier: TestTier


class TestFileMapping(TypedDict, total=False):
    """Mapping between a source file and its test files."""

    source: str
    tests: list[TestFile]


class StrategyOutputStructured(TypedDict, total=False):
    """Structured output from test-strategy agent (generate/revise modes).

    This follows the test-strategy-output.schema.json format.
    All fields are optional to support graceful degradation when agent
    outputs unstructured text.
    """

    summary: str
    tier_assignments: list[TierAssignment]
    testing_patterns: TestingPatterns
    use_cases: UseCases
    edge_cases: list[EdgeCase]
    test_file_mapping: list[TestFileMapping]
    guidance_for_planner: list[str]


class ReviewIssue(TypedDict, total=False):
    """An issue identified during review."""

    category: IssueCategory
    description: str
    strategy_reference: str
    severity: IssueSeverity


class StrategyReviewOutputStructured(TypedDict, total=False):
    """Structured output from test-strategy agent (review mode).

    This follows the test-strategy-review.schema.json format.
    All fields are optional except status.
    """

    status: Literal["APPROVED", "FEEDBACK", "BLOCKED"]
    issues: list[ReviewIssue]
    reason: str


# Type alias for plan review gap categories
PlanReviewGapCategory = Literal[
    "missing_test",
    "missing_assertion",
    "missing_usecase_marker",
    "wrong_tier",
    "missing_edge_case",
    "incomplete_setup",
    "missing_fixture",
]


class PlanReviewGap(TypedDict, total=False):
    """A gap identified during plan review."""

    category: PlanReviewGapCategory
    description: str
    plan_reference: str
    test_file: str
    severity: IssueSeverity


class PlanReviewOutputStructured(TypedDict, total=False):
    """Structured output from test-planner agent (review mode).

    This follows the test-planner-review.schema.json format.
    All fields are optional except status.
    """

    status: Literal["COMPLETE", "INCOMPLETE", "BLOCKED"]
    gaps: list[PlanReviewGap]
    reason: str
    summary: str


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


StrategyMode = Literal["generate", "review", "revise"]


def format_strategy_prompt(
    target_files: list[str],
    analysis_context: str | None = None,
    existing_tests: list[str] | None = None,
    change_type: str | None = None,
    functions_changed: list[str] | None = None,
    *,
    mode: StrategyMode = "generate",
    strategy_document: str | None = None,
    proposed_plan: str | None = None,
    coverage_gaps: list[dict[str, Any]] | None = None,
) -> str:
    """Format prompt for strategy generation, review, or revision.

    Args:
        target_files: List of target file paths.
        analysis_context: Optional description of what changed.
        existing_tests: Optional list of existing test file paths.
        change_type: Optional change type (NEW, MODIFY, DELETE, RENAME).
        functions_changed: Optional list of function names that changed (for MODIFY).
        mode: Operation mode - "generate", "review", or "revise".
        strategy_document: Original strategy document (required for review mode).
        proposed_plan: Plan to review against strategy (required for review mode).
        coverage_gaps: Coverage gaps to address (required for revise mode).

    Returns:
        Formatted prompt string for the test-strategy agent.
    """
    # Build structured input matching the schema
    input_data: dict[str, Any] = {"mode": mode, "target_files": []}

    # Add target files with optional metadata
    for file_path in target_files:
        file_entry: dict[str, Any] = {"path": file_path}
        if change_type:
            file_entry["change_type"] = change_type
        if functions_changed:
            file_entry["functions_changed"] = functions_changed
        input_data["target_files"].append(file_entry)

    # Add context if available (for generate mode)
    if mode == "generate" and (analysis_context or existing_tests):
        context: dict[str, Any] = {}
        if analysis_context:
            context["analysis_description"] = analysis_context
        if existing_tests:
            context["existing_tests"] = existing_tests
        input_data["context"] = context

    # Add review mode fields
    if mode == "review":
        input_data["strategy_document"] = strategy_document or "(No strategy)"
        input_data["proposed_plan"] = proposed_plan or "(No plan)"

    # Add revise mode fields
    if mode == "revise" and coverage_gaps:
        input_data["coverage_gaps"] = coverage_gaps

    # Format YAML representation
    yaml_input = yaml.dump(input_data, default_flow_style=False, sort_keys=False)

    # Build prompt based on mode
    files_list = "\n".join(f"- {f}" for f in target_files)

    if mode == "generate":
        prompt_parts = [
            "Analyze the following files and produce a comprehensive testing strategy.",
            "",
            "## Structured Input",
            "```yaml",
            yaml_input.rstrip(),
            "```",
            "",
            "## Target Files",
            files_list,
        ]

        if analysis_context:
            prompt_parts.extend(["", "## Context", analysis_context])

        if existing_tests:
            tests_list = "\n".join(f"- {t}" for t in existing_tests)
            prompt_parts.extend(["", "## Existing Tests (for pattern reference)", tests_list])

        prompt_parts.extend(
            [
                "",
                "## Instructions",
                "Follow your analysis workflow to produce a testing strategy document.",
                "The structured input above follows the test-strategy-input.schema.json format.",
                "Output must start with STRATEGY: followed by the document, "
                "or BLOCKED: with a reason.",
            ]
        )

    elif mode == "review":
        prompt_parts = [
            "Review the following test plan against the original strategy.",
            "",
            "## Structured Input",
            "```yaml",
            yaml_input.rstrip(),
            "```",
            "",
            "## Original Strategy",
            strategy_document or "(No strategy)",
            "",
            "## Proposed Test Plan",
            proposed_plan or "(No plan)",
            "",
            "## Instructions",
            "Verify the plan adequately covers the strategy requirements:",
            "1. Tier assignments match strategy recommendations",
            "2. Use-case coverage goals are addressed",
            "3. Testing patterns align with strategy guidance",
            "4. Edge cases from strategy are planned",
            "",
            "The structured input above follows the test-strategy-input.schema.json format "
            "(review mode).",
            "Output one of:",
            "- APPROVED (if plan satisfies strategy)",
            "- FEEDBACK: <specific issues to address>",
            "- BLOCKED: <reason review cannot proceed>",
        ]

    else:  # revise mode
        gaps_formatted = "\n".join(
            f"- {g.get('function', 'unknown')}: line={g.get('line_coverage', 0):.1f}%, "
            f"branch={g.get('branch_coverage', 0):.1f}%"
            for g in (coverage_gaps or [])
        )
        prompt_parts = [
            "Revise the testing strategy based on coverage results.",
            "",
            "## Structured Input",
            "```yaml",
            yaml_input.rstrip(),
            "```",
            "",
            "## Coverage Gaps",
            gaps_formatted or "(No gaps specified)",
            "",
            "## Why Revision Needed",
            "Coverage gaps persist after multiple planning iterations. "
            "Strategy may need structural changes.",
            "",
            "## Instructions",
            "Update the strategy to address structural gaps that prevented coverage:",
            "1. Identify patterns not covered by original strategy",
            "2. Recommend additional testing approaches",
            "3. Adjust tier assignments if needed",
            "4. Add missing edge case categories",
            "",
            "The structured input above follows the test-strategy-input.schema.json format "
            "(revise mode).",
            "Output must start with STRATEGY: followed by the revised document, "
            "or BLOCKED: with a reason.",
        ]

    return "\n".join(prompt_parts)


def format_planning_prompt(
    strategy: str | None,
    target_files: list[str],
    feedback_history: list[str] | None = None,
    coverage_gaps: list[dict[str, Any]] | None = None,
    git_diff: str | None = None,
    existing_tests: list[str] | None = None,
    strategy_structured: dict[str, Any] | None = None,
) -> str:
    """Format prompt for test planning.

    Args:
        strategy: Testing strategy document (raw string).
        target_files: List of target file paths.
        feedback_history: List of previous feedback items.
        coverage_gaps: List of coverage gap dictionaries.
        git_diff: Git diff output for target files.
        existing_tests: List of existing test file paths.
        strategy_structured: Structured parsed strategy data (if available).

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

    # Add structured strategy sections if available
    if strategy_structured:
        # Include tier assignments
        if "tier_assignments" in strategy_structured:
            tier_assignments = strategy_structured["tier_assignments"]
            if tier_assignments:
                prompt_parts.extend(["", "## Tier Assignments (from Strategy)"])
                for assignment in tier_assignments:
                    file_name = assignment.get("file", "unknown")
                    tier = assignment.get("tier", "unknown")
                    coverage_type = assignment.get("coverage_type", "unknown")
                    target = assignment.get("coverage_target", "unknown")
                    prompt_parts.append(
                        f"- {file_name}: {tier} tier, {coverage_type}, target={target}%"
                    )
                    # Include function-level details if available
                    functions = assignment.get("functions", [])
                    for func in functions:
                        func_name = func.get("name", "unknown")
                        priority = func.get("priority", "medium")
                        test_type = func.get("test_type", "unknown")
                        prompt_parts.append(f"  - {func_name}: {test_type} ({priority} priority)")

        # Include test file mapping as a guide
        if "test_file_mapping" in strategy_structured:
            test_file_mapping = strategy_structured["test_file_mapping"]
            if test_file_mapping:
                prompt_parts.extend(["", "## Test File Mapping (from Strategy)"])
                for mapping in test_file_mapping:
                    source = mapping.get("source", "unknown")
                    prompt_parts.append(f"- Source: {source}")
                    tests = mapping.get("tests", [])
                    for test in tests:
                        test_path = test.get("path", "unknown")
                        operation = test.get("operation", "unknown")
                        tier = test.get("tier", "unknown")
                        prompt_parts.append(f"  - {test_path} ({operation}, {tier})")

        # Include use cases for registry updates
        if "use_cases" in strategy_structured:
            use_cases = strategy_structured["use_cases"]
            if use_cases and "new" in use_cases:
                new_use_cases = use_cases["new"]
                if new_use_cases:
                    prompt_parts.extend(
                        ["", "## New Use Cases (update use-case registry with these)"]
                    )
                    for uc in new_use_cases:
                        uc_id = uc.get("id", "unknown")
                        endpoint = uc.get("endpoint", "unknown")
                        method = uc.get("method", "unknown")
                        description = uc.get("description", "unknown")
                        test_tier = uc.get("test_tier", "unknown")
                        prompt_parts.append(
                            f"- {uc_id}: {method} {endpoint} - {description} ({test_tier})"
                        )

        # Include testing patterns for fixture and mocking guidance
        if "testing_patterns" in strategy_structured:
            patterns = strategy_structured["testing_patterns"]

            # Fixtures
            if "fixtures_required" in patterns:
                fixtures = patterns["fixtures_required"]
                if fixtures:
                    prompt_parts.extend(["", "## Fixtures (from Strategy)"])
                    for fixture in fixtures:
                        name = fixture.get("name", "unknown")
                        exists = fixture.get("exists", False)
                        if exists:
                            path = fixture.get("path", "unknown")
                            prompt_parts.append(f"- {name} (existing at {path})")
                        else:
                            notes = fixture.get("creation_notes", "")
                            prompt_parts.append(f"- {name} (create: {notes})")

            # Mocking strategies
            if "mocking_strategies" in patterns:
                mocking = patterns["mocking_strategies"]
                if mocking:
                    prompt_parts.extend(["", "## Mocking Strategies (from Strategy)"])
                    for mock in mocking:
                        target = mock.get("target", "unknown")
                        approach = mock.get("approach", "unknown")
                        notes = mock.get("notes", "")
                        prompt_parts.append(f"- {target}: {approach} - {notes}")

        # Include guidance for planner as explicit instructions
        if "guidance_for_planner" in strategy_structured:
            guidance = strategy_structured["guidance_for_planner"]
            if guidance:
                prompt_parts.extend(["", "## Guidance from Strategy (follow these instructions)"])
                for item in guidance:
                    prompt_parts.append(f"- {item}")

    if git_diff:
        prompt_parts.extend(
            [
                "",
                "## Git Diff",
                git_diff,
            ]
        )

    if existing_tests:
        tests_list = "\n".join(f"- {t}" for t in existing_tests)
        prompt_parts.extend(
            [
                "",
                "## Existing Tests",
                tests_list,
            ]
        )

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


def format_strategy_review_prompt(
    strategy: str | None,
    plan: str | None,
    target_files: list[str] | None = None,
) -> str:
    """Format prompt for strategy review of a plan.

    Args:
        strategy: Original testing strategy document.
        plan: Test plan to review.
        target_files: Optional list of target file paths for context.

    Returns:
        Formatted prompt string for the test-strategy agent in review mode.
    """
    # Build structured input matching the review mode schema
    input_data: dict[str, Any] = {
        "mode": "review",
        "target_files": [{"path": f} for f in (target_files or ["(unknown)"])],
        "strategy_document": strategy or "(No strategy)",
        "proposed_plan": plan or "(No plan)",
    }

    # Format YAML representation
    yaml_input = yaml.dump(input_data, default_flow_style=False, sort_keys=False)

    return f"""Mode: review

Review the following test plan against the original strategy.

## Structured Input
```yaml
{yaml_input.rstrip()}
```

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

The structured input above follows the test-strategy-input.schema.json format (review mode).
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
    target_files: list[str] | None = None,
) -> str:
    """Format prompt for strategy revision.

    Args:
        strategy: Original strategy document.
        written_tests: List of written test file paths.
        coverage_gaps: List of coverage gap dictionaries.
        target_files: Optional list of target file paths for context.

    Returns:
        Formatted prompt string for the test-strategy agent in revise mode.
    """
    # Build structured input matching the revise mode schema
    # Extract unique files from coverage gaps or use target_files
    files_from_gaps: set[str] = set()
    if coverage_gaps:
        for gap in coverage_gaps:
            if "file" in gap:
                files_from_gaps.add(gap["file"])

    files_list = list(files_from_gaps) if files_from_gaps else (target_files or ["(unknown)"])

    input_data: dict[str, Any] = {
        "mode": "revise",
        "target_files": [{"path": f} for f in files_list],
        "coverage_gaps": coverage_gaps or [],
    }

    # Format YAML representation
    yaml_input = yaml.dump(input_data, default_flow_style=False, sort_keys=False)

    tests_formatted = "\n".join(f"- {t}" for t in (written_tests or []))
    gaps_formatted = "\n".join(
        f"- {g.get('function', 'unknown')}: line={g.get('line_coverage', 0):.1f}%, "
        f"branch={g.get('branch_coverage', 0):.1f}%"
        for g in (coverage_gaps or [])
    )

    return f"""Mode: revise

Revise the testing strategy based on coverage results.

## Structured Input
```yaml
{yaml_input.rstrip()}
```

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

The structured input above follows the test-strategy-input.schema.json format (revise mode).
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


def parse_strategy_output_structured(output: str) -> StrategyOutputStructured:
    r"""Parse test-strategy agent output and extract structured YAML.

    Extracts the YAML block after the STRATEGY: marker and parses it into
    a structured dictionary. Validates against the JSON Schema and implements
    graceful fallback if YAML parsing or validation fails.

    Args:
        output: Stdout from test-strategy agent.

    Returns:
        StrategyOutputStructured dict with parsed fields. If parsing or
        validation fails, returns a dict with only the 'summary' field
        containing the raw text and error details.

    Examples:
        >>> output = "STRATEGY:\\n```yaml\\nsummary: Test plan\\n```"
        >>> result = parse_strategy_output_structured(output)
        >>> result['summary']
        'Test plan'
    """
    # First check if blocked
    blocked_match = re.search(r"BLOCKED:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if blocked_match:
        # For blocked output, return minimal structure with summary
        return StrategyOutputStructured(summary=f"BLOCKED: {blocked_match.group(1).strip()}")

    # Extract content after STRATEGY: marker
    strategy_match = re.search(r"STRATEGY:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if not strategy_match:
        # No STRATEGY marker found - return raw output as summary
        return StrategyOutputStructured(summary=output.strip() or "No strategy output found")

    content = strategy_match.group(1).strip()

    # Try to extract YAML block (looks for ```yaml ... ``` or ```yml ... ```)
    yaml_block_match = re.search(
        r"```(?:yaml|yml)\s*\n(.+?)\n```", content, re.IGNORECASE | re.DOTALL
    )

    yaml_content = yaml_block_match.group(1).strip() if yaml_block_match else content

    # Attempt to parse YAML
    try:
        parsed_data = yaml.safe_load(yaml_content)

        # Validate that it's a dictionary
        if not isinstance(parsed_data, dict):
            # YAML parsed but not a dict - fallback to summary
            return StrategyOutputStructured(summary=content)

        # Extract fields matching the schema
        result = StrategyOutputStructured()

        if "summary" in parsed_data:
            result["summary"] = str(parsed_data["summary"])
        if "tier_assignments" in parsed_data:
            result["tier_assignments"] = parsed_data["tier_assignments"]
        if "testing_patterns" in parsed_data:
            result["testing_patterns"] = parsed_data["testing_patterns"]
        if "use_cases" in parsed_data:
            result["use_cases"] = parsed_data["use_cases"]
        if "edge_cases" in parsed_data:
            result["edge_cases"] = parsed_data["edge_cases"]
        if "test_file_mapping" in parsed_data:
            result["test_file_mapping"] = parsed_data["test_file_mapping"]
        if "guidance_for_planner" in parsed_data:
            result["guidance_for_planner"] = parsed_data["guidance_for_planner"]

        # If no fields were extracted, fallback to summary with raw content
        if not result:
            return StrategyOutputStructured(summary=content)

        # If summary is missing but we have other fields, add a default summary
        if "summary" not in result:
            result["summary"] = "Structured strategy output (no summary provided)"

        # Validate against JSON Schema
        try:
            validator = _get_output_schema_validator()
            validator.validate(dict(result))
        except jsonschema.ValidationError as ve:
            # Validation failed - include error details in summary and return minimal
            error_path = ".".join(str(p) for p in ve.absolute_path) if ve.absolute_path else "root"
            error_msg = f"Schema validation failed at '{error_path}': {ve.message}"
            # Return fallback with summary containing raw content and validation error
            return StrategyOutputStructured(
                summary=f"{result.get('summary', content)}\n\n(Validation error: {error_msg})"
            )
        except (FileNotFoundError, json.JSONDecodeError) as schema_error:
            # Schema loading failed - log but continue with parsed result
            # This allows the system to work even if schemas are missing
            result["summary"] = (
                f"{result.get('summary', 'Structured strategy output')}\n\n"
                f"(Schema validation skipped: {schema_error!s})"
            )

    except (yaml.YAMLError, ValueError, AttributeError) as e:
        # YAML parsing failed - graceful fallback
        # Return the raw content as summary field
        return StrategyOutputStructured(summary=f"{content}\n\n(Note: YAML parsing failed: {e!s})")
    else:
        return result


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

    Delegates to parse_strategy_review_output_structured for parsing and
    converts the structured result to the legacy tuple format.

    Args:
        output: Stdout from test-strategy agent in review mode.

    Returns:
        Tuple of (status, content) where status is "approved", "feedback", or "blocked".
    """
    # Delegate to structured parser
    structured = parse_strategy_review_output_structured(output)

    # Convert structured result to legacy tuple format
    status = structured["status"].lower()

    if status == "approved":
        return "approved", ""
    elif status == "feedback":
        # Extract feedback content from issues
        issues = structured.get("issues", [])
        if issues:
            # Concatenate all issue descriptions
            content = "\n".join(issue.get("description", str(issue)) for issue in issues)
            return "feedback", content
        return "feedback", ""
    else:  # blocked
        return "blocked", structured.get("reason", "Unrecognized strategy review response")


def parse_strategy_review_output_structured(output: str) -> StrategyReviewOutputStructured:
    r"""Parse test-strategy agent review mode output and extract structured data.

    Extracts status (APPROVED/FEEDBACK/BLOCKED) and parses structured YAML
    if present. Implements graceful fallback for unstructured output.

    Args:
        output: Stdout from test-strategy agent in review mode.

    Returns:
        StrategyReviewOutputStructured dict with status and optional
        issues/reason fields. For unstructured output, extracts status
        and puts raw text in appropriate field.

    Examples:
        >>> output = "APPROVED"
        >>> result = parse_strategy_review_output_structured(output)
        >>> result['status']
        'APPROVED'

        >>> output = "FEEDBACK:\\n```yaml\\nissues:\\n  - category: missing_tier\\n```"
        >>> result = parse_strategy_review_output_structured(output)
        >>> result['status']
        'FEEDBACK'
    """
    # Check for APPROVED status first
    if re.search(r"\bAPPROVED\b", output, re.IGNORECASE):
        return StrategyReviewOutputStructured(status="APPROVED")

    # Check for FEEDBACK
    feedback_match = re.search(r"FEEDBACK:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if feedback_match:
        content = feedback_match.group(1).strip()
        return _parse_review_with_yaml(content, "FEEDBACK")

    # Check for BLOCKED
    blocked_match = re.search(r"BLOCKED:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if blocked_match:
        content = blocked_match.group(1).strip()
        return _parse_review_with_yaml(content, "BLOCKED")

    # Unrecognized format - return BLOCKED with raw output
    return StrategyReviewOutputStructured(
        status="BLOCKED", reason=f"Unrecognized review response: {output.strip()}"
    )


def _parse_review_with_yaml(
    content: str, status: Literal["FEEDBACK", "BLOCKED"]
) -> StrategyReviewOutputStructured:
    """Helper to parse review content with optional YAML structure.

    Parses the content, validates against the review schema, and returns
    structured data with graceful fallback on validation errors.

    Args:
        content: The content after FEEDBACK: or BLOCKED: marker.
        status: The status type (FEEDBACK or BLOCKED).

    Returns:
        StrategyReviewOutputStructured with parsed data or graceful fallback.
    """
    # Try to extract YAML block
    yaml_block_match = re.search(
        r"```(?:yaml|yml)\s*\n(.+?)\n```", content, re.IGNORECASE | re.DOTALL
    )

    yaml_content = yaml_block_match.group(1).strip() if yaml_block_match else content

    # Attempt to parse YAML
    try:
        parsed_data = yaml.safe_load(yaml_content)

        if isinstance(parsed_data, dict):
            result = StrategyReviewOutputStructured(status=status)

            # Extract fields based on status
            if status == "FEEDBACK":
                # Look for issues array
                if "issues" in parsed_data and isinstance(parsed_data["issues"], list):
                    result["issues"] = parsed_data["issues"]
                else:
                    # No structured issues - put raw content as single issue
                    result["issues"] = [
                        {
                            "category": "pattern_mismatch",
                            "description": content,
                            "severity": "medium",
                        }
                    ]
            elif status == "BLOCKED":
                # Look for reason string
                if "reason" in parsed_data:
                    result["reason"] = str(parsed_data["reason"])
                else:
                    # No structured reason - use raw content
                    result["reason"] = content

            # Validate against JSON Schema
            try:
                validator = _get_review_schema_validator()
                validator.validate(dict(result))
            except jsonschema.ValidationError as ve:
                # Validation failed - return fallback with error details
                error_path = (
                    ".".join(str(p) for p in ve.absolute_path) if ve.absolute_path else "root"
                )
                error_msg = f"Schema validation failed at '{error_path}': {ve.message}"
                fallback = StrategyReviewOutputStructured(status=status)
                if status == "FEEDBACK":
                    fallback["issues"] = [
                        {
                            "category": "pattern_mismatch",
                            "description": f"{content}\n\n(Validation error: {error_msg})",
                            "severity": "medium",
                        }
                    ]
                else:  # BLOCKED
                    fallback["reason"] = f"{content}\n\n(Validation error: {error_msg})"
                return fallback
            except (FileNotFoundError, json.JSONDecodeError):
                # Schema loading failed - continue with parsed result
                pass

            return result

    except (yaml.YAMLError, ValueError, AttributeError):
        # YAML parsing failed - use graceful fallback
        pass

    # Fallback: return status with raw content in appropriate field
    result = StrategyReviewOutputStructured(status=status)
    if status == "FEEDBACK":
        result["issues"] = [
            {"category": "pattern_mismatch", "description": content, "severity": "medium"}
        ]
    else:  # BLOCKED
        result["reason"] = content

    return result


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

    Delegates to parse_plan_review_output_structured for parsing and
    converts the structured result to the legacy tuple format.

    Args:
        output: Stdout from test-planner agent in review mode.

    Returns:
        Tuple of (status, content) where status is "complete", "incomplete", or "blocked".
    """
    # Delegate to structured parser
    structured = parse_plan_review_output_structured(output)

    # Convert structured result to legacy tuple format
    status = structured["status"].lower()

    if status == "complete":
        summary = structured.get("summary", "plan satisfied")
        return "complete", summary

    if status == "incomplete":
        # Extract gap content from structured result
        gaps = structured.get("gaps", [])
        if gaps:
            # Concatenate all gap descriptions
            content = "\n".join(gap.get("description", str(gap)) for gap in gaps)
            return "incomplete", content
        return "incomplete", ""

    # blocked
    return "blocked", structured.get("reason", "Unrecognized plan review response")


def parse_plan_review_output_structured(output: str) -> PlanReviewOutputStructured:
    r"""Parse test-planner agent review mode output and extract structured data.

    Extracts status (COMPLETE/INCOMPLETE/BLOCKED) and parses structured YAML
    if present after the PLAN_REVIEW: marker. Implements graceful fallback
    for unstructured output.

    Args:
        output: Stdout from test-planner agent in review mode.

    Returns:
        PlanReviewOutputStructured dict with status and optional
        gaps/reason/summary fields. For unstructured output, extracts status
        and puts raw text in appropriate field.

    Examples:
        >>> output = "COMPLETE: plan satisfied"
        >>> result = parse_plan_review_output_structured(output)
        >>> result['status']
        'COMPLETE'

        >>> output = "PLAN_REVIEW:\\n```yaml\\nstatus: INCOMPLETE\\ngaps:\\n```"
        >>> result = parse_plan_review_output_structured(output)
        >>> result['status']
        'INCOMPLETE'
    """
    # First check for structured PLAN_REVIEW: marker
    plan_review_match = re.search(r"PLAN_REVIEW:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if plan_review_match:
        content = plan_review_match.group(1).strip()
        return _parse_plan_review_with_yaml(content)

    # Fall back to text prefix parsing for backward compatibility
    complete_match = re.search(r"COMPLETE:\s*(.+)", output, re.IGNORECASE)
    if complete_match:
        return PlanReviewOutputStructured(
            status="COMPLETE", summary=complete_match.group(1).strip()
        )

    incomplete_match = re.search(r"INCOMPLETE:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if incomplete_match:
        content = incomplete_match.group(1).strip()
        # Create a single gap from the raw content
        return PlanReviewOutputStructured(
            status="INCOMPLETE",
            gaps=[
                {
                    "category": "missing_test",
                    "description": content,
                    "severity": "medium",
                }
            ],
        )

    blocked_match = re.search(r"BLOCKED:\s*(.+)", output, re.IGNORECASE | re.DOTALL)
    if blocked_match:
        return PlanReviewOutputStructured(status="BLOCKED", reason=blocked_match.group(1).strip())

    # Unrecognized format - return BLOCKED with raw output
    return PlanReviewOutputStructured(
        status="BLOCKED", reason=f"Unrecognized plan review response: {output.strip()}"
    )


def _parse_plan_review_with_yaml(content: str) -> PlanReviewOutputStructured:
    """Helper to parse plan review content with optional YAML structure.

    Parses the content, validates against the plan review schema, and returns
    structured data with graceful fallback on validation errors.

    Args:
        content: The content after PLAN_REVIEW: marker.

    Returns:
        PlanReviewOutputStructured with parsed data or graceful fallback.
    """
    # Try to extract YAML block
    yaml_block_match = re.search(
        r"```(?:yaml|yml)\s*\n(.+?)\n```", content, re.IGNORECASE | re.DOTALL
    )

    yaml_content = yaml_block_match.group(1).strip() if yaml_block_match else content

    # Attempt to parse YAML
    try:
        parsed_data = yaml.safe_load(yaml_content)

        if isinstance(parsed_data, dict):
            # Extract status - required field
            status_raw = parsed_data.get("status", "BLOCKED")
            status: Literal["COMPLETE", "INCOMPLETE", "BLOCKED"]
            if status_raw.upper() == "COMPLETE":
                status = "COMPLETE"
            elif status_raw.upper() == "INCOMPLETE":
                status = "INCOMPLETE"
            else:
                status = "BLOCKED"

            result = PlanReviewOutputStructured(status=status)

            # Extract optional fields based on status
            if status == "COMPLETE":
                if "summary" in parsed_data:
                    result["summary"] = str(parsed_data["summary"])

            elif status == "INCOMPLETE":
                # Look for gaps array
                if "gaps" in parsed_data and isinstance(parsed_data["gaps"], list):
                    result["gaps"] = parsed_data["gaps"]
                else:
                    # No structured gaps - put raw content as single gap
                    result["gaps"] = [
                        {
                            "category": "missing_test",
                            "description": content,
                            "severity": "medium",
                        }
                    ]

            elif status == "BLOCKED":
                # Look for reason string
                if "reason" in parsed_data:
                    result["reason"] = str(parsed_data["reason"])
                else:
                    # No structured reason - use raw content
                    result["reason"] = content

            # Add summary if present (any status)
            if "summary" in parsed_data and "summary" not in result:
                result["summary"] = str(parsed_data["summary"])

            # Validate against JSON Schema
            try:
                validator = _get_plan_review_schema_validator()
                validator.validate(dict(result))
            except jsonschema.ValidationError as ve:
                # Validation failed - return fallback with error details
                error_path = (
                    ".".join(str(p) for p in ve.absolute_path) if ve.absolute_path else "root"
                )
                error_msg = f"Schema validation failed at '{error_path}': {ve.message}"
                fallback = PlanReviewOutputStructured(status=status)
                if status == "INCOMPLETE":
                    fallback["gaps"] = [
                        {
                            "category": "missing_test",
                            "description": f"{content}\n\n(Validation error: {error_msg})",
                            "severity": "medium",
                        }
                    ]
                elif status == "BLOCKED":
                    fallback["reason"] = f"{content}\n\n(Validation error: {error_msg})"
                return fallback
            except (FileNotFoundError, json.JSONDecodeError):
                # Schema loading failed - continue with parsed result
                pass

            return result

    except (yaml.YAMLError, ValueError, AttributeError):
        # YAML parsing failed - use graceful fallback
        pass

    # Fallback: try to determine status from raw content
    if "COMPLETE" in content.upper():
        return PlanReviewOutputStructured(status="COMPLETE", summary=content)
    if "INCOMPLETE" in content.upper():
        return PlanReviewOutputStructured(
            status="INCOMPLETE",
            gaps=[{"category": "missing_test", "description": content, "severity": "medium"}],
        )
    return PlanReviewOutputStructured(status="BLOCKED", reason=content)


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


def normalize_coverage_gaps(functions_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize coverage JSON data into unified gap structure.

    Args:
        functions_data: Parsed JSON from coverage-functions command.

    Returns:
        List of normalized gap dictionaries with function, file, line_coverage,
        and branch_coverage fields.
    """
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
    return gaps


def determine_strategy_need(
    gaps: list[dict[str, Any]], original_strategy: str | None = None
) -> bool:
    """Determine if coverage gaps indicate need for strategy revision.

    Considers:
    - Raw gap count (>10 gaps suggests systemic issue)
    - Module concentration (many gaps from same module suggests blind spot)
    - Can be extended to analyze strategy document for structural issues

    Args:
        gaps: List of coverage gap dictionaries.
        original_strategy: Original strategy document (for future extension).

    Returns:
        True if strategy revision is recommended, False otherwise.
    """
    if not gaps:
        return False

    # Heuristic 1: Many total gaps suggest strategy needs revision
    if len(gaps) > 10:
        return True

    # Heuristic 2: Check for module concentration
    # If many gaps come from the same module, strategy may have missed that module's patterns
    module_counts: dict[str, int] = {}
    for gap in gaps:
        file_path = gap.get("file", "")
        # Extract module path (directory)
        module = "/".join(file_path.split("/")[:-1]) if "/" in file_path else file_path
        module_counts[module] = module_counts.get(module, 0) + 1

    # If more than 5 gaps in a single module, suggest strategy revision
    if any(count > 5 for count in module_counts.values()):
        return True

    # Future extension: analyze original_strategy for blind spots
    # e.g., check if strategy mentions the modules with gaps
    _ = original_strategy  # Reserved for future use

    return False


def parse_coverage_results(
    summary_result: subprocess.CompletedProcess[str],
    functions_result: subprocess.CompletedProcess[str],
    original_strategy: str | None = None,
) -> CoverageResult:
    """Parse coverage command outputs to determine gaps.

    Args:
        summary_result: Result from coverage-summary command.
        functions_result: Result from coverage-functions command.
        original_strategy: Original strategy document for determining revision need.

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

    # Extract and normalize gap details
    gaps = normalize_coverage_gaps(functions_data)

    # Determine if strategy revision is needed using enhanced heuristics
    needs_strategy = determine_strategy_need(gaps, original_strategy)

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
    prompt = format_strategy_prompt(
        ctx.target_files,
        analysis_context=ctx.analysis_context,
        existing_tests=ctx.existing_tests,
    )
    result = _run_tasks_agent("test-strategy", prompt)

    # Use structured parser for new functionality
    structured_result = parse_strategy_output_structured(result.stdout or "")

    # Check if output indicates blocked status
    if "summary" in structured_result and structured_result["summary"].startswith("BLOCKED:"):
        return StateResult("blocked", {}, structured_result["summary"])

    # For backward compatibility, also get the raw string content
    status, content = parse_strategy_output(result.stdout or "")

    if status == "blocked":
        return StateResult("blocked", {}, content)

    # Store both structured and raw formats
    return StateResult(
        "planning",
        {"strategy_document": content, "strategy_structured": dict(structured_result)},
        "Strategy generated",
    )


def handle_planning(ctx: WorkflowContext) -> StateResult:
    """Create test plan via test-planner agent.

    Args:
        ctx: Current workflow context.

    Returns:
        StateResult transitioning to strategy_review or blocked state.
    """
    prompt = format_planning_prompt(
        ctx.strategy_document,
        ctx.target_files,
        ctx.feedback_history,
        ctx.coverage_gaps,
        git_diff=ctx.git_diff,
        existing_tests=ctx.existing_tests,
        strategy_structured=ctx.strategy_structured,
    )
    result = _run_tasks_agent("test-planner", prompt)

    status, content = parse_planner_output(result.stdout or "")

    if status == "blocked":
        return StateResult("blocked", {}, content)

    # Reset strategy_review_count when entering a new planning cycle
    return StateResult(
        "strategy_review", {"test_plan": content, "strategy_review_count": 0}, "Plan created"
    )


def handle_strategy_review(ctx: WorkflowContext) -> StateResult:
    """Review plan against strategy via test-strategy agent (review mode).

    Args:
        ctx: Current workflow context.

    Returns:
        StateResult transitioning to writing, planning (with feedback),
        strategy_update (if max reviews exceeded), or blocked state.
    """
    prompt = format_strategy_review_prompt(
        ctx.strategy_document, ctx.test_plan, target_files=ctx.target_files
    )
    result = _run_tasks_agent("test-strategy", prompt)

    # Use structured parser for new functionality
    structured_result = parse_strategy_review_output_structured(result.stdout or "")

    # For backward compatibility, also get the simple status
    _status, content = parse_strategy_review_output(result.stdout or "")

    if structured_result["status"] == "APPROVED":
        return StateResult("writing", {}, "Plan approved by strategy review")

    if structured_result["status"] == "FEEDBACK":
        new_review_count = ctx.strategy_review_count + 1

        # Extract feedback content from structured result or fallback to raw content
        if "issues" in structured_result:
            # Format issues into a readable string
            feedback_items = []
            for issue in structured_result["issues"]:
                category = issue.get("category", "unknown")
                description = issue.get("description", "")
                severity = issue.get("severity", "medium")
                feedback_items.append(f"[{severity}] {category}: {description}")
            feedback_content = "\n".join(feedback_items)
        else:
            feedback_content = content

        feedback_history = [*ctx.feedback_history, feedback_content]

        # Check if max strategy reviews exceeded
        if new_review_count >= ctx.max_strategy_reviews:
            msg = f"Max strategy reviews ({ctx.max_strategy_reviews}) exceeded, escalating"
            return StateResult(
                "strategy_update",
                {"feedback_history": feedback_history, "strategy_review_count": new_review_count},
                msg,
            )

        feedback_preview = feedback_content[:80]
        msg = f"Feedback ({new_review_count}/{ctx.max_strategy_reviews}): {feedback_preview}..."
        return StateResult(
            "planning",
            {"feedback_history": feedback_history, "strategy_review_count": new_review_count},
            msg,
        )

    # BLOCKED status
    reason = structured_result.get("reason", content)
    return StateResult("blocked", {}, reason)


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

    # Pass strategy_document to determine_strategy_need for analysis
    coverage_result = parse_coverage_results(
        summary_result, functions_result, original_strategy=ctx.strategy_document
    )

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
        ctx.strategy_document, ctx.written_tests, ctx.coverage_gaps, target_files=ctx.target_files
    )
    result = _run_tasks_agent("test-strategy", prompt)

    # Use structured parser for new functionality
    structured_result = parse_strategy_output_structured(result.stdout or "")

    # Check if output indicates blocked status
    if "summary" in structured_result and structured_result["summary"].startswith("BLOCKED:"):
        return StateResult("blocked", {}, structured_result["summary"])

    # For backward compatibility, also get the raw string content
    status, content = parse_strategy_output(result.stdout or "")

    if status == "blocked":
        return StateResult("blocked", {}, content)

    # Reset feedback_history and strategy_review_count for new strategy cycle
    # Store both structured and raw formats
    return StateResult(
        "planning",
        {
            "strategy_document": content,
            "strategy_structured": dict(structured_result),
            "feedback_history": [],
            "strategy_review_count": 0,
        },
        "Strategy revised",
    )


# -----------------------------------------------------------------------------
# Context initialization helpers
# -----------------------------------------------------------------------------


def _compute_git_diff(target_files: list[str]) -> str | None:
    """Compute git diff for target files.

    Args:
        target_files: List of file paths to get diff for.

    Returns:
        Git diff output as string, or None if diff fails.
    """
    try:
        # Get diff for only the target files
        command = ["git", "diff", "--", *target_files]
        result = subprocess.run(
            command, capture_output=True, text=True, cwd=PROJECT_ROOT, check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        # Also check staged changes
        command_staged = ["git", "diff", "--staged", "--", *target_files]
        result_staged = subprocess.run(
            command_staged, capture_output=True, text=True, cwd=PROJECT_ROOT, check=False
        )
        if result_staged.returncode == 0 and result_staged.stdout.strip():
            return result_staged.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        # Git command failed - return None to indicate no diff available
        return None
    return None


def _discover_existing_tests() -> list[str]:
    """Discover existing test files in the tests/ directory.

    Returns:
        List of existing test file paths.
    """
    import glob

    test_patterns = [
        "tests/**/*.py",
        "scripts/tests/**/*.py",
    ]

    existing_tests: list[str] = []
    for pattern in test_patterns:
        matches = glob.glob(str(PROJECT_ROOT / pattern), recursive=True)
        for match in matches:
            # Convert to relative path
            rel_path = str(Path(match).relative_to(PROJECT_ROOT))
            if "__pycache__" not in rel_path and "conftest" not in rel_path:
                existing_tests.append(rel_path)

    return sorted(existing_tests)[:50]  # Limit to 50 files for prompt size


# -----------------------------------------------------------------------------
# Main workflow
# -----------------------------------------------------------------------------


def run_test_automation_workflow(
    target_files: list[str],
    *,
    max_iterations: int = 5,
    max_debug_retries: int = 3,
    max_strategy_reviews: int = 3,
    analysis_context: str | None = None,
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
        max_strategy_reviews: Maximum plan revisions before escalating to strategy update.
        analysis_context: Optional description of what changed (for strategy generation).

    Returns:
        WorkflowResult with final state and context.
    """
    # Compute git diff and discover existing tests
    git_diff = _compute_git_diff(target_files)
    existing_tests = _discover_existing_tests()

    ctx = WorkflowContext(
        target_files=target_files,
        max_iterations=max_iterations,
        max_debug_retries=max_debug_retries,
        max_strategy_reviews=max_strategy_reviews,
        git_diff=git_diff,
        existing_tests=existing_tests if existing_tests else None,
        analysis_context=analysis_context,
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
    parser.add_argument(
        "--max-strategy-reviews",
        type=int,
        default=3,
        help="Maximum plan revisions before escalating to strategy update (default: 3)",
    )
    parser.add_argument(
        "--context",
        type=str,
        default=None,
        help="Optional description of what changed for strategy generation",
    )
    args = parser.parse_args()

    result = run_test_automation_workflow(
        args.files,
        max_iterations=args.max_iterations,
        max_debug_retries=args.max_debug_retries,
        max_strategy_reviews=args.max_strategy_reviews,
        analysis_context=args.context,
    )

    print(f"\n{result.message}")
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
