"""Pre-decomposition skeleton renderer — system/workflows/entities/interfaces.

Per response2.md Section 6: For intent-level intake, the Intent Agent must
NOT invent library boundaries. The skeleton represents a pre-decomposition
view of the system.

Skeleton structure:
    system/
      intent.md           — problem frame, scope, success metrics, open question IDs,
                            pointers to constraints by ID (no constraint objects)
      workflows/
        <workflow>.py     — domain workflows as function/class stubs
      entities/
        <entity>.py       — domain entities and value objects
      interfaces/
        <interface>.py    — external boundaries (providers, counterparties, etc.)
    analysis/intent/
      intent_snapshot.json — metadata snapshot (no constraint objects)
      question_queue.json  — queue snapshot

Depth rule (Section 6.2): "One level deeper than names"
    - Include workflows + key interfaces + entity shapes
    - Include TODOs tied to question IDs
    - Do NOT implement business logic

Section 5.7: Produce skeleton when:
    - Stable restatement of problem frame exists
    - Core workflows are identifiable
    - Major constraint dimensions have initial coverage or explicit open questions
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _normalize_question_refs(
    raw_questions: Any,
    *,
    fallback: list[dict[str, str]] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    """Normalize question references into parallel ID/key/scenario lists."""
    normalized: list[tuple[str, str, str]] = []

    if isinstance(raw_questions, list):
        for raw in raw_questions:
            if isinstance(raw, str):
                qid = raw.strip()
                if qid:
                    normalized.append((qid, "", ""))
                continue

            if isinstance(raw, dict):
                qid = str(raw.get("question_id", raw.get("id", ""))).strip()
                if not qid:
                    continue
                canonical_key = str(raw.get("canonical_key", "")).strip()
                scenario = str(raw.get("scenario", "")).strip()
                normalized.append((qid, canonical_key, scenario))

    if not normalized and fallback:
        for raw in fallback:
            qid = str(raw.get("question_id", raw.get("id", ""))).strip()
            if not qid:
                continue
            canonical_key = str(raw.get("canonical_key", "")).strip()
            scenario = str(raw.get("scenario", "")).strip()
            normalized.append((qid, canonical_key, scenario))

    deduped: list[tuple[str, str, str]] = []
    seen_ids: set[str] = set()
    for qid, canonical_key, scenario in normalized:
        if qid in seen_ids:
            continue
        seen_ids.add(qid)
        deduped.append((qid, canonical_key, scenario))

    question_ids, canonical_keys, scenarios = zip(*deduped) if deduped else ((), (), ())
    return list(question_ids), list(canonical_keys), list(scenarios)


def _question_todo_lines(
    subject: str,
    question_ids: list[str],
    canonical_keys: list[str],
    scenarios: list[str],
) -> list[str]:
    """Build canonical_key/scenario tied TODO comments for one stub."""
    lines: list[str] = []
    for idx, qid in enumerate(question_ids):
        if not qid:
            continue
        canonical_key = canonical_keys[idx] if idx < len(canonical_keys) else ""
        scenario = scenarios[idx] if idx < len(scenarios) else ""
        key_suffix = f" (canonical_key: {canonical_key})" if canonical_key else ""
        lines.append(f"# Q:{qid}{key_suffix}")
        if scenario:
            lines.append(f"# Scenario: {scenario}")
        lines.append(f"# TODO: finalize {subject} based on user answer to Q:{qid}.")
    return lines


@dataclass
class WorkflowStub:
    """A domain workflow stub for the skeleton."""

    name: str = ""
    description: str = ""
    open_question_ids: list[str] = field(default_factory=list)
    canonical_keys: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)


@dataclass
class EntityStub:
    """A domain entity stub for the skeleton."""

    name: str = ""
    description: str = ""
    fields: list[str] = field(default_factory=list)
    open_question_ids: list[str] = field(default_factory=list)
    canonical_keys: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)


@dataclass
class InterfaceStub:
    """An external boundary stub for the skeleton."""

    name: str = ""
    description: str = ""
    direction: str = "inbound"  # inbound | outbound | bidirectional
    open_question_ids: list[str] = field(default_factory=list)
    canonical_keys: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)


@dataclass
class SkeletonSpec:
    """Full specification for generating a pre-decomposition skeleton."""

    problem_frame: dict[str, Any] = field(default_factory=dict)
    concept_map: dict[str, Any] = field(default_factory=dict)
    workflows: list[WorkflowStub] = field(default_factory=list)
    entities: list[EntityStub] = field(default_factory=list)
    interfaces: list[InterfaceStub] = field(default_factory=list)
    open_question_ids: list[str] = field(default_factory=list)
    constraint_refs: list[str] = field(default_factory=list)  # planner constraint IDs


# ---------------------------------------------------------------------------
# SkeletonSynthesisStrategy
# ---------------------------------------------------------------------------


# TODO [R2-6.1/6.2]: Implement SkeletonSynthesisStrategy
#   - LLM strategy that produces pre-decomposition skeleton artifacts
#   - Input: problem_frame, concept_map, answered/open questions,
#     constraint references (IDs only, not objects)
#   - Output: SkeletonSpec with workflows, entities, interfaces
#   - Depth: "one level deeper than names" — stubs with TODOs tied
#     to question IDs, no business logic
#   - Must NOT invent library boundaries (that's Phase 0's job)
#   - Skeleton creation is incremental: revised as constraints arrive
class SkeletonSynthesisStrategy:
    """LLM strategy to produce pre-decomposition skeleton spec.

    Per response2.md Section 6: Produces system/workflows/entities/interfaces
    structure. Does NOT decompose into libraries.
    """

    def synthesize(
        self,
        problem_frame: dict[str, Any],
        concept_map: dict[str, Any],
        open_question_ids: list[str],
        open_questions: list[dict[str, str]] | None = None,
        constraint_refs: list[str] | None = None,
        *,
        run_agent: Any = None,
    ) -> SkeletonSpec:
        """Produce a pre-decomposition skeleton specification."""
        constraint_refs = list(constraint_refs or [])
        open_question_records = list(open_questions or [{"question_id": qid} for qid in open_question_ids])

        if run_agent is None:
            return SkeletonSpec(
                problem_frame=problem_frame,
                concept_map=concept_map,
                open_question_ids=open_question_ids,
                constraint_refs=constraint_refs,
            )

        from spec_manager.core.json_extraction import _extract_json_payload

        scope_raw = problem_frame.get("scope", {})
        if isinstance(scope_raw, dict):
            scope_text = json.dumps(scope_raw, indent=2)
        else:
            scope_text = json.dumps(str(scope_raw))

        def _extract_question_metadata(
            item: dict[str, Any],
            fallback: list[dict[str, str]],
        ) -> tuple[list[str], list[str], list[str]]:
            if not isinstance(item, dict):
                return _normalize_question_refs([], fallback=fallback)
            if "open_questions" in item:
                return _normalize_question_refs(item.get("open_questions", []), fallback=fallback)
            if "open_question_ids" in item:
                return _normalize_question_refs(item.get("open_question_ids", []), fallback=fallback)
            return _normalize_question_refs([], fallback=fallback)

        prompt = (
            "You are a systems analyst. Given the following problem frame, "
            "produce a pre-decomposition skeleton specification.\n\n"
            "## Problem Frame\n"
            f"Restatement: {problem_frame.get('current_restatement', '')}\n"
            f"Goals: {json.dumps(problem_frame.get('goals', []))}\n"
            f"Non-goals: {json.dumps(problem_frame.get('non_goals', []))}\n"
            f"Scope: {scope_text}\n\n"
            "## Open Question Metadata\n"
            f"{json.dumps(open_question_records, indent=2)}\n\n"
            f"## Constraint refs (IDs only)\n"
            f"{json.dumps(constraint_refs)}\n\n"
            "Produce a JSON object with exactly three keys:\n"
            '- "workflows": list of {{"name": str, "description": str, '
            '"open_questions": [{"question_id": str, "canonical_key": str, "scenario": str}]} \n'
            '- "entities": list of {{"name": str, "description": str, '
            '"fields": list of str, "open_questions": [{"question_id": str, "canonical_key": str, "scenario": str}]}}\n'
            '- "interfaces": list of {{"name": str, "description": str, '
            '"direction": "inbound"|"outbound"|"bidirectional", '
            '"open_questions": [{"question_id": str, "canonical_key": str, "scenario": str}]}}\n'
            "Do NOT invent library boundaries. Keep stubs shallow — "
            "one level deeper than names. Output ONLY the JSON object."
        )

        raw = run_agent(prompt)
        try:
            extracted = _extract_json_payload(raw)
            data = json.loads(extracted)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse skeleton LLM response, returning empty spec")
            return SkeletonSpec(
                problem_frame=problem_frame,
                concept_map=concept_map,
                open_question_ids=open_question_ids,
                constraint_refs=constraint_refs,
            )

        fallback_records = (
            open_question_records
            if open_question_records
            else [{"question_id": qid} for qid in open_question_ids]
        )

        workflows = []
        for w in data.get("workflows", []):
            q_ids, canonical_keys, scenarios = _extract_question_metadata(w, fallback_records)
            workflows.append(
                WorkflowStub(
                    name=w.get("name", ""),
                    description=w.get("description", ""),
                    open_question_ids=q_ids,
                    canonical_keys=canonical_keys,
                    scenarios=scenarios,
                )
            )

        entities = []
        for e in data.get("entities", []):
            q_ids, canonical_keys, scenarios = _extract_question_metadata(e, fallback_records)
            entities.append(
                EntityStub(
                    name=e.get("name", ""),
                    description=e.get("description", ""),
                    fields=e.get("fields", []),
                    open_question_ids=q_ids,
                    canonical_keys=canonical_keys,
                    scenarios=scenarios,
                )
            )

        interfaces = []
        for i in data.get("interfaces", []):
            q_ids, canonical_keys, scenarios = _extract_question_metadata(i, fallback_records)
            interfaces.append(
                InterfaceStub(
                    name=i.get("name", ""),
                    description=i.get("description", ""),
                    direction=i.get("direction", "inbound"),
                    open_question_ids=q_ids,
                    canonical_keys=canonical_keys,
                    scenarios=scenarios,
                )
            )

        return SkeletonSpec(
            problem_frame=problem_frame,
            concept_map=concept_map,
            workflows=workflows,
            entities=entities,
            interfaces=interfaces,
            open_question_ids=open_question_ids,
            constraint_refs=constraint_refs,
        )


# ---------------------------------------------------------------------------
# Skeleton renderer
# ---------------------------------------------------------------------------


# TODO [R2-6.1]: Implement render_skeleton(spec, output_dir)
#   - Takes a SkeletonSpec and renders the directory structure:
#     system/intent.md — problem frame, scope, metrics, open Qs, constraint refs
#     system/workflows/<name>.py — function/class stubs with TODO comments
#     system/entities/<name>.py — entity stubs with field shapes
#     system/interfaces/<name>.py — external boundary stubs
#   - Workflow stubs must include TODO comments referencing question IDs:
#     # Q:<question_id> (canonical_key: <key>)
#     # Scenario: <scenario text>
#     # TODO: finalize <aspect> based on user answer.
#   - Must NOT embed constraint objects — only reference by ID
def render_skeleton(spec: SkeletonSpec, output_dir: Path) -> list[Path]:
    """Render skeleton artifacts to the output directory.

    Returns list of created file paths.
    """
    created: list[Path] = []

    # --- system/intent.md ---
    system_dir = output_dir / "system"
    system_dir.mkdir(parents=True, exist_ok=True)

    pf = spec.problem_frame
    scope_raw = pf.get("scope", {})
    if isinstance(scope_raw, dict):
        scope_in = scope_raw.get("in", [])
        scope_out = scope_raw.get("out", [])
    else:
        scope_in = pf.get("scope_in", [])
        scope_out = pf.get("scope_out", [])

    intent_lines = [
        "# Intent",
        "",
        "## Problem Frame",
        f"Restatement: {pf.get('current_restatement', '')}",
        f"Goals: {json.dumps(pf.get('goals', []))}",
        f"Non-goals: {json.dumps(pf.get('non_goals', []))}",
        f"Scope In: {json.dumps(scope_in)}",
        f"Scope Out: {json.dumps(scope_out)}",
        "",
        "## Success Metrics",
        json.dumps(pf.get("success_metrics", []), indent=2),
        "",
        "## Open Question IDs",
    ]
    for qid in spec.open_question_ids:
        intent_lines.append(f"- {qid}")
    intent_lines.append("")
    intent_lines.append("## Constraint Refs (by ID)")
    for cid in spec.constraint_refs:
        intent_lines.append(f"- {cid}")
    intent_lines.append("")

    intent_path = system_dir / "intent.md"
    intent_path.write_text("\n".join(intent_lines), encoding="utf-8")
    created.append(intent_path)

    # --- system/workflows/<name>.py ---
    wf_dir = system_dir / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    for w in spec.workflows:
        lines = [f'"""{w.description}"""', ""]
        lines.extend(_question_todo_lines(w.name, list(w.open_question_ids), list(w.canonical_keys), list(w.scenarios)))
        lines.append("")
        lines.append(f"def {w.name}():")
        lines.append("    raise NotImplementedError")
        lines.append("")
        wf_path = wf_dir / f"{w.name}.py"
        wf_path.write_text("\n".join(lines), encoding="utf-8")
        created.append(wf_path)

    # --- system/entities/<name>.py ---
    ent_dir = system_dir / "entities"
    ent_dir.mkdir(parents=True, exist_ok=True)
    for e in spec.entities:
        lines = [f'"""{e.description}"""', ""]
        lines.extend(_question_todo_lines(f"entity {e.name}", list(e.open_question_ids), list(e.canonical_keys), list(e.scenarios)))
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"class {e.name}:")
        if e.fields:
            for field_name in e.fields:
                lines.append(f"    {field_name} = None")
        else:
            lines.append("    pass")
        lines.append("")
        ent_path = ent_dir / f"{e.name}.py"
        ent_path.write_text("\n".join(lines), encoding="utf-8")
        created.append(ent_path)

    # --- system/interfaces/<name>.py ---
    iface_dir = system_dir / "interfaces"
    iface_dir.mkdir(parents=True, exist_ok=True)
    for i in spec.interfaces:
        lines = [f'"""{i.description}"""', ""]
        lines.extend(
            _question_todo_lines(
                f"interface {i.name}",
                list(i.open_question_ids),
                list(i.canonical_keys),
                list(i.scenarios),
            )
        )
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"# direction: {i.direction}")
        lines.append("")
        lines.append(f"class {i.name}:")
        lines.append("    pass")
        lines.append("")
        iface_path = iface_dir / f"{i.name}.py"
        iface_path.write_text("\n".join(lines), encoding="utf-8")
        created.append(iface_path)

    return created


# TODO [R2-6.3]: Implement render_intent_snapshot(state, queue, output_dir)
#   - Renders analysis/intent/intent_snapshot.json containing:
#     problem_frame, concept_map, queue open question IDs + canonical keys,
#     references to planner-authored constraints/decisions by ID
#   - Must NOT embed constraint objects
def render_intent_snapshot(
    problem_frame: dict[str, Any],
    concept_map: dict[str, Any],
    open_questions: list[dict[str, str]],
    constraint_refs: list[str],
    output_dir: Path,
) -> Path:
    """Render the intent metadata snapshot."""
    snapshot_dir = output_dir / "analysis" / "intent"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    question_ids, canonical_keys, scenarios = _normalize_question_refs(open_questions)
    snapshot = {
        "problem_frame": problem_frame,
        "concept_map": concept_map,
        "open_questions": [
            {
                "question_id": qid,
                "canonical_key": canonical_key,
                "scenario": scenario,
            }
            for qid, canonical_key, scenario in zip(question_ids, canonical_keys, scenarios)
        ],
        "constraint_refs": list(constraint_refs),
    }

    path = snapshot_dir / "intent_snapshot.json"
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return path


def should_produce_skeleton(
    problem_frame: dict[str, Any],
    queue_state: dict[str, Any],
) -> bool:
    """Check if there is enough information to produce a skeleton.

    Returns True when all of these hold:
      1. Stable restatement of problem frame exists (even if tentative).
      2. Core workflows are identifiable (at least one goal defined).
      3. Major constraint dimensions have either at least one answered
         constraint (closed question) OR an explicit queued question
         (not silent assumptions).
    """
    # 1. Stable restatement exists
    has_restatement = bool(problem_frame.get("current_restatement", ""))

    # 2. Core workflows identifiable — goals serve as proxy
    goals = problem_frame.get("goals", [])
    has_goals = len(goals) >= 1

    # 3. Constraint dimension coverage (or explicit open constraint questions).
    open_constraint_ids = set(queue_state.get("open_constraint_question_ids", []) or [])
    closed_constraint_ids = set(queue_state.get("closed_constraint_question_ids", []) or [])
    open_constraint_dimensions = set(
        queue_state.get("open_constraint_dimensions", []) or []
    )
    closed_constraint_dimensions = set(
        queue_state.get("closed_constraint_dimensions", []) or []
    )
    has_constraint_coverage_keys = (
        "open_constraint_question_ids" in queue_state
        or "closed_constraint_question_ids" in queue_state
        or "open_constraint_dimensions" in queue_state
        or "closed_constraint_dimensions" in queue_state
    )

    has_constraint_coverage = False
    if has_constraint_coverage_keys:
        has_constraint_coverage = (
            bool(open_constraint_ids)
            or bool(closed_constraint_ids)
            or bool(open_constraint_dimensions)
            or bool(closed_constraint_dimensions)
        )

    return has_restatement and has_goals and has_constraint_coverage
