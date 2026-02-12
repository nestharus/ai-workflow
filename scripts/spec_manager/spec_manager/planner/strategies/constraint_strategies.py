"""Constraint-related planning strategies.

Six strategies that handle impact classification, constraint loading,
problem framing, constraint enrichment, non-software checklist detection,
and question composition for under-spec events.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spec_manager.planner.constraints.impact import classify_impact
from spec_manager.planner.constraints.store_adapter import ConstraintStoreAdapter
from spec_manager.planner.constraints.types import (
    ConstraintContext,
    ConstraintHypothesis,
    ConflictReport,
    DecisionRequirement,
    ProblemFrame,
)

from .protocol import PlanningSession

logger = logging.getLogger(__name__)

# Non-software dimensions that trigger checklist items.
_NON_SOFTWARE_DIMENSIONS = ("legal", "economic", "organizational", "temporal", "operational")


class ImpactClassifierStrategy:
    """Always runs. Classifies change impact deterministically."""

    @property
    def name(self) -> str:
        return "impact_classifier"

    def __init__(self) -> None:
        pass

    def run(self, session: PlanningSession) -> PlanningSession:
        layer = session.ctx.get("layer", "L1")
        gap_kinds = [g.get("kind", "") for g in session.gaps if g.get("kind")]
        touched = session.ctx.get("touched_files_count", 0)
        ext_dep = session.ctx.get("introduces_external_dep", False)
        infra = session.ctx.get("introduces_infra", False)
        cross_lib = session.ctx.get("cross_library_contract", False)

        session.impact = classify_impact(
            layer=layer,
            gap_kinds=gap_kinds,
            touched_files_count=touched,
            introduces_external_dep=ext_dep,
            introduces_infra=infra,
            cross_library_contract=cross_lib,
        )
        return session


class ConstraintCollectionStrategy:
    """Always runs. Loads constraints from the store into the session."""

    @property
    def name(self) -> str:
        return "constraint_collection"

    def __init__(self, workspace_root: Path) -> None:
        self._adapter = ConstraintStoreAdapter(workspace_root)

    def run(self, session: PlanningSession) -> PlanningSession:
        slice_id = session.ctx.get("slice_id", "__system__")

        facts = self._adapter.load_merged(slice_id)
        hypotheses = self._adapter.load_hypotheses(slice_id)

        decisions = [f for f in facts if f.decision_type]
        authoritative = [f for f in facts if not f.decision_type]

        session.constraint_context = ConstraintContext(
            authoritative=authoritative,
            decisions=decisions,
            unverified=hypotheses,
        )
        return session


class ProblemFramerStrategy:
    """Gated by impact >= MEDIUM. Uses LLM to frame the problem."""

    @property
    def name(self) -> str:
        return "problem_framer"

    def __init__(self, run_agent: Callable[..., str] | None = None) -> None:
        self._run_agent = run_agent

    def run(self, session: PlanningSession) -> PlanningSession:
        if not _impact_at_least_medium(session):
            return session

        if self._run_agent is None:
            session.problem_frame = ProblemFrame(
                goal="Resolve identified gaps",
                scope=session.ctx.get("slice_id", "unknown"),
            )
            return session

        prompt = _build_problem_frame_prompt(session)
        raw = self._run_agent(prompt)
        session.problem_frame = _parse_problem_frame(raw)
        return session


class ConstraintEnricherStrategy:
    """Gated by impact >= MEDIUM. Uses LLM to discover hypotheses, decisions, and conflicts."""

    @property
    def name(self) -> str:
        return "constraint_enricher"

    def __init__(self, run_agent: Callable[..., str] | None = None) -> None:
        self._run_agent = run_agent

    def run(self, session: PlanningSession) -> PlanningSession:
        if not _impact_at_least_medium(session):
            return session

        if self._run_agent is None:
            return session

        prompt = _build_enrichment_prompt(session)
        raw = self._run_agent(prompt)
        hypotheses, requirements, conflict_report = _parse_enrichment_output(raw)

        session.hypotheses.extend(hypotheses)
        session.decision_requirements.extend(requirements)
        if conflict_report and conflict_report.conflicts:
            session.conflict_report = conflict_report

        return session


class NonSoftwareChecklistStrategy:
    """Gated by impact >= MEDIUM. Appends decision requirements for non-software dimensions."""

    @property
    def name(self) -> str:
        return "non_software_checklist"

    def __init__(self) -> None:
        pass

    def run(self, session: PlanningSession) -> PlanningSession:
        if not _impact_at_least_medium(session):
            return session

        existing_dimensions = {dr.dimension for dr in session.decision_requirements}

        for dim in _NON_SOFTWARE_DIMENSIONS:
            if dim in existing_dimensions:
                continue

            # Check if gaps or context mention this dimension
            gap_text = " ".join(
                g.get("description", "") + " " + g.get("target", "")
                for g in session.gaps
            ).lower()

            ctx_text = json.dumps(session.ctx).lower() if session.ctx else ""

            if dim in gap_text or dim in ctx_text:
                session.decision_requirements.append(
                    DecisionRequirement(
                        decision_id=f"NSC-{dim.upper()[:4]}",
                        question=f"Has the {dim} dimension been considered for this change?",
                        kind="non_software_checklist",
                        dimension=dim,
                        scope=session.ctx.get("scope", "intra:LIB"),
                        impact=session.impact.impact if session.impact else "MEDIUM",
                        options=["yes_addressed", "not_applicable", "needs_review"],
                        needed_for=[session.ctx.get("slice_id", "unknown")],
                    )
                )

        return session


class TradeoffMapperStrategy:
    """Always runs. Loads tradeoff axes from TRADEOFFS.md or uses defaults.

    Looks for ``design/TRADEOFFS.md`` in the workspace root. If found,
    extracts axis names from markdown headings (``## <axis>`` or
    ``- <axis>``).  Falls back to a standard set of architectural
    tradeoff dimensions.
    """

    _DEFAULT_AXES = [
        "performance",
        "maintainability",
        "simplicity",
        "extensibility",
        "reliability",
        "scalability",
        "security",
    ]

    @property
    def name(self) -> str:
        return "tradeoff_mapper"

    def __init__(self, workspace_root: Path | None = None) -> None:
        self._workspace_root = workspace_root

    def run(self, session: PlanningSession) -> PlanningSession:
        axes = self._load_axes()
        session.tradeoff_axes = axes
        return session

    def _load_axes(self) -> list[str]:
        """Try loading TRADEOFFS.md; fall back to defaults."""
        if self._workspace_root is None:
            return list(self._DEFAULT_AXES)

        for candidate in [
            self._workspace_root / "design" / "TRADEOFFS.md",
            self._workspace_root / "TRADEOFFS.md",
        ]:
            if candidate.exists():
                try:
                    return self._parse_axes(candidate.read_text(encoding="utf-8"))
                except OSError:
                    pass

        return list(self._DEFAULT_AXES)

    @staticmethod
    def _parse_axes(content: str) -> list[str]:
        """Extract axis names from markdown headings and list items."""
        import re

        axes: list[str] = []
        seen: set[str] = set()

        for line in content.splitlines():
            line = line.strip()
            # Match ## headings or - list items
            m = re.match(r"^#{1,3}\s+(.+)", line) or re.match(r"^[-*]\s+\*?\*?(.+?)\*?\*?\s*$", line)
            if m:
                axis = m.group(1).strip().lower()
                # Skip generic headings
                if axis and axis not in seen and len(axis) < 40 and axis not in ("overview", "introduction", "summary", "tradeoffs", "tradeoff axes"):
                    axes.append(axis)
                    seen.add(axis)

        return axes if axes else list(TradeoffMapperStrategy._DEFAULT_AXES)


class QuestionComposerStrategy:
    """Gated by interactive mode. Refines under-spec events into clearer questions."""

    @property
    def name(self) -> str:
        return "question_composer"

    def __init__(self, run_agent: Callable[..., str] | None = None) -> None:
        self._run_agent = run_agent

    def run(self, session: PlanningSession) -> PlanningSession:
        if not session.ctx.get("interactive", False):
            return session

        if not session.under_spec_events:
            return session

        if self._run_agent is None:
            return session

        prompt = _build_question_prompt(session.under_spec_events)
        raw = self._run_agent(prompt)
        refined = _parse_question_output(raw, session.under_spec_events)
        session.under_spec_events = refined
        return session


# ---------------------------------------------------------------------------
# Impact gating helper
# ---------------------------------------------------------------------------


def _impact_at_least_medium(session: PlanningSession) -> bool:
    """Check if the session impact is at least MEDIUM."""
    if session.impact is None:
        return False
    return session.impact.impact in ("MEDIUM", "HIGH")


# ---------------------------------------------------------------------------
# Prompt builders and parsers
# ---------------------------------------------------------------------------


def _build_problem_frame_prompt(session: PlanningSession) -> str:
    gaps_text = "\n".join(
        f"  - {g.get('target', '?')}: {g.get('description', '')}"
        for g in session.gaps[:30]
    ) or "  (none)"

    constraint_text = ""
    if session.constraint_context and session.constraint_context.authoritative:
        constraint_text = "\n".join(
            f"  - [{c.constraint_id}] {c.question}"
            for c in session.constraint_context.authoritative[:20]
        )
    constraint_text = constraint_text or "  (none)"

    return f"""Frame the problem for the following planning context.

