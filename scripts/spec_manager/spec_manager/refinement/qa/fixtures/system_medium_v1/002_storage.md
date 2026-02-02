# Storage (Durable Persistence)

[INTRO]
Storage provides durable record persistence and retrieval APIs consumed by other libraries.

[BOUNDARIES]
- Owns record storage and retrieval operations.
- Owns internal durability mechanisms (journaling, compaction) as an implementation detail.
- Does NOT own request validation.
- Does NOT own request routing.

[REQUIREMENTS]
- Store records reliably with an idempotency key.
- Support lookup by ID.
- Support deletion by ID with tombstoning semantics.

[CONSTRAINTS]
- Data must be encrypted at rest.
- Data durability target is 99.99% monthly.

[INTEGRATION]
- Called by Gateway for persistence.
- Called by Domain Services to read historical state.

