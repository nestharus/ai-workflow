# TODO(single-layer): RESTRUCTURE — Phase 0 intake (routing-based) KEEPS. Phases 1-3
#   (structure, decomposition, compliance) survive as Libraries phase sub-steps. Phase 4
#   (library/atom registration) and Phase 5 (pin_functions) are eliminated. Phase 6-7
#   (adjacency/projection) restructure around shapes. Phase 8-9 (planning/implementation)
#   survive as Libraries phase core. Phase 10 (continuous QA) becomes Quality phase.
#   The sequential P0-P10 concept itself is replaced by forward-only Libraries →
#   Architecture → Quality phases.
# ALGORITHM(single-layer):
#   References: response3 Sections 9 and 12; evaluation modification #1.
#   Data structures:
#     - Keep intake payload types; add BootstrapOutput: {draft_shapes: list[DraftShape], algorithm_inventory: list[AlgorithmEntry], store_inventory: list[StoreEntry], libraries_seed_inputs: dict[str, Any]}.
#     - DraftShape: {library_id: str, ownership_paths: list[str], declared_dependencies: list[str], initial_contracts: list[str]}.
#     - AlgorithmEntry: {name: str, owning_library: str, entrypoints: list[str], required_invariants: list[str]}.
#     - StoreEntry: {store_id: str, owning_library: str, access_boundaries: list[str], required_adapters: list[str]}.
#   Interface contracts:
#     - def run_intake_only(self, ...) -> dict[str, Any]
#     - def bootstrap_single_layer(self, ...) -> BootstrapOutput
#     - def run(self, ...) -> dict[str, Any]  # delegates to PddLifecycle forward-only phases
#   Control flow:
#     1. Keep Phase 0 intake as-is for routing/decomposition extraction.
#     2. Phase 0 produces: draft shapes (one per library, ownership paths, declared dependencies, initial contracts); algorithm inventory (names + owning library + entrypoints + required invariants); store inventory (IDs + owning library + access boundaries + required adapters).
#     3. Convert intake decomposition into bootstrap shapes, algorithm inventory, and store inventory.
#     4. Seed Libraries phase inputs from decomposition output, draft shapes, and intake artifacts.
#     5. Skip legacy P4/P5 pin registration paths; skip pin projection phases.
#     6. Delegate iterative execution to PddLifecycle (Libraries -> Architecture -> Quality, forward-only).
#   Error handling:
#     - If bootstrap shape/inventory generation fails, block before entering Libraries phase with explicit diagnostics.
#     - If any legacy phase entrypoint is invoked, return explicit unsupported-path error.
#   Integration points:
#     - Called by lifecycle bootstrap path.
#     - Calls routing.shapes bootstrap/load and lifecycle.run.
# IMPL(single-layer): Phase 0 bootstrap should persist shape artifacts via
# `routing.shapes.write_shape_index` so downstream matcher/router consumers read a
# deterministic `routing/INDEX.md` + `routing/index.json` view.
# IMPL(single-layer): Libraries may start with proposal-only shapes from bootstrap; shape
# metadata should enqueue verifier refresh/creation work items in the first cycle.
# IMPL(single-layer): Any lineage assembly handoff from this orchestrator (legacy Phase 7
# paths included) should feed deterministic dependency-scan records + shape index inputs
# into `projection.lineage.builder`, not `PinFunctionRegistry` import-edge projection.
#   Test requirements:
#     - Intake artifacts still generated.
#     - Bootstrap output includes draft shapes, algorithm inventory, store inventory, and Libraries phase seeds.
#     - Legacy pin phases are unreachable in single-layer mode.
#     - Phase 0 output contains all three inventory types (draft shapes, algorithms, stores).

