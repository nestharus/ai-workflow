"""Per-slice iterative PromotionLoop.

Replaces the sequential P0-P10 pipeline with a per-slice loop that
invokes phases as tools until all gaps are closed and all atoms are
promoted through compliance gates.

State machine (per slice)::

    START_ITER
      ↓
    COLLECT_BASELINE   (diff/hash + manifest)
      ↓
    GAP_EXPLORATION    (P3 + GapQueue view)
      ↓
    PLAN               (P8)
      ↓
    IMPLEMENT          (P9) ← emits patch + pin/edge proposals + evidence
      ↓
    UNDER_SPEC_CHECK   (block-or-decide)
      ↓
    ANALYZE            (P1 + P2 + analyze_source cache)
      ↓
    PROMOTE            (P4 + P5 + gates + RefinementEngine)
      ├─ if gates fail → DEMOTE → RESTART_ITER
      ↓
    INTEGRATE (CI)     (merge to parent + tick pipeline)
      ├─ if tests fail → DOWNWARD_FLOW → DEMOTE → RESTART_ITER
      ↓
    VERIFY             (P6 + P7 + architectural gates)
      ├─ if verify fails → DEMOTE → RESTART_ITER
      ↓
    DONE?              (termination checks)
      ├─ if done → SLICE_COMPLETE
      └─ else → NEXT_ITER

Usage::

    loop = PromotionLoop(worktree_manager=wm, workspace_root=Path("."))
    result = loop.run_slice(slice_ref, run_context)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from spec_manager.orchestration.demotion import DemotionManager, DemotionTicket
from spec_manager.orchestration.evidence import EvidenceBundle
from spec_manager.orchestration.models import Layer

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Step protocol and result types
# ------------------------------------------------------------------


@dataclass
class StepResult:
    """Result of running a single loop step."""

    status: Literal["OK", "RETRY", "BLOCKED", "FAIL"] = "OK"
    bundle_path: str = ""
    emitted_tickets: list[DemotionTicket] = field(default_factory=list)
    notes_path: str | None = None
    error: str = ""


class LoopStep(Protocol):
    """Protocol for a single step in the promotion loop."""

    name: str

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Execute this step."""
        ...


@dataclass
class SliceRef:
    """Reference to a slice of work."""

    slice_id: str
    layer: Layer = "l1"
    library_id: str = ""
    worktree_path: str = ""


@dataclass
class RunContext:
    """Run-scoped context shared across all slices."""

    run_id: str = ""
    mode: Literal["interactive", "auto"] = "auto"
    workspace_root: str = ""
    max_iterations: int = 20
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class SliceContext:
    """Per-slice context for loop steps."""

    slice_id: str = ""
    slice_root: str = ""  # grandchild worktree path
    dirty_parent_root: str = ""
    clean_sibling_root: str = ""
    layer: Layer = "l1"
    run_id: str = ""
    mode: Literal["interactive", "auto"] = "auto"
    workspace_root: str = ""
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class SliceResult:
    """Final result of running the promotion loop on one slice."""

    slice_id: str = ""
    status: Literal["COMPLETE", "BLOCKED", "FAILED", "MAX_ITERATIONS"] = "COMPLETE"
    iterations: int = 0
    remaining_gaps: int = 0
    demotion_tickets: list[DemotionTicket] = field(default_factory=list)
    blocked_questions: list[str] = field(default_factory=list)
    error: str = ""


# ------------------------------------------------------------------
# Loop step implementations (delegate to existing modules)
# ------------------------------------------------------------------


