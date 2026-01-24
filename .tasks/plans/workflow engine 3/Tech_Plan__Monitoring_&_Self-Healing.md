# Tech Plan: Monitoring & Self-Healing (Restructured)

- **Doc**: Tech_Plan__Monitoring_&_Self-Healing.md
- **Updated**: 2026-01-24
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
```json
{
  "classification": "resolved|needs_user|needs_retry|needs_shutdown",
  "actions": ["kill_tool_pid", "cleanup_sandbox", "request_recover"],
  "resume_plan": {
    "script_path": "workspace/runs/<run_id>/artifacts/investigation/<bundle_id>/resume.py",
    "wss_patches": []
  },
  "conclusion_updates": [],
  "evidence_refs": {
    "run_id": "...",
    "step_execution_id": "...",
    "log_seq_ranges": [[100, 150]]
  }
}
```

### 5.3 Privacy rule (trust)
Investigator bundles MUST respect privacy policy:
- never include secrets in outbound calls
- export bundles are scrubbed by default
- prompt logs are manifests by default (not full prompts)

## 6) Workflow repair agent (bounded self-healing)

Rules:
- Repairs must be represented as patches on the ticket stack (auditable).
- Validate fixes in a sandbox before resuming.
- No destructive operations without explicit capability + user ack.
- Repairs must write provenance artifacts:
  - what was changed
  - why
  - evidence references

## 7) Conclusions lifecycle (avoid repeated debugging)

Conclusions are stored under `workspace/conclusions/` with promotion:
`draft → confirmed → promoted`

Promotion gates:
- confirmed requires reproduction across distinct runs
- promoted requires stable signature + successful remediation outcomes

Conclusions are keyed by:
- tool fingerprints
- error signature hashes
- step signatures

## 7.1) User-facing control surface (minimum CLI)

Monitoring is only useful if users can act on it quickly.

Minimum commands expected (names are illustrative; exact CLI design can vary):

- `workflowctl runs list` — list active/recent runs
- `workflowctl runs show <run_id>` — show run status + active step executions + last progress markers
- `workflowctl logs tail --run <run_id>` — tail structured events (JSONL) or a summarized view
- `workflowctl pause --run <run_id>` / `workflowctl pause --step <step_execution_id>`
- `workflowctl resume --run <run_id>` / `workflowctl resume --step <step_execution_id>`
- `workflowctl investigate --step <step_execution_id>` — request investigator spawn and print bundle path
- `workflowctl notifications tail` — show user-visible issues with stable IDs
- `workflowctl control ack <notification_id>` — acknowledge/resolve when required

**Invariant**
- These commands operate by IDs and durable artifacts. They do not rely on “watching a live UI”.


## 8) Monitoring risk register (residual risks + controls)

| Risk | Severity | Control(s) |
|---|---:|---|
| PAUSE cannot stop certain tools/LLM calls | High | enforce subprocess boundary; PID recording; escalate to investigator |
| False positives from time-based triggers | Medium | treat time as signal; require progress evidence analysis |
| Repair causes regressions | Medium | sandbox validation required; provenance + evidence; capability gating |
| Investigation loops | Low | novelty requirement + repeated signature → explicit give-up |
