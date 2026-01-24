# Tech Plan: Core Infrastructure & Data Model (Restructured)

- **Doc**: Tech_Plan__Core_Infrastructure_&_Data_Model.md
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
- **Step (plan step)**: a planned unit of work within a task. Steps are executed sequentially by default.
- **Run**: a runtime execution group (`run_id`) containing one or more step executions.
- **Step execution**: the runtime instance of executing a step (`step_execution_id`, `writer_id`, log shard).

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
- **Sandbox**: a disposable hydrated workspace used to run tools (lint/tests/build/search).


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

**Derivation (default)**:
`repo_uid = sha256(canonical_repo_root_path + "\n" + git_remote_url_or_empty)[:16]`

- Stored in `repo.json` and becomes authoritative after first creation.
- If remote URL changes later, **do not** change `repo_uid` automatically (avoid orphaning state).

## 4) IDs and time

### 4.1 IDs (format + generation)

All durable IDs are **ULIDs**:
- Sortable and filename-safe.
- Use **monotonic ULID generation** per process to avoid collisions under concurrency bursts.
- ULID monotonicity: https://github.com/ulid/spec#monotonicity

IDs used:
- `project_id`, `ticket_id`, `task_id`
- `run_id`, `step_execution_id`
- `writer_id` (ULID or short stable string)
- `notification_id`, `request_id`
- `resolution_id`, `bundle_id`, `conclusion_id`
- `workflow_id`

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
| GC / compaction | `locks/gc.lock` | repo_uid |

Lock implementation:
- cross-platform lockfile using atomic create (`O_EXCL`) + process id + start time in file body
- stale lock reaping only via explicit `workflowctl recover-locks` (loud)

## 7) Durability protocol

### 7.1 Atomic write protocol (all platforms)

For every durable write to a file `<target>`:

1. write full content to `<target>.tmp.<ulid>`
2. flush file buffers (`fsync` / `FlushFileBuffers`)
3. atomically replace `<target>` with the temp file
4. best-effort directory sync (POSIX required; Windows best-effort)

Readers ignore `*.tmp.*`.

### 7.2 Write-ahead journals (WAJ) for critical mutations (mandatory)

To avoid relying on directory durability on Windows (and to strengthen crash recovery everywhere), critical state transitions MUST be journaled.

**Journal scope**: Only for *state transitions* (not for large append-only logs):
- `run.json` status transitions
- `step_execution_id` status transitions
- `ticket.json` lifecycle transitions
- any operation that moves queue items between inbox/processing/applied

**Journal layout**:
```text
workspace/journals/
  wss.<ulid>.jsonl                 # append-only journal segments
```

**Journal record (v1)**:
```json
{
  "schema_version": 1,
  "journal_id": "01...",
  "ts": "2026-01-24T00:00:00Z",
  "op_id": "01...",
  "kind": "wss_write|queue_move",
  "target_path": "workspace/runs/<run_id>/run.json",
  "expected_rev": 7,
  "new_content_hash": "sha256:...",
  "state": "prepare|commit"
}
```

**Protocol**:
1. `prepare` record is appended and flushed
2. perform the atomic write/move
3. `commit` record is appended and flushed

**Recovery invariant**:
- if `prepare` exists without `commit`, recovery MUST re-check the target path and either:
  - complete the operation (if the new content exists but pointer didn’t move)
  - or mark as abandoned and emit a notification (never silently ignore)

## 8) Logs Store (sharded JSONL)

### 8.1 Layout
One shard per `(run_id, writer_id)`:
```text
logs/runs/<run_id>/writers/<writer_id>.jsonl
```

Shards are append-only.

### 8.2 Event schema (v1 minimum)

Each line is JSON with:

Required:
- `schema_version`, `event_type`, `ts`, `run_id`, `writer_id`, `seq`, `data`

Optional (recommended):
- `step_execution_id`
- `ticket_id`, `task_id`, `step_id`
- `severity`
- `trace_id`, `span_id`
- `prev_hash`, `event_hash` (integrity chain; see below)

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

## 9) Notifications Store and Control Actions Queue (Maildir-like)

Both queues use the same hardened pattern:
- atomic publish (tmp → inbox)
- atomic claim (inbox → processing/<consumer_id>)
- bounded requeue on crash (processing TTL)
- idempotency via `request_id` / `notification_id`

Queue directories:
```text
notifications/{tmp,inbox,processing/<consumer_id>,archive}
control_actions/{tmp,inbox,processing/<consumer_id>,ack,applied,failed,archive}
```

Queue moves that change semantic state (`inbox→processing`, `processing→applied/failed`) are covered by write-ahead journals (§7.2) to guarantee recoverability on Windows.

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

1. CLI flags
2. Repo machine-local: `~/.workflow/repos/<repo_uid>/workspace/config.toml`
3. Repo shared (optional, committed): `<repo_root>/.workflow/config.toml`
4. User-global: `~/.workflow/config.toml`
5. Built-in defaults

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

Note: Skills are managed by the AI coding CLI, not by the workflow engine config.

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

- `workflowctl doctor`:
  - verifies `git` and `jj` availability
  - checks `jj version` against configured minimum
  - checks repo is compatible (git repo present)
  - checks runtime root is writable
  - checks WSS/logs integrity (`fsck --quick`)

- `workflowctl bootstrap` (low friction):
  - if `jj` missing and `auto_bootstrap_jj=true`, downloads a pinned jj release into `~/.workflow/tools/jj/`
  - records `jj_path` override into repo-machine-local config
  - never runs without printing the exact actions it will perform (loud)

### 13.3 Tool fingerprints and env capture

Every tool execution that matters MUST produce:
- `tool_fingerprint` (path + version + args class + selected env signatures)
- `env_capture.json` (OS + key tool versions + workspace revision identifiers)

These artifacts live under:
`workspace/runs/<run_id>/artifacts/env/`

## 14) Schema compatibility and migrations (trust requirement)

### 14.1 Forward/back rules

- If code reads a doc with `schema_version` **greater** than supported → fail loudly with upgrade instructions.
- If code reads an older doc → migrate in-memory and write back only via explicit `workflowctl migrate` (avoid silent upgrades).

### 14.2 Migration mechanism

`workflowctl migrate`:
- scans WSS docs and queues
- writes a migration plan artifact
- applies migrations with journals
- writes `workspace/runs/<run_id>/artifacts/migration_report.json`

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
