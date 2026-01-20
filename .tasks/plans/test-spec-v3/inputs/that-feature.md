# That Feature - Event Delivery

Handles delivery of routed events to sinks.

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

### Algorithm 3 - Event Delivery ([=Algorithm 3])

For each routed event:
1. Look up sink from D4
2. Format event for sink type via format_for_sink()
3. Attempt delivery via sink_client()
4. On failure, apply D5 retry policy
5. After max retries, send to dead_letter_queue()

This replaces the old manual delivery code.

---

### G2 - Delivery Guarantee ([=G2])

Goal: At-least-once delivery to all matched sinks.

Depends on Algorithm 3 and D5 working correctly together.
What about exactly-once? Is that a future requirement?
