# Tech Plan: Project & Ticket Management (Restructured)

- **Doc**: Tech_Plan__Project_&_Ticket_System.md
- **Updated**: 2026-01-24
- **Component**: Project Manager + Ticket Manager (CLI)
- **Primary responsibility**: Convert planning docs into ticket/task/step execution that produces patches with durable evidence, while keeping user friction low.

## 0) Context and terminology (why this layer exists)

This layer exists because “planning tools” and “LLM coding tools” do not provide a durable, inspectable execution substrate.

It is optimized for:
- **Solo devs and small teams (2–5)** working locally.
- **Patch-Stream development**: Ticket work is a patch stack, not a mutable worktree.
- **Auditable AI execution**: every action produces durable evidence, and long-running work is observable and pausable.
- **User-defined workflows**: teams can define and evolve their own decomposition/validation/repair workflows as files.

### 0.1 Canonical hierarchy (reminder)
(See Core Infrastructure “Terminology (canonical)” for authoritative definitions.)

- **Project** → contains **Tickets**
- **Ticket** → contains **Tasks** and maps 1:1 to a **Patch-Stream ticket stack**
- **Task** → decomposes into **Steps**
- **Step (plan)** → executed as a **step execution** in a **run**, produces one or more patches


## 1) Responsibilities (by component)

### 1.1 Project Manager (PM)
1. Create/select projects.
2. Import planning docs (paste or file path) into WSS.
3. Maintain a derived index for fast listing.
4. Infer ticket dependencies and suggested ordering (heuristic; always editable).
5. Provide a user surface for notifications and for workflow configuration at the project level.

### 1.2 Ticket Manager (TM)
1. Create/open ticket and its Patch-Stream stack.
2. Create tasks (input → steps) with decomposition and approval gate.
3. Execute steps sequentially; each step produces patch(es) on the ticket stack.
4. Run validation workflows (sandbox) and block ticket completion on failure.
5. Manage deviations and evaluation artifacts.
6. Run user-selected workflows (first-class customization).

## 2) Data surfaces (authoritative)

Single source of truth for durable shapes:
- Tech_Plan__Core_Infrastructure.md

### 2.1 WSS docs used directly
- `workspace/projects/<project_id>/project.json`
- `workspace/tickets/<ticket_id>/ticket.json`
- `workspace/tickets/<ticket_id>/tasks/<task_id>/task.json`
- `workspace/runs/<run_id>/run.json`
- `workspace/runs/<run_id>/steps/<step_execution_id>.json`
- (optional) `workspace/projects/<project_id>/workflows/*.yaml`

### 2.2 PGS (jj) surfaces used indirectly
Ticket stacks are in jj; Ticket Manager persists stack metadata in `ticket.json`.

### 2.1 CLI command specifications

This system exposes two interactive shells:

- `/project-manager` — project-level navigation and ticket triage
- `/ticket-manager` — execute a specific ticket end-to-end

Both shells are line-oriented REPLs that call the same underlying `workflowctl` subcommands.

#### 2.1.1 Common interaction rules

- Input is parsed as:
  - tokens separated by whitespace
  - quoted strings supported with `"` (no nested quotes)
- Every command MUST return either:
  - a success message + any created IDs, or
  - a loud error that includes an error code and a path to evidence.

#### 2.1.2 `/project-manager` commands

Minimum command set:

- `help` — show available commands
- `projects list`
- `projects create "<title>"` → prints `project_id`
- `projects open <project_id>` — sets current project context
- `tickets list [--status open|in_progress|blocked|done]`
- `tickets create "<title>"` → prints `ticket_id` (created in `open` status)
- `tickets archive <ticket_id>` (optional)

Integration points:

- Writes to `workspace/projects/<project_id>/project.json`
- Writes to `workspace/tickets/<ticket_id>/ticket.json`
- May trigger index rebuild (see §10)

#### 2.1.3 `/ticket-manager` commands

Minimum command set (within a ticket context):

