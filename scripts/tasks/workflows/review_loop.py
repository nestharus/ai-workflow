"""Review loop workflow for strategy-planner iteration.

This module implements the review loop orchestration that iteratively invokes
the strategy-reviewer and plan-reviser agents until the plan is approved or
a termination condition is met. The loop ensures that implementation plans
align with strategy documents through structured feedback and revision cycles.
"""

from __future__ import annotations

import functools
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

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


def _get_strategy_review_validator() -> jsonschema.Draft7Validator:
    """Get a cached Draft7Validator for the strategy review output schema.

    Returns:
        Configured Draft7Validator instance.
    """
    schema = _load_schema("strategy-review-output.schema.json")
    return jsonschema.Draft7Validator(schema)


def _get_planner_revision_validator() -> jsonschema.Draft7Validator:
    """Get a cached Draft7Validator for the planner revision output schema.

    Returns:
        Configured Draft7Validator instance.
    """
    schema = _load_schema("planner-revision.schema.json")
    return jsonschema.Draft7Validator(schema)


ReviewLoopStatus = Literal["approved", "timeout", "blocked", "stalemate"]
ReviewStatus = Literal["APPROVED", "FEEDBACK", "BLOCKED"]
RevisionStatus = Literal["REVISED", "UNCHANGED", "BLOCKED"]


@dataclass
class ReviewIteration:
    """Record of a single iteration in the review loop.

    Attributes:
        iteration_number: The iteration count (1-indexed).
        review_status: Status from strategy-reviewer (APPROVED/FEEDBACK/BLOCKED).
        review_issues: List of issue IDs identified in this review.
        revision_status: Status from plan-reviser (REVISED/UNCHANGED/BLOCKED), None if
            review was APPROVED or BLOCKED.
        addressed_issues: List of issue IDs addressed by the reviser, None if no
            revision occurred.
        revision_summary: Summary of changes made, None if no revision occurred.
        error_reason: Diagnostic message when review or revision is BLOCKED due to
            parse/validation errors.
    """

    iteration_number: int
    review_status: ReviewStatus
    review_issues: list[str] = field(default_factory=list)
    revision_status: RevisionStatus | None = None
    addressed_issues: list[str] = field(default_factory=list)
    revision_summary: str | None = None
    error_reason: str | None = None


@dataclass
class ReviewLoopResult:
    """Result from running the strategy-planner review loop.

    This dataclass encapsulates the outcome of the iterative review process,
    including the final status, iteration count, and detailed history of each
    review-revise cycle.

    Attributes:
        status: Final outcome - "approved" (plan accepted), "timeout" (max iterations reached),
                "blocked" (unrecoverable error), or "stalemate" (planner returned UNCHANGED).
        iterations: Number of review-revise cycles completed.
        final_plan_path: Path to the final plan document (same as input, modified in place).
        history: Chronological record of all review iterations with detailed outcomes.
    """

    status: ReviewLoopStatus
    iterations: int
    final_plan_path: str
    history: list[ReviewIteration]


