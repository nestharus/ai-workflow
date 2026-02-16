"""Decision authority policy for the planner.

Determines whether the planner can autonomously make a decision or must
escalate to a human.  Fully deterministic (no LLM).
"""

from __future__ import annotations

from typing import Any, Literal

from spec_manager.planner.constraints.types import (
    DecisionRequirement,
    ImpactClassification,
)

_CANONICAL_DIMENSIONS = {
    "software",
    "legal",
    "economic",
    "organizational",
    "temporal",
    "operational",
}


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
        * Dimension is unknown/non-canonical.
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
    normalized_dimension = str(dimension or "").strip().lower()
    normalized_policies = {
        str(policy).strip().lower() for policy in (existing_policies or []) if str(policy).strip()
    }

    if normalized_dimension not in _CANONICAL_DIMENSIONS:
        return "human_required"

    # HIGH impact always requires human
    if impact.impact == "HIGH":
        return "human_required"

    # Legal and economic dimensions always require human
    if normalized_dimension in {"legal", "economic"}:
        return "human_required"

    # Too many constraints at once
    if constraints_introduced > 3:
        return "human_required"

    # Dimension not covered by existing policies
    if normalized_policies and normalized_dimension not in normalized_policies:
        return "human_required"

    return "planner_ok"


def build_question_pack(
    *, decision_requirements: list[DecisionRequirement]
) -> list[dict[str, Any]]:
    """Build a list of questions for human review.

    Transforms :class:`DecisionRequirement` objects into simple
    question/context dicts suitable for display or serialization.

    Args:
        decision_requirements: The decisions that need human input.

    Returns:
        List of dicts preserving all decision-requirement fields.
    """
    pack: list[dict[str, Any]] = []
    for dr in decision_requirements:
        pack.append(
            {
                "decision_id": dr.decision_id,
                "question": dr.question,
                "kind": dr.kind,
                "dimension": dr.dimension,
                "scope": dr.scope,
                "impact": dr.impact,
                "options": list(dr.options),
                "needed_for": list(dr.needed_for),
            }
        )
    return pack