Slice: {session.ctx.get('slice_id', 'unknown')}
Layer: {session.ctx.get('layer', 'L1')}

Gaps:
{gaps_text}

Existing constraints:
{constraint_text}

Return a JSON object with keys:
- goal: what this spec section aims to achieve
- scope: boundary of the problem
- domain_markers: list of key domain terms
- decision_points: list of questions that require decisions
- tradeoff_axes: list of dimensions where tradeoffs exist
- unknowns: list of identified unknowns or ambiguities
"""


def _parse_problem_frame(raw: str) -> ProblemFrame:
    try:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return ProblemFrame()
        parsed = json.loads(text[start : end + 1])
        return ProblemFrame(
            goal=parsed.get("goal", ""),
            scope=parsed.get("scope", ""),
            domain_markers=list(parsed.get("domain_markers", [])),
            decision_points=list(parsed.get("decision_points", [])),
            tradeoff_axes=list(parsed.get("tradeoff_axes", [])),
            unknowns=list(parsed.get("unknowns", [])),
        )
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse problem frame output")
        return ProblemFrame()


def _build_enrichment_prompt(session: PlanningSession) -> str:
    gaps_text = "\n".join(
        f"  - {g.get('target', '?')}: {g.get('description', '')}"
        for g in session.gaps[:30]
    ) or "  (none)"

    frame_text = ""
    if session.problem_frame:
        frame_text = (
            f"Goal: {session.problem_frame.goal}\n"
            f"Scope: {session.problem_frame.scope}\n"
            f"Unknowns: {session.problem_frame.unknowns}"
        )
    frame_text = frame_text or "  (no problem frame)"

    return f"""Analyze the following for constraint hypotheses, decision requirements, and conflicts.

