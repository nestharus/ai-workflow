# Core Infrastructure — Logs Store (Sharded JSONL)

- **Doc**: Tech_Plan__Core_Infrastructure/07_Logs_Store.md
- **Updated**: 2026-01-29
- **Library**: `workflow_engine.storage.logs`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md), [`03_IDs_and_Time.md`](03_IDs_and_Time.md)
- **Primary responsibility**: Append-only, sharded JSONL logs with integrity features and corruption handling rules.

## 8) Logs Store (sharded JSONL)

### 8.1 Layout
One shard per `(run_id, writer_id)`:
```text
logs/runs/<run_id>/writers/<writer_id>.jsonl
```

Shards are append-only.

### 8.2 Event schema (v1)

Each log line is one JSON object (“event”). Shards are append-only (§8.1).

#### 8.2.1 Required fields

Every event MUST include:

- `schema_version` (int)  
  - Must be `1`.

- `event_type` (string)  
  - Regex: `^[a-z][a-z0-9_]*$`  
  - Event types are enumerated in §8.2.3.

- `ts` (RFC3339 UTC string, ends in `Z`)

- `run_id` (ULID string)

- `writer_id` (string)  
  - Identifies the log writer. For step executions, `writer_id` MUST equal `step_execution_id` (the ULID execution instance, not the semantic `step_id`).

- `seq` (int)  
  - Monotonic per `(run_id, writer_id)` shard, starting at `1`.

**Note**: The `seq` field provides ordering within a writer shard. Do NOT use ULID ordering for event sequencing (see §4.1.2 for ULID monotonicity scope).

- `data` (object)  
  - Event payload. MUST be a JSON object (not an array).

#### 8.2.2 Optional fields (recommended)

- `step_execution_id` (ULID string)  
  - SHOULD be present for all step-related events.
- `ticket_id` (semantic ID)
- `task_id` (semantic ID)
- `step_id` (semantic ID)  
  - Semantic step identifier from plan (e.g., `step-001`).
- `severity` (string enum): `debug|info|warn|error|critical`  
  - If omitted, default is `info`.

- `trace_id`, `span_id` (strings; optional)  
  - For distributed tracing style correlation (local only in v1).

- `prev_hash`, `event_hash` (strings; optional but REQUIRED for new shards; see §8.3)

#### 8.2.3 Event type taxonomy (v1)

The following `event_type` values are **normative** for built-in components.

Run lifecycle:
- `run_started`
- `run_paused`
- `run_resumed`
- `run_completed`
- `run_failed`
- `run_investigating`

Step lifecycle:
- `step_started`
- `step_paused`
- `step_resumed`
- `step_completed`
- `step_failed`

Tool execution:
- `tool_start`
- `tool_stop`
- `tool_output_chunk` (optional; only for small bounded chunks; large output is stored as artifacts)

Gateway / policy:
- `capability_denied`
- `policy_blocked`
- `validation_failed`

WAJ / recovery:
- `journal_prepare`
- `journal_commit`
- `journal_abandoned`
- `journal_recovered`

Queues:
- `queue_published`
- `queue_claimed`
- `queue_requeued`
- `queue_applied`
- `queue_failed`

LLM:
- `net_llm_start`
- `net_llm_stop`

Compatibility note (v1):
- Log readers MUST accept legacy `llm_call_start` / `llm_call_stop` as deprecated aliases for `net_llm_start` / `net_llm_stop` and MUST emit a warning when encountered.
- v2 will drop the `llm_call_*` aliases.

Maintenance:
- `doctor_started`
- `doctor_failed`
- `doctor_ok`
- `fsck_started`
- `fsck_issue`
- `fsck_ok`
- `backup_created` (include `output_path`, `size_bytes`, `repo_uid`)
- `backup_restored` (include `backup_path`, `repo_uid`, `fsck_result`)
- `backup_repo_uid_warning` (repo_uid mismatch detected during restore)

Notes:
- Extensions MAY introduce new event types, but built-in components MUST NOT change the meaning of the above.
- Third-party/experimental event types SHOULD be prefixed with `x_`.

#### 8.2.4 Structured error object (shared contract)

Many events (and most CLI/gateway failures) embed a structured error.

Error object schema (v1):

```json
{
  "error_id": "01J...",
  "code": "E_EXPECTED_REV_MISMATCH",
  "message": "Human-readable summary (single line).",
  "retryable": false,
  "details": {},
  "caused_by": null
}
```

Rules:
- `error_id` MUST be a ULID.
- `code` MUST be one of the codes in §8.2.5 (or `x_...` for experimental).
- `details` MUST be a JSON object and MUST be bounded (no raw multi-MB logs).
- `caused_by` MAY embed a nested error object (for OS/tool errors).

#### 8.2.5 Error code taxonomy (v1)

