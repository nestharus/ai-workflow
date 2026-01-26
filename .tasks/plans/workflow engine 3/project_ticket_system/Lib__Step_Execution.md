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

Timeout:
- default `approval_timeout_ms = 300000` (5 minutes)
- on timeout, runner MUST stop loudly and escalate as `needs_user` (Monitoring §5.4.2).

## 4) How deviations are used (non-normative)

- Evaluation uses deviations to justify unplanned changes (Enhanced Rebase §4).
- Monitoring/investigation uses deviations as high-signal context for failures.
