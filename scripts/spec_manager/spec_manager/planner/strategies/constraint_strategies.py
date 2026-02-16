"""Constraint-related planning strategies.

Strategies in this module classify impact, bootstrap constraints, frame and
enrich the problem space, surface non-software dimensions, evaluate candidates,
map tradeoffs, and compose under-spec questions.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from spec_manager.planner.constraints.impact import classify_impact
from spec_manager.planner.constraints.non_software import (
    build_non_software_checklist_requirements,
)
from spec_manager.planner.constraints.types import (
    ConflictReport,
    ConstraintContext,
    ConstraintHypothesis,
    DecisionRequirement,
    ProblemFrame,
)
from spec_manager.planner.tools.constraints_tool import ConstraintsTool

from .protocol import PlanningSession

logger = logging.getLogger(__name__)

_SECURITY_PRIVACY_COMPLIANCE_KEYWORDS = (
    "security",
    "privacy",
    "compliance",
    "regulatory",
    "regulation",
    "gdpr",
    "hipaa",
    "pci",
    "soc2",
    "audit",
)


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
        gap_severities = _collect_gap_severities(session.gaps)

        try:
            touched = max(int(session.ctx.get("touched_files_count", 0) or 0), 0)
        except (TypeError, ValueError):
            touched = 0
        ext_dep = _coerce_bool(session.ctx.get("introduces_external_dep", False))
        infra = _coerce_bool(session.ctx.get("introduces_infra", False))
        cross_lib = _coerce_bool(session.ctx.get("cross_library_contract", False))
        security_privacy_compliance = _has_security_privacy_compliance_signal(
            ctx=session.ctx,
            gaps=session.gaps,
        )

        session.impact = classify_impact(
            layer=layer,
            gap_kinds=gap_kinds,
            gap_severities=gap_severities,
            touched_files_count=touched,
            introduces_external_dep=ext_dep,
            introduces_infra=infra,
            cross_library_contract=cross_lib,
            security_privacy_compliance=security_privacy_compliance,
        )
        return session


class ConstraintBootstrapStrategy:
    """Always runs. Bootstraps constraints from the store into the session."""

    @property
    def name(self) -> str:
        return "constraint_bootstrap"

    def __init__(self, workspace_root: Path) -> None:
        self._adapter = ConstraintsTool(workspace_root=workspace_root)

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

        session.decision_requirements.extend(
            build_non_software_checklist_requirements(
                gaps=session.gaps,
                context=session.ctx,
                existing_requirements=session.decision_requirements,
                impact=session.impact.impact if session.impact else "MEDIUM",
            )
        )

        return session


class CandidateEvaluatorStrategy:
    """Evaluates candidates against constraints, coupling, and blast radius."""

    @property
    def name(self) -> str:
        return "candidate_evaluator"

    def run(self, session: PlanningSession) -> PlanningSession:
        evaluations: list[dict[str, Any]] = []
        try:
            touched_files = max(int(session.ctx.get("touched_files_count", 0) or 0), 0)
        except (TypeError, ValueError):
            touched_files = 0

        for index, intention in enumerate(session.intentions):
            if not isinstance(intention, dict):
                continue
            evaluations.append(
                self._evaluate_intention_candidate(
                    index=index,
                    candidate=intention,
                    touched_files=touched_files,
                    session=session,
                )
            )

        for outcome in session.decision_outcomes:
            evaluations.append(self._evaluate_decision_outcome(outcome.to_dict(), session))

        session.candidate_evaluations = evaluations
        return session

    @staticmethod
    def _evaluate_intention_candidate(
        *,
        index: int,
        candidate: dict[str, Any],
        touched_files: int,
        session: PlanningSession,
    ) -> dict[str, Any]:
        candidate_id = (
            str(candidate.get("id", "")).strip()
            or str(candidate.get("function_name", "")).strip()
            or str(candidate.get("component_id", "")).strip()
            or str(candidate.get("file", "")).strip()
            or f"candidate-{index + 1}"
        )

        dependencies = candidate.get("dependencies", [])
        if not isinstance(dependencies, list):
            dependencies = []

        target_files = candidate.get("target_files", [])
        if not isinstance(target_files, list):
            target_files = []
        if candidate.get("file"):
            target_files = [candidate.get("file")]

        graph_targets = candidate.get("graph_targets", {})
        if not isinstance(graph_targets, dict):
            graph_targets = {}
        graph_edges = graph_targets.get("edges", [])
        if not isinstance(graph_edges, list):
            graph_edges = []

        coupling_score = len(dependencies) + len(graph_edges)
        blast_radius = max(len(target_files), touched_files)
        recommendation = "accept"
        reasons: list[str] = []

        approach_text = str(
            candidate.get("approach", candidate.get("refactor_approach", ""))
        ).strip()
        if not approach_text and session.gaps:
            recommendation = "needs_human"
            reasons.append("candidate lacks implementation approach detail")

        if session.conflict_report and session.conflict_report.conflicts:
            recommendation = "needs_human"
            reasons.append("constraint conflicts are unresolved")

        if blast_radius > 30 or coupling_score > 8:
            recommendation = "needs_human"
            reasons.append("candidate exceeds safe blast-radius/coupling threshold")

        return {
            "candidate_id": candidate_id,
            "source": "intention",
            "coupling_score": coupling_score,
            "blast_radius": blast_radius,
            "constraints_checked": CandidateEvaluatorStrategy._constraint_count(session),
            "recommendation": recommendation,
            "reasons": reasons,
        }

    @staticmethod
    def _evaluate_decision_outcome(
        outcome: dict[str, Any],
        session: PlanningSession,
    ) -> dict[str, Any]:
        decision_id = str(outcome.get("decision_id", "")).strip() or "architecture-decision"
        under_spec_events = outcome.get("under_spec_events", [])
        if not isinstance(under_spec_events, list):
            under_spec_events = []
        requirements = outcome.get("decision_requirements", [])
        if not isinstance(requirements, list):
            requirements = []
        wiring_intentions = outcome.get("wiring_intentions", [])
        if not isinstance(wiring_intentions, list):
            wiring_intentions = []

        recommendation = "accept"
        reasons: list[str] = []
        if under_spec_events or requirements or not bool(outcome.get("committed", False)):
            recommendation = "needs_human"
            reasons.append("architecture decision outcome remains unresolved")

        return {
            "candidate_id": decision_id,
            "source": "decision_outcome",
            "coupling_score": len(wiring_intentions),
            "blast_radius": len(wiring_intentions),
            "constraints_checked": CandidateEvaluatorStrategy._constraint_count(session),
            "recommendation": recommendation,
            "reasons": reasons,
        }

    @staticmethod
    def _constraint_count(session: PlanningSession) -> int:
        if session.constraint_context is None:
            return 0
        return len(session.constraint_context.authoritative) + len(
            session.constraint_context.decisions
        )


class TradeoffMapperStrategy:
    """Always runs. Loads tradeoff axes from TRADEOFFS.md or uses defaults.

    Looks for ``design/TRADEOFFS.md`` in the workspace root. If found,
    extracts axis names from markdown headings (``## <axis>`` or
    ``- <axis>``).  Falls back to a standard set of architectural
    tradeoff dimensions.
    """

    _DEFAULT_AXES: ClassVar[tuple[str, ...]] = (
        "performance",
        "maintainability",
        "simplicity",
        "extensibility",
        "reliability",
        "scalability",
        "security",
    )

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
            m = re.match(r"^#{1,3}\s+(.+)", line) or re.match(
                r"^[-*]\s+\*?\*?(.+?)\*?\*?\s*$", line
            )
            if m:
                axis = m.group(1).strip().lower()
                # Skip generic headings
                if (
                    axis
                    and axis not in seen
                    and len(axis) < 40
                    and axis
                    not in ("overview", "introduction", "summary", "tradeoffs", "tradeoff axes")
                ):
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
        mode = str(session.ctx.get("mode", "auto")).strip().lower()
        interactive = bool(session.ctx.get("interactive", False) or mode == "interactive")
        if not interactive:
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


def _collect_gap_severities(gaps: list[dict[str, Any]]) -> list[str]:
    severities: list[str] = []
    for gap in gaps:
        for key in ("severity", "severity_level", "priority", "risk_level"):
            value = gap.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                severities.append(text)
                break
    return severities


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _has_security_privacy_compliance_signal(
    *,
    ctx: dict[str, Any],
    gaps: list[dict[str, Any]],
) -> bool:
    for key in (
        "security_privacy_compliance",
        "introduces_security_privacy_compliance",
        "has_security_privacy_compliance_implication",
        "security_implication",
        "privacy_implication",
        "compliance_implication",
    ):
        if _coerce_bool(ctx.get(key, False)):
            return True

    text_chunks: list[str] = []
    for gap in gaps:
        for key in (
            "kind",
            "target",
            "description",
            "summary",
            "question",
            "dimension",
            "severity",
        ):
            value = gap.get(key)
            if value is None:
                continue
            text = str(value).strip().lower()
            if text:
                text_chunks.append(text)

    try:
        text_chunks.append(json.dumps(ctx, default=str).lower())
    except (TypeError, ValueError):
        text_chunks.append(str(ctx).lower())

    full_text = " ".join(text_chunks)
    return any(keyword in full_text for keyword in _SECURITY_PRIVACY_COMPLIANCE_KEYWORDS)


# ---------------------------------------------------------------------------
# Prompt builders and parsers
# ---------------------------------------------------------------------------


def _build_problem_frame_prompt(session: PlanningSession) -> str:
    gaps_text = (
        "\n".join(
            f"  - {g.get('target', '?')}: {g.get('description', '')}" for g in session.gaps[:30]
        )
        or "  (none)"
    )

    constraint_text = ""
    if session.constraint_context and session.constraint_context.authoritative:
        constraint_text = "\n".join(
            f"  - [{c.constraint_id}] {c.question}"
            for c in session.constraint_context.authoritative[:20]
        )
    constraint_text = constraint_text or "  (none)"

    return f"""Frame the problem for the following planning context.

