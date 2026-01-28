# Core Infrastructure — Durability Protocol (Atomic Writes + Journals)

- **Doc**: Tech_Plan__Core_Infrastructure/06_Durability_Protocol.md
- **Updated**: 2026-01-26
- **Library**: `workflow_engine.durability`
- **Depends on**: [`00_Foundation.md`](00_Foundation.md), [`03_IDs_and_Time.md`](03_IDs_and_Time.md)
- **Primary responsibility**: Cross-platform durability contract for all file-backed state (atomic replace + WAJ + deterministic recovery).

## 7) Durability protocol

### 7.1 Atomic write protocol (all platforms)

All durable state in this system is file-backed. Every write MUST be atomic.

**Goal**: after a crash/power loss, readers either see the *old complete file* or the *new complete file* — never a partial write.

#### 7.1.1 Normative algorithm

For every durable write to a file `<target_path>`:

1. **Create temp file in the same directory**  
   - `tmp_path = <target_path>.tmp.<ulid>`  
   - Temp file MUST be in the same directory as the target to preserve atomic replace semantics.

2. **Write full content**  
   - Open temp file with flags that avoid partial overwrite patterns (`O_TRUNC` ok because it is a new temp file).
   - Write all bytes.
   - Flush user-space buffers (`f.flush()`).

3. **Durability flush of the temp file**  
   - POSIX: `os.fsync(fd)`  
   - Windows: `os.fsync(fd)` (calls `FlushFileBuffers`)

4. **Atomic replace (publish)**  
   - POSIX: `os.replace(tmp_path, target_path)` (atomic rename/replace)
   - Windows:
     - If `target_path` exists AND `ReplaceFileW` is available:
       - prefer `ReplaceFileW(target_path, tmp_path, backup=NULL, flags=REPLACEFILE_IGNORE_MERGE_ERRORS, ...)`
     - Else:
       - `os.replace(tmp_path, target_path)` (atomic within volume)

5. **Directory durability (best-effort where supported)**  
   - POSIX: `fsync(parent_dir_fd)` is REQUIRED.
   - Windows: directory fsync is not reliably supported; treat as best-effort no-op.

6. **Cleanup**  
   - If any step fails after temp creation, the caller SHOULD attempt to remove `tmp_path` (best-effort).  
   - Readers MUST ignore files matching `*.tmp.*`.

#### 7.1.2 Windows fallback behavior (normative)

Windows implementations MUST behave correctly even if `ReplaceFileW` cannot be used (for example: missing symbol, unexpected error, or `target_path` does not exist).

Fallback order:
1. Try `ReplaceFileW` only when `target_path` already exists.
2. Otherwise (or on failure), use `os.replace`.

If both `ReplaceFileW` and `os.replace` fail, return a structured error `E_ATOMIC_REPLACE_FAILED` including:
- `target_path`, `tmp_path`
- platform info
- underlying OS error code/message

#### 7.1.3 How readers handle leftovers

Readers of WSS documents and queue items MUST:
- ignore `*.tmp.*`
- ignore trailing partial lines in JSONL logs (§8.4)
- treat stray temp files as non-authoritative debris (may be cleaned by `workflowctl recover`)
### 7.2 Write-ahead journals (WAJ) for critical mutations (mandatory)

To strengthen crash recovery on all platforms (and to avoid relying on directory durability on Windows), **critical semantic mutations** MUST be journaled.

**Journal scope**: WAJ is only for *small, high-value transitions*.

- WAJ is **not** for high-volume append-only streams (stdout/stderr, traces). Those belong in the Logs Store.
- WAJ **is** for small semantic transitions that would otherwise be ambiguous after a crash.

Operations that MUST be journaled:

- WSS lifecycle transitions:
  - `run.json.status`, `run.json.ended_at`
  - `steps/<step_execution_id>.json.status`, `ended_at`
  - `ticket.json.status` (and `export.status`)
- Queue moves that change semantic state:
  - `inbox → processing/<consumer_id>`
  - `processing/<consumer_id> → applied|failed|archive`

##### consumer_id format (normative)

`consumer_id` identifies the queue consumer that has claimed an item in `processing/<consumer_id>/`.

Format (v1):
- `consumer_id` MUST be: `<role>.<pid>.<ulid>`
  - `role`: short consumer role identifier (`root`, `pm`, `tm`, `step`, `ui`, `gc`, `doctor`, `recover`, etc.)
  - `pid`: OS process id of the consumer process
  - `ulid`: ULID generated once at consumer start

Staleness detection (v1):
- A `processing/<consumer_id>/` directory is considered **stale** if the lease.json
  is missing or expired AND no file in the directory has mtime within
  `queues.processing_ttl_ms` (default `300000` = 5 minutes).

