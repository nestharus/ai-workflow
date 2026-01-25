# Tech Plan: Core Infrastructure & Data Model (Restructured)

- **Doc**: Tech_Plan__Core_Infrastructure.md
- **Updated**: 2026-01-24
- **Component**: Core / Storage / Protocol
- **Primary responsibility**: Durable truth (WSS + Logs + Queues) and minimal runtime primitives with **high trust** and **low friction**.

## 0) What changed vs prior drafts (risk reductions)

This revision closes previously identified gaps by adding **fully-specified** policies for:

- **Cross-platform durability** (including Windows-native recovery semantics) via:
  - atomic writes (tier-aware)
  - write-ahead journals for critical mutations
  - integrity checks (`fsck`) and deterministic recovery (`recover`)
- **Configuration system**:
  - a single config format (TOML)
  - explicit precedence
  - schema validation + redacted config logging
- **Secrets / sensitive data**:
  - OS keychain-backed secrets store (Keyring)
  - mandatory redaction for any outbound data (LLM calls + exports)
  - export scrubber (shareable bundles without secrets)
- **Dependency management**:
  - `doctor` + `bootstrap` flows
  - explicit `jj` feature/version requirements
- **Reproducibility (without heavy services)**:
  - environment capture for every sandbox run
  - tool fingerprinting and durable tool conclusions keyed by fingerprints

No open responsibilities remain in this document set: every responsibility implied by the system goals is assigned to a component and has durable evidence outputs.

## 0.1) Terminology (canonical)

This document set uses the following canonical terms. New specs and code SHOULD reuse these names to avoid drift.

### Core planning/execution hierarchy
- **Project**: a collection of related tickets under a shared baseline.
- **Ticket**: one unit of work. **Canonical mapping: Ticket ⇄ Patch-Stream stack (PGS/jj)**.
- **Task**: a user-provided input inside a ticket (often “do X”), decomposed into steps.
- **Step (plan step)**: a planned unit of work within a task. `step_id` is the *definition ID* (stable within a task).
- **Run**: a runtime execution group (`run_id`) that groups one or more step executions.
- **Step execution**: the runtime instance of executing a step (`step_execution_id`, `writer_id`, log shard). A step execution is owned by one OS process.

### Patch-Stream terminology
- **Patch-Stream**: the *product-level* development model: tickets are patch stacks; steps produce patches; integration is rebasing stacks.
- **PGS (Patch Graph Store)**: the *storage interface* that implements Patch-Stream. Default backend: **jj**.
- **Ticket stack / patch stack**: the PGS/jj change stack for a ticket (tracked by a bookmark).
- **Patch**: an atomic change appended to a ticket stack (implemented as a jj change).

### Evidence and control
- **WSS (Workspace State Store)**: durable documents + artifacts under the runtime root.
- **Logs Store**: append-only sharded JSONL logs; one shard per step writer.
- **Queues**: filesystem maildir-like queues for notifications and control actions.
- **Evidence**: the durable truth used for debugging and recovery = **WSS + Logs + PGS**.

### “Flow” vs “Workflow”
- **Flow**: a user-facing responsibility / journey (documented in *Core Flows*). Flows are stable.
- **Workflow**: a file-defined automation that implements part of a flow (decomposition, validation, repair). Workflows are user-overridable.

### Sandbox vs hydration
- **Virtual hydration**: reconstruct file content at a given revision without checking out a working copy.
- **Sandbox**: a disposable, materialized environment used to run tools (lint/tests/build/search). In this system, sandboxes are implemented as **jj workspaces**.

### Workspace naming (avoid overload)
The word “workspace” is overloaded in tools and in English. This spec set uses these rules:

- **WSS root directory**: the directory named `workspace/` under the runtime root. Always refer to this concept as **WSS** or **WSS root**, never “workspace” unqualified.
- **jj workspace**: a Jujutsu working copy created by `jj workspace add`. Always refer to as **jj workspace**.
- **Sandbox**: an ephemeral jj workspace created under `~/.workflow/repos/<repo_uid>/sandboxes/...` for tool execution.

### ID classes (semantic vs generated)

**Semantic IDs (human-meaningful strings)**:
- `project_id`, `ticket_id`, `task_id`, `step_id`
- `workflow_id` (workflow definition ID, e.g. `task_decompose_v1`)
- `agent_id` (agent definition ID, e.g. `approval_agent_v1`)

Semantic IDs MUST be filename-safe (`[A-Za-z0-9._-]`) and MUST NOT assume global uniqueness unless explicitly scoped (e.g., `step_id` is scoped to its workflow/task).

**Generated IDs (ULID)**:
- `run_id`, `step_execution_id`, `request_id`, `notification_id`
- `writer_id`, `bundle_id`, `conclusion_id`, `journal_id`, `op_id`, `sandbox_id`

Generated IDs are always machine-generated and globally unique with extremely high probability.

**Derived IDs**:
- `repo_uid` (derived once, then persisted in `repo.json`)

### “Agent” terminology