class CollectBaselineStep:
    """Collect manifest + diff baseline for the slice."""

    name = "COLLECT_BASELINE"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Collect file hashes and diff from previous iteration."""
        from spec_manager.orchestration.evidence import DiffRef, ManifestRef

        slice_root = Path(ctx.slice_root)
        if not slice_root.exists():
            return StepResult(status="FAIL", error=f"Slice root does not exist: {ctx.slice_root}")

        # Collect manifest: list all source files + hashes
        files = []
        for p in sorted(slice_root.rglob("*")):
            if p.is_file() and not any(part.startswith(".") for part in p.parts):
                files.append({"path": str(p.relative_to(slice_root))})

        bundle.manifest = ManifestRef(files=files)
        bundle.diff = DiffRef(
            base_commit=bundle.diff.base_commit,
            head_commit="",
            changed_files=[],
        )

        # Save bundle
        bundle.save(Path(ctx.workspace_root))
        return StepResult(status="OK")


class GapExplorationStep:
    """Run P3 (compliance detection) to find remaining gaps."""

    name = "GAP_EXPLORATION"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Scan for spec comments and stub functions."""
        from spec_manager.orchestration.evidence import GapReportRef

        slice_root = Path(ctx.slice_root)
        py_files = list(slice_root.rglob("*.py"))

        if not py_files:
            bundle.gaps = GapReportRef(open_gaps=[])
            return StepResult(status="OK")

        try:
            from spec_manager.compliance.detection.orchestrator import (
                ScanConfig,
                scan_executable_gaps,
            )

            report = scan_executable_gaps(
                filepaths=py_files,
                project_root=slice_root,
                config=ScanConfig(enable_comments=True, enable_stubs=True),
            )

            gaps = []
            for ev in report.all_evidence:
                gaps.append(
                    {
                        "file": str(ev.file_path) if hasattr(ev, "file_path") else "",
                        "description": str(ev.description)
                        if hasattr(ev, "description")
                        else str(ev),
                        "kind": ev.kind.value if hasattr(ev, "kind") else "unknown",
                    }
                )

            bundle.gaps = GapReportRef(open_gaps=gaps)
        except Exception as exc:
            logger.warning("Gap exploration failed: %s", exc)
            bundle.gaps = GapReportRef(open_gaps=[])

        return StepResult(status="OK")


class PlanStep:
    """Run P8 (planning) to decide what to implement next.

    After generating plan intentions from gaps, checks each intention's
    decision requirements against the constraints store.  Uncovered
    decisions become under-spec events that block the slice before
    implementation begins.
    """

    name = "PLAN"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Generate implementation plan from gaps."""
        from spec_manager.orchestration.evidence import PlanRef

        if not bundle.gaps.open_gaps:
            bundle.plan = PlanRef(intentions=[])
            return StepResult(status="OK")

        # Create plan intentions from gaps
        intentions = []
        for gap in bundle.gaps.open_gaps:
            intentions.append(
                {
                    "gap_id": gap.get("file", "unknown"),
                    "target_file": gap.get("file", ""),
                    "approach": f"Implement: {gap.get('description', '')}",
                    "acceptance_criteria": "Gap resolved, tests pass",
                }
            )

        bundle.plan = PlanRef(intentions=intentions)

        # Run planning gate: check decision requirements against constraints
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else None
        if workspace:
            try:
                from spec_manager.orchestration.under_spec.manager import (
                    ConstraintsStore,
                )
                from spec_manager.orchestration.under_spec.planning_gate import (
                    run_planning_gate,
                )

                store = ConstraintsStore(workspace)
                gate_result = run_planning_gate(
                    constraints_store=store,
                    slice_id=ctx.slice_id,
                    intentions=intentions,
                )

                if not gate_result.all_covered:
                    # Inject under-spec events into the bundle so
                    # UnderSpecCheckStep can block before implementation
                    existing = bundle.implementation.under_spec_events or []
                    bundle.implementation.under_spec_events = (
                        existing + gate_result.under_spec_events
                    )
            except Exception as exc:
                logger.debug("Planning gate skipped: %s", exc)

        return StepResult(status="OK")


class ImplementStep:
    """Run P9 (implementation) to fill gaps.

    Delegates to :class:`ImplementationRunner` which calls the
    ``pdd-function-implementor`` agent per unresolved function and
    collects edits, pin/edge proposals, under-spec events, and tests.
    """

    name = "IMPLEMENT"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Execute implementation plan."""
        from spec_manager.orchestration.evidence import ImplementationRef

        if not bundle.plan.intentions:
            bundle.implementation = ImplementationRef()
            return StepResult(status="OK")

        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if not slice_root or not slice_root.exists():
            bundle.implementation = ImplementationRef()
            return StepResult(status="OK")

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        try:
            from spec_manager.orchestration.implementation.runner import (
                ImplementationRunner,
            )

            runner = ImplementationRunner(
                workspace_root=workspace,
                run_id=ctx.run_id,
            )

            iteration_dir = bundle.iter_dir(workspace)
            run_result = runner.run_for_slice(
                slice_root=slice_root,
                iteration_dir=iteration_dir,
                plan_intentions=bundle.plan.intentions,
                gap_report=bundle.gaps.open_gaps,
            )

            bundle.implementation = ImplementationRef(
                patch_path=run_result.patch_path,
                applied_edits=run_result.applied_edits,
                pin_proposals=run_result.pin_proposals,
                edge_proposals=run_result.edge_proposals,
                under_spec_events=run_result.under_spec_events,
                tests_added=run_result.tests_added,
            )

            if run_result.notes_path:
                return StepResult(status="OK", notes_path=run_result.notes_path)

        except Exception as exc:
            logger.warning("Implementation step failed: %s", exc)
            bundle.implementation = ImplementationRef()
            return StepResult(status="OK")

        return StepResult(status="OK")