See [`08_Queues_Notifications_and_Control_Actions.md`](08_Queues_Notifications_and_Control_Actions.md)
§9.0 for the complete staleness definition and reaper responsibilities.

Stale processing directories MUST be re-queued by recovery (`workflowctl recover`), moving items back to `inbox/` with a `warn`-severity `fsck_issue` event.

#### 7.2.1 Journal layout

```text
workspace/journals/
  waj.<ulid>.jsonl                 # append-only journal segments (rotate by size/time)
```

Journal segments are append-only JSONL. Writers MUST use the atomic append discipline described in §8 (flush + fsync at record boundaries).

#### 7.2.2 Journal record schema (v1)

```json
{
  "schema_version": 1,
  "journal_id": "01J...",
  "ts": "2026-01-24T00:00:00Z",
  "op_id": "01J...",
  "state": "prepare|commit|abandoned",

  "kind": "wss_write|queue_move",

  "target_path": "workspace/runs/<run_id>/run.json",
  "tmp_path": "workspace/runs/<run_id>/run.json.tmp.<ulid>",

  "expected_rev": 7,
  "new_content_hash": "sha256:<hex>",

  "queue": {
    "queue_name": "notifications|control_actions",
    "src_path": "notifications/inbox/<id>.json",
    "dst_path": "notifications/processing/<consumer_id>/<id>.json",
    "consumer_id": "tm.12345.01J..."
  }
}
```

Rules:
- For `kind="wss_write"`, `target_path` + `tmp_path` MUST be set, and `queue` MUST be omitted/null.
- For `kind="queue_move"`, `queue.*` MUST be set, and `target_path/tmp_path/expected_rev/new_content_hash` MUST be omitted/null.
- `op_id` is the idempotency key for the journal operation.
- `journal_id` identifies the journal record (unique per line).

#### 7.2.3 Protocol (prepare → commit)

For a journaled operation:

1. Append a `prepare` record and flush+fsync the journal segment.
2. Perform the actual operation (atomic write or atomic rename).
3. Append a `commit` record and flush+fsync the journal segment.

#### 7.2.4 Recovery algorithm (normative)

Recovery runs in two situations:
- root runtime startup (automatic)
- `workflowctl recover` (manual)

Recovery scans journal segments in chronological order and groups records by `op_id`.

For each `op_id` where a `prepare` exists without a `commit`:

##### Case A: `kind="wss_write"`

Let:
- `target_path` be the intended target
- `tmp_path` be the temp file path (may or may not exist)
- `new_content_hash` be the expected hash of the **new** content
- `expected_rev` be the expected current document revision prior to the write

Recovery MUST follow this decision tree (no guessing):

1. **Check if the write already committed in reality**  
   - If `target_path` exists AND `sha256(bytes(target_path)) == new_content_hash`:
     - append a `commit` record (reconciles the journal)
     - best-effort delete `tmp_path` if it exists
     - continue

2. **Attempt to complete using the recorded temp file**  
   - If `tmp_path` exists:
     - Load and validate the current `target_path` document (if present):
       - If the doc contains `rev` and it is NOT equal to `expected_rev`:
         - append `abandoned` record (see below)
         - emit a notification `journal_abandoned` with `op_id`, `target_path`, `expected_rev`, `actual_rev`
         - continue
     - Atomically replace `target_path` with `tmp_path` using §7.1.
     - Verify `sha256(bytes(target_path)) == new_content_hash`.
       - If verification fails: append `abandoned` record + notification (do not retry in a loop).
     - Append `commit` record.
     - continue

3. **Otherwise: cannot complete deterministically**  
   - Append `abandoned` record and emit a notification.

##### Case B: `kind="queue_move"`

Let:
- `src_path` be the source queue file
- `dst_path` be the destination path

Recovery MUST follow this decision tree:

1. If `dst_path` exists:
   - append `commit` record (the move happened)
   - continue

2. Else if `src_path` exists:
   - perform atomic rename `src_path → dst_path` (same filesystem)
   - verify `dst_path` exists
   - append `commit` record
   - continue

3. Else:
   - append `abandoned` record + notification `journal_abandoned` with `op_id`, `src_path`, `dst_path`

#### 7.2.5 What “abandoned” means (normative)

An operation is marked **abandoned** only when recovery cannot safely complete it **without overwriting a newer state** or when verification fails.

Abandoned handling MUST be loud and actionable:
- A notification MUST be written with:
  - `op_id`, `kind`, and paths
  - the reason (`expected_rev_mismatch`, `missing_tmp`, `verification_failed`, `missing_src_and_dst`)
  - a suggested command: `workflowctl recover --op <op_id>` (for inspection) or `workflowctl fsck` (for broader integrity checks)

Abandoned operations MUST NOT be silently ignored.

