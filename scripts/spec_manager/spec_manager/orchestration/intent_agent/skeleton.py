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


def _extract_json_payload_from_llm_output(output: str) -> str:
    """Extract first decodable JSON object/array from an LLM output string."""
    cleaned = output.strip()
    if not cleaned:
        return cleaned

    lines = [line for line in cleaned.splitlines() if not line.startswith("[agent-exec]")]
    cleaned = "\n".join(lines).strip()

    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            fence_end = cleaned.find("```", first_newline + 1)
            if fence_end != -1:
                cleaned = cleaned[first_newline + 1 : fence_end].strip()

    decoder = json.JSONDecoder()
    first_obj = cleaned.find("{")
    first_list = cleaned.find("[")
    starts = [idx for idx in (first_obj, first_list) if idx != -1]
    if not starts:
        return cleaned

    for start in sorted(starts):
        idx = start
        while idx < len(cleaned):
            ch = cleaned[idx]
            if ch not in "{[":
                idx += 1
                continue
            try:
                _, end = decoder.raw_decode(cleaned[idx:])
            except json.JSONDecodeError:
                idx += 1
                continue
            return cleaned[idx : idx + end]

    return cleaned[min(starts) :]


def _normalize_question_refs(
    raw_questions: Any,
    *,
    fallback: list[dict[str, str]] | None = None,
) -> tuple[list[str], list[str], list[str], list[dict[str, Any]]]:
    """Normalize question refs and record every omission or deduplication."""
    normalized: list[tuple[str, str, str]] = []
    omissions: list[dict[str, Any]] = []

    def _coerce_original_value(value: Any) -> Any:
        try:
            json.dumps(value)
        except TypeError:
            return repr(value)
        return value

    if isinstance(raw_questions, list):
        for idx, raw in enumerate(raw_questions):
            if isinstance(raw, str):
                qid = raw.strip()
                if qid:
                    normalized.append((qid, "", ""))
                else:
                    omissions.append(
                        {
                            "reason": "empty_after_strip",
                            "source": "raw_questions",
                            "index": idx,
                            "original_value": raw,
                        }
                    )
                continue

            if isinstance(raw, dict):
                qid = str(raw.get("question_id", raw.get("id", ""))).strip()
                if not qid:
                    omissions.append(
                        {
                            "reason": "missing_question_id",
                            "source": "raw_questions",
                            "index": idx,
                            "original_value": _coerce_original_value(raw),
                        }
                    )
                    continue
                canonical_key = str(raw.get("canonical_key", "")).strip()
                scenario = str(raw.get("scenario", "")).strip()
                normalized.append((qid, canonical_key, scenario))
                continue

            omissions.append(
                {
                    "reason": "unrecognized_type",
                    "source": "raw_questions",
                    "index": idx,
                    "original_value": _coerce_original_value(raw),
                }
            )
    elif raw_questions is not None:
        omissions.append(
            {
                "reason": "raw_questions_not_list",
                "source": "raw_questions",
                "index": None,
                "original_value": _coerce_original_value(raw_questions),
            }
        )

    if not normalized and fallback:
        for idx, raw in enumerate(fallback):
            qid = str(raw.get("question_id", raw.get("id", ""))).strip()
            if not qid:
                omissions.append(
                    {
                        "reason": "missing_question_id",
                        "source": "fallback",
                        "index": idx,
                        "original_value": _coerce_original_value(raw),
                    }
                )
                continue
            canonical_key = str(raw.get("canonical_key", "")).strip()
            scenario = str(raw.get("scenario", "")).strip()
            normalized.append((qid, canonical_key, scenario))

    deduped: list[tuple[str, str, str]] = []
    seen_ids: set[str] = set()
    for idx, (qid, canonical_key, scenario) in enumerate(normalized):
        if qid in seen_ids:
            omissions.append(
                {
                    "reason": "duplicate_question_id",
                    "source": "normalized",
                    "index": idx,
                    "question_id": qid,
                    "original_value": {
                        "question_id": qid,
                        "canonical_key": canonical_key,
                        "scenario": scenario,
                    },
                }
            )
            continue
        seen_ids.add(qid)
        deduped.append((qid, canonical_key, scenario))

    question_ids, canonical_keys, scenarios = (
        zip(*deduped, strict=True) if deduped else ((), (), ())
    )
    return list(question_ids), list(canonical_keys), list(scenarios), omissions


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
    question_ref_omissions: list[dict[str, Any]] = field(default_factory=list)