Slice: {session.ctx.get("slice_id", "unknown")}
Layer: {session.ctx.get("layer", "L1")}

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
    gaps_text = (
        "\n".join(
            f"  - {g.get('target', '?')}: {g.get('description', '')}" for g in session.gaps[:30]
        )
        or "  (none)"
    )

    frame_text = ""
    if session.problem_frame:
        frame_text = (
            f"Goal: {session.problem_frame.goal}\n"
            f"Scope: {session.problem_frame.scope}\n"
            f"Unknowns: {session.problem_frame.unknowns}"
        )
    frame_text = frame_text or "  (no problem frame)"

    return (
        "Analyze the following for constraint hypotheses,"
        " decision requirements, and conflicts.\n"
        f"\nSlice: {session.ctx.get('slice_id', 'unknown')}\n"
        f"\nProblem frame:\n{frame_text}\n"
        f"\nGaps:\n{gaps_text}\n"
        "\nReturn a JSON object with keys:\n"
        "- hypotheses: list of objects with hypothesis_id, question,"
        " inferred_answer, source, confidence, dimension, reasoning\n"
        "- decision_requirements: list of objects with decision_id,"
        " question, kind, dimension, scope, impact, options, needed_for\n"
        "- conflicts: list of objects describing detected conflicts"
        " (arbitrary keys)\n"
    )


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
    events_text = (
        "\n".join(
            f"  - {e.get('type', '?')}: {e.get('detail', e.get('question', ''))}"
            for e in events[:20]
        )
        or "  (none)"
    )

    return (
        "Refine the following under-spec events into clear,"
        " actionable questions for human review.\n"
        f"\nEvents:\n{events_text}\n"
        "\nReturn a JSON array of objects with keys:\n"
        "- type: the event type\n"
        "- question: a clear, actionable question\n"
        "- context: relevant context for the reviewer\n"
        "- original_detail: the original event detail\n"
    )


def _parse_question_output(raw: str, original_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
