# Tech Plan: Monitoring & Self-Healing (Restructured)

- **Doc**: Tech_Plan__Monitoring_&_Investigator.md
- **Updated**: 2026-01-29
- **Component**: Monitoring / Investigation / Repair
- **Primary responsibility**: Detect anomalies early, pause safely, investigate using durable evidence, and (when safe) repair via auditable patches.

## 0) What monitoring/self-healing is for (UX)

Monitoring exists to prevent the “2-hour black box” problem:

- Users must be able to see **what is happening** during long-running work (progress markers + last-known tool state).
- Users must be able to **pause** safely (stop tools, flush evidence) without losing context.
- If something is stuck or looping, the system should **investigate first**, using durable evidence, and then choose the lightest correct intervention.
- When user action is required, the system must surface a **single notification** with stable IDs and concrete next steps.

This spec is intentionally biased toward **loud failures** and durable diagnostics over silent auto-retries.


## 1) Non-negotiable constraints (referenced)

Global invariants are defined in Core Infrastructure. Monitoring must obey:

- No standalone daemon required: monitoring runs inside the root runtime process.
- PAUSE is mandatory and enforced inside each step process.
- Avoid silent termination: timeouts are investigation triggers, not automatic killing.
- No destructive operations without explicit gating (capabilities + user ack when dangerous).

## 2) Monitoring architecture (flat)

### 2.1 Root runtime monitoring thread (default ON)
The monitoring thread runs inside Root for every active run unless explicitly disabled in config.

Reads:
- WSS run/step docs (status, heartbeat, active tool PIDs)
- log shard tails (progress markers, failure signatures)
- queue health (stalled processing items)

Writes:
- control actions (pause/resume/trace)
- notifications (when user action is needed)
- investigation spawn requests (via control actions)
- optional: fsck/recover triggers (bounded)

### 2.2 Step process control thread (mandatory)
Each step process includes a control loop that:

- polls for control actions targeting its `step_execution_id` or `run_id`
- enforces PAUSE by stopping tool subprocesses and writing ACK
- stops WSS mutations and flushes logs at safe boundaries
- emits progress markers (`event_type="progress"`) for long-running phases

## 3) PAUSE enforcement (mandatory)

### 3.1 Tool stop ladder (graceful → forced)
1. Graceful signal:
   - POSIX: SIGTERM
   - Windows: send `CTRL_BREAK_EVENT` when possible
2. Grace period: `pause.tool_stop_grace_ms` (default 2000 ms)
3. Forced kill:
   - POSIX: SIGKILL
   - Windows: TerminateProcess

Windows notes:
- `CTRL_C_EVENT` / `CTRL_BREAK_EVENT` require `CREATE_NEW_PROCESS_GROUP`.
  Python subprocess docs: https://docs.python.org/3/library/subprocess.html

### 3.2 Tool PID recording (required)
- `tool_start` events include PID and an args-class fingerprint.
- Step execution doc maintains `active_tool_pids`.

This allows investigators (and the monitor) to act on hung tools with evidence.

### 3.3 LLM calls via cancellable subprocess boundary
LLM calls MUST be executed via a cancellable tool subprocess (`workflow_engine llm_call`) so PAUSE can stop them without relying on cooperative cancellation.

## 4) Anomaly detection (investigate-first)

### 4.1 Signals (inputs, not automatic decisions)
- Missing heartbeat beyond threshold
- Tool subprocess duration beyond expected without progress events
- Repeated identical failure signatures (no novelty)
- Oscillation (retry alternates between two states without improving)
- Queue health anomalies (items stuck in processing beyond TTL)
- Journal anomalies (prepare without commit) detected by `fsck`

### 4.2 Response ladder (lightest intervention first)
1. Enable trace override for the target step (optional).
2. Request PAUSE (step must ACK promptly).
3. Spawn investigator with bounded evidence pointers.
4. If fixable and allowed: repair agent proposes patch and validates it.
5. Resume/retry; otherwise escalate to user with notification and concrete instructions.

## 5) Investigator contract (machine-readable, bounded evidence)

### 5.1 Inputs (bounded pointers only)
- step log shard path + seq range
- WSS docs + relevant artifacts
- current stack revision identifiers
- tool command + env signature (redacted)
- last N events (bounded)
- conclusions keyed by tool fingerprints and failure signatures

