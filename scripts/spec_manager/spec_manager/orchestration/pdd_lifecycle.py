"""PDD lifecycle orchestrator: L1 → L2 → L3 layer pipeline.

Orchestrates the multi-layer promotion model from WORKFLOW_ANALYSIS.md.
Each layer runs:

1. **Entry refinement** (typed per layer: library / architectural / code quality)
2. **Per-slice PromotionLoop** until dirty == clean
3. **Exit refinement** (same type as entry)

Between layers, a **transition refinement** (next layer's type) runs as a gate.
Findings may demote work back for rework before the next layer begins.

Refinement types:

- **L1 (Code-as-Spec)**: Library refinement — concern isolation, overlap, coverage
- **L2 (Architecture)**: Architectural refinement — service decomposition, event topology
- **L3 (Clean Code)**: Code quality refinement — correctness, clarity, consistency

The refinement cascade::

    Phase 0 → Library refinement (L1 entry)
    → L1 per-slice work → Library refinement (L1 exit)
    → Architectural refinement (L1→L2 transition, may demote)
    → Propagate L1 clean → L2 dirty
    → Architectural refinement (L2 entry)
    → L2 per-slice work → Architectural refinement (L2 exit)
    → Code quality refinement (L2→L3 transition, may demote)
    → Propagate L2 clean → L3 dirty
    → Code quality refinement (L3 entry)
    → L3 per-slice work → Code quality refinement (L3 exit)
    → QA eval → main

Usage::

    manager = WorkspaceManager(run_id="my-run", input_folder=Path("specs"))
    manager.initialize()
    lifecycle = PddLifecycle(manager, mode="interactive")
    result = lifecycle.run()

Worktree support::

    from spec_manager.vcs.operations import GitVcs
    from spec_manager.vcs.worktree import WorktreeManager

    vcs = GitVcs(repo_root=Path("."))
    wm = WorktreeManager(vcs=vcs, workspace_root=Path("."), run_id="my-run")
    lifecycle = PddLifecycle(manager, worktree_manager=wm)
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.orchestration.models import Layer
from spec_manager.orchestration.pdd_orchestrator import PddOrchestrator
from spec_manager.refinement.workspace.manager import WorkspaceManager

if TYPE_CHECKING:
    from spec_manager.vcs.worktree import WorktreeManager

logger = logging.getLogger(__name__)


def _hash_text(content: str) -> str:
    """Return stable SHA256 digest for content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# Maps each layer to its typed refinement method name.
_LAYER_REFINEMENT: dict[Layer, str] = {
    "l1": "_library_refinement",
    "l2": "_architectural_refinement",
    "l3": "_code_quality_refinement",
}


