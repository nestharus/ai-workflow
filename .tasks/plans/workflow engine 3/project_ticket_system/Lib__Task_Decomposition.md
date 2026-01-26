# Library: Task Decomposition (`decompose`)

- **Primary responsibility**: Multi-pass task decomposition workflow contract, convergence criteria, and step-plan schema.
- **Depends on**: `wss_surfaces`, `workflow_resolver`, `lifecycle`
- **Used by**: `tm`

## 1) Overview

Task decomposition converts task input (`input.md`) into an executable step plan (`steps/step_plan.yaml`), using a workflow (default `task_decompose_v1`) resolved via `workflow_resolver`.

## 2) Logical roles (default workflow)

- Pattern discovery (agent): proposes boundary rules and invariants.
- Candidate surfacing (script/tool): produces candidate step plan.
- Approval gate (agent + optional user): approves/denies with rationale.
- Verification (agent): checks overlap/ordering/missing prereqs.

## 3) Convergence rules (normative)

No fixed max-iteration cap is used as a termination criterion. Decomposition convergence is determined by repeatable evidence.

### 3.1 Progress signature v1 (normative)

A decomposition attempt MUST emit a deterministic progress signature.

Inputs (durable artifacts):
- `task_input_hash`: sha256 of normalized `tasks/<task_id>/input.md` bytes
  - CRLF → LF
  - ensure exactly one trailing `\n`
- `candidate_set_hash`: sha256 of canonical JSON bytes of `steps/candidate_set.json`
- `approval_decision_hash`: sha256 of canonical JSON bytes of `steps/approval_decision.json`
- `verification_result_hash`: sha256 of canonical JSON bytes of `steps/verification_result.json`

Canonical JSON rules:
- UTF-8
- object keys sorted lexicographically
- no insignificant whitespace
- arrays remain in declared order

Signature object:

```json
{
  "schema_version": 1,
  "kind": "progress_signature",
  "algo": "sha256",
  "task_input_hash": "sha256:<hex>",
  "candidate_set_hash": "sha256:<hex>",
  "approval_decision_hash": "sha256:<hex>",
  "verification_result_hash": "sha256:<hex>"
}
```

Computation:
- `progress_signature = sha256(canonical_json_bytes(signature_object))`

Persistence (normative):
- MUST write `steps/progress_signature.json`

### 3.2 Repeat detection and loud stop (normative)

If the same `progress_signature` repeats for the same `(task_id, workflow_id)`:
- mark the task as `unsplittable`
- write `decomposition_problem_record.md` with evidence refs
- emit a notification and stop

### 3.3 Novelty rule (normative)

Each additional pass MUST add new durable evidence, for example:
- new candidate set variants (new step boundaries), or
- new constraints captured in `input.md`, or
- new verification results

If no novelty is present, stop and escalate (no silent looping).

### 3.4 Oscillation detection (normative)

Alternating approvals/denials that do not produce a stable step plan are treated as oscillation.

When detected:
- persist the oscillation evidence
- stop and require user input (constraints clarification)

## 4) Concurrency control (normative)

Decomposition MUST acquire `locks/task.<ticket_id>.<task_id>.lock` before:
- reading `task.json`
- writing any artifacts under `tasks/<task_id>/steps/` (including `step_plan.yaml` and `candidates/`)
- writing any artifacts under `tasks/<task_id>/deviations/` that are produced during decomposition

If lock acquisition fails:
- emit `E_LOCK_FAILED` including the lock path and (if available) lock holder info
- do not retry automatically
- instruct the user to check task status or wait for the other process to finish

## 5) Output artifacts (durable, normative)

The decomposition workflow MUST write under `tasks/<task_id>/steps/`:

- `step_plan.yaml` (authoritative step plan for execution; human-readable)
- `candidate_set.json` (canonical JSON; keys sorted; no whitespace)
- `approval_decision.json` (canonical JSON)
- `verification_result.json` (canonical JSON)
- `progress_signature.json` (computed signature)

Optional (audit):
- `step_rationale.md`
- `candidates/*.yaml`
- `decomposition_problem_record.md` (only when giving up loudly)

## 6) Step plan schema (v1; user-editable contract)

**File**: `workspace/tickets/<ticket_id>/tasks/<task_id>/steps/step_plan.yaml`

```yaml
schema_version: 1
ticket_id: LOC-123
task_id: task-001
workflow_id: task_decompose_v1
generated_by:
  run_id: 01J...
  step_execution_id: 01J...
  created_at: "2026-01-24T00:00:00Z"

constraints:
  mode_preference: "auto"   # auto|mode_a|mode_b
  allow_network: false      # default false; must be capability-gated
  max_files_touched: null   # null = no cap; used only as a signal

steps:
  - step_id: step-001
    title: "Add WSS schema validator"
    objective: "Ensure WSS docs are schema-validated on write"
    kind: patch            # patch|tool|investigate|decision
    mode_hint: auto        # auto|mode_a|mode_b (hint, not mandate)
    inputs:
      files:
        - path: "src/wss/store.py"
          rev: "ticket.tip"   # ticket.base|ticket.tip|<change_id>
          slice: null         # optional {start_line, end_line}
    success_criteria:
      - "unit tests pass"
      - "schema errors produce loud failures"
    depends_on: []
    capabilities_required:
      - read_stack
      - apply_patch

  - step_id: step-002
    title: "Run validation"
    kind: tool
    tool:
      workflow: ticket_validate_v1
    depends_on: ["step-001"]
```

### 6.1 Step plan validation rules (normative)

Before executing a step plan, the runner MUST validate:

1. `schema_version` is supported (currently only `1`).
2. `ticket_id`, `task_id`, and `steps` are present.
3. `steps` is an array (may be empty).
4. Each step has:
   - a unique `step_id`
   - a supported `kind`
5. `depends_on` references only `step_id`s that exist within the same plan.
6. The dependency graph is acyclic.
7. For `kind: patch` steps:
   - `capabilities_required` MUST include `apply_patch`.
8. Unknown fields are ALLOWED and MUST be preserved (forward compatibility).

Empty plans:
- `steps: []` is VALID and represents “no work needed”.
- Execution of an empty plan MUST:
  - emit a `step_plan_validated` event
  - mark the task `completed` without running patch/tool steps.

On validation failure:
- emit `E_VALIDATION_FAILED` with field-level errors (best-effort)
- do not execute any steps
- preserve the invalid plan as evidence (do not rewrite it)

## 7) Recovery when decomposition fails (normative)

If decomposition cannot converge (repeated signature, no novelty, or oscillation), the system MUST stop loudly and hand control to the user with durable artifacts.

On give-up:
- write:
  - `decomposition_problem_record.md`
  - a draft `steps/step_plan.yaml` (best attempt)
- set `task.json.status = "needs_user_plan"`
- emit a notification containing:
  - paths to the problem record and draft plan
  - the command to continue after editing

Supported user recovery actions:
1. Edit plan directly, then run:
   - `workflowctl task approve-plan <ticket_id> <task_id> --plan steps/step_plan.yaml`
2. Provide extra constraints and retry decomposition:
   - `workflowctl task decompose <ticket_id> <task_id> --workflow task_decompose_v1`
3. Abort task:
   - `workflowctl task abort <ticket_id> <task_id>`

Invariant:
- The system never “loops until it works”. If it cannot produce novelty, it gives up with evidence and a manual override path.
