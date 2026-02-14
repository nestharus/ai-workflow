"""End-to-end QA evaluation for the full PDD pipeline.

Runs the chaotic_treasury_expanded fixture through L1→L2→L3 step-by-step,
capturing each LLM output and comparing against ground truth.

Usage::

    # Run the full eval (requires LLM API keys)
    uv run python -m spec_manager.refinement.evals.e2e_eval

    # Run with a specific layer only
    uv run python -m spec_manager.refinement.evals.e2e_eval --layer l1

    # Run a single slice within a layer
    uv run python -m spec_manager.refinement.evals.e2e_eval --layer l1 --slice LIB-02

    # Dry-run: setup workspace only, no LLM calls
    uv run python -m spec_manager.refinement.evals.e2e_eval --setup-only

    # Resume from a checkpoint
    uv run python -m spec_manager.refinement.evals.e2e_eval --resume <run_id>
"""

from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Library → PDD skeleton file mapping
# ---------------------------------------------------------------------------

# Maps library IDs to their PDD skeleton Python files.
# Derived from libraries.yaml overlap_notes and route_table.jsonl.
_LIB_TO_PDD_FILES: dict[str, list[str]] = {
    "LIB-01": ["settlement_processor.py", "transaction_validator.py"],
    "LIB-02": ["risk_engine.py"],
    "LIB-03": ["reconciliation_service.py"],
    "LIB-04": ["regulatory_compliance.py"],
    "LIB-05": ["event_pipeline.py"],
    "LIB-06": ["audit_notification.py"],
    "LIB-07": [],  # Operations/deployment — no PDD skeleton
    "LIB-08": ["settlement_orchestration.py"],
}

# ---------------------------------------------------------------------------
# Fixture paths (relative to repo root)
# ---------------------------------------------------------------------------

_FIXTURES_REL = Path("scripts/spec_manager/spec_manager/refinement/evals/inputs/fixtures")
_PDD_SKELETONS_REL = _FIXTURES_REL / "chaotic_treasury_expanded_pdd"
_PHASE0_OUTPUT_REL = _FIXTURES_REL / "chaotic_treasury_expanded_phase0_output"
_GROUND_TRUTH_REL = _FIXTURES_REL / "chaotic_treasury_expanded_ground_truth.yaml"


def _resolve(rel: Path) -> Path:
    """Resolve a repo-relative path to an absolute path."""
    from spec_manager.core.project_root import get_project_root

    return get_project_root() / rel


# ---------------------------------------------------------------------------
# Ground truth loader
# ---------------------------------------------------------------------------


@dataclass
class GroundTruth:
    """Loaded ground truth for comparison."""

    sections: list[str] = field(default_factory=list)
    libraries: list[str] = field(default_factory=list)
    library_names: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    total_requirements: int = 52

    @classmethod
    def load(cls, path: Path) -> GroundTruth:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            sections=data.get("sectionization", {}).get("expected_sections", []),
            libraries=data.get("summarization", {}).get("expected_libraries", []),
            library_names=data.get("library_synthesis", {}).get("expected_libraries", []),
            requirements=data.get("library_synthesis", {}).get("expected_requirements", []),
            total_requirements=data.get("overall_requirements_count", 52),
        )


# ---------------------------------------------------------------------------
# Step result capture
# ---------------------------------------------------------------------------


@dataclass
class StepCapture:
    """Capture of a single promotion loop step execution."""

    step_name: str
    slice_id: str
    layer: str
    iteration: int
    status: str = "OK"
    duration_s: float = 0.0
    gaps_before: int = 0
    gaps_after: int = 0
    intentions_count: int = 0
    edits_count: int = 0
    under_spec_count: int = 0
    gates_passed: int = 0
    gates_failed: int = 0
    demotions: int = 0
    error: str = ""
    raw_output: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SliceCapture:
    """Capture of a full slice promotion loop."""

    slice_id: str
    layer: str
    iterations: int = 0
    final_status: str = ""
    steps: list[StepCapture] = field(default_factory=list)
    total_duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id,
            "layer": self.layer,
            "iterations": self.iterations,
            "final_status": self.final_status,
            "total_duration_s": self.total_duration_s,
            "steps": [s.to_dict() for s in self.steps],
        }