- **Agent definition (prompt)**: a markdown file used as a prompt template, addressed by `agent_id`.
- **Agent step**: a workflow step with `kind: agent` that results in a step execution process running an agent loop.
- **Model invocation / LLM call**: a single call to a model provider API. In this system, LLM calls MUST be executed via a cancellable subprocess boundary (Monitoring §3.3).

### “Patch” vs “jj change”
- In this spec set, **patch** refers to the logical change unit created by a step.
- In `jj`, the concrete unit is a **change** with a `change_id`. When referencing `jj` outputs, use `change_id` / `commit_id` precisely.
## 1) Product priorities and non-negotiable invariants (locked)

### 1.1 Product priorities (decision order)

1. **Trust**
   - durability across crash/power loss (within platform limits)
   - correctness and auditability (ID-driven evidence)
   - privacy and secrets safety (no accidental exfiltration)
2. **Friction**
   - no database service, no daemon requirement
   - minimal external installs (auto-bootstrap where possible)
   - workflows are file-based and editable
3. **Performance**
   - optimize where cheap (batch hydration, sparse sandboxes)
   - never at the cost of trust or silent failure

### 1.2 Global invariants

These apply to every component and flow unless an explicit exception is documented here.

1. **Local-first operation**
   - The runtime is local-only (single machine).
   - Network is **optional** and only used for model providers when enabled (see §12).
2. **Durable truth**
   - **WSS** documents and artifacts
   - **Logs Store** (sharded JSONL)
   - **PGS** (jj-backed patch stacks)
3. **Step logging always on**
   - step enter/exit + key events are mandatory
   - dynamic tracing is optional and enabled via durable override
4. **Flat orchestration**
   - the **root runtime** owns all step/agent OS processes (no step spawns steps directly)
5. **Mandatory PAUSE**
   - pause requests and acknowledgements are durable and auditable
6. **No silent termination**
   - no fixed “max iteration” caps as termination criteria
   - stop conditions must be **evidence-based** (progress/novelty/oscillation) with explicit give-up records
7. **User-defined workflows are first-class**
   - workflows are file-defined, schema-validated, capability-gated, and produce durable evidence

## 2) Runtime root layout (durability boundary)

All runtime artifacts live under a single runtime root:

```text
~/.workflow/
  config.toml                       # user-global config
  tools/                            # optional auto-bootstrapped tools (jj, etc.)
  agents/                           # user-global agent prompts (see Configuration & Onboarding)
  repos/<repo_uid>/
    repo.json
    workspace/                      # WSS (durable docs + artifacts)
      config.toml                   # repo-machine-local overrides (highest non-CLI)
      journals/                     # write-ahead journals for critical mutations
      projects/
      tickets/
      runs/
      conclusions/
      trace_overrides/
      workflows/                    # WSS-scoped workflows (optional)
    agents/                         # repo machine-local agent prompts
    logs/                           # Logs Store (durable, sharded JSONL)
    notifications/                  # Notifications queue (durable)
    control_actions/                # Control actions queue (durable)
    sandboxes/                      # ephemeral (disposable)
    caches/                         # disposable caches
    vcs/                            # optional jj sidecar mode
    locks/                          # cross-process locks
```

Note: Skills are deployed into CLI-specific locations (e.g., `~/.claude/skills/`), not into `~/.workflow/`. See Configuration & Onboarding §3.

This root is the durability boundary. The repository working tree is **not**.

**Project-level overrides** (optional, committed): See **Tech_Plan__Configuration_&_Onboarding.md §1.1** for the `<repo>/.workflow/` structure.

### 2.1 Platform tiers (durability + sandbox expectations)

| Tier | Environment | Durability contract | Sandbox default |
|---|---|---|---|
| **T1** | Linux (native) | Full POSIX (file + directory fsync) + journal recovery | jj workspaces + sparse patterns |
| **T1** | WSL2 with repo on Linux filesystem (ext4-in-VHD) | Same as Linux for files under ext4 | jj workspaces + sparse patterns |
| **T2** | macOS (APFS) | POSIX-like; atomic rename; directory fsync supported; journal recovery | jj workspaces + sparse patterns |
| **T3** | Windows native | File flush supported; directory durability differs; recovery relies on journals | jj workspaces + sparse patterns (copy-on-demand) |

Windows atomic replacement should prefer `ReplaceFile` where available (and the replacement stays on the same volume).
- ReplaceFile docs: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilea
- FlushFileBuffers docs: https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers

WSL filesystem guidance (performance + correctness): https://learn.microsoft.com/en-us/windows/wsl/filesystems

## 3) Identity: `repo_uid` (stable per repo per machine)

`repo_uid` identifies “this repo on this machine”. It is used to locate the repo binding directory under the runtime root.

### 3.1 Derivation (first init only; normative)

Default derivation:

`repo_uid = sha256(canonical_repo_root_path + "\n" + git_remote_url_or_empty).hexdigest()[:16]`

Where:

**`canonical_repo_root_path`** (string):
- Compute `repo_root` via `git rev-parse --show-toplevel`.
- Convert to an absolute path.
- Normalize:
  - resolve `..` / `.` segments
  - resolve symlinks when the OS provides a stable realpath (best-effort; do not fail if resolution fails)
  - on Windows: normalize drive letter to uppercase and use `/` as separator in the canonical string
  - remove any trailing slash

