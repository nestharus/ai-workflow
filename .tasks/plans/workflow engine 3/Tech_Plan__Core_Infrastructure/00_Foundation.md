# Core Infrastructure — Foundation

- **Doc**: Tech_Plan__Core_Infrastructure/00_Foundation.md
- **Updated**: 2026-01-26
- **Library**: `workflow_engine.core.foundation`
- **Depends on**: _none_
- **Primary responsibility**: Canonical terminology + product priorities + global invariants that every other core library MUST obey.

This spec is the shared base for the rest of Core Infrastructure. For the full doc map, see the root index: `../Tech_Plan__Core_Infrastructure.md`.

## 0) What changed vs prior drafts (risk reductions)

This revision closes previously identified gaps by adding **fully-specified** policies for:

- **Cross-platform durability** (including Windows-native recovery semantics) via:
  - atomic writes (tier-aware)
  - write-ahead journals for critical mutations
  - integrity checks (`fsck`) and deterministic recovery (`recover`)
- **Configuration system**:
  - a single config format (TOML)
  - explicit precedence
  - schema validation + redacted config logging
- **Secrets / sensitive data**:
  - OS keychain-backed secrets store (Keyring)
  - mandatory redaction for any outbound data (LLM calls + exports)
  - export scrubber (shareable bundles without secrets)
- **Dependency management**:
  - `doctor` + `bootstrap` flows
  - explicit `jj` feature/version requirements
- **Reproducibility (without heavy services)**:
  - environment capture for every sandbox run
  - tool fingerprinting and durable tool conclusions keyed by fingerprints

No open responsibilities remain in this document set: every responsibility implied by the system goals is assigned to a component and has durable evidence outputs.


## 0.1) Terminology (canonical)

This document set uses the following canonical terms. New specs and code SHOULD reuse these names to avoid drift.

### Core planning/execution hierarchy
- **Project**: a collection of related tickets under a shared baseline.
- **Ticket**: one unit of work. **Canonical mapping: Ticket ⇄ Patch-Stream stack (PGS/jj)**.
- **Task**: a user-provided input inside a ticket (often “do X”), decomposed into steps.
- **Step (plan step)**: a planned unit of work within a task. `step_id` is the *definition ID* (stable within a task).
- **Run**: a runtime execution group (`run_id`) that groups one or more step executions.
- **Step execution**: the runtime instance of executing a step (`step_execution_id`, `writer_id`, log shard). A step execution is owned by one OS process.

### Patch-Stream terminology
- **Patch-Stream**: the *product-level* development model: tickets are patch stacks; steps produce patches; integration is rebasing stacks.
- **PGS (Patch Graph Store)**: the *storage interface* that implements Patch-Stream. Default backend: **jj**.
- **Ticket stack / patch stack**: the PGS/jj change stack for a ticket (tracked by a bookmark).
- **Patch**: an atomic change appended to a ticket stack (implemented as a jj change).

### Evidence and control
- **WSS (Workspace State Store)**: durable documents + artifacts under the runtime root.
- **Logs Store**: append-only sharded JSONL logs; one shard per step writer.
- **Queues**: filesystem maildir-like queues for notifications and control actions.
- **Evidence**: the durable truth used for debugging and recovery = **WSS + Logs + PGS**.

### “Flow” vs “Workflow”
- **Flow**: a user-facing responsibility / journey (documented in *Core Flows*). Flows are stable.
- **Workflow**: a file-defined automation that implements part of a flow (decomposition, validation, repair). Workflows are user-overridable.

### Sandbox vs hydration
- **Virtual hydration**: reconstruct file content at a given revision without checking out a working copy.
- **Sandbox**: a disposable, materialized environment used to run tools (lint/tests/build/search). In this system, sandboxes are implemented as **jj workspaces**.

### Workspace naming (avoid overload)
The word “workspace” is overloaded in tools and in English. This spec set uses these rules:

- **WSS root directory**: the directory named `workspace/` under the runtime root. Always refer to this concept as **WSS** or **WSS root**, never “workspace” unqualified.
- **jj workspace**: a Jujutsu working copy created by `jj workspace add`. Always refer to as **jj workspace**.
- **Sandbox**: an ephemeral jj workspace created under `~/.workflow/repos/<repo_uid>/sandboxes/...` for tool execution.

### ID classes (semantic vs generated)

**Semantic IDs (human-meaningful strings)**:
- `project_id`, `ticket_id`, `task_id`, `step_id`
- `workflow_id` (workflow definition ID, e.g. `task_decompose_v1`)
- `agent_id` (agent definition ID, e.g. `approval_agent_v1`)

Semantic IDs MUST be filename-safe (`[A-Za-z0-9._-]`) and MUST NOT assume global uniqueness unless explicitly scoped (e.g., `step_id` is scoped to its workflow/task).

**Generated IDs (ULID)**:
- `run_id`, `step_execution_id`, `request_id`, `notification_id`
- `writer_id`, `bundle_id`, `conclusion_id`, `journal_id`, `op_id`, `sandbox_id`

Generated IDs are always machine-generated and globally unique with extremely high probability.

**Derived IDs**:
- `repo_uid` (derived once, then persisted in `repo.json`)

### “Agent” terminology

- **Agent definition (prompt)**: a markdown file used as a prompt template, addressed by `agent_id`.
- **Agent step**: a workflow step with `kind: agent` that results in a step execution process running an agent loop.
- **Model invocation / LLM call**: a single call to a model provider API. In this system, LLM calls MUST be executed via a cancellable subprocess boundary (Monitoring §3.3).

### “Patch” vs “jj change”
- In this spec set, **patch** refers to the logical change unit created by a step.
- In `jj`, the concrete unit is a **change** with a `change_id`. When referencing `jj` outputs, use `change_id` / `commit_id` precisely.


## 1) Product priorities and non-negotiable invariants (locked)

### 1.1 Product priorities (decision order)

1. **Trust**
   - durability across crash/power loss (within platform limits)
   - correctness and auditability (ID-driven evidence)
   - privacy and secrets safety (no accidental exfiltration)
2. **Friction**
   - no database service, no daemon requirement
   - minimal external installs (auto-bootstrap where possible)
   - workflows are file-based and editable
3. **Performance**
   - optimize where cheap (batch hydration, sparse sandboxes)
   - never at the cost of trust or silent failure

### 1.2 Global invariants

These apply to every component and flow unless an explicit exception is documented here.

1. **Local-first operation**
   - The runtime is local-only (single machine).
   - Network is **optional** and only used for model providers when enabled (see §12).
2. **Durable truth**
   - **WSS** documents and artifacts
   - **Logs Store** (sharded JSONL)
   - **PGS** (jj-backed patch stacks)
3. **Step logging always on**
   - step enter/exit + key events are mandatory
   - dynamic tracing is optional and enabled via durable override
4. **Flat orchestration**
   - the **root runtime** owns all step/agent OS processes (no step spawns steps directly)
5. **Mandatory PAUSE**
   - pause requests and acknowledgements are durable and auditable
6. **No silent termination**
   - no fixed “max iteration” caps as termination criteria
   - stop conditions must be **evidence-based** (progress/novelty/oscillation) with explicit give-up records
7. **User-defined workflows are first-class**
   - workflows are file-defined, schema-validated, capability-gated, and produce durable evidence