@dataclass
class LayerCapture:
    """Capture of a full layer execution."""

    layer: str
    slices: list[SliceCapture] = field(default_factory=list)
    entry_refinement: dict[str, Any] = field(default_factory=dict)
    exit_refinement: dict[str, Any] = field(default_factory=dict)
    transition: dict[str, Any] = field(default_factory=dict)
    total_duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "total_duration_s": self.total_duration_s,
            "entry_refinement": self.entry_refinement,
            "exit_refinement": self.exit_refinement,
            "transition": self.transition,
            "slices": [s.to_dict() for s in self.slices],
        }


@dataclass
class EvalCapture:
    """Full end-to-end eval capture."""

    run_id: str
    started_at: float = 0.0
    completed_at: float = 0.0
    layers: list[LayerCapture] = field(default_factory=list)
    ground_truth_comparison: dict[str, Any] = field(default_factory=dict)
    final_scoring: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "layers": [layer.to_dict() for layer in self.layers],
            "ground_truth_comparison": self.ground_truth_comparison,
            "final_scoring": self.final_scoring,
        }


# ---------------------------------------------------------------------------
# Workspace setup
# ---------------------------------------------------------------------------


def setup_workspace(run_id: str, *, force: bool = True) -> tuple[Any, Path]:
    """Initialize workspace with PDD skeletons + Phase 0 output.

    1. Create workspace with PDD skeleton files as ``spec_snapshot``
    2. Install Phase 0 output (libraries/, summaries/)

    Returns:
        Tuple of (WorkspaceManager, workspace_root_path).
    """
    from spec_manager.refinement.workspace.manager import WorkspaceManager

    pdd_dir = _resolve(_PDD_SKELETONS_REL)
    phase0_dir = _resolve(_PHASE0_OUTPUT_REL)

    if not pdd_dir.exists():
        raise FileNotFoundError(f"PDD skeletons not found: {pdd_dir}")
    if not phase0_dir.exists():
        raise FileNotFoundError(f"Phase 0 output not found: {phase0_dir}")

    # Create workspace with PDD skeletons as input
    manager = WorkspaceManager(run_id=run_id, input_folder=pdd_dir)
    issues = manager.initialize(force=force)
    if issues:
        logger.warning("Workspace init issues: %s", issues)

    workspace_root = manager.workspace_path

    # Remove __pycache__ from spec_snapshot (copied from PDD fixture dir)
    pycache = workspace_root / "spec_snapshot" / "__pycache__"
    if pycache.exists():
        shutil.rmtree(pycache)

    # Install Phase 0 output into workspace
    _install_phase0_output(workspace_root, phase0_dir)

    logger.info("Workspace ready at %s", workspace_root)
    return manager, workspace_root


def _install_phase0_output(workspace_root: Path, phase0_dir: Path) -> None:
    """Copy Phase 0 output artifacts into the workspace.

    Phase 0 produces:
    - libraries/ (LIB-01 through LIB-08 with details/)
    - summaries/ (per-section JSON summaries)
    - libraries.yaml, route_table.jsonl, coverage_ledger.jsonl
    """
    # Install libraries
    src_libs = phase0_dir / "libraries"
    dst_libs = workspace_root / "libraries"
    if src_libs.exists():
        if dst_libs.exists():
            shutil.rmtree(dst_libs)
        shutil.copytree(src_libs, dst_libs)
        logger.info("Installed %d libraries", len(list(dst_libs.iterdir())))

    # Install summaries
    src_summaries = phase0_dir / "summaries"
    dst_summaries = workspace_root / "summaries"
    if src_summaries.exists():
        if dst_summaries.exists():
            shutil.rmtree(dst_summaries)
        shutil.copytree(src_summaries, dst_summaries)

    # Install top-level Phase 0 artifacts
    for fname in ("libraries.yaml", "route_table.jsonl", "coverage_ledger.jsonl"):
        src = phase0_dir / fname
        if src.exists():
            shutil.copy2(src, workspace_root / fname)

    # Create per-library slice directories with Python files for L1
    _create_l1_slice_dirs(workspace_root)

    logger.info("Phase 0 output installed into workspace")


