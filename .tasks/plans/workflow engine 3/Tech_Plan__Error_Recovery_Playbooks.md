# Tech Plan: Error Recovery Playbooks (User-Facing)

- **Doc**: Tech_Plan__Error_Recovery_Playbooks.md
- **Updated**: 2026-01-29
- **Component**: Operations / Error Recovery
- **Primary responsibility**: Provide concrete, user-facing “when you see X, do Y” recovery instructions for the workflow engine’s standardized error codes.

This document is the human-facing companion to the machine-readable error taxonomy and investigation classification. It turns error codes into safe operational playbooks with exact commands, validation steps, and escalation criteria.

Cross-references:
- Error code definitions: [`Tech_Plan__Core_Infrastructure/07_Logs_Store.md`](Tech_Plan__Core_Infrastructure/07_Logs_Store.md) (§8.2.5)
- Investigation classification: [`Tech_Plan__Monitoring_&_Investigator.md`](Tech_Plan__Monitoring_&_Investigator.md) (§5.4.2)
- Recovery tools: [`Tech_Plan__Core_Infrastructure/15_Integrity_and_Recovery_Tools.md`](Tech_Plan__Core_Infrastructure/15_Integrity_and_Recovery_Tools.md)

## 0) How to use this document

1. Identify the **error code** (`E_<NAME>`) from the CLI output, notification, or structured error object.
2. Navigate to the matching playbook section (`### Error Code: ...`).
3. Follow **Immediate Safe Actions** first (evidence preservation + safety checks).
4. Execute **Recovery Steps** in order, validating outcomes at each step.
5. If any **When to Escalate** condition matches, stop and escalate with an evidence bundle.

Severity levels (operator meaning):
- **critical**: Stop immediately; do not retry; preserve evidence; escalate.
- **high**: User action required soon; retry only when explicitly indicated by the playbook; escalate if repeated.
- **medium**: Usually recoverable with bounded actions; retry is often appropriate if evidence indicates no corruption.
- **low**: Informational or minor; apply remediation as needed; escalate only if repeated or suspicious.

Escalate vs. retry:
- Prefer **retry** when the error is plausibly transient and the playbook indicates it is safe (see Monitoring decision tree: `needs_retry`, Monitoring §5.4.2.B).
- Prefer **escalation** when the error is **critical**, when it repeats after bounded remediation attempts, or when there are integrity/corruption indicators (see Monitoring decision tree: `needs_shutdown` / `needs_user`, Monitoring §5.4.2.B).

Evidence bundles:
- The investigator auto-collects bounded evidence bundles (Monitoring §5.4.1).
- When escalating manually, use the checklist in §2 (and align with Monitoring §5.4.1 bundle structure).

## 1) Playbook template (normative)

All playbooks in this document MUST follow this template structure exactly.

```markdown
### Error Code: E_<NAME>

**Severity**: [critical|high|medium|low]

**Symptoms**:
- Observable behaviors (error messages, UI states, log patterns)
- Where the error appears (CLI output, notifications, logs)

**Likely Causes**:
- Root cause categories (ordered by frequency)
- Environmental factors
- Configuration issues

**Immediate Safe Actions**:
1. Stop/pause commands (if applicable)
2. Evidence preservation steps
3. Safety checks before proceeding

**Recovery Steps**:
1. Diagnostic commands with exact syntax
2. Remediation commands with exact syntax
3. Validation commands to confirm recovery
4. Expected outcomes at each step

**When to Escalate**:
- Conditions requiring user intervention
- Conditions requiring system shutdown
- Evidence bundle requirements (reference Monitoring §5.4.1)
- What to attach (workspace docs, lock state, journal segments, etc.)

**Related Error Codes**:
- Cross-references to related playbooks

**Configuration References**:
- Relevant config keys from Configuration System §11
```

## 2) Evidence bundle checklist

When escalating, always include:
1. Error details (`error_id`, `code`, `message`, `details`)
2. Relevant log excerpts:
   - `workflowctl logs export --run <run_id> --error <error_id>`
3. WSS state for affected resources
4. Configuration snapshot:
   - `workflowctl config export --redact-secrets`
5. `fsck` report (if applicable)
6. Platform/environment details (OS, engine version, tool versions)

The investigator produces a bounded evidence bundle automatically (Monitoring §5.4.1). When escalating manually, mirror that structure where possible.

## 3) Core error playbooks (WSS / durability)

### Error Code: E_EXPECTED_REV_MISMATCH

**Severity**: high

**Symptoms**:
- WSS write is rejected with an `expected_rev` vs `actual_rev` mismatch.
- Appears in CLI output, notifications, and/or structured error logs for a write operation.

**Likely Causes**:
- Concurrent writer updated the same document.
- Stale read used to construct a mutation.
- Multiple TM/root processes operating on the same workspace.

