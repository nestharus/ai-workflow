"""Architecture candidate proposer orchestrator.

Assigns distinct tradeoff positions to K proposer invocations and
collects the resulting candidates.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .types import ArchitectureCandidate, DecisionPoint, ScopePacket

logger = logging.getLogger(__name__)

# Default tradeoff axes used when the decision point has no explicit axes.
_DEFAULT_TRADEOFF_AXES = [
    "performance",
    "maintainability",
    "simplicity",
    "extensibility",
    "reliability",
]


class ProposerOrchestrator:
    """Orchestrates K architecture candidate proposals per decision point.

    Parameters
    ----------
    workspace_root:
        Root directory of the workspace.
    k:
        Number of candidates to generate per decision (default 3).
    run_agent:
        Optional callable for LLM calls.  Signature:
        ``(prompt: str) -> str``.  When *None* a stub candidate is
        returned.
    """

    def __init__(
        self,
        workspace_root: Path,
        k: int = 3,
        run_agent: Callable[..., str] | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._k = max(1, k)
        self._run_agent = run_agent

    def assign_tradeoff_positions(
        self,
        decision_point: DecisionPoint,
        k: int | None = None,
    ) -> list[dict[str, str]]:
        """Select relevant tradeoff axes and assign K distinct positions.

        Each position is a dict mapping axis names to priorities
        (``"prioritize"`` or ``"sacrifice"``).

        Parameters
        ----------
        decision_point:
            The decision point to assign positions for.
        k:
            Override for the number of positions (defaults to ``self._k``).

        Returns
        -------
        list[dict[str, str]]
            K distinct tradeoff position assignments.
        """
        actual_k = k if k is not None else self._k

        axes = _select_axes(decision_point, actual_k)

        positions: list[dict[str, str]] = []
        for i in range(actual_k):
            position: dict[str, str] = {}
            for j, axis in enumerate(axes):
                if (i + j) % actual_k == 0:
                    position[axis] = "prioritize"
                else:
                    position[axis] = "sacrifice"
            positions.append(position)

        return positions

    def run_proposers(
        self,
        decision_point: DecisionPoint,
        scope_packet: ScopePacket,
        tradeoff_positions: list[dict[str, str]] | None = None,
    ) -> list[ArchitectureCandidate]:
        """Generate architecture candidates for a decision point.

        Parameters
        ----------
        decision_point:
            The decision being addressed.
        scope_packet:
            Context bundle with constraints, artifacts, and state.
        tradeoff_positions:
            Pre-assigned positions.  If *None*, positions are generated
            via ``assign_tradeoff_positions``.

        Returns
        -------
        list[ArchitectureCandidate]
            One candidate per tradeoff position.
        """
        if tradeoff_positions is None:
            tradeoff_positions = self.assign_tradeoff_positions(decision_point)

        candidates: list[ArchitectureCandidate] = []
        for position in tradeoff_positions:
            candidate = self._propose_one(decision_point, scope_packet, position)
            candidates.append(candidate)

        return candidates

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _propose_one(
        self,
        decision_point: DecisionPoint,
        scope_packet: ScopePacket,
        position: dict[str, str],
    ) -> ArchitectureCandidate:
        """Generate a single candidate for a given tradeoff position."""
        candidate_id = f"CAND-{uuid.uuid4().hex[:8]}"

        if self._run_agent is not None:
            return self._propose_via_llm(
                decision_point=decision_point,
                scope_packet=scope_packet,
                position=position,
                candidate_id=candidate_id,
            )

        return ArchitectureCandidate(
            candidate_id=candidate_id,
            decision_id=decision_point.decision_id,
            scope=decision_point.scope,
            position=position,
            proposal={"approach": "stub_proposal", "details": "No LLM available"},
            constraints_introduced={"software": {}, "non_software": {}},
            decision_requirements=[],
            assumptions=[],
            trace=[f"heuristic-proposal for {decision_point.decision_id}"],
        )

    def _propose_via_llm(
        self,
        *,
        decision_point: DecisionPoint,
        scope_packet: ScopePacket,
        position: dict[str, str],
        candidate_id: str,
    ) -> ArchitectureCandidate:
        """Use the LLM to generate a candidate proposal."""
        prompt = _build_proposal_prompt(decision_point, scope_packet, position)

        assert self._run_agent is not None
        raw_output = self._run_agent(prompt)

        return _parse_proposal_output(
            raw_output,
            candidate_id=candidate_id,
            decision_id=decision_point.decision_id,
            scope=decision_point.scope,
            position=position,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _select_axes(decision_point: DecisionPoint, k: int) -> list[str]:
    """Pick tradeoff axes relevant to the decision point."""
    scope = decision_point.scope.lower()
    desc = decision_point.description.lower()

    axes = list(_DEFAULT_TRADEOFF_AXES)

    if "system" in scope or "cross_slice" in decision_point.impact.blast_radius.lower():
        if "scalability" not in axes:
            axes.insert(0, "scalability")
    if "security" in desc:
        if "security" not in axes:
            axes.insert(0, "security")

    return axes[:max(k, 2)]


def _build_proposal_prompt(
    decision_point: DecisionPoint,
    scope_packet: ScopePacket,
    position: dict[str, str],
) -> str:
    """Build the LLM prompt for a single proposal."""
    constraints_text = "\n".join(
        f"  - [{c.constraint_id}] {c.question}: {c.answer}"
        for c in scope_packet.authoritative_constraints[:20]
    ) or "  (none)"

    position_text = "\n".join(
        f"  - {axis}: {priority}" for axis, priority in position.items()
    ) or "  (none)"

    return f"""Propose an architecture candidate for the following decision.