def _create_l1_slice_dirs(workspace_root: Path) -> None:
    """Create per-library directories with Python files for L1 gap exploration.

    ``_discover_slices('l1')`` points worktree_path at ``libraries/<LIB-XX>``
    which only contains Phase 0 markdown analysis. But L1 gap exploration
    (``scan_executable_gaps``) needs ``.py`` files.

    This function creates ``l1_slices/<LIB-XX>/`` directories, each containing
    copies of the relevant PDD skeleton Python files from ``spec_snapshot/``.
    The eval overrides slice worktree_path to point here instead.
    """
    spec_dir = workspace_root / "spec_snapshot"
    slices_dir = workspace_root / "l1_slices"
    slices_dir.mkdir(parents=True, exist_ok=True)

    for lib_id, py_files in _LIB_TO_PDD_FILES.items():
        lib_slice_dir = slices_dir / lib_id
        lib_slice_dir.mkdir(parents=True, exist_ok=True)
        for fname in py_files:
            src = spec_dir / fname
            if src.exists():
                shutil.copy2(src, lib_slice_dir / fname)
            else:
                logger.warning("PDD skeleton not found: %s (expected for %s)", fname, lib_id)

    logger.info(
        "Created L1 slice directories: %s",
        [d.name for d in sorted(slices_dir.iterdir()) if d.is_dir()],
    )


def _remap_l1_slices(slice_refs: list[Any], workspace_root: Path) -> list[Any]:
    """Remap L1 slice worktree_path from libraries/ to l1_slices/.

    Returns a new list of SliceRef objects with corrected paths.
    Skips libraries that have no PDD skeleton files (e.g. LIB-07).
    """
    from spec_manager.orchestration.promotion_loop import SliceRef

    remapped = []
    for ref in slice_refs:
        lib_id = ref.slice_id
        py_files = _LIB_TO_PDD_FILES.get(lib_id, [])
        if not py_files:
            logger.info("Skipping %s (no PDD skeleton files)", lib_id)
            continue
        new_path = workspace_root / "l1_slices" / lib_id
        if not new_path.exists():
            logger.warning("L1 slice dir missing: %s", new_path)
            continue
        remapped.append(
            SliceRef(
                slice_id=ref.slice_id,
                layer=ref.layer,
                library_id=ref.library_id,
                worktree_path=str(new_path),
            )
        )
    return remapped


# ---------------------------------------------------------------------------
# Step-by-step runner
# ---------------------------------------------------------------------------


def run_single_step(
    step: Any,
    ctx: Any,
    bundle: Any,
    capture: StepCapture,
) -> Any:
    """Run one step of the promotion loop and capture results.

    Returns:
        The StepResult from the step.
    """
    t0 = time.monotonic()
    capture.gaps_before = len(bundle.gaps.open_gaps) if bundle.gaps else 0

    result = step.run(ctx, bundle)

    capture.duration_s = time.monotonic() - t0
    capture.status = result.status
    capture.error = result.error or ""
    capture.demotions = len(result.emitted_tickets) if result.emitted_tickets else 0
    capture.gaps_after = len(bundle.gaps.open_gaps) if bundle.gaps else 0

    # Capture plan details
    if hasattr(bundle, "plan") and bundle.plan:
        capture.intentions_count = len(bundle.plan.intentions)

    # Capture implementation details
    if hasattr(bundle, "implementation") and bundle.implementation:
        capture.edits_count = len(bundle.implementation.applied_edits)
        capture.under_spec_count = len(bundle.implementation.under_spec_events)

    # Capture gate results
    if hasattr(bundle, "gates") and bundle.gates:
        gates = bundle.gates.gates or []
        capture.gates_passed = sum(1 for g in gates if g.get("passed", True))
        capture.gates_failed = sum(1 for g in gates if not g.get("passed", True))

    return result


