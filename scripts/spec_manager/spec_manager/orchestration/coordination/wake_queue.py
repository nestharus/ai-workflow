"""Disk-backed wake-event queue for agent coordination.

When a JIT monitor detects that a blocking condition has been resolved,
it enqueues a WakeEvent.  The promotion loop dequeues events for a slice
before deciding the next step.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WakeEvent:
    """Notification that a monitor condition has been satisfied."""

    event_id: str = ""
    timestamp: str = ""
    monitor_id: str = ""
    signal_id: str = ""
    slice_id: str = ""
    layer: str = ""
    reason: str = ""
    artifact_key: str = ""
    wake_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id:
            self.event_id = os.urandom(8).hex()
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "monitor_id": self.monitor_id,
            "signal_id": self.signal_id,
            "slice_id": self.slice_id,
            "layer": self.layer,
            "reason": self.reason,
            "artifact_key": self.artifact_key,
            "wake_payload": self.wake_payload,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WakeEvent:
        return cls(
            event_id=d.get("event_id", ""),
            timestamp=d.get("timestamp", ""),
            monitor_id=d.get("monitor_id", ""),
            signal_id=d.get("signal_id", ""),
            slice_id=d.get("slice_id", ""),
            layer=d.get("layer", ""),
            reason=d.get("reason", ""),
            artifact_key=d.get("artifact_key", ""),
            wake_payload=d.get("wake_payload", {}),
        )


class WakeQueue:
    """File-backed queue of wake events per slice.

    Events are stored as individual JSON files under
    ``<coordination_dir>/wake_events/``.
    """

    def __init__(self, coordination_dir: Path) -> None:
        self._dir = coordination_dir / "wake_events"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _event_filename(self, event: WakeEvent) -> str:
        # Include event_id so each wake artifact has collision-proof identity.
        ts = event.timestamp.replace(":", "-").replace("+", "p")
        safe_slice = "".join(
            ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(event.slice_id)
        )
        safe_event_id = "".join(
            ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(event.event_id)
        )
        return f"wake_{ts}_{safe_slice}_{safe_event_id}.json"

    def enqueue(self, event: WakeEvent) -> None:
        """Persist a wake event to disk."""
        path = self._dir / self._event_filename(event)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), indent=2))

    def _read_all(self, slice_id: str | None = None) -> list[tuple[Path, WakeEvent]]:
        """Read all events, optionally filtered by slice_id."""
        results: list[tuple[Path, WakeEvent]] = []
        if not self._dir.exists():
            return results
        for p in sorted(self._dir.iterdir()):
            if not p.name.endswith(".json"):
                continue
            try:
                evt = WakeEvent.from_dict(json.loads(p.read_text()))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.warning("Skipping malformed wake-event file '%s': %s", p, exc)
                continue
            if slice_id is None or evt.slice_id == slice_id:
                results.append((p, evt))
        return results

    def dequeue(self, slice_id: str) -> list[WakeEvent]:
        """Read and delete all events for *slice_id*."""
        pairs = self._read_all(slice_id)
        events: list[WakeEvent] = []
        for path, evt in pairs:
            events.append(evt)
            path.unlink(missing_ok=True)
        return events

    def peek(self, slice_id: str | None = None) -> list[WakeEvent]:
        """Read events without consuming them."""
        return [evt for _, evt in self._read_all(slice_id)]

    def clear(self, slice_id: str) -> None:
        """Remove all events for *slice_id*."""
        for path, _ in self._read_all(slice_id):
            path.unlink(missing_ok=True)
