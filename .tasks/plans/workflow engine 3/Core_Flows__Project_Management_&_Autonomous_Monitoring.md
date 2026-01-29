# Core Flows: Project Management & Autonomous Monitoring (Restructured)

- **Doc**: Core_Flows__Project_Management_&_Autonomous_Monitoring.md
- **Updated**: 2026-01-24
- **Component**: Flow definitions (UX responsibilities expressed as step sequences)
- **Primary responsibility**: Define “what happens” in user-facing terms, with explicit evidence boundaries and workflow customization hooks.

## 0) Flow conventions (how to read this file)

### Actors
- **User**
- **Project Manager (PM)** — interactive CLI
- **Ticket Manager (TM)** — interactive CLI
- **Root Runtime (Root)** — orchestration process
- **Step Process (Step)** — executes a step, owns its log shard
- **WSS**, **Logs**, **Queues**, **PGS (jj)**, **Sandbox**

### Evidence contract (always)
Every flow step specifies:
- **Responsibility** (what it must accomplish)
- **Owner** (which component owns it)
- **Durable evidence** (what must be written so we can debug after a crash)

Global invariants and data shapes are defined in:
- Tech_Plan__Core_Infrastructure.md

---

## Flow 0 — Install + init + first run (mental model + doctor)

**Trigger**: User wants to start using the system in a repo for the first time

0. **Install the tool (one-time, per machine)**
   - Responsibility: make `workflowctl` and the interactive CLIs available on PATH
   - Owner: user + installer (binary / bootstrap script / Python package)
   - Evidence: installer may write `~/.workflow/install_manifest.json` (optional)

1. **Repo init (one-time, per repo)**
   - Responsibility: create minimal repo-local integration points without adding services
   - Owner: `workflowctl init`
   - Actions:
     - create `<repo_root>/.workflow/workflows/` (committable workflow definitions)
     - optionally create `<repo_root>/.claude/commands/` shims that call `workflowctl`
     - optionally update `.gitignore` to avoid committing runtime artifacts
   - Evidence:
     - `workspace/runs/<run_id>/artifacts/init_report.json`

2. **Derive/load repo_uid**
   - Responsibility: create/load `repo.json` and establish runtime root path
   - Owner: CLI entrypoint
   - Evidence: `~/.workflow/repos/<repo_uid>/repo.json`

3. **Doctor check (first-run gate)**
   - Responsibility: validate dependencies, permissions, and runtime writability
   - Owner: `workflowctl doctor` (invoked implicitly once per new repo, then on demand)
   - Evidence:
     - `workspace/runs/<run_id>/artifacts/doctor_report.json`
     - notification if blocking issues exist

4. **Bootstrap tools (optional, friction reducer)**
   - Responsibility: install missing `jj` locally when allowed, without system package managers
   - Owner: `workflowctl bootstrap`
   - Evidence:
     - tool install metadata under `~/.workflow/tools/...`
     - config update in repo-local `workspace/config.toml` (machine-local)

5. **User mental model (printed once, then discoverable)**
   - Responsibility: set expectations to reduce “where did my stuff go?” confusion
   - Owner: CLI UX
   - Required messaging:
     - durable runtime root is `~/.workflow/` (not committed to git)
     - runs/steps/notifications are navigated by stable IDs
     - patch stacks live in jj (PGS) and are tied 1:1 to tickets
     - workflows are files and are expected to be customized

---

## Flow 1 — Project Manager entry (select/create project)

**Trigger**: User runs `/project-manager`

1. **Load effective config**
   - Responsibility: load config precedence and log redacted config hash
   - Owner: PM
   - Evidence: log event `config_loaded` (manifest + hash)

2. **Load projects**
   - Responsibility: list projects via derived index or scan
   - Owner: PM
   - Evidence: read `workspace/index.json` (optional) or `workspace/projects/*`

3. **Select/create project**
   - Responsibility: create `project.json` and docs directory when needed
   - Owner: PM
   - Evidence: `workspace/projects/<project_id>/project.json`

---

## Flow 2 — Configure workflows (project-scoped customization)

**Trigger**: User chooses “Configure workflows” in PM (or runs `pm workflow ...`)

1. **Initialize workflow directory**
   - Responsibility: create a project-scoped workflow pack with safe defaults
   - Owner: PM
   - Evidence: `workspace/projects/<project_id>/workflows/*.yaml`

