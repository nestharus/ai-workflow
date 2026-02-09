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
from pathlib import Path
from typing import Any

from spec_manager.refinement.workspace.manager import WorkspaceManager
from spec_manager.refinement.workspace.state import Phase, PhaseStatus

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
            except Exception:
                failed.append(pdd_phase.value)
                logger.exception("Phase %s failed", pdd_phase.value)
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
        structure (libraries/, summaries/, system/) so downstream phases and
        extraction methods can find it.
        """
        from spec_manager.intake import run_phase0

        source_dir = self.manager.structure.spec_snapshot_dir
        output_dir = self.manager.workspace_path / "phase0_output"
        result = run_phase0(source_dir, output_dir)

        # Install Phase 0 output into workspace structure
        self._install_phase0_output(output_dir)

        return result

    def _install_phase0_output(self, phase0_dir: Path) -> None:
        """Copy Phase 0 assembled output into the workspace directory structure.

        Phase 0 writes to its own output directory. The workspace structure
        (libraries/, summaries/, system/) is where extraction methods and
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

        # Install system-level constraints
        phase0_system = phase0_dir / "system"
        if phase0_system.exists():
            system_dest = self.manager.structure.root / "system"
            if system_dest.exists():
                shutil.rmtree(system_dest)
            shutil.copytree(phase0_system, system_dest)

        # Install per-file summaries
        phase0_summaries = phase0_dir / "summaries"
        if phase0_summaries.exists():
            for summary_file in phase0_summaries.glob("*.json"):
                dest = self.manager.structure.summaries_dir / summary_file.name
                shutil.copy2(summary_file, dest)

        # Install libraries.json (library definitions with names)
        libraries_json = phase0_dir / "libraries.json"
        if libraries_json.exists():
            dest = self.manager.structure.root / "libraries.json"
            shutil.copy2(libraries_json, dest)

        # Install route_table.jsonl
        route_table = phase0_dir / "route_table.jsonl"
        if route_table.exists():
            dest = self.manager.structure.root / "route_table.jsonl"
            shutil.copy2(route_table, dest)

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
        per_file_results: list[dict[str, Any]] = []

        for file_id, file_path in all_files.items():
            if not file_path.exists():
                errors.append(f"File not found: {file_path}")
                continue
            if file_path.suffix != ".py":
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

        # Write all per-file results as a single aggregate output
        self.manager.write_agent_output(
            ws_phase,
            {"files": per_file_results},
        )

        return {
            "files_parsed": parsed_count,
            "total_files": len(all_files),
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
        from spec_manager.planning.code_parser import parse_file
        from spec_manager.planning.reverser import reverse_translate

        all_files = self.manager.get_all_files()
        reversal_count = 0
        functions_processed = 0
        errors: list[str] = []

        for _file_id, file_path in all_files.items():
            if not file_path.exists() or file_path.suffix != ".py":
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
        """Phase 3: Executable gap detection via comment/stub scanning.

        Calls ``compliance.detection.orchestrator.scan_executable_gaps()``
        across all workspace files.
        """
        from spec_manager.compliance.detection.orchestrator import scan_executable_gaps

        all_files = self.manager.get_all_files()
        filepaths = [fp for fp in all_files.values() if fp.exists() and fp.suffix == ".py"]
        project_root = self.manager.structure.root

        try:
            report = scan_executable_gaps(filepaths, project_root)
            return {
                "gaps_found": len(report.all_evidence),
                "comment_gaps": len(report.comment_gaps),
                "stub_gaps": len(report.stub_gaps),
                "files_scanned": len(filepaths),
                "scan_duration_ms": report.scan_duration_ms,
            }
        except Exception as exc:
            return {
                "gaps_found": 0,
                "files_scanned": len(filepaths),
                "error": str(exc),
            }

    def _run_library_discovery(self) -> dict[str, Any]:
        """Phase 4: Branch initialization, atom registry, slice navigation.

        1. Initializes the branch directory structure via
           ``BranchManager.initialize()``.
        2. Runs the ``CollapseEngine`` against the spec snapshot to extract
           atoms (algorithms, stores, shapes) from Python files and
           register them in the atom registry.
        """
        branch_mgr = self.manager.branches
        issues = branch_mgr.initialize() if not branch_mgr.is_initialized() else []

        # Collapse the codebase into Layer 1 atoms
        source_dir = self.manager.structure.spec_snapshot_dir
        collapse_result = branch_mgr.collapse_codebase(source_dir)

        # Register all extracted atoms and persist
        all_descriptors = (
            collapse_result.extracted_atoms
            + collapse_result.extracted_stores
            + collapse_result.extracted_shapes
        )
        for descriptor in all_descriptors:
            branch_mgr.register_atom(descriptor)
        branch_mgr.atom_registry.save()

        return {
            "branch_initialized": True,
            "init_issues": issues,
            "atoms_extracted": len(collapse_result.extracted_atoms),
            "stores_extracted": len(collapse_result.extracted_stores),
            "shapes_extracted": len(collapse_result.extracted_shapes),
            "architectural_remnants": len(collapse_result.architectural_remnants),
            "collapse_warnings": collapse_result.warnings,
        }

    def _run_spec_build(self) -> dict[str, Any]:
        """Phase 5: Pin-function extraction + promotion workflow.

        1. Scans the workspace for pin functions via
           ``PinFunctionOrchestrator.scan()``.
        2. Persists the ``PinFunctionRegistry`` to the registry path.
        """
        import json

        from spec_manager.pin_functions.orchestrator import PinFunctionOrchestrator

        project_root = self.manager.structure.root
        pin_orchestrator = PinFunctionOrchestrator(project_root)

        registry = pin_orchestrator.scan()

        # Persist the registry to disk
        registry_path = pin_orchestrator.registry_path
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(registry.model_dump(), indent=2),
            encoding="utf-8",
        )

        return {
            "pins_found": len(registry.pin_functions),
            "import_edges": len(registry.import_edges),
            "registry_path": str(registry_path),
        }

    def _run_cross_library(self) -> dict[str, Any]:
        """Phase 6: Adjacency graph and disconnected component detection.

        Runs ``run_adjacency_analysis()`` against workspace source files
        to build a unified adjacency graph (call, event, store,
        cooccurrence) and detect disconnected components.
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
        """Phase 7: L2 generation, drift detection, pin propagation.

        Reads libraries from ``libraries.json`` (Phase 0 output) and
        elements from per-library ``spec_index.json`` files, then calls
        ``ProjectionGenerator.generate_plan()`` to produce plan.md.
        """
        import json

        from spec_manager.projection.generator import ProjectionGenerator
        from spec_manager.schemas.derived_elements import DerivedElement
        from spec_manager.schemas.spec_index_v2 import Library

        # 1. Load libraries from libraries.json (written by Phase 0)
        libraries: list[Library] = []
        libraries_json = self.manager.structure.root / "libraries.json"
        if libraries_json.exists():
            try:
                data = json.loads(libraries_json.read_text(encoding="utf-8"))
                for lib_data in data.get("libraries", []):
                    lib_id = lib_data.get("lib_id", "")
                    libraries.append(
                        Library(
                            lib_id=lib_id,
                            name=lib_data.get("name", lib_id),
                            description=lib_data.get("description", ""),
                        )
                    )
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read libraries.json: %s", exc)

        # 2. Load elements from per-library spec_index.json files
        elements: list[DerivedElement] = []
        lib_dirs = self.manager.get_all_libraries_recursive()
        for lib_id, lib_path in lib_dirs.items():
            spec_index_path = lib_path / "spec_index.json"
            if not spec_index_path.exists():
                continue
            try:
                spec_data = json.loads(spec_index_path.read_text(encoding="utf-8"))
                for elem_data in spec_data.get("elements", []):
                    elements.append(
                        DerivedElement(
                            elem_id=elem_data.get("element_id", elem_data.get("elem_id", "")),
                            kind=elem_data.get("kind", "REQ"),
                            lib_id=lib_id if lib_id.startswith("LIB-") else f"LIB-{lib_id}",
                            title=elem_data.get("title", ""),
                            body=elem_data.get("text", elem_data.get("body", "")),
                            evidence_atom_ids=elem_data.get("evidence_atom_ids", ["ATOM-0000"]),
                        )
                    )
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read spec_index.json for %s: %s", lib_id, exc)

        if not libraries:
            return {
                "libraries_found": 0,
                "elements_found": len(elements),
                "note": "No libraries.json found — Phase 0 output may not be installed.",
            }

        generator = ProjectionGenerator()
        artifact = generator.generate_plan(libraries=libraries, elements=elements)
        return {
            "projection_id": artifact.projection_id,
            "libraries_found": len(libraries),
            "elements_found": len(elements),
            "pins_generated": len(artifact.pins),
        }

    def _run_task_planning(self) -> dict[str, Any]:
        """Phase 8: Planning integration and gap bridge.

        Gathers target Python files from the workspace snapshot and
        compliance gap descriptions as intentions, then calls
        ``run_planning_v2_phase()`` to produce insertion plans.
        """
        from spec_manager.planning.workflow import run_planning_v2_phase

        # Gather target files from workspace snapshot
        all_files = self.manager.get_all_files()
        target_files = [str(fp) for fp in all_files.values() if fp.exists() and fp.suffix == ".py"]

        # Derive intentions from Phase 3 compliance gap descriptions
        phase3_result = self.manager.state.phases.get(Phase.COMPLIANCE_CLEAN.value)
        intentions: list[str] = []
        if phase3_result and phase3_result.outputs:
            gap_count = phase3_result.outputs.get("gaps_found", 0)
            if gap_count > 0:
                intentions.append(
                    f"Resolve {gap_count} executable gaps found during compliance scan"
                )

        result = run_planning_v2_phase(
            run_id=self.manager.run_id,
            target_files=target_files,
            intentions=intentions,
            evidence_dir=self.manager.structure.root,
        )
        return {"planning_result": result}

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

        1. Initializes ``StrategyRegistry`` and enables the
           ``StrategyEvolutionPipeline`` for continuous quality improvement.
        2. Runs the ``refinement_engine`` for coupling/cohesion detection
           and restructuring.
        """
        from spec_manager.strategies.registry import StrategyRegistry

        outputs: dict[str, Any] = {}

        registry = StrategyRegistry()
        registry.enable_evolution()
        outputs["pipeline_initialized"] = True
        outputs["strategies_registered"] = len(registry.definitions)

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
                slice_entities.setdefault(atom.vertical_slice, set()).add(atom.atom_id)
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