Decision: {decision_point.description}
Scope: {decision_point.scope}
Impact: {decision_point.impact.impact} / Blast radius: {decision_point.impact.blast_radius}

Tradeoff position (prioritize/sacrifice):
{position_text}

Authoritative constraints:
{constraints_text}

Current architecture state refs: {scope_packet.current_arch_state_refs}

Propose a concrete architecture approach that honors the tradeoff position.
Return a JSON object with keys:
- approach: short name
- details: description of the approach
- constraints_introduced: {{"software": {{}}, "non_software": {{}}}}
- decision_requirements: list of outstanding decisions needed
- assumptions: list of assumptions made
"""


def _parse_proposal_output(
    raw: str,
    *,
    candidate_id: str,
    decision_id: str,
    scope: str,
    position: dict[str, str],
) -> ArchitectureCandidate:
    """Parse LLM proposal output into an ArchitectureCandidate."""
    proposal: dict[str, Any] = {}
    constraints_introduced: dict[str, Any] = {"software": {}, "non_software": {}}
    decision_requirements: list[str] = []
    assumptions: list[str] = []

    try:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("No JSON object found in output")
        parsed = json.loads(text[start : end + 1])
        proposal = {
            "approach": parsed.get("approach", ""),
            "details": parsed.get("details", ""),
        }
        ci = parsed.get("constraints_introduced", {})
        constraints_introduced = {
            "software": dict(ci.get("software", {})),
            "non_software": dict(ci.get("non_software", {})),
        }
        decision_requirements = list(parsed.get("decision_requirements", []))
        assumptions = list(parsed.get("assumptions", []))
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse proposal output for %s", candidate_id)
        proposal = {"approach": "parse_error", "raw": raw[:500]}

    return ArchitectureCandidate(
        candidate_id=candidate_id,
        decision_id=decision_id,
        scope=scope,
        position=position,
        proposal=proposal,
        constraints_introduced=constraints_introduced,
        decision_requirements=decision_requirements,
        assumptions=assumptions,
        trace=[f"llm-proposal for {decision_id}"],
    )
