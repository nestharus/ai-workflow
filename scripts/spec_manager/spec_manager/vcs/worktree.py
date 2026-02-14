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

Backward-compatible: ``setup()`` still works for single-layer usage.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Literal

from spec_manager.orchestration.models import (
    LAYER_ORDER,
    BatchResult,
    Lane,
    Layer,
    LayerStatus,
    MergeResult,
    PipelineTickResult,
    PropagateResult,
    next_layer,
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

        # Legacy branch names (backward compat)
        self._root_branch = f"pdd/{run_id}/root"
        self._clean_branch = f"pdd/{run_id}/clean"
        self._root_path = self.worktrees_base / f"{run_id}-root"
        self._clean_path = self.worktrees_base / f"{run_id}-clean"

        # Track active library worktrees: lib_id → Path (legacy)
        self._library_worktrees: dict[str, Path] = {}

        # Multi-layer state
        self._layer_worktrees: dict[Layer, dict[Lane, Path]] = {}
        self._layer_branches: dict[Layer, dict[Lane, str]] = {}
        self._candidate_refs: dict[Layer, str] = {}
        self._upstream_accepted: dict[Layer, str] = {}
        self._slice_worktrees: dict[str, Path] = {}  # slice_id → Path
        self._base_ref: str = "HEAD"
        self._layers_initialized: bool = False

    # ------------------------------------------------------------------
    # Legacy Public API (backward compatible)
    # ------------------------------------------------------------------

    def setup(self) -> dict[str, Any]:
        """Create the root (dirty) and clean worktrees.

        This is the legacy single-layer setup.  For multi-layer, use
        :meth:`setup_layers`.

        Returns:
            Dict with ``root_path`` and ``clean_path``.
        """
        self.worktrees_base.mkdir(parents=True, exist_ok=True)
        start = self.vcs.get_current_branch() or "HEAD"

        ok, err = self.vcs.create_worktree(self._root_path, self._root_branch, start_point=start)
        if not ok:
            raise RuntimeError(f"Failed to create root worktree: {err}")
        logger.info("Created root worktree at %s", self._root_path)

        ok, err = self.vcs.create_worktree(self._clean_path, self._clean_branch, start_point=start)
        if not ok:
            raise RuntimeError(f"Failed to create clean worktree: {err}")
        logger.info("Created clean worktree at %s", self._clean_path)

        return {
            "root_path": str(self._root_path),
            "clean_path": str(self._clean_path),
        }

    def create_library_worktree(self, lib_id: str) -> Path:
        """Create a grandchild worktree for a specific library (legacy).

        For multi-layer, use :meth:`create_slice_worktree`.
        """
        if lib_id in self._library_worktrees:
            raise RuntimeError(f"Library worktree already exists for '{lib_id}'")

        branch = f"pdd/{self.run_id}/lib/{lib_id}"
        path = self.worktrees_base / f"{self.run_id}-lib-{lib_id}"
        start = self._root_branch

        ok, err = self.vcs.create_worktree(path, branch, start_point=start)
        if not ok:
            raise RuntimeError(f"Failed to create worktree for library '{lib_id}': {err}")

        self._library_worktrees[lib_id] = path
        logger.info("Created library worktree for '%s' at %s", lib_id, path)
        return path

    def promote_library(self, lib_id: str) -> dict[str, Any]:
        """Promote a library's work into the clean worktree (legacy)."""
        if lib_id not in self._library_worktrees:
            raise RuntimeError(f"No worktree found for library '{lib_id}'")

        lib_branch = f"pdd/{self.run_id}/lib/{lib_id}"
        ok, err = self.vcs.merge(self._clean_path, lib_branch)
        if not ok:
            raise RuntimeError(f"Failed to promote library '{lib_id}' to clean worktree: {err}")

        logger.info("Promoted library '%s' to clean worktree", lib_id)
        return {"lib_id": lib_id, "promoted": True}

    def rebase_root_on_clean(self) -> dict[str, Any]:
        """Rebase the dirty root worktree onto the clean sibling (legacy)."""
        ok, err = self.vcs.rebase(self._root_path, self._clean_branch)
        if not ok:
            raise RuntimeError(f"Failed to rebase root onto clean: {err}")

        logger.info("Rebased root worktree onto clean worktree")
        return {"rebased": True}

    def get_library_worktree(self, lib_id: str) -> Path | None:
        """Return the worktree path for a library, or ``None``."""
        return self._library_worktrees.get(lib_id)

    def list_worktrees(self) -> list[dict[str, Any]]:
        """List all active library worktrees."""
        return [
            {"lib_id": lib_id, "path": str(path)}
            for lib_id, path in sorted(self._library_worktrees.items())
        ]

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
            for lane in ("dirty", "clean"):
                branch = self.layer_branch(layer, lane)
                path = self.layer_worktree_path(layer, lane)

                ok, err = self.vcs.create_worktree(path, branch, start_point=self._base_ref)
                if not ok:
                    raise RuntimeError(f"Failed to create {layer}/{lane} worktree: {err}")

                if layer not in self._layer_worktrees:
                    self._layer_worktrees[layer] = {}
                if layer not in self._layer_branches:
                    self._layer_branches[layer] = {}

                self._layer_worktrees[layer][lane] = path
                self._layer_branches[layer][lane] = branch
                created.append({"layer": layer, "lane": lane, "path": str(path)})
                logger.info("Created %s/%s worktree at %s", layer, lane, path)

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
        base: Lane = "dirty",
    ) -> Path:
        """Create a grandchild worktree for a slice at a layer.

        Args:
            layer: Which layer this slice belongs to.
            slice_id: Unique slice identifier.
            base: Which lane to branch from (default: dirty).

        Returns:
            Path to the slice worktree.
        """
        full_id = f"{layer}:{slice_id}"
        if full_id in self._slice_worktrees:
            raise RuntimeError(f"Slice worktree already exists for '{full_id}'")

        nonce = uuid.uuid4().hex[:6]
        branch = f"pdd/{self.run_id}/{layer}/slice/{slice_id}/{nonce}"
        path = self.worktrees_base / f"{self.run_id}-{layer}-slice-{slice_id}"

        start = self.layer_branch(layer, base)

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
        path = self._slice_worktrees.pop(full_id, None)
        if path and self.vcs.worktree_exists(path):
            self.vcs.remove_worktree(path)
            logger.info("Removed slice worktree '%s'", full_id)

    # ------------------------------------------------------------------
    # Batch / CI primitives
    # ------------------------------------------------------------------

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

        candidate_branch = self.candidate_ref(layer)
        ok, err = self.vcs.update_ref(candidate_branch, dirty_sha)
        if not ok:
            logger.warning("Failed to snapshot candidate for %s: %s", layer, err)
            return None

        self._candidate_refs[layer] = dirty_sha
        logger.info("Snapshot candidate for %s: %s", layer, dirty_sha[:12])
        return dirty_sha

    def clear_candidate(self, layer: Layer) -> None:
        """Clear the candidate ref for a layer."""
        candidate_branch = self.candidate_ref(layer)
        self.vcs.delete_ref(candidate_branch)
        self._candidate_refs.pop(layer, None)

    @staticmethod
    def _resolve_ci_check(
        config: bool | dict[str, Any],
        *,
        check_id: str,
    ) -> tuple[bool, list[str], str]:
        """Resolve one CI check config into pass/fail + ticket metadata."""
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
        return True, [], ""

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
        gates_passed, gate_tickets, gate_error = self._resolve_ci_check(gates, check_id="gates")
        tests_passed, test_tickets, test_error = self._resolve_ci_check(tests, check_id="tests")
        ci_tickets = [*gate_tickets, *test_tickets]

        candidate_sha = self.vcs.rev_parse(self.candidate_ref(layer))
        if not candidate_sha:
            return BatchResult(
                success=False,
                layer=layer,
                error="No candidate snapshot",
                gates_passed=gates_passed,
                tests_passed=tests_passed,
                demotion_tickets=ci_tickets,
            )

        if not gates_passed or not tests_passed:
            reasons = [reason for reason in (gate_error, test_error) if reason]
            return BatchResult(
                success=False,
                layer=layer,
                candidate_sha=candidate_sha,
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
                error=f"Failed to advance clean: {err}",
                gates_passed=gates_passed,
                tests_passed=tests_passed,
            )

        # Also update the clean worktree to match
        clean_path = self._layer_worktrees.get(layer, {}).get("clean")
        if clean_path:
            # Reset clean worktree to the new clean branch HEAD
            self.vcs.rebase(clean_path, clean_branch)

        logger.info("Promoted %s clean to %s", layer, candidate_sha[:12])
        return BatchResult(
            success=True,
            layer=layer,
            candidate_sha=candidate_sha,
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
                # Candidate in flight — assume it passes and promote
                batch = self.promote_dirty_to_clean(
                    layer,
                    gates=run_gates,
                    tests=run_tests,
                )
            else:
                # Snapshot and promote
                self.snapshot_candidate(layer)
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

            # Propagate to next layer
            nl = next_layer(layer)
            if nl and nl in self._layer_worktrees:
                prop = self.propagate_clean_to_next_layer(layer)
                result.propagation_results.append(prop)
                if not prop.success:
                    result.demotion_tickets.append(f"propagation_failed:{layer}→{nl}")

            # Update upstream_accepted tracking
            self._update_upstream_accepted(layer)

        return result

    # ------------------------------------------------------------------
    # Layer transition helpers
    # ------------------------------------------------------------------

    def compute_active_layer(self) -> Layer:
        """Determine which layer should be active.

        The active layer is the lowest layer that has dirty != clean
        or has open demotion work.
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
                path = self._slice_worktrees.pop(full_id)
                if self.vcs.worktree_exists(path):
                    self.vcs.remove_worktree(path)
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

        # Remove library worktrees (legacy)
        for lib_id, path in list(self._library_worktrees.items()):
            ok, err = self.vcs.remove_worktree(path)
            if ok:
                removed.append(f"lib/{lib_id}")
            else:
                errors.append({"worktree": f"lib/{lib_id}", "error": err})
        self._library_worktrees.clear()

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

        # Remove legacy worktrees
        if self.vcs.worktree_exists(self._clean_path):
            ok, err = self.vcs.remove_worktree(self._clean_path)
            if ok:
                removed.append("clean")
            else:
                errors.append({"worktree": "clean", "error": err})

        if self.vcs.worktree_exists(self._root_path):
            ok, err = self.vcs.remove_worktree(self._root_path)
            if ok:
                removed.append("root")
            else:
                errors.append({"worktree": "root", "error": err})

        # Clear candidate refs
        for layer in LAYER_ORDER:
            self.vcs.delete_ref(self.candidate_ref(layer))

        logger.info("Cleanup complete: removed %d worktrees", len(removed))
        return {"removed": removed, "errors": errors}

    # ------------------------------------------------------------------
    # Properties (legacy compat)
    # ------------------------------------------------------------------

    @property
    def root_path(self) -> Path:
        """Path to the root (dirty) worktree (legacy)."""
        return self._root_path

    @property
    def clean_path(self) -> Path:
        """Path to the clean sibling worktree (legacy)."""
        return self._clean_path

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

    def _update_upstream_accepted(self, layer: Layer) -> None:
        """Update the upstream_accepted ref for the next layer."""
        nl = next_layer(layer)
        if nl is None:
            return

        clean_sha = self.vcs.get_head_sha(self._layer_worktrees.get(layer, {}).get("clean", Path()))
        if clean_sha:
            ref = self.upstream_accepted_ref(nl)
            self.vcs.update_ref(ref, clean_sha)
            self._upstream_accepted[nl] = clean_sha
