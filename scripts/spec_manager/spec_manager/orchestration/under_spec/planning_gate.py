"""Planning-phase constraint coverage check.

Before implementation begins, PlanStep checks that every decision
requirement in the plan is covered by an existing constraint.
Uncovered decisions become under-spec events that block the slice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from spec_manager.planner.constraints.store import ConstraintsStore

logger = logging.getLogger(__name__)


@dataclass
class CoverageResult:
    """Result of checking constraint coverage for a decision."""

    covered: bool = False
    covering_constraints: list[str] = field(default_factory=list)
    rationale: str = ""


@dataclass
class PlanningGateResult:
    """Result of running the planning gate on all plan intentions."""

    covered_decisions: list[dict[str, Any]] = field(default_factory=list)
    uncovered_decisions: list[dict[str, Any]] = field(default_factory=list)
    under_spec_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def all_covered(self) -> bool:
        return len(self.uncovered_decisions) == 0


def check_decision_coverage(
    *,
    constraints_store: ConstraintsStore,
    slice_id: str,
    decision: dict[str, Any],
) -> CoverageResult:
    """Check if a single decision requirement is covered by constraints.

    A decision is covered if the constraints store contains a constraint
    whose question matches (by ID or substring) the decision's question.

    Args:
        constraints_store: The file-based constraints store.
        slice_id: Current slice identifier.
        decision: Decision requirement dict from the planning agent.

    Returns:
        CoverageResult with coverage status and rationale.
    """
    constraints = constraints_store.load_merged(slice_id)
    decision_id = decision.get("decision_id", "")
    decision_question = decision.get("question", "").lower().strip()

    covering: list[str] = []

    for constraint in constraints:
        # Match by ID
        if constraint.constraint_id and constraint.constraint_id == decision_id:
            covering.append(constraint.constraint_id)
            continue

        # Match by question substring similarity
        constraint_q = constraint.question.lower().strip()
        if (
            constraint_q
            and decision_question
            and (constraint_q in decision_question or decision_question in constraint_q)
        ):
            covering.append(constraint.constraint_id or constraint.question[:50])

    if covering:
        return CoverageResult(
            covered=True,
            covering_constraints=covering,
            rationale=f"Covered by {len(covering)} constraint(s)",
        )

    return CoverageResult(
        covered=False,
        rationale=f"No constraint covers decision: {decision_question[:80]}",
    )


def run_planning_gate(
    *,
    constraints_store: ConstraintsStore,
    slice_id: str,
    intentions: list[dict[str, Any]],
) -> PlanningGateResult:
    """Run the planning gate on all plan intentions.

    For each intention with decision_requirements, checks constraint
    coverage. Uncovered decisions produce under_spec_events.

    Args:
        constraints_store: Constraint persistence layer.
        slice_id: Current slice identifier.
        intentions: Plan intentions from the planning agent.

    Returns:
        PlanningGateResult with covered/uncovered partitions.
    """
    result = PlanningGateResult()

    def _needed_for_target(intention: dict[str, Any]) -> Any:
        target_files = intention.get("target_files", [])
        if isinstance(target_files, list):
            normalized = [str(item) for item in target_files if str(item).strip()]
            if normalized:
                return normalized
        return intention.get("target_file", "")

    for intention in intentions:
        decision_reqs = intention.get("decision_requirements", [])
        if not decision_reqs:
            continue

        for decision in decision_reqs:
            coverage = check_decision_coverage(
                constraints_store=constraints_store,
                slice_id=slice_id,
                decision=decision,
            )

            if coverage.covered:
                result.covered_decisions.append(
                    {
                        "decision_id": decision.get("decision_id", ""),
                        "question": decision.get("question", ""),
                        "covering_constraints": coverage.covering_constraints,
                    }
                )
            else:
                result.uncovered_decisions.append(
                    {
                        "decision_id": decision.get("decision_id", ""),
                        "question": decision.get("question", ""),
                        "intention_id": intention.get("intention_id", ""),
                    }
                )
                result.under_spec_events.append(
                    {
                        "kind": "MISSING_CONSTRAINT",
                        "question": decision.get("question", ""),
                        "options": decision.get("options", []),
                        "needed_for": decision.get("needed_for", _needed_for_target(intention)),
                        "evidence_paths": [],
                    }
                )

    if result.uncovered_decisions:
        logger.info(
            "Planning gate: %d covered, %d uncovered decisions for slice '%s'",
            len(result.covered_decisions),
            len(result.uncovered_decisions),
            slice_id,
        )

    return result
