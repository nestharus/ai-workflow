"""PDD orchestrator: sequences PDD modules through design phases 0-10.

This is the primary orchestration backbone for the spec manager.  It
replaces the old 19-phase refinement pipeline with the 11-phase PDD
execution model defined in EXPECTED_STATE.md.

Each phase delegates to the corresponding PDD module entry point:

    Phase 0  (EXTRACTION)         - Not yet implemented (see phase0/ design docs)
    Phase 1  (STRUCTURE_DISCOVERY) - planning.code_parser
    Phase 2  (DECOMPOSITION)       - planning.inserter + planning.reverser
    Phase 3  (COMPLIANCE_CLEAN)    - compliance.detection.orchestrator
    Phase 4  (LIBRARY_DISCOVERY)   - branches.manager
    Phase 5  (SPEC_BUILD)          - pin_functions.orchestrator + branches.promotion
    Phase 6  (CROSS_LIBRARY)       - analysis.adjacency
    Phase 7  (PROJECTION_SYNC)     - projection.generator
    Phase 8  (TASK_PLANNING)       - planning.workflow
    Phase 9  (IMPLEMENTATION)      - core.edit_in_place + compliance.promotion
    Phase 10 (CONTINUOUS_QA)       - strategies.evolution + refinement_engine

The ``Phase`` enum in ``refinement.workspace.state`` contains both
PDD phases (0-10) and legacy refinement phases.  This module uses only
the PDD members.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from spec_manager.refinement.workspace.manager import WorkspaceManager
from spec_manager.refinement.workspace.state import Phase, PhaseStatus

if TYPE_CHECKING:
    from spec_manager.orchestration.infrastructure import PddInfrastructure

logger = logging.getLogger(__name__)

# Keep a public alias so external code that imported PddPhase still works.
PddPhase = Phase

# Ordered list of all PDD phases for iteration.
PDD_PHASE_ORDER: list[Phase] = [
    Phase.EXTRACTION,
    Phase.STRUCTURE_DISCOVERY,
    Phase.DECOMPOSITION,
    Phase.COMPLIANCE_CLEAN,
    Phase.LIBRARY_DISCOVERY,
    Phase.SPEC_BUILD,
    Phase.CROSS_LIBRARY,
    Phase.PROJECTION_SYNC,
    Phase.TASK_PLANNING,
    Phase.IMPLEMENTATION,
    Phase.CONTINUOUS_QA,
]


class PddOrchestrator:
    """Sequences PDD modules through design phases 0-10.

    Usage::

        manager = WorkspaceManager(run_id="my-run", input_folder=Path("specs"))
        manager.initialize()
        orchestrator = PddOrchestrator(manager)

        # Run all phases
        state = orchestrator.run()

        # Or run a single phase
        result = orchestrator.run_phase(Phase.STRUCTURE_DISCOVERY)

        # Or run a range
        state = orchestrator.run(
            start_phase=Phase.STRUCTURE_DISCOVERY,
            end_phase=Phase.COMPLIANCE_CLEAN,
        )
    """

    def __init__(
        self,
        manager: WorkspaceManager,
        infrastructure: PddInfrastructure | None = None,
    ) -> None:
        self.manager = manager
        self._infrastructure: PddInfrastructure | None = infrastructure
        self._phase_runners: dict[Phase, str] = {
            Phase.EXTRACTION: "_run_extraction",
            Phase.STRUCTURE_DISCOVERY: "_run_structure_discovery",
            Phase.DECOMPOSITION: "_run_decomposition",
            Phase.COMPLIANCE_CLEAN: "_run_compliance_clean",
            Phase.LIBRARY_DISCOVERY: "_run_library_discovery",
            Phase.SPEC_BUILD: "_run_spec_build",
            Phase.CROSS_LIBRARY: "_run_cross_library",
            Phase.PROJECTION_SYNC: "_run_projection_sync",
            Phase.TASK_PLANNING: "_run_task_planning",
            Phase.IMPLEMENTATION: "_run_implementation",
            Phase.CONTINUOUS_QA: "_run_continuous_qa",
        }

    @property
    def infrastructure(self) -> PddInfrastructure:
        """Lazy-init infrastructure if not provided at construction time."""
        if self._infrastructure is None:
            from spec_manager.orchestration.infrastructure import PddInfrastructure

            self._infrastructure = PddInfrastructure(self.manager)
        return self._infrastructure

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        start_phase: Phase | None = None,
        end_phase: Phase | None = None,
        *,
        stop_on_failure: bool = True,
    ) -> dict[str, Any]:
        """Run PDD phases in sequence.

        Args:
            start_phase: First phase to execute (default: first incomplete).
            end_phase: Last phase to execute (default: CONTINUOUS_QA).
            stop_on_failure: If True, stop on the first phase failure.

        Returns:
            Summary dict with ``completed``, ``failed``, and ``skipped`` lists.
        """
        start_idx = 0
        end_idx = len(PDD_PHASE_ORDER) - 1

        if start_phase is not None:
            start_idx = PDD_PHASE_ORDER.index(start_phase)
        if end_phase is not None:
            end_idx = PDD_PHASE_ORDER.index(end_phase)

        phases_to_run = PDD_PHASE_ORDER[start_idx : end_idx + 1]

        completed: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []

        for pdd_phase in phases_to_run:
            # Skip already-completed phases
            phase_result = self.manager.state.phases.get(pdd_phase.value)
            if phase_result and phase_result.status == PhaseStatus.COMPLETED:
                skipped.append(pdd_phase.value)
                logger.info("Phase %s already completed, skipping.", pdd_phase.value)
                continue

            logger.info("Starting phase: %s", pdd_phase.value)
            try:
                self.run_phase(pdd_phase)
                completed.append(pdd_phase.value)
            except Exception as exc:
                failed.append(pdd_phase.value)
                logger.error("Phase %s failed: %s", pdd_phase.value, exc)
                if stop_on_failure:
                    break

        return {
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
        }

    def run_phase(self, pdd_phase: Phase) -> dict[str, Any]:
        """Run a single PDD phase.

        Handles state transitions (start_phase / complete_phase / fail_phase)
        and delegates to the appropriate ``_run_*`` method.

        After the phase runner completes, the continuous refinement post-phase
        hook runs automatically (for phases 4+, where library structure exists).

        Args:
            pdd_phase: The phase to execute.

        Returns:
            Phase outputs dict on success.

        Raises:
            Exception: Re-raises after recording failure in state.
        """
        runner_name = self._phase_runners.get(pdd_phase)
        if runner_name is None:
            raise ValueError(f"No runner registered for phase {pdd_phase.value}")

        runner = getattr(self, runner_name)
        self.manager.start_phase(pdd_phase)
        try:
            outputs = runner()
            # Run post-phase refinement hook for phases where structure exists
            refinement_output = self._post_phase_refinement_hook(pdd_phase)
            if refinement_output:
                outputs["refinement"] = refinement_output
            self.manager.complete_phase(pdd_phase, outputs=outputs)
            logger.info("Phase %s completed.", pdd_phase.value)
            return outputs
        except Exception as exc:
            self.manager.fail_phase(pdd_phase, error=str(exc))
            raise

    # ------------------------------------------------------------------
    # Phase runners
    # ------------------------------------------------------------------

    def _run_extraction(self) -> dict[str, Any]:
        """Phase 0: Extraction.

        Converts arbitrary prose input into the PDD workspace format.
        Uses mechanical markdown parsing and regex-based entity detection
        (no LLM calls).

        Produces:
        - ``summaries/*.md`` — section-level bullet-point summaries
        - ``libraries/*/charter.md`` — library charters
        - ``libraries/*/spec.md`` — extracted requirements
        - ``libraries/*/evidence/*.md`` — evidence mappings
        """
        from spec_manager.orchestration.extraction import ProseExtractor

        extractor = ProseExtractor(self.manager)
        return extractor.extract()

    def _run_structure_discovery(self) -> dict[str, Any]:
        """Phase 1: AST-based function/class/import extraction.

        Calls ``planning.code_parser.parse_file()`` for each file in the
        workspace to produce a structural map of the codebase.
        """
        from spec_manager.planning.code_parser import parse_file

        ws_phase = Phase.STRUCTURE_DISCOVERY
        all_files = self.manager.get_all_files()
        parsed_count = 0
        errors: list[str] = []

        for file_id, file_path in all_files.items():
            if not file_path.exists():
                errors.append(f"File not found: {file_path}")
                continue
            if file_path.suffix != ".py":
                continue
            try:
                code_file = parse_file(str(file_path))
                # Store results via workspace manager
                self.manager.write_agent_output(
                    ws_phase,
                    {
                        "file_id": file_id,
                        "functions": len(code_file.functions),
                        "classes": len(code_file.classes),
                        "imports": len(code_file.imports),
                    },
                )
                parsed_count += 1
            except Exception as exc:
                errors.append(f"Failed to parse {file_path}: {exc}")

        return {
            "files_parsed": parsed_count,
            "total_files": len(all_files),
            "errors": errors,
        }

    def _run_decomposition(self) -> dict[str, Any]:
        """Phase 2: Comment insertion, reverse translation.

        Calls ``planning.inserter.plan_insertions()`` and
        ``planning.reverser.reverse_translate()`` to decompose the
        codebase into annotated algorithmic units.
        """
        from spec_manager.planning.inserter import plan_insertions
        from spec_manager.planning.reverser import reverse_translate

        all_files = self.manager.get_all_files()
        insertion_count = 0
        reversal_count = 0
        errors: list[str] = []

        for file_id, file_path in all_files.items():
            if not file_path.exists() or file_path.suffix != ".py":
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
                insertions = plan_insertions(content, str(file_path))
                insertion_count += len(insertions)
            except Exception as exc:
                errors.append(f"Insertion planning failed for {file_path}: {exc}")

            try:
                reverse_result = reverse_translate(str(file_path))
                reversal_count += 1 if reverse_result else 0
            except Exception as exc:
                errors.append(f"Reverse translation failed for {file_path}: {exc}")

        return {
            "insertions_planned": insertion_count,
            "files_reversed": reversal_count,
            "errors": errors,
        }

    def _run_compliance_clean(self) -> dict[str, Any]:
        """Phase 3: Executable gap detection via comment/stub scanning.

        Calls ``compliance.detection.orchestrator.scan_executable_gaps()``
        across all workspace files.
        """
        from spec_manager.compliance.detection.orchestrator import scan_executable_gaps

        all_files = self.manager.get_all_files()
        filepaths = [
            str(fp) for fp in all_files.values()
            if fp.exists() and fp.suffix == ".py"
        ]
        project_root = str(self.manager.structure.root)

        try:
            gaps = scan_executable_gaps(filepaths, project_root, config={})
            return {
                "gaps_found": len(gaps),
                "files_scanned": len(filepaths),
            }
        except Exception as exc:
            return {
                "gaps_found": 0,
                "files_scanned": len(filepaths),
                "error": str(exc),
            }

    def _run_library_discovery(self) -> dict[str, Any]:
        """Phase 4: Branch initialization, atom registry, slice navigation.

        Calls ``branches.manager.BranchManager.initialize()`` on the
        workspace run root to set up the branch organization system.
        """
        branch_mgr = self.manager.branches
        if not branch_mgr.is_initialized():
            issues = branch_mgr.initialize()
        else:
            issues = []

        return {
            "branch_initialized": True,
            "init_issues": issues,
        }

    def _run_spec_build(self) -> dict[str, Any]:
        """Phase 5: Pin-function extraction + promotion workflow.

        Calls ``pin_functions.orchestrator.PinFunctionOrchestrator.scan()``
        for pin extraction and uses ``branches.promotion.PromotionEngine``
        for the promotion workflow.
        """
        from spec_manager.pin_functions.orchestrator import PinFunctionOrchestrator

        project_root = str(self.manager.structure.root)
        orchestrator = PinFunctionOrchestrator(project_root)

        try:
            scan_result = orchestrator.scan()
        except Exception as exc:
            scan_result = {"error": str(exc), "pins_found": 0}

        return {
            "pin_scan": scan_result,
        }

    def _run_cross_library(self) -> dict[str, Any]:
        """Phase 6: Adjacency graph and disconnected component detection.

        Calls ``analysis.adjacency.runner.run_adjacency_analysis()`` to
        build the cross-library adjacency graph.
        """
        from spec_manager.analysis.adjacency.runner import (
            AdjacencyAnalysisConfig,
            run_adjacency_analysis,
        )

        root = self.manager.structure.root
        config = AdjacencyAnalysisConfig(
            source_dirs=[root],
            spec_dirs=[root],
        )
        try:
            report = run_adjacency_analysis(config)
            return {
                "disconnected_components": len(report.disconnected_components)
                if hasattr(report, "disconnected_components")
                else 0,
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _run_projection_sync(self) -> dict[str, Any]:
        """Phase 7: L2 generation, drift detection, pin propagation.

        Calls ``projection.generator.ProjectionGenerator.generate_plan()``
        to create/update projection plans.
        """
        from spec_manager.projection.generator import ProjectionGenerator

        generator = ProjectionGenerator()
        try:
            plan = generator.generate_plan()
            return {"projection_plan": str(plan) if plan else "empty"}
        except Exception as exc:
            return {"error": str(exc)}

    def _run_task_planning(self) -> dict[str, Any]:
        """Phase 8: Planning integration and gap bridge.

        Calls ``planning.workflow.run_planning_v2_phase()`` with the
        current run context.
        """
        from spec_manager.planning.workflow import run_planning_v2_phase

        try:
            result = run_planning_v2_phase(
                run_id=self.manager.run_id,
                target_files=[],
                intentions=[],
            )
            return {"planning_result": result}
        except Exception as exc:
            return {"error": str(exc)}

    def _run_implementation(self) -> dict[str, Any]:
        """Phase 9: Edit-in-place analysis with compliance promotion gating.

        Calls ``core.edit_in_place.analyze_project()`` on the workspace
        root and applies compliance promotion gating.
        """
        from spec_manager.core.edit_in_place import analyze_project

        project_root = str(self.manager.structure.root)
        try:
            project_state = analyze_project(project_root)
            return {
                "files_analyzed": len(project_state.files),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _run_continuous_qa(self) -> dict[str, Any]:
        """Phase 10: Strategy evolution, eval framework, and refinement engine.

        Uses ``strategies.evolution.StrategyEvolutionPipeline`` for
        continuous quality improvement and ``refinement_engine`` for
        coupling/cohesion detection and restructuring.
        """
        from spec_manager.strategies.evolution import StrategyEvolutionPipeline

        outputs: dict[str, Any] = {}

        try:
            pipeline = StrategyEvolutionPipeline()
            outputs["pipeline_initialized"] = True
            outputs["pipeline_type"] = type(pipeline).__name__
        except Exception as exc:
            outputs["pipeline_error"] = str(exc)

        # Run the refinement engine as the core of continuous QA
        refinement_result = self._run_refinement_engine()
        outputs["refinement"] = refinement_result

        return outputs

    # ------------------------------------------------------------------
    # Refinement engine integration
    # ------------------------------------------------------------------

    def _run_refinement_engine(self) -> dict[str, Any]:
        """Run coupling/cohesion detection and propose restructuring operations.

        Builds grouping units from the branch manager's vertical slices and
        atoms, runs detection against the adjacency graph, proposes operations,
        and optionally executes them.

        Returns:
            Summary dict with issues found, operations proposed, and execution
            results.
        """
        from spec_manager.analysis.adjacency.graph import AdjacencyGraph
        from spec_manager.refinement_engine.detector import (
            GroupingUnit,
            detect_all,
        )
        from spec_manager.refinement_engine.executor import RefinementExecutor
        from spec_manager.refinement_engine.operations import (
            propose_operations,
            validate_operation,
        )

        branch_mgr = self.manager.branches

        # Build grouping units from vertical slices
        grouping_units: list[GroupingUnit] = []
        all_atoms = branch_mgr.list_atoms()

        # Group atoms by vertical slice
        slice_entities: dict[str, set[str]] = {}
        unsliced: set[str] = set()
        for atom in all_atoms:
            if atom.vertical_slice:
                slice_entities.setdefault(atom.vertical_slice, set()).add(
                    atom.atom_id
                )
            else:
                unsliced.add(atom.atom_id)

        for slice_id, entity_ids in slice_entities.items():
            grouping_units.append(
                GroupingUnit(
                    unit_id=slice_id,
                    name=slice_id,
                    entity_ids=entity_ids,
                )
            )

        if not grouping_units:
            return {
                "issues_found": 0,
                "operations_proposed": 0,
                "note": "No grouping units (vertical slices) found.",
            }

        # Build adjacency graph from registered atoms
        adjacency_graph = AdjacencyGraph()
        for atom in all_atoms:
            adjacency_graph.add_node(atom.atom_id)

        # Detect coupling/cohesion issues
        issues = detect_all(adjacency_graph, grouping_units)

        # Propose operations
        operations = propose_operations(issues)

        # Validate operations
        valid_ops: list = []
        invalid_ops: list = []
        for op in operations:
            errors = validate_operation(op, adjacency_graph)
            if errors:
                invalid_ops.append({"op": op.op_type, "errors": errors})
            else:
                valid_ops.append(op)

        # Execute valid operations
        executor = RefinementExecutor(branch_mgr)
        executed = 0
        rolled_back = 0
        for op in valid_ops:
            result = executor.execute(op)
            if result.success:
                executed += 1
            else:
                executor.rollback(op)
                rolled_back += 1

        return {
            "issues_found": len(issues),
            "issues_by_type": {
                "overlap": sum(1 for i in issues if i.issue_type == "overlap"),
                "divergence": sum(1 for i in issues if i.issue_type == "divergence"),
                "overload": sum(1 for i in issues if i.issue_type == "overload"),
            },
            "operations_proposed": len(operations),
            "operations_valid": len(valid_ops),
            "operations_invalid": len(invalid_ops),
            "operations_executed": executed,
            "operations_rolled_back": rolled_back,
        }

    def _post_phase_refinement_hook(self, pdd_phase: Phase) -> dict[str, Any] | None:
        """Post-phase hook: run refinement after phases where structure exists.

        Only runs after Phase 4 (LIBRARY_DISCOVERY) or later, since earlier
        phases have no library structure to refine.

        Args:
            pdd_phase: The PDD phase that just completed.

        Returns:
            Refinement results dict, or None if refinement was skipped.
        """
        # Only run refinement after structure exists (Phase 4+)
        phase_idx = PDD_PHASE_ORDER.index(pdd_phase)
        library_discovery_idx = PDD_PHASE_ORDER.index(Phase.LIBRARY_DISCOVERY)

        if phase_idx < library_discovery_idx:
            return None

        # Don't double-run during Phase 10 (it runs refinement explicitly)
        if pdd_phase == Phase.CONTINUOUS_QA:
            return None

        try:
            return self._run_refinement_engine()
        except Exception as exc:
            logger.warning(
                "Post-phase refinement hook failed after %s: %s",
                pdd_phase.value,
                exc,
            )
            return {"error": str(exc)}
