# Library: Step Execution & Deviations (`execute`)

- **Primary responsibility**: Execute planned steps into patch stack changes, while emitting durable evidence and recording deviations.
- **Depends on**: `wss_surfaces`, `workflow_resolver`, `lifecycle`
- **Used by**: `tm`

## 1) Default step execution pipeline (normative)

For each step (sequential by default), the pipeline is:

1. Context hydration (Mode A preferred; Core Flows Flow 8)
2. Patch authoring (agent emits unified diff)
3. Hunk-lint gate (format + dry-run apply; Enhanced Rebase §3.1)
4. Patch apply to the ticket stack (new change in `jj`)
5. Record deviations (if any)
6. Emit `step_stop` with status and evidence refs

Parallelism:
- Steps are sequential unless a workflow explicitly enables safe parallelism.

## 2) Minimum evidence (normative)

Each executed step MUST produce:
- WSS step execution doc (`workspace/runs/<run_id>/steps/<step_execution_id>.json`, per Core Infrastructure)
- patch diff + metadata under the step artifacts directory (runner-defined)
- shard events: `step_start`, `tool_*`, `progress`, `step_stop`

## 3) Deviation model

### 3.1 Deviation definition

A deviation is an intentional, recorded departure from the declared plan or default policies that could affect reproducibility, correctness, or auditability.

Examples:
- switching execution mode (Mode A → Mode B fallback)
- expanding hydration scope beyond the step plan file list
- expanding sandbox sparse patterns beyond derived defaults
- skipping a planned sub-step due to a verified no-op condition
- tool substitution due to capability gating

Deviations are evidence; they are not errors by themselves.

### 3.2 When deviations MUST be recorded (normative)

A deviation record MUST be written when:
- execution mode or sandbox policy changes relative to plan/workflow defaults
- hydration scope expands beyond the step plan file list
- sparse patterns expand beyond derived defaults
- any fallback path is taken (copy fallback, manual resolution, tool substitution)

### 3.3 Deviation record format (normative)

Deviation files live under:
- `tasks/<task_id>/deviations/<deviation_id>.json`
- optional: `tasks/<task_id>/deviations/<deviation_id>.md`

`<deviation_id>` is a ULID.

Minimum JSON schema:

```json
{
  "schema_version": 1,
  "deviation_id": "<ulid>",
  "created_at": "<rfc3339>",
  "task_id": "<task_id>",
  "ticket_id": "<ticket_id>",
  "step_id": "<step_id>",
  "kind": "mode_fallback|scope_expand|sparse_expand|tool_substitute|plan_adjustment|other",
  "severity": "info|warn|error",
  "summary": "one-line description",
  "expected": "what would have happened without the deviation",
  "actual": "what happened",
  "evidence_refs": ["..."],
  "approved_by": null
}
```

If user approval is required, `approved_by` is set and the corresponding control action ID MUST be referenced in `evidence_refs`.

### 3.4 Approval flow (normative)

Approval is REQUIRED when:
- `severity: "error"` AND
- the deviation involves a capability marked `dangerous` (Integration §7.3).

Approval is OPTIONAL for `severity: "warn"` (workflow MAY request it), and NOT REQUIRED for `severity: "info"`.

Protocol:
1. Runner writes the deviation record with `approved_by: null`.
2. Runner emits a notification with `requires_action=true`.
3. Runner writes a control action request envelope:
   - `control_actions/inbox/deviation_approval_request_<deviation_id>.json`
   - `control_kind: "deviation_approval_request"`
   - includes `deviation_id`, `ticket_id`, `task_id`, `step_id`, `capability`, `approval_timeout_ms`
4. Runner MUST enter the PAUSE protocol (Core Flows Flow 12) until resolved.
5. User responds via CLI:
   - `workflowctl approve-deviation <deviation_id> --approve|--deny [--note "..."]`
   which writes:
   - `control_actions/inbox/deviation_approval_<deviation_id>.json`

Resolution:
- Approve: runner sets `approved_by` and resumes.
- Deny: runner MUST stop loudly and mark task `needs_user_plan` (or ticket `blocked`) with evidence refs.

#### 3.4.1 Timeout override mechanism (normative)

Timeout values follow this precedence order:
1. `step_spec.approval_timeout_ms` (step-specific override)
2. `workflow.defaults.approval_timeout_ms` (workflow default)
3. config default: 300000ms (5 minutes)

The control action request MUST include the resolved timeout value:
```json
{
  "control_kind": "deviation_approval_request",
  "approval_timeout_ms": 300000,
  "deadline": "<rfc3339>"
}
```

#### 3.4.2 Pre-timeout reminder (normative)

At `deadline - 30s`, the runner MUST emit a notification to remind the user:
- `notification_type`: `"deviation_approval_pending"`
- Deduplication: use `deviation_id` as the dedupe key
- If the user is already watching the run or has existing pending notifications, do not duplicate

