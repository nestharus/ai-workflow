"""Backward-compatibility re-exports — canonical location is vcs.worktree."""

from spec_manager.vcs.worktree import *  # noqa: F403
from spec_manager.vcs.worktree import WorktreeManager  # explicit for type checkers

__all__ = ["WorktreeManager"]
