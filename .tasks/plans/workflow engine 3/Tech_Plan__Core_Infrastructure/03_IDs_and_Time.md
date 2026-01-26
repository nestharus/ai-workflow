# Core Infrastructure — IDs and Time

- **Doc**: Tech_Plan__Core_Infrastructure/03_IDs_and_Time.md
- **Updated**: 2026-01-26
- **Library**: `workflow_engine.core.ids`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md)
- **Primary responsibility**: Define ID classes, ULID generation requirements, and persisted timestamp formats.

## 4) IDs and time

### 4.1 IDs (format + generation)

This system uses **two ID families**:

1. **Semantic IDs** (human-meaningful strings) — see Terminology §0.1:
   - `project_id`, `ticket_id`, `task_id`, `step_id`
   - `workflow_id`, `agent_id`

2. **Generated IDs (ULID)** for durable, globally unique identifiers:
   - `run_id`, `step_execution_id`, `request_id`, `notification_id`
   - `writer_id`, `bundle_id`, `conclusion_id`, `journal_id`, `op_id`, `sandbox_id`

Only the **generated ID family** MUST be ULIDs.

#### 4.1.1 ULID string format (normative)

- Encoding: Crockford Base32
- Length: 26 chars
- Sort order: lexicographic order matches time order (for monotonic generators)
- Payload:
  - 48-bit timestamp (milliseconds since Unix epoch, UTC)
  - 80-bit randomness

ULIDs are **filename-safe** on all supported platforms.

#### 4.1.2 Monotonic ULID generation (normative)

**Goal**: within a single OS process, successive ULID generations MUST be strictly increasing in lexicographic order, even if multiple IDs are generated in the same millisecond.

**Scope**: monotonicity is **per-process only**. Cross-process ordering is best-effort (timestamp-based) and MUST NOT be treated as a total order.

**Implementation requirement**:
- Implement ULID generation in-repo (standard library only).
- File/module name suggestion: `workflow_engine/core/ids/ulid.py`
- API (normative):
  - `new_ulid() -> str`  (thread-safe, monotonic per process)

**Algorithm (normative)**:

Maintain process-global state under a mutex:
- `last_ts_ms: int`
- `last_rand_80: int` (0 ≤ value < 2^80)

On each call:

1. Read `ts_ms = floor(time.time() * 1000)`.
2. If `ts_ms > last_ts_ms`:
   - set `last_ts_ms = ts_ms`
   - set `last_rand_80 = int.from_bytes(os.urandom(10), "big")`
3. Else (same millisecond or clock moved backwards):
   - set `ts_ms = last_ts_ms`  (monotonic clamp)
   - increment: `last_rand_80 = last_rand_80 + 1`
   - if `last_rand_80 == 2^80` (overflow):
     - wait until the system clock reaches `last_ts_ms + 1` ms
     - set `last_ts_ms = last_ts_ms + 1`
     - set `last_rand_80 = int.from_bytes(os.urandom(10), "big")`

4. Encode `(ts_ms, last_rand_80)` into Crockford Base32 ULID string.

**Clock-backwards note**: clamping is required; ULIDs MUST NOT go backwards due to NTP adjustments.

#### 4.1.3 Collision handling for file-backed queues (normative)

ULID collision probability is negligible, but file-backed queues MUST still be correct.

For producers writing queue items:
- The filename MUST be `<ulid>.json` (no extra timestamp prefixes).
- If `inbox/<ulid>.json` already exists at publish time:
  1. generate a new ULID and retry up to 3 times
  2. if it still exists, fail loudly with `E_ULID_COLLISION` and include:
     - target directory
     - colliding filename(s)

Consumers MUST treat filenames as opaque identifiers (ordering is a convenience only).
### 4.2 Timestamps

- All persisted timestamps are RFC3339 UTC strings (`...Z`).
- Filenames MUST NOT contain colons (Windows); ULIDs are used for filenames.