2. **Set default workflows**
   - Responsibility: bind workflows to actions (decompose/validate/etc)
   - Owner: PM
   - Evidence: fields in `project.json` referencing workflow_ids

3. **Validate workflows**
   - Responsibility: schema validation + capability check
   - Owner: Root/workflow registry
   - Evidence: `workspace/runs/<run_id>/artifacts/workflow_validation_report.json`

---

## Flow 3 — Load documentation (project/ticket docs)

**Trigger**: User pastes markdown or provides file path

1. Store document under:
   - project-level: `workspace/projects/<project_id>/docs/`
   - ticket-level: `workspace/tickets/<ticket_id>/docs/` (if applicable)
2. Update derived index (optional)
3. Confirm stored path

Evidence: the markdown file itself + optional index update.

---

## Flow 4 — Ticket ordering / dependencies

**Trigger**: User requests ordering

1. Load tickets for project (scan or index).
2. Infer dependencies from ticket docs (heuristic).
3. Persist ordering suggestions (editable).
4. Print dependency tree.

Evidence:
- ordering suggestions persisted with `expected_rev` to avoid lost updates.

---

## Flow 5 — Open Ticket Manager

**Trigger**: PM selects next runnable ticket

- PM prints command:
  `/ticket-manager --project <project_id> --ticket <ticket_id>`

Evidence: none required (UX convenience).

---

## Flow 6 — Ticket open/create (Patch-Stream)

**Trigger**: User runs Ticket Manager for a ticket

1. Load or create `workspace/tickets/<ticket_id>/ticket.json`.
2. If no stack metadata:
   - create jj ticket stack and bookmark
   - store stack metadata into `ticket.json`
3. Set ticket status (See `project_ticket_system/Lib__Lifecycle.md` §1 for the complete authoritative state machine):
   - If ticket was newly created by TM: create directly in `in_progress` (creation implies start)
   - Else: apply the Lifecycle §1 start-work transition
   (also set `expected_rev`).

Evidence:
- `ticket.json`
- jj stack/bookmark existence

---

## Flow 7 — Task input → decomposition (workflow-driven, user-unblockable)

**Trigger**: User pastes a task description

1. **Create task container**
   - Responsibility: allocate durable location for task inputs and outputs
   - Owner: TM
   - Evidence:
     - `workspace/tickets/<ticket_id>/tasks/<task_id>/task.json`
     - `workspace/tickets/<ticket_id>/tasks/<task_id>/input.md`

2. **Start a run**
   - Responsibility: create an execution envelope for decomposition + later step execution
   - Owner: Root
   - Evidence:
     - `workspace/runs/<run_id>/run.json`
     - log shards initialized for decomposition steps

3. **Execute decomposition workflow** (`task_decompose_v1` by default)
   - Responsibility: produce an *authoritative* step plan file (even if only a draft)
   - Owner: TM (workflow runner) + Root (spawns steps)
   - Outputs:
     - `steps/step_plan.yaml` (plan)
     - `steps/step_rationale.md` (why these boundaries)
     - optional `steps/candidates/*.yaml` (discardable but kept for auditability)
   - Evidence: decomposition events in log shards (progress signatures + decisions)

4. **Approval gate**
   - Responsibility: ensure the system does not silently proceed with a bad plan
   - Owner: workflow-defined (agent-only or agent+user)
   - Evidence:
     - `steps/approval.json` (decision, rationale, evidence refs)

5. **Convergence or give-up (no infinite loops)**
   - If decomposition **converges**:
     - TM sets `task.json.status = "ready"`
   - If decomposition **cannot converge** (repeat signature / no novelty / oscillation):
     - TM sets `task.json.status = "needs_user_plan"`
     - TM writes `decomposition_problem_record.md`
     - TM emits a notification that includes:
       - paths to the draft plan + problem record
       - the exact command to continue

6. **User unblock path (always available)**
   - User may edit `steps/step_plan.yaml` directly (or replace with a single-step plan).
   - User then runs:
     - `workflowctl task approve-plan <ticket_id> <task_id> --plan steps/step_plan.yaml`
   - TM marks task ready and execution proceeds to Flow 8.

---

