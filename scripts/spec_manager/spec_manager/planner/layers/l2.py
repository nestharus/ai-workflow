"""L2 (architecture) layer planner.

L2 routes architecture source artifacts (manifests, pin registries,
entrypoints, wiring declarations) into a decision-point planning loop.
Discovery is scoped to the current slice context rather than scanning
the full workspace graph up front.

Tools (research, integration, evidence) are injected at construction
time and are optional -- ``None`` means "skip that capability for now".
Actual LLM invocations will be wired through the tool callables later;
this module structures the data and delegates.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# Type alias for injected tool callables (all are optional).
_ToolFn = Callable[..., Any] | None


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _normalize_mode(mode_value: Any) -> str:
    mode = str(mode_value or "auto").strip().lower()
    if mode == "interactive":
        return "interactive"
    return "auto"


def _estimate_touched_files(gaps: list[dict[str, Any]]) -> int:
    files: set[str] = set()
    for gap in gaps:
        file_value = gap.get("file")
        if isinstance(file_value, str) and file_value.strip():
            files.add(file_value.strip())
        target_files = gap.get("target_files")
        if isinstance(target_files, list):
            for item in target_files:
                text = str(item).strip()
                if text:
                    files.add(text)
    return len(files)


# ---------------------------------------------------------------------------
# Architecture topology helpers
# ---------------------------------------------------------------------------

_ARCH_FILE_GLOBS: list[str] = [
    "**/component_manifest.yaml",
    "**/component_manifest.yml",
    "**/pins_registry.yaml",
    "**/pins_registry.yml",
    "**/entrypoints.yaml",
    "**/entrypoints.yml",
    "**/wiring.yaml",
    "**/wiring.yml",
]

_ARCH_FILE_BASENAMES = frozenset(
    {
        "component_manifest.yaml",
        "component_manifest.yml",
        "pins_registry.yaml",
        "pins_registry.yml",
        "entrypoints.yaml",
        "entrypoints.yml",
        "wiring.yaml",
        "wiring.yml",
    }
)


def _empty_topology() -> dict[str, Any]:
    """Return an empty architecture topology skeleton."""
    return {
        "nodes": [],
        "edges": [],
        "arch_files": [],
    }


def _is_relative_to(path: Path, candidate_parent: Path) -> bool:
    try:
        path.relative_to(candidate_parent)
    except ValueError:
        return False
    return True


def _discover_arch_files(*, workspace_root: Path | None, scope_roots: list[Path]) -> list[str]:
    """Return architecture file paths scoped to the current slice roots."""
    found: list[str] = []
    for scope_root in scope_roots:
        if not scope_root.is_dir():
            continue
        for pattern in _ARCH_FILE_GLOBS:
            for match in sorted(scope_root.glob(pattern)):
                if workspace_root is not None and _is_relative_to(match, workspace_root):
                    found.append(str(match.relative_to(workspace_root)))
                else:
                    found.append(str(match.relative_to(scope_root)))
    # Deduplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for p in found:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _normalize_arch_file_ref(
    raw_ref: str,
    *,
    workspace_root: Path | None,
    scope_roots: list[Path],
) -> str:
    text = str(raw_ref).strip()
    if not text:
        return ""
    candidate = Path(text)
    if not candidate.is_absolute():
        return text.replace("\\", "/")

    if workspace_root is not None and _is_relative_to(candidate, workspace_root):
        return str(candidate.relative_to(workspace_root)).replace("\\", "/")

    for scope_root in scope_roots:
        if _is_relative_to(candidate, scope_root):
            if workspace_root is not None and _is_relative_to(scope_root, workspace_root):
                rel = scope_root.relative_to(workspace_root) / candidate.relative_to(scope_root)
                return str(rel).replace("\\", "/")
            return str(candidate.relative_to(scope_root)).replace("\\", "/")

    return str(candidate).replace("\\", "/")


def _looks_like_arch_file_ref(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = text.replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1] if "/" in normalized else normalized
    return basename in _ARCH_FILE_BASENAMES


def _extract_arch_file_refs_from_integration_payload(payload: Any) -> list[str]:
    refs: list[str] = []
    queue: list[Any] = [payload]

    while queue:
        item = queue.pop(0)
        if isinstance(item, str):
            if _looks_like_arch_file_ref(item):
                refs.append(item.strip())
            continue
        if isinstance(item, (list, tuple, set)):
            queue.extend(item)
            continue
        if not isinstance(item, dict):
            continue

        for key, value in item.items():
            lowered = str(key).strip().lower()
            if lowered in {
                "arch_files",
                "artifact_refs",
                "files",
                "paths",
                "scoped_arch_files",
                "routed_arch_files",
                "source_artifacts",
            }:
                queue.append(value)
                continue
            if lowered in {"file", "path", "source_file", "target_file"}:
                queue.append(value)
                continue
            if lowered in {"nodes", "edges"} and isinstance(value, list):
                for row in value:
                    if isinstance(row, dict):
                        queue.append(row.get("file"))
                        queue.append(row.get("path"))
                        queue.append(row.get("source_file"))
                        queue.append(row.get("target_file"))

    deduped: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        deduped.append(ref)
    return deduped


# ---------------------------------------------------------------------------
# L2Planner
# ---------------------------------------------------------------------------


class L2Planner:
    """Architecture-layer planner.

    Satisfies the ``LayerPlanner`` protocol defined in
    ``spec_manager.planner.router``.

    Parameters
    ----------
    research_tool:
        Optional callable for research queries (e.g. LLM-based arch
        reasoning).  ``None`` to skip.
    integration_tool:
        Optional callable for integration / artifact routing analysis.
        ``None`` to skip.
    evidence_tool:
        Optional callable for evidence-store lookups.
        ``None`` to skip.
    constraints_store_adapter:
        Optional orchestration adapter handle. L2 planning always runs
        the strategy pipeline and bootstraps constraints from workspace
        state.
    """

    def __init__(
        self,
        research_tool: _ToolFn = None,
        integration_tool: _ToolFn = None,
        evidence_tool: _ToolFn = None,
        constraints_tool: _ToolFn = None,
        constraints_store_adapter: Any = None,
        work_item_store: Any = None,
        wait_graph: Any = None,
    ) -> None:
        self.layer: Literal["l2"] = "l2"
        self._research_tool = research_tool
        self._integration_tool = integration_tool
        self._evidence_tool = evidence_tool
        self._constraints_tool = constraints_tool
        self._constraints_store_adapter = constraints_store_adapter
        self._work_item_store = work_item_store
        self._wait_graph = wait_graph

    # ------------------------------------------------------------------
    # LayerPlanner interface
    # ------------------------------------------------------------------

    def discover(self, ctx: Any) -> dict[str, Any]:
        """Route slice-scoped architecture artifacts into a discovery summary."""
        workspace_root, scope_roots = self._resolve_discovery_roots(ctx)
        routed_arch_files = _discover_arch_files(
            workspace_root=workspace_root,
            scope_roots=scope_roots,
        )

        topology = _empty_topology()
        topology["arch_files"] = routed_arch_files
        topology["scope_roots"] = [str(root) for root in scope_roots]
        discovery_issues: list[str] = []

        if not scope_roots:
            discovery_issues.append("No scoped architecture roots were resolved for this slice.")

        if not routed_arch_files:
            discovery_issues.append(
                "No architecture manifest files were discovered in scoped roots "
                "(component_manifest/pins_registry/entrypoints/wiring)."
            )

        if self._integration_tool is None:
            discovery_issues.append("No integration tool is configured for L2 artifact routing.")
        else:
            try:
                enriched: Any
                if callable(self._integration_tool):
                    enriched = self._integration_tool(
                        workspace_root=str(workspace_root) if workspace_root is not None else "",
                        scope_roots=[str(root) for root in scope_roots],
                        arch_files=routed_arch_files,
                    )
                elif hasattr(self._integration_tool, "build_graph"):
                    discovery_issues.append(
                        "Integration tool exposes build_graph but no artifact-routing payload; "
                        "derived topology is ignored by SEC-105 design."
                    )
                    enriched = None
                else:
                    enriched = None

                integration_refs = _extract_arch_file_refs_from_integration_payload(enriched)
                merged_refs = [
                    _normalize_arch_file_ref(
                        ref,
                        workspace_root=workspace_root,
                        scope_roots=scope_roots,
                    )
                    for ref in integration_refs
                ]
                normalized_refs = [ref for ref in merged_refs if ref]
                for ref in normalized_refs:
                    if ref not in topology["arch_files"]:
                        topology["arch_files"].append(ref)
                topology["integration_artifact_refs"] = normalized_refs
            except Exception:
                logger.warning(
                    "L2 integration_tool failed during artifact routing",
                    exc_info=True,
                )
                discovery_issues.append(
                    "Integration tool failed during architecture artifact routing."
                )

        topology["discovery_status"] = "ready" if not discovery_issues else "incomplete"
        topology["discovery_issues"] = discovery_issues

        logger.debug(
            "L2 discover: %d scoped roots, %d arch files, %d integration refs, %d issues",
            len(scope_roots),
            len(topology["arch_files"]),
            len(topology.get("integration_artifact_refs", [])),
            len(discovery_issues),
        )
        return topology

    def build_plan(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce wiring intentions from *gaps* and architecture *discovery*.

        Always runs the full strategy pipeline (impact classification,
        constraint loading, problem framing, architecture decisions,
        candidate evaluation, authority checks).
        """
        return self._build_plan_via_strategies(ctx, gaps, discovery)

    @staticmethod
    def _resolve_discovery_roots(ctx: Any) -> tuple[Path | None, list[Path]]:
        """Resolve directory roots to scan for architecture artifacts."""
        roots: list[Path] = []
        seen: set[Path] = set()

        workspace_value = str(getattr(ctx, "workspace_root", "") or "").strip()
        workspace_root = Path(workspace_value) if workspace_value else None
        if workspace_root is not None:
            try:
                workspace_root = workspace_root.resolve()
            except OSError:
                workspace_root = None
        if workspace_root is not None and not workspace_root.is_dir():
            workspace_root = None

        def _append_root(path: Path | None) -> None:
            if path is None:
                return
            try:
                resolved = path.resolve()
            except OSError:
                return
            if not resolved.is_dir() or resolved in seen:
                return
            seen.add(resolved)
            roots.append(resolved)

        slice_root_value = str(getattr(ctx, "slice_root", "") or "").strip()
        if slice_root_value:
            _append_root(Path(slice_root_value))

        slice_id = str(getattr(ctx, "slice_id", "") or "").strip()
        if workspace_root is not None and slice_id:
            _append_root(workspace_root / "libraries" / slice_id)

        metadata = getattr(ctx, "metadata", {})
        if isinstance(metadata, dict) and workspace_root is not None:
            for key in ("focus_libraries", "libraries", "library_ids"):
                libs = metadata.get(key)
                if not isinstance(libs, list):
                    continue
                for lib in libs:
                    lib_name = str(lib).strip()
                    if lib_name:
                        _append_root(workspace_root / "libraries" / lib_name)

        # Treat workspace root as scoped only when no multi-library layout exists.
        if not roots and workspace_root is not None and not (workspace_root / "libraries").exists():
            _append_root(workspace_root)

        return workspace_root, roots

    @staticmethod
    def _build_gap_intentions(gaps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Build minimal wiring intentions directly from gap payloads."""
        intentions: list[dict[str, Any]] = []
        for gap in gaps:
            if not isinstance(gap, dict):
                continue
            target_files = gap.get("target_files", [])
            if not isinstance(target_files, list):
                target_files = []
            if (
                not target_files
                and isinstance(gap.get("file"), str)
                and str(gap.get("file", "")).strip()
            ):
                target_files = [str(gap.get("file", "")).strip()]

            approach = str(gap.get("description", gap.get("summary", ""))).strip()
            intentions.append(
                {
                    "component_id": str(gap.get("component_id") or gap.get("id") or "").strip(),
                    "target_files": [
                        str(path).strip() for path in target_files if str(path).strip()
                    ],
                    "approach": approach,
                    "pin_refs": [
                        str(ref).strip() for ref in gap.get("pin_refs", []) if str(ref).strip()
                    ]
                    if isinstance(gap.get("pin_refs"), list)
                    else [],
                    "dependencies": [
                        str(dep).strip() for dep in gap.get("dependencies", []) if str(dep).strip()
                    ]
                    if isinstance(gap.get("dependencies"), list)
                    else [],
                }
            )
        return intentions

    @staticmethod
    def _normalize_intentions_for_output(
        intentions: list[dict[str, Any]],
        gaps: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Project strategy outputs onto the L2 wiring intention contract."""
        normalized: list[dict[str, Any]] = []
        for index, intention in enumerate(intentions):
            if not isinstance(intention, dict):
                continue
            if "component_id" in intention:
                normalized.append(dict(intention))
                continue

            gap = gaps[index] if index < len(gaps) and isinstance(gaps[index], dict) else {}
            target_files = gap.get("target_files", [])
            if not isinstance(target_files, list):
                target_files = []
            if (
                not target_files
                and isinstance(gap.get("file"), str)
                and str(gap.get("file", "")).strip()
            ):
                target_files = [str(gap.get("file", "")).strip()]

            approach = str(intention.get("approach", "")).strip()
            if approach in {"stub_proposal", "parse_error"}:
                approach = ""
            if not approach:
                approach = str(intention.get("details", "")).strip()
            if approach == "No LLM available":
                approach = ""
            if not approach:
                approach = str(gap.get("description", gap.get("summary", ""))).strip()

            normalized.append(
                {
                    "component_id": str(
                        gap.get("component_id") or gap.get("id") or intention.get("source") or ""
                    ).strip(),
                    "target_files": [
                        str(path).strip() for path in target_files if str(path).strip()
                    ],
                    "approach": approach,
                    "pin_refs": [
                        str(ref).strip() for ref in gap.get("pin_refs", []) if str(ref).strip()
                    ]
                    if isinstance(gap.get("pin_refs"), list)
                    else [],
                    "dependencies": [
                        str(dep).strip() for dep in gap.get("dependencies", []) if str(dep).strip()
                    ]
                    if isinstance(gap.get("dependencies"), list)
                    else [],
                }
            )
        return normalized

    @staticmethod
    def _normalize_decision_requirements_for_output(
        requirements: list[Any],
    ) -> list[dict[str, Any]]:
        """Normalize decision requirements into a stable intention-embedded shape."""
        normalized: list[dict[str, Any]] = []
        for requirement in requirements:
            if isinstance(requirement, dict):
                payload = dict(requirement)
            elif hasattr(requirement, "to_dict") and callable(requirement.to_dict):
                raw_payload = requirement.to_dict()
                if not isinstance(raw_payload, dict):
                    continue
                payload = dict(raw_payload)
            else:
                continue

            decision_id = str(payload.get("decision_id", "")).strip()
            if not decision_id:
                continue
            payload["decision_id"] = decision_id
            payload["question"] = str(payload.get("question", "")).strip()
            payload["kind"] = str(payload.get("kind", "")).strip()
            payload["dimension"] = str(payload.get("dimension", "software")).strip() or "software"
            payload["impact"] = str(payload.get("impact", "")).strip()

            scope_hint = str(payload.get("scope_hint", "")).strip()
            if not scope_hint:
                scope_hint = str(payload.get("scope", "")).strip()
            if scope_hint:
                payload["scope_hint"] = scope_hint

            options = payload.get("options", [])
            payload["options"] = (
                [str(option).strip() for option in options if str(option).strip()]
                if isinstance(options, list)
                else []
            )

            needed_for_raw = payload.get("needed_for", [])
            if isinstance(needed_for_raw, list):
                needed_for = [
                    str(target).strip() for target in needed_for_raw if str(target).strip()
                ]
            elif str(needed_for_raw).strip():
                needed_for = [str(needed_for_raw).strip()]
            else:
                needed_for = []
            payload["needed_for"] = needed_for
            normalized.append(payload)
        return normalized

    @staticmethod
    def _find_requirement_intention_index(
        intentions: list[dict[str, Any]],
        requirement: dict[str, Any],
    ) -> int | None:
        needed_for = requirement.get("needed_for", [])
        needed_tokens = {
            str(target).strip().lower() for target in needed_for if str(target).strip()
        }
        if not needed_tokens:
            return None

        for index, intention in enumerate(intentions):
            component_id = str(intention.get("component_id", "")).strip().lower()
            if component_id and component_id in needed_tokens:
                return index

            target_files = intention.get("target_files", [])
            if not isinstance(target_files, list):
                target_files = []
            normalized_targets = [
                str(path).strip().lower() for path in target_files if str(path).strip()
            ]
            if any(
                any(token in target for target in normalized_targets) for token in needed_tokens
            ):
                return index

            target_file = str(intention.get("target_file", "")).strip().lower()
            if target_file and any(token in target_file for token in needed_tokens):
                return index

        return None

    @classmethod
    def _attach_decision_requirements_to_intentions(
        cls,
        intentions: list[dict[str, Any]],
        decision_requirements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not decision_requirements:
            return intentions

        if not intentions:
            return [
                {
                    "component_id": "",
                    "target_files": [],
                    "approach": "Resolve planning decision requirements before implementation.",
                    "decision_requirements": [dict(item) for item in decision_requirements],
                }
            ]

        enriched_intentions = [dict(intention) for intention in intentions]
        for intention in enriched_intentions:
            decision_reqs = intention.get("decision_requirements", [])
            if isinstance(decision_reqs, list):
                intention["decision_requirements"] = [
                    dict(item) for item in decision_reqs if isinstance(item, dict)
                ]
            else:
                intention["decision_requirements"] = []

        for requirement in decision_requirements:
            target_index = cls._find_requirement_intention_index(enriched_intentions, requirement)
            if target_index is None:
                target_index = 0
            enriched_intentions[target_index]["decision_requirements"].append(dict(requirement))

        return enriched_intentions

    def _build_plan_via_strategies(
        self,
        ctx: Any,
        gaps: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the strategy pipeline for L2 plan building."""
        from spec_manager.planner.strategies.architecture_strategy import (
            ArchitecturePlannerStrategy,
        )
        from spec_manager.planner.strategies.authority_strategy import AuthorityDeciderStrategy
        from spec_manager.planner.strategies.constraint_strategies import (
            CandidateEvaluatorStrategy,
            ConstraintBootstrapStrategy,
            ConstraintEnricherStrategy,
            ImpactClassifierStrategy,
            NonSoftwareChecklistStrategy,
            ProblemFramerStrategy,
            QuestionComposerStrategy,
            TradeoffMapperStrategy,
        )
        from spec_manager.planner.strategies.protocol import PlanningSession, PlanningSessionRunner

        workspace_root = Path(getattr(ctx, "workspace_root", "") or "")
        mode = _normalize_mode(getattr(ctx, "mode", "auto"))
        metadata = getattr(ctx, "metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        security_privacy_compliance = _coerce_bool(
            metadata.get("security_privacy_compliance", False)
        )
        security_privacy_compliance = (
            security_privacy_compliance
            or _coerce_bool(metadata.get("introduces_security_privacy_compliance", False))
            or _coerce_bool(metadata.get("has_security_privacy_compliance_implication", False))
        )

        session_ctx: dict[str, Any] = {
            "layer": "L2",
            "slice_id": getattr(ctx, "slice_id", ""),
            "run_id": getattr(ctx, "run_id", "default"),
            "workspace_root": str(workspace_root),
            "mode": mode,
            "interactive": mode == "interactive",
            "touched_files_count": _estimate_touched_files(gaps),
            "introduces_external_dep": _coerce_bool(metadata.get("introduces_external_dep", False)),
            "introduces_infra": _coerce_bool(metadata.get("introduces_infra", False)),
            "cross_library_contract": _coerce_bool(metadata.get("cross_library_contract", False)),
            "security_privacy_compliance": security_privacy_compliance,
            "bundle_ref": getattr(ctx, "bundle_ref", None),
            "metadata": metadata,
        }

        session = PlanningSession(
            ctx=session_ctx,
            gaps=gaps,
            discovery=discovery,
        )

        run_agent = self._research_tool

        strategies = [
            ImpactClassifierStrategy(),
            ProblemFramerStrategy(run_agent=run_agent),
            ConstraintBootstrapStrategy(workspace_root),
            ConstraintEnricherStrategy(run_agent=run_agent),
            TradeoffMapperStrategy(workspace_root),
            NonSoftwareChecklistStrategy(),
            ArchitecturePlannerStrategy(
                workspace_root,
                run_agent=run_agent,
                work_item_store=self._work_item_store,
                wait_graph=self._wait_graph,
                evidence_tool=self._evidence_tool,
            ),
            CandidateEvaluatorStrategy(),
            AuthorityDeciderStrategy(workspace_root),
            QuestionComposerStrategy(run_agent=run_agent),
        ]

        runner = PlanningSessionRunner(strategies)
        session = runner.run(session)

        intentions = self._normalize_intentions_for_output(session.intentions, gaps)
        if not intentions and gaps:
            intentions = self._build_gap_intentions(gaps)
        decision_requirements = self._normalize_decision_requirements_for_output(
            session.decision_requirements
        )
        intentions = self._attach_decision_requirements_to_intentions(
            intentions=intentions,
            decision_requirements=decision_requirements,
        )

        result: dict[str, Any] = {"intentions": intentions}
        if session.new_constraints:
            constraints_to_write = [
                constraint.to_dict()
                for constraint in session.new_constraints
                if str(getattr(constraint, "dimension", "")).strip().lower() == "software"
            ]
            if constraints_to_write:
                result["new_constraints_to_write"] = constraints_to_write
        if session.under_spec_events:
            result["under_spec_events"] = session.under_spec_events
        if session.decision_outcomes:
            result["decision_outcomes"] = [o.to_dict() for o in session.decision_outcomes]
        return result

    def resolve_under_spec(
        self,
        ctx: Any,
        events: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> dict[str, Any]:
        """Try to resolve under-spec events using architecture context.

        Resolution strategy (in order):
        1. Use routed architecture artifacts from *discovery* to see if the
           answer is derivable from known manifests / wiring declarations.
        2. If an ``evidence_tool`` is available, query it for prior
           findings that could fill the gap.
        3. If still unresolved, return ``blocked=True`` with questions
           for human input.
        """
        mode = _normalize_mode(getattr(ctx, "mode", "auto"))
        if mode == "interactive":
            questions = self._compose_interactive_under_spec_questions(events, discovery)
            return {
                "blocked": bool(questions),
                "constraints": {},
                "questions": questions,
            }

        workspace_root = self._resolve_workspace_root(getattr(ctx, "workspace_root", ""))
        scope_roots = self._collect_discovery_scope_roots(discovery)
        arch_file_refs = self._collect_discovery_arch_file_refs(discovery)
        resolved_constraints: dict[str, str] = {}
        remaining_questions: list[str] = []

        for event in events:
            event_id = event.get("id", event.get("event_id", ""))
            question = event.get("question", event.get("description", ""))
            constraint_key = event_id or question

            # Strategy 1: resolve from routed architecture artifacts.
            artifact_answer = self._resolve_event_from_artifacts(
                event=event,
                question=question,
                arch_file_refs=arch_file_refs,
                workspace_root=workspace_root,
                scope_roots=scope_roots,
            )
            if artifact_answer:
                resolved_constraints[constraint_key] = artifact_answer
                continue

            # Strategy 2: evidence lookup.
            if self._evidence_tool is not None:
                try:
                    evidence_hit: Any
                    if callable(self._evidence_tool):
                        evidence_hit = self._evidence_tool(
                            query=question,
                            layer="l2",
                            ctx_metadata=getattr(ctx, "metadata", {}),
                        )
                    elif hasattr(self._evidence_tool, "search"):
                        evidence_hit = self._evidence_tool.search(question, max_results=1)
                    else:
                        evidence_hit = None

                    answer = self._coerce_evidence_answer(evidence_hit)
                    if answer:
                        resolved_constraints[constraint_key] = answer
                        continue
                except Exception:
                    logger.warning(
                        "L2 evidence_tool failed for event %s",
                        event_id,
                        exc_info=True,
                    )

            # Strategy 3: cannot resolve -- block.
            if question:
                remaining_questions.append(question)
            elif constraint_key:
                remaining_questions.append(f"Cannot resolve under-spec event: {constraint_key}")

        blocked = len(remaining_questions) > 0
        return {
            "blocked": blocked,
            "constraints": resolved_constraints,
            "questions": remaining_questions,
        }

    def _compose_interactive_under_spec_questions(
        self,
        events: list[dict[str, Any]],
        discovery: dict[str, Any],
    ) -> list[str]:
        """Build question-first under-spec prompts with routed artifact context."""
        arch_file_refs = self._collect_discovery_arch_file_refs(discovery)
        questions: list[str] = []

        for event in events:
            event_id = str(event.get("id", event.get("event_id", ""))).strip()
            base_question = str(event.get("question", event.get("description", ""))).strip()
            if not base_question and event_id:
                base_question = f"What requirement should resolve decision {event_id}?"
            if not base_question:
                base_question = "What requirement should resolve this architecture ambiguity?"

            artifact_context = self._resolve_event_from_artifacts(
                event=event,
                question=base_question,
                arch_file_refs=arch_file_refs,
                workspace_root=None,
                scope_roots=[],
            )
            if artifact_context:
                questions.append(f"{base_question} Known artifacts: {artifact_context}")
                continue

            questions.append(
                f"{base_question} Missing routed artifact detail: specify "
                "source/target components, pins/interfaces, and the "
                "architecture files that define them."
            )
        return questions

    @staticmethod
    def _resolve_workspace_root(workspace_root_value: Any) -> Path | None:
        text = str(workspace_root_value or "").strip()
        if not text:
            return None
        try:
            path = Path(text).resolve()
        except OSError:
            return None
        return path if path.is_dir() else None

    @staticmethod
    def _collect_discovery_scope_roots(discovery: dict[str, Any]) -> list[Path]:
        raw_roots = discovery.get("scope_roots", [])
        if not isinstance(raw_roots, list):
            return []
        roots: list[Path] = []
        seen: set[Path] = set()
        for raw in raw_roots:
            text = str(raw or "").strip()
            if not text:
                continue
            try:
                candidate = Path(text).resolve()
            except OSError:
                continue
            if not candidate.is_dir() or candidate in seen:
                continue
            seen.add(candidate)
            roots.append(candidate)
        return roots

    @staticmethod
    def _collect_discovery_arch_file_refs(discovery: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        for key in ("arch_files", "integration_artifact_refs"):
            value = discovery.get(key, [])
            if not isinstance(value, list):
                continue
            refs.extend(str(item).strip() for item in value if str(item).strip())

        deduped: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            if ref in seen:
                continue
            seen.add(ref)
            deduped.append(ref)
        return deduped

    @staticmethod
    def _resolve_arch_ref_paths(
        ref: str,
        *,
        workspace_root: Path | None,
        scope_roots: list[Path],
    ) -> list[Path]:
        text = str(ref).strip()
        if not text:
            return []

        normalized = text.replace("\\", "/")
        candidates: list[Path] = []
        maybe_path = Path(normalized)
        if maybe_path.is_absolute():
            candidates.append(maybe_path)
        else:
            if workspace_root is not None:
                candidates.append(workspace_root / maybe_path)
            for scope_root in scope_roots:
                candidates.append(scope_root / maybe_path)

        resolved: list[Path] = []
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                path = candidate.resolve()
            except OSError:
                continue
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            resolved.append(path)
        return resolved

    @staticmethod
    def _collect_event_terms(event: dict[str, Any], question: str) -> set[str]:
        terms: set[str] = set()
        for key in (
            "component_id",
            "target",
            "file",
            "symbol",
            "source_component",
            "target_component",
            "pin_id",
            "pin_ref",
            "event_id",
            "contract_name",
            "event_name",
        ):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                terms.add(value.strip().lower())
        pin_refs = event.get("pin_refs")
        if isinstance(pin_refs, list):
            for pin in pin_refs:
                if isinstance(pin, str) and pin.strip():
                    terms.add(pin.strip().lower())

        question_text = str(question or "").strip().lower()
        if question_text:
            terms.add(question_text)
            for token in re.split(r"[^a-z0-9._:/#-]+", question_text):
                if len(token) >= 3:
                    terms.add(token)

        return {term for term in terms if term}

    @staticmethod
    def _resolve_event_from_artifacts(
        event: dict[str, Any],
        question: str,
        arch_file_refs: list[str],
        workspace_root: Path | None,
        scope_roots: list[Path],
    ) -> str | None:
        """Return a constraint answer derived from routed architecture artifacts."""
        if not arch_file_refs:
            return None

        terms = L2Planner._collect_event_terms(event, question)
        if not terms:
            return None

        matched_refs: list[str] = []
        for ref in arch_file_refs[:80]:
            ref_text = ref.lower()
            if any(term in ref_text for term in terms):
                matched_refs.append(ref)
                continue

            if workspace_root is None and not scope_roots:
                continue

            candidate_paths = L2Planner._resolve_arch_ref_paths(
                ref,
                workspace_root=workspace_root,
                scope_roots=scope_roots,
            )
            if not candidate_paths:
                continue

            for candidate in candidate_paths:
                try:
                    contents = candidate.read_text(encoding="utf-8", errors="ignore").lower()
                except OSError:
                    continue
                if any(term in contents for term in terms):
                    matched_refs.append(ref)
                    break

        if not matched_refs:
            return None

        return f"Artifact-derived resolution: relevant_refs={', '.join(matched_refs[:5])}."

    @staticmethod
    def _coerce_evidence_answer(evidence_hit: Any) -> str:
        """Normalize evidence-tool responses to a persisted string answer."""
        if evidence_hit is None:
            return ""
        if isinstance(evidence_hit, str):
            return evidence_hit.strip()
        if isinstance(evidence_hit, dict):
            for key in ("answer", "text", "synthesis", "detail"):
                value = evidence_hit.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        best_hit = getattr(evidence_hit, "best_hit", None)
        if best_hit is not None:
            text = getattr(best_hit, "text", "")
            if isinstance(text, str) and text.strip():
                return text.strip()
        text = getattr(evidence_hit, "text", "")
        if isinstance(text, str) and text.strip():
            return text.strip()
        rendered = str(evidence_hit).strip()
        return rendered[:1000] if rendered else ""

    def resolve_signal(self, ctx: Any, signal: Any) -> dict[str, Any] | None:
        """Attempt to resolve an ambiguity signal from architecture context.

        If an ``evidence_tool`` is available, look up prior evidence
        that might clarify the signal.  Returns a resolution dict or
        ``None`` when the signal cannot be resolved at this layer.
        """
        if signal is None:
            return None

        signal_text = signal if isinstance(signal, str) else getattr(signal, "text", str(signal))

        if self._evidence_tool is not None:
            try:
                result = self._evidence_tool(
                    query=signal_text,
                    layer="l2",
                    ctx_metadata=getattr(ctx, "metadata", {}),
                )
                if result:
                    return {
                        "resolved": True,
                        "source": "evidence",
                        "detail": result,
                    }
            except Exception:
                logger.warning(
                    "L2 evidence_tool failed in resolve_signal",
                    exc_info=True,
                )

        # Cannot resolve at this layer.
        return None

    def triage_signal(self, ctx: Any, signal: dict[str, Any]) -> dict[str, Any]:
        """Triage a coordination signal into scoped architecture decision work."""
        if not isinstance(signal, dict):
            return {"action": "NOOP", "monitors": []}

        inter_scope = _extract_inter_scope_from_signal(signal)
        if inter_scope is None:
            return {"action": "NOOP", "monitors": []}

        summary = _extract_signal_summary(signal, scope=inter_scope)
        trigger_refs = _collect_signal_trigger_refs(signal)
        decision_hash = sha256(f"{inter_scope}|{summary}".encode()).hexdigest()[:12]
        decision_id = f"DEC-{decision_hash}"
        work_item_id = decision_id

        target_slice = str(getattr(ctx, "slice_id", "") or "").strip()
        if not target_slice:
            target_slice = _parse_inter_scope_components(inter_scope)[0]
        signal_id = str(signal.get("signal_id", "")).strip()

        location = _extract_signal_location(signal)
        routing_payload = _build_arch_decision_routing_payload(
            work_item_id=work_item_id,
            summary=summary,
            owner_slice_id=target_slice,
            scope=inter_scope,
            trigger_refs=trigger_refs,
            location=location,
        )

        existing_work_item_status = ""
        if self._work_item_store is not None:
            try:
                from spec_manager.orchestration.coordination.work_items import (
                    WorkItem,
                    WorkItemLocation,
                )

                existing = self._work_item_store.get(work_item_id)
                if existing is None:
                    self._work_item_store.add(
                        WorkItem(
                            work_item_id=work_item_id,
                            spec_text=summary,
                            owner_slice_id=target_slice,
                            status="NEW",
                            kind="ARCH_DECISION",
                            location=WorkItemLocation(
                                file=location["file"],
                                symbol=location["symbol"],
                                line_hint=location["line_hint"],
                            ),
                            metadata={
                                "scope": inter_scope,
                                "trigger_refs": trigger_refs,
                                "signal_id": signal_id,
                            },
                        )
                    )
                else:
                    existing_work_item_status = str(getattr(existing, "status", "")).strip().upper()
                    routing_payload = {}
            except Exception:
                logger.warning(
                    "Failed to persist L2 ARCH_DECISION triage work item for scope %s",
                    inter_scope,
                    exc_info=True,
                )

        if existing_work_item_status in {"MERGED", "DONE"}:
            return {
                "action": "WAKE_IMMEDIATELY",
                "monitors": [],
                "routing": [],
                "scope": inter_scope,
                "why": "cross_boundary_decision_already_resolved",
            }

        monitor = {
            "type": "work_item_done",
            "work_item_id": work_item_id,
            "required_status": "MERGED",
            "kind": "work_item_status",
            "signal_id": signal_id,
            "run_id": str(getattr(ctx, "run_id", "") or "").strip(),
            "timeout_seconds": 3600,
        }
        if routing_payload:
            return {
                "action": "ROUTE_AND_WAIT",
                "routing": [routing_payload],
                "monitors": [monitor],
                "scope": inter_scope,
                "why": "cross_boundary_evidence_requires_l2_decision",
            }

        return {
            "action": "WAIT_ON_WORK_ITEM",
            "routing": [],
            "monitors": [monitor],
            "scope": inter_scope,
            "why": "cross_boundary_evidence_waiting_existing_l2_decision",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_inter_scope_from_signal(signal: dict[str, Any]) -> str | None:
    for mapping in _walk_mappings(signal):
        scope_candidate = _normalize_inter_scope(mapping.get("scope"))
        if scope_candidate:
            return scope_candidate

    for mapping in _walk_mappings(signal):
        source_lib, target_lib = _extract_library_pair(mapping)
        if not source_lib or not target_lib or source_lib == target_lib:
            continue
        interaction_handle = _extract_interaction_handle(mapping)
        if not interaction_handle:
            continue
        return f"inter:{source_lib}->{target_lib}:{interaction_handle}"

    return None


def _normalize_inter_scope(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text.startswith("inter:"):
        return None
    body = text.removeprefix("inter:").strip()
    if "->" not in body or ":" not in body:
        return None
    source_part, remainder = body.split("->", 1)
    target_part, handle_part = remainder.split(":", 1)
    source_lib = _normalize_library_name(source_part)
    target_lib = _normalize_library_name(target_part)
    handle = _normalize_handle(handle_part)
    if not source_lib or not target_lib or not handle:
        return None
    if source_lib == target_lib:
        return None
    return f"inter:{source_lib}->{target_lib}:{handle}"


def _extract_library_pair(mapping: dict[str, Any]) -> tuple[str, str]:
    pair_keys = (
        ("source_library", "target_library"),
        ("producer_library", "consumer_library"),
        ("provider_library", "consumer_library"),
        ("from_library", "to_library"),
        ("source_lib", "target_lib"),
    )
    for source_key, target_key in pair_keys:
        source_lib = _normalize_library_name(mapping.get(source_key))
        target_lib = _normalize_library_name(mapping.get(target_key))
        if source_lib and target_lib:
            return source_lib, target_lib

    for list_key in ("libraries", "library_ids", "focus_libraries"):
        raw_value = mapping.get(list_key)
        if not isinstance(raw_value, list):
            continue
        normalized = [_normalize_library_name(item) for item in raw_value]
        libs = [lib for lib in normalized if lib]
        if len(libs) >= 2:
            return libs[0], libs[1]

    return "", ""


def _extract_interaction_handle(mapping: dict[str, Any]) -> str:
    preferred_keys = (
        "interaction_handle",
        "event_name",
        "contract_name",
        "pin_mismatch",
        "pin_id",
        "pin_ref",
        "import_path",
        "import_symbol",
        "call_symbol",
        "call_name",
        "event",
        "contract",
        "pin",
        "edge_id",
        "event_id",
    )
    for key in preferred_keys:
        handle = _normalize_handle(mapping.get(key))
        if handle:
            return handle
    return ""


def _normalize_library_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    token = text.replace("\\", "/")
    if token.lower().startswith("libraries/"):
        parts = [part for part in token.split("/") if part]
        if len(parts) >= 2:
            token = parts[1]
    elif "/" in token:
        token = token.rsplit("/", 1)[-1]
    token = token.strip()
    if not token:
        return ""
    lowered = token.lower()
    if lowered in {"lib", "library", "libraries", "unknown", "tbd"}:
        return ""
    return token


def _normalize_handle(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"interaction", "handle", "unknown", "tbd", "todo"}:
        return ""
    compact = re.sub(r"\s+", "_", text)
    compact = re.sub(r"[^A-Za-z0-9._:/#-]+", "_", compact)
    compact = compact.strip("._:/#-")
    return compact


def _walk_mappings(value: Any) -> list[dict[str, Any]]:
    queue: list[Any] = [value]
    mappings: list[dict[str, Any]] = []
    while queue:
        item = queue.pop(0)
        if isinstance(item, dict):
            mappings.append(item)
            queue.extend(item.values())
            continue
        if isinstance(item, list):
            queue.extend(item)
    return mappings


def _parse_inter_scope_components(scope: str) -> tuple[str, str, str]:
    body = str(scope).removeprefix("inter:")
    source_part, remainder = body.split("->", 1)
    target_part, handle_part = remainder.split(":", 1)
    return source_part.strip(), target_part.strip(), handle_part.strip()


def _extract_signal_summary(signal: dict[str, Any], *, scope: str) -> str:
    need = signal.get("need", {})
    if isinstance(need, dict):
        for key in ("summary", "reason", "artifact_key"):
            text = str(need.get(key, "")).strip()
            if text:
                return text

    payload = signal.get("payload", {})
    if isinstance(payload, dict):
        under_spec_event = payload.get("under_spec_event")
        if isinstance(under_spec_event, dict):
            text = str(
                under_spec_event.get("question", under_spec_event.get("description", ""))
            ).strip()
            if text:
                return text
    question = str(signal.get("question", "")).strip()
    if question:
        return question
    return f"Resolve cross-library architecture decision for {scope}"


def _extract_signal_location(signal: dict[str, Any]) -> dict[str, Any]:
    spec_refs = signal.get("spec_refs", [])
    if isinstance(spec_refs, list):
        for row in spec_refs:
            if not isinstance(row, dict):
                continue
            file_hint = str(row.get("source_file", "")).strip()
            symbol = str(row.get("source_symbol", "")).strip()
            try:
                line_hint = int(row.get("source_line_hint", 0) or 0)
            except (TypeError, ValueError):
                line_hint = 0
            if file_hint or symbol:
                return {"file": file_hint, "symbol": symbol, "line_hint": line_hint}
    return {"file": "", "symbol": "", "line_hint": 0}


def _collect_signal_trigger_refs(signal: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    spec_refs = signal.get("spec_refs", [])
    if isinstance(spec_refs, list):
        for row in spec_refs:
            if not isinstance(row, dict):
                continue
            source_file = str(row.get("source_file", "")).strip()
            line_hint = str(row.get("source_line_hint", "")).strip()
            if source_file and line_hint:
                refs.append(f"{source_file}:{line_hint}")
            elif source_file:
                refs.append(source_file)

    for mapping in _walk_mappings(signal):
        for key in ("trigger_evidence", "evidence_refs", "event_id", "pin_ref", "pin_id"):
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                refs.append(value.strip())
            elif isinstance(value, list):
                refs.extend(str(item).strip() for item in value if str(item).strip())

    seen: set[str] = set()
    deduped: list[str] = []
    for ref in refs:
        if ref in seen:
            continue
        seen.add(ref)
        deduped.append(ref)
    return deduped


def _build_arch_decision_routing_payload(
    *,
    work_item_id: str,
    summary: str,
    owner_slice_id: str,
    scope: str,
    trigger_refs: list[str],
    location: dict[str, Any],
) -> dict[str, Any]:
    return {
        "work_item_id": work_item_id,
        "spec_text": summary,
        "owner_slice_id": owner_slice_id,
        "status": "NEW",
        "kind": "ARCH_DECISION",
        "location": {
            "file": str(location.get("file", "")).strip(),
            "symbol": str(location.get("symbol", "")).strip(),
            "line_hint": int(location.get("line_hint", 0) or 0),
        },
        "metadata": {
            "scope": scope,
            "trigger_refs": trigger_refs,
        },
    }
