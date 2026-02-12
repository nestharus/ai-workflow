"""Architecture candidate evaluator and decision selector.

Evaluates candidates against authoritative constraints and decides
whether to commit, block, or escalate to human review.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spec_manager.planner.constraints.types import ConstraintFact

from .types import (
    ArchitectureCandidate,
    CandidateAssessment,
    DecisionOutcome,
    DecisionPoint,
)

logger = logging.getLogger(__name__)


class CandidateEvaluator:
    """Evaluates architecture candidates against constraints.

    Parameters
    ----------
    workspace_root:
        Root directory of the workspace.
    run_agent:
        Optional callable for LLM calls.  Signature:
        ``(prompt: str) -> str``.  When *None* the evaluator uses
        deterministic heuristics only.
    """

    def __init__(
        self,
        workspace_root: Path,
        run_agent: Callable[..., str] | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._run_agent = run_agent

    def evaluate(
        self,
        candidates: list[ArchitectureCandidate],
        authoritative_constraints: list[ConstraintFact],
    ) -> list[CandidateAssessment]:
        """Evaluate each candidate against constraints.

        Parameters
        ----------
        candidates:
            Candidates to evaluate.
        authoritative_constraints:
            Constraints to check satisfaction against.

        Returns
        -------
        list[CandidateAssessment]
            One assessment per candidate, in the same order.
        """
        if self._run_agent is not None:
            return self._evaluate_via_llm(candidates, authoritative_constraints)
        return self._evaluate_heuristic(candidates, authoritative_constraints)

    def select_or_block(
        self,
        decision_point: DecisionPoint,
        candidates: list[ArchitectureCandidate],
        assessments: list[CandidateAssessment],
        authoritative_constraints: list[ConstraintFact],
    ) -> DecisionOutcome:
        """Select the best candidate or block the decision.

        Selection logic:
        1. If any candidate has recommendation=accept, no blockers, and
           no unresolved constraints: commit the best one (lowest risk).
        2. If a candidate needs human authority: block with
           decision_requirements.
        3. Otherwise: block with under_spec_events.

        Parameters
        ----------
        decision_point:
            The decision being resolved.
        candidates:
            Evaluated candidates.
        assessments:
            Assessments corresponding to candidates.
        authoritative_constraints:
            Constraints for validation.

        Returns
        -------
        DecisionOutcome
            Committed or blocked outcome.
        """
        if not candidates or not assessments:
            return DecisionOutcome(
                decision_id=decision_point.decision_id,
                committed=False,
                decision_requirements=["No candidates available"],
            )

        assessment_map = {a.candidate_id: a for a in assessments}

        # Find acceptable candidates (no blockers, no unknowns, accept recommendation)
        acceptable: list[tuple[ArchitectureCandidate, CandidateAssessment]] = []
        needs_human: list[tuple[ArchitectureCandidate, CandidateAssessment]] = []

        for cand in candidates:
            assess = assessment_map.get(cand.candidate_id)
            if assess is None:
                continue

            if assess.recommendation == "accept" and not assess.blockers:
                has_unknown = any(
                    v == "unknown" for v in assess.constraint_satisfaction.values()
                )
                if not has_unknown:
                    acceptable.append((cand, assess))
                else:
                    needs_human.append((cand, assess))
            elif assess.recommendation == "needs_human":
                needs_human.append((cand, assess))

        # Path 1: commit the lowest-risk acceptable candidate
        if acceptable:
            acceptable.sort(key=lambda pair: pair[1].risk_score)
            best_cand, best_assess = acceptable[0]

            wiring_intentions = _extract_wiring_intentions(best_cand)
            new_constraints = _extract_new_constraint_ids(best_cand)

            return DecisionOutcome(
                decision_id=decision_point.decision_id,
                committed=True,
                selected_candidate_id=best_cand.candidate_id,
                wiring_intentions=wiring_intentions,
                new_constraints=new_constraints,
            )

        # Path 2: needs human authority
        if needs_human:
            best_cand, best_assess = needs_human[0]
            reqs = list(best_cand.decision_requirements)
            if not reqs:
                reqs = [
                    f"Human review required for {decision_point.decision_id}: "
                    f"{decision_point.description}"
                ]

            return DecisionOutcome(
                decision_id=decision_point.decision_id,
                committed=False,
                selected_candidate_id=best_cand.candidate_id,
                decision_requirements=reqs,
            )

        # Path 3: all rejected / blocked
        all_blockers: list[str] = []
        for cand in candidates:
            assess = assessment_map.get(cand.candidate_id)
            if assess and assess.blockers:
                all_blockers.extend(assess.blockers)

        under_spec_events = [
            {"type": "architecture_blocked", "detail": b} for b in all_blockers
        ] if all_blockers else [
            {
                "type": "architecture_blocked",
                "detail": f"All candidates rejected for {decision_point.decision_id}",
            }
        ]

        return DecisionOutcome(
            decision_id=decision_point.decision_id,
            committed=False,
            under_spec_events=under_spec_events,
        )

    # ------------------------------------------------------------------
    # Internal evaluation methods
    # ------------------------------------------------------------------

    def _evaluate_via_llm(
        self,
        candidates: list[ArchitectureCandidate],
        authoritative_constraints: list[ConstraintFact],
    ) -> list[CandidateAssessment]:
        """Use the LLM to evaluate candidates."""
        prompt = _build_evaluation_prompt(candidates, authoritative_constraints)

        assert self._run_agent is not None
        raw_output = self._run_agent(prompt)

        assessments = _parse_evaluation_output(raw_output, candidates)

        # Ensure one assessment per candidate
        assessed_ids = {a.candidate_id for a in assessments}
        for cand in candidates:
            if cand.candidate_id not in assessed_ids:
                assessments.append(
                    CandidateAssessment(
                        candidate_id=cand.candidate_id,
                        recommendation="needs_human",
                        blockers=["LLM did not assess this candidate"],
                    )
                )

        return assessments

    def _evaluate_heuristic(
        self,
        candidates: list[ArchitectureCandidate],
        authoritative_constraints: list[ConstraintFact],
    ) -> list[CandidateAssessment]:
        """Deterministic heuristic evaluation (no LLM)."""
        constraint_ids = [c.constraint_id for c in authoritative_constraints]
        human_required_ids = {
            c.constraint_id for c in authoritative_constraints
            if c.authority_required == "human_required"
        }

        assessments: list[CandidateAssessment] = []
        for cand in candidates:
            satisfaction: dict[str, str] = {}
            blockers: list[str] = []

            for cid in constraint_ids:
                if cid in human_required_ids:
                    satisfaction[cid] = "unknown"
                else:
                    satisfaction[cid] = "satisfied"

            # Check for decision_requirements -> needs_human
            if cand.decision_requirements:
                recommendation = "needs_human"
            elif human_required_ids:
                recommendation = "needs_human"
            elif blockers:
                recommendation = "reject"
            else:
                recommendation = "accept"

            risk_score = 0.0
            if cand.assumptions:
                risk_score += 0.1 * len(cand.assumptions)
            if cand.decision_requirements:
                risk_score += 0.2 * len(cand.decision_requirements)
            risk_score = min(risk_score, 1.0)

            assessments.append(
                CandidateAssessment(
                    candidate_id=cand.candidate_id,
                    constraint_satisfaction=satisfaction,
                    blockers=blockers,
                    risk_score=risk_score,
                    reversibility=_estimate_reversibility(cand),
                    recommendation=recommendation,
                )
            )

        return assessments


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_wiring_intentions(candidate: ArchitectureCandidate) -> list[dict[str, Any]]:
    """Extract wiring intentions from a committed candidate's proposal."""
    approach = candidate.proposal.get("approach", "")
    details = candidate.proposal.get("details", "")
    return [
        {
            "source": candidate.decision_id,
            "approach": approach,
            "details": details,
            "scope": candidate.scope,
        }
    ]


