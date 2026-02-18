# TODO(single-layer): RESTRUCTURE — Architecture strategy loses L2 gate. Instead
#   activates during Architecture phase (Section 9.1 phase 2 of 3). The core
#   algorithm (detect decision points -> propose candidates -> evaluate -> persist ->
#   create work items -> manage WaitGraph) all KEEPS. Shape docs inform which
#   components are affected by architecture decisions. Decision artifacts route by
#   shape_id instead of pin references.
# ALGORITHM(single-layer):
#   References: response3 Sections 9.1 and 7.2.
#   Data structures:
#     - PhaseId = Literal['libraries', 'architecture', 'quality'].
#     - DecisionOutcome metadata must include shape_id and contract_ids.
#     - ARCH_DECISION work items must include shape_id routing handle.
#   Interface contracts:
#     - def run(self, session: PlanningSession) -> PlanningSession
#     - def _should_run(self, session: PlanningSession) -> bool  # phase == 'architecture' and impact threshold
#   Control flow:
#     1. Replace L2 gating with architecture-phase gating (phase == 'architecture').
#     2. Keep detector/proposer/evaluator/persistence pipeline.
#     3. Build ScopePacket from shape ownership and shape contracts, not pin references.
#     4. Architecture phase edits code via PromotionLoop IMPLEMENT step — can edit
#        component structure AND algorithm implementations in-place.
#     5. Persist decision artifacts. Architecture can refine algorithms in-place within
#        existing library boundaries (no target_phase routing to libraries). If a decision
#        requires new library creation or ownership change, BLOCK with diagnostics.
#   Error handling:
#     - Missing shape mapping for a decision point creates blocked architecture decision and wait graph edge.
#   Integration points:
#     - Called by planner API capability PLAN during architecture phase.
#     - Calls work_item_store and wait_graph unchanged.
# IMPL(single-layer): ARCH_DECISION emissions from this strategy should populate the
# shared work-item routing contract (`shape_id`, `created_in_phase='architecture'`,
# `required_change_type`, `evidence_refs`, `contract_ids`) and persist through
# `WorkItemStore.create/upsert` rather than legacy status-only update paths.
# IMPL(single-layer): Session gating authority should read the forward-only phase
# context (`phase == 'architecture'`) from Section 9.1, not legacy layer ids.
#   Test requirements:
#     - Strategy runs only in architecture phase.
#     - Decision artifacts include shape IDs.
#     - Blocked decisions create wait graph edges.

