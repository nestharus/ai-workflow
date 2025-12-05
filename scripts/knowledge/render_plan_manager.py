"""Render plan CRUD operations for the artifact rendering system.

This module provides functions for loading, listing, and validating render plans
stored in `.knowledge/artifacts/render_plans/`. Per fact_redesign.md lines 522-560,
render plans define deterministic, stepwise algorithms for rendering artifacts from
facts.

Render Plan Schema:
    render_plan_id: Stable identifier (e.g., prose.paragraph.v1)
    render_engine: text_llm (LLM-based) or none (tracked but not re-rendered)
    artifact_kind: Artifact kind this plan applies to
    inputs: Dict with use_structural_fieldfacts (bool), use_semantic_facts (bool)
    determinism: Dict with ordering (list of priority keys)
    steps: List of step dicts with id and instruction

Render Engines:
    - text_llm: Uses LLM to render artifact from facts
    - none: Artifact is tracked/indexed but not re-rendered (e.g., diagrams)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

import yaml

# Module-level logger
_logger = logging.getLogger(__name__)


class RenderPlanInputs(TypedDict):
    """Input configuration for a render plan."""

    use_structural_fieldfacts: bool
    use_semantic_facts: bool


class RenderPlanDeterminism(TypedDict):
    """Determinism configuration for a render plan."""

    ordering: list[str]


class RenderPlanStep(TypedDict):
    """A single step in a render plan."""

    id: str
    instruction: str


class RenderPlan(TypedDict):
    """Complete render plan structure per fact_redesign.md lines 536-560."""

    render_plan_id: str
    render_engine: Literal["text_llm", "none"]
    artifact_kind: str
    inputs: RenderPlanInputs
    determinism: RenderPlanDeterminism
    steps: list[RenderPlanStep]
    notes: str


# Required fields for validation
REQUIRED_FIELDS = frozenset(
    {
        "render_plan_id",
        "render_engine",
        "artifact_kind",
        "inputs",
        "determinism",
        "steps",
    }
)

VALID_RENDER_ENGINES = frozenset({"text_llm", "none"})


def _get_render_plan_path(render_plan_id: str, render_plans_dir: Path) -> Path:
    """Get the path for a render plan file.

    Args:
        render_plan_id: The render plan identifier.
        render_plans_dir: Base render plans directory.

    Returns:
        Path to the render plan YAML file.
    """
    return render_plans_dir / f"{render_plan_id}.yml"


def validate_render_plan_schema(plan_dict: dict[str, Any]) -> list[str]:
    """Validate a render plan dictionary against the schema.

    Args:
        plan_dict: The render plan dictionary to validate.

    Returns:
        List of validation error messages. Empty list if valid.
    """
    errors: list[str] = []

    # Check required fields
    missing = REQUIRED_FIELDS - set(plan_dict.keys())
    if missing:
        errors.append(f"Missing required fields: {sorted(missing)}")

    # Validate render_engine value
    if "render_engine" in plan_dict:
        engine = plan_dict["render_engine"]
        if engine not in VALID_RENDER_ENGINES:
            errors.append(
                f"Invalid render_engine '{engine}', must be one of: {sorted(VALID_RENDER_ENGINES)}"
            )

    # Validate inputs structure
    if "inputs" in plan_dict:
        inputs = plan_dict["inputs"]
        if not isinstance(inputs, dict):
            errors.append("Field 'inputs' must be a dict")
        else:
            for key in ("use_structural_fieldfacts", "use_semantic_facts"):
                if key not in inputs:
                    errors.append(f"Missing required input field: {key}")
                elif not isinstance(inputs[key], bool):
                    errors.append(f"Input field '{key}' must be a boolean")

    # Validate determinism structure
    if "determinism" in plan_dict:
        determinism = plan_dict["determinism"]
        if not isinstance(determinism, dict):
            errors.append("Field 'determinism' must be a dict")
        elif "ordering" not in determinism:
            errors.append("Field 'determinism' must contain 'ordering'")
        elif not isinstance(determinism["ordering"], list):
            errors.append("Field 'determinism.ordering' must be a list")

    # Validate steps structure
    if "steps" in plan_dict:
        steps = plan_dict["steps"]
        if not isinstance(steps, list):
            errors.append("Field 'steps' must be a list")
        else:
            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    errors.append(f"Step {i} must be a dict")
                else:
                    if "id" not in step:
                        errors.append(f"Step {i} missing required field 'id'")
                    if "instruction" not in step:
                        errors.append(f"Step {i} missing required field 'instruction'")

    return errors


def load_render_plan(render_plan_id: str, render_plans_dir: Path) -> RenderPlan:
    """Load a render plan from YAML file.

    Args:
        render_plan_id: The render plan identifier.
        render_plans_dir: Base render plans directory.

    Returns:
        The loaded RenderPlan.

    Raises:
        FileNotFoundError: If the render plan file doesn't exist.
        ValueError: If the render plan YAML is invalid or missing required fields.
    """
    plan_path = _get_render_plan_path(render_plan_id, render_plans_dir)

    if not plan_path.exists():
        msg = f"Render plan not found: {plan_path}"
        raise FileNotFoundError(msg)

    try:
        content = plan_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML in render plan {plan_path}: {exc}"
        raise ValueError(msg) from exc

    if not isinstance(data, dict):
        msg = f"Render plan must be a dict: {plan_path}"
        raise TypeError(msg)

    # Validate schema
    errors = validate_render_plan_schema(data)
    if errors:
        msg = f"Invalid render plan {plan_path}: {'; '.join(errors)}"
        raise ValueError(msg)

    _logger.debug("Loaded render plan: %s", render_plan_id)
    return cast("RenderPlan", data)


def list_render_plans(render_plans_dir: Path) -> list[RenderPlan]:
    """List all render plans in the render plans directory.

    Args:
        render_plans_dir: Base render plans directory.

    Returns:
        List of RenderPlan objects.
    """
    if not render_plans_dir.exists():
        return []

    plans: list[RenderPlan] = []

    for plan_path in sorted(render_plans_dir.glob("*.yml")):
        try:
            render_plan_id = plan_path.stem
            plan = load_render_plan(render_plan_id, render_plans_dir)
            plans.append(plan)
        except (FileNotFoundError, ValueError) as exc:
            _logger.warning("Skipping invalid render plan %s: %s", plan_path, exc)
            continue

    _logger.info("Loaded %d render plans from %s", len(plans), render_plans_dir)
    return plans


def get_render_plan_for_artifact_kind(
    artifact_kind: str,
    render_plans_dir: Path,
) -> RenderPlan | None:
    """Find a render plan that matches the given artifact kind.

    Args:
        artifact_kind: The artifact kind to find a plan for.
        render_plans_dir: Base render plans directory.

    Returns:
        The matching RenderPlan, or None if no match found.
    """
    plans = list_render_plans(render_plans_dir)

    for plan in plans:
        if plan["artifact_kind"] == artifact_kind:
            _logger.debug(
                "Found render plan '%s' for artifact kind '%s'",
                plan["render_plan_id"],
                artifact_kind,
            )
            return plan

    _logger.debug("No render plan found for artifact kind '%s'", artifact_kind)
    return None


def get_render_plan_by_id(
    render_plan_id: str,
    render_plans_dir: Path,
) -> RenderPlan | None:
    """Get a render plan by its ID.

    Convenience wrapper around load_render_plan that returns None instead of
    raising FileNotFoundError.

    Args:
        render_plan_id: The render plan identifier.
        render_plans_dir: Base render plans directory.

    Returns:
        The RenderPlan if found, None otherwise.
    """
    try:
        return load_render_plan(render_plan_id, render_plans_dir)
    except FileNotFoundError:
        return None
    except ValueError as exc:
        _logger.warning("Invalid render plan %s: %s", render_plan_id, exc)
        return None
