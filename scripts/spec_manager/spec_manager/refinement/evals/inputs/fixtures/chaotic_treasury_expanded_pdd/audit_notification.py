"""Audit/notification types and stub interfaces.

This module is intentionally minimal: it defines the data structures and
public surface for an audit + notification system, but does not provide any
persistence, routing, batching, or retry behavior.

Important:
    ``AuditNotification`` is a protocol (interface). ``NoopAuditNotification``
    is a concrete no-op implementation.

    If a no-op implementation is accidentally wired as the runtime component,
    audit entries and notifications will be silently dropped.

    Prefer depending on narrower protocol types (e.g., ``AuditWriter``,
    ``NotificationRouter``) and wiring a real implementation in production.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Protocol

type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | Mapping[str, JsonValue] | list[JsonValue]

# JSON encoders generally require finite numbers; NaN/Infinity are not valid JSON.
# Production implementations should reject or normalize non-finite floats at boundaries.

type Payload = Mapping[str, JsonValue]


@dataclass(frozen=True)
class Notification:
    """A single notification event.

    This value type exists so batching can carry the routing key (``event_type``)
    alongside the JSON-object ``payload``.
    """

    event_type: str
    payload: Payload


type Notifications = Sequence[Notification]

# Suggested configuration defaults for production implementations.
AUDIT_WRITE_LATENCY_BUDGET_MS: Final[int] = 50
NOTIFICATION_BATCH_MAX_SIZE: Final[int] = 50
NOTIFICATION_BATCH_WINDOW_SECONDS: Final[int] = 60
NOTIFICATION_BATCH_FLUSH_THRESHOLD: Final[int] = 20


@dataclass(frozen=True)
class AuditNotificationConfig:
    """Suggested configuration defaults for production implementations.

    This module provides :meth:`validate` but does not call it automatically.
    Real implementations are expected to:
    - Validate invariants (e.g., non-negative budgets, flush threshold not
      exceeding max size).
    - Decide how values influence durability, batching, and retry behavior.

    Suggested field meanings (implementations may interpret differently):
    - ``audit_write_latency_budget_ms``: Soft budget for the ``write_audit`` call
      path under normal conditions.
    - ``notification_batch_max_size``: Maximum notifications per batch.
    - ``notification_batch_window_seconds``: Buffering window before a flush.
    - ``notification_batch_flush_threshold``: Size that triggers an early flush.
    """

    audit_write_latency_budget_ms: int = AUDIT_WRITE_LATENCY_BUDGET_MS
    notification_batch_max_size: int = NOTIFICATION_BATCH_MAX_SIZE
    notification_batch_window_seconds: int = NOTIFICATION_BATCH_WINDOW_SECONDS
    notification_batch_flush_threshold: int = NOTIFICATION_BATCH_FLUSH_THRESHOLD

    def validate(self) -> None:
        """Validate cross-field invariants for configuration values.

        This module does not enforce configuration invariants at construction time.
        Real implementations may call this helper during wiring/startup to fail fast.

        Raises:
            ValueError: If any invariant is violated.
        """

        if self.audit_write_latency_budget_ms < 0:
            raise ValueError("audit_write_latency_budget_ms must be non-negative")
        if self.notification_batch_max_size <= 0:
            raise ValueError("notification_batch_max_size must be positive")
        if self.notification_batch_window_seconds <= 0:
            raise ValueError("notification_batch_window_seconds must be positive")
        if self.notification_batch_flush_threshold < 0:
            raise ValueError("notification_batch_flush_threshold must be non-negative")
        if self.notification_batch_flush_threshold > self.notification_batch_max_size:
            raise ValueError(
                "notification_batch_flush_threshold must not exceed notification_batch_max_size"
            )


@dataclass
class AuditEntry:
    """Audit trail entry.

    Intended semantics (documented for implementers and callers):
    - ``entry_id``: Caller-provided identifier for the stored audit record. The
      value should be stable for the lifetime of the record.
    - ``event_type``: Stable classifier used for routing/aggregation.
    - ``payload``: JSON-object event data. While this class is mutable for
      ergonomic construction, treat values as immutable once constructed
      (especially across retries). Implementations should not mutate the entry.
    - ``idempotency_key``: Caller-provided key identifying the *logical* event
      across retries. Implementations typically use this key to deduplicate
      repeated writes.
    """

    entry_id: str
    event_type: str
    payload: Payload
    idempotency_key: str


class AuditWriter(Protocol):
    """Minimal audit writer capability.

    Contract notes:
    - Implementations may persist synchronously or durably enqueue work.
    - Real implementations should surface failures (e.g., by raising) rather
      than silently dropping entries.
    - Idempotency/deduplication is typically driven by ``AuditEntry.idempotency_key``.
    - Concurrency/thread-safety expectations should be documented by implementations.
    """

    def write_audit(self, entry: AuditEntry) -> None:
        """Write an audit entry.

        Typical expectations for real implementations:
        - Return once the write is accepted (persisted or durably queued).
        - Use ``entry.idempotency_key`` to deduplicate retries.
        - Raise on failure rather than silently dropping the entry.
        """

        ...


class AuditWriteRetryHandler(Protocol):
    """Optional retry capability for audit writes.

    Ownership note:
        Many implementations handle retries internally as part of ``write_audit``.
        If exposed, this protocol is intended for internal retry workers only.
    """

    def retry_write_audit(self, entry: AuditEntry) -> None:
        """Retry a failed audit write.

        Typical expectations for real implementations:
        - Only use for idempotent writes.
        - Surface failures (raise and/or emit logs/metrics) rather than dropping.
        """

        ...


class NotificationRouter(Protocol):
    """Minimal notification routing capability.

    Contract notes:
    - Implementations typically encode/transport ``payload`` as JSON.
    - Real implementations should surface routing/serialization failures.
    - Concurrency/thread-safety expectations should be documented by implementations.
    """

    def route_notification(self, notification: Notification) -> None:
        """Route a notification.

        Typical expectations for real implementations:
        - Use ``notification.event_type`` to select a destination.
        - Encode/transport ``notification.payload`` as JSON.
        - Raise on invalid ``notification.event_type`` or non-serializable
          ``notification.payload``.
        """

        ...


class NotificationBatcher(Protocol):
    """Optional batching capability for notifications.

    Contract notes:
    - Implementations may buffer in memory for a time/window.
    - Real implementations should surface failures rather than silently dropping.
    - Concurrency/thread-safety expectations should be documented by implementations.
    """

    def batch_notifications(self, notifications: Notifications) -> None:
        """Batch notifications during high volume.

        Typical expectations for real implementations:
        - ``notifications`` carries per-item ``event_type`` and ``payload``.
        - Batching constraints are often derived from ``AuditNotificationConfig``
          (max size, window, flush threshold).
        - Failures should be surfaced rather than silently dropping events.
        """

        ...


class AuditNotification(
    AuditWriter,
    AuditWriteRetryHandler,
    NotificationRouter,
    NotificationBatcher,
    Protocol,
):
    """Combined audit + notification interface.

    This is a pure protocol; it exists to provide a convenient single type for
    wiring components that need both audit writing and notification routing.

    Implementations decide:
    - Whether operations are synchronous vs. durably queued.
    - What failures are raised vs. handled internally.
    - What batching/retry policies apply.
    """

    config: AuditNotificationConfig


@dataclass
class NoopAuditNotification:
    """Concrete no-op implementation.

    Intended for tests or explicitly disabled environments.

    This implementation intentionally and silently drops audit entries and
    notifications and never raises.
    """

    config: AuditNotificationConfig = field(default_factory=AuditNotificationConfig)

    def write_audit(self, entry: AuditEntry) -> None:
        return None

    def route_notification(self, notification: Notification) -> None:
        return None

    def batch_notifications(self, notifications: Notifications) -> None:
        return None

    def retry_write_audit(self, entry: AuditEntry) -> None:
        return None
