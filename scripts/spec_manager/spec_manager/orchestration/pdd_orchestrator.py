"""PDD orchestrator: sequences PDD modules through design phases 0-10.

This is the primary orchestration backbone for the spec manager.  It
replaces the old 19-phase refinement pipeline with the 11-phase PDD
execution model defined in EXPECTED_STATE.md.

Each phase delegates to the corresponding PDD module entry point:

    Phase 0  (EXTRACTION)         - intake/ (routing-based restructuring)
    Phase 1  (STRUCTURE_DISCOVERY) - planning.models.parse_file + core.edit_in_place
    Phase 2  (DECOMPOSITION)       - planning.reverser (reverse translation)
    Phase 3  (COMPLIANCE_CLEAN)    - compliance.detection.orchestrator + gap queue
    Phase 4  (LIBRARY_DISCOVERY)   - branches.manager (collapse + atom registry)
    Phase 5  (SPEC_BUILD)          - pin_functions.orchestrator + branches.promotion
    Phase 6  (CROSS_LIBRARY)       - analysis.adjacency.runner
    Phase 7  (PROJECTION_SYNC)     - projection.lineage + analysis.generator + projection.generator
    Phase 8  (TASK_PLANNING)       - planning.workflow
    Phase 9  (IMPLEMENTATION)      - core.edit_in_place (gap analysis + report)
    Phase 10 (CONTINUOUS_QA)       - strategies.evolution + refinement_engine

The ``Phase`` enum in ``refinement.workspace.state`` contains both
PDD phases (0-10) and legacy refinement phases.  This module uses only
the PDD members.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from spec_manager.refinement.workspace.manager import WorkspaceManager
from spec_manager.refinement.workspace.state import Phase

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


class PromotionLoopRunner:
    """Compatibility wrapper for running slice batches via PromotionLoop."""

    def __init__(
        self,
        manager: WorkspaceManager,
        *,
        max_parallel: int = 4,
    ) -> None:
        self._manager = manager
        self._max_parallel = max_parallel

    def run_slices(
        self,
        *,
        slice_refs: list[Any],
        run_context: Any,
    ) -> dict[str, Any]:
        """Run discovered slices through PromotionLoop and return scheduler output."""
        from spec_manager.orchestration.promotion_loop import PromotionLoop
        from spec_manager.orchestration.promotion_scheduler import (
            PromotionScheduler,
            SchedulerConfig,
        )

        self._prepare_slice_worktrees(slice_refs)

        loop = PromotionLoop(
            workspace_manager=self._manager,
            branch_manager=self._manager.branches,
            workspace_root=self._manager.workspace_path,
        )
        scheduler = PromotionScheduler(
            loop=loop,
            config=SchedulerConfig(max_parallel=self._max_parallel),
        )
        sched_result = scheduler.run(slice_refs, run_context)
        return {
            "slice_results": sched_result.slice_results,
            "waiting_slices": sched_result.waiting_slices,
            "all_complete": sched_result.all_complete,
        }

    def _prepare_slice_worktrees(self, slice_refs: list[Any]) -> None:
        """Materialize isolated per-slice work directories for loop execution."""
        worktree_root = (
            self._manager.workspace_path
            / ".pdd_runs"
            / self._manager.run_id
            / "slice_worktrees"
            / "l1"
        )
        worktree_root.mkdir(parents=True, exist_ok=True)

        for ref in slice_refs:
            slice_id = str(getattr(ref, "slice_id", "")).strip()
            source_raw = str(getattr(ref, "worktree_path", "")).strip()
            if not slice_id or not source_raw:
                continue

            source = Path(source_raw)
            if not source.exists() or not source.is_dir():
                logger.warning(
                    "Skipping isolated slice worktree creation for '%s': source missing at %s",
                    slice_id,
                    source,
                )
                continue

            target = worktree_root / slice_id
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            ref.worktree_path = str(target)
            metadata = getattr(ref, "metadata", None)
            if isinstance(metadata, dict):
                metadata["source_slice_root"] = str(source)
            else:
                ref.metadata = {"source_slice_root": str(source)}


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
    ) -> None:
        self.manager = manager
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        start_phase: Phase | None = None,
        end_phase: Phase | None = None,
        *,
        stop_on_failure: bool = True,
        mode: str = "loop",
    ) -> dict[str, Any]:
        """Run PDD orchestration.

        Args:
            start_phase: Reserved legacy argument (sequential pipeline retired).
            end_phase: Reserved legacy argument (sequential pipeline retired).
            stop_on_failure: Reserved legacy argument (sequential pipeline retired).
            mode: Execution mode. Only ``"loop"`` is supported.

        Returns:
            Loop summary dict from :meth:`run_loop`.
        """
        if mode != "loop":
            raise ValueError(
                "PddOrchestrator sequential pipeline mode has been retired; use mode='loop'."
            )
        return self.run_loop()

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

    def run_loop(
        self,
        *,
        max_iterations: int = 20,
        run_extraction: bool = True,
    ) -> dict[str, Any]:
        """Run the per-slice iterative PromotionLoop.

        This is the new execution mode that replaces the sequential
        P0-P10 pipeline with a convergence loop per slice.

        Steps:
        1. Conditionally run Phase 0 if IntakeQueue is non-empty or
           ``run_extraction=True`` (first run).
        2. Discover slices (libraries) from workspace.
        3. Run PromotionLoop on each slice until convergence.
        4. Run global verification (P6/P7) after all slices complete.

        Args:
            max_iterations: Max convergence iterations per slice.
            run_extraction: Whether to run Phase 0 on first invocation.
                Subsequent invocations check IntakeQueue instead.

        Returns:
            Summary dict with slice results.
        """
        from spec_manager.orchestration.intake_queue import IntakeQueue
        from spec_manager.orchestration.promotion_loop import (
            RunContext,
            SliceRef,
        )

        results: dict[str, Any] = {"mode": "loop"}

        # 1. Run Phase 0 conditionally
        intake_queue = IntakeQueue(self.manager.workspace_path)
        needs_extraction = run_extraction or intake_queue.needs_phase0()

        if needs_extraction:
            # Drain intake queue items first
            queued_items = intake_queue.drain()
            if queued_items:
                from spec_manager.orchestration.intake_queue import route_items

                patches = route_items(queued_items, self.manager.workspace_path)
                results["intake_routed"] = len(patches)

            try:
                extraction_result = self.run_phase(Phase.EXTRACTION)
                results["extraction"] = extraction_result
            except Exception as exc:
                logger.warning("Phase 0 extraction failed: %s", exc)
                results["extraction"] = {"error": str(exc)}
        else:
            results["extraction"] = "skipped (intake queue empty)"

        # 2. Discover slices from workspace
        libraries_dir = self.manager.structure.libraries_dir
        slice_refs: list[SliceRef] = []

        if libraries_dir.exists():
            for lib_dir in sorted(libraries_dir.iterdir()):
                if lib_dir.is_dir():
                    slice_refs.append(
                        SliceRef(
                            slice_id=lib_dir.name,
                            layer="l1",
                            library_id=lib_dir.name,
                            worktree_path=str(lib_dir),
                        )
                    )

        if not slice_refs:
            results["note"] = "No libraries found — nothing to loop over."
            return results

        # 3. Run PromotionLoop on discovered slices (via scheduler)
        run_context = RunContext(
            run_id=self.manager.run_id,
            mode="auto",
            lifecycle_mode="build",
            workspace_root=str(self.manager.workspace_path),
            max_iterations=max_iterations,
        )
        runner = PromotionLoopRunner(self.manager, max_parallel=4)
        runner_result = runner.run_slices(slice_refs=slice_refs, run_context=run_context)
        slice_results = runner_result["slice_results"]

        results["slices"] = [
            {
                "slice_id": r.slice_id,
                "status": r.status,
                "iterations": r.iterations,
                "remaining_gaps": r.remaining_gaps,
                "demotion_count": len(r.demotion_tickets),
            }
            for r in slice_results
        ]
        results["waiting_slices"] = runner_result["waiting_slices"]

        # 4. Global verification (P6 + P7)
        all_complete = all(r.status in {"COMPLETE", "SKIPPED"} for r in slice_results)
        if all_complete:
            try:
                p6_result = self.run_phase(Phase.CROSS_LIBRARY)
                results["cross_library"] = p6_result
            except Exception as exc:
                logger.warning("P6 cross-library failed: %s", exc)
                results["cross_library"] = {"error": str(exc)}

            try:
                p7_result = self.run_phase(Phase.PROJECTION_SYNC)
                results["projection_sync"] = p7_result
            except Exception as exc:
                logger.warning("P7 projection sync failed: %s", exc)
                results["projection_sync"] = {"error": str(exc)}

        results["all_complete"] = all_complete
        return results

    # ------------------------------------------------------------------
    # Phase runners
    # ------------------------------------------------------------------

    def _run_extraction(self) -> dict[str, Any]:
        """Phase 0: Routing-based restructuring.

        Converts freeform prose input into the PDD workspace format using
        LLM-driven routing (NOT regex, NOT extraction).

        Steps:
        1. Summarize source files (LLM, for routing decisions only)
        2. Discover libraries from summaries (LLM)
        3. Route source spans to destinations (LLM + reimplementation test)
        4. Check coverage (deterministic)
        5. Assemble output by verbatim copy (deterministic)

        After Phase 0 completes, its output is installed into the workspace
        structure (libraries/, summaries/) so downstream phases and
        extraction methods can find it.
        """
        from spec_manager.intake import run_phase0

        source_dir = self.manager.structure.spec_snapshot_dir
        output_dir = self.manager.workspace_path / "phase0_output"
        result = run_phase0(source_dir, output_dir)

        # Install Phase 0 output into workspace structure
        self._install_phase0_output(output_dir)

        # Library quality validation (post-Phase 0 gate)
        try:
            from spec_manager.intake.quality.library_quality_validator import (
                validate_libraries,
            )

            quality_report = validate_libraries(
                self.manager.workspace_path,
                phase0_output_dir=output_dir,
            )
            result["library_quality"] = quality_report.to_dict()

            if not quality_report.gate_passed:
                logger.warning(
                    "Library quality gate failed: %s",
                    [d.name for d in quality_report.dimensions if not d.passed],
                )
                result["library_quality_passed"] = False
            else:
                result["library_quality_passed"] = True
        except Exception as exc:
            logger.warning("Library quality validation failed: %s", exc)
            result["library_quality"] = {"error": str(exc)}

        return result

    def _install_phase0_output(self, phase0_dir: Path) -> None:
        """Copy Phase 0 assembled output into the workspace directory structure.

        Phase 0 writes to its own output directory. The workspace structure
        (libraries/, summaries/) is where extraction methods and
        downstream phases look for content. This bridge copies the output
        into those locations.
        """
        import shutil

        # Install assembled library directories
        phase0_libs = phase0_dir / "libraries"
        if phase0_libs.exists():
            for lib_dir in sorted(phase0_libs.iterdir()):
                if lib_dir.is_dir():
                    dest = self.manager.structure.libraries_dir / lib_dir.name
                    if dest.exists():
                        shutil.rmtree(dest)
                    shutil.copytree(lib_dir, dest)

        # Install per-file summaries
        phase0_summaries = phase0_dir / "summaries"
        if phase0_summaries.exists():
            for summary_file in phase0_summaries.glob("*.md"):
                dest = self.manager.structure.summaries_dir / summary_file.name
                shutil.copy2(summary_file, dest)

        # Install libraries.yaml (library definitions with names)
        libraries_yaml = phase0_dir / "libraries.yaml"
        if libraries_yaml.exists():
            dest = self.manager.structure.root / "libraries.yaml"
            shutil.copy2(libraries_yaml, dest)

        # Install route_table.jsonl
        route_table = phase0_dir / "route_table.jsonl"
        if route_table.exists():
            dest = self.manager.structure.root / "route_table.jsonl"
            shutil.copy2(route_table, dest)

    def _run_structure_discovery(self) -> dict[str, Any]:
        """Phase 1: AST structure + edit-in-place gap analysis.

        Two-part discovery:
        1. ``planning.models.parse_file()`` — AST structure (functions,
           classes, imports) for each Python file.
        2. ``core.edit_in_place.analyze_project()`` — translation state
           (which functions are implemented, which have gaps).
        """
        from spec_manager.comment_planning.models import parse_file
        from spec_manager.core.edit_in_place import analyze_project, find_gaps

        all_files = self.manager.get_all_files()
        parsed_count = 0
        errors: list[str] = []
        per_file_results: list[dict[str, Any]] = []

        for file_id, file_path in all_files.items():
            if not file_path.exists():
                errors.append(f"File not found: {file_path}")
                continue
            try:
                code_file = parse_file(str(file_path))
                per_file_results.append(
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

        # Edit-in-place analysis: classify comments as gaps, track translation state
        project_root = str(self.manager.structure.root)
        project_state = analyze_project(project_root)
        gaps = find_gaps(project_state)

        # Write aggregate structure output
        self.manager.write_agent_output(
            Phase.STRUCTURE_DISCOVERY,
            {"files": per_file_results},
        )

        return {
            "files_parsed": parsed_count,
            "total_files": len(all_files),
            "files_with_translation_state": len(project_state.files),
            "gaps_detected": len(gaps),
            "errors": errors,
        }

    def _run_decomposition(self) -> dict[str, Any]:
        """Phase 2: Reverse translation of functions to pseudocode.

        Calls ``planning.reverser.reverse_translate()`` for each function
        in each file to produce pseudocode annotations describing the
        implementation.

        Note: ``plan_insertions()`` is a directed operation requiring a
        user-provided intention string, so it is not called in batch mode.
        """
        from spec_manager.comment_planning.models import parse_file
        from spec_manager.comment_planning.reverser import reverse_translate

        all_files = self.manager.get_all_files()
        reversal_count = 0
        functions_processed = 0
        errors: list[str] = []

        for _file_id, file_path in all_files.items():
            if not file_path.exists():
                continue
            try:
                code_file = parse_file(str(file_path))
            except Exception as exc:
                errors.append(f"Parse failed for {file_path}: {exc}")
                continue

            for func in code_file.functions:
                try:
                    reverse_plan = reverse_translate(code_file, func.name)
                    functions_processed += 1
                    if reverse_plan.generated_comments:
                        reversal_count += 1
                except Exception as exc:
                    errors.append(
                        f"Reverse translation failed for {func.name} in {file_path}: {exc}"
                    )

        return {
            "functions_processed": functions_processed,
            "functions_with_comments": reversal_count,
            "errors": errors,
        }

    def _run_compliance_clean(self) -> dict[str, Any]:
        """Phase 3: Executable gap detection + gap queue integration.

        1. Scans all workspace Python files for executable gaps (comments,
           stubs) via ``compliance.detection.orchestrator``.
        2. Feeds gap evidence into the gap queue for downstream consumption.
        """
        from spec_manager.compliance.detection.orchestrator import (
            integrate_with_gap_queue,
            scan_executable_gaps,
        )
        from spec_manager.core.gap import GapSynthesizer
        from spec_manager.core.gap_queue import GapQueue

        all_files = self.manager.get_all_files()
        filepaths = [fp for fp in all_files.values() if fp.exists()]
        project_root = self.manager.structure.root

        report = scan_executable_gaps(filepaths, project_root)

        # Feed evidence into gap queue
        gap_queue = GapQueue()
        synthesizer = GapSynthesizer()
        integrate_with_gap_queue(report, gap_queue, synthesizer)

        return {
            "gaps_found": len(report.all_evidence),
            "comment_gaps": len(report.comment_gaps),
            "stub_gaps": len(report.stub_gaps),
            "files_scanned": len(filepaths),
            "scan_duration_ms": report.scan_duration_ms,
            "gaps_queued": len(gap_queue.gaps),
        }

    def _run_library_discovery(self) -> dict[str, Any]:
        """Phase 4: Branch initialization and brownfield span routing.

        1. Initializes the branch directory structure via
           ``BranchManager.initialize()``.
        2. Runs the ``CollapseEngine`` against the spec snapshot to route
           spans into pin/slice/store/event/adjacency artifacts and
           register routed atom candidates in the atom registry.
        """
        branch_mgr = self.manager.branches
        issues = branch_mgr.initialize() if not branch_mgr.is_initialized() else []

        # Route the codebase into initial PDD graph artifacts
        source_dir = self.manager.structure.spec_snapshot_dir
        collapse_result = branch_mgr.collapse_codebase(source_dir)

        # Register all routed atom candidates and persist
        all_descriptors = list(collapse_result.atom_candidates)
        for descriptor in all_descriptors:
            branch_mgr.register_atom(descriptor)
        branch_mgr.atom_registry.save()

        return {
            "branch_initialized": True,
            "init_issues": issues,
            "atom_candidates": len(collapse_result.atom_candidates),
            "pin_spans": len(collapse_result.pin_spans),
            "slice_entrypoints": len(collapse_result.slice_entrypoints),
            "store_touches": len(collapse_result.store_touches),
            "event_routes": len(collapse_result.event_routes),
            "architecture_promotions": len(collapse_result.architecture_promotions),
            "adjacency_edges": len(collapse_result.adjacency_edges),
            "collapse_ambiguities": len(collapse_result.ambiguities),
            "collapse_warnings": collapse_result.warnings,
        }

    def _run_spec_build(self) -> dict[str, Any]:
        """Phase 5: Pin-function extraction + promotion workflow.

        1. Scans the workspace for pin functions via
           ``PinFunctionOrchestrator.scan()``.
        2. Persists the ``PinFunctionRegistry`` to disk.
        3. Runs the ``PromotionEngine`` to promote atoms from algorithmic
           to architectural branch (with compliance gating).
        """
        import json

        from spec_manager.pin_functions.orchestrator import PinFunctionOrchestrator

        project_root = self.manager.structure.root
        pin_orchestrator = PinFunctionOrchestrator(project_root)

        registry = pin_orchestrator.scan(mode="scan")

        # Persist the registry to disk
        registry_path = pin_orchestrator.registry_path
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(registry.model_dump(), indent=2),
            encoding="utf-8",
        )

        # Run promotion workflow if branch manager has atoms
        # TODO: Wire demotion on compliance gate failure. Currently
        #   promote() returns skipped_atoms but nothing acts on them.
        #   If gates fail: DownwardFlowEngine should trace pins back
        #   to atoms, fix at L1 (code-as-spec), then re-promote.
        #   Full chain: L3→L2→L1 demotion until issue is resolved.
        branch_mgr = self.manager.branches
        promotion_result = None
        if branch_mgr.is_initialized() and branch_mgr.list_atoms():
            promotion_result = branch_mgr.promote()

        # TODO: Add architectural implementation agent after promotion.
        #   After atoms are promoted via pins, the architectural layer
        #   (services/events/middleware) needs to be BUILT from them.
        #   Pin projections define HOW atoms map to architecture
        #   (PASS_THROUGH, EVENT_BRIDGE, MIDDLEWARE_WRAP, etc.) but
        #   nothing currently generates the actual architectural code.
        #   This agent should:
        #     1. Read promoted pins and their projection types
        #     2. Generate service/event/middleware code that uses pin-functions
        #     3. Enforce NO_INLINED_ATOM_LOGIC gate (all logic via pins)
        #   Separate from P9 (algorithmic implementation) — this is
        #   architectural assembly.

        outputs: dict[str, Any] = {
            "pins_found": len(registry.pin_functions),
            "import_edges": len(registry.import_edges),
            "registry_path": str(registry_path),
        }
        if promotion_result is not None:
            outputs["promoted"] = len(promotion_result.promoted_atoms)
            outputs["skipped"] = len(promotion_result.skipped_atoms)
            outputs["promotion_errors"] = promotion_result.errors

        return outputs

    def _run_cross_library(self) -> dict[str, Any]:
        """Phase 6: Adjacency graph and disconnected component detection.

        Runs ``run_adjacency_analysis()`` against workspace roots to discover
        relationship-fact artifacts, then builds a unified relationship graph
        (calls/events/stores) and detects disconnected components.
        """
        from spec_manager.analysis.adjacency.runner import (
            AdjacencyAnalysisConfig,
            run_adjacency_analysis,
        )

        root = self.manager.structure.root
        config = AdjacencyAnalysisConfig(
            source_dirs=[self.manager.structure.spec_snapshot_dir],
            spec_dirs=[root],
        )
        report = run_adjacency_analysis(config)
        return {
            "total_nodes": report.total_nodes,
            "total_edges": report.total_edges,
            "num_components": report.num_components,
            "disconnected_warnings": len(report.disconnected_warnings),
            "signal_type_counts": report.signal_type_counts,
        }

    def _run_projection_sync(self) -> dict[str, Any]:
        """Phase 7: Lineage building, analysis generation, projection sync.

        1. Loads projection edges from pin registry.
        2. Builds ``LineageBuilder`` to trace atom→architecture projection.
        3. Runs ``generate_analysis_file()`` for the full analysis artifact.
        4. Runs ``ProjectionGenerator.generate_plan()`` for plan.md.
        5. Persists lineage table and analysis to disk.
        """
        import json

        from spec_manager.analysis.generator import generate_analysis_file, write_analysis_json
        from spec_manager.projection.generator import ProjectionGenerator
        from spec_manager.projection.lineage.builder import (
            AtomDefinition,
            LineageBuilder,
            import_records_from_pin_registry,
        )
        from spec_manager.projection.lineage.persistence import save_lineage_table
        from spec_manager.schemas.derived_elements import DerivedElement
        from spec_manager.schemas.pin_functions import PinFunctionRegistry
        from spec_manager.schemas.spec_index_v2 import Library

        root = self.manager.structure.root
        outputs: dict[str, Any] = {}

        # 1. Consume registry-declared edges as the authoritative source.
        import_records = []
        registry_path = root / ".spec" / "pin_registry.json"
        if registry_path.exists():
            try:
                pin_registry = PinFunctionRegistry.model_validate_json(
                    registry_path.read_text(encoding="utf-8")
                )
                import_records = import_records_from_pin_registry(pin_registry)
            except Exception as exc:
                logger.warning(
                    "Failed to load pin registry for projection sync lineage build: %s",
                    exc,
                    exc_info=True,
                )
                import_records = []
        if not import_records:
            outputs["lineage_input_warning"] = (
                "No pin-registry relationship edges found for lineage build."
            )
        outputs["import_edges"] = len(import_records)

        # 2. Build atom definitions from branch manager for lineage tracking
        branch_mgr = self.manager.branches
        atom_defs: list[AtomDefinition] = []
        if branch_mgr.is_initialized():
            for atom in branch_mgr.list_atoms():
                atom_defs.append(
                    AtomDefinition(
                        atom_id=atom.atom_id,
                        function_name=atom.function_name,
                        file_path=atom.file_path,
                        module_path="",
                        signature_hash=getattr(atom, "signature_hash", ""),
                    )
                )

        # 3. Build lineage table (atom → architecture projection)
        if atom_defs:
            lineage_builder = LineageBuilder(import_records=import_records, atoms=atom_defs)
            lineage_table = lineage_builder.build_lineage()
            outputs["lineage_edges"] = len(lineage_table.edges)

            # Find orphan atoms (known but not projected)
            known_atom_ids = {a.atom_id for a in atom_defs}
            orphans = lineage_table.find_orphan_atoms(known_atom_ids)
            outputs["orphan_atoms"] = len(orphans)

            # Persist lineage table
            lineage_path = root / "lineage_table.json"
            save_lineage_table(lineage_table, lineage_path)
            outputs["lineage_path"] = str(lineage_path)
        else:
            outputs["lineage_edges"] = 0
            outputs["orphan_atoms"] = 0
            outputs["note_lineage"] = "No atoms registered — skipping lineage build."

        # 4. Generate analysis file (atom registry, imports, adjacency, data flow)
        spec_snapshot = self.manager.structure.spec_snapshot_dir
        if spec_snapshot.exists():
            analysis = generate_analysis_file(
                algorithmic_dir=spec_snapshot,
                architectural_dir=root,
                run_id=self.manager.run_id,
            )
            analysis_path = root / "analysis.json"
            write_analysis_json(analysis, analysis_path)
            outputs["analysis_path"] = str(analysis_path)
            outputs["analysis_atoms"] = len(analysis.atoms)

        # 5. Load libraries + elements for projection plan
        libraries: list[Library] = []
        libraries_yaml = root / "libraries.yaml"
        if libraries_yaml.exists():
            import yaml

            data = yaml.safe_load(libraries_yaml.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for lib_data in data.get("libraries", []):
                    if not isinstance(lib_data, dict):
                        continue
                    lib_id = str(lib_data.get("lib_id", "")).strip()
                    libraries.append(
                        Library(
                            lib_id=lib_id,
                            name=str(lib_data.get("name", lib_id)),
                            description=str(lib_data.get("description", "")),
                        )
                    )

        elements: list[DerivedElement] = []
        lib_dirs = self.manager.get_all_libraries_recursive()
        for lib_id, lib_path in lib_dirs.items():
            spec_index_path = lib_path / "spec_index.json"
            if not spec_index_path.exists():
                # C01: Account for all inputs — don't silently omit libraries
                logger.warning(
                    "Library %s has no spec_index.json at %s — skipping projection",
                    lib_id,
                    spec_index_path,
                )
                continue
            spec_data = json.loads(spec_index_path.read_text(encoding="utf-8"))
            for elem_data in spec_data.get("elements", []):
                atom_ids = elem_data.get("evidence_atom_ids")
                if not atom_ids:
                    # C01: Missing provenance — surface it, don't use placeholder
                    logger.warning(
                        "Element %s in %s has no evidence_atom_ids — provenance chain is broken",
                        elem_data.get("element_id", elem_data.get("elem_id", "?")),
                        lib_id,
                    )
                    atom_ids = []
                elements.append(
                    DerivedElement(
                        elem_id=elem_data.get("element_id", elem_data.get("elem_id", "")),
                        kind=elem_data.get("kind", "REQ"),
                        lib_id=lib_id if lib_id.startswith("LIB-") else f"LIB-{lib_id}",
                        title=elem_data.get("title", ""),
                        body=elem_data.get("text", elem_data.get("body", "")),
                        evidence_atom_ids=atom_ids,
                    )
                )

        outputs["libraries_found"] = len(libraries)
        outputs["elements_found"] = len(elements)

        if libraries:
            generator = ProjectionGenerator()
            artifact = generator.generate_plan(libraries=libraries, elements=elements)
            outputs["projection_id"] = artifact.projection_id
            outputs["pins_generated"] = len(artifact.pins)

        return outputs

    def _run_task_planning(self) -> dict[str, Any]:
        """Phase 8: Planning integration and gap bridge.

        Gathers target Python files from the workspace snapshot and
        compliance gap descriptions as intentions, then calls
        ``run_planning_v2_phase()`` to produce insertion plans.
        """
        from spec_manager.comment_planning.workflow import run_planning_v2_phase

        # Gather target files from workspace snapshot
        all_files = self.manager.get_all_files()
        target_files = [str(fp) for fp in all_files.values() if fp.exists()]

        # Derive intentions from Phase 3 compliance gap descriptions
        phase3_result = self.manager.state.phases.get(Phase.COMPLIANCE_CLEAN.value)
        intentions: list[str] = []
        if phase3_result and phase3_result.outputs:
            gap_count = phase3_result.outputs.get("gaps_found", 0)
            if gap_count > 0:
                intentions.append(
                    f"Resolve {gap_count} executable gaps found during compliance scan"
                )

        # TODO: Wire under-specification → constraints → blocking flow.
        #   When planning hits an under-specification:
        #     1. Planning agent identifies potential solutions
        #     2. Checks CONSTRAINTS against each solution
        #     3. If constraints cover → decide, record in analysis docs
        #     4. If constraints DON'T cover → BLOCK
        #        - Interactive mode: generate research prompt for human
        #        - Auto mode: source decision from research team
        #     5. Human provides CONSTRAINTS (not solutions)
        #   Currently just produces plans without blocking.

        # TODO: Wire Layer 1 routing for incoming changes.
        #   When a new requirement, decision, or demoted algorithm needs
        #   to be added to code-as-spec, route it to the right library
        #   and function using vertical slice summaries:
        #     1. Load VerticalSlice summaries from branch manager
        #     2. Match incoming change against slice summaries
        #     3. Route to the right library by summary similarity
        #     4. Within library, route to right function/atom
        #   Same pattern as Phase 0 (summarize → discover → route).
        #   Infrastructure: VerticalSlice with summary details exists
        #   but isn't wired into the planning/routing flow.
        result = run_planning_v2_phase(
            run_id=self.manager.run_id,
            target_files=target_files,
            intentions=intentions,
            evidence_dir=self.manager.structure.root,
        )
        return {"planning_result": result}

    def _run_implementation(self) -> dict[str, Any]:
        """Phase 9: Implement functions from spec comments.

        1. Analyzes the project for translation state and gaps.
        2. For each UNRESOLVED function (stub + spec comments),
           calls LLM to produce implementation code.
        3. Applies implementations to files in-place.
        4. Re-analyzes to confirm gaps were resolved.

        Functions are processed file-by-file, bottom-up within each
        file (last function first) to preserve line numbers.
        """
        import json

        from spec_manager.core.agent_utils import run_agent
        from spec_manager.core.edit_in_place import (
            TranslationState,
            analyze_project,
            find_gaps,
            format_gap_report,
        )
        from spec_manager.refinement.formats import _extract_json_payload, _strip_code_fences

        project_root = str(self.manager.structure.root)
        project_state = analyze_project(project_root)
        gaps = find_gaps(project_state)
        gap_report = format_gap_report(project_state)

        # Persist gap report for downstream reference
        gap_report_path = self.manager.structure.root / "gap_report.md"
        gap_report_path.write_text(gap_report, encoding="utf-8")

        implemented: list[dict[str, Any]] = []
        impl_errors: list[dict[str, Any]] = []
        all_gaps_found: list[str] = []

        for file_path, file_state in sorted(project_state.files.items()):
            # Find functions that need implementation
            unresolved = [
                f
                for f in file_state.functions
                if f.translation_state in (TranslationState.UNRESOLVED, TranslationState.STUB)
            ]
            if not unresolved:
                continue

            source_path = Path(file_path)
            file_content = source_path.read_text(encoding="utf-8")
            lines = file_content.splitlines(keepends=True)

            # Build per-file cross-file context (excludes the current file)
            file_project_context = self._build_project_context(
                project_state,
                file_path,
            )

            # Collect imports across all functions in this file.
            # Imports are deferred until after all bodies are replaced
            # to avoid shifting line numbers during bottom-up processing.
            pending_imports: list[str] = []

            # Process bottom-up to preserve line numbers
            for func in sorted(unresolved, key=lambda f: f.line_start, reverse=True):
                spec_texts = [c.text for c in func.spec_comments]
                if not spec_texts and func.translation_state == TranslationState.STUB:
                    # Stub without spec comments — nothing to implement from
                    continue

                prompt = self._build_implementation_prompt(
                    func,
                    file_content,
                    file_state,
                    project_context=file_project_context,
                )

                try:
                    output = run_agent(
                        agent_name="pdd-function-implementor",
                        prompt=prompt,
                        workspace=self.manager.workspace_path,
                    )
                    cleaned = _strip_code_fences(output)
                    data = json.loads(_extract_json_payload(cleaned))

                    body = self._extract_body(data)
                    if not body.strip():
                        # Retry once with stronger prompt
                        logger.warning(
                            "Empty body for %s, retrying with emphasis",
                            func.qualified_name,
                        )
                        retry_prompt = self._build_implementation_prompt(
                            func,
                            file_content,
                            file_state,
                            project_context=file_project_context,
                            is_retry=True,
                        )
                        output = run_agent(
                            agent_name="pdd-function-implementor",
                            prompt=retry_prompt,
                            workspace=self.manager.workspace_path,
                        )
                        cleaned = _strip_code_fences(output)
                        data = json.loads(_extract_json_payload(cleaned))
                        body = self._extract_body(data)

                    if not body.strip():
                        impl_errors.append(
                            {
                                "function": func.qualified_name,
                                "error": "Agent returned empty body after retry",
                            }
                        )
                        continue

                    # Replace function body (no import insertion yet)
                    lines = self._apply_function_body(
                        lines,
                        func,
                        body,
                        imports_needed=[],
                    )
                    pending_imports.extend(data.get("imports_needed", []))

                    # Track results
                    implemented.append(
                        {
                            "function": func.qualified_name,
                            "file": source_path.name,
                            "spec_comments": len(spec_texts),
                            "gaps": data.get("gaps", []),
                            "notes": data.get("notes", ""),
                        }
                    )
                    all_gaps_found.extend(data.get("gaps", []))

                except Exception as exc:
                    impl_errors.append(
                        {
                            "function": func.qualified_name,
                            "error": str(exc),
                        }
                    )

            # Insert all collected imports once after all bodies are placed
            if pending_imports:
                lines = self._insert_imports(lines, pending_imports)

            # Write modified file back
            source_path.write_text("".join(lines), encoding="utf-8")

        # Re-analyze to verify gaps were resolved
        post_state = analyze_project(project_root)
        post_gaps = find_gaps(post_state)

        outputs: dict[str, Any] = {
            "files_analyzed": len(project_state.files),
            "gaps_before": len(gaps),
            "gaps_after": len(post_gaps),
            "functions_implemented": len(implemented),
            "implementation_errors": len(impl_errors),
            "implementations": implemented,
            "errors": impl_errors,
            "dependency_gaps": all_gaps_found,
            "gap_report_path": str(gap_report_path),
        }

        # TODO: Add small test generation step here.
        #   simpler.md step 4: "write small tests to validate small
        #   units of work." After implementation writes code, generate
        #   tests for each implemented function/atom, run them, and
        #   include results in outputs for compliance gating.

        return outputs

    @staticmethod
    def _build_project_context(
        project_state: Any,
        current_file: str,
    ) -> str:
        """Build a summary of other files in the project for cross-reference.

        Includes class names, method signatures, constants, and dataclass
        definitions from all files except the current one.  This gives
        the implementation agent enough context to reference cross-service
        types and methods.
        """
        parts: list[str] = []
        for file_path, file_state in sorted(project_state.files.items()):
            if file_path == current_file:
                continue
            try:
                content = Path(file_path).read_text(encoding="utf-8")
            except OSError:
                continue
            lines = content.splitlines()
            # Extract header (imports, constants, dataclasses) up to first function
            first_func_line = min(
                (f.line_start for f in file_state.functions),
                default=len(lines),
            )
            header = "\n".join(lines[: first_func_line - 1])
            # Extract method signatures
            sigs = [
                lines[f.line_start - 1].rstrip()
                for f in file_state.functions
                if f.line_start - 1 < len(lines)
            ]
            file_name = Path(file_path).name
            parts.append(f"### {file_name}\n```\n{header}\n")
            if sigs:
                parts.append("# Methods:\n")
                for sig in sigs:
                    parts.append(f"{sig}\n")
            parts.append("```\n")
        return "\n".join(parts)

    def _build_implementation_prompt(
        self,
        func: Any,
        file_content: str,
        file_state: Any,
        project_context: str = "",
        is_retry: bool = False,
    ) -> str:
        """Build the prompt for the pdd-function-implementor agent.

        Includes file context (imports, constants, class), the function
        stub with spec comments, extracted requirements, and optionally
        a summary of other project files for cross-service references.
        """
        lines = file_content.splitlines()

        # Extract the function text (from line_start to line_end)
        func_text = "\n".join(lines[func.line_start - 1 : func.line_end])

        # Extract spec comment texts
        spec_requirements = [c.text for c in func.spec_comments]

        # Build file context: everything before the first function/method
        first_func_line = min((f.line_start for f in file_state.functions), default=len(lines))
        file_header = "\n".join(lines[: first_func_line - 1])

        # Get other method signatures for cross-reference
        class_methods: list[str] = []
        for other_func in file_state.functions:
            if other_func.qualified_name != func.qualified_name:
                sig_line = lines[other_func.line_start - 1].rstrip()
                class_methods.append(sig_line)

        prompt_parts = [
            "## FILE CONTEXT\n",
            f"```\n{file_header}\n```\n",
        ]

        if class_methods:
            prompt_parts.append("## OTHER METHODS IN CLASS\n")
            prompt_parts.append("```\n")
            for m in class_methods:
                prompt_parts.append(f"{m}\n")
            prompt_parts.append("```\n")

        if project_context:
            prompt_parts.append("## OTHER FILES IN PROJECT\n")
            prompt_parts.append(project_context)
            prompt_parts.append("\n")

        prompt_parts.append("## FUNCTION TO IMPLEMENT\n")
        prompt_parts.append(f"```\n{func_text}\n```\n")

        prompt_parts.append("## REQUIREMENTS (from spec comments)\n")
        for i, req in enumerate(spec_requirements, 1):
            prompt_parts.append(f"{i}. {req}\n")

        task_instruction = (
            "\n## TASK\n"
            "Implement the function body that fulfills ALL requirements above.\n"
            "Return the body code with correct indentation "
            "(8 spaces for class methods, 4 for top-level functions).\n"
        )
        if is_retry:
            task_instruction += (
                "\nIMPORTANT: You MUST provide a non-empty implementation.\n"
                "If the function references external services or types not "
                "defined in this file, use reasonable internal attributes "
                "(e.g. self._event_bus, self._dashboard, self._dead_letters) "
                "as stand-ins. The function must have a real body.\n"
            )
        prompt_parts.append(task_instruction)

        return "\n".join(prompt_parts)

    @staticmethod
    def _extract_body(data: dict[str, Any]) -> str:
        """Extract function body from agent response.

        Checks ``body`` first (legacy field).  If empty, falls back to
        extracting added lines from ``edits[].unified_diff``.

        Args:
            data: Parsed JSON response from the agent.

        Returns:
            Body code string (may be empty if agent truly returned nothing).
        """
        body = data.get("body", "")
        if body.strip():
            return body

        # Fallback: extract added lines from unified diffs
        edits = data.get("edits", [])
        for edit in edits:
            diff_text = edit.get("unified_diff", "")
            if not diff_text:
                continue
            # Collect lines that start with '+' (additions) but skip
            # diff headers ('+++', '---') and hunk markers ('@@').
            added: list[str] = []
            for line in diff_text.splitlines():
                if line.startswith("+++") or line.startswith("---"):
                    continue
                if line.startswith("@@"):
                    continue
                if line.startswith("+"):
                    added.append(line[1:])  # strip the leading '+'
            if added:
                return "\n".join(added)

        return body

    @staticmethod
    def _insert_imports(lines: list[str], imports_needed: list[str]) -> list[str]:
        """Insert new import statements after existing imports.

        Finds the last existing ``import`` or ``from ... import`` line
        and inserts new imports immediately after it.  Skips imports
        that already appear in the file.

        Args:
            lines: File lines (with line endings).
            imports_needed: Import statements to add.

        Returns:
            Modified lines list.
        """
        from spec_manager.core.language import IMPORT_KEYWORDS

        new_lines = list(lines)
        file_text = "".join(new_lines)

        # Deduplicate and filter already-present imports
        unique_imports: list[str] = []
        for imp in imports_needed:
            imp = imp.strip()
            if imp and imp not in file_text and imp not in unique_imports:
                unique_imports.append(imp)

        if not unique_imports:
            return new_lines

        # Find the last import line to insert after
        last_import_idx = -1
        for idx, line in enumerate(new_lines):
            stripped = line.strip()
            if any(stripped.startswith(kw) for kw in IMPORT_KEYWORDS):
                last_import_idx = idx

        # If no imports found, insert after module docstring
        if last_import_idx < 0:
            in_docstring = False
            for idx, line in enumerate(new_lines):
                stripped = line.strip()
                # Language-specific: Python docstring detection
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    if in_docstring:
                        # Closing quote — insert after this line
                        last_import_idx = idx
                        break
                    elif stripped.count('"""') >= 2 or stripped.count("'''") >= 2:
                        # Single-line docstring
                        last_import_idx = idx
                        break
                    else:
                        in_docstring = True
                elif not in_docstring and stripped:
                    last_import_idx = idx
                    break

        insert_at = last_import_idx + 1 if last_import_idx >= 0 else 0
        import_block = "\n".join(unique_imports) + "\n"
        new_lines.insert(insert_at, import_block)

        return new_lines

    @staticmethod
    def _apply_function_body(
        lines: list[str],
        func: Any,
        new_body: str,
        imports_needed: list[str],
    ) -> list[str]:
        """Replace a function's body with new implementation code.

        Uses ``body_start_line`` from LLM-based code analysis to find
        the body start position, then replaces from body start (after
        docstring) through function end. Preserves the def line,
        signature, and docstring.

        Args:
            lines: File lines (with line endings).
            func: FunctionInfo with line_start, line_end, body_start_line.
            new_body: The new body code string.
            imports_needed: New imports (ignored — use ``_insert_imports``
                separately to avoid line-number drift during bottom-up
                processing).

        Returns:
            Modified lines list.
        """
        # body_start_line is 1-indexed; convert to 0-indexed for slicing
        body_start_idx = getattr(func, "body_start_line", 0) - 1
        if body_start_idx < 0:
            # Fallback: couldn't determine body start, skip this function
            return list(lines)

        func_end_idx = func.line_end  # 1-indexed, exclusive in slice

        # Ensure new_body ends with a newline
        if not new_body.endswith("\n"):
            new_body += "\n"

        new_lines = list(lines)
        # Remove old body (from body_start_idx to func_end_idx, 0-indexed)
        del new_lines[body_start_idx:func_end_idx]
        # Insert new body
        body_lines = new_body.splitlines(keepends=True)
        for k, bl in enumerate(body_lines):
            new_lines.insert(body_start_idx + k, bl)

        return new_lines

    def _run_continuous_qa(self) -> dict[str, Any]:
        """Phase 10: Strategy evolution, refinement engine analysis.

        1. Initializes ``StrategyRegistry`` and ``StrategyEvolutionPipeline``.
        2. Attempts promotion of any experimental strategies.
        3. Generates an evolution report summarizing gaps and promotions.
        4. Runs the ``refinement_engine`` for coupling/cohesion analysis.
        """
        from spec_manager.strategies.evolution import StrategyEvolutionPipeline
        from spec_manager.strategies.registry import StrategyRegistry

        outputs: dict[str, Any] = {}

        # Initialize strategy evolution pipeline
        registry = StrategyRegistry()
        registry.enable_evolution()
        pipeline = StrategyEvolutionPipeline(registry=registry)
        outputs["strategies_registered"] = len(registry.definitions)

        # Attempt promotion of experimental strategies
        promoted_count = 0
        experimental_names = [
            name
            for name, defn in registry.definitions.items()
            if (defn.metadata or {}).get("status") == "experimental"
        ]
        for name in experimental_names:
            if pipeline.promote_if_ready(name):
                promoted_count += 1
        outputs["strategies_promoted"] = promoted_count

        # Get evolution report (gaps, performance, promotions)
        evolution_report = pipeline.get_evolution_report()
        outputs["total_gaps"] = evolution_report.get("total_gaps", 0)
        outputs["experimental_strategies"] = len(
            evolution_report.get("experimental_strategies", [])
        )

        # Run the refinement engine as the core of continuous QA
        refinement_result = self._run_refinement_engine()
        outputs["refinement"] = refinement_result

        return outputs

    # ------------------------------------------------------------------
    # Refinement engine integration
    # ------------------------------------------------------------------

    def _run_refinement_engine(self) -> dict[str, Any]:
        """Run coupling/cohesion analysis on skeletons (libraries).

        Analysis-only: detects issues and proposes operations but does NOT
        execute them. The refinement engine reports grouping quality so
        humans or downstream phases can decide what to act on.

        Returns:
            Summary dict with issues found and operations proposed.
        """
        from spec_manager.analysis.adjacency.graph import AdjacencyGraph
        from spec_manager.cohesion.detector import (
            GroupingUnit,
            detect_all,
        )
        from spec_manager.cohesion.operations import (
            propose_operations,
            validate_operation,
        )

        branch_mgr = self.manager.branches

        # Build grouping units from vertical slices
        grouping_units: list[GroupingUnit] = []
        all_atoms = branch_mgr.list_atoms()

        # Group atoms by vertical slice
        slice_entities: dict[str, set[str]] = {}
        for atom in all_atoms:
            if atom.vertical_slice:
                slice_entities.setdefault(atom.vertical_slice, set()).add(atom.atom_id)

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

        # Propose operations (analysis only — not executed)
        operations = propose_operations(issues)

        # Validate proposed operations
        valid_ops: list = []
        invalid_ops: list = []
        for op in operations:
            errors = validate_operation(op, adjacency_graph)
            if errors:
                invalid_ops.append({"op": op.op_type, "errors": errors})
            else:
                valid_ops.append(op)

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