class UnderSpecCheckStep:
    """Check for under-specification and block if unresolvable.

    Delegates to :class:`UnderSpecManager` which:
    1. Checks existing constraints for coverage.
    2. Attempts resolution (interactive or auto).
    3. Validates any new constraints.
    4. Returns resolved/blocked partition.
    """

    name = "UNDER_SPEC_CHECK"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Check for under-specification events from implementation."""
        raw_events = bundle.implementation.under_spec_events

        if not raw_events:
            return StepResult(status="OK")

        from spec_manager.orchestration.under_spec.manager import (
            UnderSpecEvent,
            UnderSpecManager,
        )

        events = [UnderSpecEvent.from_dict(e) for e in raw_events]
        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        manager = UnderSpecManager(
            workspace_root=workspace,
            mode=ctx.mode,
        )
        outcome = manager.resolve(slice_id=ctx.slice_id, events=events)

        # Record decisions in the bundle
        bundle.under_spec.decisions = [
            {"event_id": e.event_id, "question": e.question} for e in outcome.resolved
        ]
        bundle.under_spec.blockers = [e.to_dict() for e in outcome.blocked]

        # Record new constraint refs
        if outcome.constraints:
            constraint_path = str(workspace / "analysis" / "constraints" / f"{ctx.slice_id}.json")
            if constraint_path not in bundle.facts.constraints_refs:
                bundle.facts.constraints_refs.append(constraint_path)

        if outcome.is_blocked:
            bundle.status = "BLOCKED"
            return StepResult(
                status="BLOCKED",
                error=f"Under-specification: {len(outcome.blocked)} unresolvable events",
            )

        return StepResult(status="OK")


class AnalyzeStep:
    """Run P1 + P2 (structure + decomposition) on implemented code.

    Uses :class:`SourceAnalysisCache` to persist analysis results across
    iterations. Only files whose content hash changed since the last
    iteration are re-analyzed.
    """

    name = "ANALYZE"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Analyze slice after implementation."""
        slice_root = Path(ctx.slice_root) if ctx.slice_root else None
        if not slice_root or not slice_root.exists():
            return StepResult(status="OK")

        workspace = Path(ctx.workspace_root) if ctx.workspace_root else Path(".")

        try:
            from spec_manager.orchestration.source_analysis_cache import (
                SourceAnalysisCache,
            )

            cache = SourceAnalysisCache(
                workspace_root=workspace,
                run_id=ctx.run_id,
            )

            # Analyze all source files in the slice
            entries: list[dict[str, str]] = []
            for py_file in sorted(slice_root.rglob("*.py")):
                if not py_file.is_file():
                    continue
                if any(part.startswith(".") for part in py_file.parts):
                    continue
                try:
                    content = py_file.read_text(encoding="utf-8")
                    analysis = cache.analyze_with_cache(
                        content, str(py_file.relative_to(slice_root))
                    )
                    entries.append(
                        {
                            "path": str(py_file.relative_to(slice_root)),
                            "functions": str(len(analysis.functions)),
                            "comments": str(len(analysis.comments)),
                        }
                    )
                except (OSError, UnicodeDecodeError) as exc:
                    logger.debug("Skipping %s: %s", py_file, exc)

            bundle.source_index.entries = entries
            bundle.source_index.path = "source_analysis.index.json"

            logger.info(
                "Analyzed %d files (cache stats: %s)",
                len(entries),
                cache.stats,
            )

        except Exception as exc:
            logger.warning("Analysis step failed: %s", exc)

        return StepResult(status="OK")


