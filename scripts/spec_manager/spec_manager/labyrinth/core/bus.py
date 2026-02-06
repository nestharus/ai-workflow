"""Async pub/sub message bus with topic routing."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# Handler type: async callable taking (topic, payload) -> None
Handler = Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]


@dataclass
class Subscription:
    """A topic subscription."""

    topic: str
    handler: Handler
    subscriber_id: str


class AsyncMessageBus:
    """Asyncio-based pub/sub message bus with topic routing.

    Rules dispatch to other rules via bus events, not direct calls.
    This provides the primary indirection mechanism for the labyrinth.
    """

    def __init__(self) -> None:
        self._subscriptions: dict[str, list[Subscription]] = defaultdict(list)
        self._pending: list[tuple[str, dict[str, Any]]] = []
        self._running = False

    def subscribe(self, topic: str, handler: Handler, subscriber_id: str = "") -> None:
        """Subscribe a handler to a topic.

        Args:
            topic: Topic to subscribe to.
            handler: Async handler function.
            subscriber_id: Identifier for the subscriber.
        """
        sub = Subscription(topic=topic, handler=handler, subscriber_id=subscriber_id)
        self._subscriptions[topic].append(sub)

    def unsubscribe(self, topic: str, subscriber_id: str) -> None:
        """Remove a subscription by subscriber ID."""
        self._subscriptions[topic] = [
            s for s in self._subscriptions[topic] if s.subscriber_id != subscriber_id
        ]

    async def publish(self, topic: str, payload: dict[str, Any] | None = None) -> None:
        """Publish a message to a topic.

        All subscribers for the topic are notified concurrently.

        Args:
            topic: Topic to publish to.
            payload: Message payload.
        """
        payload = payload or {}
        subscribers = self._subscriptions.get(topic, [])
        if not subscribers:
            logger.debug("No subscribers for topic '%s'", topic)
            return

        tasks = []
        for sub in subscribers:
            tasks.append(self._safe_dispatch(sub, topic, payload))

        await asyncio.gather(*tasks)

    async def _safe_dispatch(
        self, sub: Subscription, topic: str, payload: dict[str, Any]
    ) -> None:
        """Dispatch to a subscriber with error handling."""
        try:
            await sub.handler(topic, payload)
        except Exception:
            logger.exception(
                "Handler error (subscriber=%s, topic=%s)", sub.subscriber_id, topic
            )

    def get_subscriber_count(self, topic: str) -> int:
        """Return the number of subscribers for a topic."""
        return len(self._subscriptions.get(topic, []))

    def get_topics(self) -> list[str]:
        """Return all topics with subscribers."""
        return [t for t, subs in self._subscriptions.items() if subs]

    def clear(self) -> None:
        """Remove all subscriptions."""
        self._subscriptions.clear()
