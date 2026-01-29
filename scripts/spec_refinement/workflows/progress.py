"""Progress tracking utilities for spec refinement workflows."""

from __future__ import annotations

import sys
import threading
from datetime import datetime
from typing import Any

from tqdm import tqdm

from scripts.spec_refinement.workspace import WorkspaceManager


class ProgressTracker:
    """Track progress with a terminal progress bar and workspace history logging."""

    def __init__(
        self, total: int, description: str, *, manager: WorkspaceManager | None = None
    ) -> None:
        """Create a progress tracker with a total count and optional workspace history logging."""
        self.total = total
        self.description = description
        self._manager = manager
        self._count = 0
        # Avoid multiprocessing locks/monitor threads to prevent resource_tracker noise in tests.
        tqdm.set_lock(threading.RLock())
        tqdm.monitor_interval = 0
        self._bar = tqdm(total=total, desc=description, disable=not sys.stderr.isatty())
        self._log("progress_started", {"total": total, "description": description})

    def update(self, increment: int = 1, status: str = "") -> None:
        """Advance progress and optionally update status text."""
        self._count += increment
        if status:
            self._bar.set_postfix_str(status)
        self._bar.update(increment)
        payload = {"current": self._count}
        if status:
            payload["status"] = status
        self._log("progress_update", payload)

    def finish(self) -> None:
        """Close the progress bar and record completion."""
        self._bar.close()
        self._log("progress_finished", {"current": self._count, "total": self.total})

    def _log(self, event: str, data: dict[str, Any]) -> None:
        if self._manager is None:
            return
        self._manager.state.history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "event": event,
                **data,
            }
        )