- `help`
- `open <ticket_id>` — loads ticket + stack context
- `status` — show ticket status + current rev
- `plan` — run decomposition (`task_decompose_v1`) and show step plan summary
- `step run <step_id>` — execute a single step (`step_execute_v1`)
- `run` — execute remaining steps in order
- `validate` — run validation (`ticket_validate_v1`)
- `close` — run validate + evaluation + mark done (if pass)
- `pause` / `resume` — write control actions (Core Flows Flow 12)

Error handling:

- If a command fails, TM MUST:
  - write a notification
  - preserve run artifacts
  - present the next recommended action (retry / investigate / user decision)

#### 2.1.4 How interactive shells integrate with Root runtime

- Long-running commands start a run under `workspace/runs/<run_id>/`.
- The shell streams logs from the run log shards.
- The shell may be detached; progress is observable via:
  - `workflowctl runs list`
  - `workflowctl runs show <run_id>`
  - `workflowctl notifications tail`



## 3) Configuration and workflows (user-defined, low-friction)

### 3.1 Workflow selection model

Every major Ticket Manager action is a workflow invocation:

| TM action | Default workflow_id | Purpose |
|---|---|---|
| task decomposition | `task_decompose_v1` | input → step plan + approvals |
| step execution | `step_execute_v1` | execute a planned step (hydrate → patch → gate) |
| ticket validation | `ticket_validate_v1` | lint/tests/build in a sandbox |
| enhanced rebase | `rebase_enhanced_v1` | rebase + conflict resolution jobs |
| evaluation | `ticket_evaluate_v1` | planned vs implemented gaps report |

#### 3.1.1 Override and precedence (authoritative)

Workflow resolution MUST follow Integration §7.1 precedence, highest to lowest:

1. **CLI file override**: `--workflow-file <path>`  
   - Intended for task-local experimentation.
2. **Project-scoped WSS workflows**:  
   - `workspace/projects/<project_id>/workflows/*.yaml`
3. **Repo-shared workflows** (checked into the repo):  
   - `<repo>/.workflow/workflows/*.yaml`
4. **Repo machine-local workflows** (not committed):  
   - `workspace/workflows/*.yaml`
5. **Built-in workflows** (packaged):  
   - `builtin:<workflow_id>`

Selection flags:

- `--workflow <workflow_id>` selects by ID using the above resolution rules.
- `--workflow-file <path>` selects an explicit file (highest precedence).

If multiple candidates exist at the same precedence level, selection MUST be deterministic:
- prefer exact filename match `<workflow_id>.yaml`
- else fail loudly with `WORKFLOW_AMBIGUOUS`.



## 4) Ticket lifecycle (state machine)

Ticket status is durable and updated with optimistic concurrency (`expected_rev`):

`open → in_progress → blocked → done` (plus `abandoned`)

Rules:
- `done` requires validation workflow success (no bypass by default)
- `blocked` requires an explicit reason field + evidence refs

TM must perform status transitions under `locks/ticket.<ticket_id>.lock`.

Additional clarification:

- Tickets created via `/project-manager tickets create …` start in `open`.
- When `/ticket-manager open <ticket_id>` begins work, it transitions `open → in_progress`.
- If a ticket is created implicitly by Ticket Manager (user starts work immediately), it MUST be created directly in `in_progress`. This is considered “create+start” and should be treated as equivalent to `open` followed immediately by `in_progress`.

## 5) Task lifecycle
Task status is durable and updated by TM (single-writer under the ticket lock):

`open → decomposing → ready → executing → completed`

Additional terminal / interruption states:
- `needs_user_plan` (decomposition gave up; user must edit/approve plan)
- `failed` (execution failed with evidence; may be retried via new task/run)
- `aborted` (explicit user abort)

Rules:
- `needs_user_plan` is resolved only by an explicit user action (`task approve-plan`) or by re-running decomposition with new constraints.
- Retrying does not “loop”; retries produce new run IDs and must add new evidence.



On task creation, TM creates:

```text
workspace/tickets/<ticket_id>/tasks/<task_id>/
  task.json
  input.md
  steps/
  deviations/
  evaluation/
```

`task.json` contains:
- `task_id`, `ticket_id`
- `status`
- references to step definitions in `steps/`
- references to runs/patches produced for the task

## 6) Task decomposition (multi-pass, no fixed iteration cap)

### 6.1 Logical roles (default workflow)
- Pattern discovery (agent): proposes boundary rules and invariants.
- Candidate surfacing (script/tool): produces candidate step plan.
- Approval gate (agent + optional user): approves/denies with rationale.
- Verification (agent): checks overlap/ordering/missing prereqs.

### 6.2 Convergence rules

No fixed max-iteration cap is used as a termination criterion. Instead, decomposition convergence is determined by **repeatable evidence**.

#### 6.2.1 Progress signature v1

A decomposition attempt MUST emit a deterministic progress signature.

Inputs (durable artifacts):

- `task_input_hash`  
  - `sha256` of normalized `tasks/<task_id>/input.md` bytes:
    - CRLF → LF
    - ensure exactly one trailing `\n`

- `candidate_set_hash`  
  - `sha256` of canonical JSON bytes of `steps/candidate_set.json`

- `approval_decision_hash`  
  - `sha256` of canonical JSON bytes of `steps/approval_decision.json`

- `verification_result_hash`  
  - `sha256` of canonical JSON bytes of `steps/verification_result.json`

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

`progress_signature = sha256(canonical_json_bytes(signature_object))`

The signature MUST be persisted in:

- `steps/progress_signature.json`

#### 6.2.2 Repeat detection and loud stop

If the same `progress_signature` repeats for the same `(task_id, workflow_id)`:

- mark the task as `unsplittable`
- write `decomposition_problem_record.md` with evidence refs
- emit a notification and stop

#### 6.2.3 Novelty rule

Each additional pass MUST add new durable evidence, for example:

- new candidate set variants (new step boundaries), or
- new constraints captured in `input.md`, or
- new verification results

If no novelty is present, stop and escalate (no silent looping).

#### 6.2.4 Oscillation detection

Alternating approvals/denials that do not produce a stable step plan are treated as oscillation.

When detected:

- persist the oscillation evidence
- stop and require user input (constraints clarification)



#### 6.2.5 Concurrency control (normative)

Decomposition MUST acquire `locks/task.<ticket_id>.<task_id>.lock` before:
- reading `task.json`
- writing any artifacts under `tasks/<task_id>/steps/` (including `step_plan.yaml` and `candidates/`)
- writing any artifacts under `tasks/<task_id>/deviations/` that are produced during decomposition

If lock acquisition fails:
- emit `E_LOCK_FAILED` including the lock path and (if available) lock holder info
- do not retry automatically (avoid hiding contention)
- instruct the user to check task status or wait for the other process to finish

#### 6.2.6 Worked example (deterministic)

Given the component hashes:

- `task_input_hash` = `sha256:0000000000000000000000000000000000000000000000000000000000000000`
- `candidate_set_hash` = `sha256:1111111111111111111111111111111111111111111111111111111111111111`
- `approval_decision_hash` = `sha256:2222222222222222222222222222222222222222222222222222222222222222`
- `verification_result_hash` = `sha256:3333333333333333333333333333333333333333333333333333333333333333`

The canonical JSON input (sorted keys, no whitespace) is:

```json
{"algo":"sha256","approval_decision_hash":"sha256:2222222222222222222222222222222222222222222222222222222222222222","candidate_set_hash":"sha256:1111111111111111111111111111111111111111111111111111111111111111","kind":"progress_signature","schema_version":1,"task_input_hash":"sha256:0000000000000000000000000000000000000000000000000000000000000000","verification_result_hash":"sha256:3333333333333333333333333333333333333333333333333333333333333333"}
```

Therefore the progress signature is:

- `progress_signature` = `sha256:c5ac6d793c8a71e074903575bbecdefbb19d58fc980bb94a44123294abee1749`
### 6.3 Output artifacts (durable)