**Immediate Safe Actions**:
1. Avoid repeated blind retries if the mismatch persists.
2. Preserve the error details and the target document identifiers.
3. Confirm whether more than one workflow engine process may be running.

**Recovery Steps**:
1. Validate workspace integrity:
   - `workflowctl fsck`
2. Re-run the command (it will reload the latest `rev` and re-apply the change).
3. Check for multiple processes:
   - `ps aux | grep workflow_engine`
4. Verify lock state in:
   - `workspace/locks/`
5. Expected outcome:
   - On success, the write is accepted and the document revision advances normally.

**When to Escalate**:
- The mismatch persists with **no concurrent processes** and no other writer activity.
- Attach:
  - the affected `workspace/...` doc (WSS state)
  - `workspace/locks/` state
  - the `fsck` report (from §2)

**Related Error Codes**:
- `E_OWNERSHIP_VIOLATION`
- `E_LOCK_FAILED`
- `E_JOURNAL_ABANDONED`

**Configuration References**:
- None.

### Error Code: E_JOURNAL_ABANDONED

**Severity**: high

**Symptoms**:
- `journal_abandoned` notification is emitted.
- `workflowctl recover` reports an abandoned `op_id`.

**Likely Causes**:
- Process crash or forced termination during a journaled operation.
- Power loss / unclean shutdown mid-commit.
- Persistent environment instability causing interrupted operations.

**Immediate Safe Actions**:
1. Do not overwrite state without inspecting the current durable documents.
2. Preserve the referenced `op_id` and journal segment identifiers.
3. Avoid running concurrent recovery operations in multiple terminals.

**Recovery Steps**:
1. Run recovery inspection for the abandoned operation:
   - `workflowctl recover --op <op_id>`
2. Validate overall integrity:
   - `workflowctl fsck`
3. If the output indicates an `expected_rev` mismatch:
   - do **NOT** overwrite;
   - inspect the current document state and re-run the higher-level operation.
4. Expected outcome:
   - Recovery reports a safe resolution path for the abandoned operation, and `fsck` confirms integrity.

**When to Escalate**:
- Abandoned operations repeat despite clean shutdowns.
- Attach:
  - the relevant journal segment(s)
  - `recover --op <op_id>` output
  - `fsck` report (from §2)

**Related Error Codes**:
- `E_EXPECTED_REV_MISMATCH`
- `E_INTERNAL`

**Configuration References**:
- None.

### Error Code: E_OWNERSHIP_VIOLATION

**Severity**: high

**Symptoms**:
- Write rejected with an ownership violation message.
- Appears when attempting to mutate a resource that requires ownership.

**Likely Causes**:
- Multiple processes attempting to own the same resource.
- Stale ownership record in WSS.

**Immediate Safe Actions**:
1. Ensure only a single workflow engine is operating on the workspace.
2. Preserve the error details and `resource_id` involved.
3. Avoid clearing ownership until you confirm it is stale and safe.

**Recovery Steps**:
1. Run ownership checks:
   - `workflowctl fsck --check-ownership`
2. Verify no other processes are running:
   - `ps aux | grep workflow_engine`
3. Inspect the ownership map in WSS (resource ownership record).
4. If safe, clear stale ownership:
   - `workflowctl recover --clear-ownership <resource_id>`
5. Expected outcome:
   - Subsequent writes succeed under a single active owner; `fsck --check-ownership` passes.

**When to Escalate**:
- Ownership violation occurs with a confirmed single process and no evidence of stale ownership.
- Attach:
  - ownership map excerpt (WSS)
  - `fsck --check-ownership` output
  - process list evidence (`ps` output)

**Related Error Codes**:
- `E_EXPECTED_REV_MISMATCH`
- `E_LOCK_FAILED`

**Configuration References**:
- None.

### Error Code: E_ATOMIC_REPLACE_FAILED

**Severity**: critical

**Symptoms**:
- Atomic file operation failed; potential for partial writes or data loss.
- May appear during critical durable write paths or journal transitions.

**Likely Causes**:
- Filesystem errors (I/O failures, permissions, rename/replace limitations).
- Disk full or inode exhaustion.
- Underlying storage instability.

**Immediate Safe Actions**:
1. STOP immediately — do not retry.
2. Preserve evidence (do not modify the workspace beyond read-only inspection).
3. Preserve `tmp/` directory contents if present.

**Recovery Steps**:
1. Run a full integrity check:
   - `workflowctl fsck --full`
2. Check filesystem health and free space:
   - `df -h`
3. Inspect for disk errors using platform-appropriate tools.
4. Expected outcome:
   - `fsck --full` either confirms safe recovery boundaries or identifies corruption requiring escalation.

**When to Escalate**:
- Always escalate.
- Attach:
  - `fsck --full` report
  - filesystem diagnostics (`df -h` output; relevant system logs)
  - preserved `tmp/` contents metadata (file list, sizes, timestamps)

