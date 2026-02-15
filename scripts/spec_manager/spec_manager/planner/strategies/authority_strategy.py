"""Authority decision strategy.

Runs last in the pipeline. Reviews all decision requirements and new constraints,
calling :func:`check_authority` for each. Items the planner can decide are persisted;
items requiring human authority are moved to under-spec events.
"""

from __future__ import annotations

import logging
from pathlib import Path

from spec_manager.planner.constraints.authority import check_authority
from spec_manager.planner.constraints.store_adapter import ConstraintStoreAdapter
from spec_manager.planner.constraints.types import ConstraintFact

from .protocol import PlanningSession

logger = logging.getLogger(__name__)


class AuthorityDeciderStrategy:
    """Reviews decisions and constraints for authority, persisting or escalating.

    Args:
        workspace_root: Workspace root directory.
    """

    @property
    def name(self) -> str:
        return "authority_decider"

    def __init__(self, workspace_root: Path) -> None:
        self._workspace_root = workspace_root
        self._adapter = ConstraintStoreAdapter(workspace_root)

    def run(self, session: PlanningSession) -> PlanningSession:
        if session.impact is None:
            return session

        slice_id = session.ctx.get("slice_id", "__system__")

        # Collect existing policy dimensions
        existing_policies: list[str] = []
        if session.constraint_context:
            existing_policies = list(
                {c.dimension for c in session.constraint_context.authoritative}
            )

        # Review new_constraints
        planner_ok_facts: list[ConstraintFact] = []
        remaining_constraints: list[ConstraintFact] = []

        for fact in session.new_constraints:
            authority = check_authority(
                impact=session.impact,
                constraints_introduced=len(session.new_constraints),
                dimension=fact.dimension,
                existing_policies=existing_policies,
            )

            if authority == "planner_ok":
                fact.authority_required = "planner_ok"
                planner_ok_facts.append(fact)
            else:
                fact.authority_required = "human_required"
                session.under_spec_events.append(
                    {
                        "type": "authority_required",
                        "constraint_id": fact.constraint_id,
                        "question": fact.question,
                        "answer": fact.answer,
                        "dimension": fact.dimension,
                        "reason": "human authority required",
                    }
                )
                remaining_constraints.append(fact)

        # Persist planner-ok facts
        if planner_ok_facts:
            self._adapter.save_facts(slice_id, planner_ok_facts)

        # Update session: keep only human-required constraints
        session.new_constraints = remaining_constraints

        # Review decision_requirements
        escalated_requirements = []
        for dr in session.decision_requirements:
            authority = check_authority(
                impact=session.impact,
                constraints_introduced=0,
                dimension=dr.dimension,
                existing_policies=existing_policies,
            )

            if authority == "human_required":
                session.under_spec_events.append(
                    {
                        "type": "decision_required",
                        "decision_id": dr.decision_id,
                        "question": dr.question,
                        "kind": dr.kind,
                        "dimension": dr.dimension,
                        "options": dr.options,
                        "reason": "human authority required",
                    }
                )
            else:
                escalated_requirements.append(dr)

        session.decision_requirements = escalated_requirements
        self._escalate_candidate_evaluations(session)

        return session

    def _escalate_candidate_evaluations(self, session: PlanningSession) -> None:
        """Escalate candidate evaluations that require human authority."""
        if not session.candidate_evaluations:
            return

        existing_keys = {
            (
                str(event.get("type", "")),
                str(event.get("candidate_id", "")),
            )
            for event in session.under_spec_events
            if isinstance(event, dict)
        }

        for evaluation in session.candidate_evaluations:
            if not isinstance(evaluation, dict):
                continue
            recommendation = str(evaluation.get("recommendation", "")).strip().lower()
            if recommendation not in {"needs_human", "reject"}:
                continue

            candidate_id = str(evaluation.get("candidate_id", "")).strip()
            key = ("candidate_evaluation", candidate_id)
            if key in existing_keys:
                continue

            session.under_spec_events.append(
                {
                    "type": "candidate_evaluation",
                    "candidate_id": candidate_id,
                    "source": evaluation.get("source", "unknown"),
                    "question": ("Candidate requires human review before authority decision."),
                    "reason": "; ".join(
                        str(reason).strip()
                        for reason in evaluation.get("reasons", [])
                        if str(reason).strip()
                    )
                    or "candidate evaluation requested human review",
                }
            )
            existing_keys.add(key)
