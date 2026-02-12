"""Architecture planning strategy.

Gated by L2 + impact >= MEDIUM. Detects decision points, proposes candidates,
evaluates them, persists artifacts, creates ARCH_DECISION work items, and
manages WaitGraph edges for blocked decisions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from spec_manager.planner.architecture.artifacts import persist_decision_artifacts
from spec_manager.planner.architecture.decision_detector import DecisionPointDetector
from spec_manager.planner.architecture.evaluator import CandidateEvaluator
from spec_manager.planner.architecture.proposer import ProposerOrchestrator
from spec_manager.planner.architecture.types import DecisionOutcome, ScopePacket

from .protocol import PlanningSession

logger = logging.getLogger(__name__)


class ArchitecturePlannerStrategy:
    """Architecture decision strategy. Only runs for L2 + impact >= MEDIUM.

    Orchestrates:
    1. Decision point detection via :class:`DecisionPointDetector`.
    2. ARCH_DECISION work item creation for coordination tracking.
    3. ScopePacket population from routed source artifacts.
    4. Candidate proposal via :class:`ProposerOrchestrator` (K=3 for HIGH, K=1 for MEDIUM).
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
    ) -> None:
        self._workspace_root = workspace_root
        self._run_agent = run_agent
        self._work_item_store = work_item_store
        self._wait_graph = wait_graph

    def run(self, session: PlanningSession) -> PlanningSession:
        if not self._should_run(session):
            return session

        slice_id = session.ctx.get("slice_id", "unknown")
        run_id = session.ctx.get("run_id", "default")

        # Gather authoritative constraints
        auth_constraints = []
        if session.constraint_context:
            auth_constraints = session.constraint_context.authoritative

        # 1. Detect decision points
        detector = DecisionPointDetector(
            workspace_root=self._workspace_root,
            run_agent=self._run_agent,
        )
        decision_points = detector.detect(
            slice_id=slice_id,
            gaps=session.gaps,
            discovery=session.discovery,
            authoritative_constraints=auth_constraints,
        )

        if not decision_points:
            return session

        # 2. Create ARCH_DECISION work items for coordination tracking
        self._create_work_items(decision_points, slice_id)

        # Determine K based on impact; use session tradeoff axes if available
        k = 3 if session.impact and session.impact.impact == "HIGH" else 1

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
        scope = dp.scope or ""
        if scope.startswith("intra:"):
            lib_name = scope.split(":", 1)[1] if ":" in scope else slice_id
            source_artifacts = self._load_intra_artifacts(lib_name)
        elif scope.startswith("inter:"):
            source_artifacts = self._load_inter_artifacts(scope)

        # Current arch state refs from discovery
        arch_refs = list(session.discovery.get("arch_files", []))

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

    def _load_intra_artifacts(self, lib_name: str) -> dict[str, Any]:
        """Load charter, constraints, and details for a single library."""
        artifacts: dict[str, Any] = {}
        lib_dir = self._workspace_root / "libraries" / lib_name

        if not lib_dir.exists():
            return artifacts

        for name, key in [
            ("charter.md", "charter_text"),
            ("constraints.md", "constraint_spans"),
            ("details.md", "details_text"),
        ]:
            path = lib_dir / name
            if path.exists():
                try:
                    artifacts[key] = path.read_text(encoding="utf-8")
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
                    artifacts.setdefault("arch_files", {})[arch_name] = path.read_text(
                        encoding="utf-8"
                    )
                except OSError:
                    # C03: Surface errors — missing artifact needs diagnosis
                    logger.warning(
                        "Failed to read %s for architecture strategy", path, exc_info=True
                    )

        return artifacts

    def _load_inter_artifacts(self, scope: str) -> dict[str, Any]:
        """Load artifacts for both sides of an inter-library interaction."""
        artifacts: dict[str, Any] = {}

        # Parse inter:<A>-><B>:<handle> or inter:<A>-><B>
        parts = scope.replace("inter:", "", 1)
        libs = []
        if "->" in parts:
            left, right = parts.split("->", 1)
            libs.append(left.strip())
            # right may have :<handle>
            right_lib = right.split(":")[0].strip() if ":" in right else right.strip()
            libs.append(right_lib)

        for lib_name in libs:
            lib_artifacts = self._load_intra_artifacts(lib_name)
            if lib_artifacts:
                artifacts[lib_name] = lib_artifacts

        return artifacts

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

            for req_id in outcome.decision_requirements:
                try:
                    self._wait_graph.add_edge(
                        WaitEdge(
                            waiting_slice=slice_id,
                            provider_slice=req_id,
                            artifact_key=f"arch_decision:{dp.decision_id}",
                            signal_id=dp.decision_id,
                        )
                    )
                except Exception:
                    # CyclicDependencyError or other — log and continue
                    logger.debug(
                        "Could not add wait edge %s -> %s",
                        slice_id,
                        req_id,
                        exc_info=True,
                    )
