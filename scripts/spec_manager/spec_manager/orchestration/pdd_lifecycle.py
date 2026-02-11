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

    from spec_manager.orchestration.vcs import GitVcs
    from spec_manager.orchestration.worktree_manager import WorktreeManager

    vcs = GitVcs(repo_root=Path("."))
    wm = WorktreeManager(vcs=vcs, workspace_root=Path("."), run_id="my-run")
    lifecycle = PddLifecycle(manager, worktree_manager=wm)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.orchestration.models import Layer
from spec_manager.orchestration.pdd_orchestrator import PddOrchestrator
from spec_manager.refinement.workspace.manager import WorkspaceManager

if TYPE_CHECKING:
    from spec_manager.orchestration.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Run the full layer pipeline: intake → L1 → L2 → L3 → QA.

        Returns:
            Summary dict with results from each layer and transition.
        """
        results: dict[str, Any] = {}

        # Phase 0: Intake (raw prose → code-as-spec, if needed)
        results["intake"] = self._run_intake()

        # Setup layer worktrees if managed
        if self.worktree_manager:
            results["setup"] = self.worktree_manager.setup_layers()

        # L1: Code-as-Spec (with human approval loop)
        l1_result, approval = self._run_l1_with_approval()
        results["l1"] = l1_result
        results["approval"] = approval

        # L1→L2 transition: architectural refinement (may demote to L1)
        results["l1_l2_transition"] = self._run_transition("l1", "l2")

        # L2: Architecture
        results["l2"] = self._run_layer("l2")

        # L2→L3 transition: code quality refinement (may demote to L2)
        results["l2_l3_transition"] = self._run_transition("l2", "l3")

        # L3: Clean Code
        results["l3"] = self._run_layer("l3")

        # Final QA eval
        results["qa"] = self.qa()

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

    def _run_transition(self, from_layer: Layer, to_layer: Layer) -> dict[str, Any]:
        """Run transition between layers.

        The next layer's typed refinement runs as a transition gate.
        If it emits demotion tickets, the previous layer's slices are
        re-run to address the demoted issues.  After rework, clean is
        propagated to the next layer's dirty.

        Args:
            from_layer: Layer that just completed.
            to_layer: Layer about to start.

        Returns:
            Transition results including refinement and optional rework.
        """
        logger.info("=== Transition %s → %s ===", from_layer.upper(), to_layer.upper())
        results: dict[str, Any] = {"from": from_layer, "to": to_layer}

        refinement_method = getattr(self, _LAYER_REFINEMENT[to_layer])
        refinement_result = refinement_method()
        results["refinement"] = refinement_result

        # Handle demotion: re-run previous layer's slices
        demotions = refinement_result.get("demotion_tickets", 0)
        if demotions > 0:
            logger.info(
                "Transition %s→%s: %d demotions, re-running %s slices",
                from_layer,
                to_layer,
                demotions,
                from_layer,
            )
            results["rework"] = self._run_slices_at_layer(from_layer)

        # Propagate clean → next layer's dirty
        if self.worktree_manager:
            prop = self.worktree_manager.propagate_clean_to_next_layer(from_layer)
            results["propagation"] = {
                "success": prop.success,
                "from_layer": prop.from_layer,
                "to_layer": prop.to_layer,
                "error": prop.error,
            }

        return results

    def _run_slices_at_layer(self, layer: Layer) -> dict[str, Any]:
        """Discover slices and run PromotionLoop at a given layer.

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
            PromotionScheduler,
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
            max_iterations=20,
        )

        loop = PromotionLoop(
            worktree_manager=self.worktree_manager,
            workspace_root=self.manager.workspace_path,
        )

        scheduler = PromotionScheduler(
            loop=loop,
            config=SchedulerConfig(max_parallel=4),
        )
        sched_result = scheduler.run(slice_refs, run_context)
        slice_results = sched_result.slice_results

        return {
            "layer": layer,
            "slices": [
                {
                    "slice_id": r.slice_id,
                    "status": r.status,
                    "iterations": r.iterations,
                    "remaining_gaps": r.remaining_gaps,
                    "demotion_count": len(r.demotion_tickets),
                }
                for r in slice_results
            ],
            "all_complete": all(r.status == "COMPLETE" for r in slice_results),
        }

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
        from spec_manager.orchestration.promotion_loop import SliceRef

        slice_refs: list[SliceRef] = []

        if layer == "l1":
            libraries_dir = self.manager.structure.libraries_dir
            if libraries_dir.exists():
                for lib_dir in sorted(libraries_dir.iterdir()):
                    if lib_dir.is_dir():
                        slice_refs.append(
                            SliceRef(
                                slice_id=lib_dir.name,
                                layer=layer,
                                library_id=lib_dir.name,
                                worktree_path=str(lib_dir),
                            )
                        )

        elif layer == "l2":
            # Try component manifest first (produced by architectural refinement)
            manifest_path = self.manager.structure.root / "reports" / "component_manifest.json"
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
                for py_file in sorted(spec_snapshot_dir.rglob("*.py")):
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

    def _request_approval(self, result: dict[str, Any], iteration: int) -> dict[str, Any]:
        """Request human approval of the L1 output.

        Args:
            result: Results from the L1 layer.
            iteration: Current iteration number.

        Returns:
            Approval dict with ``approved`` bool and optional
            ``feedback`` string.
        """
        if self.mode in ("auto", "steering"):
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
            return {"approved": True, "iteration": iteration, "mode": "interactive"}

        if choice == "q":
            raise KeyboardInterrupt("User aborted lifecycle")

        # Feedback mode
        try:
            feedback = input("Feedback: ").strip()
        except (EOFError, KeyboardInterrupt):
            feedback = ""

        # Write feedback to reports directory
        reports_dir = self.manager.structure.root / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        feedback_path = reports_dir / f"feedback_iteration_{iteration}.txt"
        feedback_path.write_text(feedback, encoding="utf-8")

        return {
            "approved": False,
            "iteration": iteration,
            "feedback": feedback,
            "feedback_path": str(feedback_path),
            "mode": "interactive",
        }

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

        code_files = self._gather_all_code()

        if not code_files:
            return {"note": "No code found in spec_snapshot — skipping architectural refinement."}

        lib_summaries: list[str] = []
        for rel_path, content in code_files.items():
            lib_summaries.append(f"## {rel_path}\n\n```python\n{content[:2000]}\n```")

        prompt = (
            "## TASK\n\n"
            "Given the following code, propose 3-5 architecture candidates.\n"
            "For each candidate, describe: components, communication patterns,\n"
            "deployment model, and tradeoffs.\n\n"
            "Also identify architectural issues in the current code that need fixing.\n"
            "For each issue, include: severity (BLOCKER/MAJOR/MINOR), file, description.\n\n"
            "Return JSON with keys:\n"
            "- 'candidates': array of architecture proposals\n"
            "- 'issues': array of architectural issues found\n\n"
            + "\n\n---\n\n".join(lib_summaries)
        )

        try:
            output = run_agent(
                agent_name="opus-architecture-proposer",
                prompt=prompt,
                workspace=self.manager.workspace_path,
            )
            cleaned = _strip_code_fences(output)
            data = json.loads(_extract_json_payload(cleaned))
            candidates = data.get("candidates", [])
            issues = data.get("issues", [])

            # Write proposals to disk
            reports_dir = self.manager.structure.root / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            (reports_dir / "architecture_proposals.json").write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )

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
                tickets_path = reports_dir / "architecture_demotion_tickets.json"
                tickets_path.write_text(json.dumps(tickets, indent=2), encoding="utf-8")

            return {
                "candidates_proposed": len(candidates),
                "proposals_path": "reports/architecture_proposals.json",
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

        all_specs = self._gather_all_code()

        if not all_specs:
            return {"note": "No code found in spec_snapshot — skipping code quality refinement."}

        reviewers = [
            "chatgpt-clarity-reviewer",
            "chatgpt-completeness-reviewer",
            "chatgpt-consistency-reviewer",
            "chatgpt-correctness-reviewer",
        ]

        all_findings: list[dict[str, Any]] = []

        for file_path, code_content in all_specs.items():
            prompt = (
                f"## TASK\n\n"
                f"Review the following code for quality issues.\n"
                f"For each finding include: severity (BLOCKER/MAJOR/MINOR),\n"
                f"category (logic/architecture/style), and description.\n"
                f"Return JSON with key 'findings' containing an array of issues.\n\n"
                f"File: {file_path}\n\n"
                f"```python\n{code_content[:4000]}\n```\n"
            )

            for reviewer in reviewers:
                try:
                    output = run_agent(
                        agent_name=reviewer,
                        prompt=prompt,
                        workspace=self.manager.workspace_path,
                    )
                    cleaned = _strip_code_fences(output)
                    data = json.loads(_extract_json_payload(cleaned))
                    findings = data.get("findings", [])
                    for finding in findings:
                        finding["file"] = file_path
                        finding["reviewer"] = reviewer
                    all_findings.extend(findings)
                except Exception as exc:
                    logger.warning("Reviewer %s failed for %s: %s", reviewer, file_path, exc)

        # Write quality report
        reports_dir = self.manager.structure.root / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "code_quality_report.json").write_text(
            json.dumps({"findings": all_findings}, indent=2), encoding="utf-8"
        )

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
            tickets_path = reports_dir / "code_quality_demotion_tickets.json"
            tickets_path.write_text(json.dumps(tickets, indent=2), encoding="utf-8")

        return {
            "files_reviewed": len(all_specs),
            "total_findings": len(all_findings),
            "report_path": "reports/code_quality_report.json",
            "demotion_tickets": len(tickets),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
        code_files: dict[str, str] = {}
        spec_snapshot_dir = self.manager.structure.spec_snapshot_dir
        if spec_snapshot_dir.exists():
            for py_file in sorted(spec_snapshot_dir.rglob("*.py")):
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

        Calls the ``opus-alignment-checker`` agent per library to detect
        drift and reward hacking.
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
        reports_dir = self.manager.structure.root / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report = {
            "libraries_checked": libraries_checked,
            "drift_findings": total_drift,
            "reward_hacking_findings": total_reward_hacking,
            "errors": errors,
        }
        (reports_dir / "alignment_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )

        return report

    def _generate_overview(self) -> dict[str, Any]:
        """Generate a human-readable overview document for review.

        Calls the ``opus-overview-writer`` agent per library and
        consolidates into a single ``overview.md``.
        """
        from spec_manager.core.agent_utils import run_agent

        libraries_dir = self.manager.structure.libraries_dir
        if not libraries_dir.exists():
            return {"note": "No libraries directory — skipping overview generation."}

        overview_parts: list[str] = []
        libraries_processed = 0
        errors: list[dict[str, Any]] = []

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
                )
                overview_parts.append(f"## {lib_id}\n\n{output.strip()}\n")
                libraries_processed += 1
            except Exception as exc:
                errors.append({"lib_id": lib_id, "error": str(exc)})

        # Write consolidated overview
        reports_dir = self.manager.structure.root / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        overview_content = "# Project Overview\n\n" + "\n---\n\n".join(overview_parts)
        overview_path = reports_dir / "overview.md"
        overview_path.write_text(overview_content, encoding="utf-8")

        return {
            "libraries_processed": libraries_processed,
            "overview_path": str(overview_path),
            "errors": errors,
        }