def run_slice_step_by_step(
    slice_ref: Any,
    run_context: Any,
    loop: Any,
    *,
    max_iterations: int = 20,
    save_dir: Path | None = None,
) -> SliceCapture:
    """Run a slice through the promotion loop step-by-step with capture.

    Instead of calling ``loop.run_slice()`` which runs all steps opaquely,
    this function runs each step individually to capture intermediate state.
    """
    from spec_manager.orchestration.evidence import EvidenceBundle
    from spec_manager.orchestration.promotion_loop import SliceContext

    capture = SliceCapture(
        slice_id=slice_ref.slice_id,
        layer=slice_ref.layer,
    )
    t0 = time.monotonic()

    ctx = SliceContext(
        slice_id=slice_ref.slice_id,
        slice_root=slice_ref.worktree_path,
        layer=slice_ref.layer,
        run_id=run_context.run_id,
        mode=run_context.mode,
        workspace_root=run_context.workspace_root,
        config=run_context.config,
    )

    for iteration in range(1, max_iterations + 1):
        logger.info(
            "=== Slice '%s' iter %d/%d ===",
            slice_ref.slice_id,
            iteration,
            max_iterations,
        )
        capture.iterations = iteration

        bundle = EvidenceBundle(
            run_id=run_context.run_id,
            slice_id=slice_ref.slice_id,
            iteration=iteration,
            mode=run_context.mode,
            workspace_root=run_context.workspace_root,
            slice_root=slice_ref.worktree_path,
        )

        retry = False

        for step in loop._steps:
            step_capture = StepCapture(
                step_name=step.name,
                slice_id=slice_ref.slice_id,
                layer=slice_ref.layer,
                iteration=iteration,
            )

            logger.info("  Step: %s", step.name)
            result = run_single_step(step, ctx, bundle, step_capture)

            # Save bundle state after each step
            if save_dir:
                step_dir = save_dir / slice_ref.slice_id / f"iter_{iteration:03d}" / step.name
                step_dir.mkdir(parents=True, exist_ok=True)
                _save_bundle_snapshot(bundle, step_dir)
                (step_dir / "step_capture.json").write_text(
                    json.dumps(step_capture.to_dict(), indent=2, default=str),
                    encoding="utf-8",
                )

            capture.steps.append(step_capture)

            if result.status in ("BLOCKED", "FAIL"):
                capture.final_status = result.status
                capture.total_duration_s = time.monotonic() - t0
                return capture

            if result.status == "RETRY":
                retry = True
                break

        if not retry:
            # All steps passed — check for remaining gaps
            open_gaps = len(bundle.gaps.open_gaps) if bundle.gaps else 0
            if open_gaps == 0:
                capture.final_status = "COMPLETE"
                break
            logger.info(
                "  Slice '%s' iter %d: %d gaps remain, continuing",
                slice_ref.slice_id,
                iteration,
                open_gaps,
            )

    if not capture.final_status:
        capture.final_status = "MAX_ITERATIONS"

    capture.total_duration_s = time.monotonic() - t0
    return capture


