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
- **L3 (Clean Code)**: Code quality refinement — clarity, consistency,
  maintainability, correctness/safety, drift, diff-impact

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
import re
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from spec_manager.orchestration.models import Layer
from spec_manager.orchestration.pdd_orchestrator import PddOrchestrator
from spec_manager.refinement.workspace.manager import WorkspaceManager

if TYPE_CHECKING:
    from spec_manager.vcs.worktree import WorktreeManager

logger = logging.getLogger(__name__)
LifecycleRunMode = Literal["build", "qa", "architecture", "code_quality"]


def _hash_text(content: str) -> str:
    """Return stable SHA256 digest for content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# Maps each layer to its typed refinement method name.
_LAYER_REFINEMENT: dict[Layer, str] = {
    "l1": "_library_refinement",
    "l2": "_architectural_refinement",
    "l3": "_code_quality_refinement",
}
_LAYER_LIFECYCLE_MODE: dict[Layer, LifecycleRunMode] = {
    "l1": "build",
    "l2": "architecture",
    "l3": "code_quality",
}

_TERMINAL_SLICE_STATUSES = {"COMPLETE", "PROMOTED", "SKIPPED"}
_LAYER_SEQUENCE: tuple[Layer, Layer, Layer] = ("l1", "l2", "l3")
_LAYER_RANK: dict[str, int] = {layer: idx for idx, layer in enumerate(_LAYER_SEQUENCE)}


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
        max_parallel: Maximum concurrent slice loops per layer scheduler.
        integrate_full_test_every_n_iterations: Periodic full-suite cadence
            for per-slice integration tests.
        refinement_max_issues: Max allowed refinement/coupling issues before a
            slice/layer is considered incomplete.
        qa_enforcement: QA policy mode (``"hard"`` blocks on QA failures,
            ``"soft"`` records failures but continues).
        qa_min_pass_rate: Minimum QA pass rate required when
            ``qa_enforcement="hard"``.
        governance_strict_mode: Whether WARN-level governance findings should
            also block transitions and release.
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
        max_parallel: int = 4,
        integrate_full_test_every_n_iterations: int = 5,
        refinement_max_issues: int = 0,
        qa_enforcement: Literal["hard", "soft"] = "hard",
        qa_min_pass_rate: float = 1.0,
        governance_strict_mode: bool = False,
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
        self.max_pipeline_passes = max(1, max_pipeline_passes)
        self.max_parallel = max(1, max_parallel)
        self.integrate_full_test_every_n_iterations = max(1, integrate_full_test_every_n_iterations)
        self.refinement_max_issues = max(0, refinement_max_issues)
        self.qa_enforcement: Literal["hard", "soft"] = (
            "hard" if qa_enforcement == "hard" else "soft"
        )
        self.qa_min_pass_rate = min(max(float(qa_min_pass_rate), 0.0), 1.0)
        self.governance_strict_mode = bool(governance_strict_mode)
        self._model_profile = model_profile
        self._planner_override_provider = planner_override_provider
        self._compute_quality = False
        self._cost_ledger: Any | None = None
        self.transition_investigator_budget = 2
        self.readiness_investigator_budget = 1

    # ------------------------------------------------------------------
    # Planner construction
    # ------------------------------------------------------------------

    def _build_planner(
        self,
        *,
        work_item_store: Any = None,
        wait_graph: Any = None,
        on_constraint_saved: Callable[[str, str, str], None] | None = None,
    ) -> Any:
        """Build a GeneralPlanner instance with lifecycle tools and coordination wiring."""
        from spec_manager.orchestration.source_analysis_cache import SourceAnalysisCache
        from spec_manager.planner.api import GeneralPlanner
        from spec_manager.planner.tools.constraints_tool import ConstraintsTool
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

        constraints_tool = ConstraintsTool(workspace_root=self.manager.workspace_path)
        research_tool = ResearchTool(
            evidence_searcher=evidence_searcher,
            constraints_tool=constraints_tool,
            steering_script=steering_script,
            research_coordinator=research_coordinator,
            workspace=self.manager.workspace_path,
        )

        # Build source analysis cache and integration/constraints tools
        source_cache = SourceAnalysisCache(
            workspace_root=self.manager.workspace_path,
            run_id=self.manager.run_id,
        )
        integration_tool = IntegrationTool(
            source_cache=source_cache,
            workspace=self.manager.workspace_path,
        )

        return GeneralPlanner(
            workspace_root=self.manager.workspace_path,
            mode=self.mode,
            research_tool=research_tool,
            integration_tool=integration_tool,
            constraints_tool=constraints_tool,
            override_provider=self._planner_override_provider,
            model_id=self._resolve_model_id_for_role("planner"),
            work_item_store=work_item_store,
            wait_graph=wait_graph,
            on_constraint_saved=on_constraint_saved,
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
        if self._model_profile is not None:
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
        config["integrate_full_test_every_n_iterations"] = (
            self.integrate_full_test_every_n_iterations
        )
        config["refinement_max_issues"] = self.refinement_max_issues
        existing_pipeline_ci = config.get("pipeline_ci")
        pipeline_ci: dict[str, Any] = {
            "max_pending_batches": 1,
            "run_gates": True,
            "run_tests": True,
            "tick_interval_sec": 20,
        }
        if isinstance(existing_pipeline_ci, dict):
            pipeline_ci.update(existing_pipeline_ci)
        config["pipeline_ci"] = pipeline_ci
        return config

    @staticmethod
    def _transition_block_status(
        transition: dict[str, Any],
        *,
        default_reason: str,
    ) -> tuple[bool, str]:
        """Return whether a transition should block downstream execution."""
        if bool(transition.get("governance_blocked", False)):
            return True, str(transition.get("error") or default_reason)

        propagation = transition.get("propagation")
        if isinstance(propagation, dict) and not bool(propagation.get("success", True)):
            return True, str(propagation.get("error") or transition.get("error") or default_reason)

        if bool(transition.get("readiness_blocked", False)):
            readiness = transition.get("readiness_ci")
            readiness_error = ""
            if isinstance(readiness, dict):
                readiness_error = str(readiness.get("error") or "")
            return True, str(transition.get("error") or readiness_error or default_reason)

        return False, ""

    def _resolve_layer_worktree(self, layer: Layer, lane: str = "dirty") -> Path | None:
        """Resolve layer/lane worktree path across manager implementations."""
        if not self.worktree_manager:
            return None
        getter = getattr(self.worktree_manager, "get_layer_worktree", None)
        if callable(getter):
            try:
                path = getter(layer, lane)
            except Exception:
                path = None
            if isinstance(path, Path):
                return path
            if path:
                return Path(str(path))
        lane_map = getattr(self.worktree_manager, "_layer_worktrees", {}).get(layer, {})
        candidate = lane_map.get(str(lane))
        if isinstance(candidate, Path):
            return candidate
        if candidate:
            return Path(str(candidate))
        return None

    def _propagate_clean_to_next_layer_result(self, from_layer: Layer) -> dict[str, Any]:
        """Propagate clean->next dirty using merge first with rebase fallback."""
        if not self.worktree_manager:
            return {"success": True, "from_layer": from_layer, "error": "", "strategy": "noop"}

        merge_prop = self.worktree_manager.propagate_clean_to_next_layer(from_layer)
        merge_conflicts = [
            self._normalize_conflict_path(path)
            for path in (merge_prop.conflict_files or [])
            if self._normalize_conflict_path(path)
        ]
        propagation: dict[str, Any] = {
            "success": merge_prop.success,
            "from_layer": merge_prop.from_layer,
            "to_layer": merge_prop.to_layer,
            "merge_sha": merge_prop.merge_sha,
            "error": merge_prop.error,
            "strategy": "merge",
            "conflict_files": merge_conflicts,
        }
        if merge_prop.success:
            return propagation

        rebase_prop = self.worktree_manager.rebase_next_layer_dirty_onto_clean(from_layer)
        rebase_conflicts = [
            self._normalize_conflict_path(path)
            for path in (rebase_prop.conflict_files or [])
            if self._normalize_conflict_path(path)
        ]
        propagation["rebase_fallback"] = {
            "success": rebase_prop.success,
            "from_layer": rebase_prop.from_layer,
            "to_layer": rebase_prop.to_layer,
            "merge_sha": rebase_prop.merge_sha,
            "error": rebase_prop.error,
            "conflict_files": rebase_conflicts,
        }
        if rebase_prop.success:
            combined_conflicts: list[str] = []
            seen_conflicts: set[str] = set()
            for path in merge_conflicts + rebase_conflicts:
                if path and path not in seen_conflicts:
                    seen_conflicts.add(path)
                    combined_conflicts.append(path)
            propagation.update(
                {
                    "success": True,
                    "merge_sha": rebase_prop.merge_sha,
                    "error": "",
                    "strategy": "rebase_fallback",
                    "merge_error": merge_prop.error,
                    "conflict_files": combined_conflicts,
                }
            )
            return propagation

        merge_error = merge_prop.error or "merge propagation failed"
        rebase_error = rebase_prop.error or "rebase fallback failed"
        combined_conflicts: list[str] = []
        seen_conflicts: set[str] = set()
        for path in (
            merge_conflicts
            + rebase_conflicts
            + self._extract_conflict_files_from_errors(merge_error, rebase_error)
        ):
            normalized = self._normalize_conflict_path(path)
            if normalized and normalized not in seen_conflicts:
                seen_conflicts.add(normalized)
                combined_conflicts.append(normalized)
        propagation.update(
            {
                "success": False,
                "error": f"{merge_error}; {rebase_error}",
                "strategy": "merge_then_rebase_fallback",
                "merge_error": merge_error,
                "rebase_error": rebase_error,
                "conflict_files": combined_conflicts,
            }
        )
        return propagation

    def _lower_layer_demotion_targets(
        self,
        *,
        current_layer: Layer,
        tickets: list[dict[str, Any]],
    ) -> list[str]:
        """Return lower-layer targets from newly emitted demotion tickets."""
        current_rank = _LAYER_RANK.get(str(current_layer), 0)
        targets: set[str] = set()
        for ticket in tickets:
            target_layer = str(ticket.get("target_layer", "")).strip().lower()
            target_rank = _LAYER_RANK.get(target_layer)
            if target_rank is None:
                continue
            if target_rank < current_rank:
                targets.add(target_layer)
        return sorted(targets)

    @staticmethod
    def _ci_ticks_passed(slice_run: dict[str, Any]) -> bool:
        """Return True when all CI ticks in a slice run succeeded."""
        ci_ticks = slice_run.get("ci_ticks", [])
        if not isinstance(ci_ticks, list):
            return False
        for tick in ci_ticks:
            if not isinstance(tick, dict):
                continue
            if bool(tick.get("failed", False)):
                return False
        return True

    def _cleanup_inactive_layer_slices(self, layer: Layer) -> dict[str, Any]:
        """Cleanup inactive-layer slices unless unresolved demotions need intervention."""
        if self.worktree_manager is None:
            return {"skipped": True, "reason": "No worktree manager"}
        pending_demotions = self._count_pending_demotions_for_layer(layer)
        if pending_demotions > 0:
            return {
                "skipped": True,
                "reason": f"{pending_demotions} unresolved demotion tickets target {layer.upper()}",
                "pending_demotions": pending_demotions,
            }
        removed = self.worktree_manager.cleanup_layer_slices(layer)
        return {"skipped": False, "removed": removed, "pending_demotions": 0}

    def _run_transition_investigator(
        self,
        *,
        layer: Layer,
        scope_id: str,
        failure_refs: list[str],
        failure_evidence: dict[str, Any],
        investigator_budget: int,
        verify_callback: Callable[[int, dict[str, Any]], tuple[bool, dict[str, Any]]] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Run shared Investigator flow for transition/readiness recovery."""
        from spec_manager.orchestration.promotion_loop import attempt_investigator_recovery

        workspace_root = Path(self.manager.workspace_path)
        layer_worktree = self._resolve_layer_worktree(layer, "dirty")
        if layer_worktree is None:
            report = {
                "fixed": False,
                "attempts": [],
                "error": f"No dirty worktree for layer {layer}",
                "layer": layer,
                "scope_id": scope_id,
            }
        else:
            report = attempt_investigator_recovery(
                run_id=self.manager.run_id,
                slice_id=scope_id,
                layer=layer,
                workspace_root=workspace_root,
                layer_worktree=layer_worktree,
                failure_refs=failure_refs,
                failure_evidence=failure_evidence,
                investigator_budget=investigator_budget,
                verify_callback=verify_callback,
            )
            report["scope_id"] = scope_id

        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", scope_id).strip("_") or "transition"
        report_name = f"{slug}_investigator_report.json"
        self._write_run_report(report_name, report)
        return report, self._run_report_relpath(report_name)

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
        intake_result = self._run_intake()
        results["intake"] = intake_result
        intake_ran = bool(intake_result.get("ran", True))

        # Bootstrap constraints from intake artifacts only when intake ran.
        if intake_ran:
            try:
                from spec_manager.orchestration.under_spec.bootstrap import (
                    bootstrap_constraints_from_intake,
                )

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
        else:
            results["constraints_bootstrapped"] = {
                "skipped": True,
                "reason": "Phase 0 intake skipped",
            }

        state_mgr.update_state(phase="intake_done")

        # Overall pipeline pass cap (budget #4)
        results["pipeline_pass"] = 1
        results["max_pipeline_passes"] = self.max_pipeline_passes

        base_ref_name = f"pdd/{self.manager.run_id}/base"
        base_ref_for_setup: str | None = None
        if intake_ran:
            base_ref_created = self._record_git_ref(base_ref_name)
            results["base_ref"] = {"name": base_ref_name, "created": base_ref_created}
            if not base_ref_created:
                logger.warning(
                    "Failed to create base ref '%s' after intake; "
                    "falling back to default HEAD setup",
                    base_ref_name,
                )
            else:
                base_ref_for_setup = base_ref_name

        # Setup layer worktrees if managed
        if self.worktree_manager:
            if base_ref_for_setup is not None:
                results["setup"] = self.worktree_manager.setup_layers(base_ref=base_ref_for_setup)
            else:
                results["setup"] = self.worktree_manager.setup_layers()

        # Bounded full-pipeline passes (budget #4).
        results["pipeline_pass_history"] = []
        global_termination: dict[str, Any] = {"passed": False}
        for pipeline_pass in range(1, self.max_pipeline_passes + 1):
            results["pipeline_pass"] = pipeline_pass
            pass_outcome: dict[str, Any] = {
                "pipeline_pass": pipeline_pass,
                "l2_blocked": False,
                "l2_blocked_reason": "",
                "l3_blocked": False,
                "l3_blocked_reason": "",
                "release_blocked": False,
                "release_blocked_reason": "",
            }

            # L1: Code-as-Spec (with human approval loop)
            state_mgr.update_state(phase="l1", active_layer="l1")
            l1_result, approval = self._run_l1_with_approval()
            pass_outcome["l1"] = l1_result
            pass_outcome["approval"] = approval
            if str((approval or {}).get("status", "")).upper() == "WAITING":
                waiting_reason = "L1 approval waiting for planner-recorded answers"
                results.update(pass_outcome)
                results["pipeline_pass_history"].append(
                    {
                        "pass": pipeline_pass,
                        "status": "waiting",
                        "reason": waiting_reason,
                    }
                )
                results["awaiting_checkpoint"] = "l1_approval"
                results["waiting"] = True
                state_mgr.update_state(phase="waiting_l1_approval", active_layer="l1")
                return results
            self._record_git_tag(f"pdd/{self.manager.run_id}/l1-approved")
            state_mgr.update_state(
                layers_completed=["l1"],
                phase="l1_l2_transition",
                active_layer="l1",
            )

            l1_termination = (
                l1_result.get("layer_termination") if isinstance(l1_result, dict) else None
            )
            if (
                isinstance(l1_termination, dict)
                and l1_termination
                and not l1_termination.get("passed", False)
            ):
                pass_outcome["l2_blocked"] = True
                pass_outcome["l2_blocked_reason"] = "L1 layer termination checks failed"
                results.update(pass_outcome)
                results["pipeline_pass_history"].append(
                    {
                        "pass": pipeline_pass,
                        "status": "retry",
                        "reason": pass_outcome["l2_blocked_reason"],
                    }
                )
                if pipeline_pass >= self.max_pipeline_passes:
                    results["release_blocked"] = True
                    results["release_blocked_reason"] = pass_outcome["l2_blocked_reason"]
                    state_mgr.update_state(phase="blocked_pipeline_cap")
                    return results
                continue

            # L1→L2 transition: architectural refinement (may demote to L1)
            pass_outcome["l1_l2_transition"] = self._run_transition("l1", "l2")
            l2_transition_blocked, l2_transition_reason = self._transition_block_status(
                pass_outcome["l1_l2_transition"],
                default_reason="L1→L2 transition blocked",
            )
            if l2_transition_blocked:
                pass_outcome["l2_blocked"] = True
                pass_outcome["l2_blocked_reason"] = l2_transition_reason
                l1_l2_transition = pass_outcome.get("l1_l2_transition", {})
                if isinstance(l1_l2_transition, dict) and bool(
                    l1_l2_transition.get("escalation_required", False)
                ):
                    pass_outcome["l2_blocked_reason"] = (
                        f"{l2_transition_reason} (interactive approval required)"
                    )
                    results.update(pass_outcome)
                    results["pipeline_pass_history"].append(
                        {
                            "pass": pipeline_pass,
                            "status": "blocked",
                            "reason": pass_outcome["l2_blocked_reason"],
                        }
                    )
                    results["release_blocked"] = True
                    results["release_blocked_reason"] = pass_outcome["l2_blocked_reason"]
                    results["escalation_required"] = True
                    state_mgr.update_state(phase="blocked_transition_escalation")
                    return results
                results.update(pass_outcome)
                results["pipeline_pass_history"].append(
                    {
                        "pass": pipeline_pass,
                        "status": "retry",
                        "reason": pass_outcome["l2_blocked_reason"],
                    }
                )
                if pipeline_pass >= self.max_pipeline_passes:
                    results["release_blocked"] = True
                    results["release_blocked_reason"] = pass_outcome["l2_blocked_reason"]
                    state_mgr.update_state(phase="blocked_pipeline_cap")
                    return results
                continue

            l1_l2_activation_gate: dict[str, Any] = {
                "drained_baseline": {
                    "passed": True,
                    "note": "No worktree manager; drained-baseline gate not enforced",
                }
            }
            if self.worktree_manager is not None:
                drained_baseline = bool(self.worktree_manager.can_advance_layer("l1"))
                l1_l2_activation_gate["drained_baseline"] = {
                    "passed": drained_baseline,
                    "error": (
                        ""
                        if drained_baseline
                        else "Pipeline not drained for L1→L2 activation "
                        "(requires l2/l3 dirty == clean)"
                    ),
                }
                if not drained_baseline:
                    pass_outcome["l2_blocked"] = True
                    pass_outcome["l2_blocked_reason"] = str(
                        l1_l2_activation_gate["drained_baseline"].get("error", "")
                    )
                    pass_outcome["l1_l2_activation_gate"] = l1_l2_activation_gate
                    results.update(pass_outcome)
                    results["pipeline_pass_history"].append(
                        {
                            "pass": pipeline_pass,
                            "status": "retry",
                            "reason": pass_outcome["l2_blocked_reason"],
                        }
                    )
                    if pipeline_pass >= self.max_pipeline_passes:
                        results["release_blocked"] = True
                        results["release_blocked_reason"] = pass_outcome["l2_blocked_reason"]
                        state_mgr.update_state(phase="blocked_pipeline_cap")
                        return results
                    continue
            pass_outcome["l1_l2_activation_gate"] = l1_l2_activation_gate

            pass_outcome["l1_l2_global_verify"] = self._run_l1_l2_activation_verify()
            if not bool(pass_outcome["l1_l2_global_verify"].get("passed", False)):
                pass_outcome["l2_blocked"] = True
                pass_outcome["l2_blocked_reason"] = "L1→L2 global verify checkpoint failed"
                results.update(pass_outcome)
                results["pipeline_pass_history"].append(
                    {
                        "pass": pipeline_pass,
                        "status": "retry",
                        "reason": pass_outcome["l2_blocked_reason"],
                    }
                )
                if pipeline_pass >= self.max_pipeline_passes:
                    results["release_blocked"] = True
                    results["release_blocked_reason"] = pass_outcome["l2_blocked_reason"]
                    state_mgr.update_state(phase="blocked_pipeline_cap")
                    return results
                continue
            state_mgr.update_state(
                transitions_completed=["l1_l2"],
                phase="l2",
                active_layer="l2",
            )
            if self.worktree_manager:
                pass_outcome["l1_slice_cleanup"] = self._cleanup_inactive_layer_slices("l1")

            # L2: Architecture
            pass_outcome["l2"] = self._run_layer("l2")
            if self.mode == "interactive":
                pass_outcome["l2_checkpoint"] = self._request_l2_checkpoint(pass_outcome["l2"])
                if str(pass_outcome["l2_checkpoint"].get("status", "")).upper() == "WAITING":
                    waiting_reason = "L2 checkpoint waiting for planner-recorded answers"
                    results.update(pass_outcome)
                    results["pipeline_pass_history"].append(
                        {
                            "pass": pipeline_pass,
                            "status": "waiting",
                            "reason": waiting_reason,
                        }
                    )
                    results["awaiting_checkpoint"] = "l2_checkpoint"
                    results["waiting"] = True
                    state_mgr.update_state(phase="waiting_l2_checkpoint", active_layer="l2")
                    return results
                if bool(pass_outcome["l2_checkpoint"].get("approved", False)):
                    self._record_git_tag(f"pdd/{self.manager.run_id}/l2-approved")
            l2_termination = (
                pass_outcome["l2"].get("layer_termination")
                if isinstance(pass_outcome["l2"], dict)
                else None
            )
            if (
                isinstance(l2_termination, dict)
                and l2_termination
                and not l2_termination.get("passed", False)
            ):
                pass_outcome["l3_blocked"] = True
                l2_pause = (
                    pass_outcome["l2"].get("demotion_pause", {})
                    if isinstance(pass_outcome["l2"], dict)
                    else {}
                )
                if isinstance(l2_pause, dict) and bool(l2_pause.get("paused", False)):
                    pass_outcome["l3_blocked_reason"] = str(
                        l2_pause.get("reason")
                        or "L2 creative work paused due to lower-layer demotion"
                    )
                else:
                    pass_outcome["l3_blocked_reason"] = "L2 layer termination checks failed"
                results.update(pass_outcome)
                results["pipeline_pass_history"].append(
                    {
                        "pass": pipeline_pass,
                        "status": "retry",
                        "reason": pass_outcome["l3_blocked_reason"],
                    }
                )
                if pipeline_pass >= self.max_pipeline_passes:
                    results["release_blocked"] = True
                    results["release_blocked_reason"] = pass_outcome["l3_blocked_reason"]
                    state_mgr.update_state(phase="blocked_pipeline_cap")
                    return results
                continue
            self._record_git_ref(f"pdd/{self.manager.run_id}/l2/clean")
            state_mgr.update_state(
                layers_completed=["l1", "l2"],
                phase="l2_l3_transition",
                active_layer="l2",
            )

            # L2→L3 transition: code quality refinement (may demote to L2)
            pass_outcome["l2_l3_transition"] = self._run_transition("l2", "l3")
            l3_transition_blocked, l3_transition_reason = self._transition_block_status(
                pass_outcome["l2_l3_transition"],
                default_reason="L2→L3 transition blocked",
            )
            if l3_transition_blocked:
                pass_outcome["l3_blocked"] = True
                pass_outcome["l3_blocked_reason"] = l3_transition_reason
                l2_l3_transition = pass_outcome.get("l2_l3_transition", {})
                if isinstance(l2_l3_transition, dict) and bool(
                    l2_l3_transition.get("escalation_required", False)
                ):
                    pass_outcome["l3_blocked_reason"] = (
                        f"{l3_transition_reason} (interactive approval required)"
                    )
                    results.update(pass_outcome)
                    results["pipeline_pass_history"].append(
                        {
                            "pass": pipeline_pass,
                            "status": "blocked",
                            "reason": pass_outcome["l3_blocked_reason"],
                        }
                    )
                    results["release_blocked"] = True
                    results["release_blocked_reason"] = pass_outcome["l3_blocked_reason"]
                    results["escalation_required"] = True
                    state_mgr.update_state(phase="blocked_transition_escalation")
                    return results
                results.update(pass_outcome)
                results["pipeline_pass_history"].append(
                    {
                        "pass": pipeline_pass,
                        "status": "retry",
                        "reason": pass_outcome["l3_blocked_reason"],
                    }
                )
                if pipeline_pass >= self.max_pipeline_passes:
                    results["release_blocked"] = True
                    results["release_blocked_reason"] = pass_outcome["l3_blocked_reason"]
                    state_mgr.update_state(phase="blocked_pipeline_cap")
                    return results
                continue
            state_mgr.update_state(
                transitions_completed=["l1_l2", "l2_l3"],
                phase="l3",
                active_layer="l3",
            )
            if self.worktree_manager:
                pass_outcome["l2_slice_cleanup"] = self._cleanup_inactive_layer_slices("l2")

            # L3: Clean Code
            pass_outcome["l3"] = self._run_layer("l3")
            l3_termination = (
                pass_outcome["l3"].get("layer_termination")
                if isinstance(pass_outcome["l3"], dict)
                else None
            )
            if (
                isinstance(l3_termination, dict)
                and l3_termination
                and not l3_termination.get("passed", False)
            ):
                pass_outcome["release_blocked"] = True
                pass_outcome["release_blocked_reason"] = "L3 layer termination checks failed"
                results.update(pass_outcome)
                results["pipeline_pass_history"].append(
                    {
                        "pass": pipeline_pass,
                        "status": "retry",
                        "reason": pass_outcome["release_blocked_reason"],
                    }
                )
                if pipeline_pass >= self.max_pipeline_passes:
                    results["release_blocked"] = True
                    results["release_blocked_reason"] = pass_outcome["release_blocked_reason"]
                    state_mgr.update_state(phase="blocked_pipeline_cap")
                    return results
                continue
            self._record_git_ref(f"pdd/{self.manager.run_id}/l3/clean")
            state_mgr.update_state(
                layers_completed=["l1", "l2", "l3"],
                phase="qa",
                active_layer="",
            )

            # Final QA mode: evals/tests -> demotions -> slice rework rounds.
            pass_outcome["qa_mode"] = self._run_qa_mode()
            pass_outcome["qa"] = pass_outcome["qa_mode"].get("qa", {})
            pass_outcome["qa_gate"] = pass_outcome["qa_mode"].get("qa_gate", {})
            pass_outcome["global_termination"] = self._evaluate_global_termination(pass_outcome)

            results.update(pass_outcome)
            global_termination = pass_outcome["global_termination"]
            results["pipeline_pass_history"].append(
                {
                    "pass": pipeline_pass,
                    "status": "pass" if global_termination.get("passed", False) else "retry",
                    "reason": (
                        ""
                        if global_termination.get("passed", False)
                        else "Global termination checks failed"
                    ),
                }
            )
            if global_termination.get("passed", False):
                break

            logger.warning(
                "Pipeline pass %d/%d failed global termination checks",
                pipeline_pass,
                self.max_pipeline_passes,
            )
            if pipeline_pass >= self.max_pipeline_passes:
                results["release_blocked"] = True
                results["release_blocked_reason"] = (
                    "Global termination checks failed and pipeline pass cap reached"
                )
                state_mgr.update_state(phase="blocked_pipeline_cap")
                return results

        if not global_termination.get("passed", False):
            results["release_blocked"] = True
            results["release_blocked_reason"] = "Global termination checks did not pass"
            state_mgr.update_state(phase="blocked_global_termination")
            return results

        # Scoring
        from spec_manager.evaluation.scoring import RunReporter

        reporter = RunReporter(
            workspace_root=self.manager.workspace_path,
            run_id=self.manager.run_id,
        )
        scorecard = reporter.compute()
        reporter.write(scorecard)
        results["scorecard"] = scorecard.to_dict()

        # Read config flags for optional steps
        _run_config = state_mgr.read_config()
        _enable_quality = (
            _run_config.enable_quality_scoring if _run_config else self._compute_quality
        )
        _enable_snapshots = _run_config.enable_snapshots if _run_config else True
        snapshot_needed = _enable_snapshots or _enable_quality

        # Snapshot (required for immutable digest-based quality scoring).
        if snapshot_needed:
            try:
                from spec_manager.evaluation.snapshot import snapshot_run

                snapshot_run(self.manager.structure.root, self.manager.run_id)
            except Exception as exc:
                logger.warning("Snapshot failed: %s", exc)

        arch_digest: dict[str, Any] | None = None
        code_digest: dict[str, Any] | None = None
        producer_model_id = self._resolve_model_id_for_role("refinement")
        git_sha = self._read_git_sha() or ""
        try:
            from spec_manager.evaluation.digests import (
                build_architecture_digest,
                build_code_digest,
            )

            arch_digest = build_architecture_digest(
                self.manager.structure.root,
                self.manager.run_id,
                git_sha=git_sha,
                producer_model_id=producer_model_id,
            )
            code_digest = build_code_digest(
                self.manager.structure.root,
                self.manager.run_id,
                git_sha=git_sha,
                producer_model_id=producer_model_id,
            )

            run_reports = self.manager.workspace_path / "reports" / "pdd" / self.manager.run_id
            run_reports.mkdir(parents=True, exist_ok=True)
            (run_reports / "architecture_digest.json").write_text(
                json.dumps(arch_digest, indent=2), encoding="utf-8"
            )
            (run_reports / "code_digest.json").write_text(
                json.dumps(code_digest, indent=2), encoding="utf-8"
            )
        except Exception as digest_exc:
            logger.warning("Digest build failed: %s", digest_exc, exc_info=True)

        # Quality scoring (optional)
        if _enable_quality:
            if arch_digest is None or code_digest is None:
                results["quality_scorecard"] = {"error": "missing digests"}
            else:
                try:
                    from spec_manager.evaluation.quality import QualityReporter
                    from spec_manager.refinement.evals.judges.arch_quality import (
                        ArchitectureQualityJudge,
                    )
                    from spec_manager.refinement.evals.judges.cache import JudgeCache

                    arch_judge_output = None
                    judge_model_id = self._resolve_model_id_for_role("judge")
                    try:
                        arch_judge = ArchitectureQualityJudge(
                            workspace=self.manager.structure.root,
                            cache=JudgeCache(
                                self.manager.structure.root / "analysis" / "judge_cache"
                            ),
                            model_id=judge_model_id,
                            producer_model_id=producer_model_id,
                            allow_self_judge=judge_model_id == producer_model_id,
                        )
                        arch_judge_output = arch_judge.evaluate(arch_digest).model_dump()
                    except Exception as judge_exc:
                        logger.warning("Architecture judge failed: %s", judge_exc, exc_info=True)

                    quality_reporter = QualityReporter(
                        self.manager.structure.root, self.manager.run_id
                    )
                    quality_scorecard = quality_reporter.compute(
                        arch_digest,
                        code_digest,
                        arch_judge_output=arch_judge_output,
                        pipeline_scorecard=scorecard,
                    )
                    quality_reporter.write(quality_scorecard)
                    results["quality_scorecard"] = quality_scorecard.to_dict()
                except Exception as exc:
                    logger.warning("Quality scoring failed: %s", exc, exc_info=True)
                    results["quality_scorecard"] = {"error": str(exc)}

        # Final report
        from spec_manager.evaluation.report import FinalReportGenerator

        report_gen = FinalReportGenerator(
            workspace_root=self.manager.workspace_path,
            run_id=self.manager.run_id,
        )
        report_path, scorecard_json_path = report_gen.generate(results, scorecard)
        results["final_report_path"] = str(report_path)
        results["scorecard_json_path"] = str(scorecard_json_path)
        results["run_summary_path"] = self._run_report_relpath("run_summary.json")

        # Final whole-run governance gate
        final_governance = self._run_governance_check(
            "final",
            check_artifacts=True,
            check_report=True,
        )
        results["final_governance"] = final_governance
        if not final_governance.get("passed", True):
            logger.error(
                "Final governance gate failed: %s",
                final_governance.get("error", ""),
            )
            final_ticket = self._emit_governance_failure_ticket(
                gate="FINAL_GOVERNANCE",
                layer="L3",
                diagnosis=str(final_governance.get("error") or "Final governance gate failed"),
                evidence_refs=[
                    self._run_report_relpath("final_report.md"),
                    self._run_report_relpath("scorecard.json"),
                    self._run_report_relpath("run_summary.json"),
                ],
            )
            results["final_governance_ticket"] = final_ticket
            results["release_blocked"] = True
            results["release_blocked_reason"] = "Final governance gate failed"
            state_mgr.update_state(phase="blocked_final_governance")
            return results

        # Release signoff (auto-approve in auto mode)
        results["release_signoff"] = self._request_release_signoff(results)
        if str((results["release_signoff"] or {}).get("status", "")).upper() == "WAITING":
            results["pipeline_pass_history"].append(
                {
                    "pass": pipeline_pass,
                    "status": "waiting",
                    "reason": "Release signoff waiting for planner-recorded answer",
                }
            )
            results["awaiting_checkpoint"] = "release_signoff"
            results["waiting"] = True
            state_mgr.update_state(phase="waiting_release_signoff")
            return results
        if not bool((results["release_signoff"] or {}).get("approved", False)):
            results["release_blocked"] = True
            results["release_blocked_reason"] = "Release signoff rejected"
            state_mgr.update_state(phase="blocked_release_signoff")
            return results

        # Re-render final report after release signoff so L3 decision appears
        # in the consolidated approval checkpoint section.
        report_path, scorecard_json_path = report_gen.generate(results, scorecard)
        results["final_report_path"] = str(report_path)
        results["scorecard_json_path"] = str(scorecard_json_path)
        results["run_summary_path"] = self._run_report_relpath("run_summary.json")

        results["merge_tag"] = self._perform_release_merge_and_tag()
        merge_tag = results["merge_tag"]
        merged_to_main = bool(merge_tag.get("merged", False))
        released_via_branch = bool(merge_tag.get("release_branch_created", False)) and bool(
            merge_tag.get("tagged", False)
        )
        if not (merged_to_main or released_via_branch):
            results["release_blocked"] = True
            err = merge_tag.get("merge_error") or merge_tag.get("tag_error")
            results["release_blocked_reason"] = "Merge/tag action failed: " + str(err)
            state_mgr.update_state(phase="blocked_merge_tag")
            return results

        self._record_git_tag(f"pdd/{self.manager.run_id}/final")

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

    @staticmethod
    def _qa_phase_target_layer(phase_name: str) -> str:
        """Route QA failures to the most likely owning layer."""
        lowered = phase_name.lower()
        if any(token in lowered for token in ("arch", "topology", "wiring", "component")):
            return "L2"
        if any(token in lowered for token in ("style", "maintainability", "readability")):
            return "L3"
        return "L1"

    def _qa_failures_to_tickets(
        self,
        qa_result: dict[str, Any],
        *,
        evidence_ref: str,
    ) -> list[Any]:
        """Convert QA gate failures into DemotionTickets."""
        from spec_manager.orchestration.demotion import DemotionTicket

        failures: list[dict[str, Any]] = []
        qa_rows = qa_result.get("results", [])
        if isinstance(qa_rows, list):
            for row in qa_rows:
                if not isinstance(row, dict):
                    continue
                if bool(row.get("passed", False)):
                    continue
                failures.append(row)

        if not failures:
            qa_error = str(qa_result.get("error", "")).strip()
            if qa_error:
                failures.append({"phase": "qa-eval", "error": qa_error, "passed": False})

        tickets: list[DemotionTicket] = []
        for failure in failures:
            phase_name = str(failure.get("phase", "qa-gate")).strip() or "qa-gate"
            recall = failure.get("recall")
            precision = failure.get("precision")
            target_layer = self._qa_phase_target_layer(phase_name)
            details: list[str] = [f"QA phase '{phase_name}' failed"]
            if recall is not None:
                details.append(f"recall={recall}")
            if precision is not None:
                details.append(f"precision={precision}")
            if failure.get("error"):
                details.append(f"error={failure['error']}")
            tickets.append(
                DemotionTicket(
                    run_id=self.manager.run_id,
                    source="ALGORITHMIC_GATE" if target_layer == "L1" else "ARCH_GATE",
                    gate=f"QA::{phase_name}",
                    target_layer=target_layer,
                    origin_layer="L3",
                    hop_trace=["L3", target_layer],
                    severity="BLOCKER",
                    diagnosis=", ".join(details),
                    failing_files=[f"qa/{phase_name}.txt"],
                    evidence_refs=[evidence_ref],
                )
            )
        return tickets

    def _run_qa_mode(self, *, max_rounds: int = 3) -> dict[str, Any]:
        """Run QA as demotion-driven rounds with PromotionLoop rework."""
        from spec_manager.orchestration.demotion import DemotionManager

        rounds: list[dict[str, Any]] = []
        final_qa: dict[str, Any] = {}
        final_gate: dict[str, Any] = {
            "passed": False,
            "enforcement": self.qa_enforcement,
            "error": "QA mode did not run",
            "pass_rate": 0.0,
        }
        total_tickets = 0
        total_applied = 0
        stuck = False

        demotion_manager = DemotionManager(
            workspace_root=self.manager.workspace_path,
            run_id=self.manager.run_id,
        )

        for round_num in range(1, max_rounds + 1):
            qa_result = self.qa()
            qa_gate = self._evaluate_qa_gate(qa_result)
            qa_report_name = f"qa_round_{round_num}.json"
            self._write_run_report(qa_report_name, qa_result)
            qa_report_ref = self._run_report_relpath(qa_report_name)

            round_payload: dict[str, Any] = {
                "round": round_num,
                "qa": qa_result,
                "qa_gate": qa_gate,
                "qa_report_path": qa_report_ref,
                "demotion_tickets": 0,
                "demotion_tickets_applied": 0,
                "rework": {},
            }

            final_qa = qa_result
            final_gate = qa_gate

            if qa_gate.get("passed", False):
                rounds.append(round_payload)
                break

            tickets = self._qa_failures_to_tickets(qa_result, evidence_ref=qa_report_ref)
            if not tickets:
                round_payload["error"] = "QA failed but no demotion tickets were generated"
                rounds.append(round_payload)
                stuck = True
                break

            ticket_rows: list[dict[str, Any]] = []
            affected_layers: set[Layer] = set()
            for ticket in tickets:
                file_hint = ticket.failing_files[0] if ticket.failing_files else ""
                apply_result = demotion_manager.apply(
                    ticket,
                    slice_root=self._resolve_demotion_slice_root(file_hint),
                )
                ticket_rows.append({"ticket": ticket.to_dict(), "apply_result": apply_result})
                target_layer = str(ticket.target_layer).strip().lower()
                if target_layer in {"l1", "l2", "l3"}:
                    affected_layers.add(cast("Layer", target_layer))

            total_tickets += len(ticket_rows)
            total_applied += sum(
                1
                for row in ticket_rows
                if bool((row.get("apply_result") or {}).get("applied", False))
            )
            round_payload["demotion_tickets"] = len(ticket_rows)
            round_payload["demotion_tickets_applied"] = sum(
                1
                for row in ticket_rows
                if bool((row.get("apply_result") or {}).get("applied", False))
            )

            tickets_report_name = f"qa_demotion_tickets_round_{round_num}.json"
            self._write_run_report(tickets_report_name, ticket_rows)
            round_payload["qa_demotion_tickets_path"] = self._run_report_relpath(
                tickets_report_name
            )

            for layer in sorted(affected_layers):
                run_mode = _LAYER_LIFECYCLE_MODE.get(layer, "build")
                round_payload["rework"][layer] = self._run_slices_at_layer(
                    layer,
                    lifecycle_mode=run_mode,
                )

            rounds.append(round_payload)
            if round_num == max_rounds:
                stuck = True

        self._write_run_report("qa_mode_rounds.json", rounds)
        return {
            "qa": final_qa,
            "qa_gate": final_gate,
            "rework_rounds": rounds,
            "demotion_tickets": total_tickets,
            "demotion_tickets_applied": total_applied,
            "stuck": stuck,
            "rounds_path": self._run_report_relpath("qa_mode_rounds.json"),
        }

    def _evaluate_qa_gate(self, qa_result: dict[str, Any]) -> dict[str, Any]:
        """Evaluate QA result using configured hard/soft policy."""
        if not isinstance(qa_result, dict):
            return {
                "passed": False,
                "enforcement": self.qa_enforcement,
                "error": "QA result is not a dict",
                "pass_rate": 0.0,
            }
        pass_rate_raw = qa_result.get("pass_rate", 1.0)
        try:
            pass_rate = float(pass_rate_raw)
        except (TypeError, ValueError):
            pass_rate = 0.0
        has_error = bool(str(qa_result.get("error", "")).strip())
        threshold_ok = pass_rate >= self.qa_min_pass_rate
        enforced_pass = not has_error and threshold_ok
        return {
            "passed": enforced_pass if self.qa_enforcement == "hard" else True,
            "enforcement": self.qa_enforcement,
            "pass_rate": pass_rate,
            "min_pass_rate": self.qa_min_pass_rate,
            "qa_error": qa_result.get("error", ""),
            "enforced_pass": enforced_pass,
        }

    @staticmethod
    def _layer_slice_rows(layer_result: dict[str, Any]) -> list[dict[str, Any]]:
        slices_data = layer_result.get("slices", {})
        if isinstance(slices_data, dict):
            rows = slices_data.get("slices", [])
            return rows if isinstance(rows, list) else []
        return slices_data if isinstance(slices_data, list) else []

    def _count_pending_demotions_for_layer(self, layer: Layer) -> int:
        """Count unresolved demotion tickets targeting a specific layer."""
        tickets_dir = (
            self.manager.workspace_path
            / ".pdd_runs"
            / self.manager.run_id
            / "demotions"
            / "tickets"
        )
        if not tickets_dir.exists():
            return 0
        target = layer.upper()
        pending = 0
        for ticket_path in sorted(tickets_dir.glob("*.json")):
            try:
                payload = json.loads(ticket_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            ticket = payload.get("ticket", payload)
            if not isinstance(ticket, dict):
                continue
            if str(ticket.get("target_layer", "")).strip().upper() != target:
                continue
            if str(ticket.get("apply_status", "")).strip().upper() != "APPLIED":
                pending += 1
        return pending

    def _evaluate_layer_termination(
        self, layer: Layer, layer_result: dict[str, Any]
    ) -> dict[str, Any]:
        """Evaluate SEC-039 layer-complete conditions."""
        rows = self._layer_slice_rows(layer_result)
        non_terminal = [
            row.get("slice_id", "?")
            for row in rows
            if str(row.get("status", "")).strip().upper() not in _TERMINAL_SLICE_STATUSES
        ]
        all_slices_terminal = len(non_terminal) == 0

        layer_clean = True
        if self.worktree_manager is not None:
            layer_clean = bool(self.worktree_manager.is_layer_clean(layer))

        pending_demotions = self._count_pending_demotions_for_layer(layer)
        no_pending_demotions = pending_demotions == 0

        exit_refinement = layer_result.get("exit_refinement", {})
        exit_demotions = 0
        exit_error = False
        if isinstance(exit_refinement, dict):
            raw_demotions = exit_refinement.get("demotion_tickets", 0)
            try:
                exit_demotions = int(raw_demotions)
            except (TypeError, ValueError):
                exit_demotions = 0
            exit_error = bool(str(exit_refinement.get("error", "")).strip())
        exit_refinement_clean = exit_demotions <= 0 and not exit_error

        passed = (
            all_slices_terminal and layer_clean and no_pending_demotions and exit_refinement_clean
        )
        checks = {
            "passed": passed,
            "all_slices_terminal": all_slices_terminal,
            "non_terminal_slices": non_terminal,
            "layer_clean": layer_clean,
            "pending_demotions": pending_demotions,
            "exit_refinement_clean": exit_refinement_clean,
            "exit_refinement_demotions": exit_demotions,
            "exit_refinement_error": exit_error,
        }
        if not passed:
            logger.warning("Layer %s termination checks failed: %s", layer, checks)
        return checks

    def _run_global_connectivity_check(self, *, source_root: Path | None = None) -> dict[str, Any]:
        """Run global P6 connectivity check over clean-root code."""
        from spec_manager.analysis.adjacency.runner import (
            AdjacencyAnalysisConfig,
            run_adjacency_analysis,
        )

        effective_root = source_root or self.manager.workspace_path
        if source_root is None and self.worktree_manager is not None:
            clean_root = self.worktree_manager._layer_worktrees.get("l3", {}).get("clean")
            if clean_root is not None and Path(clean_root).exists():
                effective_root = clean_root

        try:
            report = run_adjacency_analysis(
                AdjacencyAnalysisConfig(source_dirs=[effective_root], spec_dirs=[effective_root])
            )
            disconnected = len(report.disconnected_warnings or [])
            return {
                "passed": disconnected == 0 and report.total_nodes > 0,
                "total_nodes": report.total_nodes,
                "total_edges": report.total_edges,
                "num_components": report.num_components,
                "disconnected_warnings": list(report.disconnected_warnings or []),
                "source_root": str(effective_root),
            }
        except Exception as exc:
            logger.warning("Global connectivity check failed: %s", exc, exc_info=True)
            return {"passed": False, "error": str(exc), "source_root": str(effective_root)}

    def _run_global_lineage_check(self, *, source_root: Path | None = None) -> dict[str, Any]:
        """Run global P7 lineage completeness check over clean-root code."""
        from spec_manager.projection.lineage.builder import (
            AtomDefinition,
            LineageBuilder,
            import_records_from_pin_registry,
        )
        from spec_manager.schemas.pin_functions import PinFunctionRegistry

        effective_root = source_root or self.manager.workspace_path
        if source_root is None and self.worktree_manager is not None:
            clean_root = self.worktree_manager._layer_worktrees.get("l3", {}).get("clean")
            if clean_root is not None and Path(clean_root).exists():
                effective_root = clean_root

        try:
            import_records = []
            registry_path = effective_root / ".spec" / "pin_registry.json"
            if registry_path.exists():
                try:
                    pin_registry = PinFunctionRegistry.model_validate_json(
                        registry_path.read_text(encoding="utf-8")
                    )
                    import_records = import_records_from_pin_registry(pin_registry)
                except Exception as exc:
                    logger.warning(
                        "Failed to load pin registry for global lineage check: %s",
                        exc,
                        exc_info=True,
                    )
            atom_defs: list[AtomDefinition] = []
            branch_manager = getattr(self.manager, "branches", None)
            if branch_manager is not None:
                list_atoms = getattr(branch_manager, "list_atoms", None)
                if callable(list_atoms):
                    for atom in list_atoms():
                        atom_defs.append(
                            AtomDefinition(
                                atom_id=getattr(atom, "atom_id", ""),
                                function_name=getattr(atom, "function_name", ""),
                                file_path=getattr(atom, "file_path", ""),
                                module_path="",
                                signature_hash=(
                                    getattr(atom, "signature_hash", "")
                                    or getattr(atom, "content_hash", "")
                                ),
                            )
                        )
            if not atom_defs:
                return {
                    "passed": False,
                    "error": "No atoms available for lineage completeness check",
                    "source_root": str(effective_root),
                }
            lineage_builder = LineageBuilder(import_records=import_records, atoms=atom_defs)
            lineage_table = lineage_builder.build_lineage()
            known_atom_ids = {a.atom_id for a in atom_defs}
            orphan_atoms = lineage_table.find_orphan_atoms(known_atom_ids)
            return {
                "passed": len(orphan_atoms) == 0,
                "import_edges": len(import_records),
                "lineage_edges": len(lineage_table.edges),
                "known_atoms": len(known_atom_ids),
                "orphan_atoms": len(orphan_atoms),
                "orphan_atom_ids": sorted(orphan_atoms)[:50],
                "source_root": str(effective_root),
            }
        except Exception as exc:
            logger.warning("Global lineage check failed: %s", exc, exc_info=True)
            return {"passed": False, "error": str(exc), "source_root": str(effective_root)}

    def _run_clean_root_full_tests(self, *, source_root: Path | None = None) -> dict[str, Any]:
        """Run clean-root full test suite as a global termination gate."""
        from spec_manager.core.testing.registry import TestRunnerRegistry

        root = source_root or self.manager.workspace_path
        if source_root is None and self.worktree_manager is not None:
            clean_root = self.worktree_manager._layer_worktrees.get("l3", {}).get("clean")
            if clean_root is not None and Path(clean_root).exists():
                root = clean_root
        try:
            runner = TestRunnerRegistry().pick(root=root)
            result = runner.run(root=root, scope="FULL")
            return {
                "passed": bool(getattr(result, "passed", False)),
                "runner_id": getattr(result, "runner_id", ""),
                "command": list(getattr(result, "command", []) or []),
                "failed_tests": int(getattr(result, "failed_tests", 0)),
                "source_root": str(root),
            }
        except Exception as exc:
            logger.warning("Clean-root full suite failed: %s", exc, exc_info=True)
            return {"passed": False, "error": str(exc), "source_root": str(root)}

    def _run_l1_l2_activation_verify(self) -> dict[str, Any]:
        """Run global verify checkpoint before activating L2."""
        source_root = self.manager.workspace_path
        l1_clean_root = self._resolve_layer_worktree("l1", "clean")
        if l1_clean_root is not None and l1_clean_root.exists():
            source_root = l1_clean_root
        else:
            l2_clean_root = self._resolve_layer_worktree("l2", "clean")
            if l2_clean_root is not None and l2_clean_root.exists():
                source_root = l2_clean_root

        connectivity = self._run_global_connectivity_check(source_root=source_root)
        lineage = self._run_global_lineage_check(source_root=source_root)
        full_tests = self._run_clean_root_full_tests(source_root=source_root)
        checks = {
            "p6_connectivity": bool(connectivity.get("passed", False)),
            "p7_lineage": bool(lineage.get("passed", False)),
            "clean_root_full_tests_pass": bool(full_tests.get("passed", False)),
        }
        return {
            "passed": all(checks.values()),
            "checks": checks,
            "source_root": str(source_root),
            "connectivity": connectivity,
            "lineage": lineage,
            "clean_root_full_tests": full_tests,
        }

    def _ci_receipts_pass(self) -> dict[str, Any]:
        """Validate CI batch receipts for PASS status."""
        if self.worktree_manager is None:
            return {
                "passed": True,
                "receipt_count": 0,
                "note": "Worktree manager unavailable; CI receipts not required",
            }
        run_ci_dir = self.manager.workspace_path / ".pdd_runs" / self.manager.run_id / "ci"
        if not run_ci_dir.exists():
            return {"passed": False, "error": "CI receipts directory missing", "receipt_count": 0}

        receipt_files = sorted(run_ci_dir.glob("*/batches/*.json"))
        if not receipt_files:
            return {"passed": False, "error": "No CI receipts found", "receipt_count": 0}

        failing_receipts: list[str] = []
        for receipt_path in receipt_files:
            try:
                payload = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                failing_receipts.append(str(receipt_path))
                continue
            demotions = int(payload.get("demotions", 0) or 0)
            main_updated = bool(payload.get("main_updated", True))
            if demotions > 0 or not main_updated:
                failing_receipts.append(str(receipt_path))
        return {
            "passed": len(failing_receipts) == 0,
            "receipt_count": len(receipt_files),
            "failing_receipts": failing_receipts[:20],
        }

    def _evaluate_global_termination(self, results: dict[str, Any]) -> dict[str, Any]:
        """Evaluate SEC-039 global termination preconditions."""
        has_strict_layer_data = all(
            isinstance((results.get(layer, {}) or {}).get("layer_termination"), dict)
            and bool((results.get(layer, {}) or {}).get("layer_termination"))
            for layer in ("l1", "l2", "l3")
        )
        layer_checks = {
            layer: (results.get(layer, {}) or {}).get("layer_termination", {})
            for layer in ("l1", "l2", "l3")
        }
        all_slices_terminal = all(
            bool(check.get("all_slices_terminal", True)) for check in layer_checks.values()
        )
        l3_clean = bool((layer_checks.get("l3") or {}).get("layer_clean", True))
        if has_strict_layer_data:
            ci_receipts = self._ci_receipts_pass()
            connectivity = self._run_global_connectivity_check()
            lineage = self._run_global_lineage_check()
            full_tests = self._run_clean_root_full_tests()
        else:
            ci_receipts = {"passed": True, "note": "Strict layer termination metadata unavailable"}
            connectivity = {
                "passed": True,
                "note": "Strict layer termination metadata unavailable",
            }
            lineage = {
                "passed": True,
                "note": "Strict layer termination metadata unavailable",
            }
            full_tests = {
                "passed": True,
                "note": "Strict layer termination metadata unavailable",
            }
        qa_gate = self._evaluate_qa_gate(results.get("qa", {}))
        checks = {
            "all_slices_terminal": all_slices_terminal,
            "p6_connectivity": bool(connectivity.get("passed", False)),
            "p7_lineage": bool(lineage.get("passed", False)),
            "l3_clean": l3_clean,
            "ci_receipts_pass": bool(ci_receipts.get("passed", False)),
            "clean_root_full_tests_pass": bool(full_tests.get("passed", False)),
            "qa_gate_pass": bool(qa_gate.get("passed", False)),
        }
        passed = all(checks.values())
        return {
            "passed": passed,
            "checks": checks,
            "layer_termination": layer_checks,
            "connectivity": connectivity,
            "lineage": lineage,
            "clean_root_full_tests": full_tests,
            "ci_receipts": ci_receipts,
            "qa_gate": qa_gate,
        }

    def _perform_release_merge_and_tag(self) -> dict[str, Any]:
        """Perform merge-to-main and release tag creation."""
        vcs = self.worktree_manager.vcs if self.worktree_manager else None
        if vcs is None:
            try:
                from spec_manager.vcs.operations import GitVcs

                vcs = GitVcs(repo_root=self.manager.workspace_path)
            except Exception as exc:
                return {"merged": False, "tagged": False, "error": str(exc)}

        source_branch = ""
        target_branch = vcs.get_current_branch(self.manager.workspace_path) or "HEAD"
        release_branch = f"pdd/{self.manager.run_id}/final"
        release_target_sha = ""

        merged = False
        release_branch_created = False
        merge_error = ""
        if self.worktree_manager is not None and target_branch == "main":
            source_branch = self.worktree_manager.layer_branch("l3", "clean")
            merge_result = vcs.merge(
                self.manager.workspace_path,
                source_branch,
                ff_only=True,
            )
            if isinstance(merge_result, tuple) and len(merge_result) == 2:
                merged, merge_error = bool(merge_result[0]), str(merge_result[1])
            elif isinstance(merge_result, bool):
                merged, merge_error = merge_result, ""
            else:
                merged, merge_error = True, ""
            if merged:
                release_target_sha = vcs.rev_parse("HEAD") or ""
        else:
            if self.worktree_manager is not None:
                source_branch = self.worktree_manager.layer_branch("l3", "clean")
            else:
                source_branch = vcs.get_current_branch(self.manager.workspace_path) or "HEAD"
            release_target_sha = vcs.rev_parse(source_branch) or vcs.rev_parse("HEAD") or ""
            if not release_target_sha:
                merge_error = (
                    f"Unable to resolve release SHA from source branch '{source_branch}'"
                    if source_branch
                    else "Unable to resolve release SHA from HEAD"
                )
            else:
                branch_result = vcs.update_ref(f"refs/heads/{release_branch}", release_target_sha)
                if isinstance(branch_result, tuple) and len(branch_result) == 2:
                    release_branch_created, branch_err = (
                        bool(branch_result[0]),
                        str(branch_result[1]),
                    )
                elif isinstance(branch_result, bool):
                    release_branch_created, branch_err = branch_result, ""
                else:
                    release_branch_created, branch_err = True, ""
                if not release_branch_created:
                    merge_error = (
                        branch_err or f"Failed to create release branch '{release_branch}'"
                    )

        tag_name = f"pdd/{self.manager.run_id}/final"
        tag_ok = False
        tag_error = ""
        if merged or release_branch_created:
            tag_target = release_target_sha or (vcs.rev_parse("HEAD") or "")
            if tag_target:
                existing_tag = vcs.rev_parse(f"refs/tags/{tag_name}")
                if existing_tag:
                    if existing_tag == tag_target:
                        tag_ok = True
                    else:
                        tag_error = (
                            f"Tag '{tag_name}' exists at {existing_tag}, expected {tag_target}"
                        )
                else:
                    tag_result = vcs.create_tag(
                        tag_name,
                        tag_target,
                        message=f"PDD final approval for run {self.manager.run_id}",
                    )
                    if isinstance(tag_result, tuple) and len(tag_result) == 2:
                        tag_ok, tag_error = bool(tag_result[0]), str(tag_result[1])
                    elif isinstance(tag_result, bool):
                        tag_ok, tag_error = tag_result, ""
                    else:
                        tag_ok, tag_error = True, ""
            else:
                tag_error = "Unable to resolve release target SHA for tag creation"

        return {
            "merged": merged,
            "merge_error": merge_error,
            "source_branch": source_branch,
            "target_branch": target_branch,
            "release_branch": release_branch,
            "release_branch_created": release_branch_created,
            "tagged": tag_ok,
            "tag_name": tag_name,
            "tag_error": tag_error,
        }

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
        lifecycle_mode = _LAYER_LIFECYCLE_MODE.get(layer, "build")
        results["lifecycle_mode"] = lifecycle_mode

        refinement_method = getattr(self, _LAYER_REFINEMENT[layer])

        # Entry refinement (typed per layer)
        known_ticket_paths = self._snapshot_demotion_ticket_paths()
        results["entry_refinement"] = refinement_method()
        entry_tickets = self._load_new_demotion_tickets(known_ticket_paths)
        lower_targets = self._lower_layer_demotion_targets(
            current_layer=layer,
            tickets=entry_tickets,
        )
        if lower_targets:
            results["demotion_pause"] = {
                "paused": True,
                "from_layer": layer,
                "target_layers": lower_targets,
                "ticket_count": len(entry_tickets),
                "reason": (
                    f"Entry refinement for {layer.upper()} emitted demotions to lower layer(s): "
                    f"{', '.join(target.upper() for target in lower_targets)}"
                ),
            }
            results["slices"] = {
                "layer": layer,
                "lifecycle_mode": lifecycle_mode,
                "slices": [],
                "all_complete": False,
                "paused": True,
            }
            results["exit_refinement"] = {}
            results["layer_termination"] = {
                "passed": False,
                "all_slices_terminal": False,
                "non_terminal_slices": ["__demotion_pause__"],
                "layer_clean": False,
                "pending_demotions": self._count_pending_demotions_for_layer(layer),
                "exit_refinement_clean": False,
                "exit_refinement_demotions": len(entry_tickets),
                "exit_refinement_error": True,
                "demotion_pause": True,
            }
            results["all_complete"] = False
            logger.info(
                "Layer %s paused before slice work; demotions target lower layer(s): %s",
                layer.upper(),
                ", ".join(target.upper() for target in lower_targets),
            )
            return results

        # Per-slice work via PromotionLoop
        results["slices"] = self._run_slices_at_layer(layer, lifecycle_mode=lifecycle_mode)

        # Exit refinement (typed per layer)
        results["exit_refinement"] = refinement_method()

        # Layer termination predicate: all terminal slices, clean lane state,
        # no pending demotions, and clean exit refinement.
        termination = self._evaluate_layer_termination(layer, results)
        results["layer_termination"] = termination
        results["all_complete"] = bool(termination.get("all_slices_terminal", False))

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
            known_ticket_paths = self._snapshot_demotion_ticket_paths()
            refinement_result = refinement_method()
            raw_demotions = refinement_result.get("demotion_tickets", 0)
            try:
                demotions = int(raw_demotions)
            except (TypeError, ValueError):
                demotions = 0
            round_tickets = self._load_new_demotion_tickets(known_ticket_paths)
            focus_targets_by_layer = self._collect_transition_rework_focus_targets_by_layer(
                from_layer=from_layer,
                round_tickets=round_tickets,
            )

            round_result: dict[str, Any] = {
                "round": round_num,
                "refinement": refinement_result,
                "demotions": demotions,
                "rework_ticket_count": len(round_tickets),
                "focus_targets": focus_targets_by_layer.get(from_layer, {}),
                "focus_targets_by_layer": focus_targets_by_layer,
                "rework_runs": [],
            }

            if demotions <= 0:
                rework_rounds.append(round_result)
                break

            rework_layers = sorted(focus_targets_by_layer, key=lambda layer: _LAYER_RANK[layer])
            if not rework_layers:
                rework_layers = [from_layer]
            if from_layer not in rework_layers and any(
                _LAYER_RANK[layer] < _LAYER_RANK[from_layer] for layer in rework_layers
            ):
                rework_layers.append(from_layer)
            round_result["rework_layers"] = rework_layers

            logger.info(
                "Transition %s→%s round %d/%d: %d demotions, re-running slices at layer(s): %s",
                from_layer,
                to_layer,
                round_num,
                max_rounds,
                demotions,
                ", ".join(layer.upper() for layer in rework_layers),
            )

            round_failed = False
            for rework_layer in rework_layers:
                layer_focus_targets = focus_targets_by_layer.get(rework_layer, {})
                rework_mode = _LAYER_LIFECYCLE_MODE.get(rework_layer, "build")
                target_slice_ids = sorted(layer_focus_targets)
                layer_round: dict[str, Any] = {
                    "layer": rework_layer,
                    "focus_targets": layer_focus_targets,
                }

                if not target_slice_ids:
                    logger.warning(
                        "Transition %s→%s round %d/%d: demotions for %s emitted but no owning "
                        "slice targets were identified; falling back to full-layer rework",
                        from_layer,
                        to_layer,
                        round_num,
                        max_rounds,
                        rework_layer.upper(),
                    )
                    layer_round["rework_scope"] = "full_layer_fallback_no_targets"
                    layer_round["rework"] = self._run_slices_at_layer(
                        rework_layer,
                        lifecycle_mode=rework_mode,
                    )
                else:
                    layer_round["rework_scope"] = "focused_slices"
                    layer_round["rework"] = self._run_slices_at_layer(
                        rework_layer,
                        lifecycle_mode=rework_mode,
                        target_slice_ids=target_slice_ids,
                        slice_focus_targets=layer_focus_targets,
                    )

                rework_result = layer_round["rework"]
                if not isinstance(rework_result, dict):
                    transition_stuck = True
                    round_failed = True
                    round_result["error"] = "Transition rework did not produce a structured result"
                    round_result["failed_layer"] = rework_layer
                    round_result["rework_runs"].append(layer_round)
                    break

                layer_round["rework_ci_passed"] = self._ci_ticks_passed(rework_result)
                if not bool(layer_round["rework_ci_passed"]):
                    transition_stuck = True
                    round_failed = True
                    round_result["error"] = (
                        f"Transition {from_layer}→{to_layer} rework round {round_num} "
                        f"failed CI ticks at {rework_layer.upper()}"
                    )
                    round_result["failed_layer"] = rework_layer
                    round_result["rework_runs"].append(layer_round)
                    logger.warning("%s", round_result["error"])
                    break

                rework_layer_clean = True
                if self.worktree_manager is not None:
                    rework_layer_clean = bool(self.worktree_manager.is_layer_clean(rework_layer))
                layer_round["rework_layer_clean"] = rework_layer_clean
                if not rework_layer_clean:
                    transition_stuck = True
                    round_failed = True
                    round_result["error"] = (
                        f"Transition {from_layer}→{to_layer} rework round {round_num} "
                        f"did not restore {rework_layer.upper()} to a fully clean state"
                    )
                    round_result["failed_layer"] = rework_layer
                    round_result["rework_runs"].append(layer_round)
                    logger.warning("%s", round_result["error"])
                    break

                if self.worktree_manager is not None:
                    repropagation = self._propagate_clean_to_next_layer_result(rework_layer)
                    layer_round["repropagation"] = repropagation
                    if not bool(repropagation.get("success", False)):
                        transition_stuck = True
                        round_failed = True
                        round_result["error"] = (
                            f"Transition {from_layer}→{to_layer} rework round {round_num} "
                            f"failed to re-propagate {rework_layer.upper()} clean"
                        )
                        round_result["failed_layer"] = rework_layer
                        round_result["rework_runs"].append(layer_round)
                        logger.warning(
                            "%s: %s",
                            round_result["error"],
                            repropagation.get("error", ""),
                        )
                        break

                round_result["rework_runs"].append(layer_round)

            from_layer_run = next(
                (
                    run
                    for run in round_result.get("rework_runs", [])
                    if isinstance(run, dict) and run.get("layer") == from_layer
                ),
                None,
            )
            if isinstance(from_layer_run, dict):
                round_result["rework_scope"] = from_layer_run.get("rework_scope", "")
                round_result["rework"] = from_layer_run.get("rework", {})
                round_result["rework_layer_clean"] = bool(
                    from_layer_run.get("rework_layer_clean", True)
                )
                if "repropagation" in from_layer_run:
                    round_result["repropagation"] = from_layer_run["repropagation"]
            elif round_result.get("rework_runs"):
                last_run = round_result["rework_runs"][-1]
                if isinstance(last_run, dict):
                    round_result["rework_scope"] = last_run.get("rework_scope", "")
                    round_result["rework"] = last_run.get("rework", {})
                    round_result["rework_layer_clean"] = bool(
                        last_run.get("rework_layer_clean", True)
                    )
                    if "repropagation" in last_run:
                        round_result["repropagation"] = last_run["repropagation"]

            round_result["rework_ci_passed"] = all(
                bool(run.get("rework_ci_passed", False))
                for run in round_result.get("rework_runs", [])
                if isinstance(run, dict)
            )
            if round_failed:
                rework_rounds.append(round_result)
                break
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
            results["governance_blocked"] = True
            return results

        # Transition governance gate: no open governance FAIL + required artifacts present
        governance = self._run_governance_check(
            f"transition_{from_layer}_{to_layer}",
            check_artifacts=True,
        )
        results["governance"] = governance
        if not governance.get("passed", True):
            logger.error(
                "Transition %s→%s governance gate failed: %s",
                from_layer,
                to_layer,
                governance.get("error", ""),
            )
            transition_gate = f"TRANSITION::{from_layer.upper()}->{to_layer.upper()}::GOVERNANCE"
            transition_ticket = self._emit_governance_failure_ticket(
                gate=transition_gate,
                layer=str(from_layer).upper(),
                diagnosis=str(
                    governance.get("error")
                    or f"Transition {from_layer}→{to_layer} blocked by governance gate"
                ),
                evidence_refs=[],
            )
            results["governance_ticket"] = transition_ticket
            results["governance_blocked"] = True
            results["error"] = (
                f"Transition {from_layer}→{to_layer} blocked by governance gate: "
                f"{governance.get('error', '')}"
            )
            return results

        # Propagate clean → next layer's dirty
        if self.worktree_manager:
            propagation = self._propagate_clean_to_next_layer_result(from_layer)
            if not bool(propagation.get("success", False)):
                merge_error = str(propagation.get("merge_error") or "merge propagation failed")
                rebase_error = str(propagation.get("rebase_error") or "rebase fallback failed")
                combined_conflicts = propagation.get("conflict_files", [])
                if not isinstance(combined_conflicts, list):
                    combined_conflicts = []
                combined_conflicts = [
                    self._normalize_conflict_path(path)
                    for path in combined_conflicts
                    if self._normalize_conflict_path(path)
                ]
                conflict_slice_ids = self._infer_conflict_slice_ids(to_layer, combined_conflicts)

                conflict_report_name = (
                    f"transition_{from_layer}_{to_layer}_propagation_conflict.json"
                )
                conflict_report_payload = {
                    "from_layer": from_layer,
                    "to_layer": to_layer,
                    "strategy": str(propagation.get("strategy", "merge_then_rebase_fallback")),
                    "merge_error": merge_error,
                    "rebase_error": rebase_error,
                    "conflict_files": combined_conflicts,
                    "affected_slices": conflict_slice_ids,
                }
                scope_assessment = self._assess_transition_conflict_scope(
                    to_layer=to_layer,
                    conflict_files=combined_conflicts,
                    affected_slices=conflict_slice_ids,
                )
                conflict_report_payload["scope_assessment"] = scope_assessment
                self._write_run_report(conflict_report_name, conflict_report_payload)
                conflict_report_ref = self._run_report_relpath(conflict_report_name)
                propagation["scope_assessment"] = scope_assessment

                investigator_attempted = False
                investigator_report_ref = ""
                resolved_by_investigator = False
                retry_payload: dict[str, Any] = {}

                if bool(scope_assessment.get("llm_merge_allowed", False)):
                    investigator_attempted = True

                    def verify_propagation_recovery(
                        _: int,
                        __: dict[str, Any],
                    ) -> tuple[bool, dict[str, Any]]:
                        retry_propagation = self._propagate_clean_to_next_layer_result(from_layer)
                        return bool(retry_propagation.get("success", False)), {
                            "retry_propagation": retry_propagation
                        }

                    investigator_refs = [
                        f"merge_error:{merge_error}",
                        f"rebase_error:{rebase_error}",
                        *[f"conflict_file:{path}" for path in combined_conflicts[:12]],
                    ]
                    investigator_report, investigator_report_ref = (
                        self._run_transition_investigator(
                            layer=to_layer,
                            scope_id=f"transition_{from_layer}_{to_layer}_propagation_conflict",
                            failure_refs=investigator_refs,
                            failure_evidence=conflict_report_payload,
                            investigator_budget=self.transition_investigator_budget,
                            verify_callback=verify_propagation_recovery,
                        )
                    )
                    propagation["investigator_report_path"] = investigator_report_ref
                    resolved_by_investigator = bool(investigator_report.get("fixed", False))
                    if resolved_by_investigator:
                        retry_payload = investigator_report.get("verification", {})
                        retry_propagation = (
                            retry_payload.get("retry_propagation", {})
                            if isinstance(retry_payload, dict)
                            else {}
                        )
                        propagation.update(
                            {
                                "success": bool(retry_propagation.get("success", False)),
                                "error": str(retry_propagation.get("error", "")),
                                "strategy": "investigator_recovery",
                                "merge_sha": str(retry_propagation.get("merge_sha", "")).strip(),
                                "conflict_files": list(retry_propagation.get("conflict_files", []))
                                if isinstance(retry_propagation.get("conflict_files", []), list)
                                else [],
                            }
                        )
                        results["propagation_recovery"] = {
                            "fixed": True,
                            "investigator_report_path": investigator_report_ref,
                            "verification": retry_payload,
                        }

                if not resolved_by_investigator:
                    demotion_summary = self._emit_transition_conflict_demotions(
                        from_layer=from_layer,
                        to_layer=to_layer,
                        conflict_files=combined_conflicts,
                        merge_error=merge_error,
                        rebase_error=rebase_error,
                        evidence_ref=conflict_report_ref,
                        investigator_report_ref=investigator_report_ref,
                    )
                    propagation["demotion_tickets"] = demotion_summary.get("demotion_tickets", 0)
                    propagation["affected_slices"] = demotion_summary.get("affected_slices", [])

                    results["propagation_conflict"] = {
                        **conflict_report_payload,
                        **demotion_summary,
                        "conflict_report_path": conflict_report_ref,
                        "investigator_report_path": investigator_report_ref,
                        "investigator_attempted": investigator_attempted,
                    }
                    if not investigator_attempted:
                        results["propagation_conflict"]["investigator_skipped_reason"] = (
                            "Conflict scope not limited to non-ambiguous "
                            "wiring_only/refactor_only regions."
                        )
                    results["governance_blocked"] = True
                    results["escalation_required"] = True
                    results["error"] = (
                        f"Transition {from_layer}→{to_layer} blocked by unresolved propagation "
                        f"conflicts: {propagation['error']}"
                    )

            results["propagation"] = propagation

            # Downstream readiness CI: smoke + baseline on the new dirty worktree
            if bool(propagation.get("success", False)):
                readiness = self._run_readiness_ci(to_layer)
                results["readiness_ci"] = readiness
                if not readiness.get("passed", True):
                    readiness_error = str(
                        readiness.get("error") or "Downstream readiness CI failed"
                    )
                    readiness_refs = [f"readiness_error:{readiness_error}"]
                    for row in readiness.get("tiers", []):
                        if not isinstance(row, dict):
                            continue
                        if bool(row.get("passed", False)):
                            continue
                        tier = row.get("tier")
                        failure_detail = str(row.get("error") or row.get("output") or "").strip()
                        readiness_refs.append(
                            f"tier={tier}:{failure_detail[:500]}"
                            if failure_detail
                            else f"tier={tier}"
                        )

                    def verify_readiness_recovery(
                        _: int,
                        __: dict[str, Any],
                    ) -> tuple[bool, dict[str, Any]]:
                        retry = self._run_readiness_ci(to_layer)
                        return bool(retry.get("passed", False)), {"readiness_retry": retry}

                    readiness_report, readiness_report_ref = self._run_transition_investigator(
                        layer=to_layer,
                        scope_id=f"transition_{from_layer}_{to_layer}_readiness_ci",
                        failure_refs=readiness_refs,
                        failure_evidence={
                            "from_layer": from_layer,
                            "to_layer": to_layer,
                            "readiness_ci": readiness,
                        },
                        investigator_budget=self.readiness_investigator_budget,
                        verify_callback=verify_readiness_recovery,
                    )
                    results["readiness_investigator"] = {
                        "fixed": bool(readiness_report.get("fixed", False)),
                        "investigator_report_path": readiness_report_ref,
                        "verification": readiness_report.get("verification", {}),
                    }

                    if bool(readiness_report.get("fixed", False)):
                        verification = readiness_report.get("verification", {})
                        retry_payload = (
                            verification.get("readiness_retry", {})
                            if isinstance(verification, dict)
                            else {}
                        )
                        if isinstance(retry_payload, dict) and retry_payload:
                            results["readiness_ci"] = retry_payload
                    else:
                        results["readiness_blocked"] = True
                        results["governance_blocked"] = True
                        results["escalation_required"] = True
                        results["error"] = (
                            f"Transition {from_layer}→{to_layer} blocked by downstream "
                            f"readiness CI: {readiness_error}"
                        )
                        logger.warning(
                            "Downstream readiness CI failed for %s dirty — "
                            "transition %s→%s blocked",
                            to_layer,
                            from_layer,
                            to_layer,
                        )

        return results

    def _demotion_tickets_dir(self) -> Path:
        """Return run-scoped demotion ticket artifact directory."""
        return (
            self.manager.workspace_path
            / ".pdd_runs"
            / self.manager.run_id
            / "demotions"
            / "tickets"
        )

    def _snapshot_demotion_ticket_paths(self) -> set[str]:
        """Capture current demotion ticket artifact paths."""
        tickets_dir = self._demotion_tickets_dir()
        if not tickets_dir.exists():
            return set()
        return {str(path) for path in tickets_dir.glob("*.json")}

    def _load_new_demotion_tickets(self, known_ticket_paths: set[str]) -> list[dict[str, Any]]:
        """Load demotion tickets written since *known_ticket_paths* snapshot."""
        tickets_dir = self._demotion_tickets_dir()
        if not tickets_dir.exists():
            return []

        tickets: list[dict[str, Any]] = []
        for ticket_path in sorted(tickets_dir.glob("*.json")):
            if str(ticket_path) in known_ticket_paths:
                continue
            try:
                payload = json.loads(ticket_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            ticket = payload.get("ticket", payload) if isinstance(payload, dict) else None
            if isinstance(ticket, dict):
                tickets.append(ticket)
        return tickets

    @staticmethod
    def _ticket_string_list(value: Any) -> list[str]:
        """Normalize arbitrary payloads into a list of non-empty strings."""
        if not isinstance(value, list):
            return []
        seen: set[str] = set()
        items: list[str] = []
        for raw in value:
            text = str(raw).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            items.append(text)
        return items

    @staticmethod
    def _ticket_target_layer(
        ticket: dict[str, Any],
        *,
        default_layer: Layer | None = None,
    ) -> Layer | None:
        """Return normalized ticket target layer when present."""
        target_layer = str(ticket.get("target_layer", "")).strip().lower()
        if target_layer in _LAYER_RANK:
            return cast("Layer", target_layer)
        return default_layer

    def _ticket_focus_targets(self, ticket: dict[str, Any]) -> dict[str, list[str]]:
        """Extract focus target hints from a demotion ticket payload."""
        location_symbols: list[str] = []
        location = ticket.get("location")
        if isinstance(location, dict):
            symbol = str(location.get("symbol", "")).strip()
            if symbol:
                location_symbols.append(symbol)

        return {
            "failing_files": self._ticket_string_list(ticket.get("failing_files", [])),
            "failing_pins": self._ticket_string_list(ticket.get("failing_pins", [])),
            "failing_atoms": self._ticket_string_list(ticket.get("failing_atoms", [])),
            "location_symbols": location_symbols,
        }

    def _resolve_ticket_slice_ids(
        self,
        *,
        layer: Layer,
        ticket: dict[str, Any],
        available_slice_ids: set[str],
    ) -> list[str]:
        """Resolve owning slice IDs for a transition demotion ticket."""
        resolved: set[str] = set()
        raw_slice_id = str(ticket.get("slice_id", "")).strip()

        if raw_slice_id:
            if raw_slice_id in available_slice_ids:
                resolved.add(raw_slice_id)
            if layer == "l2" and not raw_slice_id.startswith("arch-"):
                arch_slice_id = f"arch-{raw_slice_id}"
                if arch_slice_id in available_slice_ids:
                    resolved.add(arch_slice_id)
            if layer == "l3":
                if raw_slice_id.startswith("cq-") and raw_slice_id in available_slice_ids:
                    resolved.add(raw_slice_id)
                else:
                    for l3_slice_id in self._infer_conflict_slice_ids(layer, [raw_slice_id]):
                        if l3_slice_id in available_slice_ids:
                            resolved.add(l3_slice_id)

        failing_files = self._ticket_string_list(ticket.get("failing_files", []))
        for slice_id in self._infer_conflict_slice_ids(layer, failing_files):
            if slice_id in available_slice_ids:
                resolved.add(slice_id)

        component_id = str(ticket.get("component_id", "")).strip()
        if layer == "l2" and component_id:
            arch_slice_id = f"arch-{component_id}"
            if arch_slice_id in available_slice_ids:
                resolved.add(arch_slice_id)

        if layer == "l1" and raw_slice_id:
            lowered = raw_slice_id.lower()
            for slice_id in available_slice_ids:
                if slice_id.lower() in lowered or lowered in slice_id.lower():
                    resolved.add(slice_id)

        return sorted(resolved)

    def _collect_transition_rework_focus_targets_by_layer(
        self,
        *,
        from_layer: Layer,
        round_tickets: list[dict[str, Any]],
    ) -> dict[Layer, dict[str, dict[str, list[str]]]]:
        """Group transition rework focus targets by ticket target layer."""
        tickets_by_layer: dict[Layer, list[dict[str, Any]]] = {}
        from_rank = _LAYER_RANK[from_layer]
        for ticket in round_tickets:
            target_layer = self._ticket_target_layer(ticket, default_layer=from_layer)
            if target_layer is None:
                continue
            if _LAYER_RANK[target_layer] > from_rank:
                continue
            tickets_by_layer.setdefault(target_layer, []).append(ticket)

        focus_targets: dict[Layer, dict[str, dict[str, list[str]]]] = {}
        for target_layer, layer_tickets in tickets_by_layer.items():
            focus_targets[target_layer] = self._collect_transition_rework_focus_targets(
                layer=target_layer,
                round_tickets=layer_tickets,
            )
        return focus_targets

    def _collect_transition_rework_focus_targets(
        self,
        layer: Layer,
        round_tickets: list[dict[str, Any]],
    ) -> dict[str, dict[str, list[str]]]:
        """Build owning-slice focus targets from transition demotion tickets."""
        available_slice_ids = {
            str(getattr(ref, "slice_id", "")).strip()
            for ref in self._discover_slices(layer)
            if str(getattr(ref, "slice_id", "")).strip()
        }
        if not available_slice_ids:
            return {}

        focused: dict[str, dict[str, set[str]]] = {}
        for ticket in round_tickets:
            owner_slice_ids = self._resolve_ticket_slice_ids(
                layer=layer,
                ticket=ticket,
                available_slice_ids=available_slice_ids,
            )
            if not owner_slice_ids:
                continue

            focus_targets = self._ticket_focus_targets(ticket)
            for slice_id in owner_slice_ids:
                bucket = focused.setdefault(
                    slice_id,
                    {
                        "failing_files": set(),
                        "failing_pins": set(),
                        "failing_atoms": set(),
                        "location_symbols": set(),
                    },
                )
                for key in ("failing_files", "failing_pins", "failing_atoms", "location_symbols"):
                    bucket[key].update(focus_targets.get(key, []))

        normalized: dict[str, dict[str, list[str]]] = {}
        for slice_id, targets in focused.items():
            normalized[slice_id] = {
                "failing_files": sorted(targets["failing_files"]),
                "failing_pins": sorted(targets["failing_pins"]),
                "failing_atoms": sorted(targets["failing_atoms"]),
                "location_symbols": sorted(targets["location_symbols"]),
            }
        return normalized

    @staticmethod
    def _normalize_conflict_path(path: str) -> str:
        """Normalize conflict paths for stable matching."""
        normalized = str(path or "").strip().replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized.strip()

    @classmethod
    def _l3_relative_source_path(cls, *, spec_snapshot_dir: Path, file_path: Path) -> str:
        """Return normalized source path relative to the spec snapshot root."""
        try:
            relative_path = file_path.relative_to(spec_snapshot_dir).as_posix()
        except ValueError:
            relative_path = file_path.as_posix()
        return cls._normalize_conflict_path(relative_path)

    @classmethod
    def _l3_slice_id_for_relative_path(cls, relative_path: str) -> str:
        """Build a stable, unique L3 slice ID from a normalized relative file path."""
        normalized = cls._normalize_conflict_path(relative_path)
        slug_source = normalized.replace("/", "__")
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", slug_source).strip("_") or "file"
        fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
        return f"cq-{slug}-{fingerprint}"

    @classmethod
    def _extract_conflict_files_from_errors(cls, *errors: str) -> list[str]:
        """Best-effort conflict file extraction from git merge/rebase errors."""
        patterns = (
            re.compile(r"CONFLICT\s+\([^)]+\):[^\n]* in ([^\n\r]+)"),
            re.compile(r"Merge conflict in ([^\n\r]+)"),
            re.compile(r"both modified:\s*([^\n\r]+)", re.IGNORECASE),
        )
        conflict_files: list[str] = []
        seen: set[str] = set()
        for raw_error in errors:
            error_text = str(raw_error or "")
            if not error_text:
                continue
            for pattern in patterns:
                for match in pattern.findall(error_text):
                    normalized = cls._normalize_conflict_path(str(match))
                    if normalized and normalized not in seen:
                        seen.add(normalized)
                        conflict_files.append(normalized)
        return conflict_files

    def _infer_conflict_slice_ids(self, to_layer: Layer, conflict_files: list[str]) -> list[str]:
        """Map conflict files to downstream slice IDs where possible."""
        normalized_conflicts = [
            self._normalize_conflict_path(path)
            for path in conflict_files
            if self._normalize_conflict_path(path)
        ]
        if not normalized_conflicts:
            return []

        matched: set[str] = set()
        for ref in self._discover_slices(to_layer):
            slice_id = str(getattr(ref, "slice_id", "")).strip()
            if not slice_id:
                continue

            metadata = getattr(ref, "metadata", {})
            metadata_files: list[str] = []
            if isinstance(metadata, dict):
                raw_files = metadata.get("files", [])
                if isinstance(raw_files, list):
                    metadata_files = [
                        self._normalize_conflict_path(str(path))
                        for path in raw_files
                        if self._normalize_conflict_path(str(path))
                    ]

            worktree_path = self._normalize_conflict_path(str(getattr(ref, "worktree_path", "")))
            library_id = str(getattr(ref, "library_id", "")).strip()

            for conflict_path in normalized_conflicts:
                if any(
                    conflict_path == meta_file
                    or conflict_path.endswith(f"/{meta_file}")
                    or meta_file.endswith(f"/{conflict_path}")
                    for meta_file in metadata_files
                ):
                    matched.add(slice_id)
                    break
                if library_id and f"/{library_id}/" in f"/{conflict_path}/":
                    matched.add(slice_id)
                    break
                if worktree_path and (
                    conflict_path.startswith(f"{worktree_path}/")
                    or conflict_path.endswith(f"/{worktree_path}")
                ):
                    matched.add(slice_id)
                    break

        return sorted(matched)

    @staticmethod
    def _classify_transition_conflict_change_type(
        *,
        to_layer: Layer,
        conflict_path: str,
    ) -> str:
        """Classify conflict scope into change-type buckets for recovery gating."""
        normalized = str(conflict_path or "").strip().lower().replace("\\", "/")
        if not normalized:
            return "unknown"

        safe_extensions = (
            ".md",
            ".rst",
            ".txt",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".ini",
            ".cfg",
            ".lock",
        )
        code_extensions = (
            ".py",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".go",
            ".rs",
            ".java",
            ".kt",
            ".c",
            ".cc",
            ".cpp",
            ".h",
            ".hpp",
        )
        wiring_markers = (
            "/wiring/",
            "/topology/",
            "/route/",
            "/routes/",
            "/router/",
            "/handler/",
            "/handlers/",
            "/adapter/",
            "/adapters/",
            "/graph/",
            "/pin/",
            "/pins/",
            "/edge/",
            "/edges/",
            "wiring",
            "topology",
            "manifest",
        )
        refactor_markers = (
            "/refactor/",
            "refactor",
            "/cleanup/",
            "cleanup",
            "/format/",
            "format",
        )

        if normalized.endswith(safe_extensions):
            if to_layer == "l2":
                return "wiring_only"
            if to_layer == "l3":
                return "refactor_only"
            return "unknown"

        if any(marker in normalized for marker in wiring_markers):
            return "wiring_only"
        if any(marker in normalized for marker in refactor_markers):
            return "refactor_only"

        if normalized.endswith(code_extensions):
            return "unknown"

        if to_layer == "l2":
            return "wiring_only"
        if to_layer == "l3":
            return "refactor_only"
        return "unknown"

    def _assess_transition_conflict_scope(
        self,
        *,
        to_layer: Layer,
        conflict_files: list[str],
        affected_slices: list[str],
    ) -> dict[str, Any]:
        """Assess whether unresolved propagation conflicts are safe for LLM merge recovery."""
        normalized_conflicts = [
            self._normalize_conflict_path(path)
            for path in conflict_files
            if self._normalize_conflict_path(path)
        ]
        required_change_types: dict[str, str] = {}
        for path in normalized_conflicts:
            required_change_types[path] = self._classify_transition_conflict_change_type(
                to_layer=to_layer,
                conflict_path=path,
            )
        unknown_files = [
            path for path, change_type in required_change_types.items() if change_type == "unknown"
        ]
        behavior_change_files = [
            path
            for path, change_type in required_change_types.items()
            if change_type == "behavior_change"
        ]
        distinct_types = sorted(set(required_change_types.values()))
        ambiguous = bool(
            behavior_change_files
            or unknown_files
            or not normalized_conflicts
            or (normalized_conflicts and not affected_slices)
        )
        llm_merge_allowed = bool(
            normalized_conflicts
            and affected_slices
            and not ambiguous
            and set(distinct_types).issubset({"wiring_only", "refactor_only"})
        )
        overall_change_type = "mixed"
        if len(distinct_types) == 1:
            overall_change_type = distinct_types[0]
        elif not distinct_types:
            overall_change_type = "unknown"
        return {
            "overall_required_change_type": overall_change_type,
            "required_change_types_by_file": required_change_types,
            "unknown_files": unknown_files,
            "behavior_change_files": behavior_change_files,
            "behavior_ambiguity": ambiguous,
            "llm_merge_allowed": llm_merge_allowed,
        }

    def _emit_transition_conflict_demotions(
        self,
        *,
        from_layer: Layer,
        to_layer: Layer,
        conflict_files: list[str],
        merge_error: str,
        rebase_error: str,
        evidence_ref: str,
        investigator_report_ref: str = "",
    ) -> dict[str, Any]:
        """Emit demotion tickets for unresolved cross-layer propagation conflicts."""
        from spec_manager.orchestration.demotion import DemotionManager, DemotionTicket

        target_layer = cast("Literal['L1', 'L2', 'L3']", to_layer.upper())
        origin_layer = cast("Literal['L1', 'L2', 'L3']", from_layer.upper())
        affected_slices = self._infer_conflict_slice_ids(to_layer, conflict_files)

        ticket_specs: list[tuple[str, list[str]]] = []
        if affected_slices:
            for slice_id in affected_slices:
                ticket_specs.append((slice_id, list(conflict_files)))
        elif conflict_files:
            for conflict_file in conflict_files:
                ticket_specs.append(("", [conflict_file]))
        else:
            ticket_specs.append(("", []))

        diagnosis_parts = [
            (
                f"Cross-layer propagation {from_layer.upper()}→{to_layer.upper()} failed after "
                "rebase and merge conflict-recovery attempts."
            ),
            "Downstream work must be regenerated from the updated upstream baseline.",
        ]
        if rebase_error:
            diagnosis_parts.append(f"rebase_error={rebase_error}")
        if merge_error:
            diagnosis_parts.append(f"merge_error={merge_error}")
        if conflict_files:
            diagnosis_parts.append("conflict_files=" + ", ".join(conflict_files))
        diagnosis = " ".join(diagnosis_parts)

        demotion_manager = DemotionManager(
            workspace_root=self.manager.workspace_path,
            run_id=self.manager.run_id,
        )
        ticket_rows: list[dict[str, Any]] = []
        gate_name = f"TRANSITION::{from_layer.upper()}->{to_layer.upper()}::PROPAGATION_CONFLICT"
        for slice_id, failing_files in ticket_specs:
            file_hint = failing_files[0] if failing_files else ""
            evidence_refs = [evidence_ref] if evidence_ref else []
            if investigator_report_ref:
                evidence_refs.append(investigator_report_ref)
            ticket = DemotionTicket(
                run_id=self.manager.run_id,
                slice_id=slice_id,
                source="ALGORITHMIC_GATE" if target_layer == "L1" else "ARCH_GATE",
                gate=gate_name,
                target_layer=target_layer,
                origin_layer=origin_layer,
                hop_trace=[origin_layer, target_layer],
                severity="BLOCKER",
                diagnosis=diagnosis,
                failing_files=failing_files,
                evidence_refs=evidence_refs,
                investigator_report_ref=investigator_report_ref,
            )
            try:
                apply_result = demotion_manager.apply(
                    ticket,
                    slice_root=self._resolve_demotion_slice_root(file_hint),
                )
            except Exception as exc:
                apply_result = {"applied": False, "error": str(exc)}
            ticket_rows.append({"ticket": ticket.to_dict(), "apply_result": apply_result})

        report_name = f"transition_{from_layer}_{to_layer}_propagation_demotion_tickets.json"
        self._write_run_report(report_name, ticket_rows)
        return {
            "demotion_tickets": len(ticket_rows),
            "demotion_tickets_applied": sum(
                1
                for row in ticket_rows
                if bool((row.get("apply_result") or {}).get("applied", False))
            ),
            "demotion_tickets_path": self._run_report_relpath(report_name),
            "affected_slices": affected_slices,
        }

    def _run_slices_at_layer(
        self,
        layer: Layer,
        *,
        lifecycle_mode: LifecycleRunMode = "build",
        target_slice_ids: list[str] | None = None,
        slice_focus_targets: dict[str, dict[str, list[str]]] | None = None,
    ) -> dict[str, Any]:
        """Discover slices and run PromotionLoop at a given layer.

        Creates coordination infrastructure (WorkItemStore, WakeQueue,
        MonitorRegistry, MonitorExecutor, WaitGraph) per layer and passes
        them to the ReactivePromotionScheduler.

        Args:
            layer: Which layer to run slices at.
            lifecycle_mode: PromotionLoop lifecycle mode for this layer pass.
            target_slice_ids: Optional focused slice IDs to run.
            slice_focus_targets: Optional per-slice focus targets derived
                from demotion tickets.

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
        requested_slice_ids = {
            str(slice_id).strip() for slice_id in (target_slice_ids or []) if str(slice_id).strip()
        }
        if requested_slice_ids:
            slice_refs = [ref for ref in slice_refs if ref.slice_id in requested_slice_ids]

        if not slice_refs:
            note = f"No slices found at {layer}"
            if requested_slice_ids:
                note = f"No matching slices found at {layer} for focused rework targets"
            return {
                "layer": layer,
                "lifecycle_mode": lifecycle_mode,
                "requested_slice_ids": sorted(requested_slice_ids),
                "note": note,
                "slices": [],
                "all_complete": True,
            }

        # Create slice worktrees if managed.
        # L2 runs directly in l2/dirty (Option A): no per-slice grandchildren.
        if self.worktree_manager:
            if layer == "l2":
                layer_dirty = self._resolve_layer_worktree("l2", "dirty")
                if layer_dirty is not None:
                    dirty_path = str(layer_dirty)
                    for ref in slice_refs:
                        ref.worktree_path = dirty_path
                else:
                    logger.warning(
                        "L2 dirty worktree unavailable; using discovered slice roots "
                        "for architecture run"
                    )
            else:
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
        run_context_config = self._build_run_context_config()
        if slice_focus_targets:
            run_context_config = {
                **run_context_config,
                "slice_focus_targets": {
                    str(slice_id): {
                        "failing_files": list(targets.get("failing_files", [])),
                        "failing_pins": list(targets.get("failing_pins", [])),
                        "failing_atoms": list(targets.get("failing_atoms", [])),
                        "location_symbols": list(targets.get("location_symbols", [])),
                    }
                    for slice_id, targets in slice_focus_targets.items()
                    if str(slice_id).strip()
                },
            }

        run_context = RunContext(
            run_id=self.manager.run_id,
            mode="auto" if self.mode != "interactive" else "interactive",
            lifecycle_mode=lifecycle_mode,
            workspace_root=str(self.manager.workspace_path),
            config=run_context_config,
        )

        # Build coordination infrastructure
        (
            monitor_executor,
            wake_queue,
            work_item_store,
            wait_graph,
            on_constraint_saved,
        ) = self._build_coordination(layer, run_context)

        planner = self._build_planner(
            work_item_store=work_item_store,
            wait_graph=wait_graph,
            on_constraint_saved=on_constraint_saved,
        )

        loop = PromotionLoop(
            worktree_manager=self.worktree_manager,
            workspace_manager=self.manager,
            branch_manager=self.manager.branches,
            workspace_root=self.manager.workspace_path,
            planner=planner,
        )

        ci_ticks: list[dict[str, Any]] = []
        ci_tick_slices: set[str] = set()
        ci_tick_lock = threading.Lock()
        periodic_tick_counter = 0
        run_gates: bool | dict[str, Any] = True
        run_tests: bool | dict[str, Any] = True
        max_pending_batches = 1
        tick_interval_sec = 20.0
        if isinstance(run_context.config, dict):
            pipeline_ci = run_context.config.get("pipeline_ci")
            if isinstance(pipeline_ci, dict):
                run_gates = cast("bool | dict[str, Any]", pipeline_ci.get("run_gates", True))
                run_tests = cast("bool | dict[str, Any]", pipeline_ci.get("run_tests", True))
                raw_max_pending = pipeline_ci.get("max_pending_batches", 1)
                try:
                    max_pending_batches = max(0, int(raw_max_pending))
                except (TypeError, ValueError):
                    max_pending_batches = 1
                raw_tick_interval = pipeline_ci.get("tick_interval_sec", 20)
                try:
                    tick_interval_sec = max(float(raw_tick_interval), 1.0)
                except (TypeError, ValueError):
                    tick_interval_sec = 20.0

        def record_ci_tick(slice_id: str, *, trigger: str) -> dict[str, Any]:
            wm = self.worktree_manager
            if wm is None:
                return {}

            with ci_tick_lock:
                batch_id = f"batch_{trigger}_{slice_id}_{len(ci_ticks) + 1}"
                try:
                    tick = wm.tick_pipeline(
                        active_layer=layer,
                        max_pending_batches=max_pending_batches,
                        run_gates=run_gates,
                        run_tests=run_tests,
                    )
                except Exception as exc:
                    receipt: dict[str, Any] = {
                        "batch_id": batch_id,
                        "slice_id": slice_id,
                        "trigger": trigger,
                        "layer": layer,
                        "failed": True,
                        "failure_summary": str(exc),
                        "failure_refs": [f"ci_tick_exception:{exc}"],
                        "failure_evidence": {"exception": str(exc)},
                    }
                    ci_ticks.append(receipt)
                    ci_tick_slices.add(slice_id)
                    if hasattr(self, "_state_mgr"):
                        batch_dir = self._state_mgr.run_dir / "ci" / layer / "batches"
                        batch_dir.mkdir(parents=True, exist_ok=True)
                        receipt_path = batch_dir / f"{batch_id}.json"
                        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
                        receipt["receipt_path"] = str(receipt_path)
                    return receipt

                layer_batch: Any | None = None
                layer_results = getattr(tick, "layer_results", None)
                if isinstance(layer_results, dict):
                    layer_batch = layer_results.get(layer)

                candidate_sha = getattr(layer_batch, "candidate_sha", None)
                base_clean_sha = getattr(layer_batch, "base_clean_sha", None)
                batch_success = (
                    bool(getattr(layer_batch, "success", True)) if layer_batch is not None else True
                )
                batch_error = str(getattr(layer_batch, "error", "") or "")
                batch_demotion_tickets = (
                    [str(item) for item in (getattr(layer_batch, "demotion_tickets", []) or [])]
                    if layer_batch is not None
                    else []
                )
                gates_passed = (
                    bool(getattr(layer_batch, "gates_passed", True)) if layer_batch else True
                )
                tests_passed = (
                    bool(getattr(layer_batch, "tests_passed", True)) if layer_batch else True
                )

                propagation_failures: list[dict[str, Any]] = []
                for prop in getattr(tick, "propagation_results", []) or []:
                    if str(getattr(prop, "from_layer", "")) != str(layer):
                        continue
                    if bool(getattr(prop, "success", True)):
                        continue
                    propagation_failures.append(
                        {
                            "from_layer": getattr(prop, "from_layer", ""),
                            "to_layer": getattr(prop, "to_layer", ""),
                            "error": str(getattr(prop, "error", "") or ""),
                            "conflict_files": list(getattr(prop, "conflict_files", []) or []),
                        }
                    )

                failed = (not batch_success) or bool(propagation_failures)
                failure_refs: list[str] = []
                if batch_error:
                    failure_refs.append(f"batch_error:{batch_error}")
                for ticket_ref in batch_demotion_tickets:
                    if ticket_ref:
                        failure_refs.append(f"batch_ticket:{ticket_ref}")
                for prop_failure in propagation_failures:
                    prop_error = str(prop_failure.get("error", "")).strip()
                    hop = f"{prop_failure.get('from_layer')}->{prop_failure.get('to_layer')}"
                    if prop_error:
                        failure_refs.append(f"propagation:{hop}:{prop_error}")
                    for path in prop_failure.get("conflict_files", []) or []:
                        failure_refs.append(f"propagation_conflict_file:{path}")

                failure_summary = ""
                if failed:
                    segments: list[str] = []
                    if batch_error:
                        segments.append(batch_error)
                    if propagation_failures and not batch_error:
                        segments.append("cross-layer propagation failed")
                    failure_summary = "; ".join(segments) if segments else "CI tick failed"

                receipt = {
                    "batch_id": batch_id,
                    "slice_id": slice_id,
                    "trigger": trigger,
                    "layer": layer,
                    "main_updated": tick.main_updated,
                    "main_sha": getattr(tick, "main_sha", None),
                    "demotions": len(tick.demotion_tickets),
                    "candidate_sha": candidate_sha,
                    "base_clean_sha": base_clean_sha,
                    "failed": failed,
                    "failure_summary": failure_summary,
                    "failure_refs": failure_refs[:24],
                    "failure_evidence": {
                        "batch_success": batch_success,
                        "batch_error": batch_error,
                        "batch_demotion_tickets": batch_demotion_tickets,
                        "gates_passed": gates_passed,
                        "tests_passed": tests_passed,
                        "propagation_failures": propagation_failures,
                    },
                }
                ci_ticks.append(receipt)
                ci_tick_slices.add(slice_id)

                if hasattr(self, "_state_mgr"):
                    batch_dir = self._state_mgr.run_dir / "ci" / layer / "batches"
                    batch_dir.mkdir(parents=True, exist_ok=True)
                    receipt_path = batch_dir / f"{batch_id}.json"
                    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
                    receipt["receipt_path"] = str(receipt_path)
                return receipt

        def on_slice_merge(slice_id: str) -> dict[str, Any] | None:
            normalized = str(slice_id).strip()
            if not normalized:
                return None
            receipt = record_ci_tick(normalized, trigger="post_merge")
            try:
                monitor_executor.on_event("SLICE_MERGED")
            except Exception:
                logger.warning(
                    "Failed to emit coordination event SLICE_MERGED for %s",
                    normalized,
                    exc_info=True,
                )
            return receipt

        def on_periodic_tick() -> None:
            nonlocal periodic_tick_counter
            periodic_tick_counter += 1
            record_ci_tick(f"periodic-{periodic_tick_counter}", trigger="periodic")
            try:
                monitor_executor.on_event("GIT_DIRTY_ADVANCED")
            except Exception:
                logger.warning(
                    "Failed to emit coordination event GIT_DIRTY_ADVANCED",
                    exc_info=True,
                )

        run_context.ci_tick_callback = on_slice_merge if self.worktree_manager else None
        run_context.ci_periodic_tick_callback = on_periodic_tick if self.worktree_manager else None
        run_context.ci_periodic_tick_interval_sec = tick_interval_sec

        def on_slice_result(result: Any) -> None:
            if str(getattr(result, "status", "")).upper() != "COMPLETE":
                return
            slice_id = str(getattr(result, "slice_id", "")).strip()
            if not slice_id:
                return
            record_ci_tick(slice_id, trigger="on_complete")

        layer_parallelism = 1 if layer == "l2" else self.max_parallel
        scheduler = ReactivePromotionScheduler(
            loop=loop,
            config=SchedulerConfig(
                max_parallel=layer_parallelism,
                monitor_poll_interval_sec=max(1, int(tick_interval_sec)),
            ),
            monitor_executor=monitor_executor,
            wake_queue=wake_queue,
        )
        gap_counts = self._load_gap_priority_counts(layer, slice_refs)
        sched_result = scheduler.run(
            slice_refs,
            run_context,
            gap_counts=gap_counts,
            on_slice_result=on_slice_result if self.worktree_manager else None,
        )
        slice_results = sched_result.slice_results

        # Fallback for schedulers/mocks that do not invoke ``on_slice_result``.
        if self.worktree_manager:
            for sr in slice_results:
                if sr.status != "COMPLETE":
                    continue
                if sr.slice_id in ci_tick_slices:
                    continue
                record_ci_tick(sr.slice_id, trigger="completion_fallback")

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

        all_terminal = all(r.status in _TERMINAL_SLICE_STATUSES for r in slice_results)

        return {
            "layer": layer,
            "lifecycle_mode": lifecycle_mode,
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
            "all_complete": all_terminal,
            "waiting_slices": sched_result.waiting_slices,
            "total_layer_demotions": total_layer_demotions,
            "budget_exceeded": budget_exceeded,
        }

    def _build_coordination(
        self,
        layer: Layer,
        run_context: Any,
    ) -> tuple[Any, Any, Any, Any, Callable[[str, str, str], None]]:
        """Build coordination infrastructure for a layer run.

        Creates WorkItemStore, WakeQueue, MonitorRegistry, WaitGraph,
        ConditionChecker, and MonitorExecutor, plus a constraint-save callback
        that emits direct wake events.

        Args:
            layer: Layer being run.
            run_context: Run-scoped context.

        Returns:
            Tuple of
            ``(monitor_executor, wake_queue, work_item_store, wait_graph, on_constraint_saved)``.
        """
        from spec_manager.orchestration.coordination.monitor_executor import (
            ConditionChecker,
            MonitorExecutor,
        )
        from spec_manager.orchestration.coordination.monitors import MonitorRegistry
        from spec_manager.orchestration.coordination.wait_graph import WaitGraph
        from spec_manager.orchestration.coordination.wake_queue import WakeEvent, WakeQueue
        from spec_manager.orchestration.coordination.work_items import WorkItemStore
        from spec_manager.planner.constraints.store import ConstraintsStore

        workspace = self.manager.workspace_path
        run_id = run_context.run_id if hasattr(run_context, "run_id") else self.manager.run_id
        coordination_dir = workspace / ".pdd_runs" / run_id / "coordination"
        coordination_dir.mkdir(parents=True, exist_ok=True)

        work_item_store = WorkItemStore(coordination_dir)
        wake_queue = WakeQueue(coordination_dir)
        monitor_registry = MonitorRegistry(coordination_dir)
        wait_graph = WaitGraph()

        constraints_store = ConstraintsStore(workspace)

        checker = ConditionChecker(
            workspace_root=workspace,
            work_item_store=work_item_store,
            constraints_store=constraints_store,
        )

        monitor_executor: Any | None = None

        def on_constraint_saved(slice_id: str, constraint_id: str, canonical_key: str) -> None:
            normalized_constraint_id = str(constraint_id or "").strip()
            if not normalized_constraint_id:
                return

            artifact_key = f"constraint:{normalized_constraint_id}"
            wake_payload = {
                "constraint_id": normalized_constraint_id,
                "canonical_key": str(canonical_key or "").strip(),
                "source_slice_id": str(slice_id or "").strip(),
            }

            waiting_edges = list(wait_graph.get_providers_for(normalized_constraint_id))
            for edge in waiting_edges:
                wake_queue.enqueue(
                    WakeEvent(
                        signal_id=edge.signal_id,
                        slice_id=edge.waiting_slice,
                        layer=str(layer),
                        reason="constraint_saved",
                        artifact_key=artifact_key,
                        wake_payload=wake_payload,
                    )
                )
                if edge.signal_id:
                    wait_graph.remove_edge(edge.signal_id)

            if monitor_executor is not None:
                try:
                    monitor_executor.on_event("CONSTRAINT_SAVED")
                except Exception:
                    logger.warning(
                        "Failed to emit coordination event CONSTRAINT_SAVED for constraint %s",
                        normalized_constraint_id,
                        exc_info=True,
                    )

        monitor_executor = MonitorExecutor(
            registry=monitor_registry,
            checker=checker,
            wake_queue=wake_queue,
        )

        return monitor_executor, wake_queue, work_item_store, wait_graph, on_constraint_saved

    def _load_gap_priority_counts(self, layer: Layer, slice_refs: list[Any]) -> dict[str, int]:
        """Load per-slice open-gap counts for scheduler priority ordering."""
        if not slice_refs:
            return {}

        target_ids = {
            str(getattr(ref, "slice_id", "")).strip()
            for ref in slice_refs
            if getattr(ref, "slice_id", "")
        }
        if not target_ids:
            return {}

        counts = {slice_id: 0 for slice_id in target_ids}
        for row in self._gather_latest_evidence():
            if row.get("layer") != layer:
                continue
            slice_id = str(row.get("slice_id", "")).strip()
            if slice_id not in counts:
                continue
            raw_count = row.get("open_gap_count", 0)
            try:
                counts[slice_id] = int(raw_count)
            except (TypeError, ValueError):
                counts[slice_id] = 0
        return counts

    def _discover_slices(self, layer: Layer) -> list[Any]:
        """Discover work slices for a given layer.

        - L1: slices = libraries (concern boundaries)
        - L2: slices = architectural components from component manifest
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
            manifest_path = (
                self.manager.structure.root
                / "reports"
                / "pdd"
                / self.manager.run_id
                / "component_manifest.json"
            )
            if not manifest_path.exists():
                raise RuntimeError(
                    "L2 slice discovery requires reports/pdd/"
                    f"{self.manager.run_id}/component_manifest.json"
                )
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise RuntimeError(f"L2 component manifest is unreadable: {manifest_path}") from exc

            raw_components = data.get("components", [])
            if not isinstance(raw_components, list) or not raw_components:
                raise RuntimeError(f"L2 component manifest has no components: {manifest_path}")

            for comp in raw_components:
                if not isinstance(comp, dict):
                    continue
                comp_id = str(comp.get("component_id", comp.get("id", ""))).strip()
                if not comp_id:
                    continue
                files_raw = comp.get("files", [])
                files = [str(path) for path in files_raw if isinstance(path, str)]
                wt_path = str(self.manager.structure.spec_snapshot_dir)
                if files:
                    first_file = Path(files[0])
                    if first_file.parent != Path("."):
                        wt_path = str(self.manager.structure.spec_snapshot_dir / first_file.parent)
                owned_entrypoints_raw = comp.get("owned_entrypoints", [])
                pins_consumed_raw = comp.get("pins_consumed", [])
                upstream_raw = comp.get("upstream", [])
                downstream_raw = comp.get("downstream", [])
                slice_refs.append(
                    SliceRef(
                        slice_id=f"arch-{comp_id}",
                        layer=layer,
                        library_id=comp_id,
                        worktree_path=wt_path,
                        metadata={
                            "component_id": comp_id,
                            "owned_entrypoints": [
                                str(item) for item in owned_entrypoints_raw if isinstance(item, str)
                            ],
                            "pins_consumed": [
                                str(item) for item in pins_consumed_raw if isinstance(item, str)
                            ],
                            "upstream": [
                                str(item) for item in upstream_raw if isinstance(item, str)
                            ],
                            "downstream": [
                                str(item) for item in downstream_raw if isinstance(item, str)
                            ],
                            "files": files,
                        },
                    )
                )
            if not slice_refs:
                raise RuntimeError(
                    f"L2 component manifest has no valid component IDs: {manifest_path}"
                )

        elif layer == "l3":
            # L3: one slice per code file (finding clusters handled internally)
            spec_snapshot_dir = self.manager.structure.spec_snapshot_dir
            if spec_snapshot_dir.exists():
                for py_file in source_rglob(spec_snapshot_dir):
                    if py_file.is_file():
                        relative_path = self._l3_relative_source_path(
                            spec_snapshot_dir=spec_snapshot_dir,
                            file_path=py_file,
                        )
                        slice_refs.append(
                            SliceRef(
                                slice_id=self._l3_slice_id_for_relative_path(relative_path),
                                layer=layer,
                                worktree_path=str(py_file.parent),
                                metadata={"files": [relative_path], "relative_path": relative_path},
                            )
                        )

        return slice_refs

    # ------------------------------------------------------------------
    # L1 with human approval
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical_key_matches(*, expected: str, observed: str) -> bool:
        expected_norm = str(expected).strip().lower()
        observed_norm = str(observed).strip().lower()
        if not expected_norm or not observed_norm:
            return False
        return observed_norm == expected_norm or observed_norm.startswith(f"{expected_norm}.")

    def _coordination_run_dir(self) -> Path:
        if hasattr(self, "_state_mgr"):
            return self._state_mgr.run_dir
        return self.manager.workspace_path / ".pdd_runs" / self.manager.run_id

    def _planner_has_canonical_resolution(self, canonical_key: str) -> bool:
        from spec_manager.orchestration.intent_agent.signals import PlannerUpdateStore

        run_dir = self._coordination_run_dir()
        store = PlannerUpdateStore(run_dir)
        read_result = store.read_all()
        for event in read_result.events:
            payload = event.payload if isinstance(event.payload, dict) else {}
            keys: list[str] = []
            canonical_keys = payload.get("canonical_keys", [])
            if isinstance(canonical_keys, list):
                keys.extend(str(item).strip() for item in canonical_keys if str(item).strip())
            canonical_key_single = str(payload.get("canonical_key", "")).strip()
            if canonical_key_single:
                keys.append(canonical_key_single)
            for candidate in keys:
                if self._canonical_key_matches(expected=canonical_key, observed=candidate):
                    return True
        return False

    def _signal_already_emitted(self, signal_id: str) -> bool:
        from spec_manager.orchestration.intent_agent.signals import UserQuestionSignalStore

        run_dir = self._coordination_run_dir()
        store = UserQuestionSignalStore(run_dir)
        read_result = store.read_all()
        target = str(signal_id).strip()
        if not target:
            return False
        return any(str(signal.source.signal_id).strip() == target for signal in read_result.signals)

    def _emit_lifecycle_question_signal(
        self,
        *,
        checkpoint: str,
        signal_id: str,
        layer: str,
        taxonomy_hint: str,
        canonical_key_hint: str,
        text: str,
        answer_spec_hint: dict[str, Any],
        payload: dict[str, Any],
    ) -> bool:
        if self._signal_already_emitted(signal_id):
            return False

        from spec_manager.orchestration.intent_agent.signals import (
            SignalBlocking,
            SignalContext,
            SignalQuestion,
            SignalSource,
            UserQuestionSignal,
            UserQuestionSignalStore,
        )

        run_dir = self._coordination_run_dir()
        store = UserQuestionSignalStore(run_dir)
        signal = UserQuestionSignal(
            run_id=self.manager.run_id,
            source=SignalSource(
                kind="PDD_LIFECYCLE",
                trace_id=checkpoint,
                slice_id="__system__",
                layer=layer,
                signal_id=signal_id,
            ),
            question=SignalQuestion(
                text=text,
                taxonomy_hint=taxonomy_hint,
                canonical_key_hint=canonical_key_hint,
                answer_spec_hint=answer_spec_hint,
            ),
            context=SignalContext(
                blocking=SignalBlocking(
                    severity="BLOCKING",
                    blocked_slices=[],
                ),
            ),
            payload=payload,
        )
        store.write(signal)
        return True

    def _run_l1_with_approval(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Run L1 layer and checkpoint via signal-based approval flow."""
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
            if str(approval.get("status", "")).upper() == "WAITING":
                return l1_result, approval

            logger.info(
                "L1 not approved (iteration %d): %s",
                iteration,
                approval.get("feedback", ""),
            )

        self._write_approval_artifact(
            "l1",
            approved=False,
            iteration=iteration,
            exhausted_iterations=True,
            reason="max_iterations_reached",
        )
        message = (
            "L1 approval blocked: max approval iterations "
            f"({self.max_approval_iterations}) reached without approval."
        )
        logger.error(message)
        raise RuntimeError(message)

    def _write_approval_artifact(
        self,
        layer: str,
        approved: bool,
        iteration: int = 0,
        **extra: Any,
    ) -> None:
        """Write an approval decision artifact using run-scoped layout.

        Args:
            layer: Approval layer (e.g., "l1", "l2", "l3").
            approved: Whether the checkpoint was approved.
            iteration: Iteration number (relevant for L1 loops).
            **extra: Additional metadata to include in the artifact.
        """
        if not hasattr(self, "_state_mgr"):
            return

        approvals_root = self._state_mgr.run_dir / "approvals"
        if layer == "l1":
            artifact_path = approvals_root / "l1" / f"iteration_{iteration}" / "decision.json"
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

        checkpoint = "l1_approval"
        signal_specs = [
            {
                "signal_id": f"{checkpoint}:validation:iter{iteration}",
                "layer": "l1",
                "taxonomy_hint": "VALIDATION",
                "canonical_key_hint": "pdd.lifecycle.l1.validation",
                "text": (
                    "Does the L1 output align with your intent and acceptance expectations "
                    "before moving to architecture work?"
                ),
                "answer_spec_hint": {
                    "preferred_kind": "choice",
                    "choices": [
                        {"id": "align_yes", "label": "Aligned, proceed to L2"},
                        {"id": "align_with_gaps", "label": "Proceed, record known gaps"},
                        {"id": "align_no", "label": "Not aligned yet"},
                    ],
                },
            },
            {
                "signal_id": f"{checkpoint}:scope:iter{iteration}",
                "layer": "l1",
                "taxonomy_hint": "SCOPE",
                "canonical_key_hint": "pdd.lifecycle.l1.scope",
                "text": (
                    "Before L2 starts, confirm scope boundaries or list any scope adjustments "
                    "that must be captured as constraints."
                ),
                "answer_spec_hint": {
                    "preferred_kind": "choice_or_text",
                    "choices": [
                        {"id": "scope_no_change", "label": "Scope unchanged"},
                        {"id": "scope_adjust", "label": "Scope needs adjustment"},
                    ],
                },
            },
        ]

        pending_keys = [
            spec["canonical_key_hint"]
            for spec in signal_specs
            if not self._planner_has_canonical_resolution(spec["canonical_key_hint"])
        ]
        if pending_keys:
            emitted = 0
            for spec in signal_specs:
                if spec["canonical_key_hint"] not in pending_keys:
                    continue
                emitted += int(
                    self._emit_lifecycle_question_signal(
                        checkpoint=checkpoint,
                        signal_id=spec["signal_id"],
                        layer=spec["layer"],
                        taxonomy_hint=spec["taxonomy_hint"],
                        canonical_key_hint=spec["canonical_key_hint"],
                        text=spec["text"],
                        answer_spec_hint=spec["answer_spec_hint"],
                        payload={
                            "checkpoint": checkpoint,
                            "iteration": iteration,
                            "overview_ref": overview_ref,
                            "alignment_ref": alignment_ref,
                        },
                    )
                )
            self._write_approval_artifact(
                "l1",
                approved=False,
                iteration=iteration,
                checkpoint=checkpoint,
                status="WAITING",
                pending_canonical_keys=pending_keys,
                emitted_signals=emitted,
                overview_ref=overview_ref,
                alignment_ref=alignment_ref,
            )
            return {
                "approved": False,
                "status": "WAITING",
                "checkpoint": checkpoint,
                "iteration": iteration,
                "pending_canonical_keys": pending_keys,
                "mode": "interactive",
            }

        self._write_approval_artifact(
            "l1",
            approved=True,
            iteration=iteration,
            checkpoint=checkpoint,
            status="APPROVED",
            signal_flow=True,
            overview_ref=overview_ref,
            alignment_ref=alignment_ref,
        )
        return {
            "approved": True,
            "status": "APPROVED",
            "checkpoint": checkpoint,
            "iteration": iteration,
            "mode": "interactive",
        }

    def _request_l2_checkpoint(self, l2_result: dict[str, Any]) -> dict[str, Any]:
        """Signal-based L2 checkpoint before L3 promotion."""
        if self.mode in ("auto", "steering"):
            self._write_approval_artifact("l2", approved=True)
            return {"approved": True, "mode": self.mode}

        checkpoint = "l2_checkpoint"
        layer_summary = (
            {
                "all_complete": bool(l2_result.get("all_complete", False)),
                "slice_count": len(l2_result.get("slices", []) or []),
                "waiting_slices": list(l2_result.get("waiting_slices", []) or []),
            }
            if isinstance(l2_result, dict)
            else {}
        )
        signal_specs = [
            {
                "signal_id": f"{checkpoint}:tradeoff",
                "taxonomy_hint": "TRADEOFF",
                "canonical_key_hint": "pdd.lifecycle.l2.tradeoff",
                "text": (
                    "Are any architectural tradeoffs still unresolved and BLOCKING before L3?"
                ),
            },
            {
                "signal_id": f"{checkpoint}:constraint",
                "taxonomy_hint": "CONSTRAINT",
                "canonical_key_hint": "pdd.lifecycle.l2.constraint",
                "text": (
                    "Confirm whether any additional architecture constraints must be recorded "
                    "before L3 implementation quality work proceeds."
                ),
            },
            {
                "signal_id": f"{checkpoint}:scope",
                "taxonomy_hint": "SCOPE",
                "canonical_key_hint": "pdd.lifecycle.l2.scope",
                "text": "Confirm architecture scope boundaries before L3 begins.",
            },
        ]
        pending_keys = [
            spec["canonical_key_hint"]
            for spec in signal_specs
            if not self._planner_has_canonical_resolution(spec["canonical_key_hint"])
        ]
        if pending_keys:
            emitted = 0
            for spec in signal_specs:
                if spec["canonical_key_hint"] not in pending_keys:
                    continue
                emitted += int(
                    self._emit_lifecycle_question_signal(
                        checkpoint=checkpoint,
                        signal_id=spec["signal_id"],
                        layer="l2",
                        taxonomy_hint=spec["taxonomy_hint"],
                        canonical_key_hint=spec["canonical_key_hint"],
                        text=spec["text"],
                        answer_spec_hint={
                            "preferred_kind": "choice_or_text",
                            "choices": [
                                {"id": "resolved", "label": "Resolved"},
                                {"id": "needs_input", "label": "Needs additional input"},
                            ],
                        },
                        payload={
                            "checkpoint": checkpoint,
                            "layer_summary": layer_summary,
                        },
                    )
                )
            self._write_approval_artifact(
                "l2",
                approved=False,
                checkpoint=checkpoint,
                status="WAITING",
                pending_canonical_keys=pending_keys,
                emitted_signals=emitted,
            )
            return {
                "approved": False,
                "status": "WAITING",
                "checkpoint": checkpoint,
                "pending_canonical_keys": pending_keys,
                "mode": "interactive",
            }

        self._write_approval_artifact(
            "l2",
            approved=True,
            checkpoint=checkpoint,
            status="APPROVED",
            signal_flow=True,
        )
        return {
            "approved": True,
            "status": "APPROVED",
            "checkpoint": checkpoint,
            "mode": "interactive",
        }

    def _request_release_signoff(self, results: dict[str, Any]) -> dict[str, Any]:
        """Release signoff via VALIDATION signal and planner-recorded answer."""
        if self.mode in ("auto", "steering"):
            self._write_approval_artifact("l3", approved=True, checkpoint="release_signoff")
            return {"approved": True, "mode": self.mode}

        checkpoint = "release_signoff"
        canonical_key = "pdd.lifecycle.release.signoff"
        scorecard = results.get("scorecard", {})
        pending = not self._planner_has_canonical_resolution(canonical_key)
        if pending:
            emitted = int(
                self._emit_lifecycle_question_signal(
                    checkpoint=checkpoint,
                    signal_id=f"{checkpoint}:validation",
                    layer="l3",
                    taxonomy_hint="VALIDATION",
                    canonical_key_hint=canonical_key,
                    text=("Does this meet your acceptance expectations for release?"),
                    answer_spec_hint={
                        "preferred_kind": "choice",
                        "choices": [
                            {"id": "approve", "label": "Approve"},
                            {"id": "not_yet", "label": "Not yet - list up to 3 issues"},
                            {"id": "approve_with_gaps", "label": "Approve with known gaps"},
                        ],
                    },
                    payload={
                        "checkpoint": checkpoint,
                        "scorecard_overall_pass": bool(scorecard.get("overall_pass", True)),
                        "final_governance": results.get("final_governance", {}),
                    },
                )
            )
            self._write_approval_artifact(
                "l3",
                approved=False,
                checkpoint=checkpoint,
                status="WAITING",
                pending_canonical_keys=[canonical_key],
                emitted_signals=emitted,
            )
            return {
                "approved": False,
                "status": "WAITING",
                "checkpoint": checkpoint,
                "pending_canonical_keys": [canonical_key],
                "mode": "interactive",
            }

        self._write_approval_artifact(
            "l3",
            approved=True,
            checkpoint=checkpoint,
            status="APPROVED",
            signal_flow=True,
        )
        return {
            "approved": True,
            "status": "APPROVED",
            "checkpoint": checkpoint,
            "mode": "interactive",
        }

    # ------------------------------------------------------------------
    # Intake
    # ------------------------------------------------------------------

    def _run_intake(self) -> dict[str, Any]:
        """Run Phase 0 intake conditionally with bounded rework.

        Intake runs only when input appears to be raw prose and no structured
        libraries already exist. If intake quality indicates unresolved
        coverage/overlap issues, intake re-runs up to 2 passes.

        Returns:
            Intake summary with ``ran`` flag and final pass details.
        """
        should_run, reason = self._should_run_intake()
        if not should_run:
            logger.info("Skipping Phase 0 intake: %s", reason)
            return {
                "ran": False,
                "skipped": True,
                "reason": reason,
                "attempts": 0,
                "max_rework_passes": 2,
            }

        max_passes = 2
        passes: list[dict[str, Any]] = []
        rework_reasons: list[str] = []

        for attempt in range(1, max_passes + 1):
            pass_result = self._run_intake_once()
            pass_result["attempt"] = attempt
            passes.append(pass_result)

            rework_reasons = self._intake_rework_reasons(pass_result)
            if not rework_reasons:
                break

            if attempt < max_passes:
                logger.warning(
                    "Phase 0 intake pass %d/%d requires rework (%s); retrying",
                    attempt,
                    max_passes,
                    ", ".join(rework_reasons),
                )

        final_result: dict[str, Any] = dict(passes[-1]) if passes else {}
        final_result["ran"] = True
        final_result["attempts"] = len(passes)
        final_result["max_rework_passes"] = max_passes
        final_result["passes"] = passes
        if rework_reasons:
            final_result["rework_reasons"] = rework_reasons
        return final_result

    def _should_run_intake(self) -> tuple[bool, str]:
        """Return whether Phase 0 intake should run for this lifecycle."""
        libraries_dir = self.manager.structure.libraries_dir
        if libraries_dir.exists() and any(path.is_dir() for path in libraries_dir.iterdir()):
            return False, "workspace already contains libraries"

        raw_input_root = getattr(self.manager, "input_folder", None)
        if isinstance(raw_input_root, Path):
            input_root = raw_input_root
        elif isinstance(raw_input_root, str):
            input_root = Path(raw_input_root)
        else:
            input_root = self.manager.workspace_path / "spec_snapshot"
        if not input_root.exists():
            return True, "input folder does not exist locally; attempting intake"

        if self._input_appears_structured(input_root):
            return False, "input already structured"

        prose_suffixes = {".md", ".markdown", ".txt", ".rst", ".adoc"}
        candidate_files = [
            path
            for path in input_root.rglob("*")
            if path.is_file() and not any(part.startswith(".") for part in path.parts)
        ]
        if not candidate_files:
            return False, "input folder contains no files"

        has_non_prose = any(path.suffix.lower() not in prose_suffixes for path in candidate_files)
        if has_non_prose:
            return False, "input contains non-prose files"

        return True, "raw prose input detected"

    @staticmethod
    def _input_appears_structured(input_root: Path) -> bool:
        """Heuristic: detect pre-structured intake input layout."""
        if (input_root / "libraries.yaml").exists():
            return True
        if (input_root / "route_table.jsonl").exists():
            return True
        if (input_root / "coverage_ledger.jsonl").exists():
            return True

        libraries_dir = input_root / "libraries"
        return libraries_dir.exists() and any(path.is_dir() for path in libraries_dir.iterdir())

    def _run_intake_once(self) -> dict[str, Any]:
        """Run one Phase 0 intake pass.

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

    @staticmethod
    def _intake_rework_reasons(result: dict[str, Any]) -> list[str]:
        """Extract bounded rework triggers from an intake result payload."""
        reasons: list[str] = []

        def add_reason(reason: str) -> None:
            if reason not in reasons:
                reasons.append(reason)

        if int(result.get("coverage_files_incomplete", 0) or 0) > 0:
            add_reason("coverage_below_100")

        quality = result.get("library_quality")
        if isinstance(quality, dict):
            dimensions = quality.get("dimensions")
            if isinstance(dimensions, list):
                for dim in dimensions:
                    if not isinstance(dim, dict):
                        continue
                    name = str(dim.get("name", "")).lower().strip()
                    passed = bool(dim.get("passed", True))
                    if name == "completeness" and not passed:
                        add_reason("coverage_below_100")
                    if name == "routing_overlap" and not passed:
                        add_reason("fatal_routing_overlap")

        error_text = str(result.get("error", "")).lower()
        if "coverage" in error_text:
            add_reason("coverage_below_100")
        if "routing overlap" in error_text or ("overlap" in error_text and "route" in error_text):
            add_reason("fatal_routing_overlap")

        return reasons

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

        Produces a canonical component manifest, identifies issues, and emits
        :class:`DemotionTicket` instances for findings that require changes
        at lower layers.

        Returns:
            Architecture refinement results including demotion tickets.
        """
        logger.info("=== Architectural Refinement ===")

        from spec_manager.core.agent_utils import run_agent
        from spec_manager.orchestration.demotion import DemotionManager, DemotionTicket
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
            "Given the following promotion evidence, produce a canonical L2 component manifest.\n\n"
            "Return JSON with keys:\n"
            "- 'components': array of component records\n"
            "- 'issues': array of architectural issues found\n\n"
            "Each component record must include:\n"
            "- component_id (string)\n"
            "- owned_entrypoints (array[string])\n"
            "- pins_consumed (array[string])\n"
            "- upstream (array[string])\n"
            "- downstream (array[string])\n"
            "- files (array[string])\n\n"
            "Issues should include: severity (BLOCKER/MAJOR/MINOR), file, description.\n\n"
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
            components = data.get("components", [])
            issues = data.get("issues", [])

            normalized_components: list[dict[str, Any]] = []
            for raw_comp in components if isinstance(components, list) else []:
                if not isinstance(raw_comp, dict):
                    continue
                component_id = str(raw_comp.get("component_id") or raw_comp.get("id") or "").strip()
                if not component_id:
                    continue

                normalized_components.append(
                    {
                        "component_id": component_id,
                        "owned_entrypoints": [
                            str(item)
                            for item in (raw_comp.get("owned_entrypoints") or [])
                            if isinstance(item, str)
                        ],
                        "pins_consumed": [
                            str(item)
                            for item in (raw_comp.get("pins_consumed") or [])
                            if isinstance(item, str)
                        ],
                        "upstream": [
                            str(item)
                            for item in (raw_comp.get("upstream") or [])
                            if isinstance(item, str)
                        ],
                        "downstream": [
                            str(item)
                            for item in (raw_comp.get("downstream") or [])
                            if isinstance(item, str)
                        ],
                        "files": [
                            str(item)
                            for item in (raw_comp.get("files") or [])
                            if isinstance(item, str)
                        ],
                    }
                )

            manifest_payload = {"components": normalized_components}
            self._write_run_report("component_manifest.json", manifest_payload)

            # Emit and route DemotionTickets via the authoritative demotion ledger.
            demotion_manager = DemotionManager(
                workspace_root=self.manager.workspace_path,
                run_id=self.manager.run_id,
            )
            tickets: list[dict[str, Any]] = []
            for issue in issues if isinstance(issues, list) else []:
                if not isinstance(issue, dict):
                    continue
                severity = str(issue.get("severity", "MINOR")).upper()
                normalized_severity = (
                    severity if severity in ("BLOCKER", "MAJOR", "MINOR") else "MINOR"
                )
                target_layer = "L1" if normalized_severity == "BLOCKER" else "L2"
                issue_file = str(issue.get("file", "")).strip()
                evidence_refs = [self._run_report_relpath("component_manifest.json")]
                issue_refs = issue.get("evidence_refs", [])
                if isinstance(issue_refs, list):
                    evidence_refs.extend(str(ref) for ref in issue_refs if str(ref).strip())
                ticket = DemotionTicket(
                    run_id=self.manager.run_id,
                    slice_id=str(issue.get("slice_id", "")).strip(),
                    source="ARCH_GATE",
                    target_layer=target_layer,
                    origin_layer="L2",
                    hop_trace=["L2", target_layer],
                    severity=normalized_severity,
                    diagnosis=str(issue.get("description", "Architectural issue")),
                    failing_files=[issue_file] if issue_file else [],
                    evidence_refs=evidence_refs,
                )
                apply_result = demotion_manager.apply(
                    ticket,
                    slice_root=self._resolve_demotion_slice_root(issue_file),
                )
                tickets.append({"ticket": ticket.to_dict(), "apply_result": apply_result})

            if tickets:
                self._write_run_report("architecture_demotion_tickets.json", tickets)

            return {
                "component_count": len(normalized_components),
                "component_manifest_path": self._run_report_relpath("component_manifest.json"),
                "demotion_tickets": len(tickets),
                "demotion_tickets_applied": sum(
                    1
                    for row in tickets
                    if bool((row.get("apply_result") or {}).get("applied", False))
                ),
            }
        except Exception as exc:
            logger.warning("Architectural refinement failed: %s", exc)
            return {"error": str(exc)}

    def _code_quality_refinement(self) -> dict[str, Any]:
        """Code quality refinement using the authoritative L3 review pack.

        Runs N quality reviewers and emits :class:`DemotionTicket`
        instances for findings that touch logic (demote to L1) or
        architecture (demote to L2).

        Returns:
            Code quality refinement results including demotion tickets.
        """
        logger.info("=== Code Quality Refinement ===")

        from spec_manager.core.agent_utils import run_agent
        from spec_manager.orchestration.demotion import DemotionManager, DemotionTicket
        from spec_manager.orchestration.pattern_library import PatternLibrary
        from spec_manager.orchestration.promotion_loop import L3_REVIEW_PACK
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

        review_model_id = self._resolve_model_id_for_role("review")
        pattern_lib = PatternLibrary(
            library_path=self.manager.workspace_path / ".pdd_runs" / "pattern_library.json"
        )

        all_findings: list[dict[str, Any]] = []

        for row in evidence_rows:
            slice_id = row.get("slice_id", "")
            for reviewer in L3_REVIEW_PACK:
                pattern_section = pattern_lib.get_review_prompt_section(reviewer.dimension)
                prompt = (
                    "## TASK\n\n"
                    "Review the following promotion evidence for quality and conformance risks.\n"
                    f"Objective: {reviewer.objective}\n"
                    "For each finding include: severity (BLOCKER/MAJOR/MINOR),\n"
                    "category (logic/architecture/style/maintainability/drift/diff-impact),\n"
                    "required_change_type (refactor_only/wiring_only/behavior_change), and "
                    "description.\n"
                    "Return JSON with key 'findings' containing an array of issues.\n\n"
                    f"{pattern_section}\n\n"
                    f"Evidence slice: {slice_id}\n\n"
                    f"Evidence:\n{json.dumps(row, indent=2)}\n"
                )
                try:
                    output = run_agent(
                        agent_name=reviewer.agent_name,
                        prompt=prompt,
                        workspace=self.manager.workspace_path,
                        model_id=review_model_id,
                        role=reviewer.reviewer_id,
                        run_id=self.manager.run_id,
                        slice_id=slice_id,
                        layer=str(row.get("layer", "l3")),
                        call_hook=self._record_llm_call,
                    )
                    cleaned = _strip_code_fences(output)
                    data = json.loads(_extract_json_payload(cleaned))
                    findings = data.get("findings", [])
                    for finding in findings:
                        if not isinstance(finding, dict):
                            continue
                        finding["file"] = slice_id
                        finding["reviewer"] = reviewer.reviewer_id
                        finding["agent_name"] = reviewer.agent_name
                        finding["dimension"] = reviewer.dimension
                        finding.setdefault("category", reviewer.default_category)
                        finding.setdefault(
                            "required_change_type", reviewer.default_required_change_type
                        )
                        all_findings.append(finding)
                except Exception as exc:
                    logger.warning(
                        "Reviewer %s failed for evidence slice %s: %s",
                        reviewer.reviewer_id,
                        slice_id,
                        exc,
                    )

        # Write quality report
        self._write_run_report("code_quality_report.json", {"findings": all_findings})

        # Emit and route DemotionTickets for findings that touch logic or architecture.
        demotion_manager = DemotionManager(
            workspace_root=self.manager.workspace_path,
            run_id=self.manager.run_id,
        )
        tickets: list[dict[str, Any]] = []
        for finding in all_findings:
            category = finding.get("category", "style")
            severity = finding.get("severity", "MINOR")
            required_change_type = finding.get("required_change_type", "refactor_only")
            if (
                category in ("logic", "diff-impact")
                or required_change_type == "behavior_change"
                or category == "architecture"
                or severity == "BLOCKER"
            ):
                target = (
                    "L1"
                    if (
                        category in ("logic", "diff-impact")
                        or required_change_type == "behavior_change"
                    )
                    else "L2"
                )
                ticket = DemotionTicket(
                    run_id=self.manager.run_id,
                    slice_id=str(finding.get("slice_id", finding.get("file", ""))).strip(),
                    source="REVIEW",
                    target_layer=target,
                    origin_layer="L3",
                    hop_trace=["L3", target],
                    severity=severity if severity in ("BLOCKER", "MAJOR", "MINOR") else "MINOR",
                    diagnosis=str(
                        finding.get("description", finding.get("issue", "Quality issue"))
                    ),
                    failing_files=[finding.get("file", "")] if finding.get("file") else [],
                    evidence_refs=[self._run_report_relpath("code_quality_report.json")],
                )
                finding_refs = finding.get("evidence_refs", [])
                if isinstance(finding_refs, list):
                    ticket.evidence_refs.extend(
                        str(ref) for ref in finding_refs if str(ref).strip()
                    )
                file_hint = str(finding.get("file", "")).strip()
                apply_result = demotion_manager.apply(
                    ticket,
                    slice_root=self._resolve_demotion_slice_root(file_hint),
                )
                tickets.append({"ticket": ticket.to_dict(), "apply_result": apply_result})

        if tickets:
            self._write_run_report("code_quality_demotion_tickets.json", tickets)

        return {
            "files_reviewed": len(evidence_rows),
            "total_findings": len(all_findings),
            "report_path": self._run_report_relpath("code_quality_report.json"),
            "demotion_tickets": len(tickets),
            "demotion_tickets_applied": sum(
                1 for row in tickets if bool((row.get("apply_result") or {}).get("applied", False))
            ),
        }

    # ------------------------------------------------------------------
    # Governance helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _layer_literal(value: str) -> Literal["L1", "L2", "L3"]:
        normalized = str(value).strip().upper()
        if normalized == "L2":
            return "L2"
        if normalized == "L3":
            return "L3"
        return "L1"

    def _governance_strict_mode_enabled(self) -> bool:
        return bool(self.governance_strict_mode)

    @staticmethod
    def _governance_finding(
        message: str,
        *,
        level: Literal["FAIL", "WARN"],
        checkpoint: str,
    ) -> dict[str, Any]:
        return {
            "level": level,
            "checkpoint": checkpoint,
            "message": message,
        }

    def _emit_governance_failure_ticket(
        self,
        *,
        gate: str,
        layer: str,
        diagnosis: str,
        evidence_refs: list[str],
    ) -> dict[str, Any]:
        """Persist a governance failure ticket for run-level hard stops."""
        from spec_manager.orchestration.demotion import DemotionTicket

        normalized_layer = self._layer_literal(layer)
        ticket = DemotionTicket(
            run_id=self.manager.run_id,
            slice_id="__pipeline__",
            source="ALGORITHMIC_GATE" if normalized_layer == "L1" else "ARCH_GATE",
            category="governance",
            gate=gate,
            origin_layer=normalized_layer,
            target_layer=normalized_layer,
            severity="BLOCKER",
            diagnosis=diagnosis[:500],
            evidence_refs=[str(ref).strip() for ref in evidence_refs if str(ref).strip()],
        )
        # Run-level governance failures are not applied to a single slice patch path.
        ticket.apply_status = "APPLIED"

        tickets_dir = self._demotion_tickets_dir()
        tickets_dir.mkdir(parents=True, exist_ok=True)
        ticket_path = tickets_dir / f"{ticket.ticket_id}.json"
        ticket_path.write_text(
            json.dumps(
                {
                    "ticket": ticket.to_dict(),
                    "result": {
                        "applied": False,
                        "patches": [],
                        "gap_evidence_added": 0,
                        "note": "governance hard-stop ticket (run-level)",
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return {"ticket": ticket.to_dict(), "ticket_path": str(ticket_path)}

    def _latest_bundle_paths_by_slice(self, bundle_paths: list[Path]) -> list[Path]:
        latest: dict[str, tuple[int, Path]] = {}
        for bundle_path in bundle_paths:
            slice_id = bundle_path.parent.parent.name
            try:
                iteration = int(bundle_path.parent.name.split("_")[-1])
            except (TypeError, ValueError):
                iteration = -1
            prev = latest.get(slice_id)
            if prev is None or iteration > prev[0]:
                latest[slice_id] = (iteration, bundle_path)
        return [payload[1] for _, payload in sorted(latest.items())]

    def _open_governance_fail_findings(self, *, bundle_paths: list[Path]) -> list[str]:
        """Scan latest per-slice evidence for unresolved governance FAIL findings."""
        findings: set[str] = set()
        for bundle_path in self._latest_bundle_paths_by_slice(bundle_paths):
            bundle_data = self._read_json_dict(bundle_path)
            if not bundle_data:
                continue
            slice_id = str(bundle_data.get("slice_id") or bundle_path.parent.parent.name).strip()
            iteration_dir = bundle_path.parent

            verification_ref = str((bundle_data.get("verification") or {}).get("path", "")).strip()
            if verification_ref:
                verification_payload = self._read_json_payload(iteration_dir / verification_ref)
                rows = (
                    verification_payload.get("findings", [])
                    if isinstance(verification_payload, dict)
                    else []
                )
                for row in rows if isinstance(rows, list) else []:
                    if not isinstance(row, dict):
                        continue
                    category = str(row.get("category", "")).strip().lower()
                    dimension = str(row.get("dimension", "")).strip().upper()
                    if category != "governance" and dimension != "GOVERNANCE":
                        continue
                    severity = str(row.get("severity", "MINOR")).strip().upper()
                    if severity not in {"BLOCKER", "MAJOR"}:
                        continue
                    evidence = str(
                        row.get("evidence") or row.get("description") or "governance finding"
                    )
                    findings.add(f"{slice_id}: open governance FAIL ({severity}) - {evidence}")

            quality_receipts = self._read_json_payload(iteration_dir / "quality.receipts.json")
            receipt_rows = (
                quality_receipts.get("receipts", []) if isinstance(quality_receipts, dict) else []
            )
            for receipt in receipt_rows if isinstance(receipt_rows, list) else []:
                if not isinstance(receipt, dict):
                    continue
                dimension = str(receipt.get("dimension", "")).strip().upper()
                status = str(receipt.get("status", "")).strip().upper()
                if dimension == "GOVERNANCE" and status == "FAIL":
                    reviewer_id = str(receipt.get("reviewer_id", "governance-reviewer")).strip()
                    findings.add(
                        f"{slice_id}: open governance FAIL from quality receipt {reviewer_id}"
                    )

        return sorted(findings)

    def _alignment_artifact_findings(self, *, checkpoint: str, reports_dir: Path) -> list[str]:
        findings: list[str] = []
        checkpoint_key = checkpoint.lower().strip()
        requires_alignment = checkpoint_key in {"transition_l1_l2", "transition_l2_l3", "final"}
        if not requires_alignment:
            return findings

        component_manifest = reports_dir / "component_manifest.json"
        if not component_manifest.exists():
            findings.append("Component manifest artifact missing")
        else:
            manifest_payload = self._read_json_payload(component_manifest)
            components = (
                manifest_payload.get("components", []) if isinstance(manifest_payload, dict) else []
            )
            if not isinstance(components, list):
                findings.append("Component manifest payload is invalid")
            elif not components:
                findings.append("Component manifest has no components")

        alignment_report = reports_dir / "alignment_report.json"
        if not alignment_report.exists():
            findings.append("POWER alignment artifact missing")
        else:
            alignment_payload = self._read_json_payload(alignment_report)
            if not isinstance(alignment_payload, dict):
                findings.append("POWER alignment artifact unreadable")

        return findings

    def _final_receipt_completeness_findings(self, *, bundle_paths: list[Path]) -> list[str]:
        findings: list[str] = []
        latest_paths = self._latest_bundle_paths_by_slice(bundle_paths)
        if not latest_paths:
            return ["Final governance receipt completeness: no slice bundles found"]

        for bundle_path in latest_paths:
            bundle_data = self._read_json_dict(bundle_path)
            if not bundle_data:
                findings.append(f"{bundle_path.parent.parent.name}: bundle unreadable")
                continue
            slice_id = str(bundle_data.get("slice_id") or bundle_path.parent.parent.name).strip()
            iteration_dir = bundle_path.parent

            integration_ref = str((bundle_data.get("integration") or {}).get("path", "")).strip()
            if not integration_ref:
                findings.append(f"{slice_id}: integration receipt missing")
            else:
                integration_payload = self._read_json_payload(iteration_dir / integration_ref)
                ci_tick = (
                    integration_payload.get("ci_tick")
                    if isinstance(integration_payload, dict)
                    else None
                )
                if not isinstance(ci_tick, dict):
                    findings.append(f"{slice_id}: integration receipt missing ci_tick details")
                else:
                    if not bool(ci_tick.get("triggered", False)):
                        findings.append(f"{slice_id}: CI tick not triggered")
                    ci_error = str(ci_tick.get("error", "")).strip()
                    if ci_error:
                        findings.append(f"{slice_id}: CI tick error present ({ci_error})")
                    ci_receipt = ci_tick.get("receipt")
                    if not isinstance(ci_receipt, dict) or not ci_receipt:
                        findings.append(f"{slice_id}: CI tick receipt missing")
                    elif bool(ci_receipt.get("failed", False)):
                        findings.append(f"{slice_id}: CI tick receipt failed=true")

            tests_ref = str((bundle_data.get("tests") or {}).get("slice_path", "")).strip()
            if not tests_ref:
                findings.append(f"{slice_id}: slice test receipt missing")
            else:
                test_payload = self._read_json_payload(iteration_dir / tests_ref)
                result_payload = (
                    test_payload.get("result") if isinstance(test_payload, dict) else None
                )
                if not isinstance(result_payload, dict):
                    findings.append(f"{slice_id}: slice test receipt missing result payload")

            verification_ref = str((bundle_data.get("verification") or {}).get("path", "")).strip()
            if not verification_ref:
                findings.append(f"{slice_id}: verification receipt missing")
            elif not (iteration_dir / verification_ref).exists():
                findings.append(
                    f"{slice_id}: verification receipt path missing ({verification_ref})"
                )

        return findings

    def _decision_injection_findings(self, *, run_dir: Path) -> list[str]:
        findings: list[str] = []
        approvals_dir = run_dir / "approvals"
        if not approvals_dir.exists():
            return ["Approvals directory missing"]

        for decision_path in approvals_dir.rglob("*.json"):
            rel = str(decision_path.relative_to(approvals_dir)).replace("\\", "/")
            is_allowed = (
                (rel.startswith("l1/iteration_") and rel.endswith("/decision.json"))
                or rel == "l2/decision.json"
                or rel == "l3/decision.json"
            )
            if not is_allowed:
                findings.append(
                    f"Decision-injection pattern detected: unauthorized decision file {rel}"
                )
                continue
            payload = self._read_json_dict(decision_path)
            if not payload:
                findings.append(f"Decision artifact unreadable: {rel}")
                continue
            expected_layer = rel.split("/", 1)[0]
            recorded_layer = str(payload.get("layer", "")).strip().lower()
            if recorded_layer and recorded_layer != expected_layer:
                findings.append(
                    f"Decision artifact layer mismatch for {rel}: "
                    f"expected {expected_layer}, got {recorded_layer}"
                )

        return findings

    def _run_governance_check(
        self,
        checkpoint: str,
        *,
        check_artifacts: bool = False,
        check_report: bool = False,
    ) -> dict[str, Any]:
        """Run governance validation at a pipeline checkpoint."""
        run_id = self.manager.run_id
        workspace = self.manager.workspace_path
        run_dir = workspace / ".pdd_runs" / run_id
        reports_dir = workspace / "reports" / "pdd" / run_id
        findings: list[dict[str, Any]] = []
        checkpoint_key = checkpoint.lower().strip()
        strict_mode = self._governance_strict_mode_enabled()

        def add_findings(messages: list[str], *, level: Literal["FAIL", "WARN"]) -> None:
            for message in messages:
                findings.append(
                    self._governance_finding(message, level=level, checkpoint=checkpoint)
                )

        bundle_paths = self._iter_bundle_paths()
        if check_artifacts:
            if not bundle_paths:
                add_findings(["No evidence bundles found in slices directory"], level="FAIL")
            else:
                integrity_errors = 0
                for bundle_path in bundle_paths:
                    try:
                        bundle_data = json.loads(bundle_path.read_text(encoding="utf-8"))
                    except Exception as exc:
                        add_findings(
                            [f"Unreadable evidence bundle: {bundle_path.name} ({exc})"],
                            level="FAIL",
                        )
                        integrity_errors += 1
                        continue
                    issues = self._bundle_integrity_issues(bundle_data, bundle_path=bundle_path)
                    if issues:
                        integrity_errors += 1
                        parent_name = bundle_path.parent.name
                        grandparent_name = bundle_path.parent.parent.name
                        scoped_issues = [
                            f"{grandparent_name}/{parent_name}: {issue}" for issue in issues
                        ]
                        add_findings(scoped_issues, level="FAIL")
                if integrity_errors > 0:
                    add_findings(
                        [f"{integrity_errors} bundle(s) failed integrity checks"], level="FAIL"
                    )

            demotions_dir = run_dir / "demotions"
            if not demotions_dir.exists():
                add_findings(["Demotions directory missing"], level="WARN")

            add_findings(
                self._approval_artifact_findings(checkpoint=checkpoint, run_dir=run_dir),
                level="FAIL",
            )
            add_findings(
                self._alignment_artifact_findings(checkpoint=checkpoint, reports_dir=reports_dir),
                level="FAIL",
            )
            add_findings(
                self._open_governance_fail_findings(bundle_paths=bundle_paths),
                level="FAIL",
            )

            if checkpoint_key == "final":
                run_summary_path = reports_dir / "run_summary.json"
                add_findings(
                    self._run_summary_artifact_findings(
                        run_summary_path=run_summary_path,
                        workspace=workspace,
                    ),
                    level="FAIL",
                )
                add_findings(
                    self._final_receipt_completeness_findings(bundle_paths=bundle_paths),
                    level="FAIL",
                )
                add_findings(
                    self._decision_injection_findings(run_dir=run_dir),
                    level="FAIL",
                )

        if check_report:
            report_path = reports_dir / "final_report.md"
            if not report_path.exists():
                add_findings(["Final report missing"], level="FAIL")
            scorecard_path = reports_dir / "scorecard.json"
            if not scorecard_path.exists():
                add_findings(["Scorecard JSON missing"], level="FAIL")
            if checkpoint_key == "final":
                run_summary_path = reports_dir / "run_summary.json"
                if not run_summary_path.exists():
                    add_findings(["Run summary JSON missing"], level="FAIL")
            if report_path.exists():
                add_findings(self._report_content_findings(report_path), level="FAIL")

        fail_count = sum(1 for finding in findings if finding.get("level") == "FAIL")
        warn_count = sum(1 for finding in findings if finding.get("level") == "WARN")
        passed = fail_count == 0 and (warn_count == 0 or not strict_mode)

        blocking_findings = [
            finding
            for finding in findings
            if finding.get("level") == "FAIL" or (strict_mode and finding.get("level") == "WARN")
        ]
        error = "; ".join(str(finding.get("message", "")).strip() for finding in blocking_findings)
        return {
            "checkpoint": checkpoint,
            "passed": passed,
            "strict_mode": strict_mode,
            "fail_count": fail_count,
            "warn_count": warn_count,
            "findings": findings,
            "error": error,
        }

    def _approval_artifact_findings(self, *, checkpoint: str, run_dir: Path) -> list[str]:
        """Validate semantic approval requirements for a checkpoint."""
        findings: list[str] = []
        checkpoint_key = checkpoint.lower().strip()
        approvals_dir = run_dir / "approvals"

        requires_l1 = checkpoint_key in {"transition_l1_l2", "transition_l2_l3", "final"}
        requires_l2 = checkpoint_key in {"transition_l2_l3", "final"} and self.mode == "interactive"

        if requires_l1:
            l1_decision, l1_path = self._latest_l1_approval(approvals_dir)
            if not l1_decision:
                findings.append("L1 approval artifact missing")
            else:
                if not bool(l1_decision.get("approved")):
                    findings.append("L1 approval artifact records unapproved decision")
                decision_mode = str(l1_decision.get("mode", ""))
                if decision_mode and decision_mode != self.mode:
                    findings.append(
                        f"L1 approval mode mismatch: expected {self.mode}, found {decision_mode}"
                    )
                if self.mode == "interactive" and bool(l1_decision.get("auto_approved")):
                    findings.append("L1 interactive approval was auto-approved")
                if not l1_path.exists():
                    findings.append("L1 approval decision file missing")

        if requires_l2:
            l2_path = approvals_dir / "l2" / "decision.json"
            l2_decision = self._read_json_dict(l2_path)
            if not l2_decision:
                findings.append("Interactive mode requires L2 checkpoint decision artifact")
            elif not bool(l2_decision.get("approved")):
                findings.append("L2 checkpoint decision is not approved")

        return findings

    def _run_summary_artifact_findings(
        self, *, run_summary_path: Path, workspace: Path
    ) -> list[str]:
        """Validate required artifact completeness from run_summary.json manifest."""
        if not run_summary_path.exists():
            return ["Run summary JSON missing"]

        try:
            run_summary = json.loads(run_summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"Run summary JSON unreadable: {exc}"]
        if not isinstance(run_summary, dict):
            return ["Run summary JSON payload is not an object"]

        artifacts = run_summary.get("artifacts")
        if not isinstance(artifacts, list):
            return ["Run summary missing artifacts manifest list"]

        findings: list[str] = []
        required_seen = 0
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                findings.append("Run summary artifacts manifest contains non-object entry")
                continue
            if not bool(artifact.get("required", False)):
                continue
            required_seen += 1
            artifact_id = str(artifact.get("artifact_id", "artifact")).strip() or "artifact"
            path_str = str(artifact.get("path", "")).strip()
            if not path_str:
                findings.append(f"Run summary required artifact '{artifact_id}' missing path")
                continue
            artifact_path = Path(path_str)
            if not artifact_path.is_absolute():
                artifact_path = workspace / artifact_path

            kind = str(artifact.get("kind", "file")).lower()
            if kind == "dir":
                if not artifact_path.exists() or not artifact_path.is_dir():
                    findings.append(
                        f"Run summary required directory missing: {artifact_id} ({path_str})"
                    )
                    continue
                glob_pattern = str(artifact.get("glob", "")).strip()
                min_entries_raw = artifact.get("min_entries", 1)
                try:
                    min_entries = max(0, int(min_entries_raw))
                except (TypeError, ValueError):
                    min_entries = 1
                if glob_pattern:
                    entry_count = len(list(artifact_path.glob(glob_pattern)))
                else:
                    entry_count = len(list(artifact_path.iterdir()))
                if entry_count < min_entries:
                    findings.append(
                        f"Run summary required directory underfilled: {artifact_id} "
                        f"({path_str}, expected >= {min_entries}, found {entry_count})"
                    )
                continue

            if not artifact_path.exists() or not artifact_path.is_file():
                findings.append(f"Run summary required file missing: {artifact_id} ({path_str})")
                continue
            non_empty_required = bool(artifact.get("non_empty_required", True))
            if non_empty_required and artifact_path.stat().st_size <= 0:
                findings.append(f"Run summary required file is empty: {artifact_id} ({path_str})")

        if required_seen == 0:
            findings.append("Run summary artifacts manifest has no required entries")
        return findings

    def _report_content_findings(self, report_path: Path) -> list[str]:
        """Validate that the final report contains required governance sections."""
        findings: list[str] = []
        try:
            report_text = report_path.read_text(encoding="utf-8")
        except OSError as exc:
            return [f"Final report unreadable: {exc}"]

        required_sections = (
            "## Executive Summary",
            "## Architecture Topology",
            "## Scorecard",
            "## POWER Alignment",
            "## Approval Checkpoints",
            "## Demotion Summary",
            "## Known Risks / Unresolved Issues",
            "## Evidence Links",
        )
        for section in required_sections:
            if section not in report_text:
                findings.append(f"Final report missing section: {section}")

        approval_rows = (
            "L1 Mandatory Approval",
            "L2 Architecture Checkpoint",
            "L3 Release Signoff",
        )
        for row in approval_rows:
            if row not in report_text:
                findings.append(f"Final report missing approval checkpoint row: {row}")

        if "Detailed artifact:" not in report_text or "alignment_report.json" not in report_text:
            findings.append("POWER alignment artifact reference missing from final report")

        return findings

    @staticmethod
    def _read_json_payload(path: Path) -> dict[str, Any] | list[Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if isinstance(payload, (dict, list)):
            return payload
        return {}

    @staticmethod
    def _read_json_dict(path: Path) -> dict[str, Any]:
        payload = PddLifecycle._read_json_payload(path)
        return payload if isinstance(payload, dict) else {}

    def _latest_l1_approval(self, approvals_dir: Path) -> tuple[dict[str, Any], Path]:
        """Return the latest L1 decision artifact payload and path."""
        l1_root = approvals_dir / "l1"
        candidates = sorted(
            l1_root.glob("iteration_*/decision.json"),
            key=self._iteration_sort_key,
        )
        if not candidates:
            return {}, l1_root / "decision.json"
        latest_path = candidates[-1]
        return self._read_json_dict(latest_path), latest_path

    @staticmethod
    def _iteration_sort_key(path: Path) -> int:
        try:
            return int(path.parent.name.split("_")[-1])
        except (TypeError, ValueError):
            return -1

    # ------------------------------------------------------------------
    # CI helpers
    # ------------------------------------------------------------------

    def _run_readiness_ci(self, layer: Layer) -> dict[str, Any]:
        """Run downstream readiness smoke + baseline on a layer's dirty worktree.

        Args:
            layer: The layer whose dirty worktree to test.

        Returns:
            Dict with ``passed`` bool, tier results, and optional ``error``.
        """
        from spec_manager.orchestration.test_tiers import TierConfig, TierRunner

        if not self.worktree_manager:
            return {"passed": True, "note": "No worktree manager — skipping readiness CI"}

        dirty_path = self._resolve_layer_worktree(layer, "dirty")
        if not dirty_path or not dirty_path.exists():
            return {"passed": True, "note": f"No dirty worktree for {layer}"}

        runner = TierRunner(config=TierConfig(), cwd=dirty_path)
        tier_results = runner.run_for_tiers(layer, [0, 1])
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

    def _read_git_sha(self) -> str | None:
        """Resolve HEAD SHA for provenance when available."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.manager.structure.root,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return None
        sha = result.stdout.strip()
        return sha or None

    def _record_git_ref(self, ref_name: str) -> bool:
        """Record a git ref milestone for the run and create a real git ref.

        Creates/moves the git ref at current HEAD via the VCS abstraction and
        writes metadata to the run directory for pipeline timeline auditing.

        Args:
            ref_name: Ref name (e.g., ``pdd/<run_id>/base``).

        Returns:
            True when the git ref was created/updated successfully.
        """
        head_sha = self._read_git_sha()
        ref_created = False
        ref_error = ""

        vcs = self.worktree_manager.vcs if self.worktree_manager else None
        if vcs is None:
            try:
                from spec_manager.vcs.operations import GitVcs

                vcs = GitVcs(repo_root=self.manager.workspace_path)
            except Exception as exc:
                ref_error = f"Unable to initialize VCS helper: {exc}"

        if not head_sha:
            ref_error = ref_error or "Unable to resolve HEAD SHA"
        elif vcs is not None:
            try:
                update_result = vcs.update_ref(ref_name, head_sha)
                if isinstance(update_result, tuple) and len(update_result) == 2:
                    ok, err = update_result
                else:
                    ok, err = False, f"Unexpected update_ref return value: {update_result!r}"
            except Exception as exc:
                ok, err = False, str(exc)
            ref_created = bool(ok)
            ref_error = str(err)
            if not ref_created:
                logger.warning("Failed to create git ref '%s': %s", ref_name, ref_error)

        import time

        if hasattr(self, "_state_mgr"):
            refs_dir = self._state_mgr.run_dir / "refs"
            refs_dir.mkdir(parents=True, exist_ok=True)
            ref_data = {
                "ref": ref_name,
                "run_id": self.manager.run_id,
                "timestamp": time.time(),
                "head_sha": head_sha or "",
                "git_ref_created": ref_created,
                "git_ref_error": ref_error,
            }
            (refs_dir / f"{ref_name.replace('/', '_')}.json").write_text(
                json.dumps(ref_data, indent=2), encoding="utf-8"
            )

        return ref_created

    def _record_git_tag(self, tag_name: str) -> bool:
        """Record a git tag milestone for the run and create a real git tag."""
        head_sha = self._read_git_sha()
        tag_created = False
        tag_error = ""

        vcs = self.worktree_manager.vcs if self.worktree_manager else None
        if vcs is None:
            try:
                from spec_manager.vcs.operations import GitVcs

                vcs = GitVcs(repo_root=self.manager.workspace_path)
            except Exception as exc:
                tag_error = f"Unable to initialize VCS helper: {exc}"

        if not head_sha:
            tag_error = tag_error or "Unable to resolve HEAD SHA"
        elif vcs is not None:
            existing_tag_sha = vcs.rev_parse(f"refs/tags/{tag_name}")
            if existing_tag_sha:
                if existing_tag_sha == head_sha:
                    tag_created = True
                else:
                    tag_error = (
                        f"Tag '{tag_name}' exists at {existing_tag_sha}, expected {head_sha}"
                    )
            else:
                try:
                    tag_result = vcs.create_tag(
                        tag_name,
                        head_sha,
                        message=f"PDD milestone tag for run {self.manager.run_id}",
                    )
                    if isinstance(tag_result, tuple) and len(tag_result) == 2:
                        ok, err = tag_result
                    else:
                        ok, err = False, f"Unexpected create_tag return value: {tag_result!r}"
                except Exception as exc:
                    ok, err = False, str(exc)
                tag_created = bool(ok)
                tag_error = str(err)

            if not tag_created:
                logger.warning("Failed to create git tag '%s': %s", tag_name, tag_error)

        import time

        if hasattr(self, "_state_mgr"):
            refs_dir = self._state_mgr.run_dir / "refs"
            refs_dir.mkdir(parents=True, exist_ok=True)
            tag_data = {
                "tag": tag_name,
                "run_id": self.manager.run_id,
                "timestamp": time.time(),
                "head_sha": head_sha or "",
                "git_tag_created": tag_created,
                "git_tag_error": tag_error,
            }
            (refs_dir / f"{tag_name.replace('/', '_')}.json").write_text(
                json.dumps(tag_data, indent=2), encoding="utf-8"
            )

        return tag_created

    def _resolve_demotion_slice_root(self, file_hint: str) -> Path:
        """Resolve best-effort slice root for demotion ticket materialization."""
        workspace_raw = self.manager.workspace_path
        workspace = workspace_raw if isinstance(workspace_raw, Path) else Path(str(workspace_raw))
        spec_snapshot_raw = getattr(self.manager.structure, "spec_snapshot_dir", workspace)
        spec_snapshot = spec_snapshot_raw if isinstance(spec_snapshot_raw, Path) else workspace
        hint = str(file_hint).strip()
        if hint:
            hint_path = Path(hint)
            candidates: list[Path] = []
            if hint_path.is_absolute():
                candidates.append(hint_path)
            else:
                candidates.append(spec_snapshot / hint_path)
                candidates.append(workspace / hint_path)
            for candidate in candidates:
                if candidate.is_file():
                    return candidate.parent
                if candidate.is_dir():
                    return candidate
        if spec_snapshot.exists():
            return spec_snapshot
        return workspace

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

    def _bundle_integrity_issues(
        self,
        bundle_data: dict[str, Any],
        *,
        bundle_path: Path | None = None,
    ) -> list[str]:
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

        if bundle_path is not None:
            iteration_dir = bundle_path.parent
            required_refs = (
                ("manifest.path", str((bundle_data.get("manifest") or {}).get("path", "")).strip()),
                ("diff.path", str((bundle_data.get("diff") or {}).get("path", "")).strip()),
                (
                    "implementation.result_path",
                    str((bundle_data.get("implementation") or {}).get("result_path", "")).strip(),
                ),
                (
                    "promotion.path",
                    str((bundle_data.get("promotion") or {}).get("path", "")).strip(),
                ),
                ("gates.path", str((bundle_data.get("gates") or {}).get("path", "")).strip()),
                (
                    "integration.path",
                    str((bundle_data.get("integration") or {}).get("path", "")).strip(),
                ),
                (
                    "tests.slice_path",
                    str((bundle_data.get("tests") or {}).get("slice_path", "")).strip(),
                ),
                (
                    "verification.path",
                    str((bundle_data.get("verification") or {}).get("path", "")).strip(),
                ),
                (
                    "pins_snapshot.path",
                    str((bundle_data.get("pins_snapshot") or {}).get("path", "")).strip(),
                ),
                (
                    "graph_snapshot.path",
                    str((bundle_data.get("graph_snapshot") or {}).get("path", "")).strip(),
                ),
            )
            for label, rel_path in required_refs:
                if not rel_path:
                    issues.append(f"{label} missing")
                    continue
                artifact_path = iteration_dir / rel_path
                if not artifact_path.exists():
                    issues.append(f"{label} artifact missing: {rel_path}")

            for rel_path in (bundle_data.get("manifest") or {}).get("generated_files", []) or []:
                rel_value = str(rel_path).strip()
                if not rel_value:
                    continue
                if not (iteration_dir / rel_value).exists():
                    issues.append(f"manifest.generated_files artifact missing: {rel_value}")

            integration_ref = str((bundle_data.get("integration") or {}).get("path", "")).strip()
            if integration_ref:
                integration_payload = self._read_json_payload(iteration_dir / integration_ref)
                if isinstance(integration_payload, dict):
                    ci_tick = integration_payload.get("ci_tick")
                    if not isinstance(ci_tick, dict):
                        issues.append("integration report missing ci_tick payload")
                    else:
                        if not bool(ci_tick.get("triggered", False)):
                            issues.append("integration ci_tick.triggered is false")
                        ci_error = str(ci_tick.get("error", "")).strip()
                        if ci_error:
                            issues.append(f"integration ci_tick error present: {ci_error}")
                        ci_receipt = ci_tick.get("receipt")
                        if not isinstance(ci_receipt, dict) or not ci_receipt:
                            issues.append("integration ci_tick receipt missing")
                        elif bool(ci_receipt.get("failed", False)):
                            issues.append("integration ci_tick receipt failed=true")
                else:
                    issues.append("integration report unreadable")

            under_spec_events = (bundle_data.get("implementation") or {}).get(
                "under_spec_events"
            ) or []
            under_spec = bundle_data.get("under_spec") or {}
            decision_activity = bool(under_spec_events or under_spec.get("decisions"))
            decision_ref = str(under_spec.get("path", "")).strip()
            if decision_activity and not decision_ref:
                issues.append("under_spec decision activity present but under_spec.path missing")
            if decision_ref:
                decision_path = iteration_dir / decision_ref
                if not decision_path.exists():
                    issues.append(f"under_spec decision log artifact missing: {decision_ref}")
                else:
                    decision_payload = self._read_json_payload(decision_path)
                    if not isinstance(decision_payload, dict):
                        issues.append(f"under_spec decision log unreadable: {decision_ref}")
                    elif "decisions" not in decision_payload and "blockers" not in decision_payload:
                        issues.append(
                            f"under_spec decision log missing decisions/blockers sections: "
                            f"{decision_ref}"
                        )
                    impl_ref = str(
                        (bundle_data.get("implementation") or {}).get("result_path", "")
                    ).strip()
                    impl_path = iteration_dir / impl_ref if impl_ref else None
                    if (
                        impl_path is not None
                        and impl_path.exists()
                        and decision_path.stat().st_mtime < impl_path.stat().st_mtime
                    ):
                        issues.append(
                            "under_spec decision log stale relative to implementation result"
                        )

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
