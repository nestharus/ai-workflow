# Data Library

Data structures for the event processing system.

---

### D1 - Event ([=D1])

Basic event structure:
- id (uuid)
- source (string - where it came from)
- payload (json)
- timestamp
- type (string)

We probably need more fields but this is v1.

---

### D2 - Source ([=D2])

A source is where events come from:
- id
- name
- config (json - connection details, etc.)

Hmm, should config include auth? Probably need to call authenticate_source()
before we can pull events. TODO: figure out auth flow.

---

### D3 - Sink ([=D3])

Where we send processed events:
- id
- name
- type (kafka, s3, webhook, etc.)
- config

Not sure if we need a separate Transform entity or if that's part of routing.

---
Section 2: Processing
---

---

### D5 - Dead Letter Queue ([=D5])

Events that fail after max retries go here:
- original_event (copy of D1)
- error_reason
- failed_at
- retry_count

---
Section 4: Reliability
---
