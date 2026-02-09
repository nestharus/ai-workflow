"""Worktree manager for parallel library implementation.

Implements the worktree hierarchy from ``simpler.md``:

- **Dirty root worktree** — where the PDD pipeline runs and messy
  parallel implementation happens.
- **Per-library grandchild worktrees** — one per library, agents
  implement in parallel with no dependency tracking.
- **Clean sibling worktree** — accumulates tested, promoted code.
  The dirty worktree rebases onto the clean worktree periodically
  to avoid big-bang integration.

Usage::

    from spec_manager.orchestration.vcs import GitVcs
    from spec_manager.orchestration.worktree_manager import WorktreeManager

    vcs = GitVcs(repo_root=Path("."))
    mgr = WorktreeManager(vcs=vcs, workspace_root=Path("."), run_id="my-run")
    mgr.setup()

    path = mgr.create_library_worktree("auth-service")
    # ... run implementation agent in `path` ...
    mgr.promote_library("auth-service")

    mgr.cleanup()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from spec_manager.orchestration.vcs import VcsOperations

logger = logging.getLogger(__name__)


class WorktreeManager:
    """Manages worktrees for parallel per-library implementation.

    Args:
        vcs: VCS abstraction (e.g. :class:`GitVcs`).
        workspace_root: Root of the repository / workspace.
        run_id: Unique identifier for this PDD run (used to namespace
            worktree directories and branch names).
        worktrees_base: Base directory for worktrees.  Defaults to
            ``workspace_root / ".worktrees"``.
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

        self._root_branch = f"pdd/{run_id}/root"
        self._clean_branch = f"pdd/{run_id}/clean"

        self._root_path = self.worktrees_base / f"{run_id}-root"
        self._clean_path = self.worktrees_base / f"{run_id}-clean"

        # Track active library worktrees: lib_id → Path
        self._library_worktrees: dict[str, Path] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def setup(self) -> dict[str, Any]:
        """Create the root (dirty) and clean worktrees.

        Must be called before creating library worktrees.

        Returns:
            Dict with ``root_path`` and ``clean_path``.

        Raises:
            RuntimeError: If worktree creation fails.
        """
        self.worktrees_base.mkdir(parents=True, exist_ok=True)

        # Determine start point — current branch HEAD
        start = self.vcs.get_current_branch() or "HEAD"

        # Create root (dirty) worktree
        ok, err = self.vcs.create_worktree(
            self._root_path, self._root_branch, start_point=start
        )
        if not ok:
            raise RuntimeError(f"Failed to create root worktree: {err}")
        logger.info("Created root worktree at %s", self._root_path)

        # Create clean sibling worktree
        ok, err = self.vcs.create_worktree(
            self._clean_path, self._clean_branch, start_point=start
        )
        if not ok:
            raise RuntimeError(f"Failed to create clean worktree: {err}")
        logger.info("Created clean worktree at %s", self._clean_path)

        return {
            "root_path": str(self._root_path),
            "clean_path": str(self._clean_path),
        }

    def create_library_worktree(self, lib_id: str) -> Path:
        """Create a grandchild worktree for a specific library.

        The worktree branches off the root (dirty) worktree's current
        HEAD so it inherits the PDD pipeline output.

        Args:
            lib_id: Library identifier (e.g. ``"auth-service"``).

        Returns:
            Path to the library's worktree.

        Raises:
            RuntimeError: If the library worktree already exists or
                creation fails.
        """
        if lib_id in self._library_worktrees:
            raise RuntimeError(
                f"Library worktree already exists for '{lib_id}'"
            )

        branch = f"pdd/{self.run_id}/lib/{lib_id}"
        path = self.worktrees_base / f"{self.run_id}-lib-{lib_id}"

        # Start from root worktree's HEAD
        start = self._root_branch

        ok, err = self.vcs.create_worktree(path, branch, start_point=start)
        if not ok:
            raise RuntimeError(
                f"Failed to create worktree for library '{lib_id}': {err}"
            )

        self._library_worktrees[lib_id] = path
        logger.info("Created library worktree for '%s' at %s", lib_id, path)
        return path

    def promote_library(self, lib_id: str) -> dict[str, Any]:
        """Promote a library's work into the clean worktree.

        Merges the library branch into the clean sibling.  Per
        ``simpler.md``: *"As slices of work are completed, they are
        extracted from the commits and pushed on to the clean worktree
        where tests can run and pass."*

        Args:
            lib_id: Library identifier.

        Returns:
            Promotion result dict.

        Raises:
            RuntimeError: If merge fails (conflict).
        """
        if lib_id not in self._library_worktrees:
            raise RuntimeError(f"No worktree found for library '{lib_id}'")

        lib_branch = f"pdd/{self.run_id}/lib/{lib_id}"

        ok, err = self.vcs.merge(self._clean_path, lib_branch)
        if not ok:
            raise RuntimeError(
                f"Failed to promote library '{lib_id}' to clean worktree: {err}"
            )

        logger.info("Promoted library '%s' to clean worktree", lib_id)
        return {"lib_id": lib_id, "promoted": True}

    def rebase_root_on_clean(self) -> dict[str, Any]:
        """Rebase the dirty root worktree onto the clean sibling.

        Per ``simpler.md``: *"Then the dirty worktree is rebased on to
        the clean worktree.  This avoids final big bang integration."*

        Returns:
            Rebase result dict.

        Raises:
            RuntimeError: If rebase fails.
        """
        ok, err = self.vcs.rebase(self._root_path, self._clean_branch)
        if not ok:
            raise RuntimeError(
                f"Failed to rebase root onto clean: {err}"
            )

        logger.info("Rebased root worktree onto clean worktree")
        return {"rebased": True}

    def get_library_worktree(self, lib_id: str) -> Path | None:
        """Return the worktree path for a library, or ``None``."""
        return self._library_worktrees.get(lib_id)

    def list_worktrees(self) -> list[dict[str, Any]]:
        """List all active library worktrees.

        Returns:
            List of dicts with ``lib_id`` and ``path``.
        """
        return [
            {"lib_id": lib_id, "path": str(path)}
            for lib_id, path in sorted(self._library_worktrees.items())
        ]

    def cleanup(self) -> dict[str, Any]:
        """Remove all worktrees for this run.

        Removes library worktrees first, then clean and root.

        Returns:
            Cleanup summary dict.
        """
        removed: list[str] = []
        errors: list[dict[str, str]] = []

        # Remove library worktrees
        for lib_id, path in list(self._library_worktrees.items()):
            ok, err = self.vcs.remove_worktree(path)
            if ok:
                removed.append(f"lib/{lib_id}")
            else:
                errors.append({"worktree": f"lib/{lib_id}", "error": err})
        self._library_worktrees.clear()

        # Remove clean worktree
        if self.vcs.worktree_exists(self._clean_path):
            ok, err = self.vcs.remove_worktree(self._clean_path)
            if ok:
                removed.append("clean")
            else:
                errors.append({"worktree": "clean", "error": err})

        # Remove root worktree
        if self.vcs.worktree_exists(self._root_path):
            ok, err = self.vcs.remove_worktree(self._root_path)
            if ok:
                removed.append("root")
            else:
                errors.append({"worktree": "root", "error": err})

        logger.info("Cleanup complete: removed %d worktrees", len(removed))
        return {"removed": removed, "errors": errors}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def root_path(self) -> Path:
        """Path to the root (dirty) worktree."""
        return self._root_path

    @property
    def clean_path(self) -> Path:
        """Path to the clean sibling worktree."""
        return self._clean_path
