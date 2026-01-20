# Data Library

Data structures for the event system.

---

### D1 - Event ([=D1])

Core event structure:
- id: uuid
- type: string
- payload: json
- timestamp: datetime
- source_id: reference to D2

Events flow through the pipeline defined in Algorithm 1.

---

### D2 - EventSource ([=D2])

Where events originate:
- id: uuid
- name: string
- protocol: http | websocket | kafka
- config: json

Each source must be registered before use.

---

### D3 - RoutingRule ([=D3])

Rules for directing events to sinks:
- id: uuid
- source_pattern: regex matching D2 names
- type_pattern: regex matching event types
- sink_id: reference to D4
- priority: int

Higher priority rules evaluated first.

---

### D4 - Sink ([=D4])

Destination for processed events:
- id: uuid
- name: string
- type: kafka | s3 | webhook | database
- config: json
- retry_policy: reference to D5

Each sink type uses a different delivery mechanism.

---

### D5 - RetryPolicy ([=D5])

How to handle delivery failures:
- max_attempts: int
- backoff_ms: int
- backoff_multiplier: float

TODO: decide if we need circuit breaker logic here.

---

### Algorithm 1 - Event Ingestion ([=Algorithm 1])

Steps:
1. Receive event from source
2. Validate schema via validate_event()
3. Assign internal tracking id
4. Enqueue for processing

This is the entry point for all events.

Uses (@[+D1]) and (@[+D2]).

---

### Algorithm 2 - Event Routing ([=Algorithm 2])

After ingestion:
1. Load routing rules from rule_store()
2. Match event against rules by priority
3. For each match, queue event for that sink
4. Track routing decisions in audit_log()

This depends on Algorithm 1 completing first.

Uses (@[+D3]) and (@[+D4]).

---

### Algorithm 3 - Event Delivery ([=Algorithm 3])

For each routed event:
1. Look up sink from D4
2. Format event for sink type via format_for_sink()
3. Attempt delivery via sink_client()
4. On failure, apply D5 retry policy
5. After max retries, send to dead_letter_queue()

Uses (@[+D4]) and (@[+D5]).

---
