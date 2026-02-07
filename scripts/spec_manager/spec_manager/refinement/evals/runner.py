"""Evaluation runner for spec refinement system.

Orchestrates evaluation of sequence specs through the refinement pipeline,
tracking metrics, detecting loops, and generating reports.
"""

from __future__ import annotations

import contextlib
import math
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.core.project_root import resolve_from_root
from spec_manager.refinement.evals.checkpoint import CheckpointManager, EvalCheckpoint
from spec_manager.refinement.evals.inputs.ground_truth import PhaseGroundTruth
from spec_manager.refinement.evals.inputs.sequence_spec import SequenceSpec, load_sequence_spec
from spec_manager.refinement.evals.logger import EvalLogger
from spec_manager.refinement.evals.loop_detector import LoopDetector, LoopStatus
from spec_manager.refinement.evals.metrics import (
    DetailCaptureMetrics,
    PhaseMetrics,
    analyze_convergence,
    score_detail_capture,
)
from spec_manager.refinement.evals.report import EvalReport, EvalResult, save_report

if TYPE_CHECKING:
    from spec_manager.refinement.interactive.signal_resolver import SignalResolver


@dataclass
class EvalConfig:
    """Configuration for evaluation runs.

    Attributes:
        spec_ids: List of spec IDs to evaluate. If None, evaluates all.
        checkpoint_dir: Directory for checkpoints.
        output_dir: Directory for reports and logs.
        max_iterations_per_phase: Maximum iterations per phase.
        stagnation_threshold: Number of stagnant iterations to detect loop.
        convergence_threshold: Ratio threshold for convergence.
        fuzzy_match_threshold: Threshold for fuzzy string matching.
        parallel: Whether to evaluate specs in parallel.
        use_real_workflows: Whether to use real workflow extraction instead of simulation.
        workspace_temp_dir: Optional temp directory for real workflow workspaces.
        resolve_ambiguities: Whether to run post-phase ambiguity resolution.
    """

    spec_ids: list[str] | None = None
    checkpoint_dir: Path = field(
        default_factory=lambda: resolve_from_root("runs", "evals", "checkpoints")
    )
    output_dir: Path = field(default_factory=lambda: resolve_from_root("runs", "evals", "reports"))
    max_iterations_per_phase: int = 10
    stagnation_threshold: int = 3
    convergence_threshold: float = 0.95
    fuzzy_match_threshold: float = 0.6
    parallel: bool = False
    use_real_workflows: bool = False
    workspace_temp_dir: Path | None = None
    sparse: bool = False
    resolve_ambiguities: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "spec_ids": self.spec_ids,
            "checkpoint_dir": str(self.checkpoint_dir),
            "output_dir": str(self.output_dir),
            "max_iterations_per_phase": self.max_iterations_per_phase,
            "stagnation_threshold": self.stagnation_threshold,
            "convergence_threshold": self.convergence_threshold,
            "fuzzy_match_threshold": self.fuzzy_match_threshold,
            "parallel": self.parallel,
            "use_real_workflows": self.use_real_workflows,
            "workspace_temp_dir": str(self.workspace_temp_dir) if self.workspace_temp_dir else None,
            "sparse": self.sparse,
            "resolve_ambiguities": self.resolve_ambiguities,
        }


@dataclass
class EvalState:
    """State for a single spec evaluation.

    Attributes:
        spec: The sequence spec being evaluated.
        run_id: Unique identifier for this evaluation run.
        current_phase: Current phase being evaluated.
        iteration: Current iteration within the phase.
        loop_detector: Loop detector for the current phase.
        detail_metrics: Accumulated detail metrics.
        convergence_trajectory: Convergence ratios per iteration.
        bottlenecks: Identified bottlenecks.
        errors: Errors encountered.
        workspace_integration: Optional workspace integration for real workflows.
        workspace_manager: Optional workspace manager for real workflows.
    """

    spec: SequenceSpec
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    current_phase: str | None = None
    iteration: int = 0
    loop_detector: LoopDetector = field(default_factory=LoopDetector)
    detail_metrics: DetailCaptureMetrics = field(default_factory=DetailCaptureMetrics)
    convergence_trajectory: list[float] = field(default_factory=list)
    bottlenecks: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    workspace_integration: Any = None  # WorkspaceIntegration when using real workflows
    workspace_manager: Any = None  # WorkspaceManager when using real workflows