def _save_bundle_snapshot(bundle: Any, save_dir: Path) -> None:
    """Save a snapshot of the evidence bundle to disk."""
    # Gaps
    if bundle.gaps and bundle.gaps.open_gaps:
        (save_dir / "gaps.json").write_text(
            json.dumps(bundle.gaps.open_gaps, indent=2, default=str),
            encoding="utf-8",
        )

    # Plan
    if bundle.plan and bundle.plan.intentions:
        (save_dir / "plan.json").write_text(
            json.dumps(bundle.plan.intentions, indent=2, default=str),
            encoding="utf-8",
        )

    # Implementation
    if bundle.implementation:
        impl_data = {
            "applied_edits": bundle.implementation.applied_edits,
            "under_spec_events": bundle.implementation.under_spec_events,
            "pin_proposals": bundle.implementation.pin_proposals,
            "edge_proposals": bundle.implementation.edge_proposals,
        }
        (save_dir / "implementation.json").write_text(
            json.dumps(impl_data, indent=2, default=str),
            encoding="utf-8",
        )

    # Gates
    if bundle.gates and bundle.gates.gates:
        (save_dir / "gates.json").write_text(
            json.dumps(bundle.gates.gates, indent=2, default=str),
            encoding="utf-8",
        )

    # Source index
    if bundle.source_index and bundle.source_index.entries:
        (save_dir / "source_index.json").write_text(
            json.dumps(bundle.source_index.entries, indent=2, default=str),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Ground truth comparison
# ---------------------------------------------------------------------------


def compare_requirements_coverage(
    workspace_root: Path, ground_truth: GroundTruth
) -> dict[str, Any]:
    """Compare implemented code against ground truth requirements.

    Reads all Python files from spec_snapshot/ and checks which of the 52
    requirements appear to be implemented (based on spec comments remaining
    as ``pass`` stubs or having real implementations).

    Returns:
        Comparison report dict.
    """
    spec_dir = workspace_root / "spec_snapshot"
    if not spec_dir.exists():
        return {"error": "spec_snapshot not found"}

    implemented_funcs = 0
    stub_funcs = 0
    total_funcs = 0

    for py_file in sorted(spec_dir.rglob("*.py")):
        if not py_file.is_file():
            continue
        content = py_file.read_text(encoding="utf-8")
        lines = content.split("\n")

        in_function = False
        func_has_body = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("def "):
                if in_function:
                    total_funcs += 1
                    if func_has_body:
                        implemented_funcs += 1
                    else:
                        stub_funcs += 1
                in_function = True
                func_has_body = False
            elif in_function and stripped and stripped != "pass" and not stripped.startswith("#"):
                if not stripped.startswith('"""') and not stripped.startswith("'''"):
                    func_has_body = True

        # Handle last function
        if in_function:
            total_funcs += 1
            if func_has_body:
                implemented_funcs += 1
            else:
                stub_funcs += 1

    # Check requirement preservation in code
    requirements_found = 0
    all_code = ""
    for py_file in sorted(spec_dir.rglob("*.py")):
        if py_file.is_file():
            all_code += py_file.read_text(encoding="utf-8") + "\n"

    for req in ground_truth.requirements:
        # Check if key phrases from the requirement appear in code
        # (either as comments or as implementation)
        key_phrases = _extract_key_phrases(req)
        if any(phrase.lower() in all_code.lower() for phrase in key_phrases):
            requirements_found += 1

    return {
        "total_functions": total_funcs,
        "implemented_functions": implemented_funcs,
        "stub_functions": stub_funcs,
        "implementation_rate": implemented_funcs / total_funcs if total_funcs else 0,
        "total_requirements": ground_truth.total_requirements,
        "requirements_found": requirements_found,
        "requirements_coverage": (
            requirements_found / ground_truth.total_requirements
            if ground_truth.total_requirements
            else 0
        ),
    }


def _extract_key_phrases(requirement: str) -> list[str]:
    """Extract key identifying phrases from a requirement string."""
    phrases = []
    # Use numbers and specific terms as key identifiers
    import re

    # Dollar amounts
    for m in re.finditer(r"\$[\d,]+[MKB]?", requirement):
        phrases.append(m.group())

    # Percentages
    for m in re.finditer(r"\d+(?:\.\d+)?%", requirement):
        phrases.append(m.group())

    # Time durations
    for m in re.finditer(
        r"\d+\s*(?:minutes?|hours?|seconds?|days?|years?|ms)", requirement, re.IGNORECASE
    ):
        phrases.append(m.group())

    # Key technical terms (3+ word sequences)
    words = requirement.split()
    if len(words) >= 3:
        phrases.append(" ".join(words[:3]))
        if len(words) >= 5:
            phrases.append(" ".join(words[2:5]))

    return phrases if phrases else [requirement[:40]]


# ---------------------------------------------------------------------------
# Main eval orchestrator
# ---------------------------------------------------------------------------


class E2EEval:
    """End-to-end evaluation orchestrator.

    Sets up workspace, runs the pipeline step-by-step, and scores results.
    """

    def __init__(
        self,
        *,
        run_id: str | None = None,
        layer: str | None = None,
        slice_id: str | None = None,
        setup_only: bool = False,
        resume_run_id: str | None = None,
    ) -> None:
        self.run_id = run_id or f"e2e-eval-{uuid.uuid4().hex[:8]}"
        self.target_layer = layer
        self.target_slice = slice_id
        self.setup_only = setup_only
        self.resume_run_id = resume_run_id
        self._ground_truth: GroundTruth | None = None
        self._capture: EvalCapture | None = None

    @property
    def ground_truth(self) -> GroundTruth:
        if self._ground_truth is None:
            self._ground_truth = GroundTruth.load(_resolve(_GROUND_TRUTH_REL))
        return self._ground_truth

    @property
    def output_dir(self) -> Path:
        from spec_manager.core.project_root import resolve_from_root

        return resolve_from_root("runs", "evals", "e2e", self.run_id)

    def run(self) -> EvalCapture:
        """Run the full end-to-end evaluation."""
        self._capture = EvalCapture(run_id=self.run_id, started_at=time.time())

        # Setup workspace
        logger.info("=== E2E Eval: Setting up workspace ===")
        manager, workspace_root = setup_workspace(self.run_id, force=True)

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Save setup info
        setup_info = {
            "run_id": self.run_id,
            "workspace_root": str(workspace_root),
            "pdd_skeletons": str(_resolve(_PDD_SKELETONS_REL)),
            "phase0_output": str(_resolve(_PHASE0_OUTPUT_REL)),
            "ground_truth_path": str(_resolve(_GROUND_TRUTH_REL)),
            "target_layer": self.target_layer,
            "setup_time": time.time(),
        }
        (self.output_dir / "setup.json").write_text(
            json.dumps(setup_info, indent=2), encoding="utf-8"
        )

        if self.setup_only:
            logger.info("=== Setup-only mode: workspace ready at %s ===", workspace_root)
            return self._capture

        # Build planner and promotion loop
        from spec_manager.orchestration.pdd_lifecycle import PddLifecycle

        lifecycle = PddLifecycle(manager, mode="auto")
        planner = lifecycle._build_planner()

        from spec_manager.orchestration.promotion_loop import (
            PromotionLoop,
            RunContext,
        )

        loop = PromotionLoop(
            workspace_root=workspace_root,
            planner=planner,
        )
        run_context = RunContext(
            run_id=self.run_id,
            mode="auto",
            workspace_root=str(workspace_root),
        )

        # Run layers
        layers_to_run = ["l1", "l2", "l3"]
        if self.target_layer:
            layers_to_run = [self.target_layer]

        for layer_name in layers_to_run:
            layer_capture = self._run_layer(
                layer_name, manager, lifecycle, loop, run_context, workspace_root
            )
            self._capture.layers.append(layer_capture)

            # Save layer results
            layer_path = self.output_dir / f"layer_{layer_name}.json"
            layer_path.write_text(
                json.dumps(layer_capture.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )

        # Final ground truth comparison
        logger.info("=== E2E Eval: Final ground truth comparison ===")
        self._capture.ground_truth_comparison = compare_requirements_coverage(
            workspace_root, self.ground_truth
        )

        # Final scoring
        self._capture.final_scoring = self._compute_final_score()
        self._capture.completed_at = time.time()

        # Save full capture
        (self.output_dir / "eval_capture.json").write_text(
            json.dumps(self._capture.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )

        # Print summary
        self._print_summary()

        return self._capture

    def _run_layer(
        self,
        layer: str,
        manager: Any,
        lifecycle: Any,
        loop: Any,
        run_context: Any,
        workspace_root: Path,
    ) -> LayerCapture:
        """Run a single layer with step-by-step capture."""

        layer_capture = LayerCapture(layer=layer)
        t0 = time.monotonic()

        logger.info("=== Layer %s: START ===", layer.upper())

        # Entry refinement
        logger.info("  Entry refinement for %s", layer)
        try:
            refinement_method = getattr(
                lifecycle,
                {
                    "l1": "_library_refinement",
                    "l2": "_architectural_refinement",
                    "l3": "_code_quality_refinement",
                }[layer],
            )
            layer_capture.entry_refinement = refinement_method()
        except Exception as exc:
            logger.warning("  Entry refinement failed: %s", exc)
            layer_capture.entry_refinement = {"error": str(exc)}

        # Discover slices
        slice_refs = lifecycle._discover_slices(layer)
        logger.info("  Discovered %d slices for %s", len(slice_refs), layer)

        # For L1: remap worktree paths from libraries/ → l1_slices/ (Python files)
        if layer == "l1":
            slice_refs = _remap_l1_slices(slice_refs, workspace_root)
            logger.info("  Remapped to %d L1 slices with Python files", len(slice_refs))

        save_dir = self.output_dir / f"steps_{layer}"

        # Filter to target slice if requested
        if self.target_slice:
            slice_refs = [r for r in slice_refs if r.slice_id == self.target_slice]
            if not slice_refs:
                logger.warning("  Slice '%s' not found in %s", self.target_slice, layer)

        # Run each slice
        for slice_ref in slice_refs:
            logger.info("  === Slice '%s' ===", slice_ref.slice_id)
            slice_capture = run_slice_step_by_step(
                slice_ref,
                run_context,
                loop,
                max_iterations=20 if layer == "l1" else 15,
                save_dir=save_dir,
            )
            layer_capture.slices.append(slice_capture)

            # Save slice summary
            slice_path = save_dir / slice_ref.slice_id / "summary.json"
            slice_path.parent.mkdir(parents=True, exist_ok=True)
            slice_path.write_text(
                json.dumps(slice_capture.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )

        # Exit refinement
        logger.info("  Exit refinement for %s", layer)
        try:
            layer_capture.exit_refinement = refinement_method()
        except Exception as exc:
            logger.warning("  Exit refinement failed: %s", exc)
            layer_capture.exit_refinement = {"error": str(exc)}

        layer_capture.total_duration_s = time.monotonic() - t0
        logger.info(
            "=== Layer %s: DONE (%.1fs) ===",
            layer.upper(),
            layer_capture.total_duration_s,
        )

        return layer_capture

    def _compute_final_score(self) -> dict[str, Any]:
        """Compute final scoring from all captured data."""
        if not self._capture:
            return {}

        gt = self._capture.ground_truth_comparison

        total_steps = 0
        ok_steps = 0
        retry_steps = 0
        failed_steps = 0
        total_llm_steps = 0
        total_duration = 0.0

        for layer in self._capture.layers:
            for sl in layer.slices:
                for step in sl.steps:
                    total_steps += 1
                    total_duration += step.duration_s
                    if step.status == "OK":
                        ok_steps += 1
                    elif step.status == "RETRY":
                        retry_steps += 1
                    else:
                        failed_steps += 1
                    if step.step_name in (
                        "PLAN",
                        "IMPLEMENT",
                        "UNDER_SPEC_CHECK",
                        "GAP_EXPLORATION",
                        "PROMOTE",
                        "VERIFY",
                        "ALIGN",
                    ):
                        total_llm_steps += 1

        completed_slices = sum(
            1
            for layer in self._capture.layers
            for sl in layer.slices
            if sl.final_status == "COMPLETE"
        )
        total_slices = sum(len(layer.slices) for layer in self._capture.layers)

        return {
            "total_steps": total_steps,
            "ok_steps": ok_steps,
            "retry_steps": retry_steps,
            "failed_steps": failed_steps,
            "step_success_rate": ok_steps / total_steps if total_steps else 0,
            "total_llm_steps": total_llm_steps,
            "total_duration_s": total_duration,
            "completed_slices": completed_slices,
            "total_slices": total_slices,
            "slice_completion_rate": completed_slices / total_slices if total_slices else 0,
            "requirements_coverage": gt.get("requirements_coverage", 0),
            "implementation_rate": gt.get("implementation_rate", 0),
            "functions_implemented": gt.get("implemented_functions", 0),
            "functions_total": gt.get("total_functions", 0),
        }

    def _print_summary(self) -> None:
        """Print human-readable summary to stdout."""
        if not self._capture:
            return

        score = self._capture.final_scoring
        gt = self._capture.ground_truth_comparison

        print("\n" + "=" * 70)
        print(f"  E2E EVAL SUMMARY — {self.run_id}")
        print("=" * 70)

        for layer in self._capture.layers:
            completed = sum(1 for s in layer.slices if s.final_status == "COMPLETE")
            total = len(layer.slices)
            print(
                f"\n  {layer.layer.upper()}: {completed}/{total} slices complete "
                f"({layer.total_duration_s:.1f}s)"
            )
            for sl in layer.slices:
                step_count = len(sl.steps)
                print(
                    f"    {sl.slice_id}: {sl.final_status} "
                    f"({sl.iterations} iters, {step_count} steps, "
                    f"{sl.total_duration_s:.1f}s)"
                )

        req_found = gt.get("requirements_found", "?")
        req_total = gt.get("total_requirements", "?")
        func_impl = gt.get("implemented_functions", "?")
        func_total = gt.get("total_functions", "?")
        print(f"\n  Requirements coverage: {req_found}/{req_total}")
        print(f"  Functions implemented: {func_impl}/{func_total}")
        print(f"  Step success rate: {score.get('step_success_rate', 0):.1%}")
        print(f"  Slice completion rate: {score.get('slice_completion_rate', 0):.1%}")
        print(f"  Total duration: {score.get('total_duration_s', 0):.1f}s")
        print(f"\n  Full results: {self.output_dir}")
        print("=" * 70)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    """CLI entrypoint for e2e eval."""
    import argparse

    parser = argparse.ArgumentParser(description="End-to-end QA evaluation for PDD pipeline")
    parser.add_argument(
        "--run-id",
        help="Custom run ID (default: auto-generated)",
    )
    parser.add_argument(
        "--layer",
        choices=["l1", "l2", "l3"],
        help="Run only a specific layer",
    )
    parser.add_argument(
        "--slice",
        help="Run only a specific slice (e.g. LIB-02)",
    )
    parser.add_argument(
        "--setup-only",
        action="store_true",
        help="Only setup workspace, no LLM calls",
    )
    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        help="Resume from a previous run",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    evaluator = E2EEval(
        run_id=args.run_id,
        layer=args.layer,
        slice_id=args.slice,
        setup_only=args.setup_only,
        resume_run_id=args.resume,
    )

    capture = evaluator.run()

    if args.setup_only:
        return 0

    # Return 0 if slice completion rate > 50%, else 1
    score = capture.final_scoring
    if score.get("slice_completion_rate", 0) >= 0.5:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