class PddLifecycle:
    """Orchestrates the L1→L2→L3 layer pipeline.

    This is the ONLY top-level lifecycle controller.
    :class:`PddOrchestrator` handles individual PDD phase execution.
    This class orchestrates the layer transitions, typed refinement,
    and the per-slice PromotionLoop at each layer.

    Args:
        manager: Initialized workspace manager.
        mode: Resolution mode — ``"auto"`` (multi-model research),
            ``"interactive"`` (user prompts), or ``"steering"``
            (pre-defined script for evals).
        use_research: Enable web research for ambiguity resolution.
        use_evidence_store: Enable evidence store search.
        steering_path: Path to steering script JSON (for eval mode).
        max_refinement_iterations: Max ambiguity resolution iterations
            per library.
        worktree_manager: Optional worktree manager for parallel
            per-library implementation.
        max_approval_iterations: Max L1→review→patch loops before
            auto-approving (prevents infinite loops).
        max_demotions_per_layer: Per-layer demotion budget (budget #3).
            If total demotions across all slices in a layer exceed this,
            a warning is logged and escalation metadata is emitted.
        max_pipeline_passes: Overall pipeline pass cap (budget #4).
            Maximum number of times the L1→L2→L3 pipeline can run.
        model_profile: Optional model profile used for role-based model routing.
        planner_override_provider: Optional planner provider override for tests/evals.
    """

    def __init__(
        self,
        manager: WorkspaceManager,
        mode: str = "interactive",
        *,
        use_research: bool = False,
        use_evidence_store: bool = False,
        steering_path: Path | None = None,
        max_refinement_iterations: int = 5,
        worktree_manager: WorktreeManager | None = None,
        max_approval_iterations: int = 3,
        max_demotions_per_layer: int = 50,
        max_pipeline_passes: int = 2,
        model_profile: Any = None,
        planner_override_provider: Any = None,
    ) -> None:
        self.manager = manager
        self.orchestrator = PddOrchestrator(manager)
        self.mode = mode
        self.use_research = use_research
        self.use_evidence_store = use_evidence_store
        self.steering_path = steering_path
        self.max_refinement_iterations = max_refinement_iterations
        self.worktree_manager: WorktreeManager | None = worktree_manager
        self.max_approval_iterations = max_approval_iterations
        self.max_demotions_per_layer = max_demotions_per_layer
        self.max_pipeline_passes = max_pipeline_passes
        self._model_profile = model_profile
        self._planner_override_provider = planner_override_provider
        self._compute_quality = False
        self._cost_ledger: Any | None = None

    # ------------------------------------------------------------------
    # Planner construction
    # ------------------------------------------------------------------

    def _build_planner(self) -> Any:
        """Build a Planner instance with tools wired from lifecycle config."""
        from spec_manager.orchestration.source_analysis_cache import SourceAnalysisCache
        from spec_manager.planner.api import Planner
        from spec_manager.planner.tools.constraints_tool import ConstraintsTool
        from spec_manager.planner.tools.evidence_tool import EvidenceTool
        from spec_manager.planner.tools.integration_tool import IntegrationTool
        from spec_manager.planner.tools.research_tool import ResearchTool

        # Build evidence searcher if evidence store is enabled
        evidence_searcher = None
        evidence_index = None
        if self.use_evidence_store:
            try:
                from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex
                from spec_manager.refinement.hollowed_spec.searcher import (
                    EvidenceSearcher,
                )

                index_path = (
                    self.manager.workspace_path
                    / "workspace"
                    / "indexes"
                    / "evidence_store_index.json"
                )
                if index_path.exists():
                    evidence_index = EvidenceIndex.load(index_path)
                    evidence_searcher = EvidenceSearcher(evidence_index)
            except Exception as exc:
                logger.debug("Could not load evidence searcher: %s", exc)

        # Build steering script if path provided
        steering_script = None
        if self.steering_path:
            try:
                from spec_manager.refinement.interactive.steering.steering_script import (
                    SteeringScript,
                )

                steering_script = SteeringScript.from_file(self.steering_path)
            except Exception as exc:
                logger.debug("Could not load steering script: %s", exc)

        # Build research coordinator for web research
        research_coordinator = None
        if self.use_research:
            try:
                from spec_manager.refinement.interactive.research.coordinator import (
                    ResearchCoordinator,
                )

                research_coordinator = ResearchCoordinator(evidence_index=evidence_index)
            except Exception as exc:
                logger.debug("Could not build research coordinator: %s", exc)

        research_tool = ResearchTool(
            evidence_searcher=evidence_searcher,
            steering_script=steering_script,
            research_coordinator=research_coordinator,
            workspace=self.manager.workspace_path,
        )
        evidence_tool = EvidenceTool(evidence_searcher=evidence_searcher)

        # Build source analysis cache and integration/constraints tools
        source_cache = SourceAnalysisCache(
            workspace_root=self.manager.workspace_path,
            run_id=self.manager.run_id,
        )
        integration_tool = IntegrationTool(
            source_cache=source_cache,
            workspace=self.manager.workspace_path,
        )
        constraints_tool = ConstraintsTool(workspace_root=self.manager.workspace_path)

        return Planner(
            workspace_root=self.manager.workspace_path,
            mode=self.mode,
            research_tool=research_tool,
            evidence_tool=evidence_tool,
            integration_tool=integration_tool,
            constraints_tool=constraints_tool,
            override_provider=self._planner_override_provider,
            model_id=self._resolve_model_id_for_role("planner"),
        )

    def _resolve_model_id_for_role(self, role: str) -> str:
        """Resolve a model ID for a logical role using the active model profile."""
        if self._model_profile is None:
            return ""
        if isinstance(self._model_profile, dict):
            role_models = self._model_profile.get("role_models")
            if isinstance(role_models, dict):
                role_model_id = role_models.get(role)
                if role_model_id:
                    return str(role_model_id)
            return str(self._model_profile.get("producer_model_id", "") or "")
        try:
            model_id = self._model_profile.get_model_for_role(role)
        except Exception:
            logger.debug("Could not resolve model_id for role '%s'", role)
            return ""
        return str(model_id or "")

    def _build_run_context_config(self) -> dict[str, Any]:
        """Build run context config payload with model profile and resolved ids."""
        config: dict[str, Any] = {}
        if self._model_profile is None:
            return config

        if hasattr(self._model_profile, "to_dict"):
            config["model_profile"] = self._model_profile.to_dict()
        elif isinstance(self._model_profile, dict):
            config["model_profile"] = dict(self._model_profile)
        else:
            config["model_profile"] = {"name": str(self._model_profile)}

        model_ids = {
            role: model_id
            for role in ("planner", "refinement", "review", "judge")
            if (model_id := self._resolve_model_id_for_role(role))
        }
        if model_ids:
            config["model_ids"] = model_ids
        return config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Run the full layer pipeline: intake → L1 → L2 → L3 → QA.

        Returns:
            Summary dict with results from each layer and transition.
        """
        from spec_manager.orchestration.run_state import RunConfig, RunStateManager

        results: dict[str, Any] = {}

        # Initialize run state tracking
        state_mgr = RunStateManager(
            workspace_root=self.manager.workspace_path,
            run_id=self.manager.run_id,
        )
        self._state_mgr = state_mgr
        state_mgr.ensure_directories()
        state_mgr.write_config(
            RunConfig(
                run_id=self.manager.run_id,
                mode=self.mode,
                input_folder=str(self.manager.structure.input_folder)
                if hasattr(self.manager.structure, "input_folder")
                else "",
                max_approval_iterations=self.max_approval_iterations,
                enable_snapshots=True,
                enable_quality_scoring=self._compute_quality,
            )
        )
        state_mgr.update_state(phase="intake", active_layer="")

        # Phase 0: Intake (raw prose → code-as-spec, if needed)
        results["intake"] = self._run_intake()

        # Bootstrap constraints from intake artifacts
        try:
            from spec_manager.planner.constraints.bootstrap import bootstrap_constraints_from_intake

            libraries_dir = self.manager.structure.libraries_dir
            system_dir = self.manager.structure.root / "system"
            results["constraints_bootstrapped"] = bootstrap_constraints_from_intake(
                workspace_root=self.manager.workspace_path,
                libraries_dir=libraries_dir,
                system_dir=system_dir if system_dir.exists() else None,
            )
        except Exception as exc:
            logger.warning("Constraint bootstrap failed: %s", exc)
            results["constraints_bootstrapped"] = {"error": str(exc)}

        state_mgr.update_state(phase="intake_done")

        # Overall pipeline pass cap (budget #4)
        results["pipeline_pass"] = 1
        results["max_pipeline_passes"] = self.max_pipeline_passes

        self._record_git_ref(f"pdd/{self.manager.run_id}/base")

        # Setup layer worktrees if managed
        if self.worktree_manager:
            results["setup"] = self.worktree_manager.setup_layers()

        # L1: Code-as-Spec (with human approval loop)
        state_mgr.update_state(phase="l1", active_layer="l1")
        l1_result, approval = self._run_l1_with_approval()
        results["l1"] = l1_result
        results["approval"] = approval
        self._record_git_ref(f"pdd/{self.manager.run_id}/l1-approved")
        state_mgr.update_state(
            layers_completed=["l1"],
            phase="l1_l2_transition",
            active_layer="l1",
        )

        # C02: Validate L1 completion before L2 starts
        l1_slices_data = l1_result.get("slices", {})
        l1_slices = (
            l1_slices_data.get("slices", []) if isinstance(l1_slices_data, dict) else l1_slices_data
        )
        incomplete = [s for s in l1_slices if s.get("status") not in ("COMPLETE", "PROMOTED")]
        if incomplete:
            incomplete_ids = [s.get("slice_id", "?") for s in incomplete]
            logger.warning(
                "L1 has %d incomplete slices: %s — L2 input may be partial",
                len(incomplete),
                incomplete_ids,
            )
            results["l1_incomplete_slices"] = incomplete_ids
            if not l1_result.get("all_complete", False):
                logger.error(
                    "L1 NOT all_complete — blocking L2 transition. "
                    "Incomplete slices must be resolved before L2 can start."
                )
                results["l2_blocked"] = True
                results["l2_blocked_reason"] = "L1 slices incomplete"
                return results

        # L1→L2 transition: architectural refinement (may demote to L1)
        results["l1_l2_transition"] = self._run_transition("l1", "l2")
        state_mgr.update_state(
            transitions_completed=["l1_l2"],
            phase="l2",
            active_layer="l2",
        )

        # L2: Architecture
        results["l2"] = self._run_layer("l2")
        self._record_git_ref(f"pdd/{self.manager.run_id}/l2/clean")

        # Optional L2 checkpoint: approve architecture topology before L3
        if self.mode == "interactive":
            results["l2_checkpoint"] = self._request_l2_checkpoint(results["l2"])
        state_mgr.update_state(
            layers_completed=["l1", "l2"],
            phase="l2_l3_transition",
            active_layer="l2",
        )

        # L2→L3 transition: code quality refinement (may demote to L2)
        results["l2_l3_transition"] = self._run_transition("l2", "l3")
        state_mgr.update_state(
            transitions_completed=["l1_l2", "l2_l3"],
            phase="l3",
            active_layer="l3",
        )

        # L3: Clean Code
        results["l3"] = self._run_layer("l3")
        self._record_git_ref(f"pdd/{self.manager.run_id}/l3/clean")
        state_mgr.update_state(
            layers_completed=["l1", "l2", "l3"],
            phase="qa",
            active_layer="",
        )

        # Final QA eval
        results["qa"] = self.qa()

        # Scoring
        from spec_manager.evaluation.scoring import RunReporter

        reporter = RunReporter(
            workspace_root=self.manager.workspace_path,
            run_id=self.manager.run_id,
        )
        scorecard = reporter.compute(results)
        reporter.write(scorecard)
        results["scorecard"] = scorecard.to_dict()

        # Read config flags for optional steps
        _run_config = state_mgr.read_config()
        _enable_quality = (
            _run_config.enable_quality_scoring if _run_config else self._compute_quality
        )
        _enable_snapshots = _run_config.enable_snapshots if _run_config else True

        # Quality scoring (optional)
        if _enable_quality:
            try:
                from spec_manager.evaluation.digests import (
                    build_architecture_digest,
                    build_code_digest,
                )
                from spec_manager.evaluation.quality import QualityReporter

                arch_digest = build_architecture_digest(
                    self.manager.structure.root, self.manager.run_id
                )
                code_digest = build_code_digest(self.manager.structure.root, self.manager.run_id)

                run_reports = self.manager.workspace_path / "reports" / "pdd" / self.manager.run_id
                run_reports.mkdir(parents=True, exist_ok=True)
                (run_reports / "architecture_digest.json").write_text(
                    json.dumps(arch_digest, indent=2), encoding="utf-8"
                )
                (run_reports / "code_digest.json").write_text(
                    json.dumps(code_digest, indent=2), encoding="utf-8"
                )

                quality_reporter = QualityReporter(self.manager.structure.root, self.manager.run_id)
                quality_scorecard = quality_reporter.compute(
                    arch_digest,
                    code_digest,
                    pipeline_scorecard=scorecard,
                )
                quality_reporter.write(quality_scorecard)
                results["quality_scorecard"] = quality_scorecard.to_dict()
            except Exception as exc:
                logger.warning("Quality scoring failed: %s", exc, exc_info=True)
                results["quality_scorecard"] = {"error": str(exc)}

        # Snapshot
        if _enable_snapshots:
            try:
                from spec_manager.evaluation.snapshot import snapshot_run

                snapshot_run(self.manager.structure.root, self.manager.run_id)
            except Exception as exc:
                logger.warning("Snapshot failed: %s", exc)

        # Final report
        from spec_manager.evaluation.report import FinalReportGenerator

        report_gen = FinalReportGenerator(
            workspace_root=self.manager.workspace_path,
            run_id=self.manager.run_id,
        )
        report_path, scorecard_json_path = report_gen.generate(results, scorecard)
        results["final_report_path"] = str(report_path)
        results["scorecard_json_path"] = str(scorecard_json_path)

        # Final whole-run governance gate
        final_governance = self._run_governance_check(
            "final",
            check_artifacts=True,
            check_report=True,
        )
        results["final_governance"] = final_governance
        if not final_governance.get("passed", True):
            logger.warning(
                "Final governance gate failed: %s",
                final_governance.get("error", ""),
            )

        # Release signoff (auto-approve in auto mode)
        results["release_signoff"] = self._request_release_signoff(results)
        self._record_git_ref(f"pdd/{self.manager.run_id}/release")

        state_mgr.update_state(phase="done")

        # Cleanup worktrees
        if self.worktree_manager:
            results["cleanup"] = self.worktree_manager.cleanup()

        return results

    def qa(self) -> dict[str, Any]:
        """Run QA eval framework.

        Returns:
            QA evaluation results.
        """
        logger.info("=== PDD Lifecycle: QA ===")

        from spec_manager.refinement.evals.runner import EvalConfig, EvalRunner

        config = EvalConfig(use_judge=True)
        runner = EvalRunner(config)

        try:
            report = runner.run()
            return {
                "pass_rate": report.pass_rate,
                "total_phases": report.total_phases,
                "phases_passed": report.phases_passed,
                "results": [
                    {
                        "phase": r.phase,
                        "passed": r.passed,
                        "recall": r.detail_metrics.recall if r.detail_metrics else None,
                        "precision": r.detail_metrics.precision if r.detail_metrics else None,
                    }
                    for r in report.results
                ],
            }
        except Exception as exc:
            logger.warning("QA eval failed: %s", exc)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Layer orchestration
    # ------------------------------------------------------------------

    def _run_layer(self, layer: Layer) -> dict[str, Any]:
        """Run a single layer: entry refinement → per-slice work → exit refinement.

        Args:
            layer: Which layer to run.

        Returns:
            Dict with entry_refinement, slices, and exit_refinement results.
        """
        logger.info("=== Layer %s: START ===", layer.upper())
        results: dict[str, Any] = {"layer": layer}

        refinement_method = getattr(self, _LAYER_REFINEMENT[layer])

        # Entry refinement (typed per layer)
        results["entry_refinement"] = refinement_method()

        # Per-slice work via PromotionLoop
        results["slices"] = self._run_slices_at_layer(layer)

        # Exit refinement (typed per layer)
        results["exit_refinement"] = refinement_method()

        logger.info("=== Layer %s: DONE ===", layer.upper())
        return results

    def _run_transition(
        self, from_layer: Layer, to_layer: Layer, *, max_rounds: int = 3
    ) -> dict[str, Any]:
        """Run transition between layers with demotion round cap.

        The next layer's typed refinement runs as a transition gate.
        If it emits demotion tickets, the previous layer's slices are
        re-run to address the demoted issues.  This loop repeats up to
        ``max_rounds`` times.  After rework, clean is propagated to the
        next layer's dirty.

        Args:
            from_layer: Layer that just completed.
            to_layer: Layer about to start.
            max_rounds: Maximum demotion rework rounds before declaring stuck.

        Returns:
            Transition results including refinement and optional rework.
        """
        logger.info("=== Transition %s → %s ===", from_layer.upper(), to_layer.upper())
        results: dict[str, Any] = {"from": from_layer, "to": to_layer}

        refinement_method = getattr(self, _LAYER_REFINEMENT[to_layer])

        rework_rounds: list[dict[str, Any]] = []
        transition_stuck = False

        for round_num in range(1, max_rounds + 1):
            refinement_result = refinement_method()
            demotions = refinement_result.get("demotion_tickets", 0)

            round_result: dict[str, Any] = {
                "round": round_num,
                "refinement": refinement_result,
                "demotions": demotions,
            }

            if demotions <= 0:
                rework_rounds.append(round_result)
                break

            logger.info(
                "Transition %s→%s round %d/%d: %d demotions, re-running %s slices",
                from_layer,
                to_layer,
                round_num,
                max_rounds,
                demotions,
                from_layer,
            )
            round_result["rework"] = self._run_slices_at_layer(from_layer)
            rework_rounds.append(round_result)

            if round_num == max_rounds and demotions > 0:
                transition_stuck = True
                logger.warning(
                    "Transition %s→%s: stuck after %d rounds with %d demotions remaining",
                    from_layer,
                    to_layer,
                    max_rounds,
                    demotions,
                )

        results["refinement"] = rework_rounds[-1]["refinement"] if rework_rounds else {}
        results["rework_rounds"] = rework_rounds
        results["transition_stuck"] = transition_stuck
        if transition_stuck:
            results["error"] = f"Transition {from_layer}→{to_layer} stuck after {max_rounds} rounds"

        # Transition governance gate: no open governance FAIL + required artifacts present
        governance = self._run_governance_check(
            f"transition_{from_layer}_{to_layer}",
            check_artifacts=True,
        )
        results["governance"] = governance
        if not governance.get("passed", True):
            logger.warning(
                "Transition %s→%s governance gate failed: %s",
                from_layer,
                to_layer,
                governance.get("error", ""),
            )

        # Propagate clean → next layer's dirty
        if self.worktree_manager:
            prop = self.worktree_manager.propagate_clean_to_next_layer(from_layer)
            results["propagation"] = {
                "success": prop.success,
                "from_layer": prop.from_layer,
                "to_layer": prop.to_layer,
                "error": prop.error,
            }

            # Downstream readiness CI: smoke test on the new dirty worktree
            if prop.success:
                readiness = self._run_readiness_ci(to_layer)
                results["readiness_ci"] = readiness
                if not readiness.get("passed", True):
                    results["readiness_blocked"] = True
                    logger.warning(
                        "Downstream readiness CI failed for %s dirty — transition %s→%s blocked",
                        to_layer,
                        from_layer,
                        to_layer,
                    )

        return results

    def _run_slices_at_layer(self, layer: Layer) -> dict[str, Any]:
        """Discover slices and run PromotionLoop at a given layer.

        Creates coordination infrastructure (WorkItemStore, WakeQueue,
        MonitorRegistry, MonitorExecutor, WaitGraph) per layer and passes
        them to the ReactivePromotionScheduler.

        Args:
            layer: Which layer to run slices at.

        Returns:
            Dict with per-slice results.
        """
        from spec_manager.orchestration.promotion_loop import (
            PromotionLoop,
            RunContext,
        )
        from spec_manager.orchestration.promotion_scheduler import (
            ReactivePromotionScheduler,
            SchedulerConfig,
        )

        # Discover slices for this layer
        slice_refs = self._discover_slices(layer)

        if not slice_refs:
            return {"layer": layer, "note": f"No slices found at {layer}"}

        # Create slice worktrees if managed
        if self.worktree_manager:
            for ref in slice_refs:
                try:
                    wt_path = self.worktree_manager.create_slice_worktree(layer, ref.slice_id)
                    ref.worktree_path = str(wt_path)
                except RuntimeError:
                    # Worktree may already exist from a previous iteration
                    existing = self.worktree_manager.get_slice_worktree(layer, ref.slice_id)
                    if existing:
                        ref.worktree_path = str(existing)

        # Run PromotionLoop via scheduler
        run_context = RunContext(
            run_id=self.manager.run_id,
            mode="auto" if self.mode != "interactive" else "interactive",
            workspace_root=str(self.manager.workspace_path),
            config=self._build_run_context_config(),
        )

        planner = self._build_planner()

        loop = PromotionLoop(
            worktree_manager=self.worktree_manager,
            workspace_root=self.manager.workspace_path,
            planner=planner,
        )

        # Build coordination infrastructure
        monitor_executor, wake_queue = self._build_coordination(layer, run_context)

        scheduler = ReactivePromotionScheduler(
            loop=loop,
            config=SchedulerConfig(max_parallel=4),
            monitor_executor=monitor_executor,
            wake_queue=wake_queue,
        )
        sched_result = scheduler.run(slice_refs, run_context)
        slice_results = sched_result.slice_results

        # Per-layer demotion budget check (budget #3)
        total_layer_demotions = sum(len(sr.demotion_tickets) for sr in slice_results)
        budget_exceeded = total_layer_demotions > self.max_demotions_per_layer
        if budget_exceeded:
            logger.warning(
                "Layer %s demotion budget exceeded: %d > %d — escalating",
                layer,
                total_layer_demotions,
                self.max_demotions_per_layer,
            )

        # CI backpressure: tick pipeline after each completed slice
        ci_ticks: list[dict[str, Any]] = []
        candidate_in_flight = False
        for sr in slice_results:
            if sr.status == "COMPLETE" and self.worktree_manager:
                if candidate_in_flight:
                    logger.info(
                        "Backpressure: waiting for candidate before processing slice '%s'",
                        sr.slice_id,
                    )
                tick = self.worktree_manager.tick_pipeline(active_layer=layer)
                ci_ticks.append(
                    {
                        "slice_id": sr.slice_id,
                        "main_updated": tick.main_updated,
                        "demotions": len(tick.demotion_tickets),
                    }
                )
                candidate_in_flight = bool(tick.demotion_tickets)

                # Write CI batch receipt
                if hasattr(self, "_state_mgr"):
                    batch_dir = self._state_mgr.run_dir / "ci" / layer / "batches"
                    batch_dir.mkdir(parents=True, exist_ok=True)
                    batch_id = f"batch_{sr.slice_id}_{len(ci_ticks)}"
                    receipt = {
                        "batch_id": batch_id,
                        "slice_id": sr.slice_id,
                        "layer": layer,
                        "main_updated": tick.main_updated,
                        "demotions": len(tick.demotion_tickets),
                    }
                    receipt_path = batch_dir / f"{batch_id}.json"
                    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

        return {
            "layer": layer,
            "slices": [
                {
                    "slice_id": r.slice_id,
                    "status": r.status,
                    "iterations": r.iterations,
                    "remaining_gaps": r.remaining_gaps,
                    "demotion_count": len(r.demotion_tickets),
                    "wake_count": r.wake_count,
                }
                for r in slice_results
            ],
            "ci_ticks": ci_ticks,
            "all_complete": sched_result.all_complete,
            "waiting_slices": sched_result.waiting_slices,
            "total_layer_demotions": total_layer_demotions,
            "budget_exceeded": budget_exceeded,
        }

    def _build_coordination(self, layer: Layer, run_context: Any) -> tuple[Any, Any]:
        """Build coordination infrastructure for a layer run.

        Creates WorkItemStore, WakeQueue, MonitorRegistry, ConditionChecker,
        and MonitorExecutor.  Returns (monitor_executor, wake_queue).

        Args:
            layer: Layer being run.
            run_context: Run-scoped context.

        Returns:
            Tuple of (MonitorExecutor, WakeQueue).
        """
        from spec_manager.orchestration.coordination.monitor_executor import (
            ConditionChecker,
            MonitorExecutor,
        )
        from spec_manager.orchestration.coordination.monitors import MonitorRegistry
        from spec_manager.orchestration.coordination.wake_queue import WakeQueue
        from spec_manager.orchestration.coordination.work_items import WorkItemStore

        workspace = self.manager.workspace_path
        run_id = run_context.run_id if hasattr(run_context, "run_id") else self.manager.run_id
        coordination_dir = workspace / ".pdd_runs" / run_id / "coordination"
        coordination_dir.mkdir(parents=True, exist_ok=True)

        work_item_store = WorkItemStore(coordination_dir)
        wake_queue = WakeQueue(coordination_dir)
        monitor_registry = MonitorRegistry(coordination_dir)

        checker = ConditionChecker(
            workspace_root=workspace,
            work_item_store=work_item_store,
        )

        monitor_executor = MonitorExecutor(
            registry=monitor_registry,
            checker=checker,
            wake_queue=wake_queue,
        )

        return monitor_executor, wake_queue

    def _discover_slices(self, layer: Layer) -> list[Any]:
        """Discover work slices for a given layer.

        - L1: slices = libraries (concern boundaries)
        - L2: slices = architectural components from component manifest,
              falling back to per-library wrappers if no manifest exists
        - L3: slices = code files (per file, with finding clusters internally)

        Args:
            layer: Layer to discover slices for.

        Returns:
            List of SliceRef objects.
        """
        from spec_manager.core.language import source_rglob
        from spec_manager.orchestration.promotion_loop import SliceRef

        slice_refs: list[SliceRef] = []

        if layer == "l1":
            libraries_dir = self.manager.structure.libraries_dir
            snapshot_dir = self.manager.structure.spec_snapshot_dir
            if libraries_dir.exists():
                for lib_dir in sorted(libraries_dir.iterdir()):
                    if lib_dir.is_dir():
                        # Use spec_snapshot if the library dir has no code
                        # files (e.g., only markdown analysis).  With a
                        # WorktreeManager the path is overridden later anyway.
                        wt = str(lib_dir)
                        if (
                            not any(lib_dir.rglob("*.*"))
                            or not any(
                                p.suffix not in {".md", ".json", ".yaml", ".yml"}
                                for p in lib_dir.rglob("*")
                                if p.is_file()
                            )
                        ) and snapshot_dir.exists():
                            wt = str(snapshot_dir)
                        slice_refs.append(
                            SliceRef(
                                slice_id=lib_dir.name,
                                layer=layer,
                                library_id=lib_dir.name,
                                worktree_path=wt,
                            )
                        )

        elif layer == "l2":
            # Try component manifest first (produced by architectural refinement)
            manifest_path = (
                self.manager.structure.root
                / "reports"
                / "pdd"
                / self.manager.run_id
                / "component_manifest.json"
            )
            if manifest_path.exists():
                try:
                    data = json.loads(manifest_path.read_text(encoding="utf-8"))
                    for comp in data.get("components", []):
                        comp_id = comp.get("component_id", comp.get("id", ""))
                        if comp_id:
                            # Determine worktree path from component's files
                            files = comp.get("files", [])
                            wt_path = str(self.manager.structure.spec_snapshot_dir)
                            if files:
                                first_file = Path(files[0])
                                if first_file.parent != Path("."):
                                    wt_path = str(
                                        self.manager.structure.spec_snapshot_dir / first_file.parent
                                    )
                            slice_refs.append(
                                SliceRef(
                                    slice_id=f"arch-{comp_id}",
                                    layer=layer,
                                    worktree_path=wt_path,
                                )
                            )
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("Failed to read component manifest: %s", exc)

            # Fallback: wrap libraries as architectural slices
            if not slice_refs:
                libraries_dir = self.manager.structure.libraries_dir
                if libraries_dir.exists():
                    for lib_dir in sorted(libraries_dir.iterdir()):
                        if lib_dir.is_dir():
                            slice_refs.append(
                                SliceRef(
                                    slice_id=f"arch-{lib_dir.name}",
                                    layer=layer,
                                    library_id=lib_dir.name,
                                    worktree_path=str(lib_dir),
                                )
                            )

        elif layer == "l3":
            # L3: one slice per code file (finding clusters handled internally)
            spec_snapshot_dir = self.manager.structure.spec_snapshot_dir
            if spec_snapshot_dir.exists():
                for py_file in source_rglob(spec_snapshot_dir):
                    if py_file.is_file():
                        slice_refs.append(
                            SliceRef(
                                slice_id=f"cq-{py_file.stem}",
                                layer=layer,
                                worktree_path=str(py_file.parent),
                            )
                        )

        return slice_refs

    # ------------------------------------------------------------------
    # L1 with human approval
    # ------------------------------------------------------------------

    def _run_l1_with_approval(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Run L1 layer with human approval loop.

        Per ``simpler.md``: generate overview → human reviews → approve
        or patch → repeat.

        In ``"auto"`` and ``"steering"`` modes, approval is automatic.
        In ``"interactive"`` mode, the user is prompted for approval.

        Returns:
            Tuple of ``(l1_result, approval_result)``.
        """
        iteration = 0
        l1_result: dict[str, Any] = {}

        while iteration < self.max_approval_iterations:
            iteration += 1
            logger.info(
                "=== L1 approval iteration %d/%d ===",
                iteration,
                self.max_approval_iterations,
            )

            l1_result = self._run_layer("l1")

            # Generate overview for review
            overview = self._generate_overview()
            l1_result["overview"] = overview

            # POWER alignment check
            alignment = self._check_alignment()
            l1_result["alignment"] = alignment

            approval = self._request_approval(l1_result, iteration)

            if approval["approved"]:
                return l1_result, approval

            logger.info(
                "L1 not approved (iteration %d): %s",
                iteration,
                approval.get("feedback", ""),
            )

        # Max iterations reached — auto-approve
        logger.warning(
            "Max approval iterations (%d) reached — auto-approving",
            self.max_approval_iterations,
        )
        return l1_result, {
            "approved": True,
            "iteration": iteration,
            "auto_approved": True,
            "reason": "max_iterations_reached",
        }

    def _write_approval_artifact(
        self,
        layer: str,
        approved: bool,
        iteration: int = 0,
        **extra: Any,
    ) -> None:
        """Write an approval decision artifact using run-scoped layout.

        Args:
            layer: Approval layer (e.g., "l1", "l2", "release").
            approved: Whether the checkpoint was approved.
            iteration: Iteration number (relevant for L1 loops).
            **extra: Additional metadata to include in the artifact.
        """
        if not hasattr(self, "_state_mgr"):
            return

        approvals_root = self._state_mgr.run_dir / "approvals"
        if layer == "l1":
            artifact_path = approvals_root / "l1" / f"iteration_{iteration}" / "decision.json"
        elif layer == "l2":
            artifact_path = approvals_root / "l2" / "decision.json"
        elif layer == "release":
            artifact_path = approvals_root / "l3" / "release_decision.json"
        else:
            artifact_path = approvals_root / layer / "decision.json"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)

        decision: dict[str, Any] = {
            "layer": layer,
            "iteration": iteration,
            "approved": approved,
            "mode": self.mode,
        }
        decision.update(extra)
        artifact_path.write_text(json.dumps(decision, indent=2), encoding="utf-8")

    def _request_approval(self, result: dict[str, Any], iteration: int) -> dict[str, Any]:
        """Request human approval of the L1 output.

        Args:
            result: Results from the L1 layer.
            iteration: Current iteration number.

        Returns:
            Approval dict with ``approved`` bool and optional
            ``feedback`` string.
        """
        run_reports_dir = self.manager.structure.root / "reports" / "pdd" / self.manager.run_id
        overview_ref = (result.get("overview") or {}).get("overview_path", "")
        alignment_ref = str(run_reports_dir / "alignment_report.json")

        if self.mode in ("auto", "steering"):
            self._write_approval_artifact(
                "l1",
                approved=True,
                iteration=iteration,
                overview_ref=overview_ref,
                alignment_ref=alignment_ref,
            )
            return {"approved": True, "iteration": iteration, "mode": self.mode}

        # Interactive mode — prompt user
        overview_result = result.get("overview", {})
        overview_path = overview_result.get("overview_path", "")

        print("\n" + "=" * 60)
        print("PDD L1 (Code-as-Spec) COMPLETE — Review Required")
        print("=" * 60)
        if overview_path:
            print(f"\nOverview document: {overview_path}")
        print("\nPlease review the overview and library specs.")
        print("Options:")
        print("  [a] Approve — proceed to L2 (Architecture)")
        print("  [f] Feedback — provide feedback for next iteration")
        print("  [q] Quit — abort lifecycle")

        try:
            choice = input("\nYour choice [a/f/q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "a"

        if choice == "a" or choice == "":
            self._write_approval_artifact(
                "l1",
                approved=True,
                iteration=iteration,
                overview_ref=overview_ref,
                alignment_ref=alignment_ref,
            )
            return {"approved": True, "iteration": iteration, "mode": "interactive"}

        if choice == "q":
            raise KeyboardInterrupt("User aborted lifecycle")

        # Feedback mode
        try:
            feedback = input("Feedback: ").strip()
        except (EOFError, KeyboardInterrupt):
            feedback = ""

        # Write feedback to run-scoped reports directory
        run_reports_dir.mkdir(parents=True, exist_ok=True)
        feedback_path = run_reports_dir / f"feedback_iteration_{iteration}.txt"
        feedback_path.write_text(feedback, encoding="utf-8")

        self._write_approval_artifact(
            "l1",
            approved=False,
            iteration=iteration,
            overview_ref=overview_ref,
            alignment_ref=alignment_ref,
            feedback_path=str(feedback_path),
        )
        return {
            "approved": False,
            "iteration": iteration,
            "feedback": feedback,
            "feedback_path": str(feedback_path),
            "mode": "interactive",
        }

    def _request_l2_checkpoint(self, l2_result: dict[str, Any]) -> dict[str, Any]:
        """Optional L2 checkpoint: approve architecture topology before L3.

        Only prompted in interactive mode.  Auto/steering modes auto-approve.

        Args:
            l2_result: Results from the L2 layer.

        Returns:
            Checkpoint result dict.
        """
        if self.mode in ("auto", "steering"):
            self._write_approval_artifact("l2", approved=True)
            return {"approved": True, "mode": self.mode}

        print("\n" + "=" * 60)
        print("PDD L2 (Architecture) COMPLETE — Optional Checkpoint")
        print("=" * 60)
        print("\nArchitecture layer is done. Review component topology before L3.")
        print("Options:")
        print("  [a] Approve — proceed to L3 (Clean Code)")
        print("  [q] Quit — abort lifecycle")

        try:
            choice = input("\nYour choice [a/q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "a"

        if choice == "q":
            raise KeyboardInterrupt("User aborted lifecycle at L2 checkpoint")

        self._write_approval_artifact("l2", approved=True)
        return {"approved": True, "mode": "interactive"}

    def _request_release_signoff(self, results: dict[str, Any]) -> dict[str, Any]:
        """Release signoff after L3 + final governance.

        Auto-approve in auto/steering modes.

        Args:
            results: Full run results.

        Returns:
            Signoff result dict.
        """
        if self.mode in ("auto", "steering"):
            self._write_approval_artifact("release", approved=True)
            return {"approved": True, "mode": self.mode}

        scorecard = results.get("scorecard", {})
        passed = scorecard.get("overall_pass", True)

        print("\n" + "=" * 60)
        print("PDD Pipeline COMPLETE — Release Signoff")
        print("=" * 60)
        print(f"\nOverall scorecard: {'PASS' if passed else 'FAIL'}")
        final_gov = results.get("final_governance", {})
        if not final_gov.get("passed", True):
            print(f"Governance: FAIL — {final_gov.get('error', '')}")
        print("\nOptions:")
        print("  [a] Approve release")
        print("  [r] Reject release")

        try:
            choice = input("\nYour choice [a/r]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "a"

        approved = choice != "r"
        self._write_approval_artifact("release", approved=approved)
        return {"approved": approved, "mode": "interactive"}

    # ------------------------------------------------------------------
    # Intake
    # ------------------------------------------------------------------

    def _run_intake(self) -> dict[str, Any]:
        """Run Phase 0 intake: raw prose → code-as-spec.

        Uses the PddOrchestrator for Phase 0 execution.

        Returns:
            Phase 0 results.
        """
        logger.info("=== PDD Lifecycle: INTAKE ===")
        from spec_manager.refinement.workspace.state import Phase

        try:
            return self.orchestrator.run_phase(Phase.EXTRACTION)
        except Exception as exc:
            logger.warning("Phase 0 intake failed: %s", exc)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Typed refinement methods
    # ------------------------------------------------------------------

    def _library_refinement(self) -> dict[str, Any]:
        """Library refinement: concern isolation, overlap, coverage.

        Runs ambiguity detection + resolution on each library spec
        using :class:`InteractiveWorkflow` in the configured mode.

        Returns:
            Refinement results per library.
        """
        from spec_manager.refinement.interactive.workflow import InteractiveWorkflow

        libraries_dir = self.manager.structure.libraries_dir
        if not libraries_dir.exists():
            return {"note": "No libraries directory — skipping refinement."}

        results: dict[str, Any] = {}
        workspace = self.manager.workspace_path

        for lib_dir in sorted(libraries_dir.iterdir()):
            if not lib_dir.is_dir():
                continue
            lib_id = lib_dir.name

            lib_content = self._gather_library_content(lib_dir)
            if not lib_content:
                results[lib_id] = {"skipped": "no content found"}
                continue

            workflow = InteractiveWorkflow(
                workspace=workspace,
                interactive=(self.mode == "interactive"),
                steering_path=self.steering_path,
                use_research=self.use_research,
                use_evidence_store=self.use_evidence_store,
                max_iterations=self.max_refinement_iterations,
            )

            refined = workflow.run(lib_content)
            changed = refined != lib_content

            if changed:
                analysis_path = lib_dir / "analysis.md"
                analysis_path.write_text(refined, encoding="utf-8")

            results[lib_id] = {
                "refined": changed,
                "original_length": len(lib_content),
                "refined_length": len(refined),
            }

        return results

    def _architectural_refinement(self) -> dict[str, Any]:
        """Architectural refinement: service decomposition, event topology.

        Proposes architectural candidates, identifies issues, and emits
        :class:`DemotionTicket` instances for findings that require changes
        at lower layers.

        Returns:
            Architecture refinement results including demotion tickets.
        """
        logger.info("=== Architectural Refinement ===")

        from spec_manager.core.agent_utils import run_agent
        from spec_manager.orchestration.demotion import DemotionTicket
        from spec_manager.refinement.formats import (
            _extract_json_payload,
            _strip_code_fences,
        )

        evidence_rows = self._gather_latest_evidence()
        if not evidence_rows:
            code_files = self._gather_all_code()
            if not code_files:
                return {
                    "note": (
                        "No code found in spec_snapshot and no promotion "
                        "evidence — skipping architectural refinement."
                    )
                }
            evidence_rows = [
                {
                    "slice_id": rel_path,
                    "layer": "l2",
                    "file_hash": _hash_text(content),
                    "manifest_file_count": 1,
                    "open_gap_count": 0,
                    "pin_count": 0,
                    "edge_count": 0,
                }
                for rel_path, content in code_files.items()
            ]

        evidence_section = []
        for row in evidence_rows[:30]:
            evidence_section.append(
                "## Slice Evidence\n"
                f"- slice_id: {row.get('slice_id', '')}\n"
                f"- layer: {row.get('layer', '')}\n"
                f"- file_hash: {row.get('file_hash', '')}\n"
                f"- manifest_file_count: {row.get('manifest_file_count', 0)}\n"
                f"- open_gap_count: {row.get('open_gap_count', 0)}\n"
                f"- pin_count: {row.get('pin_count', 0)}\n"
                f"- edge_count: {row.get('edge_count', 0)}\n"
            )

        prompt = (
            "## TASK\n\n"
            "Given the following promotion evidence, propose 3-5 architecture candidates.\n"
            "For each candidate, describe: components, communication patterns,\n"
            "deployment model, and tradeoffs.\n\n"
            "Also identify architectural issues indicated by the evidence that need fixing.\n"
            "For each issue, include: severity (BLOCKER/MAJOR/MINOR), file, description.\n\n"
            "Return JSON with keys:\n"
            "- 'candidates': array of architecture proposals\n"
            "- 'issues': array of architectural issues found\n\n"
            + "\n\n---\n\n".join(evidence_section)
        )

        refinement_model_id = self._resolve_model_id_for_role("refinement")

        try:
            output = run_agent(
                agent_name="opus-architecture-proposer",
                prompt=prompt,
                workspace=self.manager.workspace_path,
                model_id=refinement_model_id,
                role="architecture_proposer",
                run_id=self.manager.run_id,
                layer="l2",
                call_hook=self._record_llm_call,
            )
            cleaned = _strip_code_fences(output)
            data = json.loads(_extract_json_payload(cleaned))
            candidates = data.get("candidates", [])
            issues = data.get("issues", [])

            # Write proposals to disk
            self._write_run_report("architecture_proposals.json", data)

            # Emit DemotionTickets for architectural issues
            tickets: list[dict[str, Any]] = []
            for issue in issues:
                severity = issue.get("severity", "MINOR")
                ticket = DemotionTicket(
                    source="ARCH_GATE",
                    target_layer="L1" if severity == "BLOCKER" else "L2",
                    origin_layer="L2",
                    severity=severity if severity in ("BLOCKER", "MAJOR", "MINOR") else "MINOR",
                    diagnosis=issue.get("description", "Architectural issue"),
                    failing_files=[issue.get("file", "")] if issue.get("file") else [],
                )
                tickets.append(ticket.to_dict())

            if tickets:
                self._write_run_report("architecture_demotion_tickets.json", tickets)

            return {
                "candidates_proposed": len(candidates),
                "proposals_path": self._run_report_relpath("architecture_proposals.json"),
                "demotion_tickets": len(tickets),
            }
        except Exception as exc:
            logger.warning("Architectural refinement failed: %s", exc)
            return {"error": str(exc)}

    def _code_quality_refinement(self) -> dict[str, Any]:
        """Code quality refinement: correctness, clarity, consistency.

        Runs N quality reviewers and emits :class:`DemotionTicket`
        instances for findings that touch logic (demote to L1) or
        architecture (demote to L2).

        Returns:
            Code quality refinement results including demotion tickets.
        """
        logger.info("=== Code Quality Refinement ===")

        from spec_manager.core.agent_utils import run_agent
        from spec_manager.orchestration.demotion import DemotionTicket
        from spec_manager.refinement.formats import (
            _extract_json_payload,
            _strip_code_fences,
        )

        evidence_rows = self._gather_latest_evidence()
        if not evidence_rows:
            all_specs = self._gather_all_code()
            if not all_specs:
                return {
                    "note": (
                        "No code found in spec_snapshot and no promotion "
                        "evidence — skipping code quality refinement."
                    )
                }
            evidence_rows = [
                {
                    "slice_id": path,
                    "layer": "l3",
                    "file_hash": _hash_text(content),
                    "manifest_file_count": 1,
                    "open_gap_count": 0,
                    "pin_count": 0,
                    "edge_count": 0,
                }
                for path, content in all_specs.items()
            ]

        reviewers = [
            "chatgpt-clarity-reviewer",
            "chatgpt-completeness-reviewer",
            "chatgpt-consistency-reviewer",
            "chatgpt-correctness-reviewer",
        ]
        review_model_id = self._resolve_model_id_for_role("review")

        all_findings: list[dict[str, Any]] = []

        for row in evidence_rows:
            slice_id = row.get("slice_id", "")
            prompt = (
                f"## TASK\n\n"
                f"Review the following promotion evidence for quality risks.\n"
                f"For each finding include: severity (BLOCKER/MAJOR/MINOR),\n"
                f"category (logic/architecture/style), and description.\n"
                f"Return JSON with key 'findings' containing an array of issues.\n\n"
                f"Evidence slice: {slice_id}\n\n"
                f"Evidence:\n{json.dumps(row, indent=2)}\n"
            )

            for reviewer in reviewers:
                try:
                    output = run_agent(
                        agent_name=reviewer,
                        prompt=prompt,
                        workspace=self.manager.workspace_path,
                        model_id=review_model_id,
                        role=reviewer,
                        run_id=self.manager.run_id,
                        slice_id=slice_id,
                        layer=str(row.get("layer", "l3")),
                        call_hook=self._record_llm_call,
                    )
                    cleaned = _strip_code_fences(output)
                    data = json.loads(_extract_json_payload(cleaned))
                    findings = data.get("findings", [])
                    for finding in findings:
                        finding["file"] = slice_id
                        finding["reviewer"] = reviewer
                    all_findings.extend(findings)
                except Exception as exc:
                    logger.warning(
                        "Reviewer %s failed for evidence slice %s: %s", reviewer, slice_id, exc
                    )

        # Write quality report
        self._write_run_report("code_quality_report.json", {"findings": all_findings})

        # Emit DemotionTickets for findings that touch logic or architecture
        tickets: list[dict[str, Any]] = []
        for finding in all_findings:
            category = finding.get("category", "style")
            severity = finding.get("severity", "MINOR")
            if category in ("logic", "architecture") or severity == "BLOCKER":
                target = "L1" if category == "logic" else "L2"
                ticket = DemotionTicket(
                    source="REVIEW",
                    target_layer=target,
                    origin_layer="L3",
                    severity=severity if severity in ("BLOCKER", "MAJOR", "MINOR") else "MINOR",
                    diagnosis=finding.get("description", finding.get("issue", "Quality issue")),
                    failing_files=[finding.get("file", "")] if finding.get("file") else [],
                )
                tickets.append(ticket.to_dict())

        if tickets:
            self._write_run_report("code_quality_demotion_tickets.json", tickets)

        return {
            "files_reviewed": len(evidence_rows),
            "total_findings": len(all_findings),
            "report_path": self._run_report_relpath("code_quality_report.json"),
            "demotion_tickets": len(tickets),
        }

    # ------------------------------------------------------------------
    # Governance helpers
    # ------------------------------------------------------------------

    def _run_governance_check(
        self,
        checkpoint: str,
        *,
        check_artifacts: bool = False,
        check_report: bool = False,
    ) -> dict[str, Any]:
        """Run governance validation at a pipeline checkpoint.

        Checks:
        - No open governance FAIL findings
        - Required artifacts present (if check_artifacts)
        - Report completeness (if check_report)

        Args:
            checkpoint: Name of the checkpoint (e.g., "transition_l1_l2", "final").
            check_artifacts: Whether to verify artifact presence.
            check_report: Whether to verify final report.

        Returns:
            Dict with ``passed`` bool and findings.
        """
        run_id = self.manager.run_id
        workspace = self.manager.workspace_path
        run_dir = workspace / ".pdd_runs" / run_id
        reports_dir = workspace / "reports" / "pdd" / run_id
        findings: list[str] = []

        if check_artifacts:
            bundle_paths = self._iter_bundle_paths()
            if not bundle_paths:
                findings.append("No evidence bundles found in slices directory")
            else:
                integrity_errors = 0
                for bundle_path in bundle_paths:
                    try:
                        bundle_data = json.loads(bundle_path.read_text(encoding="utf-8"))
                    except Exception as exc:
                        findings.append(f"Unreadable evidence bundle: {bundle_path.name} ({exc})")
                        integrity_errors += 1
                        continue
                    issues = self._bundle_integrity_issues(bundle_data)
                    if issues:
                        integrity_errors += 1
                        parent_name = bundle_path.parent.name
                        grandparent_name = bundle_path.parent.parent.name
                        findings.append(f"{grandparent_name}/{parent_name}: {issues[0]}")
                if integrity_errors > 0:
                    findings.append(f"{integrity_errors} bundle(s) failed integrity checks")

            # Verify demotion ledger exists (it's OK if empty)
            demotions_dir = run_dir / "demotions"
            if not demotions_dir.exists():
                findings.append("Demotions directory missing")

        if check_report:
            report_path = reports_dir / "final_report.md"
            if not report_path.exists():
                findings.append("Final report missing")
            scorecard_path = reports_dir / "scorecard.json"
            if not scorecard_path.exists():
                findings.append("Scorecard JSON missing")

        passed = len(findings) == 0
        return {
            "checkpoint": checkpoint,
            "passed": passed,
            "findings": findings,
            "error": "; ".join(findings) if findings else "",
        }

    # ------------------------------------------------------------------
    # CI helpers
    # ------------------------------------------------------------------

    def _run_readiness_ci(self, layer: Layer) -> dict[str, Any]:
        """Run tier-aware smoke check on a layer's dirty worktree.

        Uses :class:`TierRunner` to dispatch the appropriate test tiers
        for the given layer.  Validates that the downstream dirty worktree
        is runnable before creative work begins.

        Args:
            layer: The layer whose dirty worktree to test.

        Returns:
            Dict with ``passed`` bool, tier results, and optional ``error``.
        """
        from spec_manager.orchestration.test_tiers import TierConfig, TierRunner

        if not self.worktree_manager:
            return {"passed": True, "note": "No worktree manager — skipping readiness CI"}

        dirty_path = self.worktree_manager.get_layer_worktree(layer, "dirty")
        if not dirty_path or not dirty_path.exists():
            return {"passed": True, "note": f"No dirty worktree for {layer}"}

        runner = TierRunner(config=TierConfig(), cwd=dirty_path)
        tier_results = runner.run_for_layer(layer)
        all_passed = all(r.passed for r in tier_results)

        result: dict[str, Any] = {
            "passed": all_passed,
            "tiers": [r.to_dict() for r in tier_results],
        }
        if not all_passed:
            failed = [r for r in tier_results if not r.passed]
            result["error"] = f"Tier {failed[0].tier} failed: {failed[0].error[:500]}"

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_git_ref(self, ref_name: str) -> None:
        """Record a git ref milestone for the run.

        Writes ref metadata to the run directory so downstream tooling
        can reconstruct the pipeline timeline.

        Args:
            ref_name: Ref name (e.g., ``pdd/<run_id>/l1-approved``).
        """
        if not hasattr(self, "_state_mgr"):
            return
        import time

        refs_dir = self._state_mgr.run_dir / "refs"
        refs_dir.mkdir(parents=True, exist_ok=True)
        ref_data = {
            "ref": ref_name,
            "run_id": self.manager.run_id,
            "timestamp": time.time(),
        }
        (refs_dir / f"{ref_name.replace('/', '_')}.json").write_text(
            json.dumps(ref_data, indent=2), encoding="utf-8"
        )

    def _write_run_report(self, filename: str, data: dict | list | str) -> None:
        """Write a report file to the run-scoped reports directory.

        Args:
            filename: Report filename (e.g., "architecture_proposals.json").
            data: Data to write (dict/list serialized as JSON, str written as-is).
        """
        content = (
            json.dumps(data, indent=2, ensure_ascii=False)
            if isinstance(data, (dict, list))
            else data
        )

        # Run-scoped path
        run_reports_dir = self._run_reports_dir()
        run_reports_dir.mkdir(parents=True, exist_ok=True)
        (run_reports_dir / filename).write_text(content, encoding="utf-8")

    def _run_reports_dir(self) -> Path:
        """Return the run-scoped reports directory path."""
        return self.manager.structure.root / "reports" / "pdd" / self.manager.run_id

    def _run_report_relpath(self, filename: str) -> str:
        """Return run-scoped report path relative to workspace root."""
        return f"reports/pdd/{self.manager.run_id}/{filename}"

    def _record_llm_call(self, payload: dict[str, Any]) -> None:
        """Persist LLM call telemetry to this run's cost ledger."""
        from spec_manager.evaluation.cost_ledger import CostLedger, LLMCallRecord

        run_id = str(payload.get("run_id", "") or self.manager.run_id)
        ledger_path = (
            self.manager.workspace_path / ".pdd_runs" / run_id / "analysis" / "llm_calls.jsonl"
        )
        if (
            self._cost_ledger is None
            or getattr(self._cost_ledger, "ledger_path", None) != ledger_path
        ):
            self._cost_ledger = CostLedger(ledger_path)
        self._cost_ledger.record(LLMCallRecord.from_dict(payload))

    def _iter_bundle_paths(self) -> list[Path]:
        """List all per-iteration bundle.json artifacts for the active run."""
        run_slices_dir = self.manager.workspace_path / ".pdd_runs" / self.manager.run_id / "slices"
        if not run_slices_dir.exists():
            return []
        return sorted(run_slices_dir.glob("*/iter_*/bundle.json"))

    def _bundle_integrity_issues(self, bundle_data: dict[str, Any]) -> list[str]:
        """Return evidence integrity failures for one bundle payload."""
        issues: list[str] = []
        manifest_files = (bundle_data.get("manifest") or {}).get("files") or []
        if not manifest_files:
            issues.append("manifest.files missing")
            return issues

        for item in manifest_files:
            if not item.get("path"):
                issues.append("manifest file missing path")
            if not item.get("sha256"):
                issues.append("manifest file missing sha256")

        material = "\n".join(
            f"{item.get('path', '')}:{item.get('sha256', '')}"
            for item in sorted(manifest_files, key=lambda x: x.get("path", ""))
        )
        expected_hash = _hash_text(material) if material else ""
        diff_hash = (bundle_data.get("diff") or {}).get("content_hash") or ""
        if expected_hash and diff_hash and expected_hash != diff_hash:
            issues.append("diff.content_hash does not match manifest hash")

        pins_snapshot = bundle_data.get("pins_snapshot") or {}
        graph_snapshot = bundle_data.get("graph_snapshot") or {}
        if not pins_snapshot.get("path"):
            issues.append("pins_snapshot.path missing")
        if not pins_snapshot.get("snapshot_hash"):
            issues.append("pins_snapshot.snapshot_hash missing")
        if not graph_snapshot.get("path"):
            issues.append("graph_snapshot.path missing")
        if not graph_snapshot.get("snapshot_hash"):
            issues.append("graph_snapshot.snapshot_hash missing")

        return issues

    def _gather_latest_evidence(self) -> list[dict[str, Any]]:
        """Load one latest bundle per slice and summarize key evidence fields."""
        by_slice: dict[str, Path] = {}
        for bundle_path in self._iter_bundle_paths():
            slice_id = bundle_path.parent.parent.name
            prev = by_slice.get(slice_id)
            if prev is None or bundle_path.parent.name > prev.parent.name:
                by_slice[slice_id] = bundle_path

        rows: list[dict[str, Any]] = []
        for slice_id, path in sorted(by_slice.items()):
            try:
                bundle_data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.debug("Skipping unreadable bundle %s: %s", path, exc)
                continue

            layer_hint = "l1"
            if slice_id.startswith("arch-"):
                layer_hint = "l2"
            elif slice_id.startswith("cq-"):
                layer_hint = "l3"
            manifest_files = (bundle_data.get("manifest") or {}).get("files") or []
            implementation = bundle_data.get("implementation") or {}
            gaps = (bundle_data.get("gaps") or {}).get("open_gaps") or []
            rows.append(
                {
                    "slice_id": slice_id,
                    "layer": layer_hint,
                    "file_hash": (bundle_data.get("diff") or {}).get("content_hash", ""),
                    "manifest_file_count": len(manifest_files),
                    "open_gap_count": len(gaps),
                    "pin_count": len(implementation.get("pin_proposals") or []),
                    "edge_count": len(implementation.get("edge_proposals") or []),
                    "bundle_path": str(path),
                }
            )
        return rows

    def _gather_library_content(self, lib_dir: Path) -> str:
        """Gather content for a library from its detail files.

        Returns a combined view of the library's own detail files
        (algorithms.md, shapes.md, stores.md, constraints.md, analysis.md).

        Args:
            lib_dir: Library directory (e.g., runs/<run>/libraries/LIB-01).

        Returns:
            Combined content string, or empty string if nothing found.
        """
        parts: list[str] = []

        details_dir = lib_dir / "details"
        if details_dir.exists():
            for detail_file in sorted(details_dir.iterdir()):
                if detail_file.is_file() and detail_file.suffix == ".md":
                    content = detail_file.read_text(encoding="utf-8")
                    parts.append(f"### {detail_file.stem}\n\n{content}")

        for fname in ("constraints.md", "analysis.md"):
            fpath = lib_dir / fname
            if fpath.exists():
                content = fpath.read_text(encoding="utf-8")
                parts.append(f"### {fname.replace('.md', '')}\n\n{content}")

        return "\n\n---\n\n".join(parts)

    def _gather_all_code(self) -> dict[str, str]:
        """Gather all code from spec_snapshot, keyed by filename.

        Returns:
            Dict mapping relative path to file content.
        """
        from spec_manager.core.language import source_rglob

        code_files: dict[str, str] = {}
        spec_snapshot_dir = self.manager.structure.spec_snapshot_dir
        if spec_snapshot_dir.exists():
            for py_file in source_rglob(spec_snapshot_dir):
                if py_file.is_file():
                    try:
                        code_files[str(py_file.relative_to(spec_snapshot_dir))] = py_file.read_text(
                            encoding="utf-8"
                        )
                    except (OSError, UnicodeDecodeError):
                        continue
        return code_files

    def _check_alignment(self) -> dict[str, Any]:
        """Run POWER alignment check on all library specs.

        Calls alignment review agents per library to detect drift and reward hacking.
        """
        from spec_manager.core.agent_utils import run_agent
        from spec_manager.refinement.formats import (
            _extract_json_payload,
            _strip_code_fences,
        )

        libraries_dir = self.manager.structure.libraries_dir
        if not libraries_dir.exists():
            return {"note": "No libraries directory — skipping alignment check."}

        total_drift = 0
        total_reward_hacking = 0
        libraries_checked = 0
        errors: list[dict[str, Any]] = []
        review_model_id = self._resolve_model_id_for_role("review")

        code_files = self._gather_all_code()

        for lib_dir in sorted(libraries_dir.iterdir()):
            if not lib_dir.is_dir():
                continue
            lib_id = lib_dir.name
            charter_path = lib_dir / "charter.md"
            constraints_path = lib_dir / "constraints.md"

            charter_content = (
                charter_path.read_text(encoding="utf-8") if charter_path.exists() else ""
            )
            constraints_content = (
                constraints_path.read_text(encoding="utf-8") if constraints_path.exists() else ""
            )

            if not charter_content and not constraints_content:
                continue

            lib_content = self._gather_library_content(lib_dir)

            code_summary = "\n\n".join(
                f"### {fp}\n```python\n{content[:1500]}\n```"
                for fp, content in list(code_files.items())[:10]
            )

            prompt = (
                "## TASK\n\n"
                "Check the current code against the original charter/constraints.\n"
                "Detect requirement drift and reward hacking.\n"
                "Return JSON with keys: drift_findings, reward_hacking_findings.\n\n"
                f"Library ID: {lib_id}\n\n"
                f"Charter:\n{charter_content.strip()}\n\n"
                f"Constraints:\n{constraints_content.strip()}\n\n"
                f"Library Details:\n{lib_content[:2000]}\n\n"
                f"Current Code:\n{code_summary}\n"
            )

            try:
                output = run_agent(
                    agent_name="opus-alignment-checker",
                    prompt=prompt,
                    workspace=self.manager.workspace_path,
                    model_id=review_model_id,
                    role="alignment_checker",
                    run_id=self.manager.run_id,
                    slice_id=lib_id,
                    layer="l3",
                    call_hook=self._record_llm_call,
                )
                cleaned = _strip_code_fences(output)
                data = json.loads(_extract_json_payload(cleaned))

                drift = data.get("drift_findings", [])
                reward = data.get("reward_hacking_findings", [])
                total_drift += len(drift)
                total_reward_hacking += len(reward)
                libraries_checked += 1
            except Exception as exc:
                errors.append({"lib_id": lib_id, "error": str(exc)})

        # Write alignment report
        report = {
            "libraries_checked": libraries_checked,
            "drift_findings": total_drift,
            "reward_hacking_findings": total_reward_hacking,
            "errors": errors,
        }
        self._write_run_report("alignment_report.json", report)

        return report

    def _generate_overview(self) -> dict[str, Any]:
        """Generate a human-readable overview document for review.

        Calls overview writer agents per library and consolidates into a
        single ``overview.md``.
        """
        from spec_manager.core.agent_utils import run_agent

        libraries_dir = self.manager.structure.libraries_dir
        if not libraries_dir.exists():
            return {"note": "No libraries directory — skipping overview generation."}

        overview_parts: list[str] = []
        libraries_processed = 0
        errors: list[dict[str, Any]] = []
        refinement_model_id = self._resolve_model_id_for_role("refinement")

        for lib_dir in sorted(libraries_dir.iterdir()):
            if not lib_dir.is_dir():
                continue
            lib_id = lib_dir.name

            lib_content = self._gather_library_content(lib_dir)
            if not lib_content:
                continue

            charter_content = ""
            charter_path = lib_dir / "charter.md"
            if charter_path.exists():
                charter_content = charter_path.read_text(encoding="utf-8")

            prompt = (
                "## TASK\n\n"
                "Generate a human-readable overview for this library.\n"
                "Explain what it does, how components fit together,\n"
                "and key design decisions in clear prose.\n\n"
                "Return the overview as markdown (no JSON wrapper).\n\n"
                f"Library ID: {lib_id}\n\n"
                f"Charter:\n{charter_content.strip()}\n\n"
                f"Library Content:\n{lib_content[:4000]}\n"
            )

            try:
                output = run_agent(
                    agent_name="opus-overview-writer",
                    prompt=prompt,
                    workspace=self.manager.workspace_path,
                    model_id=refinement_model_id,
                    role="overview_writer",
                    run_id=self.manager.run_id,
                    slice_id=lib_id,
                    layer="l3",
                    call_hook=self._record_llm_call,
                )
                overview_parts.append(f"## {lib_id}\n\n{output.strip()}\n")
                libraries_processed += 1
            except Exception as exc:
                errors.append({"lib_id": lib_id, "error": str(exc)})

        # Write consolidated overview
        overview_content = "# Project Overview\n\n" + "\n---\n\n".join(overview_parts)
        self._write_run_report("overview.md", overview_content)
        overview_path = (
            self.manager.structure.root / "reports" / "pdd" / self.manager.run_id / "overview.md"
        )

        return {
            "libraries_processed": libraries_processed,
            "overview_path": str(overview_path),
            "errors": errors,
        }