### 5.2 Outputs

Investigator output is a small JSON object written to WSS and consumed by the root runtime.

```json
{
  "classification": "resolved|needs_user|needs_retry|needs_shutdown",
  "incident_type": "tool_timeout|policy_blocked|dependency_missing|rebase_conflict|wss_corruption|unknown",
  "confidence": 0.0,
  "reason": "Short human-readable summary (single paragraph).",

  "actions": ["kill_tool_pid", "cleanup_sandbox", "request_recover"],

  "resume_plan": {
    "script_path": "workspace/runs/<run_id>/artifacts/investigation/<bundle_id>/resume.py",
    "wss_patches": []
  },

  "conclusion_updates": [],
  "evidence_refs": {
    "run_id": "...",
    "step_execution_id": "...",
    "log_seq_ranges": [[100, 150]],
    "artifact_paths": []
  }
}
```

Rules:
- `classification` is the *action class* (what to do next).
- `incident_type` is the *cause category* (why it happened).
- `confidence` is a float in `[0,1]` (0 = guess; 1 = certain).
- `resume_plan` MAY be null when classification is `needs_user` or `needs_shutdown`.
### 5.3 Privacy rule (trust)
Investigator bundles MUST respect privacy policy:
- never include secrets in outbound calls
- export bundles are scrubbed by default
- prompt logs are manifests by default (not full prompts)

### 5.4 Investigator implementation (workflow `investigate_v1`)

The investigator is a workflow + agent pair that operates on **bounded evidence**, not on live repo state.

#### 5.4.1 Evidence bundle generation

On investigator spawn, Root MUST create an evidence bundle directory:

- `workspace/runs/<run_id>/artifacts/investigation/<investigation_id>/`

Bundle contents (minimum):

- `investigation_request.json` (reason, triggering signature, limits)
- `events.jsonl` (last N structured events; bounded by config)
- `tool_runs/` (tool_run.json + stdout/stderr excerpts; bounded)
- `step_state.json` (current step execution state)
- `ticket_refs.json` (ticket_id, base_rev, tip_rev, relevant paths)
- `conclusions_snapshot.json` (relevant conclusions retrieved by signature)

The bundle MUST include enough pointers to reproduce the problem, but MUST NOT include secrets (Core Infrastructure §12).

#### 5.4.2 Classification and analysis (v1)

The investigator MUST produce both:
- `incident_type` (cause category), and
- `classification` (recommended next action category)

**User-facing playbooks**: For detailed user-facing recovery instructions for each error code, see `Tech_Plan__Error_Recovery_Playbooks.md`. The playbooks provide exact commands, escalation criteria, and evidence collection guidance.

##### A) Incident type (cause category)

Choose one of:

- `tooling_failure` (compiler/test runner, missing deps, env mismatch)
- `patch_failure` (invalid diff, scope violation, apply failure)
- `rebase_conflict` (conflict markers, ambiguous resolution)
- `timeout_or_hang` (no progress markers, long-running command)
- `policy_block` (capability gating, trust restrictions)
- `unknown` (insufficient evidence)

Evidence-first rules:
- Prefer tool exit codes + stderr signatures + structured errors emitted by the runner/gateway.
- Consult promoted conclusions before inventing new hypotheses.

##### B) Action classification decision tree (normative)

The investigator MUST set `classification` according to this decision tree:

1. **Resolved** (`resolved`)
   - Set when:
     - the run/step has already progressed to completion, OR
     - the observed failure condition is no longer present and the system is safe to resume without additional changes
   - Example evidence:
     - a later log shows `step_completed` for the stalled step
     - queue action already applied

2. **Needs retry** (`needs_retry`)
   - Set when:
     - the failure is plausibly transient, AND
     - a retry is allowed by policy/capabilities, AND
     - retry does not require user intent (no semantic choices)
   - Example evidence patterns:
     - `E_TOOL_TIMEOUT`
     - `timeout_or_hang` with no data corruption indicators
     - transient network/provider errors for LLM calls (`E_LLM_CALL_FAILED` with retryable=true)

