"""Decision point detection from gaps, discovery, and evidence.

Uses an LLM call (via injectable ``run_agent``) to examine gaps, architecture
files, and evidence for a slice, then filters out points already covered by
existing authoritative constraints.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spec_manager.planner.constraints.types import ConstraintFact, ImpactClassification

from .types import DecisionPoint

logger = logging.getLogger(__name__)


class DecisionPointDetector:
    """Detects architecture decision points from slice context.

    Parameters
    ----------
    workspace_root:
        Root directory of the workspace.
    run_agent:
        Optional callable for LLM calls.  Signature:
        ``(prompt: str) -> str``.  When *None* the detector falls back
        to a heuristic-only mode.
    """

    def __init__(
        self,
        workspace_root: Path,
        run_agent: Callable[..., str] | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._run_agent = run_agent

    def detect(
        self,
        *,
        slice_id: str,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
        evidence_refs: list[str] | None = None,
        authoritative_constraints: list[ConstraintFact] | None = None,
    ) -> list[DecisionPoint]:
        """Detect decision points for a slice.

        Parameters
        ----------
        slice_id:
            Identifier of the slice being analysed.
        gaps:
            Gap analysis results for the slice.
        discovery:
            Discovery graph (nodes + edges) for the slice.
        evidence_refs:
            Optional evidence references to consider.
        authoritative_constraints:
            Existing constraints that may cover decisions.

        Returns
        -------
        list[DecisionPoint]
            Decision points that are NOT already covered.
        """
        if authoritative_constraints is None:
            authoritative_constraints = []
        if evidence_refs is None:
            evidence_refs = []

        raw_points = self._detect_raw(
            slice_id=slice_id,
            gaps=gaps,
            discovery=discovery,
            evidence_refs=evidence_refs,
        )

        return self._filter_decided(raw_points, authoritative_constraints)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _detect_raw(
        self,
        *,
        slice_id: str,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
        evidence_refs: list[str],
    ) -> list[DecisionPoint]:
        """Produce raw (unfiltered) decision points."""
        if self._run_agent is not None:
            return self._detect_via_llm(
                slice_id=slice_id,
                gaps=gaps,
                discovery=discovery,
                evidence_refs=evidence_refs,
            )
        return self._detect_heuristic(
            slice_id=slice_id,
            gaps=gaps,
            discovery=discovery,
        )

    def _detect_via_llm(
        self,
        *,
        slice_id: str,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
        evidence_refs: list[str],
    ) -> list[DecisionPoint]:
        """Use the LLM to identify decision points."""
        prompt = _build_detection_prompt(
            slice_id=slice_id,
            gaps=gaps,
            discovery=discovery,
            evidence_refs=evidence_refs,
        )

        assert self._run_agent is not None
        raw_output = self._run_agent(prompt)

        return _parse_detection_output(raw_output, slice_id)

    def _detect_heuristic(
        self,
        *,
        slice_id: str,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> list[DecisionPoint]:
        """Fallback heuristic when no LLM is available.

        Creates one decision point per gap that mentions architecture
        keywords.
        """
        arch_keywords = {
            "architecture",
            "pattern",
            "design",
            "topology",
            "interface",
            "coupling",
            "dependency",
            "layer",
            "module",
            "component",
        }
        points: list[DecisionPoint] = []

        for gap in gaps:
            desc = gap.get("description", "") + " " + gap.get("target", "")
            if any(kw in desc.lower() for kw in arch_keywords):
                point = DecisionPoint(
                    decision_id=f"DEC-{uuid.uuid4().hex[:8]}",
                    scope=gap.get("scope", "intra:LIB"),
                    description=gap.get("description", ""),
                    trigger_evidence=[gap.get("target", "")],
                    impact=ImpactClassification(
                        impact="MEDIUM",
                        blast_radius="SLICE",
                    ),
                    owner_slice_id=slice_id,
                    status="OPEN",
                )
                points.append(point)

        return points

    def _filter_decided(
        self,
        points: list[DecisionPoint],
        authoritative_constraints: list[ConstraintFact],
    ) -> list[DecisionPoint]:
        """Remove points already covered by authoritative constraints."""
        if not authoritative_constraints:
            return list(points)

        decided_scopes: set[str] = set()
        decided_questions: set[str] = set()
        for c in authoritative_constraints:
            if c.status == "ACTIVE" and c.validated:
                decided_scopes.add(c.scope)
                decided_questions.add(c.question.lower())

        filtered: list[DecisionPoint] = []
        for point in points:
            if point.scope in decided_scopes and point.description.lower() in decided_questions:
                logger.debug(
                    "Filtering out decided point %s (covered by constraint)",
                    point.decision_id,
                )
                continue
            filtered.append(point)

        return filtered


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def _build_detection_prompt(
    *,
    slice_id: str,
    gaps: list[dict[str, Any]],
    discovery: dict[str, Any],
    evidence_refs: list[str],
) -> str:
    """Build the LLM prompt for decision detection."""
    nodes_summary = []
    for node in discovery.get("nodes", [])[:50]:
        nodes_summary.append(
            f"  - {node.get('kind', '?')}: {node.get('name', node.get('id', '?'))}"
        )
    nodes_text = "\n".join(nodes_summary) if nodes_summary else "  (none)"

    gaps_summary = []
    for gap in gaps[:30]:
        gaps_summary.append(f"  - {gap.get('target', '?')}: {gap.get('description', '')}")
    gaps_text = "\n".join(gaps_summary) if gaps_summary else "  (none)"

    evidence_text = (
        "\n".join(f"  - {ref}" for ref in evidence_refs[:20]) if evidence_refs else "  (none)"
    )

    return f"""Analyze the following slice for architecture decision points.

Slice ID: {slice_id}

Discovery nodes:
{nodes_text}

Gaps:
{gaps_text}

Evidence references:
{evidence_text}

Identify architecture decisions that need to be made. For each, provide:
- scope: the scope of the decision (intra:LIB, inter:A->B, system)
- description: what needs to be decided
- trigger_evidence: which evidence triggered this
- impact: LOW/MEDIUM/HIGH
- blast_radius: LOCAL/SLICE/CROSS_SLICE/SYSTEM

Return a JSON array of objects with keys: scope, description,
trigger_evidence (list), impact, blast_radius.
Return [] if no architecture decisions are needed.
"""


def _parse_detection_output(raw: str, slice_id: str) -> list[DecisionPoint]:
    """Parse LLM output into DecisionPoint instances."""
    try:
        text = raw.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            return []
        parsed = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse decision detection output")
        return []

    points: list[DecisionPoint] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        point = DecisionPoint(
            decision_id=f"DEC-{uuid.uuid4().hex[:8]}",
            scope=item.get("scope", "intra:LIB"),
            description=item.get("description", ""),
            trigger_evidence=list(item.get("trigger_evidence", [])),
            impact=ImpactClassification(
                impact=item.get("impact", "MEDIUM"),
                blast_radius=item.get("blast_radius", "SLICE"),
            ),
            owner_slice_id=slice_id,
            status="OPEN",
        )
        points.append(point)

    return points
