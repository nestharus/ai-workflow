# Core Infrastructure — Queues (Notifications + Control Actions)

* **Doc**: Tech_Plan__Core_Infrastructure/08_Queues_Notifications_and_Control_Actions.md
* **Updated**: 2026-01-26
* **Library**: `workflow_engine.storage.queues`
* **Depends on**: [`00_Foundation.md`](00_Foundation.md), [`03_IDs_and_Time.md`](03_IDs_and_Time.md), [`06_Durability_Protocol.md`](06_Durability_Protocol.md)
* **Primary responsibility**: Durable, local-first maildir-like queues for user notifications and control/action envelopes.

## 9) Notifications Store and Control Actions Queue (maildir-like)

Two durable queues exist:

* `notifications/` — messages intended for the user (or UI surface)
* `control_actions/` — user/system control envelopes (pause/resume/ack/decisions)

Both queues use the same hardened pattern:

* atomic publish (`tmp/` → `inbox/`)
* atomic claim (`inbox/` → `processing/<consumer_id>/`)
* bounded requeue on crash (processing TTL)
* idempotency via `notification_id` / `request_id`

Queue directories:

```text
notifications/{tmp,inbox,processing/<consumer_id>,archive}
control_actions/{tmp,inbox,processing/<consumer_id>,ack,applied,failed,archive}
```

Queue moves that change semantic state (`inbox→processing`, `processing→applied/failed`)
are covered by write-ahead journals (§7.2).

### 9.0 Consumer identity (`consumer_id`) (normative)

Queue claim semantics require a stable per-consumer directory under `processing/`.

**Definition**: `consumer_id` identifies a single consumer process instance.

**Format (v1)**:
`<role>.<pid>.<ulid>`

* `role`: short string enum (recommended):
  * `root` (root runtime)
  * `pm` (Project Manager session)
  * `tm` (Ticket Manager session)
  * `step` (step execution process consuming its control actions)
  * `ui` (any external UI wrapper)
  * `gc`, `doctor`, `recover` (maintenance commands)
* `pid`: OS process id as decimal
* `ulid`: generated once at process start (`new_ulid()`)

Example:
* `tm.48210.01J3ZQK9X5J9H6R8V2S4J2E9P3`

**Allocation rule**:
* A process that consumes a queue MUST generate exactly one `consumer_id` at
  startup and reuse it for the lifetime of the process.

**PID reuse after reboot**:
* PID reuse is not a collision because the ULID component differs.
* Old processing directories from previous process instances are cleaned by
  the lease TTL reaper.

**ULID generation failure**:
* If ULID generation fails, the process MUST fail loudly with `E_INTERNAL`
  ("cannot generate consumer_id") and refuse to consume queues.
* No fallback or retry for ULID generation itself.

**Collision detection (defensive)**:
On consumer startup:
1. Attempt to create `processing/<consumer_id>/` directory exclusively
   (atomic mkdir).
2. If directory already exists:
   * Generate a new ULID and retry (up to 3 attempts).
   * If still exists after 3 retries → fail loudly with `E_ULID_COLLISION`.

**Stale consumer cleanup**:
* Reaping is performed by the root runtime (or `workflowctl recover`).
* A processing directory is stale if:
  * `lease.json` is missing or expired (`last_heartbeat_ts` older than
    `queues.lease_ttl_ms`), AND
  * no file in the directory has `mtime` within `queues.processing_ttl_ms`
    (default `300000`)
* Reaper action:
  1. Move all queue items back to `inbox/` (atomic rename per file).
  2. Record each move in WAJ (§7.2).
  3. Delete the stale `processing/<consumer_id>/` directory.

Empty processing directories MAY be removed by the reaper.

### 9.1 Notification schema and priority

A notification is a JSON document with required fields (Core §5.2) plus:

* `notification_id` (ULID; required)
* `dedupe_key` (string; optional) — deterministic key for suppressing duplicate
  notifications