3. **Needs user** (`needs_user`)
   - Set when:
     - a semantic decision is required, OR
     - a required capability/policy is missing, OR
     - the fix requires user action (install dependency, provide credentials, approve a destructive action)
   - Example evidence patterns:
     - `policy_block` / `E_CAPABILITY_DENIED` / `E_POLICY_BLOCKED`
     - `dependency_missing` / `E_DEPENDENCY_MISSING`
     - `rebase_conflict` where multiple resolutions are plausible

4. **Needs shutdown** (`needs_shutdown`)
   - Set when:
     - the system is in an unsafe or non-progressing state that cannot be recovered automatically, OR
     - evidence indicates corruption or repeated non-progressing loops
   - Example evidence patterns:
     - WSS corruption detected by `fsck` (`E_INTERNAL` with integrity failures)
     - repeated identical failures after bounded remediation attempts (e.g., repeat hunk-lint in Mode B)
     - runaway process/resource exhaustion

##### C) “Fixable and allowed” (normative)

An issue is **fixable and allowed** when ALL are true:
- the investigator can propose a deterministic `resume_plan` script, AND
- the script’s required capabilities are available (Integration §7.3), AND
- the plan does not require user intent (no semantic tradeoffs; no destructive operations)

If any condition is false, classification MUST be `needs_user` or `needs_shutdown` as appropriate.

##### D) Quick mapping from error codes → default classification

When a structured error code is available, the investigator SHOULD start with this mapping (then confirm with evidence):

- `E_TOOL_TIMEOUT` → `needs_retry`
- `E_LLM_CALL_FAILED` with `retryable=true` → `needs_retry`
- `E_DEPENDENCY_MISSING` → `needs_user`
- `E_CAPABILITY_DENIED` / `E_POLICY_BLOCKED` → `needs_user`
- `E_EXPECTED_REV_MISMATCH` → `needs_user`
- `E_JOURNAL_ABANDONED` → `needs_user`
- `E_SPARSE_DERIVATION_FAILED` → `needs_user`
- `E_INTERNAL` → `needs_shutdown` (unless evidence clearly indicates a simple retry will succeed)

##### E) Retry policy (normative)

When `classification = needs_retry`, Root MAY perform an automatic retry, but MUST bound retries to avoid silent looping.

Default policy (v1):
- `max_attempts_per_step_execution = 3` (1 initial attempt + up to 2 retries)
- backoff schedule (per retry attempt): `1000ms`, then `5000ms`
- retries MUST stop early if any retry produces a **different** failure that is classified as `needs_user` or `needs_shutdown`

Escalation rule:
- If the same `failure_signature` repeats for all attempts, Root MUST stop loudly and treat the condition as `needs_user` (even if originally classified `needs_retry`).

All retries MUST:
- append an attempt record to the run journal
- emit a notification on the final failure (non-retryable outcome)

#### 5.4.3 Resume plan generation

The investigator MUST output a structured resume plan:

- `resume_plan.json` with:
  - `recommended_action` (enum): `retry|switch_to_mode_b|request_user_input|run_repair_workflow|abort`
  - `rationale` (string)
  - `proposed_changes` (array): e.g., “expand hydration scope to X”, “use full sandbox”
  - `evidence_refs` (array)
  - optional `user_questions` (array of strings)

Resume plans are intended to be machine-consumable by Root (Flow 13) and user-readable.

#### 5.4.4 Interaction with conclusions

Before proposing a new remediation, the investigator MUST:
- search conclusions for matching signatures/tool fingerprints
- when considering any conclusion candidate:
  - if `disabled_until` is present and `disabled_until > current_time`:
    - skip it
    - emit `event_type="conclusion_skipped"` with `reason="disabled"` and include `disabled_until` and `disabled_reason` for audit trail
    - continue to the next candidate
- if an applicable promoted conclusion exists:
  - propose applying it unless evidence indicates it is inapplicable

Any time a conclusion is applied, the outcome MUST be recorded and linked back for promotion/demotion accounting.


## 6) Workflow repair agent (bounded self-healing)

Rules:
- Repairs must be represented as patches on the ticket stack (auditable).
- Validate fixes in a sandbox before resuming.
- No destructive operations without explicit capability + user ack.
- Repairs must write provenance artifacts:
  - what was changed
  - why
  - evidence references