The reminder MUST be lightweight and not block workflow execution.

#### 3.4.3 Timeout extension (normative)

Users may extend an approval timeout via CLI:

```bash
workflowctl approve-deviation <deviation_id> --extend-ms <ms> [--note "..."]
```

This writes a control action:
- `control_actions/inbox/deviation_extend_<deviation_id>.json`
- `control_kind`: `"deviation_extend"`
- includes `deviation_id`, `extend_ms`, `note`, and `created_at`

Extension rules:
- Maximum of 3 extensions per deviation (configurable via `max_approval_extensions`)
- Each extension updates the deviation record with a new `deadline`
- Total timeout is tracked: original + sum of all extensions
- Extension attempts beyond the limit are rejected with error

The deviation record MUST track:
```json
{
  "extensions": [
    {
      "granted_at": "<rfc3339>",
      "extend_ms": 300000,
      "note": "Need more time to review",
      "new_deadline": "<rfc3339>"
    }
  ],
  "extension_count": 1
}
```

#### 3.4.4 Extension envelope lifecycle (normative)

**Critical**: Extension envelopes MUST be processed according to their arrival time relative to the deadline and the run state.

**3-phase envelope processing model**:

1. **Phase A: Pre-deadline (while timer is active)**
   - Extension arrives before `deadline`
   - Runner accepts envelope and updates `deadline`
   - Timer is rescheduled to new deadline
   - Run continues in PAUSE state

2. **Phase B: Post-deadline, pre-stop (after timer fires, before stop executes)**
   - Extension arrives after `deadline` but before run state transitions to `stopped`
   - Runner records the extension attempt with `late: true` and `outcome: "rejected_post_timer"`
   - Extension is NOT applied; original timeout action proceeds
   - Notification `deviation_extension_rejected` is emitted with:
     ```json
     {
       "deviation_id": "...",
       "attempted_at": "<rfc3339>",
       "deadline": "<rfc3339>",
       "reason": "Extension arrived after timer fired but before stop finalized",
       "outcome": "rejected_no_effect"
     }
     ```
   - This phase is atomic and bounded; it ends as soon as the run state becomes `stopped`

3. **Phase C: Post-stop (after run state is `stopped`)**
   - Extension arrives after run state is `stopped`
   - Runner records the extension attempt with `late: true`
   - Extension is REJECTED with error; run remains stopped
   - Error response is written to the control action inbox:
     ```json
     {
       "control_kind": "deviation_extend_response",
       "deviation_id": "...",
       "status": "error",
       "error": "Cannot extend stopped run",
       "rejected_at": "<rfc3339>",
       "run_state": "stopped",
       "instructions": "Use workflowctl run resume <run_id> instead of extension"
     }
     ```
   - Notification `deviation_extension_rejected` is emitted with details
   - Run is NOT revived under any circumstances

**Timer/stop reconciliation rules**:

- The timeout timer is the primary authority on deadline enforcement
- Upon timer expiration, the runner atomically:
  1. Marks timeout as expired
  2. Checks for in-flight extension envelopes (any arriving within a bounded race window, typically 100ms)
  3. If any in-flight envelopes exist, marks them as arrived post-timer and rejects them
  4. Transitions run state to `stopped`
- Any extension envelope arriving after the run state becomes `stopped` is automatically rejected
- The run state transition to `stopped` is irreversible; once stopped, extensions never revive the run

**Edge case: in-flight extension at exact deadline**

- If an extension envelope is in-flight (received but not yet processed) when the timer expires:
  - The runner processes the envelope and marks it `late: true`
  - The extension is NOT applied
  - The stop action proceeds as scheduled
- This ensures deterministic behavior: the timer fire takes precedence over in-flight extensions

**User-facing guidance**:

- If a user attempts to extend a paused run and receives `deviation_extension_rejected`, they must use `workflowctl run resume <run_id>` to manually continue (if they want to proceed despite the timeout expiring)
- Extension is for extending the deadline while paused, not for reviving a stopped run

#### 3.4.5 Late approval handling (normative)

If an approval arrives after the timeout has expired and the run has already stopped:

1. Record the approval with `late: true` in the deviation record:
   ```json
   {
     "approved_by": "<user_id>",
     "approval_recorded_at": "<rfc3339>",
     "late": true,
     "late_reason": "Approval received after timeout and run stop"
   }
   ```

2. Emit notification `deviation_approval_late` with:
   - `deviation_id`
   - `run_id`
   - `step_id`
   - User instructions: `workflowctl run resume <run_id> --from-step <step_id>`

3. Do NOT automatically resume on late approval (avoids silent race resolution)

The user must explicitly resume the run if they want to proceed with the late approval.

## 4) How deviations are used (non-normative)

- Evaluation uses deviations to justify unplanned changes (Enhanced Rebase §4).
- Monitoring/investigation uses deviations as high-signal context for failures.