**Related Error Codes**:
- `E_INTERNAL`

**Configuration References**:
- None.

### Error Code: E_ULID_COLLISION

**Severity**: critical

**Symptoms**:
- ULID generation collision detected.
- May present as repeated ID generation failures or explicit `E_ULID_COLLISION`.

**Likely Causes**:
- System clock issues (time moved backwards, non-monotonic clock source).
- NTP misconfiguration / clock skew.
- Extremely abnormal ULID generation conditions.

**Immediate Safe Actions**:
1. STOP immediately.
2. Preserve the collision details (which IDs collided and where they were observed).
3. Avoid generating additional IDs in the same environment until time is validated.

**Recovery Steps**:
1. Check system clock:
   - `date`
2. Verify NTP synchronization using your environment’s standard tooling.
3. Validate ULID integrity:
   - `workflowctl fsck --check-ulids`
4. Expected outcome:
   - Clock diagnostics explain the collision risk and `fsck --check-ulids` reports any affected documents.

**When to Escalate**:
- Always escalate.
- Attach:
  - ULID collision details
  - system time diagnostics (clock, NTP status)
  - `fsck --check-ulids` output

**Related Error Codes**:
- `E_INTERNAL`

**Configuration References**:
- None.

## 4) Sandbox / tool error playbooks

### Error Code: E_SPARSE_DERIVATION_FAILED

**Severity**: medium

**Symptoms**:
- Sandbox create/run fails because the runner refuses overly broad sparse patterns.
- May mention sparse derivation failure and/or pattern rejection.

**Likely Causes**:
- Workflow definition `inputs.files` is too broad or ambiguous.
- Sparse pattern derivation produces patterns that are not accepted by `jj sparse`.
- Workflow’s include/exclude patterns are underspecified.

**Immediate Safe Actions**:
1. Preserve sandbox derivation artifacts for the affected run.
2. Do not widen patterns blindly; prefer narrowing inputs.
3. Confirm the failure is isolated to sparse derivation (not general `jj` failure).

**Recovery Steps**:
1. Inspect the derived patterns artifact (must be written to `workspace/runs/<run_id>/artifacts/`).
2. Narrow `inputs.files` in the workflow definition.
3. Provide explicit `include_patterns` in the workflow.
4. If acceptable, enable full fallback:
   - `workflowctl config set sandbox.allow_full_fallback true`
5. Or use a per-run flag:
   - `workflowctl run <workflow> --allow-full-fallback`
6. Expected outcome:
   - Sandbox creation proceeds with acceptable sparse patterns or an explicitly allowed full fallback.

**When to Escalate**:
- Patterns are narrow but `jj sparse` still fails.
- Attach:
  - sandbox create request/response
  - derived sparse patterns artifact
  - sandbox creation logs (`workspace/runs/<run_id>/logs/`)

**Related Error Codes**:
- `E_SANDBOX_CREATE_FAILED`

**Configuration References**:
- `sandbox.allow_full_fallback` (boolean)

### Error Code: E_SANDBOX_CREATE_FAILED

**Severity**: high

**Symptoms**:
- Sandbox creation fails (e.g., `jj` workspace creation error).
- Appears during run setup or step environment provisioning.

**Likely Causes**:
- Insufficient disk space.
- `jj` binary missing or not executable.
- Permission issues in `workspace/` or sandbox paths.
- Corrupted PGS / `jj` state.

**Immediate Safe Actions**:
1. Preserve sandbox creation logs for the run.
2. Avoid repeated sandbox creation attempts until basic prerequisites are verified.
3. Confirm whether the failure is global (all runs) or isolated to one run.

**Recovery Steps**:
1. Check disk space:
   - `df -h workspace/`
2. Verify `jj` binary:
   - `which jj`
   - `jj --version`
3. Check PGS integrity in repo root:
   - `jj log`
4. Inspect sandbox creation logs:
   - `workspace/runs/<run_id>/logs/`
5. Try manual sandbox creation:
   - `jj workspace add <path>`
6. Expected outcome:
   - `jj` commands succeed and sandbox creation proceeds normally.

**When to Escalate**:
- `jj` commands work manually but sandbox creation still fails.
- Attach:
  - sandbox creation logs (`workspace/runs/<run_id>/logs/`)
  - `jj` command outputs (`jj --version`, `jj log`)
  - sandbox request/response payloads if available

**Related Error Codes**:
- `E_SPARSE_DERIVATION_FAILED`
- `E_DEPENDENCY_MISSING`

**Configuration References**:
- None.

### Error Code: E_SANDBOX_RUN_FAILED

**Severity**: medium

**Symptoms**:
- Tool execution inside a sandbox fails.
- Tool may succeed outside sandbox but fails within it.

