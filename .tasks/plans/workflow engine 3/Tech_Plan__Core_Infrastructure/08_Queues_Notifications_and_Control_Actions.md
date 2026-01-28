# Core Infrastructure — Queues (Notifications + Control Actions)

- **Doc**: Tech_Plan__Core_Infrastructure/08_Queues_Notifications_and_Control_Actions.md
- **Updated**: 2026-01-26
- **Library**: `workflow_engine.storage.queues`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md), [`03_IDs_and_Time.md`](03_IDs_and_Time.md), [`06_Durability_Protocol.md`](06_Durability_Protocol.md)
- **Primary responsibility**: Durable, local-first maildir-like queues for user notifications and control/action envelopes.

## 9) Notifications Store and Control Actions Queue (maildir-like)

Two durable queues exist:

- `notifications/` — messages intended for the user (or UI surface)
- `control_actions/` — user/system control envelopes (pause/resume/ack/decisions)

Both queues use the same hardened pattern:

- atomic publish (`tmp/` → `inbox/`)
- atomic claim (`inbox/` → `processing/<consumer_id>/`)
- bounded requeue on crash (processing TTL)
- idempotency via `notification_id` / `request_id`

Queue directories:

```text
notifications/{tmp,inbox,processing/<consumer_id>,archive}
control_actions/{tmp,inbox,processing/<consumer_id>,ack,applied,failed,archive}
```

Queue moves that change semantic state (`inbox→processing`, `processing→applied/failed`) are covered by write-ahead journals (§7.2).

### 9.0 Consumer identity (`consumer_id`) (normative)

Queue claim semantics require a stable per-consumer directory under `processing/`.

**Definition**: `consumer_id` identifies a single consumer process instance.

**Format (v1)**:
`<role>.<pid>.<ulid>`

- `role`: short string enum (recommended):
  - `root` (root runtime)
  - `pm` (Project Manager session)
  - `tm` (Ticket Manager session)
  - `step` (step execution process consuming its control actions)
  - `ui` (any external UI wrapper)
  - `gc`, `doctor`, `recover` (maintenance commands)
- `pid`: OS process id as decimal
- `ulid`: generated once at process start (`new_ulid()`)

Example:
- `tm.48210.01J3ZQK9X5J9H6R8V2S4J2E9P3`

**Allocation rule**:
- A process that consumes a queue MUST generate exactly one `consumer_id` at startup and reuse it for the lifetime of the process.

**PID reuse after reboot**:
- PID reuse is not a collision because the ULID component differs.
- Old processing directories from previous process instances are cleaned by the lease TTL reaper.

**ULID generation failure**:
- If ULID generation fails, the process MUST fail loudly with `E_INTERNAL` ("cannot generate consumer_id") and refuse to consume queues.
- No fallback or retry for ULID generation itself.

**Collision detection (defensive)**:
On consumer startup:
1. Attempt to create `processing/<consumer_id>/` directory exclusively (atomic mkdir).
2. If directory already exists:
   - Generate a new ULID and retry (up to 3 attempts).
   - If still exists after 3 retries → fail loudly with `E_ULID_COLLISION`.

**Stale consumer cleanup**:
- Reaping is performed by the root runtime (or `workflowctl recover`).
- A processing directory is stale if:
  - `lease.json` is missing or expired (`last_heartbeat_ts` older than `queues.lease_ttl_ms`), AND
  - no file in the directory has `mtime` within `queues.processing_ttl_ms` (default `300000`)
- Reaper action:
  1. Move all queue items back to `inbox/` (atomic rename per file).
  2. Record each move in WAJ (§7.2).
  3. Delete the stale `processing/<consumer_id>/` directory.

Empty processing directories MAY be removed by the reaper.
### 9.1 Notification schema and priority

A notification is a JSON document with required fields (Core §5.2) plus:

- `notification_id` (ULID; required)
- `dedupe_key` (string; optional) — deterministic key for suppressing duplicate notifications
- `severity` (enum; required): `info|warn|error|critical`
- `title` (string; required)
- `message` (string; required)
- `kind` (string; optional; machine classification)
- `evidence_refs` (array; optional): file paths / run ids / step ids
- `requires_action` (bool; default `false`)
- `expires_at` (RFC3339 timestamp; optional)

**Deduplication rule (normative)**:
- Producers SHOULD set `dedupe_key` for error-like notifications to prevent accidental spam (e.g., repeated retries).
- For step failures, the recommended v1 key is:
  - `sha256(event_type + "|" + run_id + "|" + step_execution_id + "|" + error.code).hexdigest()[:16]`
- Consumers MAY suppress notifications with the same `dedupe_key` within the active run, but MUST NOT delete the underlying evidence.

Priority mapping (normative):

- `critical` > `error` > `warn` > `info`

Queues do not reorder; consumers SHOULD display by severity and recency.

### 9.2 Delivery and routing

Routing is intentionally local and file-based.

Minimum delivery surfaces:

- `workflowctl notifications tail` — stream notifications (polls the queue)
- `/project-manager` and `/ticket-manager` interactive shells — display and prompt when `requires_action=true`

A consumer MUST:

1. claim from `notifications/inbox/`
2. display/render it (CLI)
3. if `requires_action=false`:
   - move to `notifications/archive/`
4. if `requires_action=true`:
   - keep in `processing/<consumer_id>/` until the user acks (see §9.4)

### 9.3 Expiry and TTL

- If `expires_at` is omitted, the notification does not expire automatically.
- If `expires_at` is present:
  - consumers MAY drop it quietly only after it is moved to `archive/` (never from `inbox/` without processing)
  - expiry is a UI hint; it does not delete evidence

### 9.4 Acknowledgement and dismissal

Notifications that require action MUST be explicitly acknowledged.

Ack is expressed as a control action:

- `control_actions/inbox/notification_ack_<notification_id>.json`

Fields:

- `control_kind: "notification_ack"`
- `notification_id`
- `actor` (user id or `local_user`)
- optional `note`

On ack:

- the notification is moved to `notifications/archive/`
- the ack envelope is moved to `control_actions/applied/`

