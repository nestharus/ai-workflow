"""Constraint-related planning strategies.

Strategies in this module classify impact, bootstrap constraints, frame and
enrich the problem space, surface non-software dimensions, evaluate candidates,
map tradeoffs, and compose under-spec questions.
"""

from __future__ import annotations

import json
import logging
import re
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

        touched = session.ctx.get("touched_files_count", 0)
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
        parsed_frame, parse_failure_event = _parse_problem_frame(raw)
        session.problem_frame = parsed_frame or ProblemFrame()
        if parse_failure_event is not None:
            session.add_under_spec_event(parse_failure_event)
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
        hypotheses, requirements, conflict_report, parse_failure_event = _parse_enrichment_output(
            raw
        )

        session.hypotheses.extend(hypotheses)
        session.decision_requirements.extend(requirements)
        if conflict_report and conflict_report.conflicts:
            session.conflict_report = conflict_report
        if parse_failure_event is not None:
            session.add_under_spec_event(parse_failure_event)

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

        session.set_candidate_evaluations(evaluations)
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
    """Always runs. Loads the authoritative tradeoff priority ordering.

    Uses TRADEOFFS.md when available and parses the explicit priority model.
    If the file cannot be loaded or parsed reliably, this strategy emits an
    under-spec event and falls back to the canonical in-code ordering derived
    from design guidance.
    """

    _AUTHORITATIVE_AXES: ClassVar[tuple[str, ...]] = (
        "fidelity",
        "robustness",
        "diagnosability",
        "efficiency",
        "speed",
    )

    @property
    def name(self) -> str:
        return "tradeoff_mapper"

    def __init__(self, workspace_root: Path | None = None) -> None:
        self._workspace_root = workspace_root

    def run(self, session: PlanningSession) -> PlanningSession:
        axes, warning = self._load_axes()
        session.tradeoff_axes = axes
        if warning is not None:
            session.add_under_spec_event(warning)
        return session

    def _load_axes(self) -> tuple[list[str], dict[str, Any] | None]:
        """Load authoritative axes and surface source/load failures explicitly."""
        if self._workspace_root is None:
            return list(self._AUTHORITATIVE_AXES), _build_tradeoff_source_warning(
                reason="workspace root not available for TRADEOFFS lookup",
                source_path="",
            )

        candidates = [
            self._workspace_root / ".tasks" / "plans" / "spec manager" / "design" / "TRADEOFFS.md",
            self._workspace_root / "design" / "TRADEOFFS.md",
            self._workspace_root / "TRADEOFFS.md",
        ]
        for candidate in candidates:
            if not candidate.exists():
                continue
            try:
                axes = self._parse_axes(candidate.read_text(encoding="utf-8"))
            except OSError:
                logger.warning("Failed to read tradeoff source %s", candidate, exc_info=True)
                return list(self._AUTHORITATIVE_AXES), _build_tradeoff_source_warning(
                    reason="failed to read authoritative tradeoff source",
                    source_path=str(candidate),
                )
            if axes:
                return axes, None
            return list(self._AUTHORITATIVE_AXES), _build_tradeoff_source_warning(
                reason="failed to parse authoritative tradeoff priority ordering",
                source_path=str(candidate),
            )

        return list(self._AUTHORITATIVE_AXES), _build_tradeoff_source_warning(
            reason="authoritative TRADEOFFS.md not found",
            source_path="",
        )

    @staticmethod
    def _parse_axes(content: str) -> list[str]:
        """Extract the explicit priority ordering from TRADEOFFS.md."""
        section_match = re.search(
            r"(?is)^##\s+Priority ordering\s*(.+?)(?:^##\s+|\Z)",
            content,
            re.MULTILINE,
        )
        if section_match is None:
            return []

        priorities: dict[int, str] = {}
        for line in section_match.group(1).splitlines():
            token = line.strip()
            if not token:
                continue
            match = re.search(r"\*\*(\d+)\.\s*([^*]+?)\s*\*\*", token)
            if match is None:
                match = re.search(r"^(\d+)\.\s+\*\*([^*]+?)\*\*", token)
            if match is None:
                continue
            rank = int(match.group(1))
            canonical = _canonical_tradeoff_axis(match.group(2))
            if canonical is None:
                continue
            priorities[rank] = canonical

        if not priorities:
            return []

        ordered = [priorities[index] for index in sorted(priorities)]
        if ordered[: len(TradeoffMapperStrategy._AUTHORITATIVE_AXES)] != list(
            TradeoffMapperStrategy._AUTHORITATIVE_AXES
        ):
            return []
        return ordered


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

        source_events = session.under_spec_event_dicts()
        prompt = _build_question_prompt(source_events)
        raw = self._run_agent(prompt)
        refined, parse_failure_event = _parse_question_output(raw, source_events)
        session.set_under_spec_events(refined)
        if parse_failure_event is not None:
            session.add_under_spec_event(parse_failure_event)
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
    selected_gaps, omitted_gaps = _truncate_items(
        session.gaps,
        limit=30,
        identifier=_gap_identifier,
    )
    gaps_text = (
        "\n".join(
            f"  - {gap.get('target', '?')}: {gap.get('description', '')}" for gap in selected_gaps
        )
        or "  (none)"
    )
    gap_coverage = _build_coverage_summary(
        label="gaps",
        total=len(session.gaps),
        selected=len(selected_gaps),
        omitted_identifiers=omitted_gaps,
    )

    authoritative = (
        session.constraint_context.authoritative
        if session.constraint_context and session.constraint_context.authoritative
        else []
    )
    selected_constraints, omitted_constraints = _truncate_items(
        authoritative,
        limit=20,
        identifier=_constraint_identifier,
    )
    constraint_text = (
        "\n".join(
            f"  - [{constraint.constraint_id}] {constraint.question}"
            for constraint in selected_constraints
        )
        or "  (none)"
    )
    constraint_coverage = _build_coverage_summary(
        label="constraints",
        total=len(authoritative),
        selected=len(selected_constraints),
        omitted_identifiers=omitted_constraints,
    )

    return f"""Frame the problem for the following planning context.

Slice: {session.ctx.get("slice_id", "unknown")}
Layer: {session.ctx.get("layer", "L1")}

Gaps:
{gaps_text}

Gap coverage:
{gap_coverage}

Existing constraints:
{constraint_text}

Constraint coverage:
{constraint_coverage}

Return a JSON object with keys:
- goal: what this spec section aims to achieve
- scope: boundary of the problem
- domain_markers: list of key domain terms
- decision_points: list of questions that require decisions
- tradeoff_axes: list of dimensions where tradeoffs exist
- unknowns: list of identified unknowns or ambiguities
"""