**Likely Causes**:
- Tool is not available in the sandbox environment.
- Permission issues within sandbox.
- Resource limits are too strict.
- Sparse patterns exclude required tool dependencies.

**Immediate Safe Actions**:
1. Preserve tool run artifacts and stderr for the failing step.
2. Avoid repeated runs until tool availability and sparse patterns are checked.
3. Confirm whether the failure is tool-specific or sandbox-wide.

**Recovery Steps**:
1. Check tool availability:
   - `workflowctl doctor --check-tools`
2. Inspect tool stderr:
   - `workspace/runs/<run_id>/artifacts/tool_runs/`
3. Verify sandbox sparse patterns include tool dependencies.
4. Check resource limits configuration:
   - `workflowctl config get sandbox.resource_limits`
5. Expected outcome:
   - Tool dependencies are included and the tool executes successfully inside the sandbox.

**When to Escalate**:
- Tool works outside the sandbox but fails inside it repeatedly.
- Attach:
  - tool_run artifacts
  - sandbox creation/run logs
  - `workflowctl doctor --check-tools` output

**Related Error Codes**:
- `E_TOOL_FAILED`
- `E_TOOL_TIMEOUT`

**Configuration References**:
- `sandbox.resource_limits` (object)

### Error Code: E_TOOL_FAILED

**Severity**: medium

**Symptoms**:
- Tool subprocess exited with a non-zero code.
- Error message indicates tool-specific failure.

**Likely Causes**:
- Tool-specific failure (tests failing, compiler errors, etc.).
- Invalid arguments.
- Missing runtime dependencies for the tool.

**Immediate Safe Actions**:
1. Preserve stdout/stderr artifacts for the tool run.
2. Avoid rerunning with different arguments until the failing arguments are identified.
3. Confirm whether the failure is deterministic across retries.

**Recovery Steps**:
1. Inspect tool stdout/stderr:
   - `workspace/runs/<run_id>/artifacts/tool_runs/<tool_run_id>/`
2. Check tool exit code and error message.
3. Verify tool arguments in:
   - `tool_run.json`
4. Try running the tool manually with the same arguments.
5. Check tool dependencies:
   - `workflowctl doctor --tool <tool_name>`
6. Expected outcome:
   - Tool failure is explained and resolved (fixed arguments/deps), and re-run succeeds.

**When to Escalate**:
- Tool failure is unexpected or unclear after inspecting artifacts and manual reproduction.
- Attach:
  - tool_run artifacts
  - manual execution results (stdout/stderr + exit code)
  - relevant environment details

**Related Error Codes**:
- `E_SANDBOX_RUN_FAILED`
- `E_DEPENDENCY_MISSING`

**Configuration References**:
- None.

### Error Code: E_TOOL_TIMEOUT

**Severity**: medium

**Symptoms**:
- Tool subprocess exceeded the timeout.
- Logs show no progress markers near the timeout boundary.

**Likely Causes**:
- Hung process or deadlock.
- Infinite loop.
- Resource exhaustion.

**Immediate Safe Actions**:
1. Preserve logs and progress markers leading up to the timeout.
2. Identify whether the tool is still running before killing it.
3. Avoid increasing timeouts until you confirm the tool is legitimately slow (not hung).

**Recovery Steps**:
1. Check if the tool is still running:
   - `ps aux | grep <tool_pid>`
2. Inspect last progress markers in logs.
3. Check resource usage:
   - `top`
   - `htop`
4. If the tool is hung, request PAUSE (grace period then SIGKILL per pause protocol).
5. Increase timeout if legitimate:
   - `workflowctl config set timeouts.tool_default_ms <value>`
6. Retry with increased timeout.
7. Expected outcome:
   - Either the tool completes successfully under a justified timeout, or evidence confirms a hang requiring escalation.

**When to Escalate**:
- Repeated timeouts with no progress markers.
- Attach:
  - tool logs and progress events
  - resource diagnostics (CPU/memory)
  - tool_run artifacts (stdout/stderr)

**Related Error Codes**:
- `E_TOOL_FAILED`
- `E_LLM_CALL_FAILED`

**Configuration References**:
- `timeouts.tool_default_ms` (integer)

## 5) Model / LLM error playbooks

### Error Code: E_MODEL_ROUTE_NOT_FOUND

**Severity**: high

**Symptoms**:
- Model routing failed: no provider configured for the requested model.
- CLI/notification indicates a missing route for a model name.

**Likely Causes**:
- Missing model configuration.
- Typo in model name in the workflow definition.
- Provider not configured for the environment.

**Immediate Safe Actions**:
1. Preserve the requested model name from the error details.
2. Avoid repeated calls until configuration is confirmed.
3. Confirm whether this is a new model name or a regression.

**Recovery Steps**:
1. Check model configuration:
   - `workflowctl config get models`
