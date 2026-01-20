"""Workspace management for spec processing."""

from spec_manager.workspace.manager import WorkspaceManager
from spec_manager.workspace.state import WorkspaceState, PhaseStatus

__all__ = [
    "WorkspaceManager",
    "WorkspaceState",
    "PhaseStatus",
]