def _parse_problem_frame(raw: str) -> tuple[ProblemFrame | None, dict[str, Any] | None]:
    try:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("problem frame output did not include a JSON object")
        parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            raise TypeError("problem frame output must be a JSON object")
        return ProblemFrame(
            goal=str(parsed.get("goal", "")).strip(),
            scope=str(parsed.get("scope", "")).strip(),
            domain_markers=_coerce_string_list(parsed.get("domain_markers", [])),
            decision_points=_coerce_string_list(parsed.get("decision_points", [])),
            tradeoff_axes=_coerce_string_list(parsed.get("tradeoff_axes", [])),
            unknowns=_coerce_string_list(parsed.get("unknowns", [])),
        ), None
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse problem frame output", exc_info=True)
        return None, _build_parse_failure_event(
            stage="problem_framer",
            raw=raw,
            error=str(exc),
        )


def _build_enrichment_prompt(session: PlanningSession) -> str:
    selected_gaps, omitted_gaps = _truncate_items(
        session.gaps,
        limit=30,
        identifier=_gap_identifier,
    )
    gaps_text = (
        "\n".join(
            f"  - {gap.get('target', '?')}: {gap.get('description', '')}" for gap in selected_gaps
        )
        or "  (none)"
    )
    gap_coverage = _build_coverage_summary(
        label="gaps",
        total=len(session.gaps),
        selected=len(selected_gaps),
        omitted_identifiers=omitted_gaps,
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
        f"\nGap coverage:\n{gap_coverage}\n"
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
) -> tuple[
    list[ConstraintHypothesis],
    list[DecisionRequirement],
    ConflictReport | None,
    dict[str, Any] | None,
]:
    hypotheses: list[ConstraintHypothesis] = []
    requirements: list[DecisionRequirement] = []
    conflict_report: ConflictReport | None = None

    try:
        text = raw.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("constraint enrichment output did not include a JSON object")
        parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            raise TypeError("constraint enrichment output must be a JSON object")

        hypotheses_payload = parsed.get("hypotheses", [])
        if not isinstance(hypotheses_payload, list):
            raise TypeError("hypotheses payload must be a list")
        requirements_payload = parsed.get("decision_requirements", [])
        if not isinstance(requirements_payload, list):
            raise TypeError("decision_requirements payload must be a list")
        conflicts_payload = parsed.get("conflicts", [])
        if conflicts_payload is not None and not isinstance(conflicts_payload, list):
            raise TypeError("conflicts payload must be a list")

        for hypothesis in hypotheses_payload:
            if isinstance(hypothesis, dict):
                hypotheses.append(ConstraintHypothesis.from_dict(hypothesis))

        for requirement in requirements_payload:
            if isinstance(requirement, dict):
                requirements.append(DecisionRequirement.from_dict(requirement))

        if conflicts_payload:
            conflict_report = ConflictReport(
                conflicts=[
                    dict(conflict) for conflict in conflicts_payload if isinstance(conflict, dict)
                ]
            )

    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse enrichment output", exc_info=True)
        return (
            hypotheses,
            requirements,
            conflict_report,
            _build_parse_failure_event(
                stage="constraint_enricher",
                raw=raw,
                error=str(exc),
            ),
        )

    return hypotheses, requirements, conflict_report, None