2. Verify the model name in the workflow definition.
3. List available models:
   - `workflowctl models list`
4. Add a model route:
   - `workflowctl config set models.<model_name>.provider <provider>`
5. Verify provider credentials are configured.
6. Expected outcome:
   - Model routes resolve and LLM calls proceed for the requested model.

**When to Escalate**:
- Model is configured but routing still fails.
- Attach:
  - redacted config export
  - routing logs (if available)
  - workflow definition snippet indicating the model name

**Related Error Codes**:
- `E_LLM_CALL_FAILED`

**Configuration References**:
- `models` (object)
- `models.<model_name>.provider` (string)

### Error Code: E_LLM_CALL_FAILED

**Severity**: medium (retryable=true), high (retryable=false)

**Symptoms**:
- LLM API call failed.
- Structured error details include a `retryable` field.

**Likely Causes**:
- Network issues.
- Rate limits.
- Invalid API key.
- Provider outage.

**Immediate Safe Actions**:
1. Preserve the full structured error object (including `retryable`).
2. Avoid repeated manual retries if `retryable=false`.
3. Confirm whether other provider calls are failing at the same time.

**Recovery Steps**:
1. Check error details in the structured error object (`retryable` field).
2. If `retryable=true`:
   - Monitoring will auto-retry (up to 3 attempts).
3. If `retryable=false`:
   - Check API key configuration (redacted):
     - `workflowctl config get providers.<provider>.api_key`
   - Verify network connectivity:
     - `curl <provider_api_endpoint>`
   - Check provider status page.
   - Inspect LLM call logs:
     - `workspace/runs/<run_id>/logs/`
4. If rate limited:
   - wait and retry, or increase backoff:
     - `workflowctl config set llm.retry_backoff_ms <value>`
5. Expected outcome:
   - Retryable failures resolve with bounded retries; non-retryable failures are resolved by configuration/network remediation.

**When to Escalate**:
- Non-retryable failure persists with valid credentials and confirmed network connectivity.
- Attach:
  - LLM call logs
  - provider response/error payload (redacted)
  - configuration export (redacted)

**Related Error Codes**:
- `E_MODEL_ROUTE_NOT_FOUND`
- `E_TOOL_TIMEOUT`

**Configuration References**:
- `llm.retry_backoff_ms` (integer)
- `providers.<provider>.api_key` (string; secret)

## 6) Dependency / platform error playbooks

### Error Code: E_DEPENDENCY_MISSING

**Severity**: high

**Symptoms**:
- Required tool or dependency not found.
- Error includes the missing dependency name or check.

**Likely Causes**:
- Tool not installed.
- Tool not in `PATH`.
- Wrong version installed.

**Immediate Safe Actions**:
1. Preserve the missing dependency identifier from error details.
2. Avoid continuing operations that require the missing dependency.
3. Confirm whether the environment recently changed (PATH/tooling updates).

**Recovery Steps**:
1. Run the dependency check:
   - `workflowctl doctor`
2. Identify the missing dependency from the error details.
3. Install the missing tool (refer to dependency documentation).
4. Verify installation:
   - `which <tool>`
   - `<tool> --version`
5. Re-run doctor:
   - `workflowctl doctor`
6. If version mismatch:
   - update the tool, or adjust the version constraint in config.
7. Expected outcome:
   - `workflowctl doctor` passes and the blocked operation can be retried.

**When to Escalate**:
- Dependency is installed but not detected.
- Attach:
  - `workflowctl doctor` report
  - `which <tool>` and `<tool> --version` output
  - environment details (`PATH`, OS)

**Related Error Codes**:
- `E_SANDBOX_CREATE_FAILED`
- `E_TOOL_FAILED`

**Configuration References**:
- None.

### Error Code: E_UNSUPPORTED_PLATFORM

**Severity**: critical

**Symptoms**:
- Platform/OS is not supported for the requested operation.
- Error indicates unsupported platform constraints.

**Likely Causes**:
- Platform mismatch (Windows-specific operation on Linux, or vice versa).
- Missing platform-specific capability/tooling.
- Workflow requirements incompatible with the host OS.

**Immediate Safe Actions**:
1. STOP — do not attempt workarounds that may violate safety assumptions.
2. Preserve the workflow/operation identifier and platform details.
3. Avoid running destructive migrations or recovery actions on an unsupported platform.

**Recovery Steps**:
1. Check platform:
   - `uname -a` (Linux/macOS)
   - `ver` (Windows)
2. Review workflow requirements for platform constraints.
3. Check if an alternative workflow exists for the current platform.
4. Consult the platform compatibility matrix in documentation.
5. Expected outcome:
   - Operation is re-run on a supported platform or via a supported alternative.

**When to Escalate**:
- Always escalate.
- Attach:
  - platform details (OS/version)
  - workflow requirements and operation context

