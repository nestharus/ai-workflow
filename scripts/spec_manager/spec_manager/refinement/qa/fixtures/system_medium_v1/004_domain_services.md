# Domain Services (Core Business Logic)

[INTRO]
Domain Services implement core business workflows and orchestrate interactions between Gateway,
Storage, and Event Bus.

[BOUNDARIES]
- Owns domain business logic and workflow orchestration.
- Does NOT own request routing or input validation (Gateway owns those).
- Does NOT own transport-level delivery semantics (Event Bus owns those).
- Does NOT own storage durability mechanisms (Storage owns those).

[REQUIREMENTS]
- Execute domain workflows deterministically from validated inputs.
- Persist domain state changes via Storage.
- Publish domain events via Event Bus when state changes.

[CONSTRAINTS]
- Must be testable via deterministic unit tests (no hidden I/O).
- Must support idempotent workflow execution.

[INTEGRATION]
- Receives validated requests from Gateway.
- Uses Storage for persistence and reads.
- Uses Event Bus for event emission.

