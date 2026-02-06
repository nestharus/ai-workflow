"""Append-only event log for capturing execution steps."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LogEntry:
    """A single entry in the event log.

    Attributes:
        timestamp: Monotonic timestamp of the event.
        event_type: Type of event (e.g., rule_executed, service_triggered).
        source: Source component (rule ID, service name, etc.).
        topic: Bus topic associated with this event.
        data: Arbitrary event data.
    """

    timestamp: float
    event_type: str
    source: str
    topic: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class EventLog:
    """Append-only log capturing all execution steps.

    Thread-safe. Used by integration tests to verify that:
    1. All integration points were connected
    2. All side-effect chains fired in correct order
    """

    def __init__(self) -> None:
        self._entries: list[LogEntry] = []
        self._lock = threading.Lock()

    def append(
        self,
        event_type: str,
        source: str,
        topic: str = "",
        data: dict[str, Any] | None = None,
    ) -> LogEntry:
        """Append a new entry to the log.

        Args:
            event_type: Type of event.
            source: Source component.
            topic: Bus topic.
            data: Event data.

        Returns:
            The created LogEntry.
        """
        entry = LogEntry(
            timestamp=time.monotonic(),
            event_type=event_type,
            source=source,
            topic=topic,
            data=data or {},
        )
        with self._lock:
            self._entries.append(entry)
        return entry

    @property
    def entries(self) -> list[LogEntry]:
        """Return a snapshot of all entries."""
        with self._lock:
            return list(self._entries)

    def filter_by_type(self, event_type: str) -> list[LogEntry]:
        """Return entries matching the given event type."""
        with self._lock:
            return [e for e in self._entries if e.event_type == event_type]

    def filter_by_source(self, source: str) -> list[LogEntry]:
        """Return entries from the given source."""
        with self._lock:
            return [e for e in self._entries if e.source == source]

    def filter_by_topic(self, topic: str) -> list[LogEntry]:
        """Return entries on the given topic."""
        with self._lock:
            return [e for e in self._entries if e.topic == topic]

    def get_sources_in_order(self) -> list[str]:
        """Return ordered list of unique sources as they appeared."""
        with self._lock:
            seen: set[str] = set()
            ordered: list[str] = []
            for entry in self._entries:
                if entry.source not in seen:
                    seen.add(entry.source)
                    ordered.append(entry.source)
            return ordered

    def clear(self) -> None:
        """Clear all entries."""
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