**Related Error Codes**:
- `E_DEPENDENCY_MISSING`

**Configuration References**:
- None.

## 7) Policy / capability error playbooks

### Error Code: E_CAPABILITY_DENIED

**Severity**: high

**Symptoms**:
- Operation blocked by capability gating.
- Error indicates the required capability/trust gate.

**Likely Causes**:
- Required capability not granted.
- Trust level insufficient for the requested action.

**Immediate Safe Actions**:
1. Identify the required capability from error details.
2. Avoid granting capabilities without understanding security implications.
3. Preserve operation context (what was attempted).

**Recovery Steps**:
1. Identify required capability from error details.
2. Check current capabilities:
   - `workflowctl config get capabilities`
3. Review capability documentation for security implications.
4. If safe, grant capability:
   - `workflowctl config set capabilities.<capability> true`
5. Re-run the operation.
6. Expected outcome:
   - Operation proceeds when the correct capability is granted.

**When to Escalate**:
- Capability should be granted but the operation is still blocked.
- Attach:
  - capability config snapshot
  - operation details and error payload

**Related Error Codes**:
- `E_POLICY_BLOCKED`

**Configuration References**:
- `capabilities.<capability>` (boolean)

### Error Code: E_POLICY_BLOCKED

**Severity**: high

**Symptoms**:
- Operation blocked by policy rules.
- Error indicates a policy violation category (privacy/network/export/etc.).

**Likely Causes**:
- Privacy policy violation.
- Network policy restriction.
- Export policy block.

**Immediate Safe Actions**:
1. Identify the policy violation from error details.
2. Avoid weakening policy without confirming the change is acceptable.
3. Preserve the operation inputs that triggered the policy decision.

**Recovery Steps**:
1. Identify policy violation from error details.
2. Check policy configuration:
   - `workflowctl config get policy`
3. Review policy documentation.
4. If the violation is legitimate, adjust policy:
   - `workflowctl config set policy.<rule> <value>`
5. If violation indicates a security issue, investigate before proceeding.
6. Expected outcome:
   - Operation proceeds under an intentionally configured policy, or remains blocked for safety.

**When to Escalate**:
- Policy block is unexpected or unclear.
- Attach:
  - policy config snapshot (redacted where required)
  - operation details and error payload

**Related Error Codes**:
- `E_CAPABILITY_DENIED`

**Configuration References**:
- `policy.<rule>` (varies)

### Error Code: E_LOCK_FAILED

**Severity**: high

**Symptoms**:
- Failed to acquire a cross-process lock.
- Error indicates lock contention or lock acquisition failure.

**Likely Causes**:
- Another process holds the lock.
- Stale lockfile remains after an unclean shutdown.

**Immediate Safe Actions**:
1. Confirm whether another workflow engine process is running.
2. Avoid deleting lockfiles until you confirm they are stale.
3. Preserve lock state for escalation if needed.

**Recovery Steps**:
1. Check for running processes:
   - `ps aux | grep workflow_engine`
2. Inspect the lockfile:
   - `cat workspace/locks/<resource>.lock`
3. If no process is running and the lock is stale (check timestamp):
   - remove stale lock:
     - `rm workspace/locks/<resource>.lock`
4. If a process is running:
   - wait for it to complete or PAUSE it.
5. Retry the operation.
6. Expected outcome:
   - Lock acquisition succeeds under a single active process and operations proceed.

**When to Escalate**:
- Lock acquisition fails with no competing process.
- Attach:
  - lockfile contents and timestamps
  - process list output
  - operation context

**Related Error Codes**:
- `E_EXPECTED_REV_MISMATCH`
- `E_OWNERSHIP_VIOLATION`

**Configuration References**:
- `queues.lease_ttl_ms` (integer)

## 8) Core / validation error playbooks

### Error Code: E_INTERNAL

**Severity**: critical

**Symptoms**:
- Internal system error or unexpected state.
- May include assertion failures or integrity failure indicators.

**Likely Causes**:
- Bug in the workflow engine.
- Data corruption.
- Invariant violation.

**Immediate Safe Actions**:
1. STOP immediately — do not retry.
2. Preserve all evidence; do not modify the workspace.
3. Capture the full error payload and surrounding logs.

**Recovery Steps**:
1. Run a full integrity check:
   - `workflowctl fsck --full`
2. Check for corruption indicators in error details.
3. Review recent operations in logs for the failing run.
4. Expected outcome:
   - `fsck --full` provides a definitive integrity report and points to recoverable vs. non-recoverable conditions.

**When to Escalate**:
- Always escalate.
- Attach:
  - `fsck --full` report
  - full logs for the run/step
  - error details payload

**Related Error Codes**:
- `E_ATOMIC_REPLACE_FAILED`
- `E_ULID_COLLISION`

**Configuration References**:
- None.

### Error Code: E_VALIDATION_FAILED