## 7) Conclusions lifecycle (promotion states)

Conclusions are persistent, evidence-backed “known failure → known fix” records.

States:

- `draft` — created from a single incident (unverified)
- `confirmed` — reproduced across distinct runs with the same signature
- `promoted` — repeatedly successful remediation; safe for auto-application

### 7.0 Promotion thresholds (normative)

Definitions:

- A **reproduction** is an incident with the same `failure_signature` and compatible `tool_fingerprint`.
- A **successful remediation** is a run where:
  - the conclusion’s remediation was applied, AND
  - the subsequent validation passed (or the incident was resolved and execution resumed successfully)

Thresholds:

- `draft → confirmed` requires:
  - at least **2** reproductions
  - in **distinct run_id**
  - within a **30 day** window

- `confirmed → promoted` requires:
  - at least **2** successful remediations
  - in **distinct run_id**
  - within a **90 day** window
  - and no more than **1** remediation failure in that same window

### 7.1 Demotion and invalidation

Promoted conclusions must remain trustworthy.

- If a promoted conclusion is applied and fails to remediate in **2 consecutive** attempts:
  - demote it to `confirmed`
  - record demotion reason and evidence refs

- Manual invalidation is allowed:
  - `workflowctl conclusions invalidate <conclusion_id>`
  - sets state to `draft` and requires re-confirmation

### 7.2 Time windows and retention

- Reproduction and remediation counts are evaluated over rolling windows:
  - 30 days for confirmation
  - 90 days for promotion
- Historical events are retained for audit, even if outside the window.

### 7.3 Required fields in a conclusion record

Each conclusion record stored in WSS (Core Infrastructure — WSS §5.5) MUST store:

- `schema_version` (int)
- `conclusion_id` (ULID)
- `state` (`draft|confirmed|promoted`)
- `failure_signature` (string)
- optional `tool_fingerprint` constraints
- `remediation` (what to do; workflow id or patch recipe)
- `reproductions[]` with evidence refs
- `applications[]` with:
  - `timestamp` (RFC3339 UTC, ends in `Z`)
  - outcome (`success|fail`)
  - evidence refs
- optional disable fields:
  - `disabled_until` (RFC3339 timestamp, optional)
  - `disabled_reason` (string, optional)
- `stats` (object) containing:
  - `total_applications` (int)
  - `successful_applications` (int)
  - `failed_applications` (int)
  - `last_applied_at` (RFC3339 timestamp)
  - `avg_resolution_time_ms` (int, optional)
  - `most_common_triggers[]` (array of failure signatures)
- `created_at` (RFC3339)
- `updated_at` (RFC3339)
- `rev` (int)



### 7.4 User-facing control surface

CLI commands (minimum):

- `workflowctl conclusions list [--state draft|confirmed|promoted]`
- `workflowctl conclusions show <conclusion_id>`
- `workflowctl conclusions promote <conclusion_id>` (manual override)
- `workflowctl conclusions invalidate <conclusion_id>`
- `workflowctl conclusions apply <conclusion_id> --run <run_id>` (force apply for debugging)
- `workflowctl conclusions stats [--since-days N] [--format json|table]`
- `workflowctl conclusions disable <conclusion_id> [--until <RFC3339>] --reason <string>`
- `workflowctl conclusions export --out <path> [--state draft|confirmed|promoted] [--redact-secrets]`
- `workflowctl conclusions import <path> [--merge-strategy skip|overwrite|update] [--dry-run]`

All commands must print evidence refs and never hide the underlying artifacts.

### 7.5 Operational management semantics (normative)

This section defines required behavior for the conclusion management commands listed in §7.4.

#### 7.5.1 `workflowctl conclusions stats`

Signature:
- `workflowctl conclusions stats [--since-days N] [--format json|table]`

Behavior:
- Reads all conclusion documents from `workspace/conclusions/`.
- If `--since-days N` is provided, filter applications by `applications[].timestamp >= now - N days` (rolling window).
- Aggregates:
  - total applications in window
  - success rate = `successful_applications / total_applications * 100`
  - top 5 most common triggers (group by `failure_signature`)
  - optional: time-saved estimate (sum `avg_resolution_time_ms` across successful applications)

