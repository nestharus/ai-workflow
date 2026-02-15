"""Architecture planning strategy.

Gated by L2 + impact >= MEDIUM. Detects decision points, proposes candidates,
evaluates them, persists artifacts, creates ARCH_DECISION work items, and
manages WaitGraph edges for blocked decisions.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spec_manager.planner.architecture.artifacts import persist_decision_artifacts
from spec_manager.planner.architecture.decision_detector import DecisionPointDetector
from spec_manager.planner.architecture.evaluator import CandidateEvaluator
from spec_manager.planner.architecture.proposer import ProposerOrchestrator
from spec_manager.planner.architecture.types import DecisionOutcome, ScopePacket
from spec_manager.planner.constraints.types import ConstraintFact

from .protocol import PlanningSession

logger = logging.getLogger(__name__)


class ArchitecturePlannerStrategy:
    """Architecture decision strategy. Only runs for L2 + impact >= MEDIUM.

    Orchestrates:
    1. Decision point detection via :class:`DecisionPointDetector`.
    2. ARCH_DECISION work item creation for coordination tracking.
    3. ScopePacket population from routed source artifacts.
    4. Candidate proposal via :class:`ProposerOrchestrator` (K=3 for HIGH, K=2 for MEDIUM).
    5. Candidate evaluation via :class:`CandidateEvaluator`.
    6. Artifact persistence via :func:`persist_decision_artifacts`.
    7. WaitGraph edge creation for blocked decisions.
    8. Accumulation of outcomes, wiring intentions, and new constraints on the session.

    Args:
        workspace_root: Workspace root directory.
        run_agent: Optional LLM callable for testability.
        work_item_store: Optional :class:`WorkItemStore` for ARCH_DECISION tracking.
        wait_graph: Optional :class:`WaitGraph` for blocked-decision edges.
    """

    @property
    def name(self) -> str:
        return "architecture_planner"

    def __init__(
        self,
        workspace_root: Path,
        run_agent: Callable[..., str] | None = None,
        work_item_store: Any = None,
        wait_graph: Any = None,
        evidence_tool: Any = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._run_agent = run_agent
        self._work_item_store = work_item_store
        self._wait_graph = wait_graph
        self._evidence_tool = evidence_tool

    def run(self, session: PlanningSession) -> PlanningSession:
        if not self._should_run(session):
            return session

        slice_id = session.ctx.get("slice_id", "unknown")
        run_id = session.ctx.get("run_id", "default")

        # Gather authoritative constraints
        auth_constraints = []
        if session.constraint_context:
            auth_constraints = session.constraint_context.authoritative

        evidence_refs = self._collect_slice_evidence_refs(session, slice_id)

        # 1. Detect decision points
        detector = DecisionPointDetector(
            workspace_root=self._workspace_root,
            run_agent=self._run_agent,
        )
        decision_points = detector.detect(
            slice_id=slice_id,
            gaps=session.gaps,
            discovery=session.discovery,
            evidence_refs=evidence_refs,
            authoritative_constraints=auth_constraints,
        )

        if not decision_points:
            return session

        # 2. Create ARCH_DECISION work items for coordination tracking
        self._create_work_items(decision_points, slice_id)

        # Determine K based on impact; MEDIUM receives a small option set (2-3).
        k = 3 if session.impact and session.impact.impact == "HIGH" else 2

        proposer = ProposerOrchestrator(
            workspace_root=self._workspace_root,
            k=k,
            run_agent=self._run_agent,
        )
        evaluator = CandidateEvaluator(
            workspace_root=self._workspace_root,
            run_agent=self._run_agent,
        )

        # 3-7. For each decision point: build scope, propose, evaluate, persist
        for dp in decision_points:
            # 3. Build ScopePacket with routed source artifacts
            scope_packet = self._build_scope_packet(
                dp,
                slice_id,
                auth_constraints,
                session,
            )

            # 4. Propose candidates
            candidates = proposer.run_proposers(dp, scope_packet)

            # 5. Evaluate candidates
            assessments = evaluator.evaluate(candidates, auth_constraints)
            outcome = evaluator.select_or_block(dp, candidates, assessments, auth_constraints)

            # 6. Persist artifacts
            persist_decision_artifacts(
                workspace_root=self._workspace_root,
                run_id=run_id,
                decision_id=dp.decision_id,
                candidates=candidates,
                assessments=assessments,
                outcome=outcome,
            )

            # 7. Update work item status + WaitGraph for blocked decisions
            self._update_coordination(dp, outcome, slice_id)

            # 8. Accumulate on session
            session.decision_outcomes.append(outcome)

            if outcome.committed:
                session.intentions.extend(outcome.wiring_intentions)
                new_facts = self._materialize_outcome_constraints(dp, outcome, candidates)
                if new_facts:
                    existing_constraint_ids = {
                        fact.constraint_id for fact in session.new_constraints if fact.constraint_id
                    }
                    for fact in new_facts:
                        if fact.constraint_id in existing_constraint_ids:
                            continue
                        session.new_constraints.append(fact)
                        if fact.authority_required == "planner_ok":
                            auth_constraints.append(fact)
                        existing_constraint_ids.add(fact.constraint_id)

            if outcome.under_spec_events:
                session.under_spec_events.extend(outcome.under_spec_events)

        return session

    def _should_run(self, session: PlanningSession) -> bool:
        """Check if this strategy should run: L2 + impact >= MEDIUM."""
        layer = session.ctx.get("layer", "L1").upper()
        if layer != "L2":
            return False
        if session.impact is None:
            return False
        return session.impact.impact in ("MEDIUM", "HIGH")

    # ------------------------------------------------------------------
    # ScopePacket population (Fix 7)
    # ------------------------------------------------------------------

    def _build_scope_packet(
        self,
        dp: Any,
        slice_id: str,
        auth_constraints: list[Any],
        session: PlanningSession,
    ) -> ScopePacket:
        """Build a ScopePacket with routed source artifacts for a decision point."""
        source_artifacts: dict[str, Any] = {}
        arch_refs: list[str] = []

        # Load source artifacts based on scope
        scope = str(dp.scope or "").strip()
        intra_scope = self._parse_intra_scope(scope)
        inter_scope = self._parse_inter_scope(scope)
        if intra_scope is not None:
            lib_name, sub_scope = intra_scope
            source_artifacts = self._load_intra_artifacts(lib_name, sub_scope=sub_scope)
        elif inter_scope is not None:
            source_artifacts = self._load_inter_artifacts(scope)

        # Current arch state refs from routed discovery + scope artifacts
        arch_refs = self._project_arch_refs(source_artifacts, session.discovery)

        # Tradeoff assignment from session axes
        tradeoff_assignment: dict[str, str] = {}
        if session.tradeoff_axes:
            for axis in session.tradeoff_axes[:5]:
                tradeoff_assignment[axis] = "consider"

        return ScopePacket(
            decision_id=dp.decision_id,
            scope=dp.scope,
            trigger_evidence=dp.trigger_evidence,
            source_artifacts=source_artifacts,
            authoritative_constraints=auth_constraints,
            current_arch_state_refs=arch_refs,
            tradeoff_assignment=tradeoff_assignment,
        )

    @staticmethod
    def _project_arch_refs(
        source_artifacts: dict[str, Any],
        discovery: dict[str, Any],
    ) -> list[str]:
        refs: list[str] = []
        arch_payload = source_artifacts.get("arch_files")
        if isinstance(arch_payload, dict | list):
            refs.extend(str(name).strip() for name in arch_payload if str(name).strip())

        if not refs:
            for lib_payload in source_artifacts.values():
                if not isinstance(lib_payload, dict):
                    continue
                nested = lib_payload.get("arch_files")
                if isinstance(nested, dict):
                    refs.extend(str(name).strip() for name in nested if str(name).strip())

        if not refs:
            discovery_refs = discovery.get("arch_files", [])
            if isinstance(discovery_refs, list):
                refs.extend(str(name).strip() for name in discovery_refs if str(name).strip())

        seen: set[str] = set()
        deduped: list[str] = []
        for ref in refs:
            if ref in seen:
                continue
            seen.add(ref)
            deduped.append(ref)
        return deduped

    def _collect_slice_evidence_refs(self, session: PlanningSession, slice_id: str) -> list[str]:
        refs: list[str] = []
        for gap in session.gaps:
            if not isinstance(gap, dict):
                continue
            self._extend_refs(refs, gap.get("evidence_refs"))
            self._extend_refs(refs, gap.get("trigger_evidence"))
            self._extend_refs(refs, gap.get("source_refs"))
            self._extend_refs(refs, gap.get("target_files"))
            self._extend_refs(refs, gap.get("file"))

        self._extend_refs(refs, session.ctx.get("evidence_refs"))
        bundle_ref = session.ctx.get("bundle_ref")
        if bundle_ref is not None:
            self._extend_refs(refs, self._collect_bundle_evidence_refs(bundle_ref))

        self._extend_refs(refs, self._query_evidence_tool(slice_id, session.ctx))

        seen: set[str] = set()
        deduped: list[str] = []
        for ref in refs:
            if ref in seen:
                continue
            seen.add(ref)
            deduped.append(ref)
        return deduped

    @staticmethod
    def _extend_refs(refs: list[str], value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            text = value.strip()
            if text:
                refs.append(text)
            return
        if isinstance(value, list):
            for item in value:
                ArchitecturePlannerStrategy._extend_refs(refs, item)
            return
        if isinstance(value, (tuple, set)):
            for item in value:
                ArchitecturePlannerStrategy._extend_refs(refs, item)
            return
        if isinstance(value, dict):
            for key in ("ref", "path", "evidence_ref", "evidence_path", "file"):
                if key in value:
                    ArchitecturePlannerStrategy._extend_refs(refs, value.get(key))
            return

    @staticmethod
    def _collect_bundle_evidence_refs(bundle_ref: Any) -> list[str]:
        refs: list[str] = []
        facts = getattr(bundle_ref, "facts", None)
        if facts is None and isinstance(bundle_ref, dict):
            facts = bundle_ref.get("facts")
        if isinstance(facts, dict):
            claims = facts.get("llm_claims", [])
            constraints_refs = facts.get("constraints_refs", [])
        else:
            claims = getattr(facts, "llm_claims", []) if facts is not None else []
            constraints_refs = getattr(facts, "constraints_refs", []) if facts is not None else []

        ArchitecturePlannerStrategy._extend_refs(refs, constraints_refs)
        for claim in claims if isinstance(claims, list) else []:
            if not isinstance(claim, dict):
                continue
            ArchitecturePlannerStrategy._extend_refs(refs, claim.get("evidence_refs"))
            ArchitecturePlannerStrategy._extend_refs(refs, claim.get("file"))

        source_index = getattr(bundle_ref, "source_index", None)
        if source_index is None and isinstance(bundle_ref, dict):
            source_index = bundle_ref.get("source_index")
        entries = (
            source_index.get("entries", [])
            if isinstance(source_index, dict)
            else getattr(source_index, "entries", [])
        )
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            ArchitecturePlannerStrategy._extend_refs(refs, entry.get("path"))

        return refs

    def _query_evidence_tool(self, slice_id: str, ctx: dict[str, Any]) -> list[str]:
        if self._evidence_tool is None:
            return []

        refs: list[str] = []
        query = f"{slice_id} architecture decision evidence"
        try:
            if callable(self._evidence_tool):
                raw = self._evidence_tool(
                    query=query,
                    layer="l2",
                    ctx_metadata=ctx,
                )
            elif hasattr(self._evidence_tool, "search"):
                raw = self._evidence_tool.search(query, max_results=5)
            else:
                raw = None
        except Exception:
            logger.debug("Failed querying evidence tool for slice %s", slice_id, exc_info=True)
            return []

        if raw is None:
            return []
        if isinstance(raw, dict):
            self._extend_refs(refs, raw.get("evidence_refs"))
            self._extend_refs(refs, raw.get("hits"))
            return refs
        hits = getattr(raw, "hits", None)
        if isinstance(hits, list):
            for hit in hits:
                if isinstance(hit, dict):
                    self._extend_refs(refs, hit.get("section_path"))
                    self._extend_refs(refs, hit.get("lib_id"))
                else:
                    self._extend_refs(refs, getattr(hit, "section_path", ""))
                    self._extend_refs(refs, getattr(hit, "lib_id", ""))
            return refs
        return refs

    def _materialize_outcome_constraints(
        self,
        decision_point: Any,
        outcome: DecisionOutcome,
        candidates: list[Any],
    ) -> list[ConstraintFact]:
        if not outcome.committed or not outcome.new_constraints:
            return []

        selected = None
        for candidate in candidates:
            if candidate.candidate_id == outcome.selected_candidate_id:
                selected = candidate
                break
        if selected is None:
            return []

        software_constraints = selected.constraints_introduced.get("software", {})
        non_software_constraints = selected.constraints_introduced.get("non_software", {})
        if not isinstance(software_constraints, dict):
            software_constraints = {}
        if not isinstance(non_software_constraints, dict):
            non_software_constraints = {}

        facts: list[ConstraintFact] = []
        for constraint_id in outcome.new_constraints:
            cid = str(constraint_id).strip()
            if not cid:
                continue
            if cid in software_constraints:
                fact = self._build_constraint_fact(
                    constraint_id=cid,
                    payload=software_constraints.get(cid),
                    scope=decision_point.scope,
                    dimension="software",
                    decision_id=decision_point.decision_id,
                    candidate_id=selected.candidate_id,
                )
            else:
                fact = self._build_constraint_fact(
                    constraint_id=cid,
                    payload=non_software_constraints.get(cid),
                    scope=decision_point.scope,
                    dimension="operational",
                    decision_id=decision_point.decision_id,
                    candidate_id=selected.candidate_id,
                )
            if fact is not None:
                facts.append(fact)
        return facts

    @staticmethod
    def _build_constraint_fact(
        *,
        constraint_id: str,
        payload: Any,
        scope: str,
        dimension: str,
        decision_id: str,
        candidate_id: str,
    ) -> ConstraintFact | None:
        question = f"Architecture decision constraint {constraint_id}"
        answer = ""
        resolved_dimension = dimension
        resolved_authority = "planner_ok" if dimension == "software" else "human_required"

        if isinstance(payload, dict):
            text_question = str(payload.get("question", "")).strip()
            text_answer = str(payload.get("answer", payload.get("value", ""))).strip()
            payload_dimension = str(payload.get("dimension", "")).strip().lower()
            payload_authority_required = str(payload.get("authority_required", "")).strip().lower()
            if text_question:
                question = text_question
            answer = text_answer or json.dumps(payload, sort_keys=True)
            if payload_dimension in {
                "software",
                "legal",
                "economic",
                "organizational",
                "temporal",
                "operational",
            }:
                resolved_dimension = payload_dimension
            if payload_authority_required in {"planner_ok", "human_required"}:
                resolved_authority = payload_authority_required
            elif resolved_dimension != "software":
                resolved_authority = "human_required"
        elif isinstance(payload, str):
            answer = payload.strip()
        elif payload is not None:
            answer = str(payload).strip()

        if not answer:
            answer = f"Constraint committed by {decision_id}/{candidate_id}"

        resolved_scope = scope or "system"
        applies_to_layers = ArchitecturePlannerStrategy._resolve_applies_to_layers(
            payload=payload,
            dimension=resolved_dimension,
            scope=resolved_scope,
            question=question,
            answer=answer,
        )

        return ConstraintFact(
            constraint_id=constraint_id,
            question=question,
            answer=answer,
            source="research",
            confidence=1.0,
            validated=True,
            dimension=resolved_dimension,  # type: ignore[arg-type]
            authority_required=resolved_authority,  # type: ignore[arg-type]
            decision_type="architecture_decision",
            scope=resolved_scope,
            applies_to_layers=applies_to_layers,
            status="ACTIVE",
            trace=[
                f"decision_id={decision_id}",
                f"candidate_id={candidate_id}",
                "origin=architecture_planner",
            ],
        )

    @staticmethod
    def _resolve_applies_to_layers(
        *,
        payload: Any,
        dimension: str,
        scope: str,
        question: str,
        answer: str,
    ) -> list[str]:
        explicit = ArchitecturePlannerStrategy._extract_layer_targets(payload)
        if explicit:
            return explicit
        if dimension != "software":
            return ["L2"]
        if ArchitecturePlannerStrategy._is_l1_obligation(
            payload=payload,
            scope=scope,
            question=question,
            answer=answer,
        ):
            return ["L1", "L2"]
        return ["L2"]

    @staticmethod
    def _extract_layer_targets(payload: Any) -> list[str]:
        if not isinstance(payload, dict):
            return []
        raw_layers = payload.get("applies_to_layers", [])
        if isinstance(raw_layers, str):
            candidate_values = [raw_layers]
        elif isinstance(raw_layers, list):
            candidate_values = [str(item) for item in raw_layers]
        else:
            return []

        normalized: list[str] = []
        for value in candidate_values:
            for token in value.replace("|", ",").split(","):
                layer = token.strip().upper()
                if layer in {"L1", "L2", "L3"} and layer not in normalized:
                    normalized.append(layer)
        return normalized

    @staticmethod
    def _is_l1_obligation(
        *,
        payload: Any,
        scope: str,
        question: str,
        answer: str,
    ) -> bool:
        if isinstance(payload, dict):
            for key in ("requires_l1_implementation", "implementation_required_for_l1"):
                if bool(payload.get(key, False)):
                    return True

            for key in (
                "kind",
                "constraint_kind",
                "obligation_type",
                "requirement_type",
            ):
                token = str(payload.get(key, "")).strip().lower()
                if any(marker in token for marker in ("contract", "ordering", "idempot")):
                    return True

        text_blob = " ".join(
            part
            for part in (
                str(scope or ""),
                str(question or ""),
                str(answer or ""),
                json.dumps(payload, sort_keys=True) if isinstance(payload, dict) else "",
            )
            if part
        ).lower()
        return any(
            marker in text_blob
            for marker in (
                "contract",
                "ordering",
                "idempot",
                "must implement",
                "implementation requirement",
            )
        )

    def _load_intra_artifacts(self, lib_name: str, *, sub_scope: str = "") -> dict[str, Any]:
        """Load charter, constraints, and details for a single library."""
        artifacts: dict[str, Any] = {}
        lib_dir = self._workspace_root / "libraries" / lib_name

        if not lib_dir.exists():
            return artifacts

        if sub_scope:
            artifacts["scope_filter"] = {"intra_sub_scope": sub_scope}

        for name, key in [
            ("charter.md", "charter_text"),
            ("constraints.md", "constraint_spans"),
            ("details.md", "details_text"),
        ]:
            path = lib_dir / name
            if path.exists():
                try:
                    contents = path.read_text(encoding="utf-8")
                    if sub_scope and not self._text_matches_scope_filter(contents, sub_scope):
                        continue
                    artifacts[key] = contents
                except OSError:
                    # C03: Surface errors — missing artifact needs diagnosis
                    logger.warning(
                        "Failed to read %s for architecture strategy", path, exc_info=True
                    )

        # Load arch files if present
        for arch_name in [
            "component_manifest.yaml",
            "pins_registry.yaml",
            "wiring.yaml",
            "entrypoints.yaml",
        ]:
            path = lib_dir / arch_name
            if path.exists():
                try:
                    contents = path.read_text(encoding="utf-8")
                    if sub_scope and not self._text_matches_scope_filter(
                        f"{arch_name}\n{contents}", sub_scope
                    ):
                        continue
                    artifacts.setdefault("arch_files", {})[arch_name] = contents
                except OSError:
                    # C03: Surface errors — missing artifact needs diagnosis
                    logger.warning(
                        "Failed to read %s for architecture strategy", path, exc_info=True
                    )

        return artifacts

    def _load_inter_artifacts(self, scope: str) -> dict[str, Any]:
        """Load artifacts for both sides of an inter-library interaction."""
        artifacts: dict[str, Any] = {}
        parsed = self._parse_inter_scope(scope)
        if parsed is None:
            return artifacts
        source_lib, target_lib, interaction_handle = parsed
        artifacts["interaction_handle"] = interaction_handle

        for lib_name in (source_lib, target_lib):
            lib_artifacts = self._load_intra_artifacts(lib_name)
            filtered = self._filter_artifacts_for_interaction(lib_artifacts, interaction_handle)
            if filtered:
                artifacts[lib_name] = filtered

        return artifacts

    @staticmethod
    def _parse_intra_scope(scope: str) -> tuple[str, str] | None:
        text = str(scope or "").strip()
        if not text.startswith("intra:"):
            return None
        body = text.removeprefix("intra:").strip()
        if not body:
            return None
        segments = [segment.strip() for segment in body.split(":")]
        lib_name = segments[0] if segments else ""
        if not lib_name or lib_name.upper() == "LIB":
            return None
        sub_scope = ":".join(segment for segment in segments[1:] if segment)
        return lib_name, sub_scope

    @staticmethod
    def _parse_inter_scope(scope: str) -> tuple[str, str, str] | None:
        text = str(scope or "").strip()
        if not text.startswith("inter:"):
            return None
        body = text.removeprefix("inter:").strip()
        if "->" not in body or ":" not in body:
            return None
        left, right = body.split("->", 1)
        source_lib = left.strip()
        target_part, handle_part = right.split(":", 1)
        target_lib = target_part.strip()
        interaction_handle = handle_part.strip()
        if not source_lib or not target_lib or not interaction_handle:
            return None
        if source_lib.upper() == "LIB" or target_lib.upper() == "LIB":
            return None
        return source_lib, target_lib, interaction_handle

    def _filter_artifacts_for_interaction(
        self, artifacts: dict[str, Any], interaction_handle: str
    ) -> dict[str, Any]:
        if not artifacts:
            return {}
        filtered: dict[str, Any] = {}
        scope_filter_raw = artifacts.get("scope_filter", {})
        scope_filter = dict(scope_filter_raw) if isinstance(scope_filter_raw, dict) else {}
        scope_filter["interaction_handle"] = interaction_handle
        filtered["scope_filter"] = scope_filter

        for key, value in artifacts.items():
            if key == "scope_filter":
                continue
            if key == "arch_files" and isinstance(value, dict):
                matches = {
                    name: text
                    for name, text in value.items()
                    if self._text_matches_scope_filter(f"{name}\n{text}", interaction_handle)
                }
                if matches:
                    filtered["arch_files"] = matches
                continue
            # Keep charter/constraints/details as baseline library context while
            # narrowing architecture manifests to interaction-specific evidence.
            filtered[key] = value
        return filtered

    @staticmethod
    def _text_matches_scope_filter(text: str, scope_fragment: str) -> bool:
        if not scope_fragment:
            return True
        expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", scope_fragment)
        tokens = [token for token in re.split(r"[^A-Za-z0-9]+", expanded.lower()) if token]
        if not tokens:
            return True
        haystack = str(text).lower()
        return all(token in haystack for token in tokens)

    # ------------------------------------------------------------------
    # Coordination: WorkItems + WaitGraph (Fixes 4, 6)
    # ------------------------------------------------------------------

    def _create_work_items(self, decision_points: list[Any], slice_id: str) -> None:
        """Create ARCH_DECISION work items for each decision point."""
        if self._work_item_store is None:
            return

        from spec_manager.orchestration.coordination.work_items import WorkItem

        for dp in decision_points:
            existing = self._work_item_store.get(dp.decision_id)
            if existing is not None:
                continue  # Already tracked

            wi = WorkItem(
                work_item_id=dp.decision_id,
                spec_text=dp.description,
                owner_slice_id=dp.owner_slice_id or slice_id,
                status="NEW",
                kind="ARCH_DECISION",
                metadata={
                    "scope": dp.scope,
                    "trigger_refs": dp.trigger_evidence,
                    "required_constraints": dp.required_constraints,
                },
            )
            try:
                self._work_item_store.add(wi)
            except Exception:
                logger.warning(
                    "Failed to create ARCH_DECISION work item %s",
                    dp.decision_id,
                    exc_info=True,
                )

    def _update_coordination(
        self,
        dp: Any,
        outcome: DecisionOutcome,
        slice_id: str,
    ) -> None:
        """Update work item status and add WaitGraph edges for blocked decisions."""
        # Update work item status
        if self._work_item_store is not None:
            try:
                if outcome.committed:
                    self._work_item_store.update_status(dp.decision_id, "DONE")
                elif outcome.under_spec_events or outcome.decision_requirements:
                    self._work_item_store.update_status(dp.decision_id, "BLOCKED")
                else:
                    self._work_item_store.update_status(dp.decision_id, "IN_PROGRESS")
            except (KeyError, ValueError):
                logger.debug(
                    "Could not update work item status for %s",
                    dp.decision_id,
                    exc_info=True,
                )

        # Add WaitGraph edges for blocked decisions
        if self._wait_graph is not None and not outcome.committed and outcome.decision_requirements:
            from spec_manager.orchestration.coordination.wait_graph import WaitEdge

            existing_edges = {
                (edge.waiting_slice, edge.provider_slice)
                for edge in self._wait_graph.get_waiting_on(slice_id)
            }

            for requirement in outcome.decision_requirements:
                constraint_id = self._normalize_constraint_dependency_id(requirement)
                if not constraint_id:
                    continue
                if (slice_id, constraint_id) in existing_edges:
                    continue
                try:
                    self._wait_graph.add_edge(
                        WaitEdge(
                            waiting_slice=slice_id,
                            provider_slice=constraint_id,
                            artifact_key=f"constraint:{constraint_id}",
                            signal_id=f"constraint_wait:{slice_id}:{constraint_id}:{dp.decision_id}",
                        )
                    )
                    existing_edges.add((slice_id, constraint_id))
                except Exception:
                    # CyclicDependencyError or other — log and continue
                    logger.debug(
                        "Could not add wait edge %s -> %s",
                        slice_id,
                        constraint_id,
                        exc_info=True,
                    )

    @staticmethod
    def _normalize_constraint_dependency_id(requirement: Any) -> str:
        if isinstance(requirement, dict):
            for key in ("constraint_id", "constraint_key", "id"):
                candidate = str(requirement.get(key, "")).strip()
                if candidate:
                    return candidate
            return ""

        candidate = str(requirement or "").strip()
        if not candidate or any(char.isspace() for char in candidate):
            return ""
        return candidate