* `severity` (enum; required): `info|warn|error|critical`
* `title` (string; required)
* `message` (string; required)
* `kind` (string; optional; machine classification)
* `evidence_refs` (array; optional): file paths / run ids / step ids
* `requires_action` (bool; default `false`)
* `expires_at` (RFC3339 timestamp; optional)

**Deduplication rule (normative)**:

Deduplication operates at two distinct levels:

1. **Persistence level**: All notifications MUST be written to `notifications/inbox/`
   atomically. No deduplication occurs at the storage layer.

2. **Display level**: CLI consumers MAY suppress notifications with the same
   `(dedupe_key, severity)` tuple within `notification_dedupe_window_ms` of the
   first notification's `created_at` timestamp. This suppression is UI-only
   and does not affect the durable queue.

**Producer recommendations**:
* Producers SHOULD set `dedupe_key` for error-like notifications to prevent
  accidental spam (e.g., repeated retries).
* For step failures, the recommended v1 key is:
  * `sha256(event_type + "|" + run_id + "|" + step_execution_id + "|" +
    error.code).hexdigest()\[:16\]`

**Consumer behavior**:
* Consumers MAY suppress display of duplicate notifications based on
  `(dedupe_key, severity)` within `notification_dedupe_window_ms`.
* Duplicates are identified by comparing the `created_at` timestamp of the
  first stored notification with subsequent notifications.
* Suppression at display level MUST NOT delete or move notifications from the
  durable queue.

**Configuration**: `notification_dedupe_window_ms` is part of the queue
configuration managed by the Configuration System (see §11.4.3).

Priority mapping (normative):

* `critical` > `error` > `warn` > `info`

Queues do not reorder; consumers SHOULD display by severity and recency.

### 9.2 Delivery and routing

Routing is intentionally local and file-based.

Minimum delivery surfaces:

* `workflowctl notifications tail` — stream notifications (polls the queue)
* `/project-manager` and `/ticket-manager` interactive shells — display and prompt
  when `requires_action=true`

A consumer MUST:

1. claim from `notifications/inbox/`
2. display/render it (CLI)
3. if `requires_action=false`:
   * move to `notifications/archive/`
4. if `requires_action=true`:
   * keep in `processing/<consumer_id>/` until the user acks (see §9.4)

### 9.3 Expiry and TTL

* If `expires_at` is omitted, the notification does not expire automatically.
* If `expires_at` is present:
  * consumers MAY drop it quietly only after it is moved to `archive/` (never from
    `inbox/` without processing)
  * expiry is a UI hint; it does not delete evidence

### 9.4 Acknowledgement and dismissal

Notifications that require action MUST be explicitly acknowledged.

Ack is expressed as a control action:

* `control_actions/inbox/notification_ack_<notification_id>.json`

Fields:

* `control_kind: "notification_ack"`
* `notification_id`
* `actor` (user id or `local_user`)
* optional `note`

On ack:

* the notification is moved to `notifications/archive/`
* the ack envelope is moved to `control_actions/applied/`

### 9.5 Deviation approval control kinds (normative)

Deviation-related control actions follow the maildir lifecycle for `control_actions/`.

Permitted deviation approval `control_kind` values:
* `deviation_approval_request`
* `deviation_approval`
* `deviation_extend`

#### 9.5.1 deviation_approval_request

**Envelope location**: `control_actions/inbox/deviation_approval_request_<deviation_id>.json`

**Required fields**:
* `control_kind`: `"deviation_approval_request"`
* `deviation_id` (string; ULID)
* `ticket_id` (string)
* `task_id` (string)
* `step_id` (string)
* `capability` (string)
* `approval_timeout_ms` (integer)
* `deadline` (RFC3339 timestamp)
* `created_at` (RFC3339 timestamp; optional, defaults to envelope creation time)

**Lifecycle moves**:
1. `inbox/` → `processing/<consumer_id>/` (claim)
2. On resolution (via `deviation_approval` or timeout):
   * `processing/<consumer_id>/` → `ack/` (if action is consumed)
   * `processing/<consumer_id>/` → `failed/` (if timeout without response)