## Flow 8 — Step execution (patch creation; workflow-driven)

**Goal**: Execute a single planned step and produce a durable patch + evidence with no silent failures.

Inputs (minimum):

- `ticket_id`
- `step_id` (semantic ID from step plan, e.g., `step-001`)
- `step_execution_id` (ULID for this execution instance)
- `step_plan_item` (from `tasks/<task_id>/steps/step_plan.yaml`)

Outputs (durable evidence):

- `workspace/runs/<run_id>/artifacts/steps/<step_execution_id>/patch.diff` (unified diff; may be empty only if explicitly allowed)
- `workspace/runs/<run_id>/artifacts/steps/<step_execution_id>/patch_meta.json`
- `workspace/runs/<run_id>/artifacts/steps/<step_execution_id>/hydration_manifest.json`
- `workspace/runs/<run_id>/artifacts/steps/<step_execution_id>/hunk_lint.json` (Stage 1 result)
- logs for any tool runs
- optional `deviations/<deviation_id>.md` (see Project & Ticket Management §7.3)

### 8.0 Identifier contract

- `step_id`: semantic identifier from `tasks/<task_id>/steps/step_plan.yaml` (e.g., `step-001`)
- `step_execution_id`: ULID generated when the step execution begins
- All artifact paths use `step_execution_id`
- All log events include both identifiers for correlation

See Core Infrastructure §4.1 for ID definitions.

### 8.1 Mode selection

Step execution supports two modes (Integration §6):

- **Mode A (virtual hydration)**: read files directly from VCS state without a checkout
- **Mode B (sandbox)**: create a sandbox, run tools there, then translate results back into patches

Sandbox lifecycle timing is context-specific; see Integration §9.2.0.

Mode selection is policy-driven (Integration §6). Core rule:

- Prefer Mode A unless:
  - the workflow step declares `sandbox.required: true` (Workflow schema §7.2.5), or
  - virtual hydration is not possible for required inputs (binary/too-large/unsupported), or
  - an earlier guarded failure triggered a Mode B fallback.

### 8.2 Hydration protocol

Hydration is **deterministic** and driven by the step plan. The runner must not guess silently.

#### 8.2.1 Hydration scope

Primary hydration set = the file list declared by the step plan item:

- `step.inputs.files[*].path` (Project & Ticket Management §6.4)

Each file entry may include:

- `rev` (revset string; default `ticket.tip`)
- `slice` (optional; line range for prompt-size control)

No automatic dependency-closure heuristic is applied by default.

If additional context is needed, the step agent must request it explicitly via the gateway hydration tools; these requests are logged and persisted in `hydration_manifest.json`.

#### 8.2.2 Hydration execution

For each distinct `rev` referenced in the file list:

1. Call `workflow_engine.invoke` with subcommand `hydrate` (Integration §8) for the required paths.
2. Store a `hydration_manifest.json` with:
   - requested paths
   - resolved revisions
   - per-path status (`ok|not_found|binary|too_large|error`)
   - content hashes and blob refs (if applicable)

#### 8.2.3 Hydration failure handling

Hydration failures are handled loudly.

- `not_found`:
  - Allowed only when the step is permitted to create the file.
  - The manifest records `exists=false` and the step runner provides an empty virtual file to the patch author.

- `binary` / `too_large` / `error`:
  - If Mode A was selected:
    - the runner MUST attempt a single **Mode B fallback** when allowed by policy and sandbox backend is available
    - the fallback is recorded as a deviation with `kind: mode_fallback`
  - If Mode B is unavailable or the fallback also fails:
    - the step fails and the workflow applies the step’s `on_failure` policy (Workflow schema §7.2.7)

### 8.3 Agent handoff contract

The step runner passes a single structured input object to the patch author agent:

- `context`:
  - `ticket_id`
  - `step_id`              # semantic step identifier from plan (e.g., step-001)
  - `step_execution_id`    # ULID for this execution instance
  - `run_id`
  - `base_rev`, `tip_rev`
  - `mode` (`A|B`)
  - `allowed_write_paths` (derived from step plan)
- `hydration`:
  - `manifest_ref` (path to `hydration_manifest.json`)
  - `files[]`:
    - `path`
    - `rev`
    - `content_inline` (for small text files) **or** `blob_ref`
    - `sha256`
    - `is_binary`
    - `slice` (if applied)