**Severity**: medium

**Symptoms**:
- Schema validation failed due to invalid input.
- Error details include the failing path and reason.

**Likely Causes**:
- Malformed workflow definition.
- Invalid field values.
- Missing required fields.

**Immediate Safe Actions**:
1. Preserve the validation error details (path + reason).
2. Avoid editing unrelated fields; apply the minimal correct fix.
3. Confirm the workflow schema version expected by the engine.

**Recovery Steps**:
1. Identify the validation error from error details (path + reason).
2. Inspect the workflow definition file.
3. Consult workflow schema documentation.
4. Fix the validation error in the workflow definition.
5. Re-validate:
   - `workflowctl workflow validate <workflow_file>`
6. Retry the operation.
7. Expected outcome:
   - Validation passes and the operation proceeds.

**When to Escalate**:
- Validation fails but the definition appears correct.
- Attach:
  - workflow definition file
  - validation error payload

**Related Error Codes**:
- `E_SCHEMA_VERSION_UNSUPPORTED`

**Configuration References**:
- None.

### Error Code: E_SCHEMA_VERSION_UNSUPPORTED

**Severity**: high

**Symptoms**:
- Document schema version not supported.
- Engine reports workspace or document schema mismatch.

**Likely Causes**:
- Workspace created with a newer engine version.
- Migration required.
- Invalid or corrupted schema version markers.

**Immediate Safe Actions**:
1. Preserve the reported schema versions (workspace vs engine).
2. Avoid running migrations repeatedly if they fail; preserve logs.
3. Do not modify WSS documents manually to “fix” schema versions.

**Recovery Steps**:
1. Check workspace schema version:
   - `workflowctl fsck --check-schema`
2. Check current engine version:
   - `workflowctl version`
3. If workspace is newer:
   - upgrade the engine.
4. If workspace is older:
   - run migration:
     - `workflowctl migrate`
5. Verify migration:
   - `workflowctl fsck`
6. Expected outcome:
   - Workspace schema becomes compatible and `fsck` passes.

**When to Escalate**:
- Migration fails or schema version is invalid.
- Attach:
  - `fsck --check-schema` output
  - migration logs
  - engine version output

**Related Error Codes**:
- `E_INTERNAL`

**Configuration References**:
- None.

### Error Code: E_NOT_FOUND

**Severity**: medium

**Symptoms**:
- Requested resource not found.
- Error indicates missing ID/path for a resource type.

**Likely Causes**:
- Invalid ID or typo.
- Resource deleted.
- Workspace state diverged from expectation.

**Immediate Safe Actions**:
1. Preserve the requested resource ID and resource type.
2. Avoid creating a new resource with the same ID unless the system supports it explicitly.
3. Check logs for recent operations involving the resource.

**Recovery Steps**:
1. Verify resource ID from error details.
2. List available resources:
   - `workflowctl <resource_type> list`
3. Check for typos in the resource ID.
4. If the resource should exist, check WSS:
   - `cat workspace/<resource_path>.json`
5. If resource was deleted, check logs for the deletion event.
6. Expected outcome:
   - Resource is located/identified or the deletion cause is explained.

**When to Escalate**:
- Resource should exist but is not found.
- Attach:
  - resource ID/type
  - relevant WSS state
  - log excerpts showing recent actions on the resource

**Related Error Codes**:
- `E_NOT_ALLOWED`

**Configuration References**:
- None.

### Error Code: E_NOT_ALLOWED

**Severity**: medium

**Symptoms**:
- Operation not allowed in the current state.
- Error indicates state machine violation or invalid transition.

**Likely Causes**:
- Invalid transition for the resource’s current state.
- Operation invoked at the wrong time.
- Resource state is incorrect due to earlier failure.

**Immediate Safe Actions**:
1. Preserve the resource state and the operation requested.
2. Avoid forcing state transitions without understanding invariants.
3. Check whether a prior failure left the resource in an intermediate state.

**Recovery Steps**:
1. Check current resource state from error details.
2. Review state machine documentation for valid transitions.
3. Verify the operation is appropriate for the current state.
4. If state is incorrect, investigate how it reached that state.
5. If state is correct, use the appropriate operation for that state.
6. Expected outcome:
   - Operation is retried with a valid transition or the underlying state issue is identified.

**When to Escalate**:
- State transition should be valid but is blocked.
- Attach:
  - resource state (WSS)
  - operation details
  - relevant logs leading to current state

**Related Error Codes**:
- `E_NOT_FOUND`
- `E_INTERNAL`

**Configuration References**:
- None.

### Error Code: E_WORKFLOW_AMBIGUOUS

**Severity**: medium

**Symptoms**:
- Multiple workflows match the requested operation.
- CLI indicates ambiguous workflow selection.

**Likely Causes**:
- Ambiguous workflow ID.
- Multiple versions present.
- Naming conflict in workflow registry.

