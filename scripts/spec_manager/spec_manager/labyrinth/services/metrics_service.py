"""Metrics service - counters and gauges on rule events."""

from __future__ import annotations

from typing import Any

from spec_manager.labyrinth.core.bus import AsyncMessageBus
from spec_manager.labyrinth.core.event_log import EventLog


class MetricsService:
    """Tracks counters and gauges based on rule execution events.

    Yet another side-effect service for integration testing.
    """

    def __init__(self, bus: AsyncMessageBus, event_log: EventLog) -> None:
        self._bus = bus
        self._event_log = event_log
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}

    def subscribe_to_topic(self, topic: str) -> None:
        """Subscribe to a topic for metrics tracking."""
        self._bus.subscribe(
            topic=topic,
            handler=self._handle_event,
            subscriber_id=f"metrics_service:{topic}",
        )

    async def _handle_event(self, topic: str, payload: dict[str, Any]) -> None:
        """Handle a bus event by updating metrics."""
        counter_key = f"rule_executions:{topic}"
        self._counters[counter_key] = self._counters.get(counter_key, 0) + 1

        self._event_log.append(
            event_type="metrics_updated",
            source="metrics_service",
            topic=topic,
            data={"counter": counter_key, "value": self._counters[counter_key]},
        )

    def get_counter(self, key: str) -> int:
        """Get a counter value."""
        return self._counters.get(key, 0)

    def set_gauge(self, key: str, value: float) -> None:
        """Set a gauge value."""
        self._gauges[key] = value

    def get_gauge(self, key: str) -> float:
        """Get a gauge value."""
        return self._gauges.get(key, 0.0)

    @property
    def counters(self) -> dict[str, int]:
        """Return all counters."""
        return dict(self._counters)

    def clear(self) -> None:
        """Clear all metrics."""
        self._counters.clear()
        self._gauges.clear()
