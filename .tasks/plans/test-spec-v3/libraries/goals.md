# Goals Library

Goals for the event system.

---

### G1 - Routing Latency ([=G1])

Goal: Route events within 10ms of ingestion.

Might conflict with complex rule matching. Need to benchmark.
How should we handle no matching rules? Drop or default sink?

---

### G2 - Delivery Guarantee ([=G2])

Goal: At-least-once delivery to all matched sinks.

Depends on Algorithm 3 and D5 working correctly together.
What about exactly-once? Is that a future requirement?

---