**Immediate Safe Actions**:
1. Preserve the workflow selector used (ID/pattern/namespace).
2. Avoid running the wrong workflow; use fully qualified IDs.
3. Confirm whether the ambiguity is expected (multiple versions) or accidental.

**Recovery Steps**:
1. List matching workflows:
   - `workflowctl workflow list --filter <pattern>`
2. Use fully qualified workflow ID:
   - `<namespace>/<workflow_id>@<version>`
3. Check workflow registry:
   - `workflowctl workflow show <workflow_id>`
4. If the conflict is unintended, rename or remove the conflicting workflow.
5. Expected outcome:
   - A single workflow is selected deterministically and the operation proceeds.

**When to Escalate**:
- Workflow ID is unambiguous but still reported as ambiguous.
- Attach:
  - workflow registry state
  - workflow list output
  - workflow selector used

**Related Error Codes**:
- `E_VALIDATION_FAILED`

**Configuration References**:
- None.

## 9) Quick reference index

| Error Code | Severity | Primary Action | Escalate If |
|------------|----------|----------------|-------------|
| E_EXPECTED_REV_MISMATCH | High | `fsck` + retry | Persists with no concurrent processes |
| E_JOURNAL_ABANDONED | High | `recover --op` + `fsck` | Repeated on clean shutdowns |
| E_OWNERSHIP_VIOLATION | High | `fsck --check-ownership` + clear stale ownership | Single process still violates ownership |
| E_ATOMIC_REPLACE_FAILED | Critical | STOP + `fsck --full` | Always |
| E_ULID_COLLISION | Critical | STOP + clock check + `fsck --check-ulids` | Always |
| E_SPARSE_DERIVATION_FAILED | Medium | Narrow patterns or enable fallback | Narrow patterns still fail |
| E_SANDBOX_CREATE_FAILED | High | Disk/`jj` checks + inspect logs | `jj` works manually but sandbox still fails |
| E_SANDBOX_RUN_FAILED | Medium | `doctor --check-tools` + inspect artifacts | Tool works outside sandbox but not inside |
| E_TOOL_FAILED | Medium | Inspect tool_run artifacts + reproduce | Failure remains unclear/unexpected |
| E_TOOL_TIMEOUT | Medium | Check PID/progress + adjust timeout | Repeated timeouts with no progress |
| E_MODEL_ROUTE_NOT_FOUND | High | Configure model route | Configured but routing still fails |
| E_LLM_CALL_FAILED | Medium/High | Retry if retryable; fix creds/network if not | Non-retryable persists with valid creds |
| E_DEPENDENCY_MISSING | High | `doctor` + install missing tool | Installed but not detected |
| E_UNSUPPORTED_PLATFORM | Critical | STOP + run on supported platform | Always |
| E_CAPABILITY_DENIED | High | Grant capability if safe | Should be granted but still blocked |
| E_POLICY_BLOCKED | High | Inspect policy + adjust if legitimate | Unexpected/unclear policy decision |
| E_LOCK_FAILED | High | Inspect lock + clear stale lockfile | No competing process yet lock fails |
| E_INTERNAL | Critical | STOP + `fsck --full` | Always |
| E_VALIDATION_FAILED | Medium | Fix input + `workflow validate` | Appears correct but still fails |
| E_SCHEMA_VERSION_UNSUPPORTED | High | `fsck --check-schema` + `migrate`/upgrade | Migration fails/invalid schema |
| E_NOT_FOUND | Medium | Verify ID + list resources | Resource should exist but missing |
| E_NOT_ALLOWED | Medium | Verify state/transition | Transition should be valid but blocked |
| E_WORKFLOW_AMBIGUOUS | Medium | Use fully qualified workflow ID | Unambiguous but still ambiguous |

## Appendix A: Configuration keys

This appendix lists configuration keys referenced by playbooks in this document. Full configuration documentation lives in [`Tech_Plan__Core_Infrastructure/10_Configuration_System.md`](Tech_Plan__Core_Infrastructure/10_Configuration_System.md) (Configuration System §11).

- `sandbox.allow_full_fallback` (boolean) - Allow full checkout when sparse derivation fails
- `sandbox.resource_limits` (object) - Sandbox resource limits
- `timeouts.tool_default_ms` (integer) - Default tool timeout in milliseconds
- `llm.retry_backoff_ms` (integer) - LLM retry backoff in milliseconds
- `models` (object) - Model routing configuration root
- `models.<model_name>.provider` (string) - Provider route for a model name
- `providers.<provider>.api_key` (string; secret) - Provider API key (always redacted on export)
- `queues.lease_ttl_ms` (integer) - Queue processing lease TTL
- `capabilities.<capability>` (boolean) - Capability grants
- `policy.<rule>` (varies) - Policy rules
