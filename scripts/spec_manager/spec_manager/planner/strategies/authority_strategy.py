"""Authority decision strategy.

Runs last in the pipeline. Reviews all decision requirements and new constraints,
calling :func:`check_authority` for each. Items the planner can decide are persisted;
items requiring human authority are moved to under-spec events.
"""

from __future__ import annotations

import logging
from pathlib import Path

from spec_manager.planner.constraints.authority import check_authority
from spec_manager.planner.constraints.types import ConstraintFact
from spec_manager.planner.tools.constraints_tool import ConstraintsTool

from .protocol import CandidateEvaluation, PlanningSession

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
        self._adapter = ConstraintsTool(workspace_root=workspace_root)

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
                _append_trace_entry(fact, "authority_review=planner_ok")
                _record_constraint_authority_audit(session, fact, authority)
                planner_ok_facts.append(fact)
            else:
                fact.authority_required = "human_required"
                _append_trace_entry(fact, "authority_review=human_required")
                _record_constraint_authority_audit(session, fact, authority)
                session.add_under_spec_event(
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
            deduped_facts: list[ConstraintFact] = []
            seen_constraint_ids: set[str] = set()
            for fact in planner_ok_facts:
                fact_id = str(fact.constraint_id).strip()
                if fact_id and fact_id in seen_constraint_ids:
                    continue
                if fact_id:
                    seen_constraint_ids.add(fact_id)
                deduped_facts.append(fact)
            self._adapter.save_facts(slice_id, deduped_facts)
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
                session.add_under_spec_event(
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
            for event in session.under_spec_event_dicts()
            if isinstance(event, dict)
        }

        for evaluation in session.candidate_evaluations:
            if isinstance(evaluation, dict):
                typed_evaluation = CandidateEvaluation.from_dict(evaluation)
            else:
                typed_evaluation = evaluation
            recommendation = typed_evaluation.recommendation.strip().lower()
            if recommendation not in {"needs_human", "reject"}:
                continue

            candidate_id = typed_evaluation.candidate_id
            key = ("candidate_evaluation", candidate_id)
            if key in existing_keys:
                continue

            session.add_under_spec_event(
                {
                    "type": "candidate_evaluation",
                    "candidate_id": candidate_id,
                    "source": typed_evaluation.source,
                    "recommendation": typed_evaluation.recommendation,
                    "coupling_score": typed_evaluation.coupling_score,
                    "blast_radius": typed_evaluation.blast_radius,
                    "constraints_checked": typed_evaluation.constraints_checked,
                    "evaluation_metadata": dict(typed_evaluation.metadata),
                    "question": ("Candidate requires human review before authority decision."),
                    "reason": "; ".join(reason for reason in typed_evaluation.reasons if reason)
                    or "candidate evaluation requested human review",
                    "reasons": list(typed_evaluation.reasons),
                }
            )
            existing_keys.add(key)


def _append_trace_entry(fact: ConstraintFact, entry: str) -> None:
    trace_entries: list[str] = []
    if isinstance(fact.trace, list):
        trace_entries = fact.trace
    elif fact.trace:
        trace_entries = [str(fact.trace)]
    if entry not in trace_entries:
        trace_entries.append(entry)
    fact.trace = trace_entries


def _record_constraint_authority_audit(
    session: PlanningSession,
    fact: ConstraintFact,
    authority: str,
) -> None:
    session.constraint_authority_audit.append(
        {
            "constraint_id": fact.constraint_id,
            "authority": authority,
            "dimension": fact.dimension,
            "question": fact.question,
            "answer": fact.answer,
            "fact": fact.to_dict(),
        }
    )