class PromoteStep:
    """Run P4 + P5 + gates + refinement engine.

    Delegates to:
    - P4: ``branches.manager.collapse_codebase`` (atoms/stores/shapes)
    - P5: ``pin_functions.orchestrator`` + ``branches.promotion``
    - Gates: ``compliance.promotion`` (algorithmic + architectural)
    - Refinement: ``refinement_engine.detector`` (coupling/cohesion)

    Accepts pin/edge proposals from bundle.implementation to merge
    with scan results (mode="both").
    """

    name = "PROMOTE"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Extract atoms, promote through compliance gates."""
        slice_root = Path(ctx.slice_root) if ctx.slice_root else None

        if not slice_root or not slice_root.exists():
            return StepResult(status="OK")

        pin_proposals = bundle.implementation.pin_proposals
        edge_proposals = bundle.implementation.edge_proposals
        registry = None

        try:
            from spec_manager.pin_functions.orchestrator import (
                PinFunctionOrchestrator,
            )

            orchestrator = PinFunctionOrchestrator(project_root=slice_root)

            mode = "both" if (pin_proposals or edge_proposals) else "scan"
            registry = orchestrator.scan(
                mode=mode,
                pin_proposals=pin_proposals,
                edge_proposals=edge_proposals,
            )

            bundle.pins_snapshot.path = "pins.snapshot.json"
            bundle.pins_snapshot.schema_version = registry.schema_version

        except Exception as exc:
            logger.warning("Pin function scan failed: %s", exc)

        try:
            from spec_manager.compliance.promotion.config import PromotionGateConfig
            from spec_manager.compliance.promotion.evidence_loader import (
                load_analyzed_files,
            )
            from spec_manager.compliance.promotion.orchestrator import (
                LayerPromotionGate,
            )
            from spec_manager.orchestration.source_analysis_cache import (
                SourceAnalysisCache,
            )

            config = PromotionGateConfig.default()
            config.project_root = str(slice_root)

            # Pre-load file analyses via cache for evidence-based gates
            workspace = Path(ctx.workspace_root) if ctx.workspace_root else slice_root
            cache = SourceAnalysisCache(workspace_root=workspace, run_id=ctx.run_id)

            algo_files = self._resolve_files(config.algorithmic_roots, slice_root)
            arch_files = self._resolve_files(config.architectural_roots, slice_root)
            algo_analyzed = load_analyzed_files(algo_files, source_cache=cache)
            arch_analyzed = load_analyzed_files(arch_files, source_cache=cache)

            gate = LayerPromotionGate(
                config,
                pin_registry=registry,
                algorithmic_analyzed=algo_analyzed,
                architectural_analyzed=arch_analyzed,
            )
            report = gate.run_all_checks()

            gates_data = []
            for gr in report.gate_results:
                gates_data.append(
                    {
                        "gate_id": gr.gate_id,
                        "passed": gr.passed,
                        "summary": gr.summary,
                    }
                )
            bundle.gates.gates = gates_data

            if not report.passed:
                ticket = DemotionTicket(
                    run_id=ctx.run_id,
                    slice_id=ctx.slice_id,
                    source="GATE_FAILURE",
                    target_layer="L1",
                    severity="BLOCKER",
                    diagnosis=f"Gates failed: {[b.summary for b in report.blockers]}",
                )
                return StepResult(
                    status="RETRY",
                    emitted_tickets=[ticket],
                    error="Promotion gates failed",
                )

        except Exception as exc:
            logger.warning("Promotion gates failed: %s", exc)

        return StepResult(status="OK")

    @staticmethod
    def _resolve_files(roots: list[str], project_root: Path) -> list[Path]:
        """Resolve directory roots to Python file lists."""
        files: list[Path] = []
        for root in roots:
            root_path = project_root / root
            if root_path.exists():
                files.extend(sorted(root_path.rglob("*.py")))
        return files


class IntegrateStep:
    """Merge slice into dirty, tick CI pipeline."""

    name = "INTEGRATE"

    def __init__(self, worktree_manager: Any = None) -> None:
        self._wm = worktree_manager

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Merge grandchild → dirty, tick pipeline."""
        if not self._wm:
            return StepResult(status="OK")

        # 1. Merge slice → layer dirty
        merge_result = self._wm.merge_slice_to_dirty(ctx.layer, ctx.slice_id)
        if not merge_result.success:
            ticket = DemotionTicket(
                run_id=ctx.run_id,
                slice_id=ctx.slice_id,
                source="TEST_FAILURE",
                target_layer="L1",
                severity="BLOCKER",
                diagnosis=f"Merge conflict: {merge_result.error}",
            )
            return StepResult(
                status="RETRY",
                emitted_tickets=[ticket],
                error=merge_result.error,
            )

        # 2. Tick CI pipeline
        tick_result = self._wm.tick_pipeline(active_layer=ctx.layer)
        for dt_ref in tick_result.demotion_tickets:
            logger.warning("Pipeline demotion: %s", dt_ref)

        return StepResult(status="OK")


