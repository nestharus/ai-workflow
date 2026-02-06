"""Audit service - subscribes to rule events and writes audit entries."""

from __future__ import annotations

from typing import Any

from spec_manager.labyrinth.core.bus import AsyncMessageBus
from spec_manager.labyrinth.core.event_log import EventLog


class AuditService:
    """Subscribes to rule execution events and writes audit log entries.

    This is a 'decoy-like' service - it subscribes to the same topics as
    functional rules but produces logging/audit output rather than
    functional output. Tests REQUIRE it to fire.
    """

    def __init__(self, bus: AsyncMessageBus, event_log: EventLog) -> None:
        self._bus = bus
        self._event_log = event_log
        self._audit_entries: list[dict[str, Any]] = []

    def subscribe_to_topic(self, topic: str) -> None:
        """Subscribe to a topic for audit logging."""
        self._bus.subscribe(
            topic=topic,
            handler=self._handle_event,
            subscriber_id=f"audit_service:{topic}",
        )

    async def _handle_event(self, topic: str, payload: dict[str, Any]) -> None:
        """Handle a bus event by creating an audit entry."""
        entry = {
            "topic": topic,
            "rule_id": payload.get("rule_id", ""),
            "record_id": payload.get("record_id", ""),
            "action": "RULE_EXECUTED",
        }
        self._audit_entries.append(entry)
        self._event_log.append(
            event_type="audit_logged",
            source="audit_service",
            topic=topic,
            data=entry,
        )

    @property
    def audit_entries(self) -> list[dict[str, Any]]:
        """Return all audit entries."""
        return list(self._audit_entries)

    def clear(self) -> None:
        """Clear all audit entries."""
        self._audit_entries.clear()