**Idempotency**: `deviation_id` serves as the idempotency key. Consumers MUST reject
processing if a request envelope with the same `deviation_id` has already been resolved
(`ack/` or `failed/`).

#### 9.5.2 deviation_approval

**Envelope location**: `control_actions/inbox/deviation_approval_<deviation_id>.json`

**Required fields**:
* `control_kind`: `"deviation_approval"`
* `deviation_id` (string; ULID)
* `decision` (enum: `"approve"| "deny"`)
* `actor` (string; user id)
* `created_at` (RFC3339 timestamp; optional)
* `note` (string; optional)

**Lifecycle moves**:
1. `inbox/` → `processing/<consumer_id>/` (claim)
2. On processing:
   * If matching `deviation_approval_request` exists and is unresolved:
     * Update deviation record with `approved_by`
     * Move request envelope to `ack/`
   * If request is already resolved or does not exist:
     * Move to `failed/` with error annotation
3. After successful processing:
   * `processing/<consumer_id>/` → `applied/`

**Maildir consistency**: Both the request and approval envelopes MUST be atomically
moved. The runner MUST check both `ack/` and `applied/` when polling for approval status.

#### 9.5.3 deviation_extend

**Envelope location**: `control_actions/inbox/deviation_extend_<deviation_id>.json`

**Required fields**:
* `control_kind`: `"deviation_extend"`
* `deviation_id` (string; ULID)
* `extend_ms` (integer)
* `note` (string)
* `created_at` (RFC3339 timestamp; optional)

**Lifecycle moves**:
1. `inbox/` → `processing/<consumer_id>/` (claim)
2. On processing:
   * Validate `extend_ms` against `max_approval_extensions` config
   * Update deviation record with new `deadline` and extension entry
   * If validation fails or extension limit exceeded:
     * Move to `failed/` with error annotation
3. After successful processing:
   * `processing/<consumer_id>/` → `applied/`

**Constraint**: Maximum of 3 extensions per deviation (configurable). Consumers MUST
track `extension_count` in the deviation record and reject extension attempts beyond
the limit.

#### 9.5.4 deviation_extend_response

**Purpose**: Consumer-generated response to a `deviation_extend` control action. This differs
from the standard lifecycle flow; it is written directly to the requester's inbox to
communicate rejection outcomes, particularly in Phase C scenarios (post-stop).

**Envelope location**: `control_actions/inbox/deviation_extend_response_<deviation_id>.json`

**Required fields**:
* `control_kind`: `"deviation_extend_response"`
* `deviation_id` (string; ULID)
* `status` (enum: `"success" | "error"`)
* `error` (string; required when `status: "error"`)
* `rejected_at` (RFC3339 timestamp; required when `status: "error"`)
* `run_state` (string; required when `status: "error"`; actual state of the run at
  rejection time)
* `instructions` (string; optional; user-facing guidance for next steps)

**Lifecycle moves**:
1. Written directly to `inbox/` by the consumer (not claimed via processing)
2. Requester reads from `inbox/` to retrieve response
3. After processing response:
   * Move to `ack/` (if response is consumed and acknowledged)

**Rejection flow cross-reference**:
See [`Lib__Step_Execution.md`](../../project_ticket_system/Lib__Step_Execution.md) Phase C (§3.4.4)
for the complete rejection handling model:
* **Phase A (pre-deadline)**: Extension is accepted; `deviation_extend` moves to
  `applied/`
* **Phase B (post-deadline, pre-stop)**: Extension is rejected; `deviation_extend`
  moves to `applied/` with `late: true`, and `deviation_extension_rejected`
  notification is emitted
* **Phase C (post-stop)**: Extension is rejected; `deviation_extend_response` is written
  with `status: "error"`, `run_state: "stopped"`, and instructions to use
  `workflowctl run resume` instead

**Idempotency**: `deviation_id` + `rejected_at` serves as the idempotency key for
response envelopes. Consumers MAY discard duplicate responses seen from their inbox.
