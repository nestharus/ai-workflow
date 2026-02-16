"""Worktree manager for multi-layer parallel promotion pipeline.

Implements the 6-worktree hierarchy from the refined promotion model:

- **L1 (Code-as-Spec)**: dirty + clean + grandchild slices
- **L2 (Architecture)**: dirty + clean
- **L3 (Clean Code)**: dirty + clean → main

Each layer has a dirty/clean worktree pair.  Creative work only happens
at the active layer.  CI (merge + test) runs at all layers in parallel.

Branch naming convention::

    pdd/<run_id>/l1/dirty
    pdd/<run_id>/l1/clean
    pdd/<run_id>/l1/candidate       (CI snapshot ref)
    pdd/<run_id>/l2/dirty
    pdd/<run_id>/l2/clean
    ...
    pdd/<run_id>/<layer>/slice/<slice_id>/<nonce>

"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Literal

from spec_manager.core.layer_types import (
    LAYER_ORDER,
    BatchResult,
    Lane,
    Layer,
    LayerStatus,
    MergeResult,
    PipelineTickResult,
    PropagateResult,
    next_layer,
    prev_layer,
)
from spec_manager.vcs.operations import VcsOperations

logger = logging.getLogger(__name__)


class WorktreeManager:
    """Manages worktrees for the multi-layer promotion pipeline.

    Args:
        vcs: VCS abstraction (e.g. :class:`GitVcs`).
        workspace_root: Root of the repository / workspace.
        run_id: Unique identifier for this PDD run.
        worktrees_base: Base directory for worktrees.
    """

    def __init__(
        self,
        vcs: VcsOperations,
        workspace_root: Path,
        run_id: str,
        *,
        worktrees_base: Path | None = None,
    ) -> None:
        self.vcs = vcs
        self.workspace_root = workspace_root
        self.run_id = run_id
        self.worktrees_base = worktrees_base or (workspace_root / ".worktrees")

        # Multi-layer state
        self._layer_worktrees: dict[Layer, dict[Lane, Path]] = {}
        self._layer_branches: dict[Layer, dict[Lane, str]] = {}
        self._batch_seq: dict[Layer, int] = {}
        self._slice_worktrees: dict[str, Path] = {}  # slice_id → Path
        self._base_ref: str = "HEAD"
        self._layers_initialized: bool = False

    # ------------------------------------------------------------------
    # Multi-layer setup
    # ------------------------------------------------------------------

    def setup_layers(
        self,
        base_ref: str | None = None,
        layers: list[Layer] | None = None,
        create_all: bool = True,
    ) -> dict[str, Any]:
        """Create dirty/clean worktree pairs for each layer.

        Args:
            base_ref: Branch/commit to start all worktrees from.
                Defaults to current branch HEAD.
            layers: Which layers to create.  Defaults to all three.
            create_all: If True, create all layers upfront.
                If False, only create the first layer.

        Returns:
            Dict describing created worktrees.
        """
        self.worktrees_base.mkdir(parents=True, exist_ok=True)
        self._base_ref = base_ref or self.vcs.get_current_branch() or "HEAD"

        target_layers = layers or list(LAYER_ORDER)
        if not create_all:
            target_layers = target_layers[:1]

        created: list[dict[str, str]] = []
        for layer in target_layers:
            created.extend(self._ensure_layer_worktrees(layer))

        self._layers_initialized = True
        return {"base_ref": self._base_ref, "worktrees": created}

    # ------------------------------------------------------------------
    # Layer accessors
    # ------------------------------------------------------------------

    def layer_branch(self, layer: Layer, lane: Lane) -> str:
        """Return the branch name for a layer/lane."""
        return f"pdd/{self.run_id}/{layer}/{lane}"

    def candidate_ref(self, layer: Layer) -> str:
        """Return the candidate ref name for a layer."""
        return f"pdd/{self.run_id}/{layer}/candidate"

    def upstream_accepted_ref(self, layer: Layer) -> str:
        """Return the upstream_accepted ref name for a layer."""
        return f"pdd/{self.run_id}/{layer}/upstream_accepted"

    def layer_worktree_path(self, layer: Layer, lane: Lane) -> Path:
        """Return the filesystem path for a layer/lane worktree."""
        return self.worktrees_base / f"{self.run_id}-{layer}-{lane}"

    def get_layer_worktree(self, layer: Layer, lane: Lane) -> Path | None:
        """Return the concrete worktree path for a layer/lane, if initialized."""
        return self._layer_worktrees.get(layer, {}).get(lane)

    def get_layer_heads(self, layer: Layer) -> dict[str, str | None]:
        """Return current SHAs for dirty, clean, and candidate at a layer."""
        dirty_path = self._layer_worktrees.get(layer, {}).get("dirty")
        clean_path = self._layer_worktrees.get(layer, {}).get("clean")

        dirty_sha = self.vcs.get_head_sha(dirty_path) if dirty_path else None
        clean_sha = self.vcs.get_head_sha(clean_path) if clean_path else None
        candidate_sha = self.vcs.rev_parse(self.candidate_ref(layer))

        return {
            "dirty_sha": dirty_sha,
            "clean_sha": clean_sha,
            "candidate_sha": candidate_sha,
        }

    def is_layer_clean(self, layer: Layer) -> bool:
        """Check if a layer's dirty == clean (all work promoted).

        A layer is fully clean when:
        - ``rev-parse dirty == rev-parse clean``
        - No in-flight candidate (or candidate == clean)
        """
        heads = self.get_layer_heads(layer)
        dirty = heads["dirty_sha"]
        clean = heads["clean_sha"]
        candidate = heads["candidate_sha"]

        if dirty is None or clean is None:
            return False
        if dirty != clean:
            return False
        return not (candidate is not None and candidate != clean)

    def get_layer_status(self, layer: Layer) -> LayerStatus:
        """Get a full status snapshot for a layer."""
        heads = self.get_layer_heads(layer)
        dirty = heads["dirty_sha"]
        clean = heads["clean_sha"]

        pending = 0
        if dirty and clean:
            count = self.vcs.rev_list_count(clean, dirty)
            if count is not None:
                pending = count

        upstream_sha = self.vcs.rev_parse(self.upstream_accepted_ref(layer))

        return LayerStatus(
            layer=layer,
            dirty_sha=dirty,
            clean_sha=clean,
            candidate_sha=heads["candidate_sha"],
            is_clean=self.is_layer_clean(layer),
            pending_commits=pending,
            upstream_accepted_sha=upstream_sha,
        )

    # ------------------------------------------------------------------
    # Grandchild / slice worktrees (active-layer work)
    # ------------------------------------------------------------------

    def create_slice_worktree(
        self,
        layer: Layer,
        slice_id: str,
    ) -> Path:
        """Create a grandchild worktree for a slice at a layer.

        Args:
            layer: Which layer this slice belongs to.
            slice_id: Unique slice identifier.

        Returns:
            Path to the slice worktree.
        """
        full_id = f"{layer}:{slice_id}"
        if full_id in self._slice_worktrees:
            raise RuntimeError(f"Slice worktree already exists for '{full_id}'")
        active_layer = self.compute_active_layer()
        if layer != active_layer:
            raise RuntimeError(
                f"Cannot create slice worktree for '{full_id}': active layer is '{active_layer}'"
            )

        nonce = uuid.uuid4().hex[:6]
        branch = f"pdd/{self.run_id}/{layer}/slice/{slice_id}/{nonce}"
        path = self.worktrees_base / f"{self.run_id}-{layer}-slice-{slice_id}"

        start = self.layer_branch(layer, "dirty")

        ok, err = self.vcs.create_worktree(path, branch, start_point=start)
        if not ok:
            raise RuntimeError(f"Failed to create slice worktree for '{full_id}': {err}")

        self._slice_worktrees[full_id] = path
        logger.info("Created slice worktree for '%s' at %s", full_id, path)
        return path

    def get_slice_worktree(self, layer: Layer, slice_id: str) -> Path | None:
        """Return the worktree path for a slice, or None."""
        return self._slice_worktrees.get(f"{layer}:{slice_id}")

    def merge_slice_to_dirty(
        self,
        layer: Layer,
        slice_id: str,
        strategy: Literal["merge", "rebase"] = "merge",
    ) -> MergeResult:
        """Merge a completed slice into the layer's dirty worktree.

        Args:
            layer: Target layer.
            slice_id: Slice to merge.
            strategy: Integration strategy (``merge`` or ``rebase``).

        Returns:
            MergeResult with success/failure details.
        """
        full_id = f"{layer}:{slice_id}"
        if full_id not in self._slice_worktrees:
            return MergeResult(
                success=False,
                slice_id=slice_id,
                layer=layer,
                error=f"No slice worktree for '{full_id}'",
            )

        dirty_path = self._layer_worktrees.get(layer, {}).get("dirty")
        if not dirty_path:
            return MergeResult(
                success=False,
                slice_id=slice_id,
                layer=layer,
                error=f"No dirty worktree for layer '{layer}'",
            )

        # Get the slice branch name
        slice_branch = self.vcs.get_current_branch(self._slice_worktrees[full_id])
        if not slice_branch:
            return MergeResult(
                success=False,
                slice_id=slice_id,
                layer=layer,
                error="Cannot determine slice branch",
            )

        if strategy == "merge":
            ok, err = self.vcs.merge(dirty_path, slice_branch)
        elif strategy == "rebase":
            ok, err = self.vcs.rebase(dirty_path, slice_branch)
        else:
            return MergeResult(
                success=False,
                slice_id=slice_id,
                layer=layer,
                error=f"Unknown merge strategy: {strategy}",
            )
        if not ok:
            return MergeResult(
                success=False,
                slice_id=slice_id,
                layer=layer,
                error=err,
            )

        merge_sha = self.vcs.get_head_sha(dirty_path)
        logger.info("Merged slice '%s' into %s/dirty", slice_id, layer)
        return MergeResult(
            success=True,
            slice_id=slice_id,
            layer=layer,
            merge_sha=merge_sha,
        )

    def cleanup_slice_worktree(self, layer: Layer, slice_id: str) -> None:
        """Remove a slice worktree."""
        full_id = f"{layer}:{slice_id}"
        path = self._slice_worktrees.get(full_id)
        if path is None:
            return

        ok, err = self.vcs.remove_worktree(path)
        if not ok:
            logger.warning("Failed removing slice worktree '%s': %s", full_id, err)
            return

        self._slice_worktrees.pop(full_id, None)
        logger.info("Removed slice worktree '%s'", full_id)

    # ------------------------------------------------------------------
    # Batch / CI primitives
    # ------------------------------------------------------------------

    def _next_batch_tag_name(self, layer: Layer) -> tuple[str, int]:
        """Allocate the next unique batch tag name for *layer*."""
        seq = self._batch_seq.get(layer, 0) + 1
        self._batch_seq[layer] = seq
        return f"pdd/{self.run_id}/batch/{layer}/{seq}", seq

    def snapshot_candidate(self, layer: Layer) -> str | None:
        """Set candidate ref to dirty HEAD; returns SHA.

        The candidate is the "batch" being tested for promotion.
        """
        dirty_path = self._layer_worktrees.get(layer, {}).get("dirty")
        if not dirty_path:
            return None

        dirty_sha = self.vcs.get_head_sha(dirty_path)
        if not dirty_sha:
            return None

        clean_path = self._layer_worktrees.get(layer, {}).get("clean")
        base_clean_sha = self.vcs.get_head_sha(clean_path) if clean_path else None

        merge_commits: list[str] = []
        if base_clean_sha:
            commits = self.vcs.rev_list(base_clean_sha, dirty_sha, merges_only=True)
            if isinstance(commits, list):
                merge_commits = [str(commit) for commit in commits if str(commit).strip()]

        tag_ok = False
        tag_err = ""
        tag_name = ""
        for _ in range(8):
            tag_name, seq = self._next_batch_tag_name(layer)
            metadata_lines = [
                f"PDD batch snapshot: run={self.run_id} layer={layer} seq={seq}",
                f"base_clean_sha: {base_clean_sha or 'unknown'}",
                f"candidate_sha: {dirty_sha}",
                "included_merge_commits:",
            ]
            if merge_commits:
                metadata_lines.extend(f"- {merge_sha}" for merge_sha in merge_commits)
            else:
                metadata_lines.append("- none")
            tag_ok, tag_err = self.vcs.create_tag(
                tag_name,
                dirty_sha,
                message="\n".join(metadata_lines),
            )
            if tag_ok or "exists" not in tag_err.lower():
                break
        if not tag_ok:
            logger.warning("Failed to create batch tag %s for %s: %s", tag_name, layer, tag_err)
            return None

        candidate_branch = self.candidate_ref(layer)
        ok, err = self.vcs.update_ref(candidate_branch, dirty_sha)
        if not ok:
            logger.warning("Failed to snapshot candidate for %s: %s", layer, err)
            return None

        logger.info("Snapshot candidate for %s: %s", layer, dirty_sha[:12])
        return dirty_sha

    def clear_candidate(self, layer: Layer) -> None:
        """Clear the candidate ref for a layer."""
        candidate_branch = self.candidate_ref(layer)
        if self.vcs.rev_parse(candidate_branch) is None:
            return
        ok, err = self.vcs.delete_ref(candidate_branch)
        if not ok:
            logger.warning("Failed to clear candidate ref for %s: %s", layer, err)

    @staticmethod
    def _resolve_gate_check(
        config: bool | dict[str, Any],
        *,
        check_id: str,
    ) -> tuple[bool, list[str], str]:
        """Resolve gate check config into pass/fail + ticket metadata."""
        if isinstance(config, dict):
            enabled = bool(config.get("enabled", True))
            if not enabled:
                return True, [], ""
            passed = bool(config.get("passed", True))
            tickets = [str(t) for t in (config.get("demotion_tickets", []) or []) if str(t).strip()]
            error = str(config.get("error", "")).strip()
            if passed:
                return True, [], ""
            if not tickets:
                tickets = [f"{check_id}_failed"]
            if not error:
                error = f"{check_id} failed"
            return False, tickets, error

        enabled = bool(config)
        if not enabled:
            return True, [], ""
        return (
            False,
            [f"{check_id}_not_evaluated"],
            f"{check_id} enabled without explicit evaluation result",
        )

    def _default_tier_commands(self, workspace_root: Path) -> dict[str, Any]:
        """Infer tier command defaults from known test layouts."""
        commands: dict[str, Any] = {}
        spec_tests_root = workspace_root / "scripts" / "spec_manager" / "tests"
        repo_tests_root = workspace_root / "tests"

        if spec_tests_root.exists():
            unit_dir = spec_tests_root / "unit"
            component_dir = spec_tests_root / "component"
            l1_component_dir = component_dir / "orchestration"

            if unit_dir.exists():
                commands["tier1_command"] = "uv run pytest -q scripts/spec_manager/tests/unit"
            if component_dir.exists():
                commands["tier2_command"] = "uv run pytest -q scripts/spec_manager/tests/component"
            if l1_component_dir.exists():
                commands["tier2_l1_command"] = (
                    "uv run pytest -q scripts/spec_manager/tests/component/orchestration"
                )
            commands["tier3_command"] = "uv run pytest -q scripts/spec_manager/tests"
            return commands

        if repo_tests_root.exists():
            unit_dir = repo_tests_root / "unit"
            integration_dir = repo_tests_root / "integration"
            component_dir = repo_tests_root / "component"

            if unit_dir.exists():
                commands["tier1_command"] = "uv run pytest -q tests/unit"
            else:
                commands["tier1_command"] = "uv run pytest -q tests"

            if integration_dir.exists():
                commands["tier2_command"] = "uv run pytest -q tests/integration"
                commands["tier2_l1_command"] = "uv run pytest -q tests/integration"
            elif component_dir.exists():
                commands["tier2_command"] = "uv run pytest -q tests/component"
                commands["tier2_l1_command"] = "uv run pytest -q tests/component"

            commands["tier3_command"] = "uv run pytest -q tests"

        return commands

    def _run_tier_tests(
        self,
        layer: Layer,
        tests: bool | dict[str, Any],
    ) -> tuple[bool, list[str], str]:
        """Execute tiered tests for a layer promotion."""
        from spec_manager.orchestration.test_tiers import TierConfig, TierRunner

        if isinstance(tests, dict):
            enabled = bool(tests.get("enabled", True))
            overrides = dict(tests)
        else:
            enabled = bool(tests)
            overrides = {}
        if not enabled:
            return True, [], ""

        dirty_path = self._layer_worktrees.get(layer, {}).get("dirty")
        if not dirty_path or not dirty_path.exists():
            return False, [f"tests_failed:{layer}"], f"No dirty worktree for {layer}"

        config_payload = self._default_tier_commands(dirty_path)
        config_payload.update(overrides)
        config_payload.pop("enabled", None)

        tier_runner = TierRunner(config=TierConfig.from_dict(config_payload), cwd=dirty_path)
        tier_results = tier_runner.run_for_layer(layer)
        first_failure = next((result for result in tier_results if not result.passed), None)
        if first_failure is None:
            return True, [], ""

        failure_detail = str(
            first_failure.error or first_failure.output or "test tier failed"
        ).strip()
        return (
            False,
            [f"tests_failed:{layer}:tier{first_failure.tier}"],
            f"Tier {first_failure.tier} failed for {layer}: {failure_detail[:500]}",
        )

    def promote_dirty_to_clean(
        self,
        layer: Layer,
        *,
        gates: bool | dict[str, Any] = False,
        tests: bool | dict[str, Any] = False,
    ) -> BatchResult:
        """Advance clean to the candidate snapshot (fast-forward).

        This is the "dirty → clean" promotion at a single layer.
        Gate/test checks are configured by ``gates`` and ``tests``.
        """
        clean_path = self._layer_worktrees.get(layer, {}).get("clean")
        base_clean_sha = self.vcs.get_head_sha(clean_path) if clean_path else None

        candidate_sha = self.vcs.rev_parse(self.candidate_ref(layer))
        if not candidate_sha:
            return BatchResult(
                success=False,
                layer=layer,
                base_clean_sha=base_clean_sha,
                error="No candidate snapshot",
                gates_passed=True,
                tests_passed=True,
            )

        gates_passed, gate_tickets, gate_error = self._resolve_gate_check(gates, check_id="gates")
        tests_passed, test_tickets, test_error = self._run_tier_tests(layer, tests)
        ci_tickets = [*gate_tickets, *test_tickets]

        if not gates_passed or not tests_passed:
            reasons = [reason for reason in (gate_error, test_error) if reason]
            return BatchResult(
                success=False,
                layer=layer,
                candidate_sha=candidate_sha,
                base_clean_sha=base_clean_sha,
                gates_passed=gates_passed,
                tests_passed=tests_passed,
                error="; ".join(reasons) if reasons else "CI checks failed",
                demotion_tickets=ci_tickets,
            )

        clean_branch = self.layer_branch(layer, "clean")
        ok, err = self.vcs.update_ref(clean_branch, candidate_sha)
        if not ok:
            return BatchResult(
                success=False,
                layer=layer,
                candidate_sha=candidate_sha,
                base_clean_sha=base_clean_sha,
                error=f"Failed to advance clean: {err}",
                gates_passed=gates_passed,
                tests_passed=tests_passed,
            )

        # Also update the clean worktree to match
        clean_path = self._layer_worktrees.get(layer, {}).get("clean")
        if clean_path:
            # Reset clean worktree to the new clean branch HEAD
            sync_ok, sync_err = self.vcs.rebase(clean_path, clean_branch)
            if not sync_ok:
                return BatchResult(
                    success=False,
                    layer=layer,
                    candidate_sha=candidate_sha,
                    base_clean_sha=base_clean_sha,
                    clean_sha=candidate_sha,
                    error=f"Clean ref advanced but failed to sync clean worktree: {sync_err}",
                    gates_passed=gates_passed,
                    tests_passed=tests_passed,
                )

        logger.info("Promoted %s clean to %s", layer, candidate_sha[:12])
        return BatchResult(
            success=True,
            layer=layer,
            candidate_sha=candidate_sha,
            base_clean_sha=base_clean_sha,
            clean_sha=candidate_sha,
            gates_passed=gates_passed,
            tests_passed=tests_passed,
        )

    def propagate_clean_to_next_layer(self, from_layer: Layer) -> PropagateResult:
        """Merge from_layer's clean into next_layer's dirty.

        This is the cross-layer batch promotion:
        L1 clean → L2 dirty, L2 clean → L3 dirty.
        """
        to_layer = next_layer(from_layer)
        if to_layer is None:
            return PropagateResult(
                success=False,
                from_layer=from_layer,
                to_layer=from_layer,
                error="No next layer (already at L3)",
            )

        try:
            self._ensure_layer_worktrees(to_layer)
        except RuntimeError as exc:
            return PropagateResult(
                success=False,
                from_layer=from_layer,
                to_layer=to_layer,
                error=str(exc),
            )

        to_dirty_path = self._layer_worktrees.get(to_layer, {}).get("dirty")
        if not to_dirty_path:
            return PropagateResult(
                success=False,
                from_layer=from_layer,
                to_layer=to_layer,
                error=f"No dirty worktree for {to_layer}",
            )

        from_clean_branch = self.layer_branch(from_layer, "clean")
        ok, err = self.vcs.merge(to_dirty_path, from_clean_branch)
        if not ok:
            return PropagateResult(
                success=False,
                from_layer=from_layer,
                to_layer=to_layer,
                error=err,
            )

        merge_sha = self.vcs.get_head_sha(to_dirty_path)
        logger.info(
            "Propagated %s/clean → %s/dirty (%s)",
            from_layer,
            to_layer,
            merge_sha[:12] if merge_sha else "?",
        )
        return PropagateResult(
            success=True,
            from_layer=from_layer,
            to_layer=to_layer,
            merge_sha=merge_sha,
        )

    def rebase_next_layer_dirty_onto_clean(self, from_layer: Layer) -> PropagateResult:
        """Rebase next layer dirty onto *from_layer* clean as conflict recovery."""
        to_layer = next_layer(from_layer)
        if to_layer is None:
            return PropagateResult(
                success=False,
                from_layer=from_layer,
                to_layer=from_layer,
                error="No next layer (already at L3)",
            )

        to_dirty_path = self._layer_worktrees.get(to_layer, {}).get("dirty")
        if not to_dirty_path:
            return PropagateResult(
                success=False,
                from_layer=from_layer,
                to_layer=to_layer,
                error=f"No dirty worktree for {to_layer}",
            )

        from_clean_branch = self.layer_branch(from_layer, "clean")
        ok, err = self.vcs.rebase(to_dirty_path, from_clean_branch)
        if not ok:
            return PropagateResult(
                success=False,
                from_layer=from_layer,
                to_layer=to_layer,
                error=err,
            )

        rebased_sha = self.vcs.get_head_sha(to_dirty_path)
        logger.info(
            "Rebased %s/dirty onto %s/clean (%s)",
            to_layer,
            from_layer,
            rebased_sha[:12] if rebased_sha else "?",
        )
        return PropagateResult(
            success=True,
            from_layer=from_layer,
            to_layer=to_layer,
            merge_sha=rebased_sha,
        )

    # ------------------------------------------------------------------
    # Pipeline tick (drain whatever can advance)
    # ------------------------------------------------------------------

    def tick_pipeline(
        self,
        active_layer: Layer,
        *,
        max_pending_batches: int = 1,
        run_gates: bool | dict[str, Any] = False,
        run_tests: bool | dict[str, Any] = False,
    ) -> PipelineTickResult:
        """Attempt to advance the entire pipeline in one tick.

        For each layer (L1 → L2 → L3):
        1. If dirty != clean and CI is free → snapshot candidate
        2. Evaluate configured gates/tests for the candidate
        3. Advance clean to candidate when checks pass
        4. Propagate clean to next layer's dirty
        5. At L3: merge clean to main

        Args:
            active_layer: The currently active creative layer.
            max_pending_batches: Backpressure limit.
            run_gates: Gate check config for each promote operation.
            run_tests: Test check config for each promote operation.

        Returns:
            PipelineTickResult summarizing what advanced.
        """
        result = PipelineTickResult()

        for layer in LAYER_ORDER:
            if layer not in self._layer_worktrees:
                continue

            # Check backpressure
            if not self._check_backpressure(layer, max_pending_batches):
                logger.debug(
                    "Backpressure: skipping %s (downstream not caught up)",
                    layer,
                )
                continue

            # Check if there's pending work
            if self.is_layer_clean(layer):
                continue

            # Check if a candidate is already in flight
            existing_candidate = self.vcs.rev_parse(self.candidate_ref(layer))
            clean_sha = self.vcs.get_head_sha(self._layer_worktrees[layer].get("clean", Path()))

            if existing_candidate and existing_candidate != clean_sha:
                # Candidate lock is exclusive per layer; do not start or promote
                # another candidate until this one is explicitly resolved.
                logger.debug(
                    "Candidate in flight for %s at %s; skipping promotion tick",
                    layer,
                    existing_candidate[:12],
                )
                continue

            # Snapshot and promote the current dirty head.
            candidate_sha = self.snapshot_candidate(layer)
            if not candidate_sha:
                clean_path = self._layer_worktrees.get(layer, {}).get("clean")
                base_clean_sha = self.vcs.get_head_sha(clean_path) if clean_path else None
                result.layer_results[layer] = BatchResult(
                    success=False,
                    layer=layer,
                    base_clean_sha=base_clean_sha,
                    error=f"Failed to snapshot candidate for {layer}",
                    gates_passed=True,
                    tests_passed=True,
                )
                break

            batch = self.promote_dirty_to_clean(
                layer,
                gates=run_gates,
                tests=run_tests,
            )

            result.layer_results[layer] = batch

            if not batch.success:
                if batch.demotion_tickets:
                    result.demotion_tickets.extend(batch.demotion_tickets)
                # Stop propagating if this layer failed
                break

            # Clear candidate after successful promotion
            self.clear_candidate(layer)

            # Update upstream acceptance on consumer-side promotion.
            self._update_upstream_accepted(layer)

            # Propagate to next layer
            nl = next_layer(layer)
            if nl and nl in self._layer_worktrees:
                prop = self.propagate_clean_to_next_layer(layer)
                result.propagation_results.append(prop)
                if not prop.success:
                    result.demotion_tickets.append(f"propagation_failed:{layer}→{nl}")

        return result

    # ------------------------------------------------------------------
    # Layer transition helpers
    # ------------------------------------------------------------------

    def compute_active_layer(self) -> Layer:
        """Determine which layer should be active.

        The active layer is the lowest layer with dirty != clean.

        Demotion reopening is represented by writing new commits to a
        target layer's dirty branch, which naturally makes dirty != clean.
        """
        for layer in LAYER_ORDER:
            if layer not in self._layer_worktrees:
                continue
            if not self.is_layer_clean(layer):
                return layer
        # All layers clean — return L1 as default
        return "l1"

    def can_advance_layer(self, layer: Layer) -> bool:
        """Check if the system can advance past this layer.

        Requirements:
        - This layer is fully clean
        - All higher layers have no failing candidates
        - Pipeline has drained (downstream clean == dirty)
        """
        if not self.is_layer_clean(layer):
            return False

        # Check all layers above are also clean
        idx = LAYER_ORDER.index(layer)
        for upper_layer in LAYER_ORDER[idx + 1 :]:
            if upper_layer not in self._layer_worktrees:
                continue
            if not self.is_layer_clean(upper_layer):
                return False

        return True

    def cleanup_layer_slices(self, layer: Layer) -> list[str]:
        """Remove all slice worktrees for a layer."""
        prefix = f"{layer}:"
        removed = []
        for full_id in list(self._slice_worktrees.keys()):
            if full_id.startswith(prefix):
                path = self._slice_worktrees[full_id]
                ok, err = self.vcs.remove_worktree(path)
                if not ok:
                    logger.warning("Failed removing slice worktree '%s': %s", full_id, err)
                    continue
                self._slice_worktrees.pop(full_id, None)
                removed.append(full_id)
        return removed

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> dict[str, Any]:
        """Remove all worktrees for this run."""
        removed: list[str] = []
        errors: list[dict[str, str]] = []

        # Remove slice worktrees
        for full_id, path in list(self._slice_worktrees.items()):
            ok, err = self.vcs.remove_worktree(path)
            if ok:
                removed.append(f"slice/{full_id}")
            else:
                errors.append({"worktree": f"slice/{full_id}", "error": err})
        self._slice_worktrees.clear()

        # Remove layer worktrees (clean first, then dirty)
        for layer in reversed(LAYER_ORDER):
            for lane in ("clean", "dirty"):
                wt = self._layer_worktrees.get(layer, {}).get(lane)
                if wt and self.vcs.worktree_exists(wt):
                    ok, err = self.vcs.remove_worktree(wt)
                    if ok:
                        removed.append(f"{layer}/{lane}")
                    else:
                        errors.append({"worktree": f"{layer}/{lane}", "error": err})
        self._layer_worktrees.clear()
        self._layer_branches.clear()

        # Clear candidate refs
        for layer in LAYER_ORDER:
            candidate_ref = self.candidate_ref(layer)
            if self.vcs.rev_parse(candidate_ref) is None:
                continue
            ok, err = self.vcs.delete_ref(candidate_ref)
            if not ok:
                errors.append({"worktree": f"{layer}/candidate", "error": err})

        logger.info("Cleanup complete: removed %d worktrees", len(removed))
        return {"removed": removed, "errors": errors}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_backpressure(self, layer: Layer, max_pending: int) -> bool:
        """Check if backpressure allows promoting at this layer."""
        nl = next_layer(layer)
        if nl is None:
            return True  # L3 has no downstream

        if nl not in self._layer_worktrees:
            return True

        # How many commits are pending in the downstream?
        upstream_ref = self.upstream_accepted_ref(nl)
        upstream_sha = self.vcs.rev_parse(upstream_ref)
        clean_sha = self.vcs.get_head_sha(self._layer_worktrees.get(layer, {}).get("clean", Path()))

        if not upstream_sha or not clean_sha:
            return True  # No tracking yet, allow

        count = self.vcs.rev_list_count(upstream_sha, clean_sha)
        if count is None:
            return True

        return count <= max_pending

    def _ensure_layer_worktrees(self, layer: Layer) -> list[dict[str, str]]:
        """Ensure dirty/clean worktrees exist for *layer*.

        Returns:
            Metadata entries for worktrees created in this call.
        """
        created: list[dict[str, str]] = []
        for lane in ("dirty", "clean"):
            existing_path = self._layer_worktrees.get(layer, {}).get(lane)
            if existing_path is not None:
                self._layer_branches.setdefault(layer, {})[lane] = self.layer_branch(layer, lane)
                continue

            branch = self.layer_branch(layer, lane)
            path = self.layer_worktree_path(layer, lane)
            ok, err = self.vcs.create_worktree(path, branch, start_point=self._base_ref)
            if not ok:
                raise RuntimeError(f"Failed to create {layer}/{lane} worktree: {err}")

            self._layer_worktrees.setdefault(layer, {})[lane] = path
            self._layer_branches.setdefault(layer, {})[lane] = branch
            created.append({"layer": layer, "lane": lane, "path": str(path)})
            logger.info("Created %s/%s worktree at %s", layer, lane, path)

        return created

    def _update_upstream_accepted(self, layer: Layer) -> None:
        """Record that *layer* accepted its upstream clean state.

        For example, when L2 promotes dirty->clean successfully, this moves
        ``l2/upstream_accepted`` to the current ``l1/clean`` SHA.
        """
        upstream_layer = prev_layer(layer)
        if upstream_layer is None:
            return

        upstream_clean = self.vcs.get_head_sha(
            self._layer_worktrees.get(upstream_layer, {}).get("clean", Path())
        )
        if not upstream_clean:
            return

        ref = self.upstream_accepted_ref(layer)
        ok, err = self.vcs.update_ref(ref, upstream_clean)
        if not ok:
            logger.warning(
                "Failed updating upstream acceptance for %s from %s clean: %s",
                layer,
                upstream_layer,
                err,
            )
            return
