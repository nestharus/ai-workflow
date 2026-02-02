# Event Bus (Audit + Integration Events)

[INTRO]
Event Bus provides publish/subscribe messaging for audit and integration events.

[BOUNDARIES]
- Owns event publishing and delivery semantics.
- Does NOT own business logic; it transports events only.
- Does NOT own persistent business state (delegates to Storage when needed).

[REQUIREMENTS]
- Accept events with type, timestamp, and payload.
- Deliver events to subscribed consumers at-least-once.
- Support consumer groups with independent offsets.

[CONSTRAINTS]
- Must preserve event order per key.
- Must support burst throughput >= 10k events/sec.
- Must expose basic delivery metrics (lag, throughput, error counts).

[INTEGRATION]
- Gateway publishes audit events.
- Domain Services publish domain events.
- Observability consumes delivery metrics for alerting.

