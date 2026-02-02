# Gateway (External API)

[INTRO]
The Gateway receives external HTTP requests and routes them to internal components.
It is responsible for request-shape validation and correlation IDs.

[BOUNDARIES]
- Owns request routing for inbound HTTP traffic.
- Owns input validation for inbound requests.
- Does NOT own durable storage (delegates persistence to Storage).
- Does NOT own domain business logic (delegates to Domain Services).

[REQUIREMENTS]
- Validate request schema; reject invalid requests with a clear error.
- Route requests based on path/method to internal handlers.
- Attach a `correlation_id` to each request and propagate it downstream.

[CONSTRAINTS]
- Must add <= 5ms p95 latency at 1000 rps steady-state.
- Must not log secrets (tokens, passwords, API keys).

[INTEGRATION]
- Calls Storage to persist request/response metadata and retrieve prior records.
- Publishes audit events to Event Bus for security/compliance.