# Phase names in evaluation order
EVAL_PHASES = [
    "sectionization",
    "summarization",
    "library_synthesis",
    "evidence_expansion",
    "spec_building",
    "architecture",
    "interfaces",
    "tasks",
]


class EvalRunner:
    """Runner for spec refinement evaluation.

    Orchestrates evaluation of specs through phases, tracking metrics,
    detecting loops, and managing checkpoints.

    Attributes:
        config: Evaluation configuration.
        checkpoint_manager: Checkpoint manager for persistence.
        fixtures_dir: Directory containing spec fixtures.
    """

    def __init__(
        self,
        config: EvalConfig,
        fixtures_dir: Path | None = None,
        signal_resolver: SignalResolver | None = None,
    ) -> None:
        """Initialize the eval runner.

        Args:
            config: Evaluation configuration.
            fixtures_dir: Directory containing spec fixtures.
            signal_resolver: Optional ``SignalResolver`` for ambiguity resolution.
        """
        self.config = config
        self.checkpoint_manager = CheckpointManager(config.checkpoint_dir)
        self.fixtures_dir = fixtures_dir or resolve_from_root(
            "scripts", "spec_manager", "spec_manager", "refinement", "evals", "inputs", "fixtures"
        )
        self._signal_resolver = signal_resolver

    def run(self) -> EvalReport:
        """Run evaluation on all configured specs.

        Returns:
            EvalReport with results for all specs.
        """
        run_id = f"eval_{uuid.uuid4().hex[:8]}"
        report = EvalReport(run_id=run_id)

        # Load specs to evaluate
        specs = self._load_specs()
        if not specs:
            report.recommendations.append("No specs found to evaluate.")
            return report

        # Evaluate each spec
        for spec in specs:
            result = self._evaluate_spec(spec, run_id)
            report.add_result(result)

        # Compute aggregates and save
        report.compute_aggregates()
        save_report(report, self.config.output_dir, f"eval_report_{run_id}")

        return report

    def run_single(self, spec_id: str) -> EvalResult:
        """Run evaluation on a single spec.

        Args:
            spec_id: ID of the spec to evaluate.

        Returns:
            EvalResult for the spec.
        """
        run_id = f"eval_{spec_id}_{uuid.uuid4().hex[:8]}"
        spec = self._load_spec(spec_id)
        if spec is None:
            return EvalResult(
                spec_id=spec_id,
                spec_title="Unknown",
                success=False,
                errors=[f"Spec not found: {spec_id}"],
            )
        return self._evaluate_spec(spec, run_id)

    def resume(self, run_id: str) -> EvalReport | None:
        """Resume an interrupted evaluation run.

        Args:
            run_id: Run ID to resume.

        Returns:
            EvalReport if resumed successfully, None otherwise.
        """
        checkpoint = self.checkpoint_manager.load(run_id)
        if checkpoint is None:
            return None

        # Reload spec and continue from checkpoint
        spec = self._load_spec(checkpoint.spec_id)
        if spec is None:
            return None

        # Create report with resumed state
        report = EvalReport(run_id=run_id)
        result = self._evaluate_spec_from_checkpoint(spec, checkpoint)
        report.add_result(result)
        report.compute_aggregates()

        return report

    def _load_specs(self) -> list[SequenceSpec]:
        """Load specs to evaluate based on config."""
        from spec_manager.refinement.evals.inputs.sequence_spec import load_sequence_specs_from_dir

        all_specs = load_sequence_specs_from_dir(self.fixtures_dir)

        if self.config.spec_ids:
            return [spec for spec in all_specs if spec.spec_id in self.config.spec_ids]
        return [spec for spec in all_specs if not spec.spec_id.endswith("_sparse")]

    def _load_spec(self, spec_id: str) -> SequenceSpec | None:
        """Load a single spec by ID."""
        for suffix in [".yaml", ".yml", ".json"]:
            path = self.fixtures_dir / f"{spec_id}{suffix}"
            if path.exists():
                return load_sequence_spec(path)
        return None

    def _evaluate_spec(self, spec: SequenceSpec, run_id: str) -> EvalResult:
        """Evaluate a single spec through all phases.

        Args:
            spec: Spec to evaluate.
            run_id: Run identifier.

        Returns:
            EvalResult for the spec.
        """
        state = EvalState(spec=spec, run_id=run_id)

        # Sparse-to-dense evaluation mode
        if self.config.sparse and spec.sparse_spec_path:
            return self._evaluate_sparse_to_dense(spec, state, run_id)

        logger = EvalLogger(
            self.config.output_dir / f"{run_id}_{spec.spec_id}.log.jsonl",
            spec_id=spec.spec_id,
        )

        # Create checkpoint
        checkpoint = self.checkpoint_manager.create_checkpoint(
            run_id=f"{run_id}_{spec.spec_id}",
            spec_id=spec.spec_id,
            config=self.config.to_dict(),
        )

        logger.log_eval_start(config=self.config.to_dict())
        start_time = time.perf_counter()

        result = EvalResult(
            spec_id=spec.spec_id,
            spec_title=spec.title,
            phases_total=len(EVAL_PHASES),
        )

        try:
            for phase in EVAL_PHASES:
                phase_metrics = self._evaluate_phase(state, phase, logger, checkpoint)
                result.phase_results[phase] = phase_metrics
                state.detail_metrics.add_phase_metrics(phase_metrics)
                result.phases_completed += 1

                if not phase_metrics.converged:
                    # For real workflows, the phase ran once and the recall
                    # gap reflects what the single pass missed — not
                    # stagnation.  For simulation, the iteration loop adds
                    # its own specific bottleneck (cycling, stagnant, etc.).
                    if self.config.use_real_workflows:
                        recall_pct = int(phase_metrics.detail_score.recall * 100)
                        result.bottlenecks.append(f"{phase}:incomplete({recall_pct}%)")
                    else:
                        result.bottlenecks.append(f"{phase}:stagnation")

        except Exception as exc:
            result.success = False
            result.errors.append(str(exc))
            logger.log_error(state.current_phase, "exception", str(exc))

        finally:
            # Clean up workspace integration if using real workflows
            if state.workspace_integration is not None:
                with contextlib.suppress(Exception):
                    state.workspace_integration.cleanup()
                # Best effort cleanup

        # Finalize
        result.total_duration_ms = (time.perf_counter() - start_time) * 1000
        result.detail_metrics = state.detail_metrics
        result.convergence_analysis = analyze_convergence(
            state.convergence_trajectory,
            convergence_threshold=self.config.convergence_threshold,
        )
        result.bottlenecks.extend(state.bottlenecks)
        result.errors.extend(state.errors)

        logger.log_eval_end(success=result.success, summary=result.to_dict())

        return result

    def _evaluate_sparse_to_dense(
        self,
        spec: SequenceSpec,
        state: EvalState,
        run_id: str,
    ) -> EvalResult:
        """Evaluate sparse-to-dense steering for a spec.

        Loads the sparse spec, runs InteractiveWorkflow with steering,
        and scores the refined result against dense ground truth.

        Args:
            spec: The full (dense) SequenceSpec with ground truth.
            state: Evaluation state.
            run_id: Run identifier.

        Returns:
            EvalResult for the sparse-to-dense evaluation.
        """
        import time

        from spec_manager.refinement.evals.metrics import score_detail_capture

        start_time = time.perf_counter()
        result = EvalResult(
            spec_id=spec.spec_id,
            spec_title=f"{spec.title} (sparse-to-dense)",
            phases_total=1,
        )

        # Load sparse spec
        sparse_path = self.fixtures_dir / spec.sparse_spec_path
        if not sparse_path.exists():
            result.success = False
            result.errors.append(f"Sparse spec not found: {sparse_path}")
            return result

        sparse_spec = load_sequence_spec(sparse_path)

        # Run interactive workflow with steering
        steering_path = None
        if spec.steering_script_path:
            steering_path = self.fixtures_dir / spec.steering_script_path
            if not steering_path.exists():
                steering_path = None

        try:
            import tempfile

            from spec_manager.refinement.interactive.workflow import InteractiveWorkflow

            with tempfile.TemporaryDirectory() as tmpdir:
                workspace = Path(tmpdir)
                spec_file = workspace / "spec.md"
                spec_file.write_text(sparse_spec.to_markdown(), encoding="utf-8")

                # Determine resolver: explicit > steering-only > legacy
                resolver = self._signal_resolver
                if resolver is None and steering_path and steering_path.exists():
                    from spec_manager.refinement.interactive.signal_resolver import (
                        SteeringOnlyResolver,
                    )
                    from spec_manager.refinement.interactive.steering.steering_script import (
                        SteeringScript,
                    )

                    resolver = SteeringOnlyResolver(SteeringScript.from_file(steering_path))

                workflow = InteractiveWorkflow(
                    workspace=workspace,
                    interactive=False,
                    steering_path=steering_path if resolver is None else None,
                    max_iterations=5,
                    signal_resolver=resolver,
                )
                refined_text = workflow.run(sparse_spec.to_markdown())

                # Score refined text against dense ground truth
                expected = spec.ground_truth.get_all_expected_requirements()
                # Simple heuristic: check which requirements appear in refined text
                actual = [req for req in expected if req.lower() in refined_text.lower()]
                score = score_detail_capture(
                    expected, actual, fuzzy_threshold=self.config.fuzzy_match_threshold
                )

                result.phases_completed = 1
                result.detail_metrics = DetailCaptureMetrics()
                result.detail_metrics.add_phase_metrics(
                    PhaseMetrics(
                        phase_name="sparse_to_dense",
                        detail_score=score,
                        iterations=1,
                        converged=score.recall >= self.config.convergence_threshold,
                        duration_ms=(time.perf_counter() - start_time) * 1000,
                        gaps_open=score.expected_count - score.matched_count,
                        gaps_closed=score.matched_count,
                    )
                )

        except Exception as exc:
            result.success = False
            result.errors.append(f"Sparse-to-dense evaluation failed: {exc}")

        result.total_duration_ms = (time.perf_counter() - start_time) * 1000
        return result

    def _evaluate_spec_from_checkpoint(
        self,
        spec: SequenceSpec,
        checkpoint: EvalCheckpoint,
    ) -> EvalResult:
        """Continue evaluation from a checkpoint.

        Args:
            spec: Spec to evaluate.
            checkpoint: Checkpoint to resume from.

        Returns:
            EvalResult for the spec.
        """
        state = EvalState(spec=spec, run_id=checkpoint.run_id)
        logger = EvalLogger(
            self.config.output_dir / f"{checkpoint.run_id}.log.jsonl",
            spec_id=spec.spec_id,
        )

        start_time = time.perf_counter()
        result = EvalResult(
            spec_id=spec.spec_id,
            spec_title=spec.title,
            phases_total=len(EVAL_PHASES),
        )

        try:
            # Restore completed phase results
            for phase_name in checkpoint.get_completed_phases():
                phase_checkpoint = checkpoint.phases[phase_name]
                if phase_checkpoint.metrics:
                    result.phase_results[phase_name] = PhaseMetrics.from_dict(
                        phase_checkpoint.metrics
                    )
                    result.phases_completed += 1

            # Continue with remaining phases
            completed = set(checkpoint.get_completed_phases())
            for phase in EVAL_PHASES:
                if phase in completed:
                    continue

                phase_metrics = self._evaluate_phase(state, phase, logger, checkpoint)
                result.phase_results[phase] = phase_metrics
                state.detail_metrics.add_phase_metrics(phase_metrics)
                result.phases_completed += 1

        finally:
            # Clean up workspace integration if using real workflows
            if state.workspace_integration is not None:
                with contextlib.suppress(Exception):
                    state.workspace_integration.cleanup()
                # Best effort cleanup

        result.total_duration_ms = (time.perf_counter() - start_time) * 1000
        result.detail_metrics = state.detail_metrics
        result.convergence_analysis = analyze_convergence(
            state.convergence_trajectory,
            convergence_threshold=self.config.convergence_threshold,
        )

        return result

    def _evaluate_phase(
        self,
        state: EvalState,
        phase: str,
        logger: EvalLogger,
        checkpoint: EvalCheckpoint,
    ) -> PhaseMetrics:
        """Evaluate a single phase.

        Args:
            state: Evaluation state.
            phase: Phase name.
            logger: Logger for the evaluation.
            checkpoint: Checkpoint for persistence.

        Returns:
            PhaseMetrics for the phase.
        """
        state.current_phase = phase
        state.iteration = 0
        state.loop_detector.reset()

        logger.log_phase_start(phase)
        self.checkpoint_manager.update_phase_start(checkpoint, phase)

        start_time = time.perf_counter()
        converged = False
        gaps_open = 0
        gaps_closed = 0

        # Get ground truth for this phase - use phase-appropriate expected items
        ground_truth = state.spec.ground_truth.get_phase_ground_truth(phase)
        expected_items = self._get_expected_items_for_phase(ground_truth, phase)

        # Phase execution with convergence tracking
        actual_items: list[str] = []
        score = score_detail_capture(
            expected_items, [], fuzzy_threshold=self.config.fuzzy_match_threshold
        )

        # Real workflows run once per phase (the workflow itself handles any
        # internal iteration).  The eval iteration loop only makes sense for
        # simulation mode where we artificially increase coverage each round.
        max_iters = 1 if self.config.use_real_workflows else self.config.max_iterations_per_phase

        for iteration in range(1, max_iters + 1):
            state.iteration = iteration
            iter_start = time.perf_counter()

            # Extract actual items using real workflows or simulation
            if self.config.use_real_workflows:
                actual_items = self._extract_with_real_workflow(state, phase, iteration)
            else:
                actual_items = self._simulate_extraction(state, phase, iteration)

            # Score this iteration
            score = score_detail_capture(
                expected_items,
                actual_items,
                fuzzy_threshold=self.config.fuzzy_match_threshold,
            )

            # Track convergence
            convergence_ratio = score.recall
            state.convergence_trajectory.append(convergence_ratio)

            # Compute content hash for loop detection
            content_hash = LoopDetector.compute_hash(str(actual_items))
            loop_status = state.loop_detector.update(content_hash)

            iter_duration = (time.perf_counter() - iter_start) * 1000

            logger.log_iteration(
                phase=phase,
                iteration=iteration,
                gaps_open=len(expected_items) - score.matched_count,
                content_hash=content_hash,
                duration_ms=iter_duration,
                convergence_ratio=convergence_ratio,
            )

            self.checkpoint_manager.update_phase_iteration(
                checkpoint,
                phase,
                iteration,
                loop_detector=state.loop_detector,
            )

            # Check for convergence
            if convergence_ratio >= self.config.convergence_threshold:
                converged = True
                gaps_closed = score.matched_count
                gaps_open = score.expected_count - score.matched_count
                break

            # Check for loop conditions (only relevant in simulation mode)
            if loop_status in {LoopStatus.STAGNANT, LoopStatus.CYCLING}:
                logger.log_loop_warning(
                    phase=phase,
                    loop_status=loop_status.value,
                    iteration=iteration,
                    details={"hash": content_hash},
                )
                state.bottlenecks.append(f"{phase}:{loop_status.value}@{iteration}")
                break

            if loop_status == LoopStatus.MAX_ITERATIONS:
                state.bottlenecks.append(f"{phase}:max_iterations")
                break

        duration_ms = (time.perf_counter() - start_time) * 1000

        # Use the last score from the loop (avoids duplicate workflow calls)
        final_score = score

        # For real workflows that didn't converge, record the gap without
        # false stagnation/cycling signals.
        if not converged and self.config.use_real_workflows:
            gaps_open = score.expected_count - score.matched_count
            gaps_closed = score.matched_count

        metrics = PhaseMetrics(
            phase_name=phase,
            detail_score=final_score,
            iterations=state.iteration,
            converged=converged,
            duration_ms=duration_ms,
            gaps_open=gaps_open,
            gaps_closed=gaps_closed,
        )

        if converged:
            self.checkpoint_manager.update_phase_complete(checkpoint, phase, metrics)
        else:
            self.checkpoint_manager.update_phase_failed(
                checkpoint, phase, f"Did not converge after {state.iteration} iterations"
            )

        logger.log_phase_end(phase=phase, success=converged, metrics=metrics.to_dict())

        return metrics

    def _extract_with_real_workflow(
        self,
        state: EvalState,
        phase: str,
        iteration: int,
    ) -> list[str]:
        """Extract outputs using real workflow execution.

        Creates a workspace from the spec (if not already created), runs the
        actual phase workflow, and extracts outputs.

        For evaluation purposes, if outputs are successfully extracted even when
        the workflow reports partial failures, we mark the workspace phase as
        completed to allow downstream phases to run.

        Args:
            state: Evaluation state.
            phase: Phase name.
            iteration: Current iteration.

        Returns:
            List of extracted output strings.
        """
        from pathlib import Path as P

        from spec_manager.refinement.evals.workflow_integration import WorkspaceIntegration
        from spec_manager.refinement.workspace import Phase as WorkspacePhase
        from spec_manager.refinement.workspace import WorkspaceManager as WM
        from spec_manager.refinement.workspace.state import PhaseStatus

        # Initialize workspace integration if not already done
        if state.workspace_integration is None:
            state.workspace_integration = WorkspaceIntegration(
                temp_dir=self.config.workspace_temp_dir,
                cleanup_on_exit=True,
            )

        # Create workspace manager if not already done
        if state.workspace_manager is None:
            try:
                state.workspace_manager = state.workspace_integration.create_workspace_from_spec(
                    state.spec
                )
            except Exception as exc:
                state.errors.append(f"Failed to create workspace: {exc}")
                return []

        # Run the phase workflow (only on first iteration for each phase)
        if iteration == 1:
            try:
                workflow_result = state.workspace_integration.run_phase_workflow(
                    state.workspace_manager, phase
                )
                if not workflow_result.get("success", False):
                    error_msg = workflow_result.get("error", "Unknown error")
                    state.errors.append(f"Phase {phase} workflow failed: {error_msg}")
            except Exception as exc:
                state.errors.append(f"Phase {phase} workflow exception: {exc}")

            # CRITICAL: Reload workspace manager from disk after workflow execution.
            # The workflow creates its own WorkspaceManager instance which updates
            # state on disk. Our reference is now stale.
            try:
                state.workspace_manager = WM(
                    run_id=state.workspace_manager.run_id, input_folder=P(".")
                )
            except Exception as exc:
                state.errors.append(f"Failed to reload workspace manager: {exc}")

        # Extract outputs from workspace
        outputs: list[str] = []
        try:
            outputs = state.workspace_integration.extract_phase_outputs(
                state.workspace_manager, phase
            )
        except Exception as exc:
            state.errors.append(f"Failed to extract {phase} outputs: {exc}")

        # For eval purposes: force-complete the phase and all intermediate phases
        # that downstream workflows require. This ensures we can evaluate the full
        # pipeline even with partial failures.
        if iteration == 1:
            # Map eval phases to the workspace phases that need to be completed.
            # Downstream workflows check these intermediate phases.
            phase_chain = self._get_phase_completion_chain(phase)
            for ws_phase in phase_chain:
                try:
                    phase_result = state.workspace_manager.state.phases.get(ws_phase)
                    if phase_result is None or phase_result.status != PhaseStatus.COMPLETED:
                        state.workspace_manager.complete_phase(
                            WorkspacePhase(ws_phase),
                            outputs={"eval_forced": True, "has_outputs": bool(outputs)},
                        )
                except (ValueError, AttributeError, KeyError, OSError) as exc:
                    state.errors.append(f"Force-completion failed for {ws_phase}: {exc}")

        return outputs

    def _get_phase_completion_chain(self, eval_phase: str) -> list[str]:
        """Get all workspace phases to complete for an eval phase.

        The eval uses simplified 8-phase names, but the actual workflows have
        additional intermediate phases with their own completion requirements.
        This returns all phases that need to be force-completed to allow
        downstream workflows to run.

        Args:
            eval_phase: The eval phase name (sectionization, summarization, etc.)

        Returns:
            List of workspace phase names to complete (in order).
        """
        # Map eval phases to the chain of workspace phases that need completion.
        # Downstream workflows check these intermediate phases.
        phase_chains: dict[str, list[str]] = {
            "sectionization": ["sectionization"],
            "summarization": ["summarization"],
            "library_synthesis": ["library_synthesis"],
            "evidence_expansion": ["evidence_expansion"],
            "spec_building": [
                "spec_building",
                "spec_stabilization",
                "sublibrary_detection",
            ],
            "architecture": [
                "architecture_proposal",
                "architecture_selection",
                "architecture_mapping",
            ],
            "interfaces": [
                "library_structure_review",
                "interfaces",
            ],
            "tasks": ["tasks"],
        }
        return phase_chains.get(eval_phase, [eval_phase])

    def _simulate_extraction(
        self,
        state: EvalState,
        phase: str,
        iteration: int,
    ) -> list[str]:
        """Simulate requirement extraction for a phase.

        In a real implementation, this would call the actual phase workflow
        and extract requirements from the workspace. For evaluation purposes,
        we simulate gradual convergence based on iteration count.

        Args:
            state: Evaluation state.
            phase: Phase name.
            iteration: Current iteration.

        Returns:
            List of extracted requirement strings.
        """
        ground_truth = state.spec.ground_truth.get_phase_ground_truth(phase)
        expected = self._get_expected_items_for_phase(ground_truth, phase)
        if not expected:
            return []

        # Simulate gradual improvement: extract more items each iteration
        # This is a placeholder - real implementation would use actual extraction
        coverage = min(1.0, (iteration * 0.2) + 0.3)  # 50% at iter 1, 70% at iter 2, etc.
        num_to_return = math.ceil(len(expected) * coverage)

        # Return a subset of expected items to simulate extraction
        return expected[:num_to_return]

    def _get_expected_items_for_phase(
        self,
        ground_truth: PhaseGroundTruth | None,
        phase: str,
    ) -> list[str]:
        """Get the appropriate expected items for a phase.

        Different phases have different expected outputs: sectionization
        expects sections, library_synthesis expects libraries and requirements,
        etc.

        Args:
            ground_truth: PhaseGroundTruth object for the phase.
            phase: Phase name.

        Returns:
            List of expected item strings for scoring.
        """
        if ground_truth is None:
            return []

        # Map phases to their primary expected output types
        if phase == "sectionization":
            return ground_truth.expected_sections
        elif phase == "summarization":
            return ground_truth.expected_libraries
        elif phase == "library_synthesis":
            # Combine libraries and requirements for library synthesis
            return ground_truth.expected_libraries + ground_truth.expected_requirements
        elif phase == "spec_building":
            # Requirements and elements for spec building
            return ground_truth.expected_requirements + ground_truth.expected_elements
        elif phase == "tasks":
            return ground_truth.expected_tasks
        elif phase == "architecture":
            return ground_truth.expected_decisions
        elif phase == "interfaces":
            return ground_truth.expected_elements
        else:
            # Default to requirements for unknown phases
            return ground_truth.expected_requirements
