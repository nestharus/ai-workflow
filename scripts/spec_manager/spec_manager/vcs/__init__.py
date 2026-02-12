"""VCS abstraction layer for worktree management."""

from __future__ import annotations

from spec_manager.vcs.operations import GitVcs, VcsOperations
from spec_manager.vcs.worktree import WorktreeManager

__all__ = [
    "GitVcs",
    "VcsOperations",
    "WorktreeManager",
]
