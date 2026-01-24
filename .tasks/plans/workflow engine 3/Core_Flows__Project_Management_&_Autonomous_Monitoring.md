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
- Tech_Plan__Core_Infrastructure_&_Data_Model.md

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
3. Set ticket status `in_progress` (with `expected_rev`).

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

For each step (sequential by default):

1. Hydrate context (Mode A by default).
2. Generate patch.
3. Hunk-lint (fast reject).
4. Apply patch to jj stack.
5. Record deviations if needed.
6. Emit `step_stop`.

Evidence:
- step doc in WSS
- patch id recorded
- shard events: `step_start`, `tool_*`, `progress`, `step_stop`

---

## Flow 9 — Validation (sandbox; workflow-driven; recovery-first)

**Trigger**: user requests validation or attempts to close ticket

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
   - TM sets `ticket.json.status = "blocked"`
   - TM writes `validation_report.md` and emits a notification including:
     - failing command(s)
     - artifact paths and evidence IDs
     - recommended next action

5. **User recovery options**
   - Create follow-up task: `workflowctl task create --ticket <ticket_id> --from-validation <run_id>`
   - Run repair workflow: `workflowctl run --workflow ticket_repair_v1 --ticket <ticket_id> --run <run_id>`
   - Export for review (without closing): `workflowctl export --ticket <ticket_id> --mode review`

---

## Flow 10 — Ticket close/export (scrub-aware, trust-preserving)

**Trigger**: user requests “close ticket”

1. **Require validation**
   - Responsibility: prevent claiming “done” on failing code
   - Owner: TM
   - Rule: required validation workflow MUST have a passing result for the current ticket tip.

2. **If validation is failing**
   - TM blocks close (ticket remains `blocked`)
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

## Flow 12 — PAUSE/RESUME protocol (mandatory)

### Request (control action)
`control_actions/inbox/pause.<request_id>.json`

```json
{
  "schema_version": 1,
  "request_id": "01...",
  "action_type": "pause",
  "target": { "step_execution_id": "01..." },
  "deadline_ms": 10000
}
```

### ACK (step writes)
`control_actions/ack/pause.<request_id>.<step_execution_id>.json`

```json
{
  "schema_version": 1,
  "request_id": "01...",
  "action_type": "pause",
  "run_id": "01...",
  "step_execution_id": "01...",
  "ack_ts": "2026-01-24T00:00:00Z",
  "result": "acknowledged",
  "details": {
    "tool_subprocesses_stopped": true,
    "logs_flushed": true,
    "wss_mutations_stopped": true
  }
}
```

Paused definition:
- no tools running, no WSS mutations, control loop waiting, logs flushed.

If cannot ACK:
- step emits `pause_failed` evidence and requests investigation
- root spawns investigator

---

## Flow 13 — Spawn-step (flat orchestration)

Agents request child steps by writing a `spawn_step` control action.
Root validates, spawns as a direct child, and writes an ACK with `child_step_execution_id`.

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