- `artifacts`:
  - references to prior step outputs required for continuity

The runner may inline file content into the LLM prompt, but the durable contract is the manifest + blob refs.

### 8.4 Patch generation and gating

1. Patch author agent emits:
   - unified diff (required)
   - patch metadata (rationale, touched paths, expected effects)
2. Stage 1 hunk-lint runs (Enhanced Rebase & Evaluation §3):
   - validates unified diff structure
   - enforces scope: patch MUST NOT modify paths outside `allowed_write_paths`
   - computes a stable `failure_signature` on failure
3. If hunk-lint passes:
   - apply patch to the ticket stack (PGS adapter)
   - persist evidence and update `ticket.json` progress
4. If a sandbox was created for the step, the runner MUST destroy it (unless retained by policy) after patch application + evidence persistence and before emitting `step_stop` (Integration §9.2.0).
5. Emit `step_stop` with status + evidence refs.



## Flow 9 — Validation (sandbox; workflow-driven; recovery-first)

**Trigger**: user requests validation or attempts to close ticket

Sandbox lifecycle rules for validation are defined in Integration §9.2.0.

1. **Create sandbox from ticket tip**
   - Responsibility: provide a tool-execution environment without mutating durable state
   - Owner: Root (sandbox runner)
   - Evidence:
     - sandbox metadata artifact (`env_capture.json`)
     - sandbox creation events in logs

2. **Run validation workflow** (`ticket_validate_v1` by default)
   - Responsibility: run workflow-defined commands (lint/tests/build) and persist outputs
   - Owner: workflow runner + sandbox runner
   - Evidence:
     - `workspace/runs/<run_id>/artifacts/sandbox/validation_summary.json`
     - stdout/stderr artifacts per command
     - log events `tool_start/tool_stop` + `progress`

3. **If validation passes**
   - TM keeps ticket eligible for close.

4. **If validation fails (ticket becomes blocked)**
   - TM transitions ticket `in_progress → blocked` (see `project_ticket_system/Lib__Lifecycle.md` §1)
   - TM MUST record `reason="validation_failure"`, `evidence_refs=[validation_run_id]`, and `blocker_kind="validation_failure"`
   - TM writes `validation_report.md` and emits a notification including:
     - failing command(s)
     - artifact paths and evidence IDs
     - recommended next action

5. **User recovery options**
   - Create follow-up task: `workflowctl task create --ticket <ticket_id> --from-validation <run_id>`
   - Run repair workflow: `workflowctl run --workflow ticket_repair_v1 --ticket <ticket_id> --run <run_id>`
   - Export for review (without closing): `workflowctl export --ticket <ticket_id> --mode review`
   - Recovery actions transition `blocked → in_progress` when the blocker is resolved (see `project_ticket_system/Lib__Lifecycle.md` §1)
     - On repair workflow success, TM transitions `blocked → in_progress` with `reason="blocker_resolved"`

---

## Flow 10 — Ticket close/export (scrub-aware, trust-preserving)

**Trigger**: user requests “close ticket”

1. **Require validation**
   - Responsibility: prevent claiming “done” on failing code
   - Owner: TM
   - Rule: required validation workflow MUST have a passing result for the current ticket tip.

2. **If validation is failing**
   - TM blocks close (ticket remains in `blocked` state; no transition; see `project_ticket_system/Lib__Lifecycle.md` §1)
   - TM prints the path to the latest validation report and the next action commands
   - Optional: user may export **for review only** (does not mark done)

3. **Export stack (validated path)**
   - Responsibility: materialize the ticket stack to the chosen export policy
   - Owner: TM + PGS adapter
   - Policies:
     - `squash` (default)
     - `linear`
   - Evidence:
     - export metadata written into `ticket.json`
     - export artifact refs (commit IDs, tip change ID)

4. **Mark ticket done**
   - Responsibility: finalize ticket state only after validated export
   - Owner: TM
   - Evidence: `ticket.json.status="done"` with export metadata

5. **Scrub-aware sharing (optional)**
   - User may run `workflowctl export scrub --ticket <ticket_id> [--run <run_id>]`
   - Scrubber produces a shareable archive + a redaction manifest.

---

## Flow 11 — Enhanced rebase (conflicts as data; workflow-driven)