The decomposition workflow MUST write these durable artifacts under `tasks/<task_id>/steps/`:

- `step_plan.yaml`  
  - Authoritative step plan for execution (human-readable).

- `candidate_set.json`  
  - Canonical JSON representation of the candidate set used for progress signatures.
  - MUST be written in canonical JSON (keys sorted, no whitespace).

- `approval_decision.json`  
  - Canonical JSON record of approval/denial and any selected candidate identifiers.

- `verification_result.json`  
  - Canonical JSON record of verification checks and outcomes.

- `progress_signature.json`  
  - The computed progress signature (see §6.2.1).

Optional (kept for auditability):

- `step_rationale.md`
- `candidates/*.yaml` (alternate candidates; may be large)
- `decomposition_problem_record.md` (written only when giving up loudly)



### 6.4 Step plan schema (v1; user-editable contract)

`steps/step_plan.yaml` is intentionally human-editable. It is the primary artifact users edit to unblock decomposition or to enforce their own workflow standards.

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

# Optional: global constraints that apply to all steps in this task
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
    depends_on: []          # list of step_ids
    capabilities_required:  # enforced by the runner
      - read_stack
      - apply_patch

  - step_id: step-002
    title: "Run validation"
    kind: tool
    tool:
      workflow: ticket_validate_v1
    depends_on: ["step-001"]
