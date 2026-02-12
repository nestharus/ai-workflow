"""Backward-compatibility re-exports — canonical location is vcs.operations."""

from spec_manager.vcs.operations import *  # noqa: F403
from spec_manager.vcs.operations import GitVcs, VcsOperations  # explicit for type checkers

__all__ = ["GitVcs", "VcsOperations"]
