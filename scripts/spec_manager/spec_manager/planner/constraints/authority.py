"""Decision authority policy for the planner.

Determines whether the planner can autonomously make a decision or must
escalate to a human.  Fully deterministic (no LLM).
"""

from __future__ import annotations

from typing import Literal

from spec_manager.planner.constraints.types import (
    DecisionRequirement,
    ImpactClassification,
)


def check_authority(
    *,
    impact: ImpactClassification,
    constraints_introduced: int = 0,
    dimension: str = "software",
    existing_policies: list[str] | None = None,
) -> Literal["planner_ok", "human_required"]:
    """Check whether the planner has authority to make a decision.

    Rules (any match → ``human_required``):
        * Impact is HIGH.
        * Dimension is ``legal`` or ``economic``.
        * More than 3 new constraints are introduced at once.
        * No existing policy covers the dimension (when *existing_policies*
          is non-empty but does not contain the dimension).

    Everything else → ``planner_ok``.

    Args:
        impact: The :class:`ImpactClassification` for the change.
        constraints_introduced: Number of new constraints being introduced.
        dimension: The constraint dimension (e.g. ``software``, ``legal``).
        existing_policies: List of dimensions that have existing policies.

    Returns:
        ``"planner_ok"`` or ``"human_required"``.
    """
    if existing_policies is None:
        existing_policies = []

    # HIGH impact always requires human
    if impact.impact == "HIGH":
        return "human_required"

    # Legal and economic dimensions always require human
    if dimension in ("legal", "economic"):
        return "human_required"

    # Too many constraints at once
    if constraints_introduced > 3:
        return "human_required"

    # Dimension not covered by existing policies
    if existing_policies and dimension not in existing_policies:
        return "human_required"

    return "planner_ok"


def build_question_pack(
    *, decision_requirements: list[DecisionRequirement]
) -> list[dict[str, str]]:
    """Build a list of questions for human review.

    Transforms :class:`DecisionRequirement` objects into simple
    question/context dicts suitable for display or serialization.

    Args:
        decision_requirements: The decisions that need human input.

    Returns:
        List of dicts with ``question``, ``kind``, ``dimension``,
        ``scope``, ``options``, and ``needed_for`` keys.
    """
    pack: list[dict[str, str]] = []
    for dr in decision_requirements:
        pack.append(
            {
                "question": dr.question,
                "kind": dr.kind,
                "dimension": dr.dimension,
                "scope": dr.scope,
                "options": ", ".join(dr.options) if dr.options else "",
                "needed_for": ", ".join(dr.needed_for) if dr.needed_for else "",
            }
        )
    return pack
