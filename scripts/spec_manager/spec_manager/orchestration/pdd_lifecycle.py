"""PDD lifecycle orchestrator: Build → QA → Architecture → Code Quality.

This is the higher-level lifecycle loop from ``simpler.md``.  It wraps
:class:`PddOrchestrator` (phases 0-10) with the 4-phase PDD lifecycle.

The lifecycle iterates: run the internal pipeline, detect ambiguities,
resolve them (interactively or via auto-research), check alignment, and
generate a review document for human approval.

Usage::

    manager = WorkspaceManager(run_id="my-run", input_folder=Path("specs"))
    manager.initialize()
    lifecycle = PddLifecycle(manager, mode="interactive")

    # Full lifecycle
    result = lifecycle.run()

    # Or individual phases
    build_result = lifecycle.build()
    qa_result = lifecycle.qa()

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

from spec_manager.orchestration.pdd_orchestrator import PddOrchestrator
from spec_manager.refinement.workspace.manager import WorkspaceManager

if TYPE_CHECKING:
    from spec_manager.orchestration.worktree_manager import WorktreeManager

logger = logging.getLogger(__name__)


class PddLifecycle:
    """Orchestrates the 4-phase PDD lifecycle from simpler.md.

    This is the ONLY top-level lifecycle controller.
    :class:`PddOrchestrator` handles the internal 11-phase pipeline.
    This class handles the outer loop: iterate, resolve ambiguities,
    align, review, and iterate again.

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
        max_approval_iterations: Max build→review→patch loops before
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
        """Run the complete PDD lifecycle.

        Includes the human approval loop between Build and QA per
        ``simpler.md``: build → overview → human review → approve or
        patch → repeat.

        Returns:
            Summary dict with results from each lifecycle phase.
        """
        # TODO: Restructure as per-slice iterative promotion loop.
        #   Currently sequential: Build → QA → Architecture → Code Quality.
        #   Should be:
        #     1. Run Promotion 1 (P0 intake, optional — skip if input is PDD)
        #     2. Create worktrees per library
        #     3. FOR EACH SLICE (parallel across library worktrees):
        #        a. P3 gap exploration (find remaining TODO comments)
        #        b. P8 planning (what to implement, how to integrate)
        #        c. P9 implementation (write code + small tests)
        #        d. Under-specification check → constraints → block or decide
        #        e. P1/P2 analyze (parse, reverse-translate)
        #        f. P4/P5 promote (extract atoms, pin, compliance gates)
        #        g. Refinement engine (coupling/cohesion)
        #        h. CI on clean worktree (extract slice → test → rebase)
        #        i. P6/P7 verify (cross-library, lineage)
        #        j. POWER alignment (periodic)
        #        k. If gates fail → fix → retry from (a)
        #     4. Termination: all TODO comments resolved, all atoms promoted,
        #        all gates pass, clean worktree tests pass
        #     5. Quality reviewers → demotion if logic issues → re-promote
        #     6. Merge to main
        results: dict[str, Any] = {}

        # Build with approval loop
        build_result, approval_result = self.build_with_approval()
        results["build"] = build_result
        results["approval"] = approval_result

        results["qa"] = self.qa()
        results["architecture"] = self.architecture()
        results["code_quality"] = self.code_quality()

        # Cleanup worktrees if managed
        if self.worktree_manager:
            results["cleanup"] = self.worktree_manager.cleanup()

        return results

    # ------------------------------------------------------------------
    # Lifecycle Phase 1: Build
    # ------------------------------------------------------------------

    def build(self) -> dict[str, Any]:
        """Lifecycle Phase 1: Build.

        Steps:
        1. Run internal PDD pipeline (phases 0-10).
        2. Refine each library spec for ambiguities.
        3. POWER alignment check.
        4. Generate overview document for human review.

        Returns:
            Build phase results.
        """
        logger.info("=== PDD Lifecycle: BUILD ===")
        outputs: dict[str, Any] = {}

        # TODO: Restructure build to separate Promotion 1 from Promotion 2.
        #   Step 1 should ONLY run P0 (intake) if input is raw prose.
        #   Then create worktrees BEFORE the iterative loop.
        #   Then the iterative per-slice loop replaces steps 1-5.
        #   Current flow runs all 11 phases as a single sequential pass,
        #   creates worktrees last (too late), and batches refinement.

        # 1. Run the internal 11-phase pipeline
        # TODO: Replace with: run P0 once (if needed), then iterative
        #   per-slice loop for P3→P8→P9→P4→P5 with CI integration.
        pipeline_result = self.orchestrator.run()
        outputs["pipeline"] = pipeline_result

        # 2. Refine library specs (ambiguity detection + resolution)
        # TODO: Remove batch refinement. Ambiguity resolution should
        #   happen INLINE during implementation when under-specification
        #   is hit. The planning agent checks constraints, blocks if
        #   insufficient, and sources from human or research team.
        refinement_result = self._refine_libraries()
        outputs["refinement"] = refinement_result

        # 3. POWER alignment check
        alignment_result = self._check_alignment()
        outputs["alignment"] = alignment_result

        # 4. Generate overview for human review
        overview_result = self._generate_overview()
        outputs["overview"] = overview_result

        # 5. Create per-library worktrees for parallel implementation
        # TODO: Move worktree creation to BEFORE the iterative loop.
        #   Worktrees are where implementation happens — they must
        #   exist before P9 writes code. Currently created after
        #   all phases complete, which is too late.
        if self.worktree_manager:
            worktree_result = self._setup_library_worktrees()
            outputs["worktrees"] = worktree_result

        logger.info("=== BUILD complete ===")
        return outputs

    def build_with_approval(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Build phase with human approval loop.

        Per ``simpler.md`` steps 8-12: generate overview → human
        reviews → human references intent misalignment → return to
        build for patch → human approves.

        In ``"auto"`` and ``"steering"`` modes, approval is automatic.
        In ``"interactive"`` mode, the user is prompted for approval.

        Returns:
            Tuple of ``(build_result, approval_result)``.
        """
        iteration = 0
        build_result: dict[str, Any] = {}

        while iteration < self.max_approval_iterations:
            iteration += 1
            logger.info(
                "=== Build-Approval iteration %d/%d ===",
                iteration,
                self.max_approval_iterations,
            )

            build_result = self.build()

            approval = self._request_approval(build_result, iteration)

            if approval["approved"]:
                return build_result, approval

            # Not approved — feedback is recorded, loop back to build
            logger.info(
                "Build not approved (iteration %d): %s",
                iteration,
                approval.get("feedback", ""),
            )

        # Max iterations reached — auto-approve to prevent infinite loop
        logger.warning(
            "Max approval iterations (%d) reached — auto-approving",
            self.max_approval_iterations,
        )
        return build_result, {
            "approved": True,
            "iteration": iteration,
            "auto_approved": True,
            "reason": "max_iterations_reached",
        }

    def _request_approval(self, build_result: dict[str, Any], iteration: int) -> dict[str, Any]:
        """Request human approval of the build output.

        Args:
            build_result: Results from the build phase.
            iteration: Current iteration number.

        Returns:
            Approval dict with ``approved`` bool and optional
            ``feedback`` string.
        """
        if self.mode in ("auto", "steering"):
            return {"approved": True, "iteration": iteration, "mode": self.mode}

        # Interactive mode — prompt user
        overview_result = build_result.get("overview", {})
        overview_path = overview_result.get("overview_path", "")

        print("\n" + "=" * 60)
        print("PDD BUILD COMPLETE — Review Required")
        print("=" * 60)
        if overview_path:
            print(f"\nOverview document: {overview_path}")
        print("\nPlease review the overview and library specs.")
        print("Options:")
        print("  [a] Approve — proceed to QA phase")
        print("  [f] Feedback — provide feedback for next iteration")
        print("  [q] Quit — abort lifecycle")

        try:
            choice = input("\nYour choice [a/f/q]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "a"  # Default to approve on non-interactive terminals

        if choice == "a" or choice == "":
            return {"approved": True, "iteration": iteration, "mode": "interactive"}

        if choice == "q":
            raise KeyboardInterrupt("User aborted lifecycle")

        # Feedback mode
        try:
            feedback = input("Feedback: ").strip()
        except (EOFError, KeyboardInterrupt):
            feedback = ""

        # Write feedback to reports directory for the next build iteration
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
    # Lifecycle Phase 2: QA
    # ------------------------------------------------------------------

    def qa(self) -> dict[str, Any]:
        """Lifecycle Phase 2: QA.

        Steps:
        1. Run eval framework against the current state.
        2. Detect failures via LLM judge scorer.
        3. Report failures for root cause analysis.

        Returns:
            QA phase results.
        """
        # TODO: QA is a process at every promotion, not a separate phase.
        #   Should run as part of compliance gating within the per-slice
        #   loop: after P9 writes code, run tests + eval before promoting.
        #   Keep this method as a standalone check but wire it into the
        #   promotion loop as a gate.
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
    # Lifecycle Phase 3: Architecture
    # ------------------------------------------------------------------

    def architecture(self) -> dict[str, Any]:
        """Lifecycle Phase 3: Architecture.

        Steps:
        1. Propose architectures via ``opus-architecture-proposer``.
        2. Analyze tradeoffs.
        3. Choose best hybrid.
        4. Refactor.

        Returns:
            Architecture phase results.
        """
        # TODO: Architecture emerges from Promotion 2 (L1→L2), not
        #   from a separate proposal phase. Pin-function scan + atom
        #   promotion already create architectural structure. This
        #   method should validate what emerged, not propose from scratch.
        #   Move architectural validation into the promotion loop.
        logger.info("=== PDD Lifecycle: ARCHITECTURE ===")

        from spec_manager.core.agent_utils import run_agent
        from spec_manager.refinement.formats import _extract_json_payload, _strip_code_fences

        # Gather library summaries for architecture context
        libraries_dir = self.manager.structure.libraries_dir
        lib_summaries: list[str] = []
        if libraries_dir.exists():
            for lib_dir in sorted(libraries_dir.iterdir()):
                if not lib_dir.is_dir():
                    continue
                spec_path = lib_dir / "spec.md"
                if spec_path.exists():
                    content = spec_path.read_text(encoding="utf-8")
                    lib_summaries.append(f"## {lib_dir.name}\n\n{content[:2000]}")

        if not lib_summaries:
            return {"note": "No library specs found — skipping architecture phase."}

        # Propose architectures
        prompt = (
            "## TASK\n\n"
            "Given the following library specs, propose 3-5 architecture candidates.\n"
            "For each candidate, describe: components, communication patterns,\n"
            "deployment model, and tradeoffs.\n\n"
            "Return JSON with key 'candidates' containing an array of proposals.\n\n"
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

            # Write proposals to disk
            reports_dir = self.manager.structure.root / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            (reports_dir / "architecture_proposals.json").write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )

            return {
                "candidates_proposed": len(candidates),
                "proposals_path": "reports/architecture_proposals.json",
            }
        except Exception as exc:
            logger.warning("Architecture proposal failed: %s", exc)
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Lifecycle Phase 4: Code Quality
    # ------------------------------------------------------------------

    def code_quality(self) -> dict[str, Any]:
        """Lifecycle Phase 4: Code Quality.

        Steps:
        1. Run N quality reviewers (clarity, completeness, consistency, correctness).
        2. Collect findings.
        3. Report for refactoring.

        Returns:
            Code quality phase results.
        """
        # TODO: Code quality IS Promotion 3 (L2→L3). If quality
        #   reviewers find logic issues → trigger demotion all the way
        #   down to L1 (code-as-spec), fix there, re-promote through
        #   ALL gates. Currently just collects findings, no demotion.
        logger.info("=== PDD Lifecycle: CODE QUALITY ===")

        from spec_manager.core.agent_utils import run_agent
        from spec_manager.refinement.formats import _extract_json_payload, _strip_code_fences

        # Gather all library specs for review
        libraries_dir = self.manager.structure.libraries_dir
        all_specs: dict[str, str] = {}
        if libraries_dir.exists():
            for lib_dir in sorted(libraries_dir.iterdir()):
                if not lib_dir.is_dir():
                    continue
                spec_path = lib_dir / "spec.md"
                if spec_path.exists():
                    all_specs[lib_dir.name] = spec_path.read_text(encoding="utf-8")

        if not all_specs:
            return {"note": "No library specs found — skipping code quality phase."}

        reviewers = [
            "chatgpt-clarity-reviewer",
            "chatgpt-completeness-reviewer",
            "chatgpt-consistency-reviewer",
            "chatgpt-correctness-reviewer",
        ]

        all_findings: list[dict[str, Any]] = []

        for lib_id, spec_content in all_specs.items():
            prompt = (
                f"## TASK\n\n"
                f"Review the following spec for quality issues.\n"
                f"Return JSON with key 'findings' containing an array of issues.\n\n"
                f"Library: {lib_id}\n\n"
                f"Spec:\n{spec_content[:4000]}\n"
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
                        finding["lib_id"] = lib_id
                        finding["reviewer"] = reviewer
                    all_findings.extend(findings)
                except Exception as exc:
                    logger.warning("Reviewer %s failed for %s: %s", reviewer, lib_id, exc)

        # Write quality report
        reports_dir = self.manager.structure.root / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        (reports_dir / "code_quality_report.json").write_text(
            json.dumps({"findings": all_findings}, indent=2), encoding="utf-8"
        )

        return {
            "libraries_reviewed": len(all_specs),
            "total_findings": len(all_findings),
            "report_path": "reports/code_quality_report.json",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _setup_library_worktrees(self) -> dict[str, Any]:
        """Create worktrees for each discovered library.

        Sets up the worktree hierarchy (root + clean) and creates
        a grandchild worktree per library for parallel implementation.
        """
        if not self.worktree_manager:
            return {"note": "No worktree manager configured."}

        libraries_dir = self.manager.structure.libraries_dir
        if not libraries_dir.exists():
            return {"note": "No libraries directory — skipping worktree setup."}

        # Setup root and clean worktrees
        setup_result = self.worktree_manager.setup()

        # Create per-library worktrees
        created: list[str] = []
        errors: list[dict[str, str]] = []

        for lib_dir in sorted(libraries_dir.iterdir()):
            if not lib_dir.is_dir():
                continue
            lib_id = lib_dir.name
            try:
                self.worktree_manager.create_library_worktree(lib_id)
                created.append(lib_id)
            except RuntimeError as exc:
                errors.append({"lib_id": lib_id, "error": str(exc)})

        return {
            **setup_result,
            "libraries_created": len(created),
            "library_ids": created,
            "errors": errors,
        }

    def _refine_libraries(self) -> dict[str, Any]:
        """Run ambiguity detection + resolution on each library spec.

        Uses :class:`InteractiveWorkflow` in the configured mode.
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
            spec_path = lib_dir / "spec.md"
            if not spec_path.exists():
                results[lib_id] = {"skipped": "no spec.md"}
                continue

            original_spec = spec_path.read_text(encoding="utf-8")

            workflow = InteractiveWorkflow(
                workspace=workspace,
                interactive=(self.mode == "interactive"),
                steering_path=self.steering_path,
                use_research=self.use_research,
                use_evidence_store=self.use_evidence_store,
                max_iterations=self.max_refinement_iterations,
            )

            refined_spec = workflow.run(original_spec)
            changed = refined_spec != original_spec

            if changed:
                spec_path.write_text(refined_spec, encoding="utf-8")

            results[lib_id] = {
                "refined": changed,
                "original_length": len(original_spec),
                "refined_length": len(refined_spec),
            }

        return results

    def _check_alignment(self) -> dict[str, Any]:
        """Run POWER alignment check on all library specs.

        Calls the ``opus-alignment-checker`` agent per library to detect
        drift and reward hacking.  Applies corrective patches for high-
        severity findings.
        """
        from spec_manager.core.agent_utils import run_agent
        from spec_manager.refinement.formats import _extract_json_payload, _strip_code_fences

        libraries_dir = self.manager.structure.libraries_dir
        if not libraries_dir.exists():
            return {"note": "No libraries directory — skipping alignment check."}

        total_drift = 0
        total_reward_hacking = 0
        libraries_checked = 0
        errors: list[dict[str, Any]] = []

        for lib_dir in sorted(libraries_dir.iterdir()):
            if not lib_dir.is_dir():
                continue
            lib_id = lib_dir.name
            spec_path = lib_dir / "spec.md"
            charter_path = lib_dir / "charter.md"

            if not spec_path.exists():
                continue

            spec_content = spec_path.read_text(encoding="utf-8")
            charter_content = (
                charter_path.read_text(encoding="utf-8") if charter_path.exists() else ""
            )

            if not charter_content:
                # No charter to check against — skip alignment
                continue

            prompt = (
                "## TASK\n\n"
                "Check the library spec against the original charter.\n"
                "Detect requirement drift and reward hacking.\n"
                "Return JSON with keys: drift_findings, reward_hacking_findings.\n\n"
                f"Library ID: {lib_id}\n\n"
                f"Charter:\n{charter_content.strip()}\n\n"
                f"Current Spec:\n{spec_content.strip()}\n"
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
            spec_path = lib_dir / "spec.md"
            if not spec_path.exists():
                continue

            spec_content = spec_path.read_text(encoding="utf-8")
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
                f"Spec:\n{spec_content.strip()}\n"
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