"""Architecture planning strategy.

Gated by architecture phase + impact >= MEDIUM. Detects decision points, proposes candidates,
evaluates them, persists artifacts, creates ARCH_DECISION work items, and
manages WaitGraph edges for blocked decisions.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spec_manager.compliance.promotion.config import PhaseId
from spec_manager.planner.architecture.artifacts import persist_decision_artifacts
from spec_manager.planner.architecture.decision_detector import DecisionPointDetector
from spec_manager.planner.architecture.evaluator import CandidateEvaluator
from spec_manager.planner.architecture.proposer import ProposerOrchestrator
from spec_manager.planner.architecture.types import DecisionOutcome, ScopePacket
from spec_manager.planner.constraints.types import ConstraintFact

from .protocol import PlanningSession

logger = logging.getLogger(__name__)
_ARCHITECTURE_PHASE: PhaseId = "architecture"


class ArchitecturePlannerStrategy:
    """Architecture decision strategy. Only runs for architecture phase + impact >= MEDIUM.

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

        slice_id = str(session.ctx.get("slice_id", "unknown")).strip() or "unknown"
        run_id = str(session.ctx.get("run_id", "default")).strip() or "default"

        # Gather authoritative constraints
        auth_constraints = []
        if session.constraint_context:
            auth_constraints = session.constraint_context.authoritative

        evidence_refs, evidence_status = self._collect_slice_evidence_refs(session, slice_id)
        if evidence_status is not None:
            session.ctx["architecture_evidence_status"] = evidence_status
            session.add_under_spec_event(
                {
                    "type": "evidence_unavailable",
                    "question": "Evidence collection for architecture planning was partial.",
                    "reason": str(evidence_status.get("reason", "")).strip()
                    or "evidence source unavailable",
                    "detail": (
                        "Architecture decisions are proceeding with reduced evidence coverage."
                    ),
                    "source": str(evidence_status.get("source", "evidence_tool")).strip()
                    or "evidence_tool",
                    "slice_id": slice_id,
                    "query": str(evidence_status.get("query", "")).strip(),
                }
            )
        else:
            session.ctx.pop("architecture_evidence_status", None)

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

        decision_routing = self._resolve_decision_routings(
            decision_points=decision_points,
            slice_id=slice_id,
            discovery=session.discovery,
        )

        # 2. Create ARCH_DECISION work items for coordination tracking
        self._create_work_items(
            decision_points,
            slice_id,
            run_id,
            decision_routing,
        )

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
            routing = decision_routing.get(str(getattr(dp, "decision_id", "")).strip(), {})
            if not self._routing_has_shape_mapping(routing):
                outcome = self._build_missing_shape_mapping_outcome(dp, routing=routing)
                self._attach_outcome_metadata(outcome, routing)
                persist_decision_artifacts(
                    workspace_root=self._workspace_root,
                    run_id=run_id,
                    decision_id=dp.decision_id,
                    candidates=[],
                    assessments=[],
                    outcome=outcome,
                )
                self._update_coordination(
                    dp,
                    outcome,
                    slice_id,
                    run_id=run_id,
                    routing=routing,
                )
                session.decision_outcomes.append(outcome)
                if outcome.under_spec_events:
                    session.extend_under_spec_events(outcome.under_spec_events)
                continue

            # 3. Build ScopePacket with routed source artifacts
            scope_packet = self._build_scope_packet(
                dp,
                slice_id,
                auth_constraints,
                session,
                routing=routing,
            )

            # 4. Propose candidates
            candidates = proposer.run_proposers(dp, scope_packet)

            # 5. Evaluate candidates
            assessments = evaluator.evaluate(candidates, auth_constraints)
            outcome = evaluator.select_or_block(dp, candidates, assessments, auth_constraints)
            authority_violation = self._detect_architecture_authority_violation(
                decision_point=dp,
                outcome=outcome,
                candidates=candidates,
            )
            if authority_violation:
                outcome = self._block_outcome_for_authority_violation(
                    decision_point=dp,
                    prior_outcome=outcome,
                    diagnostic=authority_violation,
                )

            self._attach_outcome_metadata(outcome, routing)

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
            self._update_coordination(
                dp,
                outcome,
                slice_id,
                run_id=run_id,
                routing=routing,
            )

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
                session.extend_under_spec_events(outcome.under_spec_events)

        return session

    def _resolve_decision_routings(
        self,
        *,
        decision_points: list[Any],
        slice_id: str,
        discovery: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        routing: dict[str, dict[str, Any]] = {}
        shape_index = self._load_shape_index()
        for decision_point in decision_points:
            decision_id = str(getattr(decision_point, "decision_id", "")).strip()
            if not decision_id:
                continue
            routing[decision_id] = self._resolve_decision_routing(
                decision_point=decision_point,
                slice_id=slice_id,
                discovery=discovery,
                shape_index=shape_index,
            )
        return routing

    def _load_shape_index(self) -> Any | None:
        try:
            from spec_manager.routing import load_shape_pack

            return load_shape_pack(self._workspace_root)
        except Exception:
            logger.debug("Unable to load shape pack for architecture strategy", exc_info=True)
            return None

    def _resolve_decision_routing(
        self,
        *,
        decision_point: Any,
        slice_id: str,
        discovery: dict[str, Any],
        shape_index: Any | None,
    ) -> dict[str, Any]:
        owner_slice_id = (
            str(getattr(decision_point, "owner_slice_id", "")).strip() or str(slice_id).strip()
        )
        scope = str(getattr(decision_point, "scope", "") or "").strip()

        evidence_refs: list[str] = []
        self._extend_refs(evidence_refs, getattr(decision_point, "trigger_evidence", []))
        if isinstance(discovery, dict):
            self._extend_refs(evidence_refs, discovery.get("arch_files"))
            self._extend_refs(evidence_refs, discovery.get("files"))
        evidence_refs = self._dedupe_text_values(evidence_refs)

        candidate_shape_id = ""
        for key in ("shape_id", "owner_shape_id"):
            value = str(getattr(decision_point, key, "")).strip()
            if value:
                candidate_shape_id = value
                break

        lookup_refs = self._shape_lookup_refs(
            scope=scope,
            owner_slice_id=owner_slice_id,
            evidence_refs=evidence_refs,
        )
        if not candidate_shape_id and shape_index is not None:
            try:
                from spec_manager.routing import resolve_shape_for_file

                for file_ref in lookup_refs:
                    resolved = resolve_shape_for_file(file_ref, shape_index)
                    resolved_text = str(resolved or "").strip()
                    if resolved_text:
                        candidate_shape_id = resolved_text
                        break
            except Exception:
                logger.debug(
                    "Unable to resolve shape for decision scope %s",
                    scope,
                    exc_info=True,
                )

        if not candidate_shape_id and shape_index is not None and owner_slice_id:
            if self._shape_exists(shape_index, owner_slice_id):
                candidate_shape_id = owner_slice_id

        scope_fallback_reason = ""
        if not candidate_shape_id:
            intra_scope = self._parse_intra_scope(scope)
            if intra_scope is not None:
                candidate_shape_id = intra_scope[0]
                scope_fallback_reason = (
                    "Resolved shape routing from intra scope without shape-pack ownership evidence."
                )
        if not candidate_shape_id:
            inter_scope = self._parse_inter_scope(scope)
            if inter_scope is not None:
                source_lib, target_lib, _ = inter_scope
                if owner_slice_id in {source_lib, target_lib}:
                    candidate_shape_id = owner_slice_id
                else:
                    candidate_shape_id = source_lib
                scope_fallback_reason = (
                    "Resolved shape routing from inter scope without shape-pack ownership evidence."
                )

        contract_ids: list[str] = []
        verifier_ids: list[str] = []
        shape_metadata: dict[str, Any] = {}
        if candidate_shape_id and shape_index is not None:
            shape = self._find_shape(shape_index, candidate_shape_id)
            if shape is not None:
                contracts = getattr(shape, "contracts", [])
                for contract in contracts if isinstance(contracts, list) else []:
                    cid = str(getattr(contract, "contract_id", "")).strip()
                    if cid:
                        contract_ids.append(cid)

                verifiers = getattr(shape, "verifiers", [])
                for verifier in verifiers if isinstance(verifiers, list) else []:
                    vid = str(getattr(verifier, "verifier_id", "")).strip()
                    if vid:
                        verifier_ids.append(vid)

                shape_metadata = {
                    "shape_package": str(getattr(shape, "package", "")).strip(),
                    "shape_source_path": str(getattr(shape, "source_path", "")).strip(),
                }

        if candidate_shape_id:
            mapping_status = "resolved"
            mapping_reason = scope_fallback_reason
        else:
            mapping_status = "missing"
            mapping_reason = (
                f"No shape mapping could be resolved for decision scope '{scope or 'unknown'}'."
            )

        return {
            "owner_slice_id": owner_slice_id,
            "shape_id": candidate_shape_id,
            "contract_ids": self._dedupe_text_values(contract_ids),
            "verifier_ids": self._dedupe_text_values(verifier_ids),
            "evidence_refs": evidence_refs,
            "mapping_status": mapping_status,
            "mapping_reason": mapping_reason,
            "lookup_refs": lookup_refs,
            **shape_metadata,
        }

    @staticmethod
    def _dedupe_text_values(values: Any) -> list[str]:
        flattened: list[str] = []
        ArchitecturePlannerStrategy._extend_refs(flattened, values)
        if not flattened and values is not None and not isinstance(values, (dict, list, tuple, set)):
            flattened = [str(values).strip()]
        seen: set[str] = set()
        deduped: list[str] = []
        for value in flattened:
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        return deduped

    def _shape_lookup_refs(
        self,
        *,
        scope: str,
        owner_slice_id: str,
        evidence_refs: list[str],
    ) -> list[str]:
        refs: list[str] = []
        intra_scope = self._parse_intra_scope(scope)
        inter_scope = self._parse_inter_scope(scope)
        if intra_scope is not None:
            library_name, sub_scope = intra_scope
            refs.append(f"libraries/{library_name}")
            if sub_scope:
                refs.append(f"libraries/{library_name}/{sub_scope.replace(':', '/')}")
        if inter_scope is not None:
            source_lib, target_lib, _ = inter_scope
            refs.extend([f"libraries/{source_lib}", f"libraries/{target_lib}"])
        if owner_slice_id:
            refs.append(f"libraries/{owner_slice_id}")
            refs.append(owner_slice_id)
        for evidence_ref in evidence_refs:
            if "/" in evidence_ref or "\\" in evidence_ref:
                refs.append(evidence_ref)
        return self._dedupe_text_values(refs)

    @staticmethod
    def _shape_exists(shape_index: Any, shape_id: str) -> bool:
        shapes = getattr(shape_index, "shapes", {})
        if not isinstance(shapes, dict):
            return False
        target = str(shape_id).strip()
        if not target:
            return False
        for existing_shape_id in shapes:
            if str(existing_shape_id).strip() == target:
                return True
        return False

    @staticmethod
    def _find_shape(shape_index: Any, shape_id: str) -> Any | None:
        shapes = getattr(shape_index, "shapes", {})
        if not isinstance(shapes, dict):
            return None
        target = str(shape_id).strip()
        if not target:
            return None
        for existing_shape_id, shape in shapes.items():
            if str(existing_shape_id).strip() == target:
                return shape
        return None

    @staticmethod
    def _routing_has_shape_mapping(routing: dict[str, Any]) -> bool:
        return bool(str(routing.get("shape_id", "")).strip())

    def _build_missing_shape_mapping_outcome(
        self,
        decision_point: Any,
        *,
        routing: dict[str, Any],
    ) -> DecisionOutcome:
        decision_id = str(getattr(decision_point, "decision_id", "")).strip()
        scope = str(getattr(decision_point, "scope", "")).strip()
        reason = str(routing.get("mapping_reason", "")).strip() or (
            f"No shape mapping available for architecture decision scope '{scope or 'unknown'}'."
        )
        requirement_id = f"shape_mapping:{decision_id or 'unknown'}"
        return DecisionOutcome(
            decision_id=decision_id,
            committed=False,
            selected_candidate_id="",
            wiring_intentions=[],
            new_constraints=[],
            under_spec_events=[
                {
                    "type": "architecture_shape_mapping_missing",
                    "question": "Which shape owns this architecture decision?",
                    "reason": reason,
                    "detail": (
                        "Architecture decision is blocked until shape ownership mapping is resolved."
                    ),
                    "scope": scope,
                }
            ],
            decision_requirements=[requirement_id],
        )

    @staticmethod
    def _attach_outcome_metadata(
        outcome: DecisionOutcome,
        routing: dict[str, Any],
    ) -> None:
        metadata = {
            "shape_id": str(routing.get("shape_id", "")).strip(),
            "contract_ids": [
                str(item).strip()
                for item in routing.get("contract_ids", [])
                if str(item).strip()
            ],
        }
        outcome.metadata = metadata
        if outcome.wiring_intentions:
            for intention in outcome.wiring_intentions:
                if not isinstance(intention, dict):
                    continue
                intention.setdefault("shape_id", metadata["shape_id"])
                intention.setdefault("contract_ids", list(metadata["contract_ids"]))

    def _detect_architecture_authority_violation(
        self,
        *,
        decision_point: Any,
        outcome: DecisionOutcome,
        candidates: list[Any],
    ) -> str:
        if not outcome.committed:
            return ""

        selected_candidate = None
        for candidate in candidates:
            if str(getattr(candidate, "candidate_id", "")).strip() == str(
                outcome.selected_candidate_id
            ).strip():
                selected_candidate = candidate
                break
        if selected_candidate is None:
            return ""

        proposal = getattr(selected_candidate, "proposal", {})
        target_phase = str(
            proposal.get("target_phase", proposal.get("route_to_phase", ""))
            if isinstance(proposal, dict)
            else ""
        ).strip().lower()
        if target_phase and target_phase == "libraries":
            return (
                "Architecture decisions cannot route changes to libraries phase; "
                "implement in architecture phase or block."
            )

        allowed_libraries = self._allowed_scope_libraries(str(getattr(decision_point, "scope", "")))
        text_blob = self._candidate_text_blob(selected_candidate)
        if any(
            marker in text_blob
            for marker in (
                "create new library",
                "new library",
                "introduce new library",
                "add new library",
            )
        ):
            return (
                "Committed architecture candidate requires new library creation, "
                "which is outside architecture-phase authority."
            )
        if any(
            marker in text_blob
            for marker in (
                "ownership change",
                "change ownership",
                "transfer ownership",
                "move ownership",
                "re-home",
                "rehome",
            )
        ):
            return (
                "Committed architecture candidate requires shape ownership change, "
                "which must be blocked with diagnostics."
            )

        referenced_libraries = self._extract_referenced_libraries(text_blob)
        if allowed_libraries and referenced_libraries and not referenced_libraries.issubset(
            allowed_libraries
        ):
            return (
                "Committed architecture candidate references libraries outside the scoped "
                f"ownership boundary: allowed={sorted(allowed_libraries)} "
                f"referenced={sorted(referenced_libraries)}."
            )
        return ""

    @staticmethod
    def _candidate_text_blob(candidate: Any) -> str:
        fragments: list[str] = []
        for key in (
            "scope",
            "decision_id",
            "trace",
            "assumptions",
            "decision_requirements",
        ):
            value = getattr(candidate, key, None)
            if value is None:
                continue
            if isinstance(value, list):
                fragments.extend(str(item).strip() for item in value if str(item).strip())
            else:
                text = str(value).strip()
                if text:
                    fragments.append(text)
        proposal = getattr(candidate, "proposal", None)
        if proposal is not None:
            try:
                fragments.append(json.dumps(proposal, sort_keys=True))
            except (TypeError, ValueError):
                fragments.append(str(proposal))
        return " ".join(fragments).lower()

    @staticmethod
    def _allowed_scope_libraries(scope: str) -> set[str]:
        allowed: set[str] = set()
        intra_scope = ArchitecturePlannerStrategy._parse_intra_scope(scope)
        if intra_scope is not None:
            allowed.add(intra_scope[0].lower())
            return allowed
        inter_scope = ArchitecturePlannerStrategy._parse_inter_scope(scope)
        if inter_scope is not None:
            allowed.add(inter_scope[0].lower())
            allowed.add(inter_scope[1].lower())
        return allowed

    @staticmethod
    def _extract_referenced_libraries(text_blob: str) -> set[str]:
        matches: set[str] = set()
        for match in re.findall(r"libraries/([a-zA-Z0-9_.-]+)", text_blob):
            normalized = str(match).strip().lower()
            if normalized:
                matches.add(normalized)
        for match in re.findall(r"intra:([a-zA-Z0-9_.-]+)", text_blob):
            normalized = str(match).strip().lower()
            if normalized:
                matches.add(normalized)
        for source, target in re.findall(
            r"inter:([a-zA-Z0-9_.-]+)->([a-zA-Z0-9_.-]+)", text_blob
        ):
            if source:
                matches.add(source.strip().lower())
            if target:
                matches.add(target.strip().lower())
        return matches

    def _block_outcome_for_authority_violation(
        self,
        *,
        decision_point: Any,
        prior_outcome: DecisionOutcome,
        diagnostic: str,
    ) -> DecisionOutcome:
        decision_id = str(getattr(decision_point, "decision_id", "")).strip()
        requirement_token = f"architecture_authority:{decision_id or 'unknown'}"
        under_spec_events = list(prior_outcome.under_spec_events)
        under_spec_events.append(
            {
                "type": "architecture_out_of_authority",
                "question": "Can this architecture decision be implemented in-place?",
                "reason": diagnostic,
                "detail": (
                    "Architecture phase is forward-only and cannot perform ownership transfer "
                    "or new-library creation routing."
                ),
                "scope": str(getattr(decision_point, "scope", "")).strip(),
            }
        )
        return DecisionOutcome(
            decision_id=decision_id,
            committed=False,
            selected_candidate_id=str(prior_outcome.selected_candidate_id),
            wiring_intentions=[],
            new_constraints=[],
            under_spec_events=under_spec_events,
            decision_requirements=self._dedupe_text_values(
                [*prior_outcome.decision_requirements, requirement_token]
            ),
        )

    def _should_run(self, session: PlanningSession) -> bool:
        """Check if this strategy should run: architecture phase + impact >= MEDIUM."""
        # IMPL(single-layer): Replace `layer == "L2"` checks with
        # `phase == "architecture"` while keeping the impact threshold gate.
        phase = str(session.ctx.get("phase", "")).strip().lower()
        if phase != _ARCHITECTURE_PHASE:
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
        *,
        routing: dict[str, Any],
    ) -> ScopePacket:
        """Build a ScopePacket with routed source artifacts for a decision point."""
        # IMPL(single-layer): ScopePacket authority should come from shape ownership
        # + shape contracts/verifier refs (Sections 9.1/7.2), not pin references or
        # manifest-only routing assumptions.
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
            for axis in session.tradeoff_axes:
                tradeoff_assignment[axis] = "consider"

        evidence_status = session.ctx.get("architecture_evidence_status")
        if isinstance(evidence_status, dict):
            source_artifacts["evidence_status"] = dict(evidence_status)

        source_artifacts["shape_authority"] = {
            "shape_id": str(routing.get("shape_id", "")).strip(),
            "contract_ids": [
                str(item).strip()
                for item in routing.get("contract_ids", [])
                if str(item).strip()
            ],
            "verifier_ids": [
                str(item).strip()
                for item in routing.get("verifier_ids", [])
                if str(item).strip()
            ],
            "mapping_status": str(routing.get("mapping_status", "")).strip(),
            "mapping_reason": str(routing.get("mapping_reason", "")).strip(),
            "owner_slice_id": str(routing.get("owner_slice_id", "")).strip()
            or str(slice_id).strip(),
            "shape_package": str(routing.get("shape_package", "")).strip(),
            "shape_source_path": str(routing.get("shape_source_path", "")).strip(),
        }

        # IMPL(single-layer): Decision metadata persisted downstream should include
        # `shape_id` and `contract_ids` on the outcome/work-item path.
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

    def _collect_slice_evidence_refs(
        self,
        session: PlanningSession,
        slice_id: str,
    ) -> tuple[list[str], dict[str, Any] | None]:
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

        tool_refs, evidence_status = self._query_evidence_tool(slice_id, session.ctx)
        self._extend_refs(refs, tool_refs)

        seen: set[str] = set()
        deduped: list[str] = []
        for ref in refs:
            if ref in seen:
                continue
            seen.add(ref)
            deduped.append(ref)
        return deduped, evidence_status

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

    def _query_evidence_tool(
        self,
        slice_id: str,
        ctx: dict[str, Any],
    ) -> tuple[list[str], dict[str, Any] | None]:
        if self._evidence_tool is None:
            return [], None

        refs: list[str] = []
        query = f"{slice_id} architecture decision evidence"
        try:
            if callable(self._evidence_tool):
                raw = self._evidence_tool(
                    query=query,
                    phase=_ARCHITECTURE_PHASE,
                    ctx_metadata=ctx,
                )
            elif hasattr(self._evidence_tool, "search"):
                raw = self._evidence_tool.search(query, max_results=5)
            else:
                raw = None
        except Exception:
            logger.warning("Failed querying evidence tool for slice %s", slice_id, exc_info=True)
            return [], {
                "source": "evidence_tool",
                "status": "unavailable",
                "reason": "exception while querying evidence tool",
                "slice_id": slice_id,
                "query": query,
            }

        if raw is None:
            return [], {
                "source": "evidence_tool",
                "status": "unavailable",
                "reason": "evidence tool returned no result",
                "slice_id": slice_id,
                "query": query,
            }
        if isinstance(raw, dict):
            self._extend_refs(refs, raw.get("evidence_refs"))
            self._extend_refs(refs, raw.get("hits"))
            return refs, None
        hits = getattr(raw, "hits", None)
        if isinstance(hits, list):
            for hit in hits:
                if isinstance(hit, dict):
                    self._extend_refs(refs, hit.get("section_path"))
                    self._extend_refs(refs, hit.get("lib_id"))
                else:
                    self._extend_refs(refs, getattr(hit, "section_path", ""))
                    self._extend_refs(refs, getattr(hit, "lib_id", ""))
            return refs, None
        return refs, {
            "source": "evidence_tool",
            "status": "unavailable",
            "reason": "evidence tool result shape was not recognized",
            "slice_id": slice_id,
            "query": query,
        }

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
        resolved_source = "research"
        resolved_confidence = 0.3

        if isinstance(payload, dict):
            text_question = str(payload.get("question", "")).strip()
            text_answer = str(payload.get("answer", payload.get("value", ""))).strip()
            payload_dimension = str(payload.get("dimension", "")).strip().lower()
            payload_authority_required = str(payload.get("authority_required", "")).strip().lower()
            payload_source = str(payload.get("source", "")).strip().lower()
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
            if payload_source in {"user", "research", "steering", "existing"}:
                resolved_source = payload_source
            resolved_confidence = ArchitecturePlannerStrategy._derive_generated_fact_confidence(
                payload.get("confidence")
            )
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
            source=resolved_source,  # type: ignore[arg-type]
            confidence=resolved_confidence,
            validated=False,
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
                "validation=pending",
            ],
        )

    @staticmethod
    def _derive_generated_fact_confidence(value: Any) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 0.3
        if parsed < 0:
            return 0.0
        if parsed > 0.6:
            return 0.6
        return parsed

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

    def _create_work_items(
        self,
        decision_points: list[Any],
        slice_id: str,
        run_id: str,
        decision_routing: dict[str, dict[str, Any]],
    ) -> None:
        """Create ARCH_DECISION work items for each decision point."""
        # IMPL(single-layer): Work item writes should use create/upsert semantics
        # so repeated decision routing merges evidence/contract refs deterministically.
        if self._work_item_store is None:
            return

        from spec_manager.orchestration.coordination.work_items import WorkItem

        for dp in decision_points:
            decision_id = str(getattr(dp, "decision_id", "")).strip()
            if not decision_id:
                continue
            routing = decision_routing.get(decision_id, {})
            payload = self._build_arch_decision_work_item_payload(
                decision_point=dp,
                slice_id=slice_id,
                run_id=run_id,
                routing=routing,
                status="OPEN",
            )
            # IMPL(single-layer): Include routing metadata (`shape_id`,
            # `created_in_phase='architecture'`, `required_change_type`,
            # `evidence_refs`, `contract_ids`) in this payload path.
            try:
                work_item = WorkItem.from_dict(payload)
                existing = self._work_item_store.get(work_item.work_item_id)
                if existing is None:
                    self._work_item_store.create(work_item)
                else:
                    upsert_payload = work_item.to_dict()
                    upsert_payload["status"] = self._transitionable_arch_status(
                        current_status=str(getattr(existing, "status", "")).strip().upper(),
                        desired_status="OPEN",
                    )
                    self._work_item_store.upsert(
                        WorkItem.from_dict(upsert_payload),
                        merge_policy="append_evidence",
                    )
            except Exception:
                logger.warning(
                    "Failed to create ARCH_DECISION work item %s",
                    decision_id,
                    exc_info=True,
                )

    def _build_arch_decision_work_item_payload(
        self,
        *,
        decision_point: Any,
        slice_id: str,
        run_id: str,
        routing: dict[str, Any],
        status: str,
    ) -> dict[str, Any]:
        decision_id = str(getattr(decision_point, "decision_id", "")).strip()
        title = str(getattr(decision_point, "description", "")).strip() or (
            f"Architecture decision {decision_id or 'unknown'}"
        )
        owner_slice_id = str(routing.get("owner_slice_id", "")).strip() or str(slice_id).strip()
        shape_id = str(routing.get("shape_id", "")).strip() or owner_slice_id or "unmapped-shape"
        contract_ids = self._dedupe_text_values(routing.get("contract_ids", []))
        trigger_refs = self._dedupe_text_values(getattr(decision_point, "trigger_evidence", []))
        evidence_refs = self._dedupe_text_values([*trigger_refs, *routing.get("evidence_refs", [])])
        return {
            "work_item_id": decision_id,
            "run_id": run_id,
            "slice_id": owner_slice_id,
            "title": title,
            "description": title,
            "shape_id": shape_id,
            "created_in_phase": _ARCHITECTURE_PHASE,
            "required_change_type": "spec_change",
            "status": status,
            "kind": "ARCH_DECISION",
            "priority": "high",
            "file_locations": self._extract_file_locations(trigger_refs),
            "evidence_refs": evidence_refs,
            "contract_ids": contract_ids,
            "verifier_ids": self._dedupe_text_values(routing.get("verifier_ids", [])),
            "metadata": {
                "decision_type": str(getattr(decision_point, "decision_type", "")).strip(),
                "scope": str(getattr(decision_point, "scope", "")).strip(),
                "mapping_status": str(routing.get("mapping_status", "")).strip() or "missing",
                "mapping_reason": str(routing.get("mapping_reason", "")).strip(),
                "lookup_refs": self._dedupe_text_values(routing.get("lookup_refs", [])),
            },
        }

    @staticmethod
    def _extract_file_locations(evidence_refs: list[str]) -> list[dict[str, Any]]:
        locations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in evidence_refs:
            ref = str(value).strip()
            if not ref:
                continue
            file_path = ref
            line_start: int | None = None
            if ":" in ref:
                prefix, suffix = ref.rsplit(":", 1)
                if suffix.isdigit():
                    file_path = prefix.strip()
                    line_start = int(suffix)
            if not file_path or ("/" not in file_path and "\\" not in file_path):
                continue
            key = f"{file_path}:{line_start or ''}"
            if key in seen:
                continue
            seen.add(key)
            locations.append(
                {
                    "file_path": file_path,
                    "line_start": line_start,
                    "line_end": line_start,
                    "symbol": None,
                }
            )
        return locations

    @staticmethod
    def _transitionable_arch_status(current_status: str, desired_status: str) -> str:
        current = str(current_status).strip().upper()
        desired = str(desired_status).strip().upper()
        if not desired:
            return "OPEN"
        if current == "DECIDED":
            return "DECIDED"
        if not current:
            return desired
        if current != desired:
            return desired
        if desired == "OPEN":
            return "EXPLORING"
        if desired == "EXPLORING":
            return "OPEN"
        return desired

    def _update_coordination(
        self,
        dp: Any,
        outcome: DecisionOutcome,
        slice_id: str,
        *,
        run_id: str,
        routing: dict[str, Any],
    ) -> None:
        """Update work item status and add WaitGraph edges for blocked decisions."""
        # IMPL(single-layer): Keep wait-graph integration, but blocked architecture
        # decisions caused by missing shape routing must emit deterministic diagnostics
        # and remain blocked (no cross-phase reroute).
        # Update work item status
        if self._work_item_store is not None:
            try:
                desired_status = "EXPLORING"
                if outcome.committed:
                    desired_status = "DECIDED"
                elif outcome.under_spec_events or outcome.decision_requirements:
                    desired_status = "BLOCKED"
                self._upsert_arch_decision_status(
                    decision_point=dp,
                    slice_id=slice_id,
                    run_id=run_id,
                    routing=routing,
                    status=desired_status,
                )
            except (KeyError, ValueError):
                logger.debug(
                    "Could not update work item status for %s",
                    dp.decision_id,
                    exc_info=True,
                )

        # Add WaitGraph edges for blocked decisions
        if self._wait_graph is not None and not outcome.committed and outcome.decision_requirements:
            from spec_manager.orchestration.coordination.wait_graph import (
                CyclicDependencyError,
                WaitEdge,
            )

            existing_edges = {
                (edge.waiting_slice, edge.provider_slice)
                for edge in self._wait_graph.get_waiting_on(slice_id)
            }

            for requirement in outcome.decision_requirements:
                constraint_id = self._normalize_constraint_dependency_id(requirement)
                if not constraint_id:
                    continue
                provider_slice = self._resolve_constraint_owner_slice(requirement, constraint_id)
                if not provider_slice:
                    logger.debug(
                        "Skipped wait edge for %s; unresolved owner for requirement %s",
                        slice_id,
                        constraint_id,
                    )
                    continue
                if (slice_id, provider_slice) in existing_edges:
                    continue
                try:
                    self._wait_graph.add_edge(
                        WaitEdge(
                            waiting_slice=slice_id,
                            provider_slice=provider_slice,
                            artifact_key=f"arch_decision:{dp.decision_id}",
                            signal_id=(
                                f"constraint_wait:{slice_id}:{provider_slice}:"
                                f"{constraint_id}:{dp.decision_id}"
                            ),
                        )
                    )
                    existing_edges.add((slice_id, provider_slice))
                except CyclicDependencyError as exc:
                    self._handle_wait_cycle(
                        run_id=run_id,
                        waiting_slice=slice_id,
                        provider_slice=provider_slice,
                        constraint_id=constraint_id,
                        decision_id=str(getattr(dp, "decision_id", "")).strip(),
                        cycle=exc.cycle,
                    )
                except Exception:
                    logger.debug(
                        "Could not add wait edge %s -> %s",
                        slice_id,
                        provider_slice,
                        exc_info=True,
                    )

    def _upsert_arch_decision_status(
        self,
        *,
        decision_point: Any,
        slice_id: str,
        run_id: str,
        routing: dict[str, Any],
        status: str,
    ) -> None:
        if self._work_item_store is None:
            return

        from spec_manager.orchestration.coordination.work_items import WorkItem

        payload = self._build_arch_decision_work_item_payload(
            decision_point=decision_point,
            slice_id=slice_id,
            run_id=run_id,
            routing=routing,
            status=status,
        )
        incoming = WorkItem.from_dict(payload)
        existing = self._work_item_store.get(incoming.work_item_id)
        if existing is None:
            self._work_item_store.create(incoming)
            return
        upsert_payload = incoming.to_dict()
        upsert_payload["status"] = self._transitionable_arch_status(
            current_status=str(getattr(existing, "status", "")).strip().upper(),
            desired_status=status,
        )
        self._work_item_store.upsert(
            WorkItem.from_dict(upsert_payload),
            merge_policy="append_evidence",
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

    def _resolve_constraint_owner_slice(self, requirement: Any, constraint_id: str) -> str:
        if isinstance(requirement, dict):
            for key in ("owner_slice_id", "provider_slice", "slice_id", "owner_slice"):
                candidate = str(requirement.get(key, "")).strip()
                if candidate:
                    return candidate

        if self._work_item_store is not None:
            try:
                item = self._work_item_store.get(constraint_id)
            except Exception:
                item = None
            owner_slice_id = str(getattr(item, "slice_id", "")).strip() if item else ""
            if owner_slice_id:
                return owner_slice_id

        return constraint_id

    def _handle_wait_cycle(
        self,
        *,
        run_id: str,
        waiting_slice: str,
        provider_slice: str,
        constraint_id: str,
        decision_id: str,
        cycle: list[str],
    ) -> None:
        cycle_path = [str(node).strip() for node in cycle if str(node).strip()]
        if not cycle_path:
            cycle_path = [waiting_slice, provider_slice, waiting_slice]

        stub_owner_slice = self._choose_cycle_stub_owner(
            cycle_path=cycle_path,
            fallback_slice=provider_slice,
        )
        logger.warning(
            "Wait-graph cycle detected while adding %s -> %s for %s: %s",
            waiting_slice,
            provider_slice,
            constraint_id,
            " -> ".join(cycle_path),
        )

        if self._work_item_store is None:
            logger.warning(
                "Cannot create cycle-breaking work item for %s: work_item_store unavailable",
                constraint_id,
            )
            return

        from spec_manager.orchestration.coordination.work_items import WorkItem

        work_item_id = self._cycle_break_work_item_id(
            waiting_slice=waiting_slice,
            provider_slice=provider_slice,
            constraint_id=constraint_id,
            cycle_path=cycle_path,
        )
        if self._work_item_store.get(work_item_id) is not None:
            return

        title = (
            f"Define interface stub for '{constraint_id}' to break wait-cycle "
            + " -> ".join(cycle_path)
        )
        stub_payload = {
            "work_item_id": work_item_id,
            "run_id": run_id,
            "slice_id": stub_owner_slice,
            "title": title,
            "description": title,
            "shape_id": stub_owner_slice or provider_slice or waiting_slice or "cycle-break",
            "created_in_phase": _ARCHITECTURE_PHASE,
            "required_change_type": "spec_change",
            "status": "NEW",
            "kind": "SPEC_WORK",
            "priority": "high",
            "evidence_refs": self._dedupe_text_values(
                [f"arch_decision:{decision_id}", f"constraint:{constraint_id}"]
            ),
            "contract_ids": [constraint_id],
            "metadata": {
                "source": "wait_graph_cycle",
                "decision_id": decision_id,
                "waiting_slice": waiting_slice,
                "provider_slice": provider_slice,
                "cycle_path": cycle_path,
                "monitor_required_status": "MERGED",
                "monitor_kind": "work_item_status",
                "tags": ["cycle_breaking", "interface_stub"],
            },
        }
        try:
            self._work_item_store.create(WorkItem.from_dict(stub_payload))
        except Exception:
            logger.warning(
                "Failed to create cycle-breaking work item %s",
                work_item_id,
                exc_info=True,
            )

    @staticmethod
    def _choose_cycle_stub_owner(*, cycle_path: list[str], fallback_slice: str) -> str:
        if len(cycle_path) >= 2 and cycle_path[1]:
            return cycle_path[1]
        return fallback_slice

    @staticmethod
    def _cycle_break_work_item_id(
        *,
        waiting_slice: str,
        provider_slice: str,
        constraint_id: str,
        cycle_path: list[str],
    ) -> str:
        seed = "|".join(
            [
                waiting_slice,
                provider_slice,
                constraint_id,
                "->".join(cycle_path),
            ]
        )
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
        return f"cycle-break:{digest}"