def _build_question_prompt(events: list[dict[str, Any]]) -> str:
    selected_events, omitted_events = _truncate_items(
        events,
        limit=20,
        identifier=_event_identifier,
    )
    events_text = (
        "\n".join(
            f"  - {event.get('type', '?')}: {event.get('detail', event.get('question', ''))}"
            for event in selected_events
        )
        or "  (none)"
    )
    event_coverage = _build_coverage_summary(
        label="under-spec events",
        total=len(events),
        selected=len(selected_events),
        omitted_identifiers=omitted_events,
    )

    return (
        "Refine the following under-spec events into clear,"
        " actionable questions for human review.\n"
        f"\nEvents:\n{events_text}\n"
        f"\nEvent coverage:\n{event_coverage}\n"
        "\nReturn a JSON array of objects with keys:\n"
        "- type: the event type\n"
        "- question: a clear, actionable question\n"
        "- context: relevant context for the reviewer\n"
        "- original_detail: the original event detail\n"
    )


def _parse_question_output(
    raw: str,
    original_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    try:
        text = raw.strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end == -1:
            raise ValueError("question composer output did not include a JSON array")
        parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, list):
            raise TypeError("question composer output must be a JSON array")
        refined = [dict(item) for item in parsed if isinstance(item, dict)]
        if not refined:
            raise ValueError("question composer output had no event objects")
        return refined, None
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Failed to parse question composer output", exc_info=True)
        return list(original_events), _build_parse_failure_event(
            stage="question_composer",
            raw=raw,
            error=str(exc),
        )


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _truncate_items(
    items: list[Any],
    *,
    limit: int,
    identifier: Callable[[Any, int], str],
) -> tuple[list[Any], list[str]]:
    selected = list(items[: max(limit, 0)])
    omitted_identifiers = [
        identifier(item, index)
        for index, item in enumerate(items[max(limit, 0) :], start=max(limit, 0))
    ]
    filtered_omitted = [value for value in omitted_identifiers if value]
    return selected, filtered_omitted


def _build_coverage_summary(
    *,
    label: str,
    total: int,
    selected: int,
    omitted_identifiers: list[str],
) -> str:
    omitted = max(total - selected, 0)
    omitted_text = ", ".join(omitted_identifiers[:20]) if omitted_identifiers else "(none)"
    label_key = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "items"
    return (
        f"- total_{label_key}: {total}\n"
        f"- included_{label_key}: {selected}\n"
        f"- omitted_{label_key}: {omitted}\n"
        f"- omitted_{label_key}_identifiers: {omitted_text}"
    )


def _gap_identifier(value: Any, index: int) -> str:
    if not isinstance(value, dict):
        return f"gap-{index + 1}"
    explicit_id = str(value.get("gap_id", "")).strip() or str(value.get("id", "")).strip()
    target = str(value.get("target", "")).strip()
    return explicit_id or target or f"gap-{index + 1}"


def _constraint_identifier(value: Any, index: int) -> str:
    constraint_id = str(getattr(value, "constraint_id", "")).strip()
    question = str(getattr(value, "question", "")).strip()
    return constraint_id or question or f"constraint-{index + 1}"


def _event_identifier(value: Any, index: int) -> str:
    if not isinstance(value, dict):
        return f"event-{index + 1}"
    event_type = str(value.get("type", "")).strip()
    question = str(value.get("question", value.get("detail", ""))).strip()
    candidate_id = str(value.get("candidate_id", "")).strip()
    decision_id = str(value.get("decision_id", "")).strip()
    constraint_id = str(value.get("constraint_id", "")).strip()
    reference = candidate_id or decision_id or constraint_id or question
    return ": ".join(part for part in (event_type, reference) if part) or f"event-{index + 1}"


def _build_parse_failure_event(*, stage: str, raw: str, error: str) -> dict[str, Any]:
    return {
        "type": "llm_parse_failure",
        "question": f"Resolve malformed planner output for stage '{stage}'.",
        "reason": error,
        "detail": f"Planner stage '{stage}' produced non-parseable output.",
        "stage": stage,
        "raw_output": raw,
        "raw_output_excerpt": raw[:1000],
        "raw_output_length": len(raw),
    }


def _canonical_tradeoff_axis(raw_axis: str) -> str | None:
    normalized = re.sub(r"[^a-z]+", " ", raw_axis.lower()).strip()
    if normalized.startswith("fidelity"):
        return "fidelity"
    if normalized.startswith("robustness"):
        return "robustness"
    if normalized.startswith("diagnosability"):
        return "diagnosability"
    if normalized.startswith("efficiency"):
        return "efficiency"
    if normalized.startswith("speed"):
        return "speed"
    return None


def _build_tradeoff_source_warning(*, reason: str, source_path: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "tradeoff_source_unavailable",
        "question": "Validate tradeoff priority ordering for this planning run.",
        "reason": reason,
        "detail": "Tradeoff axes defaulted to the canonical fidelity-first ordering.",
        "canonical_axes": list(TradeoffMapperStrategy._AUTHORITATIVE_AXES),
    }
    if source_path:
        payload["source_path"] = source_path
    return payload
