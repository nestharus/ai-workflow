"""Notification service - triggers on rule execution events."""

from __future__ import annotations

from typing import Any

from spec_manager.labyrinth.core.bus import AsyncMessageBus
from spec_manager.labyrinth.core.event_log import EventLog


class NotificationService:
    """Triggers webhook-like notifications on rule execution events.

    Another side-effect service that tests require to fire correctly.
    """

    def __init__(self, bus: AsyncMessageBus, event_log: EventLog) -> None:
        self._bus = bus
        self._event_log = event_log
        self._notifications: list[dict[str, Any]] = []

    def subscribe_to_topic(self, topic: str) -> None:
        """Subscribe to a topic for notifications."""
        self._bus.subscribe(
            topic=topic,
            handler=self._handle_event,
            subscriber_id=f"notification_service:{topic}",
        )

    async def _handle_event(self, topic: str, payload: dict[str, Any]) -> None:
        """Handle a bus event by creating a notification."""
        notification = {
            "topic": topic,
            "rule_id": payload.get("rule_id", ""),
            "record_id": payload.get("record_id", ""),
            "type": "webhook",
        }
        self._notifications.append(notification)
        self._event_log.append(
            event_type="notification_sent",
            source="notification_service",
            topic=topic,
            data=notification,
        )

    @property
    def notifications(self) -> list[dict[str, Any]]:
        """Return all notifications."""
        return list(self._notifications)

    def clear(self) -> None:
        """Clear all notifications."""
        self._notifications.clear()