def _extract_new_constraint_ids(candidate: ArchitectureCandidate) -> list[str]:
    """Extract IDs of new constraints introduced by the candidate."""
    ids: list[str] = []
    for section in ("software", "non_software"):
        section_data = candidate.constraints_introduced.get(section, {})
        if isinstance(section_data, dict):
            ids.extend(section_data.keys())
    return ids


def _estimate_reversibility(candidate: ArchitectureCandidate) -> str:
    """Estimate how reversible a candidate is based on its scope and assumptions."""
    scope = candidate.scope.lower()
    if "system" in scope:
        return "HARD"
    if "inter" in scope or "cross" in scope:
        return "MEDIUM"
    return "EASY"


def _build_evaluation_prompt(
    candidates: list[ArchitectureCandidate],
    authoritative_constraints: list[ConstraintFact],
) -> str:
    """Build the LLM prompt for candidate evaluation."""
    constraints_text = "\n".join(
        f"  - [{c.constraint_id}] {c.question}: {c.answer} "
        f"(authority: {c.authority_required})"
        for c in authoritative_constraints[:30]
    ) or "  (none)"

    candidates_text_parts: list[str] = []
    for cand in candidates:
        candidates_text_parts.append(
            f"  Candidate {cand.candidate_id}:\n"
            f"    Position: {cand.position}\n"
            f"    Approach: {cand.proposal.get('approach', '')}\n"
            f"    Details: {cand.proposal.get('details', '')}\n"
            f"    Assumptions: {cand.assumptions}"
        )
    candidates_text = "\n".join(candidates_text_parts) or "  (none)"

    return f"""Evaluate the following architecture candidates against the authoritative constraints.

Constraints:
{constraints_text}

Candidates:
{candidates_text}

For each candidate, return a JSON array of objects with keys:
- candidate_id: the candidate ID
- constraint_satisfaction: dict mapping constraint_id to "satisfied" | "violated" | "unknown"
- blockers: list of blocking issues (empty if none)
- risk_score: 0.0 to 1.0
- reversibility: "EASY" | "MEDIUM" | "HARD"
- recommendation: "accept" | "reject" | "needs_human"
"""


def _parse_evaluation_output(
    raw: str,
    candidates: list[ArchitectureCandidate],
) -> list[CandidateAssessment]:
    """Parse LLM evaluation output into CandidateAssessment instances."""
    try:
        text = raw.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            return []
        parsed = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse evaluation output")
        return []

    assessments: list[CandidateAssessment] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        rec = item.get("recommendation", "needs_human")
        if rec not in ("accept", "reject", "needs_human"):
            rec = "needs_human"

        assessments.append(
            CandidateAssessment(
                candidate_id=item.get("candidate_id", ""),
                constraint_satisfaction=dict(item.get("constraint_satisfaction", {})),
                blockers=list(item.get("blockers", [])),
                risk_score=float(item.get("risk_score", 0.5)),
                reversibility=item.get("reversibility", "MEDIUM"),
                recommendation=rec,
            )
        )

    return assessments