**`git_remote_url_or_empty`** (string):
- If `origin` exists: `git remote get-url origin`
- Otherwise: empty string
- Normalize by stripping surrounding whitespace.

### 3.2 Persistence rule (authoritative after creation)

- On `workflowctl init`, the derived `repo_uid` is written to `~/.workflow/repos/<repo_uid>/repo.json`.
- After `repo.json` exists, its stored `repo_uid` is authoritative.
- If the git remote changes later, DO NOT change `repo_uid` automatically (avoid orphaning state). A manual migration tool may be added later.
### 3.3 Collision handling (normative)

`repo_uid` collisions are extremely unlikely, but the runtime MUST handle them deterministically.

On `workflowctl init`:

1. Derive the candidate `repo_uid` per §3.1.
2. If `~/.workflow/repos/<repo_uid>/repo.json` does not exist → use it.
3. If it exists:
   - Load the existing `repo.json`.
   - If `repo.json.repo_root` matches the discovered `repo_root` (after the same canonicalization) → reuse it.
   - Otherwise, a collision (or user copy) has occurred.

Collision resolution rule (v1):
- Append a counter suffix: `<repo_uid>-<n>` where `n` starts at `1` and increments until a free directory is found.
- The final `repo_uid` MUST be written to the new `repo.json` and is authoritative thereafter.

### 3.4 Handling manual edits to `repo.json` (normative)

`repo.json` is authoritative after creation (§3.2), but manual edits may orphan state.

If the runtime detects that `repo.json.repo_uid` does not match its directory name, it MUST fail loudly with:
- error code: `E_VALIDATION_FAILED`
- details: `path`, `expected_repo_uid`, `actual_repo_uid`

The error message MUST instruct the user to either:
- restore `repo.json` from version control / backups, or
- re-run `workflowctl init` (which creates a new binding directory).
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

## 5) Workspace State Store (WSS)

WSS is the durable hierarchical document store for mutable workflow state and artifacts that are not safely re-derivable.

### 5.1 WSS layout (authoritative)

```text
workspace/
  config.toml
  journals/
  index.json                         # derived, optional
  workflows/                         # WSS-scoped workflows (optional, YAML)
  projects/<project_id>/
    project.json
    docs/
    artifacts/
  tickets/<ticket_id>/
    ticket.json
    docs/
    tasks/<task_id>/
      task.json
      input.md
      steps/                         # step definitions (durable plan)
      deviations/
      evaluation/
    rebase/
      conflicts/
  runs/<run_id>/
    run.json
    steps/<step_execution_id>.json
    artifacts/
      env/                           # env capture, tool versions, fingerprints
      sandbox/                       # lint/test/build outputs (durable)
      investigation/                 # bounded evidence bundles
      scripts/                       # registered scripts (hash-addressed)
  conclusions/
    tools/<tool_fingerprint>/
    perf/<step_signature>/
  trace_overrides/
    overrides.json
```

### 5.2 Required fields for every durable JSON document

Every durable JSON document MUST include:

- `schema_version: int`
- stable ID field(s) (`ticket_id`, `run_id`, etc.)
- `created_at`, `updated_at`
- `rev: int` (monotonic document revision; starts at 1)
- ownership metadata when relevant:
  - `owned_by` (component role)
  - `writer_id` (if step-owned)

### 5.3 JSON Merge Patch (RFC 7396) as the only update mechanism

All updates to JSON docs use **JSON Merge Patch (RFC 7396)**:
- Patch root MUST be a JSON object; otherwise reject.
- Arrays are treated as scalars (replace entirely) → avoid arrays in multi-writer docs.
- `null` in a patch indicates deletion and MUST NOT be used as a business value.

RFC 7396: https://datatracker.ietf.org/doc/html/rfc7396

## 6) Multi-writer correctness (ownership + concurrency)

### 6.1 Ownership map (enforced at WSS helper layer)

| Document | Owner | Rationale |
|---|---|---|
| `workspace/runs/<run_id>/run.json` | Root runtime | lifecycle + grouping + routing |
| `workspace/runs/<run_id>/steps/<step_execution_id>.json` | Step process | step status/metrics and tool PID set |
| `workspace/projects/**` | Project Manager session | planning + import |
| `workspace/tickets/**` | Ticket Manager session | planning + ticket lifecycle |
| `workspace/index.json` | Root runtime | derived index |
| `workspace/conclusions/**` | Root runtime (investigator role) | promotion requires global gating |

Ownership violations MUST fail loudly (structured error), without retries.

### 6.2 Optimistic concurrency (`expected_rev`) and `rev` rules

For every JSON document write:
- the writer loads current doc
- validates ownership
- validates schema_version (must be <= supported)
- validates `expected_rev` when required
- applies merge patch
- increments `rev` by 1
- writes atomically

**When `expected_rev` is mandatory**:
- any doc with multiple plausible writers or sessions:
  - `ticket.json` lifecycle and metadata
  - `project.json` lifecycle fields
  - `run.json` lifecycle fields
  - derived indexes (`index.json`)
  - workflow registry overlays (if stored in WSS)

