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
        max_parallel: int = 1,
        integrate_full_test_every_n_iterations: int = 5,
        refinement_max_issues: int = 0,
        qa_enforcement: Literal["hard", "soft"] = "hard",
        qa_min_pass_rate: float = 1.0,
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
                from spec_manager.planner.constraints.bootstrap import (
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

            # L2: Architecture
            pass_outcome["l2"] = self._run_layer("l2")
            self._record_git_ref(f"pdd/{self.manager.run_id}/l2/clean")
            if self.mode == "interactive":
                pass_outcome["l2_checkpoint"] = self._request_l2_checkpoint(pass_outcome["l2"])
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

            # L3: Clean Code
            pass_outcome["l3"] = self._run_layer("l3")
            self._record_git_ref(f"pdd/{self.manager.run_id}/l3/clean")
            state_mgr.update_state(
                layers_completed=["l1", "l2", "l3"],
                phase="qa",
                active_layer="",
            )

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
            results["release_blocked"] = True
            results["release_blocked_reason"] = "Final governance gate failed"
            state_mgr.update_state(phase="blocked_final_governance")
            return results

        # Release signoff (auto-approve in auto mode)
        results["release_signoff"] = self._request_release_signoff(results)
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
        release_path_ready = bool(results["merge_tag"].get("merged", False)) or bool(
            results["merge_tag"].get("release_branch_created", False)
        )
        if not (release_path_ready and bool(results["merge_tag"].get("tagged", False))):
            results["release_blocked"] = True
            mt = results["merge_tag"]
            err = mt.get("merge_error") or mt.get("tag_error")
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
                    source="GATE_FAILURE",
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

    def _run_global_connectivity_check(self) -> dict[str, Any]:
        """Run global P6 connectivity check over clean-root code."""
        from spec_manager.analysis.adjacency.runner import (
            AdjacencyAnalysisConfig,
            run_adjacency_analysis,
        )

        source_root = self.manager.workspace_path
        if self.worktree_manager is not None:
            clean_root = self.worktree_manager._layer_worktrees.get("l3", {}).get("clean")
            if clean_root is not None and Path(clean_root).exists():
                source_root = clean_root

        try:
            report = run_adjacency_analysis(
                AdjacencyAnalysisConfig(source_dirs=[source_root], spec_dirs=[source_root])
            )
            disconnected = len(report.disconnected_warnings or [])
            return {
                "passed": disconnected == 0 and report.total_nodes > 0,
                "total_nodes": report.total_nodes,
                "total_edges": report.total_edges,
                "num_components": report.num_components,
                "disconnected_warnings": list(report.disconnected_warnings or []),
                "source_root": str(source_root),
            }
        except Exception as exc:
            logger.warning("Global connectivity check failed: %s", exc, exc_info=True)
            return {"passed": False, "error": str(exc), "source_root": str(source_root)}

    def _run_global_lineage_check(self) -> dict[str, Any]:
        """Run global P7 lineage completeness check over clean-root code."""
        from spec_manager.projection.lineage.builder import (
            AtomDefinition,
            LineageBuilder,
            scan_imports_from_directory,
        )

        source_root = self.manager.workspace_path
        if self.worktree_manager is not None:
            clean_root = self.worktree_manager._layer_worktrees.get("l3", {}).get("clean")
            if clean_root is not None and Path(clean_root).exists():
                source_root = clean_root

        try:
            import_records = scan_imports_from_directory(source_root)
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
                    "source_root": str(source_root),
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
                "source_root": str(source_root),
            }
        except Exception as exc:
            logger.warning("Global lineage check failed: %s", exc, exc_info=True)
            return {"passed": False, "error": str(exc), "source_root": str(source_root)}

    def _run_clean_root_full_tests(self) -> dict[str, Any]:
        """Run clean-root full test suite as a global termination gate."""
        from spec_manager.core.testing.registry import TestRunnerRegistry

        root = self.manager.workspace_path
        if self.worktree_manager is not None:
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
        results["entry_refinement"] = refinement_method()

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
            rework_mode = _LAYER_LIFECYCLE_MODE.get(from_layer, "build")
            round_result["rework"] = self._run_slices_at_layer(
                from_layer,
                lifecycle_mode=rework_mode,
            )
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
            results["governance_blocked"] = True
            results["error"] = (
                f"Transition {from_layer}→{to_layer} blocked by governance gate: "
                f"{governance.get('error', '')}"
            )
            return results

        # Propagate clean → next layer's dirty
        if self.worktree_manager:
            merge_prop = self.worktree_manager.propagate_clean_to_next_layer(from_layer)
            prop = merge_prop
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

            if not merge_prop.success:
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
                    prop = rebase_prop
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
                else:
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
                    conflict_slice_ids = self._infer_conflict_slice_ids(
                        to_layer, combined_conflicts
                    )
                    propagation["error"] = f"{merge_error}; {rebase_error}"
                    propagation["conflict_files"] = combined_conflicts

                    conflict_report_name = (
                        f"transition_{from_layer}_{to_layer}_propagation_conflict.json"
                    )
                    conflict_report_payload = {
                        "from_layer": from_layer,
                        "to_layer": to_layer,
                        "strategy": "merge_then_rebase_fallback",
                        "merge_error": merge_error,
                        "rebase_error": rebase_error,
                        "conflict_files": combined_conflicts,
                        "affected_slices": conflict_slice_ids,
                    }
                    self._write_run_report(conflict_report_name, conflict_report_payload)
                    conflict_report_ref = self._run_report_relpath(conflict_report_name)

                    demotion_summary = self._emit_transition_conflict_demotions(
                        from_layer=from_layer,
                        to_layer=to_layer,
                        conflict_files=combined_conflicts,
                        merge_error=merge_error,
                        rebase_error=rebase_error,
                        evidence_ref=conflict_report_ref,
                    )
                    propagation["demotion_tickets"] = demotion_summary.get("demotion_tickets", 0)
                    propagation["affected_slices"] = demotion_summary.get("affected_slices", [])

                    results["propagation_conflict"] = {
                        **conflict_report_payload,
                        **demotion_summary,
                        "conflict_report_path": conflict_report_ref,
                    }
                    results["governance_blocked"] = True
                    results["escalation_required"] = True
                    results["error"] = (
                        f"Transition {from_layer}→{to_layer} blocked by unresolved propagation "
                        f"conflicts: {propagation['error']}"
                    )

            results["propagation"] = propagation

            # Downstream readiness CI: smoke test on the new dirty worktree
            if prop.success:
                readiness = self._run_readiness_ci(to_layer)
                results["readiness_ci"] = readiness
                if not readiness.get("passed", True):
                    results["readiness_blocked"] = True
                    results["governance_blocked"] = True
                    results["escalation_required"] = True
                    readiness_error = str(
                        readiness.get("error") or "Downstream readiness CI failed"
                    )
                    results["error"] = (
                        f"Transition {from_layer}→{to_layer} blocked by downstream readiness CI: "
                        f"{readiness_error}"
                    )
                    logger.warning(
                        "Downstream readiness CI failed for %s dirty — transition %s→%s blocked",
                        to_layer,
                        from_layer,
                        to_layer,
                    )

        return results

    @staticmethod
    def _normalize_conflict_path(path: str) -> str:
        """Normalize conflict paths for stable matching."""
        normalized = str(path or "").strip().replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized.strip()

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

    def _emit_transition_conflict_demotions(
        self,
        *,
        from_layer: Layer,
        to_layer: Layer,
        conflict_files: list[str],
        merge_error: str,
        rebase_error: str,
        evidence_ref: str,
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
                "merge and rebase conflict-recovery attempts."
            ),
            "Downstream work must be regenerated from the updated upstream baseline.",
        ]
        if merge_error:
            diagnosis_parts.append(f"merge_error={merge_error}")
        if rebase_error:
            diagnosis_parts.append(f"rebase_error={rebase_error}")
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
            ticket = DemotionTicket(
                run_id=self.manager.run_id,
                slice_id=slice_id,
                source="GATE_FAILURE",
                gate=gate_name,
                target_layer=target_layer,
                origin_layer=origin_layer,
                hop_trace=[origin_layer, target_layer],
                severity="BLOCKER",
                diagnosis=diagnosis,
                failing_files=failing_files,
                evidence_refs=[evidence_ref] if evidence_ref else [],
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
    ) -> dict[str, Any]:
        """Discover slices and run PromotionLoop at a given layer.

        Creates coordination infrastructure (WorkItemStore, WakeQueue,
        MonitorRegistry, MonitorExecutor, WaitGraph) per layer and passes
        them to the ReactivePromotionScheduler.

        Args:
            layer: Which layer to run slices at.
            lifecycle_mode: PromotionLoop lifecycle mode for this layer pass.

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
            lifecycle_mode=lifecycle_mode,
            workspace_root=str(self.manager.workspace_path),
            config=self._build_run_context_config(),
        )

        planner = self._build_planner()

        loop = PromotionLoop(
            worktree_manager=self.worktree_manager,
            workspace_manager=self.manager,
            branch_manager=self.manager.branches,
            workspace_root=self.manager.workspace_path,
            planner=planner,
        )

        # Build coordination infrastructure
        monitor_executor, wake_queue = self._build_coordination(layer, run_context)

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

        def record_ci_tick(slice_id: str, *, trigger: str) -> None:
            wm = self.worktree_manager
            if wm is None:
                return

            with ci_tick_lock:
                tick = wm.tick_pipeline(
                    active_layer=layer,
                    max_pending_batches=max_pending_batches,
                    run_gates=run_gates,
                    run_tests=run_tests,
                )
                ci_ticks.append(
                    {
                        "slice_id": slice_id,
                        "trigger": trigger,
                        "main_updated": tick.main_updated,
                        "demotions": len(tick.demotion_tickets),
                    }
                )
                ci_tick_slices.add(slice_id)

                layer_batch: Any | None = None
                layer_results = getattr(tick, "layer_results", None)
                if isinstance(layer_results, dict):
                    layer_batch = layer_results.get(layer)

                candidate_sha = getattr(layer_batch, "candidate_sha", None)
                base_clean_sha = getattr(layer_batch, "base_clean_sha", None)

                # Write CI batch receipt
                if hasattr(self, "_state_mgr"):
                    batch_dir = self._state_mgr.run_dir / "ci" / layer / "batches"
                    batch_dir.mkdir(parents=True, exist_ok=True)
                    batch_id = f"batch_{trigger}_{slice_id}_{len(ci_ticks)}"
                    receipt = {
                        "batch_id": batch_id,
                        "slice_id": slice_id,
                        "trigger": trigger,
                        "layer": layer,
                        "main_updated": tick.main_updated,
                        "demotions": len(tick.demotion_tickets),
                        "candidate_sha": candidate_sha,
                        "base_clean_sha": base_clean_sha,
                    }
                    receipt_path = batch_dir / f"{batch_id}.json"
                    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

        def on_slice_merge(slice_id: str) -> None:
            normalized = str(slice_id).strip()
            if not normalized:
                return
            record_ci_tick(normalized, trigger="post_merge")

        def on_periodic_tick() -> None:
            nonlocal periodic_tick_counter
            periodic_tick_counter += 1
            record_ci_tick(f"periodic-{periodic_tick_counter}", trigger="periodic")

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

        scheduler = ReactivePromotionScheduler(
            loop=loop,
            config=SchedulerConfig(
                max_parallel=self.max_parallel,
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
                            files_raw = comp.get("files", [])
                            files = [str(path) for path in files_raw if isinstance(path, str)]
                            # Determine worktree path from component's files
                            wt_path = str(self.manager.structure.spec_snapshot_dir)
                            if files:
                                first_file = Path(files[0])
                                if first_file.parent != Path("."):
                                    wt_path = str(
                                        self.manager.structure.spec_snapshot_dir / first_file.parent
                                    )
                            owned_entrypoints_raw = comp.get("owned_entrypoints", [])
                            pins_consumed_raw = comp.get("pins_consumed", [])
                            upstream_raw = comp.get("upstream", [])
                            downstream_raw = comp.get("downstream", [])
                            slice_refs.append(
                                SliceRef(
                                    slice_id=f"arch-{comp_id}",
                                    layer=layer,
                                    library_id=str(comp_id),
                                    worktree_path=wt_path,
                                    metadata={
                                        "component_id": str(comp_id),
                                        "owned_entrypoints": [
                                            str(item)
                                            for item in owned_entrypoints_raw
                                            if isinstance(item, str)
                                        ],
                                        "pins_consumed": [
                                            str(item)
                                            for item in pins_consumed_raw
                                            if isinstance(item, str)
                                        ],
                                        "upstream": [
                                            str(item)
                                            for item in upstream_raw
                                            if isinstance(item, str)
                                        ],
                                        "downstream": [
                                            str(item)
                                            for item in downstream_raw
                                            if isinstance(item, str)
                                        ],
                                        "files": files,
                                    },
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
            self._write_approval_artifact("l3", approved=True, checkpoint="release_signoff")
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
        self._write_approval_artifact("l3", approved=approved, checkpoint="release_signoff")
        return {"approved": approved, "mode": "interactive"}

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
            findings.extend(
                self._approval_artifact_findings(checkpoint=checkpoint, run_dir=run_dir)
            )
            if checkpoint.lower().strip() == "final":
                run_summary_path = reports_dir / "run_summary.json"
                findings.extend(
                    self._run_summary_artifact_findings(
                        run_summary_path=run_summary_path,
                        workspace=workspace,
                    )
                )

        if check_report:
            report_path = reports_dir / "final_report.md"
            if not report_path.exists():
                findings.append("Final report missing")
            scorecard_path = reports_dir / "scorecard.json"
            if not scorecard_path.exists():
                findings.append("Scorecard JSON missing")
            if checkpoint.lower().strip() == "final":
                run_summary_path = reports_dir / "run_summary.json"
                if not run_summary_path.exists():
                    findings.append("Run summary JSON missing")
            if report_path.exists():
                findings.extend(self._report_content_findings(report_path))

        passed = len(findings) == 0
        return {
            "checkpoint": checkpoint,
            "passed": passed,
            "findings": findings,
            "error": "; ".join(findings) if findings else "",
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
    def _read_json_dict(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
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
