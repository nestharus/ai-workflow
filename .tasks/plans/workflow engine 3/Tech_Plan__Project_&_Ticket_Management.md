# Tech Plan: Project & Ticket Management (Restructured)

- **Doc**: Tech_Plan__Project_&_Ticket_Management.md
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
- Tech_Plan__Core_Infrastructure_&_Data_Model.md

### 2.1 WSS docs used directly
- `workspace/projects/<project_id>/project.json`
- `workspace/tickets/<ticket_id>/ticket.json`
- `workspace/tickets/<ticket_id>/tasks/<task_id>/task.json`
- `workspace/runs/<run_id>/run.json`
- `workspace/runs/<run_id>/steps/<step_execution_id>.json`
- (optional) `workspace/projects/<project_id>/workflows/*.yaml`

### 2.2 PGS (jj) surfaces used indirectly
Ticket stacks are in jj; Ticket Manager persists stack metadata in `ticket.json`.

## 3) Configuration and workflows (user-defined, low-friction)

### 3.1 Workflow selection model
Every major TM action is a workflow invocation:

| TM action | Default workflow_id | Purpose |
|---|---|---|
| task decomposition | `task_decompose_v1` | input → steps plan + approval |
| step execution | `step_execute_v1` | produce patch for a step |
| ticket validation | `ticket_validate_v1` | lint/tests/build in sandbox |
| enhanced rebase | `rebase_enhanced_v1` | rebase + conflict resolution jobs |
| evaluation | `ticket_evaluate_v1` | gaps report |

Users can override workflow selection by:
- project config (`project.json` or project workflow directory)
- repo config (`.workflow/config.toml`)
- CLI flags (`--workflow <id>` or `--workflow-file <path>`)

### 3.2 Project-scoped workflow configuration (recommended UX)
PM provides commands to create/edit workflow files:

- `pm workflow init --project <project_id>`:
  - writes a starter workflow pack under:
    `workspace/projects/<project_id>/workflows/`
- `pm workflow set-default --project <project_id> --for ticket_validate --workflow <workflow_id>`

This keeps customization local and avoids requiring external services.

### 3.3 Validation commands are workflow-defined (trust + flexibility)
The validation workflow defines:
- which commands run (lint/test/build)
- sandbox include patterns (sparse patterns)
- which artifacts must be persisted
- what constitutes “pass/fail”
- on-failure behavior (investigate vs immediate user escalation)

This allows teams to define their own workflows without modifying core code.

## 4) Ticket lifecycle (state machine)

Ticket status is durable and updated with optimistic concurrency (`expected_rev`):

`open → in_progress → blocked → done` (plus `abandoned`)

Rules:
- `done` requires validation workflow success (no bypass by default)
- `blocked` requires an explicit reason field + evidence refs

TM must perform status transitions under `locks/ticket.<ticket_id>.lock`.

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

### 6.2 Convergence rules (replace “max iterations”)
No fixed max-iteration cap is used as a termination criterion. Instead:

1. **Progress signature** recorded per attempt:
   `sig = hash(task_input_hash + candidate_set + approval_decision + verification_result)`
2. If the same signature repeats:
   - mark “unsplittable”
   - write `decomposition_problem_record.md` with evidence refs
   - raise a notification and stop (loud give-up)
3. **Novelty rule**:
   - each additional pass must add new evidence or terminate
4. **Oscillation detection**:
   - alternating approvals/denials without producing valid artifacts → stop and escalate

### 6.3 Output artifacts (durable)
Decomposition workflow writes:
- `steps/step_plan.yaml` (authoritative step plan)
- `steps/step_rationale.md`
- optional: `steps/candidates/*.yaml` (kept for auditability)

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

**Validation rules**
- `schema_version`, `ticket_id`, `task_id`, and `steps[]` are required.
- `step_id` must be unique within the task.
- `kind=patch` steps must include `capabilities_required` including `apply_patch`.
- Unknown keys are allowed but preserved (forward-compatible), unless a workflow opts into “strict schema”.

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

For each step (sequential, unless a workflow explicitly enables safe parallelism):

1. Context hydration (Mode A preferred).
2. Step execution agent produces a patch.
3. Engine runs hunk-lint (format + dry-run apply).
4. Patch is applied to jj ticket stack (new change).
5. Deviations (if any) are written to `deviations/` and logged.
6. Step emits `step_stop` with status and evidence refs.

Evidence:
- step doc in WSS
- patch id recorded in task/ticket metadata
- shard events: `step_start`, `tool_*`, `progress`, `step_stop`

## 8) Validation (sandbox-based, required at ticket close)

Validation is a workflow (`ticket_validate_v1` by default).

Minimum required behavior:
1. Create sandbox workspace from ticket tip.
2. Capture environment metadata (`env_capture.json`).
3. Run configured commands.
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
1. validation workflow passes
2. export stack using policy:
   - `squash` (default) or `linear`
3. record export metadata in `ticket.json`
4. mark ticket `done`

### 9.1 Export scrubbing (shareable bundles)
If user chooses to share run/ticket evidence:
- TM triggers `workflowctl export scrub`
- scrubber runs secret scan + redaction per Core privacy policy
- produces shareable archive + redaction manifest

### 9.2 Review/export modes (avoid blocking collaboration without lying)

To reduce friction while preserving trust, export supports **two modes**:

1. **Validated export (default; required for done)**
   - only allowed when the required validation workflow passes
   - ticket transitions to `done`

2. **Review export (allowed when blocked)**
   - allowed even when validation is failing
   - exports the current patch stack to a review branch/bookmark
   - ticket remains `blocked` and is explicitly labeled:
     - `ticket.json.export.review_only = true`
     - includes a link to the failing validation report

This supports sharing work-in-progress without misrepresenting correctness.


## 10) Search/indexing (tradeoffs)

Goal: “snappy CLI listing” without embedding dependencies by default.

### Selected default
- keyword + fuzzy search over:
  - project titles/names
  - ticket titles/names
  - (optional) doc filenames
- derived index file in WSS:
  - `workspace/index.json` (root-owned derived artifact)

### Optional (user-enabled)
- embedding-based search for large-scale projects, behind an explicit opt-in flag
- embeddings must be stored locally and treated as sensitive artifacts (scrubbed on export)

## 11) Risk register (manager layer)

| Risk | Severity | Control(s) |
|---|---:|---|
| Multiple interactive sessions editing same ticket | Medium | `expected_rev` + ticket lock; loud mismatch failure |
| Decomposition “analysis paralysis” | Medium | progress signature + novelty + explicit give-up record |
| Toolchain drift between machines | Medium | env capture + tool fingerprints; workflow-defined commands |
| Users cannot debug runs | Low | ID-first CLI helpers: tail by run/step, show shard slices; scrubbed export bundles |
| Workflow customization breaks invariants | Medium | workflow schema validation + capability gating; dangerous actions require ack |