**Mismatch behavior**:
- fail once with a structured error containing:
  - `path`
  - `expected_rev`
  - `actual_rev`
  - `last_updated_at`
- no automatic retries
- notify user only if manual action is required

### 6.3 Cross-process locks (when correctness requires serialization)

Some operations must not interleave across processes:

| Operation | Lock | Scope |
|---|---|---|
| Export to the same target branch/ref | `locks/branch.<name>.lock` | repo_uid |
| Mutating the same ticket stack | `locks/ticket.<ticket_id>.lock` | repo_uid |
| Mutating a task’s decomposition artifacts (task.json, step_plan.yaml, candidates, deviations) | `locks/task.<ticket_id>.<task_id>.lock` | repo_uid |
| GC / compaction | `locks/gc.lock` | repo_uid |

**Branch lock naming (normative)**:
- Branch/ref names may include `/` and other characters that are not filename-safe.
- For `locks/branch.<name>.lock`, `<name>` MUST be:
  - `sha256(branch_or_ref_string).hexdigest()[:16]`
- The lock file body MUST include the original `branch_or_ref_string` for diagnostics.

Lock implementation:
- cross-platform lockfile using atomic create (`O_EXCL`) + process id + start time in file body
- stale lock reaping only via explicit `workflowctl recover-locks` (loud)

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
- `consumer_id` MUST be: `<pid>.<ulid>`
  - `pid`: OS process id of the consumer process
  - `ulid`: ULID generated once at consumer start

Staleness detection (v1):
- A `processing/<consumer_id>/` directory is considered **stale** if:
  - `pid` is not running (best-effort), OR
  - the directory’s newest mtime is older than `processing_stale_after_ms` (default `900000` = 15 minutes)

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
  - Identifies the log writer. For step executions, `writer_id` SHOULD equal `step_execution_id`.

- `seq` (int)  
  - Monotonic per `(run_id, writer_id)` shard, starting at `1`.

- `data` (object)  
  - Event payload. MUST be a JSON object (not an array).

#### 8.2.2 Optional fields (recommended)

- `step_execution_id` (ULID string)
- `ticket_id`, `task_id`, `step_id` (semantic IDs)
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
- `llm_call_start`
- `llm_call_stop`

Maintenance:
- `doctor_started`
- `doctor_failed`
- `doctor_ok`
- `fsck_started`
- `fsck_issue`
- `fsck_ok`

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
- `WORKFLOW_AMBIGUOUS`
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
- `E_LLM_CALL_FAILED`

Dependencies:
- `E_DEPENDENCY_MISSING`
- `E_UNSUPPORTED_PLATFORM`

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

### 8.3 Log append and read rules (corruption handling) (normative)

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

**Crash recovery / stale consumer cleanup**:
- Reaping is performed by the root runtime (or `workflowctl recover`).
- A claimed item is eligible for requeue when:
  - the queue item file `mtime` is older than `queues.processing_ttl_ms` (default `300000`), OR
  - a consumer lease file exists and is stale:
    - `processing/<consumer_id>/lease.json` with field `last_heartbeat_ts`
- Requeue means: move the file back to `inbox/` and record the move in WAJ (§7.2).

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



## 10) Mandatory PAUSE protocol (core contract)

A step is paused iff:
1. no tool subprocesses running
2. no WSS mutation in progress
3. control loop is waiting for RESUME/STOP
4. logs flushed to a safe boundary
5. ACK written under `control_actions/ack/`

Exact action/ACK shapes and flow are specified in Core Flows.

## 11) Configuration system (explicit, schema-validated)

### 11.1 Config format
All config files are TOML (`.toml`) for readability and easy hand-editing.

### 11.2 Config precedence (highest wins)

Config is loaded from multiple layers; higher layers override lower layers.

1. CLI flags
2. Repo machine-local (per repo per machine): `~/.workflow/repos/<repo_uid>/config.toml`
3. Repo shared (optional, committed): `<repo_root>/.workflow/config.toml`
4. User-global (installation): `~/.workflow/config.toml`
5. Built-in defaults

Notes:
- This precedence applies to **config TOML** only.
**Config reload behavior (normative)**:
- Config is loaded once per **command invocation** (e.g., one `workflowctl run`), producing an immutable “effective config” snapshot for that invocation.
- Long-running runs MUST NOT change behavior mid-run due to config file edits.
- Step processes inherit the effective config snapshot from their parent (root runtime) via explicit serialization in the step execution doc.
- Workflow and agent precedence are defined separately (Integration §7.1, Configuration & Onboarding §6).
### 11.3 Config logging (trust requirement)

On process start, the effective config MUST be logged as:
- `config_hash` (sha256 over canonicalized config)
- `config_redacted_preview` (sensitive keys removed)

Sensitive keys include:
- any key under `[secrets]`, `[providers]`, `[auth]`
- values matching secret-scan regexes (§12.3)

### 11.4 Minimum config schema (v1)