Slice: {session.ctx.get('slice_id', 'unknown')}

Problem frame:
{frame_text}

Gaps:
{gaps_text}

Return a JSON object with keys:
- hypotheses: list of objects with hypothesis_id, question, inferred_answer, source, confidence, dimension, reasoning
- decision_requirements: list of objects with decision_id, question, kind, dimension, scope, impact, options, needed_for
- conflicts: list of objects describing detected conflicts (arbitrary keys)
"""


def _parse_enrichment_output(
    raw: str,
) -> tuple[list[ConstraintHypothesis], list[DecisionRequirement], ConflictReport | None]:
    hypotheses: list[ConstraintHypothesis] = []
    requirements: list[DecisionRequirement] = []
    conflict_report: ConflictReport | None = None

    try:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return hypotheses, requirements, conflict_report
        parsed = json.loads(text[start : end + 1])

        for h in parsed.get("hypotheses", []):
            if isinstance(h, dict):
                hypotheses.append(ConstraintHypothesis.from_dict(h))

        for dr in parsed.get("decision_requirements", []):
            if isinstance(dr, dict):
                requirements.append(DecisionRequirement.from_dict(dr))

        conflicts = parsed.get("conflicts", [])
        if conflicts:
            conflict_report = ConflictReport(
                conflicts=[dict(c) for c in conflicts if isinstance(c, dict)]
            )

    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse enrichment output")

    return hypotheses, requirements, conflict_report


def _build_question_prompt(events: list[dict[str, Any]]) -> str:
    events_text = "\n".join(
        f"  - {e.get('type', '?')}: {e.get('detail', e.get('question', ''))}"
        for e in events[:20]
    ) or "  (none)"

    return f"""Refine the following under-spec events into clear, actionable questions for human review.

Events:
{events_text}

Return a JSON array of objects with keys:
- type: the event type
- question: a clear, actionable question
- context: relevant context for the reviewer
- original_detail: the original event detail
"""


def _parse_question_output(
    raw: str, original_events: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    try:
        text = raw.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            return list(original_events)
        parsed = json.loads(text[start : end + 1])
        if not parsed:
            return list(original_events)
        return [dict(item) for item in parsed if isinstance(item, dict)]
    except (json.JSONDecodeError, ValueError):
        logger.warning("Failed to parse question composer output")
        return list(original_events)
