"""Planning-phase constraint coverage check.

Before implementation begins, PlanStep checks that every decision
requirement in the plan is covered by an existing constraint.
Uncovered decisions become under-spec events that block the slice.
"""

from __future__ import annotations

import hashlib
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
    constraints_snapshot_hash: str = ""

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

    A decision is covered only when ``decision_id`` matches a persisted
    ``constraint_id``.

    Args:
        constraints_store: The file-based constraints store.
        slice_id: Current slice identifier.
        decision: Decision requirement dict from the planning agent.

    Returns:
        CoverageResult with coverage status and rationale.
    """
    constraints = constraints_store.load_merged(slice_id)
    decision_id = decision.get("decision_id", "")
    decision_question = str(decision.get("question", "")).strip()

    if not decision_id:
        return CoverageResult(
            covered=False,
            rationale="Decision requirement missing decision_id",
        )

    covering: list[str] = []

    for constraint in constraints:
        status = str(constraint.status or "ACTIVE").strip().upper()
        if status != "ACTIVE":
            continue
        if constraint.constraint_id and constraint.constraint_id == decision_id:
            covering.append(constraint.constraint_id)

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
    intentions: list[dict[str, Any]] | None = None,
    plan_outputs: dict[str, Any] | None = None,
) -> PlanningGateResult:
    """Run the planning gate on all plan intentions.

    For each intention with decision_requirements, checks constraint
    coverage. Uncovered decisions produce under_spec_events.

    Args:
        constraints_store: Constraint persistence layer.
        slice_id: Current slice identifier.
        intentions: Plan intentions from the planning agent.
        plan_outputs: Optional full planner PLAN output payload.

    Returns:
        PlanningGateResult with covered/uncovered partitions.
    """
    result = PlanningGateResult()
    result.constraints_snapshot_hash = constraints_store.snapshot_hash(slice_id)

    def _needed_for_target(intention: dict[str, Any]) -> Any:
        target_files = intention.get("target_files", [])
        if isinstance(target_files, list):
            normalized = [str(item) for item in target_files if str(item).strip()]
            if normalized:
                return normalized
        return intention.get("target_file", "")

    def _event_id(
        *,
        decision_id: str,
        intention_id: str,
        question: str,
        suffix: str = "",
    ) -> str:
        normalized_decision_id = str(decision_id).strip()
        if normalized_decision_id:
            return normalized_decision_id
        seed = f"{intention_id}|{question}|{suffix}".strip("|")
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12] if seed else "unknown"
        return f"plan-underspec-{digest}"

    plan_intentions = (
        plan_outputs.get("intentions", [])
        if isinstance(plan_outputs, dict)
        else (intentions if isinstance(intentions, list) else [])
    )
    if not isinstance(plan_intentions, list):
        plan_intentions = []

    for intention_index, intention in enumerate(plan_intentions):
        if not isinstance(intention, dict):
            continue
        intention_id = (
            str(intention.get("intention_id", "")).strip() or f"intention-{intention_index}"
        )
        if "decision_requirements" not in intention:
            question = (
                f"Planning output for intention '{intention_id}' is missing decision_requirements. "
                "Provide an explicit list (empty when no decisions are needed)."
            )
            result.uncovered_decisions.append(
                {
                    "decision_id": "",
                    "question": question,
                    "intention_id": intention_id,
                    "rationale": "decision_requirements field is required per intention",
                }
            )
            result.under_spec_events.append(
                {
                    "event_id": _event_id(
                        decision_id="",
                        intention_id=intention_id,
                        question=question,
                        suffix="missing-decision-requirements",
                    ),
                    "kind": "AMBIGUOUS_REQUIREMENT",
                    "question": question,
                    "context": {
                        "intention_id": intention_id,
                        "target_file": intention.get("target_file", ""),
                        "target_files": intention.get("target_files", []),
                        "target_symbols": intention.get("target_symbols", []),
                    },
                    "evidence_paths": [],
                }
            )
            continue

        decision_reqs = intention.get("decision_requirements")
        if not isinstance(decision_reqs, list):
            question = (
                f"Planning output for intention '{intention_id}' has "
                "non-list decision_requirements. "
                "Provide an explicit list (empty when no decisions are needed)."
            )
            result.uncovered_decisions.append(
                {
                    "decision_id": "",
                    "question": question,
                    "intention_id": intention_id,
                    "rationale": "decision_requirements must be a list",
                }
            )
            result.under_spec_events.append(
                {
                    "event_id": _event_id(
                        decision_id="",
                        intention_id=intention_id,
                        question=question,
                        suffix="invalid-decision-requirements",
                    ),
                    "kind": "AMBIGUOUS_REQUIREMENT",
                    "question": question,
                    "context": {
                        "intention_id": intention_id,
                        "decision_requirements": decision_reqs,
                        "target_file": intention.get("target_file", ""),
                        "target_files": intention.get("target_files", []),
                        "target_symbols": intention.get("target_symbols", []),
                    },
                    "evidence_paths": [],
                }
            )
            continue
        if not decision_reqs:
            continue

        for decision_index, decision in enumerate(decision_reqs):
            if not isinstance(decision, dict):
                question = (
                    f"Planning output for intention '{intention_id}' includes a non-object "
                    "decision requirement entry."
                )
                result.uncovered_decisions.append(
                    {
                        "decision_id": "",
                        "question": question,
                        "intention_id": intention_id,
                        "rationale": "decision requirement entries must be objects",
                    }
                )
                result.under_spec_events.append(
                    {
                        "event_id": _event_id(
                            decision_id="",
                            intention_id=intention_id,
                            question=question,
                            suffix=f"invalid-entry-{decision_index}",
                        ),
                        "kind": "AMBIGUOUS_REQUIREMENT",
                        "question": question,
                        "context": {
                            "intention_id": intention_id,
                            "decision_entry": decision,
                            "target_file": intention.get("target_file", ""),
                            "target_files": intention.get("target_files", []),
                            "target_symbols": intention.get("target_symbols", []),
                        },
                        "evidence_paths": [],
                    }
                )
                continue

            decision_id = str(decision.get("decision_id", "")).strip()
            question = str(decision.get("question", "")).strip()
            if not question:
                question = (
                    f"What decision is required for intention '{intention_id}' "
                    "(decision_requirements entry missing question)?"
                )
            options_raw = decision.get("options", [])
            options = (
                [str(item).strip() for item in options_raw if str(item).strip()]
                if isinstance(options_raw, list)
                else []
            )
            needed_for = decision.get("needed_for", _needed_for_target(intention))

            coverage = check_decision_coverage(
                constraints_store=constraints_store,
                slice_id=slice_id,
                decision=decision,
            )

            if coverage.covered:
                result.covered_decisions.append(
                    {
                        "decision_id": decision_id,
                        "question": question,
                        "covering_constraints": coverage.covering_constraints,
                    }
                )
            else:
                result.uncovered_decisions.append(
                    {
                        "decision_id": decision_id,
                        "question": question,
                        "intention_id": intention_id,
                        "rationale": coverage.rationale,
                    }
                )
                result.under_spec_events.append(
                    {
                        "event_id": _event_id(
                            decision_id=decision_id,
                            intention_id=intention_id,
                            question=question,
                            suffix=f"uncovered-{decision_index}",
                        ),
                        "kind": "MISSING_CONSTRAINT",
                        "question": question,
                        "context": {
                            "decision_id": decision_id,
                            "intention_id": intention_id,
                            "options": options,
                            "needed_for": needed_for,
                            "coverage_rationale": coverage.rationale,
                            "target_file": intention.get("target_file", ""),
                            "target_files": intention.get("target_files", []),
                            "target_symbols": intention.get("target_symbols", []),
                        },
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