```

**Validation rules (normative)**

Before executing a step plan, the runner MUST validate:

1. `schema_version` is supported (currently only `1`).
2. `ticket_id`, `task_id`, and `steps` are present.
3. `steps` is an array (may be empty).
4. Each step has:
   - a unique `step_id`
   - a supported `kind`
5. `depends_on` references only `step_id`s that exist within the same plan.
6. The dependency graph is acyclic (no circular dependencies).
7. For `kind: patch` steps:
   - `capabilities_required` MUST include `apply_patch`.
8. Unknown top-level or step-level fields are ALLOWED and MUST be preserved (forward compatibility).

Empty plans:
- `steps: []` is VALID and represents “no work needed”.
- Execution of an empty plan MUST:
  - emit a `step_plan_validated` event
  - mark the task `completed` without running patch/tool steps.

On validation failure:
- emit `E_VALIDATION_FAILED` with a list of field-level errors (best-effort)
- do not execute any steps
- preserve the invalid plan as evidence (do not rewrite it)

**Why YAML (tradeoff)**
- diff-friendly, easy to edit, easy to generate from agents, easy to validate.


### 6.5 Recovery when decomposition fails (no infinite loops; user stays unblocked)

If decomposition cannot converge (repeated signature, no novelty, or oscillation), the system must **stop loudly** and hand control to the user with durable artifacts.

**On give-up**
- TM writes:
  - `decomposition_problem_record.md` (what failed, why it gave up, evidence refs)
  - a *draft* `steps/step_plan.yaml` (best attempt so far, even if imperfect)
- TM sets `task.json.status = "needs_user_plan"`
- TM emits a notification containing:
  - paths to the problem record and draft plan
  - the command to continue after editing

**User recovery options (supported)**
1. **Edit the plan directly**  
   - user edits `steps/step_plan.yaml` (or replaces it with a single-step plan)
   - user re-runs: `workflowctl task approve-plan <ticket_id> <task_id> --plan steps/step_plan.yaml`

2. **Provide extra constraints and retry decomposition**  
   - user edits `input.md` or adds a constraints file (project-defined)
   - user re-runs: `workflowctl task decompose <ticket_id> <task_id> --workflow task_decompose_v1`

3. **Abort the task**  
   - user runs: `workflowctl task abort <ticket_id> <task_id>`  
   - TM keeps all evidence and marks task as aborted (auditable)

**Invariant**
- The system never “loops until it works”. If it cannot produce novelty, it gives up with evidence and a manual override path.


## 7) Step execution (patch creation)

For each step (sequential, unless a workflow explicitly enables safe parallelism), the default execution pipeline is:

1. Context hydration (Mode A preferred; Core Flows Flow 8)
2. Patch authoring (agent emits unified diff)
3. Hunk-lint gate (format + dry-run apply; Enhanced Rebase §3.1)
4. Patch apply to the ticket stack (new change in `jj`)
5. Record deviations (if any)
6. Emit `step_stop` with status and evidence refs

Evidence (minimum):

- step doc in WSS (`steps/<step_id>/step.json`)
- patch diff + metadata under `steps/<step_id>/`
- shard events: `step_start`, `tool_*`, `progress`, `step_stop`

### 7.1 Deviation definition

A **deviation** is any intentional, recorded departure from the declared plan or default policies that could affect reproducibility, correctness, or auditability.

Examples:

- Switching execution mode (Mode A → Mode B fallback)
- Expanding sandbox sparse patterns beyond derived defaults
- Skipping a planned sub-step due to a verified no-op condition
- Using an alternate tool command due to capability gating

Deviations are not errors by themselves; they are evidence.

### 7.2 When deviations MUST be recorded

A deviation record MUST be written when:

- the runner changes execution mode or sandbox policy relative to the plan/workflow defaults
- the runner expands hydration scope beyond the step plan file list
- the runner expands sparse patterns beyond derived defaults
- any “fallback path” is taken (copy fallback, manual resolution, tool substitution)

### 7.3 Deviation record format

Deviation files live under:

- `tasks/<task_id>/deviations/<deviation_id>.json`
- optional: `tasks/<task_id>/deviations/<deviation_id>.md` (human narrative)

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

If user approval is required for a deviation, `approved_by` is set and the corresponding approval control action is referenced in `evidence_refs`.

#### 7.3.1 Approval flow (normative)

Approval is REQUIRED when:
- `severity: "error"` AND
- the deviation involves a capability marked `dangerous` (Integration §7.3).

Approval is OPTIONAL for `severity: "warn"` (workflow MAY request it), and NOT REQUIRED for `severity: "info"`.

Approval protocol (v1):

1. Runner writes the deviation record with `approved_by: null`.
2. Runner emits a notification with `requires_action=true` describing what is being approved.
3. Runner writes a control action request envelope:
   - `control_actions/inbox/deviation_approval_request_<deviation_id>.json`
   - `control_kind: "deviation_approval_request"`
   - `deviation_id`, `ticket_id`, `task_id`, `step_id`, `capability`, `approval_timeout_ms`
4. Runner MUST enter the PAUSE protocol (Core Flows Flow 12) until approval is resolved.
5. User responds via CLI:
   - `workflowctl approve-deviation <deviation_id> --approve|--deny [--note "..."]`
   which writes:
   - `control_actions/inbox/deviation_approval_<deviation_id>.json`

Resolution rules:
- On **approve**:
  - runner sets `approved_by` (e.g., `"local_user"`) and records the control action id in `evidence_refs`
  - runner resumes execution
- On **deny**:
  - runner MUST stop loudly and mark the task `needs_user_plan` (or ticket `blocked`) with evidence refs.

Timeout:
- `approval_timeout_ms` default is `300000` (5 minutes).
- On timeout, runner MUST stop loudly (do not auto-approve) and escalate as `needs_user` (Monitoring §5.4.2).


### 7.4 How deviations are used

- Evaluation uses deviations to justify unplanned changes (Enhanced Rebase §4).
- Monitoring/investigation uses deviations as high-signal context when diagnosing failures.



## 8) Validation (sandbox-based, required at ticket close)

Validation is a workflow (`ticket_validate_v1` by default).

Minimum required behavior:
1. Create sandbox (jj workspace) from ticket tip.
2. Capture environment metadata (`env_capture.json`).
3. Run configured commands (see §8.0).
4. Persist raw outputs as artifacts:
   - stdout/stderr
   - junit/json reports when available
5. Produce a structured summary:
   - pass/fail
   - failing commands
   - key error excerpts (bounded)
6. Block ticket close on failure.

Artifacts:
```text
workspace/runs/<run_id>/artifacts/sandbox/validation_summary.json
workspace/runs/<run_id>/artifacts/sandbox/commands/<cmd_id>/{stdout,stderr,meta}.*
```

### 8.0 Validation command result interpretation

A validation workflow executes an ordered list of commands. Each command record MUST include:

- `cmd_id` (string)
- `argv` (array of strings)
- `cwd` (repo-relative path; optional)
- `timeout_ms` (int; optional)
- `success_exit_codes` (array of ints; default `[0]`)
- `optional` (bool; default `false`)
- `fail_on_stderr` (bool; default `false`)

Interpretation rules (normative):

- A command is **pass** if:
  - it exits with `exit_code ∈ success_exit_codes`, AND
  - if `fail_on_stderr=true`, `stderr` is empty
- A command is **fail** if:
  - it exits with an exit code not in `success_exit_codes`, OR
  - it times out, OR
  - the process cannot be started

Timeout:

- A timeout is treated as failure:
  - `status: "timeout"`
  - `exit_code: null`
  - `timed_out: true`

Overall validation result:

- `validation_summary.status = "pass"` only if **all non-optional commands pass**.
- Any failing non-optional command makes the summary `fail`.
- Optional command failures MUST be recorded but MUST NOT block ticket close; they produce a `warn` notification.

stderr/stdout:

- stdout and stderr are always captured as artifacts.
- stderr alone does not fail a command unless `fail_on_stderr=true`.

### 8.1 Recovery when validation fails (ticket close blocked, user not stuck)

Validation failure is not “the end”; it is an input to the next unit of work.

**On validation failure**
- TM MUST:
  - set `ticket.json.status = "blocked"`
  - write a human-readable `validation_report.md` alongside the structured summary
  - emit a notification with:
    - failing command(s)
    - artifact paths (stdout/stderr, reports)
    - the recommended next action (create follow-up task)

**Supported user actions**
1. **Create a follow-up task from the report**
   - `workflowctl task create --ticket <ticket_id> --from-validation <run_id>`
   - TM copies relevant excerpts into the new task’s `input.md` and links back to evidence IDs

2. **Run a repair workflow**
   - `workflowctl run --workflow ticket_repair_v1 --ticket <ticket_id> --run <run_id>`
   - Repair is patch-based and must validate in a sandbox before proposing RESUME/RETRY.

3. **Export for review without closing**
   - Allowed: export stack to a review branch/bookmark for sharing or PR creation
   - Not allowed: marking the ticket `done` while validation is failing

**Invariant**
- Ticket close remains blocked until the required validation workflow passes. Any “unvalidated export” must be clearly labeled and must not flip the ticket to `done`.



## 9) Ticket completion (export policy)

Ticket completion requires:

1. Required validation workflow passes.
2. Export the ticket stack using an explicit export policy.
3. Record export metadata in `ticket.json`.
4. Mark ticket `done`.

**Concurrency (normative)**:
- Export and ticket state updates MUST be performed under:
  - `locks/ticket.<ticket_id>.lock`
  - `locks/branch.<name>.lock` for the export target bookmark/ref (Core §6.3)


### 9.0 Export policy selection

Default export policy:

- `squash`

Selection mechanisms (highest precedence first):

1. CLI flag on close/export:
   - `workflowctl ticket close --export-policy squash|linear`
2. Per-ticket override in `ticket.json`:
   - `ticket.json.export.policy`
3. Global config default:
   - `[export] policy = "squash"`

### 9.1 Export policy semantics

#### 9.1.1 Squash

`squash` exports the ticket as a **single** commit that represents the net diff from `base_rev` → `tip_rev`.

- Create a new commit on top of `base_rev` with:
  - message: derived from ticket title + step summary
  - content: full diff of the ticket stack
- Create or move an export bookmark:
  - `export/<ticket_id>` → the squash commit

#### 9.1.2 Linear

`linear` exports the ticket as a **linear sequence** of commits preserving the ticket’s internal steps.

- Rebase each ticket commit in order onto `base_rev`, producing a new linear chain.
- Create or move an export bookmark:
  - `export/<ticket_id>` → the tip of the exported linear chain

Linear does not preserve any non-linear history; it is “linearized export”.

### 9.2 Export target and outputs

Export produces:

- a bookmark (or branch name) under the local `jj` repo:
  - default: `export/<ticket_id>`
- export metadata persisted in `ticket.json`:

Minimum metadata:

```json
{
  "export": {
    "policy": "squash|linear",
    "bookmark": "export/<ticket_id>",
    "exported_tip": "<commit id>",
    "exported_at": "<rfc3339>",
    "validated": true
  }
}
```

### 9.3 Export scrubbing (shareable bundles)

If the user chooses to share run/ticket evidence:

- TM triggers `workflowctl export scrub`
- scrubber runs secret scan + redaction per Core privacy policy
- produces shareable archive + redaction manifest

### 9.4 Review export (avoid blocking collaboration without lying)

To reduce friction while preserving trust, export supports **two modes**:

1. **Validated export (default; required for `done`)**
   - only allowed when the required validation workflow passes
   - ticket transitions to `done`

2. **Review export (allowed when blocked)**
   - allowed even when validation is failing
   - exports the current patch stack to `review/<ticket_id>`
   - ticket remains `blocked` and is explicitly labeled:
     - `ticket.json.export.validated = false`
     - includes a link to the failing validation report



## 10) Search/indexing (derived index)

Goal: “snappy CLI listing” without requiring external services.

### 10.1 Derived index file

- Path: `workspace/index.json`
- Ownership: root-owned derived artifact (safe to delete + rebuild)

A minimal `index.json` schema:

```json
{
  "schema_version": 1,
  "built_at": "<rfc3339>",
  "projects": [
    { "project_id": "...", "title": "...", "status": "...", "updated_at": "..." }
  ],
  "tickets": [
    { "ticket_id": "...", "project_id": "...", "title": "...", "status": "...", "updated_at": "..." }
  ]
}
```

### 10.2 Rebuild trigger and staleness detection

Index rebuild is driven by an explicit dirty marker:

- Marker path: `workspace/index.dirty`

When a writer modifies any of:
- `workspace/projects/**/project.json`
- `workspace/tickets/**/ticket.json`

it MUST also (atomically) write/update `workspace/index.dirty` with:

```json
{ "schema_version": 1, "dirty_at": "<rfc3339>", "reason": "project_or_ticket_change" }
```

Rebuild rule (normative):

- On any CLI command that needs listings/search:
  - if `workspace/index.json` is missing OR `workspace/index.dirty` exists:
    - rebuild index
    - on success: delete `workspace/index.dirty`

### 10.3 Failure behavior

- If the index is missing or stale and rebuild fails:
  - CLI MUST fall back to scanning `workspace/projects/` and `workspace/tickets/`
  - CLI MUST emit a `warn` notification with the rebuild error and evidence refs
- Index rebuild failure must not block ticket execution.

### 10.4 Manual rebuild

Provide a manual command:

- `workflowctl index rebuild`

This command:
- rebuilds `workspace/index.json`
- clears `workspace/index.dirty` on success
- prints a summary of indexed counts



## 11) Risk register (manager layer)

| Risk | Severity | Control(s) |
|---|---:|---|
| Multiple interactive sessions editing same ticket | Medium | `expected_rev` + ticket lock; loud mismatch failure |
| Decomposition “analysis paralysis” | Medium | progress signature + novelty + explicit give-up record |
| Toolchain drift between machines | Medium | env capture + tool fingerprints; workflow-defined commands |
| Users cannot debug runs | Low | ID-first CLI helpers: tail by run/step, show shard slices; scrubbed export bundles |
| Workflow customization breaks invariants | Medium | workflow schema validation + capability gating; dangerous actions require ack |