```toml
[sandbox]
# Defaults: cross-platform safe; performance tuning is optional
mode = "workspace"                 # workspace (default)
max_concurrent = 4
default_sparse = "copy"            # copy|full|empty (jj workspace add behavior)
copy_fallback = true               # allow fallback when sparse/workspace is insufficient
ttl_minutes = 120

[queues]
processing_ttl_ms = 300000         # 5 minutes
lease_refresh_ms = 30000           # consumer heartbeat cadence
max_requeue_attempts = 1           # bounded; avoid silent loops

[retention]
keep_runs = 50
keep_days = 30
compress_old_logs = true

[pause]
deadline_ms = 10000
tool_stop_grace_ms = 2000

[privacy]
network_mode = "llm_only"          # off|llm_only|unrestricted
redaction_mode = "block_on_secret" # block_on_secret|redact_and_continue
export_scrub_default = true

[models]
default = "chatgpt_5_2"
# routing can be overridden per workflow and per step

[models.routing]
# Routing key → model name (see Configuration & Onboarding §5.3)
planning = "claude-opus"
implementation = "claude-sonnet"
validation = "chatgpt-5"
multimodal = "gemini-3"

[dependencies]
jj_min_version = "0.22.0"
jj_recommended_version = "0.37.0"
auto_bootstrap_jj = true

[cli]
# Set by configuration agent (see Configuration & Onboarding §4)
default = ""                       # "claude-code"|"opencode"|"cursor"|"windsurf"|""
```
# Defaults: cross-platform safe; performance tuning is optional
mode = "workspace"                 # workspace (default)
max_concurrent = 4
default_sparse = "copy"            # copy|full|empty (jj workspace add behavior)
copy_fallback = true               # allow copy fallback when sparse/workspace is insufficient
ttl_minutes = 120

[retention]
keep_runs = 50
keep_days = 30
compress_old_logs = true

[pause]
deadline_ms = 10000
tool_stop_grace_ms = 2000

[privacy]
network_mode = "llm_only"          # off|llm_only|unrestricted
redaction_mode = "block_on_secret" # block_on_secret|redact_and_continue
export_scrub_default = true

[models]
default = "chatgpt_5_2"
# routing can be overridden per workflow and per step

[models.routing]
# Task type → model (see Configuration & Onboarding §5.3)
planning = "claude-opus"
implementation = "claude-sonnet"
validation = "chatgpt-5"
multimodal = "gemini-3"

[dependencies]
jj_min_version = "0.22.0"
jj_recommended_version = "0.37.0"
auto_bootstrap_jj = true