Core:
- `E_INTERNAL`
- `E_VALIDATION_FAILED`
- `E_SCHEMA_VERSION_UNSUPPORTED`
- `E_NOT_FOUND`
- `E_NOT_ALLOWED`
- `E_CAPABILITY_DENIED`
- `E_POLICY_BLOCKED`
- `E_WORKFLOW_AMBIGUOUS`
- `E_LOCK_FAILED`

WSS / durability:
- `E_OWNERSHIP_VIOLATION`
- `E_EXPECTED_REV_MISMATCH`
- `E_ATOMIC_REPLACE_FAILED`
- `E_JOURNAL_ABANDONED`
- `E_ULID_COLLISION`

Sandbox / tools:
- `E_SANDBOX_CREATE_FAILED`
- `E_SANDBOX_RUN_FAILED`
- `E_TOOL_FAILED`
- `E_TOOL_TIMEOUT`
- `E_SPARSE_DERIVATION_FAILED`

Models / routing:
- `E_MODEL_ROUTE_NOT_FOUND`
- `E_NET_LLM_FAILED`

Compatibility note (v1):
- When reading legacy logs, `E_LLM_CALL_FAILED` MUST be treated as a deprecated alias for `E_NET_LLM_FAILED` and MUST emit a warning when encountered.
- v2 will drop the `E_LLM_CALL_FAILED` alias.

Dependencies:
- `E_DEPENDENCY_MISSING`
- `E_UNSUPPORTED_PLATFORM`

Backup / restore:
- `E_BACKUP_FAILED`: Backup creation failed (file I/O, permissions, or ZIP error)
- `E_RESTORE_FAILED`: Restore failed (invalid ZIP, extraction error, or fsck failure)
- `E_REPO_UID_MISMATCH`: Backup repo_uid doesn't match current repo_uid

#### 8.2.6 Example events

`run_started`:

```json
{
  "schema_version": 1,
  "event_type": "run_started",
  "ts": "2026-01-24T00:00:00Z",
  "run_id": "01J...",
  "writer_id": "root",
  "seq": 1,
  "severity": "info",
  "data": {
    "workflow_id": "task_decompose_v1",
    "repo_uid": "abcd1234ef567890"
  }
}
```

`tool_stop`:

```json
{
  "schema_version": 1,
  "event_type": "tool_stop",
  "ts": "2026-01-24T00:00:10Z",
  "run_id": "01J...",
  "writer_id": "01J...step",
  "seq": 42,
  "severity": "info",
  "step_execution_id": "01J...step",
  "data": {
    "tool": "jj",
    "argv": ["jj","status","--color","never"],
    "exit_code": 0,
    "duration_ms": 812
  }
}
```

`validation_failed`:

```json
{
  "schema_version": 1,
  "event_type": "validation_failed",
  "ts": "2026-01-24T00:00:12Z",
  "run_id": "01J...",
  "writer_id": "root",
  "seq": 8,
  "severity": "error",
  "data": {
    "error": {
      "error_id": "01J...",
      "code": "E_VALIDATION_FAILED",
      "message": "Workflow schema validation failed.",
      "retryable": false,
      "details": { "path": "steps[2].depends_on[0]", "reason": "unknown step_id" },
      "caused_by": null
    }
  }
}
```
### 8.3 Integrity chain (trust feature; mandatory for new shards)

Each shard maintains a rolling hash chain:

- `prev_hash`: previous event hash (or `null` for first event)
- `event_hash`: `sha256(canonical_json_without_event_hash + prev_hash)`

This is used to detect:
- truncated last lines
- corruption
- accidental overwrites

### 8.4 Partial-write handling

Readers MUST:
- ignore a trailing partial line (non-JSON)
- treat `seq` gaps as corruption and report via `workflowctl fsck`

### 8.5 Log append and read rules (corruption handling) (normative)

**Writer rules**:
- Each writer shard (`writers/<writer_id>.jsonl`) MUST emit a strictly increasing `seq` starting at `1`.
- A writer MUST NOT reuse a `(writer_id, seq)` pair.

**Reader rules** (tailing or batch):
- Readers MUST ignore a **trailing partial line** (e.g., file ends without newline or the last line fails JSON parse).
- If a non-trailing line is malformed JSON:
  - the reader MUST skip it,
  - and MUST emit a `warn`-severity `fsck_issue` (or equivalent) event referencing:
    - `run_id`, `writer_id`, and the byte offset / line number (best-effort).
- If the reader detects a `seq` gap (e.g., sees `seq=10` after `seq=8` with no `seq=9`):
  - the reader MUST fail loudly (do not silently continue),
  - using `E_INTERNAL` with `details.reason="LOG_SEQ_GAP"`,
  - and MUST recommend running `workflowctl fsck` / `workflowctl recover`.