Errors:
- If WSS is not initialized, MUST fail with `E_NOT_FOUND` per Integration §2.1.2.
- If no conclusions exist, MUST emit a warning and exit `0`.

#### 7.5.2 `workflowctl conclusions disable`

Signature:
- `workflowctl conclusions disable <conclusion_id> [--until <RFC3339>] [--reason <string>]`

Behavior:
- `--reason` is REQUIRED for audit trail.
- If `--until` is omitted, disable indefinitely by setting `disabled_until` to a far-future timestamp (e.g., `2099-12-31T00:00:00Z`).
- Update the conclusion doc via JSON Merge Patch (RFC 7396; Core Infrastructure — WSS §5.3):
  - set `disabled_until`
  - set `disabled_reason`
  - increment `rev`
  - update `updated_at`
- Emit structured log event:
  - `event_type="conclusion_disabled"`
  - include `conclusion_id`, `disabled_until`, `disabled_reason`, and `actor` (user/system)

Application gating:
- Automatic application MUST skip conclusions where `disabled_until > current_time` and MUST emit `event_type="conclusion_skipped"` with `reason="disabled"` including `disabled_until` and `disabled_reason`.

#### 7.5.3 `workflowctl conclusions export`

Signature:
- `workflowctl conclusions export --out <path> [--state draft|confirmed|promoted] [--redact-secrets]`

Export bundle (JSON):
```json
{
  "export_version": 1,
  "exported_at": "<RFC3339>",
  "source_repo_uid": "<repo_uid>",
  "conclusions": [],
  "metadata": {
    "total_count": 0,
    "redacted": false
  }
}
```

Privacy:
- If `--redact-secrets` is set, remediation fields MUST be scrubbed per Core Infrastructure §12.
- The bundle MUST include a `redaction_manifest` in `metadata` listing what was redacted.

Write rules:
- Output MUST be written using the atomic write protocol (Core Infrastructure — Durability §7.1).
- File permissions MUST be set to `0600` (user-only read/write).

#### 7.5.4 `workflowctl conclusions import`

Signature:
- `workflowctl conclusions import <path> [--merge-strategy skip|overwrite|update] [--dry-run]`

Validation:
- Load JSON bundle and validate `export_version` compatibility.
- Validate each conclusion’s schema and required fields (Monitoring §7.3).

Conflicts:
- For each imported conclusion, detect whether `conclusion_id` exists locally and apply `--merge-strategy`:
  - `skip` (default): skip existing conclusions
  - `overwrite`: replace local conclusion entirely
  - `update`: merge `applications[]` and `reproductions[]`, keep higher `rev`

Import normalization:
- Imported conclusions MUST start in `draft` state (require re-confirmation in the new repo).
- Disable state MUST NOT be imported:
  - clear `disabled_until` and `disabled_reason`
- Reset lifecycle bookkeeping:
  - update `created_at` to import time
  - set `rev` to `1`

Dry-run:
- When `--dry-run` is set, perform validation and conflict detection without writing, and exit with a summary.

Audit:
- Emit structured log event `event_type="conclusion_imported"` for each imported conclusion.

### 7.6 Testing considerations (required)

Unit tests:
- Stats calculation with various time windows
- Disable/enable state transitions
- Export bundle generation and privacy scrubbing
- Import conflict resolution strategies
- Investigator skip logic for disabled conclusions

Integration tests:
- End-to-end: export from one repo, import to another
- Disable → wait → auto-enable workflow
- Stats accuracy across multiple runs



## 8) Monitoring risk register (residual risks + controls)

| Risk | Severity | Control(s) |
|---|---:|---|
| PAUSE cannot stop certain tools/LLM calls | High | enforce subprocess boundary; PID recording; escalate to investigator |
| False positives from time-based triggers | Medium | treat time as signal; require progress evidence analysis |
| Repair causes regressions | Medium | sandbox validation required; provenance + evidence; capability gating |
| Investigation loops | Low | novelty requirement + repeated signature → explicit give-up |

## 9) Notifications

When emitting notifications for error conditions, producers SHOULD include a reference to the relevant playbook section in the notification message, e.g., "See Error Recovery Playbooks: E_EXPECTED_REV_MISMATCH for recovery steps."