1. Acquire ticket lock.
2. Rebase stack onto new parent.
3. For each conflict: gather evidence + spawn resolver.
4. Apply resolution patch.
5. Persist conflict resolution record.
6. Escalate with notification if needed.

Evidence: conflict record + evidence refs.

---

## Flow 12 — PAUSE/RESUME protocol

**Goal**: Provide a reliable, evidence-driven way to pause and resume runs without silent failure.

### 12.1 Control action transport

Control actions are file-based envelopes in the WSS:

- Inbox: `workspace/control/inbox/`
- Outbox: `workspace/control/outbox/`

A control action is a JSON document with required fields (Core Infrastructure §5.2) plus:

- `control_kind` (string enum): `pause|resume|ack|kill_request|user_decision|notification_ack`
- `run_id` (string)
- `step_process_id` (string, optional)
- `created_at` (RFC3339 timestamp)
- `deadline_ms` (int, optional)

### 12.2 Discovery mechanism

Step processes MUST discover control actions via polling, and MAY additionally use OS file watchers:

- `poll_interval_ms` default: `250`
- The poll loop MUST be integrated into the step process main loop such that:
  - a pause request is observed even during long agent/tool operations (at latest, between operations)

### 12.3 Deadline semantics

If a control action includes `deadline_ms`, the deadline is measured from `created_at`:

- `deadline_at = created_at + deadline_ms`

This avoids ambiguity about when the step “received” the request.

If the step observes a request after `deadline_at`, it still MUST ACK, but the ACK MUST indicate `deadline_missed: true`.

### 12.4 PAUSE request

Root writes `pause.json` to `control/inbox/`:

```json
{
  "schema_version": 1,
  "control_kind": "pause",
  "run_id": "<run_id>",
  "step_process_id": "<optional>",
  "created_at": "2026-01-24T00:00:00Z",
  "deadline_ms": 10000,
  "reason": "user_requested"
}
```

### 12.5 ACK contract

On observing a PAUSE request, the step process MUST write `pause_ack.json` to `control/outbox/` with:

- `control_kind: "ack"`
- `ack_for`: ULID of the PAUSE request
- `ack_at`: timestamp
- `result` (enum):
  - `paused` — step entered paused state at a safe point
  - `cannot_pause` — step is in a non-interruptible operation (must include reason)
  - `already_finished` — step already completed
  - `investigating` — step could not pause cleanly and is requesting investigation

### 12.6 Root behavior on missed ACK deadline

If Root does not observe an ACK by `deadline_at`:

1. Root writes a **notification**:
   - severity: `warn`
   - kind: `pause_ack_timeout`
   - includes: `run_id`, `step_process_id`, `deadline_at`
2. Root spawns an investigator (`investigate_v1`) with bounded evidence:
   - last N run events
   - step heartbeat status (if available)
   - the PAUSE request envelope

Root MUST NOT silently continue execution after a pause request.

### 12.7 Forced termination policy

Root MUST NOT force-kill a step solely because the ACK is late.

Forced termination is allowed only when one of these conditions holds:

- The user explicitly requested a kill (`kill_request`) **or**
- Investigator concludes the step is wedged and recommends termination **and**
- Root has evidence the step is unresponsive (no heartbeat beyond `heartbeat_timeout_ms`)

A forced termination MUST be recorded as a deviation and must emit a loud notification.

### 12.8 RESUME

RESUME is symmetric:

- Root writes `resume.json` to inbox.
- Step ACKs and exits paused state at the next safe point.



## Flow 13 — Spawn-step (flat orchestration)

Agents request child steps by writing a `spawn_step` control action.
Root validates, spawns as a direct child, and writes an ACK with `child_step_execution_id`. # ULID for child execution instance

Evidence: control action file + ACK + child step doc.

---

## Flow 14 — Autonomous monitoring loop (observe → pause → investigate → repair)

1. Detect anomaly (missing heartbeat, repeated signature, no-progress tool, queue/journal anomalies).
2. Request PAUSE and optionally enable trace override.
3. Investigator classifies and produces a resume plan.
4. Repair agent (if applicable) generates patch and validates.
5. Root resumes/retries or escalates to user.

Evidence:
- monitor events in logs
- investigation bundle artifacts
- conclusions updated when patterns repeat
