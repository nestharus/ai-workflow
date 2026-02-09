"""Workspace manager for spec_manager workspace lifecycle.

Provides:
- WorkspaceManager: Manages workspace directory structure, state, and migration
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from spec_manager.workspace.state import WorkspaceState

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Manages the workspace directory structure and state lifecycle.

    The workspace lives at {spec_folder}/.workspace/ and contains:
    - state.json: Workspace state
    - reports/: Reports directory (migration logs, etc.)

    Args:
        spec_folder: Path to the spec folder
    """

    def __init__(self, spec_folder: Path) -> None:
        self.spec_folder = spec_folder
        self.workspace_dir = spec_folder / ".workspace"
        self._state: WorkspaceState | None = None

        # Auto-load state if it exists
        state_file = self.workspace_dir / "state.json"
        if state_file.exists():
            self._state = WorkspaceState.load(state_file)

    @property
    def state(self) -> WorkspaceState:
        """Get the current workspace state.

        Returns:
            WorkspaceState instance (creates fresh if not loaded)
        """
        if self._state is None:
            self._state = WorkspaceState(spec_folder=str(self.spec_folder))
        return self._state

    def initialize(self) -> None:
        """Initialize workspace directory structure.

        Creates .workspace/, .workspace/reports/, and a fresh state file.
        """
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        reports_dir = self.workspace_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        if self._state is None:
            self._state = WorkspaceState(spec_folder=str(self.spec_folder))

        state_file = self.workspace_dir / "state.json"
        self._state.save(state_file)

    def get_migration_log_path(self) -> Path:
        """Get the path to the migration log file.

        Returns:
            Path to migration.log
        """
        return self.workspace_dir / "reports" / "migration.log"

    def read_migration_log(self) -> list[dict[str, Any]]:
        """Read migration log entries.

        Skips malformed JSON lines gracefully.

        Returns:
            List of migration log entry dictionaries
        """
        log_path = self.get_migration_log_path()
        if not log_path.exists():
            return []

        entries: list[dict[str, Any]] = []
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                # Skip malformed lines
                continue

        return entries