def _run(command: list[str], *, cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess[str]:
    """Execute a command and stream output to stdout/stderr."""
    result = subprocess.run(command, capture_output=True, text=True, cwd=cwd)
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


def _parse_yaml_after_marker(output: str, marker: str) -> dict[str, Any]:
    """Parse YAML data that appears after a specific marker in agent output.

    Args:
        output: The stdout from an agent.
        marker: The marker string to search for (e.g., "REVIEW:", "REVISION:").

    Returns:
        Parsed YAML data as a dictionary.

    Raises:
        ValueError: If marker not found or YAML parsing fails.
    """
    # Find the marker in the output
    marker_index = output.find(marker)
    if marker_index == -1:
        raise ValueError(f"Marker '{marker}' not found in agent output")

    # Extract everything after the marker
    yaml_text = output[marker_index + len(marker) :].strip()

    # Parse the YAML
    try:
        parsed = yaml.safe_load(yaml_text)
        if not isinstance(parsed, dict):
            raise TypeError(f"Expected YAML dict after '{marker}', got {type(parsed)}")
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse YAML after '{marker}': {e}") from e
    else:
        return parsed


def _parse_review_output(output: str) -> tuple[ReviewStatus, list[str], str | None]:
    """Parse strategy-reviewer output to extract status and issue IDs.

    Validates parsed YAML against the strategy-review-output.schema.json schema.
    When validation fails, returns BLOCKED status with a diagnostic reason.

    Args:
        output: The stdout from the strategy-reviewer agent.

    Returns:
        A tuple of (status, issue_ids, error_reason) where:
        - status is one of "APPROVED", "FEEDBACK", or "BLOCKED"
        - issue_ids is a list of issue IDs (e.g., ["SR-1-001", "SR-1-002"]) when status is FEEDBACK
        - error_reason is a diagnostic message when status is BLOCKED due to parse/validation error
    """
    try:
        review_data = _parse_yaml_after_marker(output, "REVIEW:")

        # Validate against JSON Schema
        try:
            validator = _get_strategy_review_validator()
            validator.validate(review_data)
        except jsonschema.ValidationError as ve:
            error_path = ".".join(str(p) for p in ve.absolute_path) if ve.absolute_path else "root"
            error_msg = f"Schema validation failed at '{error_path}': {ve.message}"
            return "BLOCKED", [], f"Review output failed schema validation: {error_msg}"
        except (FileNotFoundError, json.JSONDecodeError):
            # Schema loading failed - log but continue with parsed result
            # This allows the system to work even if schemas are missing
            pass

        status = review_data.get("status")
        if status not in ("APPROVED", "FEEDBACK", "BLOCKED"):
            return "BLOCKED", [], f"Invalid review status: {status}"

        issue_ids = []
        if status == "FEEDBACK":
            issues = review_data.get("issues", [])
            issue_ids = [issue.get("id", "") for issue in issues if isinstance(issue, dict)]

        # For BLOCKED status, extract reason if available
        error_reason = review_data.get("reason") if status == "BLOCKED" else None

    except ValueError as e:
        # YAML parsing failed - return BLOCKED with diagnostic
        return "BLOCKED", [], f"Failed to parse review output: {e}"
    else:
        return status, issue_ids, error_reason


def _parse_revision_output(output: str) -> tuple[RevisionStatus, list[str], str | None, str | None]:
    """Parse plan-reviser output to extract status, addressed issues, summary, and reason.

    Validates parsed YAML against the planner-revision.schema.json schema.
    When validation fails, returns BLOCKED status with a diagnostic reason.

    Args:
        output: The stdout from the plan-reviser agent.

    Returns:
        A tuple of (status, addressed_issues, revision_summary, error_reason) where:
        - status is one of "REVISED", "UNCHANGED", or "BLOCKED"
        - addressed_issues is a list of issue IDs that were addressed
        - revision_summary is the summary text when status is REVISED
        - error_reason is a diagnostic message when status is BLOCKED/UNCHANGED or validation fails
    """
    try:
        revision_data = _parse_yaml_after_marker(output, "REVISION:")

        # Validate against JSON Schema
        try:
            validator = _get_planner_revision_validator()
            validator.validate(revision_data)
        except jsonschema.ValidationError as ve:
            error_path = ".".join(str(p) for p in ve.absolute_path) if ve.absolute_path else "root"
            error_msg = f"Schema validation failed at '{error_path}': {ve.message}"
            return "BLOCKED", [], None, f"Revision output failed schema validation: {error_msg}"
        except (FileNotFoundError, json.JSONDecodeError):
            # Schema loading failed - log but continue with parsed result
            # This allows the system to work even if schemas are missing
            pass

        status = revision_data.get("status")
        if status not in ("REVISED", "UNCHANGED", "BLOCKED"):
            return "BLOCKED", [], None, f"Invalid revision status: {status}"

        addressed_issues = revision_data.get("addressed_issues", [])
        revision_summary = revision_data.get("revision_summary")
        reason = revision_data.get("reason")

    except ValueError as e:
        # YAML parsing failed - return BLOCKED with diagnostic
        return "BLOCKED", [], None, f"Failed to parse revision output: {e}"
    else:
        return status, addressed_issues, revision_summary, reason


async def run_strategy_planner_review_loop(
    strategy_path: str,
    plan_path: str,
    max_iterations: int = 5,
) -> ReviewLoopResult:
    """Run strategy-planner review loop until convergence.

    This function orchestrates an iterative review-revision cycle where the
    strategy-reviewer agent evaluates a plan against a strategy document, and
    the plan-reviser agent incorporates feedback until the plan is approved or
    a termination condition is met.

    Termination conditions:
    1. status == APPROVED (success) - Plan satisfies strategy requirements
    2. iterations >= max_iterations (timeout) - Loop limit reached
    3. status == BLOCKED (unrecoverable error) - Cannot proceed with review or revision
    4. planner returns UNCHANGED (disagreement/stalemate) - Plan-reviser disagrees with feedback

    Args:
        strategy_path: Path to the strategy document file.
        plan_path: Path to the plan document file (will be modified in place).
        max_iterations: Maximum number of review-revise cycles to perform (default: 5).

    Returns:
        ReviewLoopResult with final status, iteration count, and complete history
        of all review iterations including feedback and revisions.
    """
    history: list[ReviewIteration] = []
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        # Step 1: Call strategy-reviewer
        review_prompt = f"""strategy_document: {strategy_path}
plan_document: {plan_path}
iteration: {iteration}"""

        review_result = _run_tasks_agent("strategy-reviewer", review_prompt)
        review_status, issue_ids, review_error = _parse_review_output(review_result.stdout or "")

        # Create iteration record
        current_iteration = ReviewIteration(
            iteration_number=iteration,
            review_status=review_status,
            review_issues=issue_ids,
            error_reason=review_error,
        )

        # Step 2: Check for termination conditions
        if review_status == "APPROVED":
            history.append(current_iteration)
            return ReviewLoopResult(
                status="approved",
                iterations=iteration,
                final_plan_path=plan_path,
                history=history,
            )

        if review_status == "BLOCKED":
            history.append(current_iteration)
            return ReviewLoopResult(
                status="blocked",
                iterations=iteration,
                final_plan_path=plan_path,
                history=history,
            )

        # Step 3: FEEDBACK status - call plan-reviser
        if review_status == "FEEDBACK":
            # Extract the full review YAML for feedback
            try:
                review_yaml = _parse_yaml_after_marker(review_result.stdout or "", "REVIEW:")
                feedback_yaml = yaml.dump(review_yaml)
            except ValueError:
                # If we can't extract YAML, pass the raw output
                feedback_yaml = review_result.stdout or ""

            revision_prompt = f"""mode: revise
feedback: |
{feedback_yaml}
original_plan: {plan_path}"""

            revision_result = _run_tasks_agent("plan-reviser", revision_prompt)
            revision_status, addressed_issues, revision_summary, revision_error = (
                _parse_revision_output(revision_result.stdout or "")
            )

            # Update iteration record with revision info
            current_iteration.revision_status = revision_status
            current_iteration.addressed_issues = addressed_issues
            current_iteration.revision_summary = revision_summary
            # Store revision error if present (overwrites review error if both occurred)
            if revision_error:
                current_iteration.error_reason = revision_error

            history.append(current_iteration)

            # Step 4: Check planner response
            if revision_status == "UNCHANGED":
                # Stalemate: planner disagrees with feedback
                return ReviewLoopResult(
                    status="stalemate",
                    iterations=iteration,
                    final_plan_path=plan_path,
                    history=history,
                )

            if revision_status == "BLOCKED":
                # Planner cannot proceed (e.g., conflicting requirements)
                return ReviewLoopResult(
                    status="blocked",
                    iterations=iteration,
                    final_plan_path=plan_path,
                    history=history,
                )

            # Step 5: REVISED status - loop back to step 1
            # (continue to next iteration)

    # Reached max_iterations without approval
    return ReviewLoopResult(
        status="timeout",
        iterations=iteration,
        final_plan_path=plan_path,
        history=history,
    )