"""PDD orchestrator: loop-authoritative execution with optional intake entrypoint.

This orchestrator's authoritative path is the per-slice iterative
PromotionLoop. Direct phase execution remains only for Phase 0 intake.

The legacy phase methods remain as internal building blocks:

    Phase 0  (EXTRACTION)         - intake/ (routing-based restructuring)
    Phase 1  (STRUCTURE_DISCOVERY) - dynamic source facts + core.edit_in_place
    Phase 2  (DECOMPOSITION)       - planning.reverser (reverse translation)
    Phase 3  (COMPLIANCE_CLEAN)    - compliance.detection.orchestrator + gap queue
    Phase 4  (LIBRARY_DISCOVERY)   - branches.manager (collapse + atom registry)
    Phase 5  (SPEC_BUILD)          - pin_functions.orchestrator + branches.promotion
    Phase 6  (CROSS_LIBRARY)       - analysis.adjacency.runner
    Phase 7  (PROJECTION_SYNC)     - projection.lineage + analysis.generator + projection.generator
    Phase 8  (TASK_PLANNING)       - planning over shared evidence
    Phase 9  (IMPLEMENTATION)      - core.edit_in_place (gap analysis + report)
    Phase 10 (CONTINUOUS_QA)       - strategies.evolution + refinement_engine

The ``Phase`` enum in ``refinement.workspace.state`` contains both
PDD phases (0-10) and legacy refinement phases.  This module uses only
the PDD members.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

import yaml

from spec_manager.core.agent_utils import run_agent
from spec_manager.core.json_extraction import _extract_json_payload
from spec_manager.refinement.workspace.manager import WorkspaceManager
from spec_manager.refinement.workspace.state import Phase

logger = logging.getLogger(__name__)

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
            ReactivePromotionScheduler,
            SchedulerConfig,
        )

        self._prepare_slice_worktrees(slice_refs)

        loop = PromotionLoop(
            workspace_manager=self._manager,
            branch_manager=self._manager.branches,
            workspace_root=self._manager.workspace_path,
        )
        scheduler = ReactivePromotionScheduler(
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
                history_root = worktree_root / "_history"
                history_root.mkdir(parents=True, exist_ok=True)
                history_seq = 1
                archived_target = history_root / f"{slice_id}-{history_seq:03d}"
                while archived_target.exists():
                    history_seq += 1
                    archived_target = history_root / f"{slice_id}-{history_seq:03d}"
                shutil.move(str(target), str(archived_target))
            shutil.copytree(source, target)
            ref.worktree_path = str(target)
            metadata = getattr(ref, "metadata", None)
            if isinstance(metadata, dict):
                metadata["source_slice_root"] = str(source)
            else:
                ref.metadata = {"source_slice_root": str(source)}


class PddOrchestrator:
    """Run loop-authoritative PDD orchestration with optional Phase 0 intake.

    Usage::

        manager = WorkspaceManager(run_id="my-run", input_folder=Path("specs"))
        manager.initialize()
        orchestrator = PddOrchestrator(manager)

        # Run iterative loop (authoritative execution path)
        state = orchestrator.run()

        # Optional: run extraction intake only
        result = orchestrator.run_phase(Phase.EXTRACTION)
    """

    def __init__(
        self,
        manager: WorkspaceManager,
    ) -> None:
        self.manager = manager
        self._canonical_file_facts_cache: list[dict[str, Any]] | None = None
        self._canonical_file_facts_errors: list[str] = []

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
        if start_phase is not None or end_phase is not None or stop_on_failure is not True:
            raise ValueError("Direct phase sequencing arguments are retired; use run(mode='loop').")
        if mode != "loop":
            raise ValueError(
                "PddOrchestrator sequential pipeline mode has been retired; use mode='loop'."
            )
        return self.run_loop()

    def run_phase(self, pdd_phase: Phase) -> dict[str, Any]:
        """Compatibility shim for direct phase execution.

        Direct execution is intentionally limited to Phase 0 intake.
        All iterative work must run through :meth:`run_loop`.
        """
        if pdd_phase != Phase.EXTRACTION:
            raise ValueError(
                "Direct non-extraction phase execution is retired; use run(mode='loop')."
            )
        runner = self._run_extraction
        self.manager.start_phase(pdd_phase)
        try:
            outputs = runner()
            refinement_output = self._post_phase_refinement_hook(pdd_phase)
            if refinement_output:
                outputs["refinement"] = refinement_output
            self.manager.complete_phase(pdd_phase, outputs=outputs)
            logger.info("Phase %s completed.", pdd_phase.value)
            return outputs
        except Exception as exc:
            self.manager.fail_phase(pdd_phase, error=str(exc))
            raise

    def install_phase0_output(self, phase0_dir: Path) -> None:
        """Install precomputed Phase 0 artifacts into workspace structure."""
        self._install_phase0_output(phase0_dir)

    def run_loop(
        self,
        *,
        max_iterations: int = 20,
        run_extraction: bool = False,
    ) -> dict[str, Any]:
        """Run the per-slice iterative PromotionLoop.

        This is the new execution mode that replaces the sequential
        P0-P10 pipeline with a convergence loop per slice.

        Steps:
        1. Conditionally run Phase 0 routing when external IntakeQueue is non-empty.
        2. Discover slices (libraries) from workspace.
        3. Run PromotionLoop on each slice until convergence.
        4. Use per-slice VERIFY outputs from the PromotionLoop.

        Args:
            max_iterations: Max convergence iterations per slice.
            run_extraction: Optional heavyweight full-Phase-0 flag.
                This does not trigger Phase 0 by itself; it only allows
                running ``Phase.EXTRACTION`` after trigger-based routing.

        Returns:
            Summary dict with slice results.
        """
        from spec_manager.orchestration.intake_queue import IntakeQueue
        from spec_manager.orchestration.promotion_loop import (
            RunContext,
            SliceRef,
        )

        results: dict[str, Any] = {"mode": "loop"}

        # 1. Run Phase 0 only when external intake contains queued items.
        intake_queue = IntakeQueue(self.manager.workspace_path)
        needs_phase0 = intake_queue.needs_phase0()
        results["phase0_trigger"] = {
            "queue_items": intake_queue.count(),
            "source": "external_intake_queue",
        }

        if needs_phase0:
            from spec_manager.orchestration.demotion import RoutingItem
            from spec_manager.orchestration.intake_queue import route_items

            queued_items = intake_queue.drain()
            routing_items: list[RoutingItem] = list(queued_items)
            if routing_items:
                patches = route_items(routing_items, self.manager.workspace_path)
                results["intake_routed"] = len(patches)
                results["extraction"] = "skipped (route-items mode)"
                quality_report, remediation = self._run_library_quality_gate(
                    output_dir=self.manager.workspace_path / "phase0_output",
                    source_dir=self.manager.structure.spec_snapshot_dir,
                )
                results["library_quality"] = quality_report.to_dict()
                results["library_quality_passed"] = quality_report.gate_passed
                if remediation:
                    results["library_quality_remediation"] = remediation
            elif run_extraction:
                extraction_result = self.run_phase(Phase.EXTRACTION)
                results["extraction"] = extraction_result
            else:
                results["extraction"] = "skipped (no routing payloads)"
        else:
            results["extraction"] = "skipped (no external intake queue items)"

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

        # 4. Verification is executed in-slice during loop VERIFY step.
        all_complete = all(r.status in {"COMPLETE", "SKIPPED"} for r in slice_results)
        results["verification"] = "handled_per_slice_in_promotion_loop"

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
        quality_report, remediation = self._run_library_quality_gate(
            output_dir=output_dir,
            source_dir=source_dir,
        )
        result["library_quality"] = quality_report.to_dict()
        result["library_quality_passed"] = quality_report.gate_passed
        if remediation:
            result["library_quality_remediation"] = remediation

        return result

    def _install_phase0_output(self, phase0_dir: Path) -> None:
        """Copy Phase 0 assembled output into the workspace directory structure.

        Phase 0 writes to its own output directory. The workspace structure
        (libraries/, summaries/) is where extraction methods and
        downstream phases look for content. This bridge copies the output
        into those locations.
        """
        # Install assembled library directories
        phase0_libs = phase0_dir / "libraries"
        history_root = (
            self.manager.workspace_path
            / ".pdd_runs"
            / self.manager.run_id
            / "phase0_history"
            / "libraries"
        )
        if phase0_libs.exists():
            for lib_dir in sorted(phase0_libs.iterdir()):
                if lib_dir.is_dir():
                    dest = self.manager.structure.libraries_dir / lib_dir.name
                    if dest.exists():
                        self._archive_existing_path(
                            dest, archive_root=history_root, label=lib_dir.name
                        )
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

    @staticmethod
    def _archive_existing_path(existing: Path, *, archive_root: Path, label: str) -> Path:
        """Move existing path to a run-scoped history location before replacement."""
        archive_root.mkdir(parents=True, exist_ok=True)
        seq = 1
        archive_target = archive_root / f"{label}-{seq:03d}"
        while archive_target.exists():
            seq += 1
            archive_target = archive_root / f"{label}-{seq:03d}"
        shutil.move(str(existing), str(archive_target))
        return archive_target

    def _run_library_quality_gate(
        self,
        *,
        output_dir: Path,
        source_dir: Path,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Validate Phase 0 library quality and enforce gate semantics."""
        from spec_manager.intake.quality.library_quality_validator import validate_libraries

        quality_report = validate_libraries(
            self.manager.workspace_path,
            phase0_output_dir=output_dir,
        )
        remediation: dict[str, Any] | None = None

        if quality_report.gate_passed:
            return quality_report, remediation

        logger.warning(
            "Library quality gate failed; attempting remediation for dimensions: %s",
            ", ".join(quality_report.failed_gate_dimensions),
        )
        remediation = self._attempt_library_quality_remediation(
            output_dir=output_dir,
            source_dir=source_dir,
            quality_report=quality_report.to_dict(),
        )

        if remediation.get("applied", False):
            # Re-run gate after route/coverage/assemble remediation.
            self._install_phase0_output(output_dir)
            quality_report = validate_libraries(
                self.manager.workspace_path,
                phase0_output_dir=output_dir,
            )
            if quality_report.gate_passed:
                return quality_report, remediation

        failed_dims = ",".join(quality_report.failed_gate_dimensions)
        raise ValueError(f"Library quality gate failed after remediation: {failed_dims}")

    def _attempt_library_quality_remediation(
        self,
        *,
        output_dir: Path,
        source_dir: Path,
        quality_report: dict[str, Any],
    ) -> dict[str, Any]:
        """Attempt one bounded auto-remediation pass for failed library quality gates."""
        from spec_manager.intake.assemble import assemble_output
        from spec_manager.intake.coverage import check_coverage
        from spec_manager.intake.route import route_sources
        from spec_manager.intake.types import normalize_intake_mode

        failed_dims = quality_report.get("failed_gate_dimensions", [])
        if not isinstance(failed_dims, list):
            failed_dims = []

        details: dict[str, Any] = {
            "attempted": True,
            "applied": False,
            "failed_dimensions": [str(dim) for dim in failed_dims],
            "agent_name": "spec-intake-library-repair",
        }

        try:
            repaired_libraries = self._request_library_repair_plan(
                output_dir=output_dir,
                quality_report=quality_report,
            )
            if not repaired_libraries:
                details["error"] = "repair agent did not return any libraries"
                return details

            self._write_libraries_yaml(output_dir, repaired_libraries)
            summaries = self._load_phase0_summary_payloads(output_dir)
            intake_mode = normalize_intake_mode(str(quality_report.get("intake_mode") or "prose"))
            routes, final_libraries = route_sources(
                source_dir,
                repaired_libraries,
                summaries,
                output_dir,
                intake_mode=intake_mode,
            )
            ledger = check_coverage(source_dir, routes, output_dir)
            incomplete = [entry for entry in ledger if entry.status != "fully_routed"]
            if incomplete:
                unresolved_lines = sum(
                    exc.end - exc.start + 1
                    for entry in incomplete
                    for exc in entry.exceptions
                    if exc.status == "uncovered"
                )
                raise ValueError(
                    "Coverage closure failed during remediation reroute: "
                    f"{len(incomplete)} file(s), {unresolved_lines} uncovered line(s)."
                )

            assemble_output(source_dir, routes, final_libraries, output_dir)
            self._write_libraries_yaml(output_dir, final_libraries)
            details["applied"] = True
            details["routes_created"] = len(routes)
            details["libraries"] = [lib.lib_id for lib in final_libraries]
            details["coverage_files_fully_routed"] = len(ledger)
            return details
        except Exception as exc:
            logger.warning("Library quality remediation attempt failed: %s", exc)
            details["error"] = str(exc)
            return details

    def _request_library_repair_plan(
        self,
        *,
        output_dir: Path,
        quality_report: dict[str, Any],
    ) -> list[Any]:
        """Invoke the repair agent and parse revised library definitions."""
        from spec_manager.intake.types import LibraryDef

        libraries_yaml = output_dir / "libraries.yaml"
        libraries_text = ""
        if libraries_yaml.exists():
            libraries_text = libraries_yaml.read_text(encoding="utf-8")

        report_json = json.dumps(quality_report, indent=2, ensure_ascii=False)
        prompt = (
            "## TASK\n"
            "Repair Phase 0 library boundaries after quality-gate failures.\n\n"
            "Return ONLY JSON with this schema:\n"
            '{"libraries": [{"lib_id": "LIB-0001", "name": "...", '
            '"description": "..."}], '
            '"notes": ["..."]}\n\n'
            "Rules:\n"
            "- Keep lib_id stable when possible.\n"
            "- Output complete replacement libraries list.\n"
            "- Focus on split/merge/rename boundary corrections only.\n\n"
            "## Current libraries.yaml\n"
            f"{libraries_text}\n\n"
            "## Quality report\n"
            f"{report_json}\n"
        )
        raw_output = run_agent(
            agent_name="spec-intake-library-repair",
            prompt=prompt,
            workspace=output_dir,
        )
        parsed = json.loads(_extract_json_payload(raw_output))
        if not isinstance(parsed, dict):
            raise TypeError("Library repair response must be a JSON object.")

        raw_libraries = parsed.get("libraries", [])
        if not isinstance(raw_libraries, list):
            raise TypeError("Library repair response missing 'libraries' list.")

        repaired_libraries: list[LibraryDef] = []
        for item in raw_libraries:
            if not isinstance(item, dict):
                continue
            lib_id = str(item.get("lib_id", "")).strip()
            name = str(item.get("name", "")).strip()
            description = str(item.get("description", "")).strip()
            if not lib_id or not name:
                continue
            repaired_libraries.append(
                LibraryDef(
                    lib_id=lib_id,
                    name=name,
                    description=description,
                )
            )
        return repaired_libraries

    @staticmethod
    def _write_libraries_yaml(output_dir: Path, libraries: list[Any]) -> None:
        """Persist full library definition list in Phase 0 format."""
        payload = {
            "libraries": [
                {
                    "lib_id": str(getattr(lib, "lib_id", "")),
                    "name": str(getattr(lib, "name", "")),
                    "description": str(getattr(lib, "description", "")),
                }
                for lib in libraries
                if str(getattr(lib, "lib_id", "")).strip()
            ]
        }
        libraries_path = output_dir / "libraries.yaml"
        libraries_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    @staticmethod
    def _load_phase0_summary_payloads(output_dir: Path) -> list[dict[str, Any]]:
        """Load summary payloads from existing summary markdown artifacts."""
        summaries_dir = output_dir / "summaries"
        if not summaries_dir.exists():
            return []
        payloads: list[dict[str, Any]] = []
        for summary_file in sorted(summaries_dir.glob("*.md")):
            payloads.append(
                {
                    "file_id": summary_file.stem,
                    "summary": summary_file.read_text(encoding="utf-8"),
                }
            )
        return payloads

    def _build_canonical_file_facts(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Build canonical per-file facts once for downstream phase consumers."""
        from spec_manager.core.code_analysis import analyze_file_facts

        facts_rows: list[dict[str, Any]] = []
        errors: list[str] = []
        all_files = self.manager.get_all_files()
        for file_id, file_path in all_files.items():
            if not file_path.exists():
                errors.append(f"File not found: {file_path}")
                continue
            try:
                source = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"Failed to read {file_path}: {exc}")
                continue

            try:
                rel_path = str(file_path.relative_to(self.manager.structure.root))
            except ValueError:
                rel_path = str(file_path)

            try:
                facts = analyze_file_facts(
                    source,
                    rel_path,
                    workspace=self.manager.structure.root,
                    run_id=self.manager.run_id,
                )
            except Exception as exc:
                errors.append(f"Analysis failed for {rel_path}: {exc}")
                continue

            facts_rows.append(
                {
                    "file_id": file_id,
                    "path": rel_path,
                    "content_hash": facts.content_hash,
                    "file_facts": {
                        "structure_hints": dict(facts.structure_hints),
                        "remaining_gap_pins": list(facts.gap_pins),
                        "relationship_edges": list(facts.relationship_edges),
                        "test_identity_hints": list(facts.test_identity_hints),
                        "functions": dict(facts.functions),
                        "stub_nodes": list(facts.stub_nodes),
                        "call_graph_nodes": list(facts.call_graph_nodes),
                        "call_graph_edges": list(facts.call_graph_edges),
                        "stores": dict(facts.stores),
                        "store_owners": dict(facts.store_owners),
                    },
                }
            )

        return facts_rows, errors

    def _load_or_build_canonical_file_facts(self) -> tuple[list[dict[str, Any]], list[str]]:
        """Load canonical file-facts artifact from structure output or build it once."""
        if self._canonical_file_facts_cache is not None:
            return self._canonical_file_facts_cache, list(self._canonical_file_facts_errors)

        structure_output = self.manager.read_agent_output(Phase.STRUCTURE_DISCOVERY) or {}
        if isinstance(structure_output, dict):
            rows = structure_output.get("canonical_file_facts", [])
            errors = structure_output.get("canonical_file_facts_errors", [])
            if isinstance(rows, list) and rows:
                normalized_rows = [row for row in rows if isinstance(row, dict)]
                self._canonical_file_facts_cache = normalized_rows
                self._canonical_file_facts_errors = [
                    str(err) for err in errors if isinstance(err, str)
                ]
                return normalized_rows, list(self._canonical_file_facts_errors)

        rows, errors = self._build_canonical_file_facts()
        self._canonical_file_facts_cache = rows
        self._canonical_file_facts_errors = errors
        merged_output = structure_output if isinstance(structure_output, dict) else {}
        merged_output = dict(merged_output)
        merged_output["canonical_file_facts"] = rows
        merged_output["canonical_file_facts_errors"] = errors
        self.manager.write_agent_output(Phase.STRUCTURE_DISCOVERY, merged_output)
        return rows, list(errors)

    def _run_structure_discovery(self) -> dict[str, Any]:
        """Phase 1: dynamic source facts + edit-in-place gap analysis.

        This phase avoids hard-coding language constructs (e.g., function/class/import
        categories) into required output. We keep file-level facts dynamic while the
        promotion machinery remains typed around system invariants (gaps, pins, gates).
        """
        from spec_manager.core.edit_in_place import analyze_project, find_gaps

        facts_rows, facts_errors = self._build_canonical_file_facts()
        self._canonical_file_facts_cache = facts_rows
        self._canonical_file_facts_errors = facts_errors

        per_file_results: list[dict[str, Any]] = []
        for row in facts_rows:
            if not isinstance(row, dict):
                continue
            file_facts = row.get("file_facts")
            if not isinstance(file_facts, dict):
                continue
            per_file_results.append(
                {
                    "file_id": str(row.get("file_id", "")),
                    "path": str(row.get("path", "")),
                    "facts": {
                        "functions": len(file_facts.get("functions", {}))
                        if isinstance(file_facts.get("functions", {}), dict)
                        else 0,
                        "gaps": len(file_facts.get("remaining_gap_pins", []))
                        if isinstance(file_facts.get("remaining_gap_pins", []), list)
                        else 0,
                        "edges": len(file_facts.get("relationship_edges", []))
                        if isinstance(file_facts.get("relationship_edges", []), list)
                        else 0,
                    },
                }
            )

        # Edit-in-place analysis: classify comments as gaps, track translation state
        project_root = str(self.manager.structure.root)
        project_state = analyze_project(project_root)
        gaps = find_gaps(project_state)

        # Write aggregate structure output
        self.manager.write_agent_output(
            Phase.STRUCTURE_DISCOVERY,
            {
                "files": per_file_results,
                "canonical_file_facts": facts_rows,
                "canonical_file_facts_errors": facts_errors,
            },
        )

        return {
            "files_profiled": len(per_file_results),
            "total_files": len(self.manager.get_all_files()),
            "files_with_translation_state": len(project_state.files),
            "gaps_detected": len(gaps),
            "canonical_facts_errors": facts_errors,
        }

    def _run_decomposition(self) -> dict[str, Any]:
        """Phase 2: Build decomposition from canonical code-analysis facts."""
        facts_rows, facts_errors = self._load_or_build_canonical_file_facts()
        functions_processed = 0
        decomposition_units: list[dict[str, Any]] = []
        errors: list[str] = list(facts_errors)

        for row in facts_rows:
            if not isinstance(row, dict):
                continue
            rel_path = str(row.get("path", "")).strip()
            file_facts = row.get("file_facts")
            if not rel_path or not isinstance(file_facts, dict):
                continue
            functions = file_facts.get("functions", {})
            if not isinstance(functions, dict):
                continue

            for qualified_name, fn_meta in functions.items():
                if not isinstance(fn_meta, dict):
                    continue
                signature = fn_meta.get("signature", {})
                if not isinstance(signature, dict):
                    signature = {}
                decomposition_units.append(
                    {
                        "file": rel_path,
                        "qualified_name": qualified_name,
                        "signature": signature,
                        "doc": str(fn_meta.get("doc", "")),
                        "lines": fn_meta.get("lines", []),
                    }
                )
                functions_processed += 1

        self.manager.write_agent_output(
            Phase.DECOMPOSITION,
            {"units": decomposition_units},
        )

        return {
            "functions_processed": functions_processed,
            "decomposition_units": len(decomposition_units),
            "errors": errors,
        }

    def _run_compliance_clean(self) -> dict[str, Any]:
        """Phase 3: Executable gap detection from canonical code-analysis facts."""
        from spec_manager.core.gap import GapEvidence, GapSynthesizer
        from spec_manager.core.gap_queue import GapQueue
        from spec_manager.core.gaps import Severity

        facts_rows, facts_errors = self._load_or_build_canonical_file_facts()
        gap_queue = GapQueue()
        synthesizer = GapSynthesizer()
        evidence_items: list[GapEvidence] = []
        comment_gaps = 0
        stub_gaps = 0
        scan_errors: list[str] = list(facts_errors)

        for row in facts_rows:
            if not isinstance(row, dict):
                continue
            rel_path = str(row.get("path", "")).strip()
            file_facts = row.get("file_facts")
            if not isinstance(file_facts, dict):
                continue

            for gap in file_facts.get("remaining_gap_pins", []):
                if not isinstance(gap, dict):
                    continue
                kind = str(gap.get("kind", "")).strip()
                if kind == "comment_gap":
                    comment_gaps += 1
                    invariant_family = "executable_comment"
                    gap_type = "unimplemented_comment"
                    severity = Severity.WARNING
                elif "stub" in kind:
                    stub_gaps += 1
                    invariant_family = "executable_stub"
                    gap_type = "stub_function"
                    severity = Severity.ERROR
                else:
                    continue

                location = str(gap.get("file") or rel_path).strip()
                line = (gap.get("span") or {}).get("start_line")
                source_ref = f"{location}:{line}" if line else location
                evidence_items.append(
                    GapEvidence(
                        invariant_family=invariant_family,
                        description=str(gap.get("description", kind)),
                        details={
                            "derived_artifact_target": location or "unknown",
                            "source": [source_ref] if source_ref else [],
                            "gap_type": gap_type,
                            "severity": severity,
                            "kind": kind,
                        },
                        confidence=0.95,
                        location=source_ref or None,
                        detector="code_analysis",
                    )
                )

        synthesized_gaps = synthesizer.cluster_evidence(evidence_items)
        gap_queue.update(synthesized_gaps)

        return {
            "gaps_found": len(evidence_items),
            "comment_gaps": comment_gaps,
            "stub_gaps": stub_gaps,
            "files_scanned": len(facts_rows),
            "scan_errors": scan_errors,
            "gaps_queued": len(gap_queue.get_open_gaps()),
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
        """Phase 5: Build pin/edge registry from LLM outputs and run demotion-aware promotion."""
        import json
        from datetime import UTC, datetime

        from spec_manager.core.gap_queue import GapQueue
        from spec_manager.orchestration.demotion import DemotionManager, DemotionTicket
        from spec_manager.schemas.pin_functions import (
            ImportEdge,
            PinFunction,
            PinFunctionRegistry,
            ProjectionType,
        )

        project_root = self.manager.structure.root
        bundle_paths = self._latest_slice_bundle_paths()
        pin_rows, edge_rows = self._collect_pin_edge_snapshot_rows(bundle_paths)

        pin_models: list[PinFunction] = []
        pin_by_id: dict[str, PinFunction] = {}
        for row in pin_rows:
            try:
                pin = PinFunction.model_validate(row)
            except Exception as exc:
                logger.warning("Skipping invalid pin snapshot row: %s", exc)
                continue
            if pin.pin_func_id in pin_by_id:
                continue
            pin_by_id[pin.pin_func_id] = pin
            pin_models.append(pin)

        edge_models: list[ImportEdge] = []
        seen_edge_ids: set[str] = set()
        fallback_seq = 1
        for row in edge_rows:
            row_pin = str(row.get("pin_func_id") or row.get("src") or "").strip()
            if not row_pin or row_pin not in pin_by_id:
                continue

            projection_raw = str(row.get("projection_type") or "").strip().lower()
            signal_raw = str(row.get("signal_type") or "").strip().upper()
            if not projection_raw:
                projection_raw = self._projection_type_from_signal(signal_raw).value

            try:
                projection_type = ProjectionType(projection_raw)
            except Exception:
                projection_type = self._projection_type_from_signal(signal_raw)

            edge_id = str(row.get("edge_id") or "").strip()
            if not edge_id:
                edge_id = f"IMEDGE-SNAPSHOT-{fallback_seq:04d}"
                fallback_seq += 1
            if edge_id in seen_edge_ids:
                continue

            arch_location = str(row.get("arch_location") or row.get("dst") or "").strip()
            arch_file_path = str(row.get("arch_file_path") or "").strip()
            if not arch_location:
                arch_location = arch_file_path
            if not arch_file_path and ":" in arch_location:
                arch_file_path = arch_location.split(":", 1)[0]
            if not arch_file_path:
                continue

            arch_line_raw = row.get("arch_line", 0)
            try:
                arch_line = int(arch_line_raw)
            except (TypeError, ValueError):
                arch_line = 0

            confidence_raw = row.get("confidence", row.get("weight", 0.8))
            try:
                confidence = float(confidence_raw)
            except (TypeError, ValueError):
                confidence = 0.8
            confidence = max(0.0, min(1.0, confidence))

            try:
                edge = ImportEdge(
                    edge_id=edge_id,
                    pin_func_id=row_pin,
                    arch_location=arch_location,
                    arch_file_path=arch_file_path,
                    arch_line=max(arch_line, 0),
                    projection_type=projection_type,
                    confidence=confidence,
                    is_direct_import=bool(row.get("is_direct_import", True)),
                )
            except Exception as exc:
                logger.warning("Skipping invalid edge snapshot row: %s", exc)
                continue

            seen_edge_ids.add(edge_id)
            edge_models.append(edge)

        registry = PinFunctionRegistry(
            schema_version="1.0",
            pin_functions=pin_models,
            import_edges=edge_models,
            created_at=datetime.now(UTC).isoformat(),
        )
        registry_path = project_root / ".spec" / "pin_registry.json"
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(
            json.dumps(registry.model_dump(), indent=2),
            encoding="utf-8",
        )

        branch_mgr = self.manager.branches
        promotion_result = None
        demotion_rows: list[dict[str, Any]] = []
        if branch_mgr.is_initialized() and branch_mgr.list_atoms():
            promotion_result = branch_mgr.promote()
            if not promotion_result.success:
                demotion_gap_queue = GapQueue()
                demotion_manager = DemotionManager(
                    workspace_root=self.manager.workspace_path,
                    run_id=self.manager.run_id,
                    gap_queue=demotion_gap_queue,
                    branch_manager=branch_mgr,
                )
                reasons = promotion_result.errors or ["P5 promotion failed"]
                for idx, reason in enumerate(reasons, start=1):
                    ticket = DemotionTicket(
                        run_id=self.manager.run_id,
                        slice_id=f"spec-build-{idx:02d}",
                        source="ALGORITHMIC_GATE",
                        category="architecture",
                        gate="P5_PROMOTION",
                        target_layer="L1",
                        severity="BLOCKER",
                        origin_layer="L2",
                        hop_trace=["L2", "L1"],
                        failing_atoms=list(promotion_result.skipped_atoms),
                        diagnosis=str(reason),
                        evidence_refs=[str(registry_path)],
                    )
                    apply_result = demotion_manager.apply(
                        ticket,
                        self.manager.structure.root,
                        gap_queue=demotion_gap_queue,
                        branch_manager=branch_mgr,
                    )
                    demotion_rows.append(
                        {
                            "ticket": ticket.to_dict(),
                            "apply_result": apply_result,
                        }
                    )

        outputs: dict[str, Any] = {
            "pins_found": len(registry.pin_functions),
            "import_edges": len(registry.import_edges),
            "registry_path": str(registry_path),
            "source_bundles": len(bundle_paths),
            "demotion_tickets": demotion_rows,
        }
        if promotion_result is not None:
            outputs["promoted"] = len(promotion_result.promoted_atoms)
            outputs["skipped"] = len(promotion_result.skipped_atoms)
            outputs["promotion_errors"] = promotion_result.errors
            outputs["demotions_emitted"] = len(demotion_rows)
            outputs["demotions_applied"] = sum(
                1
                for row in demotion_rows
                if bool((row.get("apply_result") or {}).get("applied", False))
            )

        return outputs

    def _run_cross_library(self) -> dict[str, Any]:
        """Phase 6: Summarize cross-library topology from canonical bundle evidence."""
        edge_rows: list[dict[str, Any]] = []
        nodes: set[str] = set()
        signal_type_counts: dict[str, int] = {}

        for bundle_path in self._latest_slice_bundle_paths():
            bundle_payload = self._read_json_dict(bundle_path)
            if not bundle_payload:
                continue
            iteration_dir = bundle_path.parent
            graph_snapshot = self._bundle_snapshot(
                bundle_payload,
                iteration_dir=iteration_dir,
                field_chain=("graph_snapshot", "path"),
                list_key="edges",
            )
            if graph_snapshot:
                for edge in graph_snapshot:
                    src = str(edge.get("src") or edge.get("pin_func_id") or "").strip()
                    dst = str(edge.get("dst") or edge.get("arch_location") or "").strip()
                    if not src or not dst:
                        continue
                    signal = str(edge.get("signal_type") or "REFERENCE").upper()
                    edge_rows.append({"src": src, "dst": dst, "signal_type": signal})
                    nodes.update({src, dst})
                    signal_type_counts[signal] = signal_type_counts.get(signal, 0) + 1
                continue

            facts = bundle_payload.get("facts", {})
            if not isinstance(facts, dict):
                continue
            for edge in facts.get("call_graph_edges", []):
                if not isinstance(edge, dict):
                    continue
                src = str(edge.get("src") or "").strip()
                dst = str(edge.get("dst") or "").strip()
                if not src or not dst:
                    continue
                edge_rows.append({"src": src, "dst": dst, "signal_type": "CALL"})
                nodes.update({src, dst})
                signal_type_counts["CALL"] = signal_type_counts.get("CALL", 0) + 1

        components = self._connected_components(nodes, edge_rows)
        disconnected_nodes = sorted(component[0] for component in components if len(component) == 1)
        return {
            "total_nodes": len(nodes),
            "total_edges": len(edge_rows),
            "num_components": len(components),
            "disconnected_warnings": disconnected_nodes[:50],
            "signal_type_counts": signal_type_counts,
            "edge_source": "evidence_bundle",
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

        from spec_manager.analysis.generator import (
            AnalysisGenerationUnavailableError,
            generate_analysis_file,
            write_analysis_json,
        )
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

        # 1. Build atom definitions from branch manager for lineage tracking.
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

        # 2. Consume registry-declared projection edges.
        import_records = []
        registry_status = "missing"
        stale_reason = ""
        registry_path = root / ".spec" / "pin_registry.json"
        if registry_path.exists():
            stale, reason = self._pin_registry_is_stale(
                registry_path=registry_path,
                root=root,
                file_hints=[atom.file_path for atom in atom_defs if atom.file_path],
            )
            if stale:
                registry_status = "stale"
                stale_reason = reason or "source changed"
            else:
                registry_status = "fresh"
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
                    registry_status = "invalid"

        if not import_records:
            outputs["lineage_input_warning"] = "No usable relationship edges from pin registry."
            if stale_reason:
                outputs["lineage_input_warning"] += f" Registry stale reason: {stale_reason}"
        outputs["pin_registry_status"] = registry_status
        outputs["import_edges"] = len(import_records)

        # 3. Build lineage table (atom → architecture projection)
        if atom_defs:
            lineage_builder = LineageBuilder(import_records=import_records, atoms=atom_defs)
            lineage_table = lineage_builder.build_lineage()
            outputs["lineage_edges"] = len(lineage_table.edges)
            outputs["lineage_rejections"] = len(lineage_builder.rejected_records)
            if lineage_builder.rejected_records:
                outputs["lineage_rejection_reasons"] = [
                    rejection.reason for rejection in lineage_builder.rejected_records[:10]
                ]

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
            outputs["lineage_rejections"] = 0
            outputs["note_lineage"] = "No atoms registered — skipping lineage build."

        # 4. Generate analysis file (atom registry, imports, adjacency, data flow)
        spec_snapshot = self.manager.structure.spec_snapshot_dir
        if spec_snapshot.exists():
            try:
                analysis = generate_analysis_file(
                    algorithmic_dir=spec_snapshot,
                    architectural_dir=root,
                    run_id=self.manager.run_id,
                )
            except AnalysisGenerationUnavailableError as exc:
                outputs["analysis_generation_error"] = str(exc)
                logger.warning("Analysis generation unavailable: %s", exc)
            else:
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

    def _json_read_failures_path(self) -> Path:
        return (
            self.manager.workspace_path
            / ".pdd_runs"
            / self.manager.run_id
            / "errors"
            / "json_read_failures.jsonl"
        )

    def _record_json_read_failure(
        self,
        path: Path,
        *,
        reader: str,
        reason: str,
        detail: str = "",
    ) -> None:
        entry = {
            "reader": str(reader).strip(),
            "reason": str(reason).strip(),
            "path": str(path),
            "detail": str(detail).strip(),
        }
        log_path = self._json_read_failures_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

    def _read_json_dict(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            self._record_json_read_failure(
                path,
                reader="read_json_dict",
                reason="missing",
            )
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            self._record_json_read_failure(
                path,
                reader="read_json_dict",
                reason="unreadable",
                detail=str(exc),
            )
            return None
        except json.JSONDecodeError as exc:
            self._record_json_read_failure(
                path,
                reader="read_json_dict",
                reason="invalid_json",
                detail=str(exc),
            )
            return None
        if isinstance(payload, dict):
            return payload
        self._record_json_read_failure(
            path,
            reader="read_json_dict",
            reason="unexpected_type",
            detail=type(payload).__name__,
        )
        return None

    def _latest_slice_bundle_paths(self) -> list[Path]:
        bundles_root = self.manager.workspace_path / ".pdd_runs" / self.manager.run_id / "slices"
        if not bundles_root.exists():
            return []
        latest: list[Path] = []
        for slice_dir in sorted(path for path in bundles_root.iterdir() if path.is_dir()):
            iter_dirs = sorted(
                (
                    path
                    for path in slice_dir.glob("iter_*")
                    if path.is_dir() and (path / "bundle.json").exists()
                ),
                key=lambda path: path.name,
            )
            if iter_dirs:
                latest.append(iter_dirs[-1] / "bundle.json")
        return latest

    def _bundle_snapshot(
        self,
        bundle_payload: dict[str, Any],
        *,
        iteration_dir: Path,
        field_chain: tuple[str, str],
        list_key: str,
    ) -> list[dict[str, Any]]:
        ref = bundle_payload
        for key in field_chain:
            if not isinstance(ref, dict):
                return []
            ref = ref.get(key, {})
        rel_path = str(ref).strip() if isinstance(ref, str) else ""
        if not rel_path:
            return []
        payload = self._read_json_dict(iteration_dir / rel_path)
        if not payload:
            return []
        rows = payload.get(list_key, [])
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    def _collect_pin_edge_snapshot_rows(
        self,
        bundle_paths: list[Path],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        pin_rows: list[dict[str, Any]] = []
        edge_rows: list[dict[str, Any]] = []
        seen_pin_keys: set[tuple[str, str, int, int]] = set()
        used_pin_ids: set[str] = set()
        next_pin_id = 1
        next_edge_id = 1

        for bundle_path in bundle_paths:
            bundle_payload = self._read_json_dict(bundle_path)
            if not bundle_payload:
                continue
            iteration_dir = bundle_path.parent
            snapshot_pins = self._bundle_snapshot(
                bundle_payload,
                iteration_dir=iteration_dir,
                field_chain=("pins_snapshot", "path"),
                list_key="pins",
            )
            snapshot_edges = self._bundle_snapshot(
                bundle_payload,
                iteration_dir=iteration_dir,
                field_chain=("graph_snapshot", "path"),
                list_key="edges",
            )
            implementation_payload = bundle_payload.get("implementation", {})
            if not snapshot_pins and isinstance(implementation_payload, dict):
                raw_pin_proposals = implementation_payload.get("pin_proposals", [])
                if isinstance(raw_pin_proposals, list):
                    for proposal in raw_pin_proposals:
                        if not isinstance(proposal, dict):
                            continue
                        function_name = str(
                            proposal.get("function_name")
                            or proposal.get("pin_id")
                            or proposal.get("id")
                            or ""
                        ).strip()
                        file_path = str(
                            proposal.get("file_path") or proposal.get("file") or ""
                        ).strip()
                        if not function_name or not file_path:
                            continue
                        module_path = str(proposal.get("module_path") or "").strip()
                        if not module_path and "." in function_name:
                            module_path = function_name.rsplit(".", 1)[0]
                        line_start = proposal.get("line_start")
                        if line_start is None:
                            line_start = (proposal.get("span") or {}).get("start_line", 1)
                        line_end = proposal.get("line_end")
                        if line_end is None:
                            line_end = (proposal.get("span") or {}).get("end_line", line_start or 1)
                        snapshot_pins.append(
                            {
                                "pin_func_id": str(
                                    proposal.get("pin_func_id")
                                    or proposal.get("pin_id")
                                    or proposal.get("id")
                                    or ""
                                ).strip(),
                                "function_name": function_name.rsplit(".", 1)[-1],
                                "module_path": module_path,
                                "file_path": file_path,
                                "line_start": line_start or 1,
                                "line_end": line_end or line_start or 1,
                                "signature": str(proposal.get("signature") or "").strip(),
                                "docstring": str(proposal.get("docstring") or "").strip(),
                                "content_hash": str(proposal.get("content_hash") or "").strip(),
                                "is_shape": bool(proposal.get("is_shape", False)),
                                "store_touches": proposal.get("store_touches", []),
                                "evidence_atom_ids": proposal.get("evidence_atom_ids", []),
                            }
                        )
            if not snapshot_edges and isinstance(implementation_payload, dict):
                raw_edge_proposals = implementation_payload.get("edge_proposals", [])
                if isinstance(raw_edge_proposals, list):
                    for proposal in raw_edge_proposals:
                        if not isinstance(proposal, dict):
                            continue
                        src = str(proposal.get("pin_func_id") or proposal.get("src") or "").strip()
                        dst = str(
                            proposal.get("arch_location") or proposal.get("dst") or ""
                        ).strip()
                        if not src or not dst:
                            continue
                        signal_type = str(
                            proposal.get("signal_type") or proposal.get("projection_type") or ""
                        ).strip()
                        snapshot_edges.append(
                            {
                                "edge_id": str(proposal.get("edge_id") or "").strip(),
                                "src": src,
                                "dst": dst,
                                "arch_file_path": str(
                                    proposal.get("arch_file_path") or dst.split(":", 1)[0]
                                ).strip(),
                                "arch_line": proposal.get("arch_line", 0),
                                "projection_type": str(
                                    proposal.get("projection_type") or ""
                                ).strip(),
                                "signal_type": signal_type,
                                "confidence": proposal.get(
                                    "confidence",
                                    proposal.get("weight", 0.8),
                                ),
                                "is_direct_import": bool(proposal.get("is_direct_import", True)),
                            }
                        )

            local_pin_id_map: dict[str, str] = {}
            for row in snapshot_pins:
                function_name = str(row.get("function_name") or "").strip()
                file_path = str(row.get("file_path") or "").strip().replace("\\", "/")
                if not function_name or not file_path:
                    continue
                line_start_raw = row.get("line_start", 1)
                line_end_raw = row.get("line_end", line_start_raw)
                try:
                    line_start = max(int(line_start_raw), 1)
                except (TypeError, ValueError):
                    line_start = 1
                try:
                    line_end = max(int(line_end_raw), line_start)
                except (TypeError, ValueError):
                    line_end = line_start

                key = (function_name, file_path, line_start, line_end)
                proposed_pin_id = str(row.get("pin_func_id") or "").strip()
                if key in seen_pin_keys:
                    if proposed_pin_id:
                        for existing in pin_rows:
                            if (
                                str(existing.get("function_name", "")).strip() == function_name
                                and str(existing.get("file_path", "")).strip().replace("\\", "/")
                                == file_path
                                and int(existing.get("line_start", 0)) == line_start
                                and int(existing.get("line_end", 0)) == line_end
                            ):
                                local_pin_id_map[proposed_pin_id] = str(existing["pin_func_id"])
                                break
                    continue

                canonical_pin_id = proposed_pin_id
                if not canonical_pin_id or canonical_pin_id in used_pin_ids:
                    canonical_pin_id = f"PFUNC-SNAPSHOT-{next_pin_id:04d}"
                    next_pin_id += 1

                local_pin_id_map[proposed_pin_id] = canonical_pin_id
                used_pin_ids.add(canonical_pin_id)
                seen_pin_keys.add(key)
                pin_rows.append(
                    {
                        "pin_func_id": canonical_pin_id,
                        "function_name": function_name,
                        "module_path": str(row.get("module_path") or "").strip(),
                        "file_path": file_path,
                        "line_start": line_start,
                        "line_end": line_end,
                        "signature": str(row.get("signature") or "").strip(),
                        "docstring": str(row.get("docstring") or "").strip(),
                        "content_hash": str(row.get("content_hash") or "").strip(),
                        "is_shape": bool(row.get("is_shape", False)),
                        "store_touches": [
                            str(item).strip()
                            for item in row.get("store_touches", [])
                            if str(item).strip()
                        ],
                        "evidence_atom_ids": [
                            str(item).strip()
                            for item in row.get("evidence_atom_ids", [])
                            if str(item).strip()
                        ],
                    }
                )

            for edge in snapshot_edges:
                src = str(edge.get("src") or edge.get("pin_func_id") or "").strip()
                src = local_pin_id_map.get(src, src)
                if not src:
                    continue
                dst = str(edge.get("dst") or edge.get("arch_location") or "").strip()
                arch_file_path = str(edge.get("arch_file_path") or "").strip()
                if not dst and arch_file_path:
                    dst = arch_file_path
                if not arch_file_path and ":" in dst:
                    arch_file_path = dst.split(":", 1)[0]
                if not dst or not arch_file_path:
                    continue

                edge_id = str(edge.get("edge_id") or "").strip()
                if not edge_id:
                    edge_id = f"IMEDGE-SNAPSHOT-{next_edge_id:04d}"
                    next_edge_id += 1
                edge_rows.append(
                    {
                        "edge_id": edge_id,
                        "pin_func_id": src,
                        "arch_location": dst,
                        "arch_file_path": arch_file_path,
                        "arch_line": edge.get("arch_line", 0),
                        "projection_type": str(edge.get("projection_type") or "").strip().lower(),
                        "signal_type": str(edge.get("signal_type") or "").strip().upper(),
                        "confidence": edge.get("confidence", edge.get("weight", 0.8)),
                        "is_direct_import": bool(edge.get("is_direct_import", True)),
                    }
                )

        return pin_rows, edge_rows

    @staticmethod
    def _projection_type_from_signal(signal: str) -> Any:
        from spec_manager.schemas.pin_functions import ProjectionType

        normalized = signal.upper().strip()
        if normalized == "EVENT":
            return ProjectionType.EVENT_BRIDGE
        if normalized == "STORE_TOUCH":
            return ProjectionType.AGGREGATION
        return ProjectionType.PASS_THROUGH

    @staticmethod
    def _connected_components(
        nodes: set[str],
        edges: list[dict[str, Any]],
    ) -> list[list[str]]:
        adjacency: dict[str, set[str]] = {node: set() for node in nodes}
        for edge in edges:
            src = str(edge.get("src") or "").strip()
            dst = str(edge.get("dst") or "").strip()
            if not src or not dst:
                continue
            adjacency.setdefault(src, set()).add(dst)
            adjacency.setdefault(dst, set()).add(src)

        seen: set[str] = set()
        components: list[list[str]] = []
        for node in sorted(adjacency):
            if node in seen:
                continue
            stack = [node]
            component: list[str] = []
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                component.append(current)
                for neighbor in adjacency.get(current, set()):
                    if neighbor not in seen:
                        stack.append(neighbor)
            components.append(sorted(component))
        return components

    def _pending_demotion_ticket_paths(self) -> Path:
        return (
            self.manager.workspace_path
            / ".pdd_runs"
            / self.manager.run_id
            / "demotions"
            / "tickets"
        )

    def _load_pending_routing_tickets(self) -> list[Any]:
        """Load unresolved demotion tickets that explicitly require routing."""
        from spec_manager.orchestration.demotion import DemotionTicket

        tickets_dir = self._pending_demotion_ticket_paths()
        if not tickets_dir.exists():
            return []
        tickets: list[DemotionTicket] = []
        seen_ids: set[str] = set()
        for ticket_path in sorted(tickets_dir.glob("*.json")):
            try:
                payload = json.loads(ticket_path.read_text(encoding="utf-8"))
            except OSError as exc:
                self._record_json_read_failure(
                    ticket_path,
                    reader="pending_routing_loader",
                    reason="unreadable",
                    detail=str(exc),
                )
                continue
            except json.JSONDecodeError as exc:
                self._record_json_read_failure(
                    ticket_path,
                    reader="pending_routing_loader",
                    reason="invalid_json",
                    detail=str(exc),
                )
                continue
            ticket_raw = payload.get("ticket", payload) if isinstance(payload, dict) else None
            if not isinstance(ticket_raw, dict):
                continue
            ticket = DemotionTicket.from_dict(ticket_raw)
            if not ticket.routing_required:
                continue
            if str(ticket.apply_status).strip().upper() == "APPLIED":
                continue
            if ticket.ticket_id in seen_ids:
                continue
            seen_ids.add(ticket.ticket_id)
            tickets.append(ticket)
        return tickets

    def _pin_registry_is_stale(
        self,
        *,
        registry_path: Path,
        root: Path,
        file_hints: list[str],
    ) -> tuple[bool, str]:
        """Determine whether a registry-derived lineage view is stale."""
        try:
            registry_mtime = registry_path.stat().st_mtime
        except OSError as exc:
            return True, f"registry_unreadable:{exc}"

        for hint in file_hints:
            rel = str(hint).strip()
            if not rel:
                continue
            candidate = Path(rel)
            if not candidate.is_absolute():
                root_candidate = root / candidate
                workspace_candidate = self.manager.workspace_path / candidate
                if root_candidate.exists():
                    candidate = root_candidate
                elif workspace_candidate.exists():
                    candidate = workspace_candidate
                else:
                    return True, f"missing_source:{rel}"
            if not candidate.exists():
                return True, f"missing_source:{rel}"
            try:
                if candidate.stat().st_mtime > registry_mtime:
                    return True, f"newer_source:{rel}"
            except OSError as exc:
                return True, f"source_unreadable:{rel}:{exc}"
        return False, ""

    def _run_task_planning(self) -> dict[str, Any]:
        """Phase 8: Build a task plan from canonical gap evidence."""
        facts_rows, facts_errors = self._load_or_build_canonical_file_facts()
        target_files = [
            str(row.get("path", "")).strip()
            for row in facts_rows
            if isinstance(row, dict) and str(row.get("path", "")).strip()
        ]

        # Derive intentions from Phase 3 compliance gap descriptions
        phase3_result = self.manager.state.phases.get(Phase.COMPLIANCE_CLEAN.value)
        intentions: list[str] = []
        if phase3_result and phase3_result.outputs:
            gap_count = phase3_result.outputs.get("gaps_found", 0)
            if gap_count > 0:
                intentions.append(
                    f"Resolve {gap_count} executable gaps found during compliance scan"
                )

        plan_items: list[dict[str, Any]] = []
        for error in facts_errors:
            plan_items.append(
                {
                    "file": "",
                    "action": "inspect",
                    "priority": "high",
                    "reason": error,
                }
            )

        for row in facts_rows:
            if not isinstance(row, dict):
                continue
            rel_path = str(row.get("path", "")).strip()
            file_facts = row.get("file_facts")
            if not rel_path or not isinstance(file_facts, dict):
                plan_items.append(
                    {
                        "file": rel_path,
                        "action": "inspect",
                        "priority": "high",
                        "reason": "Missing canonical file-facts payload for planning.",
                    }
                )
                continue

            for gap in file_facts.get("remaining_gap_pins", []):
                if not isinstance(gap, dict):
                    continue
                kind = str(gap.get("kind", "")).strip()
                if kind not in {"comment_gap", "stub_gap"}:
                    continue
                plan_items.append(
                    {
                        "file": rel_path,
                        "action": "implement",
                        "priority": "high" if kind == "stub_gap" else "medium",
                        "kind": kind,
                        "anchor": str(gap.get("pin_id", "")),
                        "description": str(gap.get("description", "")),
                    }
                )

        if not plan_items:
            plan_items.append(
                {
                    "file": "",
                    "action": "verify",
                    "priority": "low",
                    "reason": "No open executable gaps detected from canonical analysis.",
                }
            )

        result = {
            "run_id": self.manager.run_id,
            "target_files": target_files,
            "intentions": intentions,
            "items": plan_items,
        }
        return {"planning_result": result}

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

        # Detect coupling/cohesion issues and account for graph-missing entities.
        dropped_entities: list = []
        issues = detect_all(
            adjacency_graph,
            grouping_units,
            dropped_entities=dropped_entities,
        )

        # Propose operations (analysis only — not executed)
        operations = propose_operations(issues)

        # Validate proposed operations
        valid_ops: list = []
        invalid_ops: list = []
        for op in operations:
            errors = validate_operation(
                op,
                adjacency_graph,
                source_memberships=slice_entities,
            )
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
            "dropped_entities": [de.__dict__ for de in dropped_entities],
            "dropped_entity_count": len(dropped_entities),
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