class SkeletonSynthesisTransientParseError(RuntimeError):
    """Retryable LLM parse failure after bounded attempts."""

    def __init__(self, attempts: int, max_attempts: int) -> None:
        self.attempts = attempts
        self.max_attempts = max_attempts
        super().__init__(
            f"Failed to parse skeleton LLM response after {attempts}/{max_attempts} attempts"
        )


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

    MAX_PARSE_ATTEMPTS: int = 3

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
        open_question_records = list(
            open_questions or [{"question_id": qid} for qid in open_question_ids]
        )

        if run_agent is None:
            return SkeletonSpec(
                problem_frame=problem_frame,
                concept_map=concept_map,
                open_question_ids=open_question_ids,
                constraint_refs=constraint_refs,
            )

        scope_raw = problem_frame.get("scope", {})
        if isinstance(scope_raw, dict):
            scope_text = json.dumps(scope_raw, indent=2)
        else:
            scope_text = json.dumps(str(scope_raw))

        def _extract_question_metadata(
            item: dict[str, Any],
            fallback: list[dict[str, str]],
        ) -> tuple[list[str], list[str], list[str], list[dict[str, Any]]]:
            if not isinstance(item, dict):
                return _normalize_question_refs([], fallback=fallback)
            if "open_questions" in item:
                return _normalize_question_refs(item.get("open_questions", []), fallback=fallback)
            if "open_question_ids" in item:
                return _normalize_question_refs(
                    item.get("open_question_ids", []), fallback=fallback
                )
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
            '"open_questions": [{"question_id": str, "canonical_key": str, '
            '"scenario": str}]}\n'
            '- "entities": list of {{"name": str, "description": str, '
            '"fields": list of str, "open_questions": [{"question_id": str, '
            '"canonical_key": str, "scenario": str}]}}\n'
            '- "interfaces": list of {{"name": str, "description": str, '
            '"direction": "inbound"|"outbound"|"bidirectional", '
            '"open_questions": [{"question_id": str, "canonical_key": str, '
            '"scenario": str}]}}\n'
            "Do NOT invent library boundaries. Keep stubs shallow — "
            "one level deeper than names. Output ONLY the JSON object."
        )

        data: Any = None
        for attempt in range(1, self.MAX_PARSE_ATTEMPTS + 1):
            raw = run_agent(prompt)
            try:
                extracted = _extract_json_payload_from_llm_output(raw)
                data = json.loads(extracted)
                break
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.warning(
                    "Failed to parse skeleton LLM response on attempt %d/%d",
                    attempt,
                    self.MAX_PARSE_ATTEMPTS,
                )
                if attempt >= self.MAX_PARSE_ATTEMPTS:
                    raise SkeletonSynthesisTransientParseError(
                        attempts=attempt,
                        max_attempts=self.MAX_PARSE_ATTEMPTS,
                    ) from exc
        if not isinstance(data, dict):
            logger.warning(
                "Skeleton LLM response root is %s, expected object; returning empty spec",
                type(data).__name__,
            )
            return SkeletonSpec(
                problem_frame=problem_frame,
                concept_map=concept_map,
                open_question_ids=open_question_ids,
                constraint_refs=constraint_refs,
            )

        expected_sections = ("workflows", "entities", "interfaces")
        missing_sections = [section for section in expected_sections if section not in data]
        unexpected_sections = [key for key in data if key not in expected_sections]
        if missing_sections:
            logger.warning(
                "Skeleton LLM response missing sections %s; "
                "defaulting missing sections to empty lists",
                missing_sections,
            )
        if unexpected_sections:
            logger.warning(
                "Skeleton LLM response includes unexpected sections %s; ignoring extras",
                unexpected_sections,
            )

        def _coerce_section(section_name: str) -> list[dict[str, Any]]:
            raw_section = data.get(section_name, [])
            if raw_section is None:
                return []
            if not isinstance(raw_section, list):
                logger.warning(
                    "Skeleton LLM response section %r is %s, expected list; using empty list",
                    section_name,
                    type(raw_section).__name__,
                )
                return []

            normalized_items: list[dict[str, Any]] = []
            for idx, raw_item in enumerate(raw_section):
                if not isinstance(raw_item, dict):
                    logger.warning(
                        "Skeleton LLM response item %s[%d] is %s, expected object; dropping item",
                        section_name,
                        idx,
                        type(raw_item).__name__,
                    )
                    continue
                normalized_items.append(raw_item)
            return normalized_items

        workflow_items = _coerce_section("workflows")
        entity_items = _coerce_section("entities")
        interface_items = _coerce_section("interfaces")

        fallback_records = (
            open_question_records
            if open_question_records
            else [{"question_id": qid} for qid in open_question_ids]
        )

        workflows = []
        question_ref_omissions: list[dict[str, Any]] = []

        for idx, w in enumerate(workflow_items):
            q_ids, canonical_keys, scenarios, omissions = _extract_question_metadata(
                w, fallback_records
            )
            question_ref_omissions.extend(
                {
                    "section": "workflows",
                    "item_index": idx,
                    "item_name": str(w.get("name", "")).strip(),
                    **omission,
                }
                for omission in omissions
            )
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
        for idx, e in enumerate(entity_items):
            q_ids, canonical_keys, scenarios, omissions = _extract_question_metadata(
                e, fallback_records
            )
            question_ref_omissions.extend(
                {
                    "section": "entities",
                    "item_index": idx,
                    "item_name": str(e.get("name", "")).strip(),
                    **omission,
                }
                for omission in omissions
            )
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
        for idx, i in enumerate(interface_items):
            q_ids, canonical_keys, scenarios, omissions = _extract_question_metadata(
                i, fallback_records
            )
            question_ref_omissions.extend(
                {
                    "section": "interfaces",
                    "item_index": idx,
                    "item_name": str(i.get("name", "")).strip(),
                    **omission,
                }
                for omission in omissions
            )
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
            question_ref_omissions=question_ref_omissions,
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
        lines.extend(
            _question_todo_lines(
                w.name, list(w.open_question_ids), list(w.canonical_keys), list(w.scenarios)
            )
        )
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
        lines.extend(
            _question_todo_lines(
                f"entity {e.name}",
                list(e.open_question_ids),
                list(e.canonical_keys),
                list(e.scenarios),
            )
        )
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

    question_ids, canonical_keys, scenarios, question_ref_omissions = _normalize_question_refs(
        open_questions
    )
    snapshot = {
        "problem_frame": problem_frame,
        "concept_map": concept_map,
        "open_questions": [
            {
                "question_id": qid,
                "canonical_key": canonical_key,
                "scenario": scenario,
            }
            for qid, canonical_key, scenario in zip(
                question_ids, canonical_keys, scenarios, strict=True
            )
        ],
        "open_question_ref_omissions": question_ref_omissions,
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
    open_constraint_dimensions = set(queue_state.get("open_constraint_dimensions", []) or [])
    closed_constraint_dimensions = set(queue_state.get("closed_constraint_dimensions", []) or [])
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