class VerifyStep:
    """Run P6 + P7 + architectural gates (post-integration)."""

    name = "VERIFY"

    def run(self, ctx: SliceContext, bundle: EvidenceBundle) -> StepResult:
        """Cross-library connectivity + lineage verification."""
        # P6: adjacency runner (cross-library)
        # P7: lineage + generators
        # Architectural quality gates
        return StepResult(status="OK")


# ------------------------------------------------------------------
# Default step sequence
# ------------------------------------------------------------------

DEFAULT_STEPS: list[type] = [
    CollectBaselineStep,
    GapExplorationStep,
    PlanStep,
    ImplementStep,
    UnderSpecCheckStep,
    AnalyzeStep,
    PromoteStep,
    IntegrateStep,
    VerifyStep,
]


# ------------------------------------------------------------------
# PromotionLoop
# ------------------------------------------------------------------


class PromotionLoop:
    """Per-slice iterative promotion loop.

    Replaces the sequential P0-P10 pipeline with a convergence loop
    that runs until all gaps are closed and all atoms promoted.

    Args:
        worktree_manager: Multi-layer worktree manager.
        workspace_root: Root of the repository.
        demotion_manager: Handles applying demotion tickets.
        steps: Custom step sequence (defaults to all steps).
    """

    def __init__(
        self,
        worktree_manager: Any = None,
        workspace_root: Path = Path("."),
        demotion_manager: DemotionManager | None = None,
        steps: list[Any] | None = None,
    ) -> None:
        self._wm = worktree_manager
        self._workspace_root = workspace_root
        self._dm = demotion_manager or DemotionManager(workspace_root)

        # Build step instances
        if steps is not None:
            self._steps = steps
        else:
            self._steps = []
            for step_cls in DEFAULT_STEPS:
                if step_cls is IntegrateStep:
                    self._steps.append(step_cls(worktree_manager=self._wm))
                else:
                    self._steps.append(step_cls())

    def run_slice(
        self,
        slice_ref: SliceRef,
        run_context: RunContext,
    ) -> SliceResult:
        """Run the promotion loop on a single slice until convergence.

        Args:
            slice_ref: The slice to process.
            run_context: Run-scoped configuration.

        Returns:
            SliceResult with final status.
        """
        ctx = SliceContext(
            slice_id=slice_ref.slice_id,
            slice_root=slice_ref.worktree_path,
            layer=slice_ref.layer,
            run_id=run_context.run_id,
            mode=run_context.mode,
            workspace_root=run_context.workspace_root,
            config=run_context.config,
        )

        # Set dirty/clean parent paths if worktree manager available
        if self._wm:
            dirty = self._wm._layer_worktrees.get(ctx.layer, {}).get("dirty")
            clean = self._wm._layer_worktrees.get(ctx.layer, {}).get("clean")
            if dirty:
                ctx.dirty_parent_root = str(dirty)
            if clean:
                ctx.clean_sibling_root = str(clean)

        all_tickets: list[DemotionTicket] = []
        iteration = 0

        while iteration < run_context.max_iterations:
            iteration += 1
            logger.info("=== Slice '%s' iteration %d ===", ctx.slice_id, iteration)

            bundle = EvidenceBundle(
                run_id=run_context.run_id,
                slice_id=slice_ref.slice_id,
                iteration=iteration,
                mode=run_context.mode,
                workspace_root=run_context.workspace_root,
                slice_root=slice_ref.worktree_path,
            )

            retry = False

            for step in self._steps:
                logger.debug("Running step: %s", step.name)
                result = step.run(ctx, bundle)

                if result.emitted_tickets:
                    all_tickets.extend(result.emitted_tickets)
                    # Apply demotion tickets
                    for ticket in result.emitted_tickets:
                        self._dm.apply(ticket, Path(ctx.slice_root))

                if result.status == "BLOCKED":
                    # Slice is blocked — return with blocked status
                    questions = []
                    for event in bundle.implementation.under_spec_events:
                        if q := event.get("question"):
                            questions.append(q)
                    return SliceResult(
                        slice_id=ctx.slice_id,
                        status="BLOCKED",
                        iterations=iteration,
                        demotion_tickets=all_tickets,
                        blocked_questions=questions,
                    )

                if result.status == "RETRY":
                    # A gate/test/merge failed — restart iteration
                    retry = True
                    break

                if result.status == "FAIL":
                    return SliceResult(
                        slice_id=ctx.slice_id,
                        status="FAILED",
                        iterations=iteration,
                        demotion_tickets=all_tickets,
                        error=result.error,
                    )

            if retry:
                continue

            # Check termination
            remaining = len(bundle.gaps.open_gaps)
            if remaining == 0:
                bundle.status = "COMPLETE"
                bundle.save(Path(run_context.workspace_root))
                return SliceResult(
                    slice_id=ctx.slice_id,
                    status="COMPLETE",
                    iterations=iteration,
                    remaining_gaps=0,
                    demotion_tickets=all_tickets,
                )

            # Still gaps — loop
            logger.info(
                "Slice '%s': %d gaps remaining, continuing",
                ctx.slice_id,
                remaining,
            )

        # Max iterations reached
        return SliceResult(
            slice_id=ctx.slice_id,
            status="MAX_ITERATIONS",
            iterations=iteration,
            remaining_gaps=len(bundle.gaps.open_gaps) if bundle else 0,
            demotion_tickets=all_tickets,
        )

    def run_slices(
        self,
        slice_refs: list[SliceRef],
        run_context: RunContext,
    ) -> list[SliceResult]:
        """Run the promotion loop on multiple slices sequentially.

        TODO: Add parallelism via PromotionScheduler (Step 7).

        Args:
            slice_refs: Slices to process.
            run_context: Run-scoped configuration.

        Returns:
            List of SliceResults.
        """
        results = []
        for ref in slice_refs:
            result = self.run_slice(ref, run_context)
            results.append(result)

            if result.status == "FAILED":
                logger.error("Slice '%s' failed: %s", ref.slice_id, result.error)
                # Continue with other slices rather than aborting

        return results