[cli]
# Set by configuration agent (see Configuration & Onboarding §4)
default = ""              # "claude-code"|"opencode"|"cursor"|"windsurf"|""
```

### 11.4.1 Sandbox TTL semantics

Sandbox cleanup is governed by `[sandbox] ttl_minutes`.

- Each sandbox metadata record MUST include:
  - `created_at`
  - `last_used_at`
- `last_used_at` is initialized to `created_at` and updated:
  - after every sandbox command invocation (success or failure)

Expiration rule (normative):

- A sandbox is eligible for cleanup when:
  - `now - last_used_at > ttl_minutes`
  - AND the sandbox is not referenced by an active run

If `last_used_at` is missing (legacy sandboxes), cleanup uses `created_at` as the start time.

**Enforcement (normative)**:
- Sandbox TTL is enforced by `workflowctl gc` (Core §11.5) and MAY also be enforced opportunistically at the end of `workflowctl run` / `workflowctl validate`.
- Enforcement MUST:
  1. acquire `locks/gc.lock`
  2. enumerate sandboxes under `~/.workflow/repos/<repo_uid>/sandboxes/`
  3. delete only sandboxes eligible by the rule above
  4. record a `gc_sandbox_deleted` event (or `fsck_issue` on failure) with `sandbox_id` and path



Note: Skills are managed by the AI coding CLI, not by the workflow engine config.

### 11.4.2 Model selection and override precedence (normative)

A workflow run selects a model for each **step execution**.

Model selection is **deterministic** and follows this precedence (highest wins):

1. **CLI override**  
   - `workflowctl run ... --model <model_ref>` (applies to all steps unless a step explicitly overrides again via `--respect-step-model=false`, which is NOT supported in v1)
2. **Step-level override (workflow YAML)**  
   - `steps[*].model: <model_ref>`
3. **Workflow default (workflow YAML)**  
   - `defaults.model: <model_ref>`
4. **Effective config default**  
   - `[models].default = <model_ref>`

Where `<model_ref>` is either:
- an explicit model name (e.g., `chatgpt_5_2`, `gemini_3`), OR
- a routing key (e.g., `planning`, `implementation`, `validation`, `multimodal`)

**Routing resolution (normative)**:
- If `<model_ref>` matches a known explicit model name, use it.
- Otherwise treat it as a routing key and resolve via `[models.routing].<key>`.
- If no mapping exists, fail loudly with `E_MODEL_ROUTE_NOT_FOUND` and include:
  - the unresolved key
  - the effective config file(s) used (paths only)
  - the workflow and step IDs (if applicable)

This section defines only **intra-run** precedence. File-level config precedence is defined in §11.2.
### 11.5 Retention and garbage collection

Retention is enforced by an explicit GC operation. There is no silent background deletion.

#### 11.5.1 Invocation

GC can be invoked:

- manually: `workflowctl gc`
- opportunistically on CLI startup (optional): if `workflowctl` detects `last_gc_at` older than `gc_interval_hours` (configurable)

Any GC run MUST write a summary to:

- `workspace/gc/gc_<run_ts>.json`

#### 11.5.2 What GC manages

GC may delete or compact:

- completed run directories under `workspace/runs/`
- archived notifications/control actions older than retention window
- sandboxes under `sandboxes/` (subject to sandbox TTL semantics §11.4.1)
- log shards under `workspace/logs/` (optional compression)

GC MUST NOT delete:

- active runs (`run.json.status in {"running","paused","investigating"}`)
- artifacts referenced by active runs

#### 11.5.3 Run retention rule

Config:

- `[retention] keep_days`
- `[retention] keep_runs`

Normative rule:

- For each repo, compute:
  - `cutoff_time = now - keep_days`
  - `protected_runs = newest keep_runs runs by start time`
- A completed run is eligible for deletion if:
  - it is not in `protected_runs`
  - AND its `finished_at < cutoff_time`

This means “keep at least N recent runs, and also keep all runs from the last D days”.

#### 11.5.4 Log compaction

If enabled, GC MAY compress old log shards:

- Input: `logs/shards/<run_id>/*.log`
- Output: `logs/shards/<run_id>/*.log.gz`

Compression is optional and must be transparent:

- `workflowctl logs show` MUST read either plain or compressed logs.

#### 11.5.5 Evidence preservation

Before deleting a run, GC MUST ensure that ticket-level durable evidence remains:

- ticket records in `workspace/tickets/`
- exported patches / summaries required for audit

GC is allowed to delete *run-local* artifacts that are reproducible from ticket state (e.g., hydration blobs), but must not delete ticket state.



## 12) Secrets, privacy, and export controls (trust requirement)

### 12.1 Secrets storage (low-friction, cross-platform)

All long-lived secrets (model provider keys, tokens) MUST be stored in the OS credential store via the Python **keyring** interface when available.

- Keyring project: https://pypi.org/project/keyring/

Fallback (when no system keyring is available):
- store an encrypted local secrets file under `~/.workflow/secrets/`
- encryption key is stored in the best available OS facility; if none exists, require user passphrase (last resort)

**Never** store secrets in:
- WSS JSON docs
- log events
- workflow YAML
- exported bundles

### 12.2 Network policy (explicit, default-safe)

`privacy.network_mode` governs outbound network:

- `off`: no outbound network; remote models disabled; only local tooling allowed
- `llm_only` (default): only known model provider endpoints are allowed (best-effort enforcement; also logged)
- `unrestricted`: no restriction (advanced users)

All remote LLM calls MUST:
- go through a cancellable subprocess boundary (so PAUSE can stop them)
- use redaction policies (§12.3)
- log only request metadata, not raw prompts by default (see below)

### 12.3 Secret scanning and redaction (mandatory on outbound)

Before sending any text to a remote model OR exporting a bundle, run secret scanning.

Minimum detectors:
- PEM private keys (`BEGIN ... PRIVATE KEY`)
- AWS access keys
- GitHub tokens
- generic high-entropy token heuristics (bounded to avoid false positives)
- `.env` and known secret file patterns (path-based)

Policy:
- `block_on_secret` (default): abort outbound operation; emit notification with offending evidence refs
- `redact_and_continue`: replace secret substrings with `REDACTED(<kind>:<hash>)` and proceed

### 12.4 Prompt logging (avoid accidental retention)

Default:
- store a **prompt manifest** (hashes + pointers) rather than full prompts:
  - `prompt_hash`
  - `bundle_id`
  - referenced file slice hashes
- store full prompts only when `privacy.allow_prompt_capture = true`

### 12.5 Export scrubber (shareable evidence bundles)

`workflowctl export scrub <run_id|ticket_id>` produces a shareable archive that:
- removes secrets (scanner + redaction)
- replaces file contents with hashes unless explicitly included
- includes:
  - run/step metadata
  - logs (optionally truncated)
  - environment capture
  - conclusions and conflict records
- emits a manifest of what was removed/redacted

Export is **always explicit** (no background uploads).

## 13) Dependency management (trust + friction)

### 13.1 Required external tools

Baseline:
- `git` (already present for developers)
- `jj` (Patch-Stream backbone)

Optional (per workflow):
- language toolchains (python/node/rust/etc)
- test runners, linters

### 13.2 `doctor` and `bootstrap` responsibilities

`workflowctl doctor` and `workflowctl bootstrap` are **trust and friction** utilities. They MUST be deterministic and must fail loudly.

#### 13.2.1 `workflowctl doctor` (normative checks)

`doctor` performs these checks, in this order. Each failing check MUST emit:
- one structured error (Core §8.2.4)
- one log event (`doctor_failed`)
- a non-zero process exit code

Checks:

1. **Locate repo root**
   - Command: `git rev-parse --show-toplevel`
   - Pass: command succeeds and returns a path
   - Fail (`E_NOT_FOUND`): “Not inside a git repository.”

2. **Derive or load `repo_uid`**
   - If `~/.workflow/repos/<repo_uid>/repo.json` exists, load it and use its `repo_uid`.
   - Otherwise, derive `repo_uid` per §3 and report that the repo is “not initialized”.

3. **Runtime root writable**
   - Attempt to create and delete: `~/.workflow/.write_test.<ulid>`
   - Attempt to create `~/.workflow/repos/<repo_uid>/` if missing
   - Fail (`E_NOT_ALLOWED`): insufficient permissions

4. **Tool availability**
   - `git`:
     - Pass if `git --version` succeeds
     - Fail (`E_DEPENDENCY_MISSING`) otherwise
   - `jj`:
     - Determine `jj_path`:
       1) repo-machine-local config override (if present)
       2) `PATH`
     - Pass if `jj --version` succeeds
     - Fail (`E_DEPENDENCY_MISSING`) otherwise

5. **`jj` version check**
   - Parse `jj --version` as a SemVer-like `MAJOR.MINOR.PATCH` (ignore suffixes like `-rc1` for minimum comparison).
   - Minimum required: `dependencies.jj_min_version` (Core config §11.4).
   - Fail (`E_DEPENDENCY_MISSING`) if installed version is less than minimum.

6. **Repo compatibility**
   - Pass if the repo is usable as a jj-backed Patch-Stream:
     - `jj root` succeeds, OR
     - repo is a git repo and `workflowctl bootstrap` is permitted to initialize jj (policy/config dependent)
   - Fail (`E_NOT_ALLOWED`) if jj is missing or repo cannot be used.

7. **Quick integrity checks**
   - `workflowctl fsck --quick` MUST run:
     - WSS JSON parse + schema_version checks
     - required fields present (§5.2)
     - log shard trailing partial line handling (§8.4)
   - Fail (`E_INTERNAL`) if corruption is detected.

On full success, `doctor` MUST emit:
- log event `doctor_ok`
- exit code `0`

#### 13.2.2 `workflowctl bootstrap` (low friction; bounded)

`bootstrap` may download or prepare dependencies when allowed by config.

Normative behavior:

- If `jj` is missing AND `dependencies.auto_bootstrap_jj=true`:
  - Download a pinned jj release into `~/.workflow/tools/jj/<version>/jj[.exe]`
  - Record the chosen `jj_path` in repo-machine-local config: `~/.workflow/repos/<repo_uid>/config.toml`
- Otherwise:
  - Fail with `E_DEPENDENCY_MISSING` and an actionable message

`bootstrap` MUST:
- print/log the exact actions it will perform before executing them
- never make network calls unless allowed by `[privacy].network_mode` (Core config §11.4)
### 13.3 Tool fingerprints and env capture

Every tool execution that matters MUST emit two artifacts:

- `tool_fingerprint` — a stable identifier for “what tool ran, with what argument shape, in what relevant environment”
- `env_capture.json` — a bounded, redact-safe snapshot of runtime environment (versions + platform) for reproducibility

Artifacts live under:

- `workspace/runs/<run_id>/artifacts/env/`

#### 13.3.1 Tool fingerprint format

A tool fingerprint is a string:

- `tfp1:sha256:<hex>`

It is computed from a canonical JSON payload.

##### Payload fields (v1)

```json
{
  "schema_version": 1,
  "tool_name": "pytest",
  "tool_path": "/usr/bin/pytest",
  "tool_realpath": "/usr/bin/pytest",
  "tool_version": "pytest 8.2.0",
  "args_class": "--maxfail <N> -q <PATH> ...",
  "env_sigs": {
    "PATH": "sha256:<hex>",
    "PYTHONPATH": "sha256:<hex>"
  },
  "binary_sha256": "sha256:<hex>|null"
}
```

Rules:

- `tool_path` MUST be the absolute path used for execution.
- `tool_realpath` MUST be the resolved symlink target of `tool_path`.
- `tool_version` MUST be obtained via a tool-specific version probe (usually `--version`).
- `binary_sha256`:
  - included only if enabled by config (`[tool_fingerprint] include_binary_hash = true`)
  - otherwise MUST be `null`
- `env_sigs` MUST store **hashes of values**, never raw values.

##### Selected env var set (default)

The fingerprint includes hashes for the following variables if present:

- `PATH`
- `PYTHONPATH`
- `VIRTUAL_ENV`, `CONDA_PREFIX`
- `NODE_OPTIONS`
- `JAVA_HOME`
- `GOROOT`, `GOMODCACHE`
- `CARGO_HOME`, `RUSTUP_HOME`
- `LANG`, `LC_ALL`

Workflows MAY extend this set via config (`[tool_fingerprint] extra_env = [...]`).

##### `args_class` definition

`args_class` is a deterministic normalization of `argv[1:]` intended to group runs that differ only in volatile values (paths, numbers).

Normative normalization:

- Split tokens on the first `=` for long options of the form `--opt=value` and rewrite as `--opt=<VAL>`.
- For tokens that are values to an option (the token immediately following a token starting with `-`), rewrite as `<VAL>`, except when the value is itself a flag (starts with `-`).
- For remaining non-flag tokens:
  - if it contains `/` or `\` → `<PATH>`
  - else if it ends with a common extension (`.py`, `.js`, `.ts`, `.go`, `.rs`, `.json`, `.yaml`, `.yml`) → `<PATH>`
  - else if it is an integer → `<N>`
  - else → `<ARG>`

The normalized tokens are joined with single spaces.

#### 13.3.2 Fingerprint computation

1. Build the payload object.
2. Serialize it as canonical JSON:
   - UTF-8
   - object keys sorted lexicographically
   - no insignificant whitespace
3. Compute:
   - `digest = sha256(canonical_bytes)`
4. Emit:
   - `tool_fingerprint = "tfp1:sha256:" + digest.hexdigest()`

The full payload SHOULD be persisted alongside the tool run record as `tool_fingerprint.json` for auditability.

#### 13.3.3 env_capture.json

`env_capture.json` is a bounded, redact-safe snapshot.

Minimum fields:

- `schema_version`
- `os` (name, version)
- `arch`
- `jj_version`
- language runtimes (when applicable): `python_version`, `node_version`, `java_version`, `go_version`, `rustc_version`
- `repo_uid`
- `base_rev` / `tip_rev` (when the tool run is tied to a ticket stack)

It MUST NOT include secret values. If environment variables are captured, they MUST be captured only as hashes.



## 14) Schema compatibility and migrations (trust requirement)

### 14.1 Forward/back rules

- If code reads a doc with `schema_version` **greater** than supported → fail loudly with upgrade instructions.
- If code reads an older doc → migrate in-memory and write back only via explicit `workflowctl migrate` (avoid silent upgrades).

### 14.2 Migration mechanism

Schema evolution is handled by explicit, auditable migrations. Migrations are not implicit “best effort” upgrades.

#### 14.2.1 Migration definition

A migration is a versioned unit that transforms one or more stores from version N → N+1.

Each migration MUST declare:

- `migration_id` (string; stable)
- `from_schema_version` (int)
- `to_schema_version` (int)
- `applies_to` (enum): `workspace|repo_runtime|tickets|projects|logs|queues|index`
- `preconditions` (checks; fail loudly if unmet)
- `actions` (file transforms)

Migrations MUST be **idempotent**:
- re-running the same migration MUST not corrupt state
- if state is already at `to_schema_version`, the migration is a no-op

Migrations may be implemented as:
- code (preferred; deterministic transforms), or
- declarative “JSON patch” style transforms for simple cases

#### 14.2.2 `workflowctl migrate` behavior

`workflowctl migrate` MUST support two modes:

- `--dry-run` (default):
  - scan state roots
  - compute a migration plan
  - write the plan to `workspace/migrations/plan_<ts>.json`
  - perform no writes

- `--apply`:
  - execute the plan in order
  - write durable markers for each applied migration

Plan contents (minimum):

- target root(s)
- current versions found
- migrations required (ordered)
- files to be modified

#### 14.2.3 Ordering and versioning

- Migrations are applied in increasing `to_schema_version` order per store.
- Cross-store migrations MUST declare dependencies; the plan resolver must topologically sort.

#### 14.2.4 Backups and rollback

Rollback is “restore from backup”.

Before modifying any file, `--apply` MUST:

- copy the original file to:
  - `workspace/migrations/backups/<ts>/<original_path>`

If a migration fails mid-way:

- stop immediately (loud failure)
- leave backups intact
- write `workspace/migrations/failed_<ts>.json` with the error and partial progress

A future `workflowctl migrate --restore <ts>` MAY be added; until then, restore is manual using backups.

#### 14.2.5 Applied markers

On successful application, the tool MUST write:

- `workspace/migrations/applied/<migration_id>.json`

Including:

- `migration_id`
- `applies_to`
- `applied_at`
- `files_modified[]` with before/after hashes



## 15) Integrity and recovery tools (trust requirement)

### 15.1 `workflowctl fsck`

Validations:
- WSS JSON parse + required fields present
- `rev` monotonicity
- log shard parse, seq monotonicity, hash chain verification
- queue directory invariants (no duplicates, no stranded tmp)
- journal invariants (prepare/commit pairs)

Outputs:
- durable report artifact + notification if corruption is detected

### 15.2 `workflowctl recover`

Recovery actions:
- finalize or roll back incomplete journaled operations
- requeue orphaned processing items after TTL
- cleanup stranded tmp files
- optionally rebuild derived index

All recovery actions are logged and bundled as evidence.

## 16) Core risk register (residual risks + controls)

All known risks have explicit controls; none require unspecified future work.

| Risk | Severity | Control(s) |
|---|---:|---|
| Cross-platform durability differences | Medium | tiered durability + journals + recover/fsck |
| Evidence bloat | Medium | retention + compression + GC; block GC on active runs |
| Secrets exfiltration | High | keyring secrets + outbound scanning + network policy + export scrubber |
| Concurrency hazards | Medium | ownership enforcement + expected_rev + locks |
| Toolchain drift | Medium | env capture + tool fingerprints + workflow-defined tool commands |
| Schema drift | Medium | explicit migrate tool + loud failure on unknown schema_version |