# Tech Plan: Integration & File Structure (Restructured)

- **Doc**: Tech_Plan__Integration_&_File_Structure.md
- **Updated**: 2026-01-24
- **Component**: Repo layout + execution integration glue
- **Primary responsibility**: Define module boundaries, entrypoints, and how flows emit durable state/evidence with minimal user friction.

## 1) Scope

This file defines how the runtime integrates with developer workflows and the codebase layout after migrating to:

- WSS (durable docs + artifacts)
- sharded JSONL logs (durable evidence)
- notifications + control actions queues (durable control plane)
- Patch-Stream (jj-backed ticket stacks)
- sandboxes (ephemeral tool execution)
- schema-validated user workflows (file-defined)
- a single auditable tool gateway (`workflow_engine`) for agents

**Single source of truth for global invariants**:
- Tech_Plan__Core_Infrastructure_&_Data_Model.md

This file specifies integration deltas: entrypoints, module boundaries, sandbox wiring, and workflow definition integration.

## 2) Entry points

### Interactive CLIs
- `/project-manager`
- `/ticket-manager --project <project_id> --ticket <ticket_id>`

### Non-interactive CLI (`workflowctl`)

`workflowctl` is the stable automation surface used by:
- users (directly),
- interactive CLIs (PM/TM),
- and “AI coding tool” command shims.

Minimum required subcommands (names are part of the UX contract; exact flags may evolve):

**Onboarding** (see Configuration & Onboarding §2, §7)
- `workflowctl init [--interactive] [--project]`
- `workflowctl doctor`
- `workflowctl bootstrap` (optional)

**Configuration** (see Configuration & Onboarding §5, §7)
- `workflowctl config show [--explain]`
- `workflowctl config set <key> <value>`
- `workflowctl providers list|add|remove|test <name>`

**CLI Integration** (see Configuration & Onboarding §4)
- `workflowctl install --cli <name> [--project]` (installs commands + workflow-manager skill)
- `workflowctl uninstall --cli <name> [--project]`

**Agents** (see Configuration & Onboarding §6)
- `workflowctl agents list|show|run <name> [--input <file>]`

**Workflow execution**
- `workflowctl run --workflow <id-or-path> ...`
- `workflowctl workflows list|validate`

**Task control**
- `workflowctl task approve-plan <ticket_id> <task_id> --plan <path>`
- `workflowctl task decompose <ticket_id> <task_id> [--workflow ...]`
- `workflowctl task abort <ticket_id> <task_id>`
- `workflowctl task create --ticket <ticket_id> --from-validation <run_id>`

**Observability + control**
- `workflowctl runs list|show`
- `workflowctl logs tail --run <run_id>`
- `workflowctl pause|resume --run <run_id> | --step <step_execution_id>`
- `workflowctl investigate --step <step_execution_id>`
- `workflowctl notifications tail`

**Export/sharing**
- `workflowctl export --ticket <ticket_id> --mode validated|review`
- `workflowctl export scrub --ticket <ticket_id> [--run <run_id>]`


## 3) Distribution (low friction)

### 3.1 Preferred distribution (single binary per platform)
To minimize installs and version drift:

- Distribute `workflowctl` + the interactive CLIs as a single self-contained executable per platform (bundled Python runtime + dependencies).
- External installs should be limited to:
  - `git` (assumed present for developers)
  - `jj` (auto-bootstrap supported; see §10)

### 3.2 Auto-bootstrap tools (optional but recommended)
If configured (`dependencies.auto_bootstrap_jj=true`), `workflowctl bootstrap` can download a pinned `jj` binary into:
`~/.workflow/tools/jj/<version>/jj[.exe]`

This reduces user friction without requiring system package managers.


### 3.3 Supported install modes (choose 1)

To match different user preferences while keeping friction low:

1. **Prebuilt executable (recommended)**  
   - Single file per platform (bundled Python runtime + dependencies).
   - Fastest onboarding and least version drift.

2. **Remote bootstrap script (recommended for prototypes)**  
   - One command downloads the pinned executable and installs a small shim into a user-writable bin dir.
   - Script never mutates the repo; it only installs under `~/.workflow/` and the user’s PATH.

3. **Python package (workflow authoring / library use)**  
   - `workflowctl` can also be installed as a Python package so users can write Python workflows against the library.
   - The engine still enforces the gateway/capability model at runtime.

All modes converge to the same on-disk runtime root: `~/.workflow/`.

### 3.4 Repo init (first-run UX)

`workflowctl init` is the per-repo onboarding action. It is self-bootstrapping.

**Detailed behavior**: See **Tech_Plan__Configuration_&_Onboarding.md §2** for the full onboarding flow.

**Self-bootstrapping flow**:
1. `init` asks user which CLI they use (interactive prompt)
2. `init` launches that CLI with a bootstrap prompt
3. Agent installs the workflow-manager skill
4. Agent uses the skill to configure everything else

**Key principles**:
- **Zero project pollution by default**: `init` writes only to `~/.workflow/repos/<repo_uid>/`
- **Project files are opt-in**: `--project` flag required to create `<repo>/.workflow/`
- **Self-bootstrapping**: Agent installs skill first, then uses it to configure

**Responsibilities**
- Create `~/.workflow/repos/<repo_uid>/` and `repo.json` (always)
- Ask user which CLI they use (always)
- Launch that CLI with bootstrap prompt (always)
- With `--project` flag: also create `<repo>/.workflow/` structure

**Non-goals**
- `init` does **not** create tickets, does **not** import docs, and does **not** start a background daemon.

**Evidence**
- `init_report.json` written under `workspace/runs/<run_id>/artifacts/` for auditability (what files were created/modified).


## 4) Step instrumentation (integration contract)

Every step process MUST:

- emit `step_start` and `step_stop`
- append JSONL events to its own log shard
- maintain step doc liveness (`metrics.heartbeat_ts`)
- honor PAUSE and write an ACK
- treat “unable to pause” as an investigation trigger (loud, evidence-backed)

### 4.1 Minimum `@step` decorator responsibilities
`@step` is the boundary where durability is guaranteed:

- creates/updates: `workspace/runs/<run_id>/steps/<step_execution_id>.json`
- appends to: `logs/runs/<run_id>/writers/<writer_id>.jsonl`
- emits periodic progress markers for long-running work:
  - `event_type="progress"` with `data.progress_key` and `data.progress_value`

## 5) Flat orchestration rule (enforced)

- Root runtime is the only process allowed to spawn step/agent processes.
- Steps may spawn **tool subprocesses** (linters/tests/build) internally, but must:
  - record PIDs in logs and step doc
  - stop them during PAUSE using the documented ladder

## 6) Patch-Stream integration (Mode A vs Mode B)

### Mode A — “blind patch editor” (preferred default)
1. Hydrate required files (virtual hydration; no checkout).
2. Produce patch (unified diff or structured hunks).
3. Run hunk-lint (format + dry-run apply).
4. Apply to ticket stack (jj change).
5. Persist evidence (patch id + refs) into WSS/logs.

### Mode B — “sandbox editor” (fallback)
1. Create ephemeral sandbox workspace hydrated from ticket stack tip.
2. Run tools normally (formatters/tests/search).
3. Capture diff vs baseline.
4. Run hunk-lint and apply patch to ticket stack.
5. Persist tool outputs as artifacts (durable), not as “truth”.

Selection policy:
- Prefer Mode A unless repo-wide tooling is required, hydration is too large/slow, or repeated hunk-lint failures occur.

## 7) Workflows as a first-class integration surface (user-defined)

User experience requires the ability to define and share workflows without adding services.

### 7.1 Workflow definition locations (precedence)

Workflows are YAML documents validated against a schema.

Highest precedence first:
1. CLI `--workflow-file <path>`
2. Project-scoped WSS: `workspace/projects/<project_id>/workflows/*.yaml`
3. Repo-shared (committable): `<repo_root>/.workflow/workflows/*.yaml`
4. Repo-machine-local (WSS): `workspace/workflows/*.yaml`
5. Built-in defaults packaged with the tool

### 7.2 Workflow schema (v1 summary)

Required top-level fields:
- `schema_version: 1`
- `workflow_id`
- `display_name`
- `description`
- `inputs` (JSON-schema-like object; used for CLI prompting/validation)
- `capabilities_required`
- `steps` (DAG or sequence)

Step fields:
- `step_id`
- `kind`: `agent|tool|script|subworkflow`
- `entrypoint`:
  - `builtin:<name>` for built-ins
  - `file:<relative_path>` for agent prompts
  - `script:<artifact_ref>` for registered scripts
  - `tool:<subcommand>` for gateway tool calls
- `model` (optional; defaults to config)
- `sandbox` (optional; defaults to config)
- `depends_on` (optional; enables DAG)
- `on_failure`: `investigate|retry|abort|escalate` (default: investigate)

### 7.3 Capability gating (trust)
Workflows may request capabilities. The runner enforces:

- if capability is not enabled in config → fail loudly
- if capability is marked “dangerous” → require explicit user ack (per run) unless allowlisted

Example dangerous capabilities:
- network beyond LLM providers
- write outside sandbox
- git/jj push
- file deletion outside sandbox

## 8) `workflow_engine` gateway (single tool constraint)

### Purpose
All agent execution goes through one constrained, auditable gateway. Agents do not run arbitrary commands directly.

### Interface
Tool: `workflow_engine.invoke(payload: JSON) -> JSON`

### Allowlisted subcommands (v1)

| Subcommand | Purpose | Capability |
|---|---|---|
| `help` | schemas + examples | none |
| `hydrate` | virtual hydration (Mode A) | `read_stack` |
| `apply_patch` | apply patch to ticket stack | `apply_patch` |
| `sandbox_create` | create sandbox workspace | `sandbox_exec` |
| `sandbox_run` | run tool in sandbox/workspace | `sandbox_exec` |
| `sandbox_destroy` | cleanup sandbox workspace | `sandbox_exec` |
| `llm_call` | cancellable LLM call wrapper | `net_llm` |
| `spawn_step` | request child step | `spawn_child` |
| `wait_step` | wait for step completion | none |
| `control_write` | write control actions | `control_send` |
| `export_scrub` | build scrubbed bundle | `export_scrub` |
| `graph_static` | generate static graph | none |
| `graph_run` | generate dynamic graph | none |
| `run_python_script` | run registered script artifact | `script_exec` |

### Validation (mandatory)
For every invocation:
- validate against JSON schema
- reject unknown fields
- enforce repo-relative paths (deny absolute and `..`)
- enforce max sizes (patch, hydration, stdout chunk)
- enforce privacy policy:
  - for `llm_call`, secret scan + network_mode checks
  - for `export_scrub`, secret scan + scrub policy

### Python execution rule (registered artifacts only)
- Agent-authored scripts are stored as run artifacts: `workspace/runs/<run_id>/artifacts/scripts/<script_id>.py`.
- A script is “registered” by:
  - writing it as an artifact
  - recording `sha256` in a sidecar manifest
- Execution references script path + expected hash; gateway logs both `tool_start` and `tool_stop` including hashes.

## 9) Sandboxes (cross-platform, low-friction)

### 9.1 Principle: sandboxes are jj workspaces
Sandboxes are implemented as **jj workspaces** (materialized working copies backed by a single repo store).

JJ workspaces are designed for parallel working copies:
- Working copy docs: https://docs.jj-vcs.dev/latest/working-copy/
- `jj workspace add` supports controlling sparse patterns (`--sparse-patterns`) (v0.22+):
  - https://man.archlinux.org/man/extra/jujutsu/jj-workspace-add.1.en
  - release note excerpt (v0.22): https://github.com/jj-vcs/jj/discussions/4568

Sparse patterns are controlled via `jj sparse`:
- https://docs.jj-vcs.dev/latest/cli-reference/ (see `jj sparse`)
- `jj sparse set` man page: https://man.archlinux.org/man/extra/jujutsu/jj-sparse-set.1.en

### 9.2 Sandbox creation algorithm (default)
Given `(repo_root, baseline_revset, sparse_mode)`:

1. Allocate `sandbox_id` (ULID)
2. Create directory:
   `~/.workflow/repos/<repo_uid>/sandboxes/<run_id>/<sandbox_id>/`
3. Run:
   `jj workspace add <sandbox_path> --name <sandbox_id> --revision <baseline_revset> --sparse-patterns <copy|full|empty>`
4. If workflow specifies explicit include patterns:
   - `jj sparse set --clear --add <pattern> ...` inside sandbox
5. Record sandbox metadata:
   - jj version
   - baseline revset / commit id
   - sparse patterns
   → `workspace/runs/<run_id>/artifacts/env/sandbox_<sandbox_id>.json`

### 9.3 Copy fallback (enabled by default; guarded)
Some repos/tools require more files than sparse heuristics capture. To reduce user friction:
- `sandbox.copy_fallback=true` by default

When fallback triggers:
- expand sparse patterns to `full`, or
- materialize required paths by adding patterns, or
- as last resort, create a full working copy (still a workspace) and warn loudly

Guards (defaults in Core config):
- max concurrent sandboxes
- TTL cleanup
- total sandbox disk budget (soft limit with warnings)

### 9.4 Sandbox destruction (mandatory cleanup)
- Destroy tool subprocesses
- Flush sandbox logs and persist required artifacts
- Remove workspace directory
- Run `jj workspace forget` if required by jj state
All actions are logged.

## 10) Repo code layout (target)

```text
scripts/
  core/
    protocol/
      schema_v1.py
      merge_patch.py
      atomic_write.py
      journals.py                 # write-ahead journal helpers
      pause.py
      redaction.py                # secret scanning + redaction
      config.py                   # config loading + schema validation
      locks.py                    # lock helpers
    storage/
      wss.py
      logs.py
      queues.py
    secrets/
      keyring_store.py            # secrets get/set/delete
      fallback_store.py
    vcs/
      jj_adapter.py
    sandbox/
      workspace_runner.py         # jj workspace-based sandboxes
    workflows/
      registry.py                 # load/merge workflows from precedence
      runner.py                   # execute workflow steps (DAG)
      schema.py                   # workflow YAML schema
    conclusions/
      store.py
    investigation/
      bundle.py
      contract.py
    runtime/
      root.py
      step.py
      ids.py
      doctor.py
      fsck.py
      recover.py
  project_manager/
    cli.py
    project_index.py
  ticket_manager/
    cli.py
    task_decomposition/
      orchestrator.py
      agents/
        pattern_discovery.md
        approval.md
        verification.md
      candidate_surfacing.py
    task_executor.py
  pr/
    review_implementation.py
    update_pr.py
    rebase_enhanced.py
    merge.py
  monitoring/
    monitor_thread.py
    anomaly_detector.py
    workflow_repair.md

workflowctl/
  main.py
```

## 11) Integration risk register (residual risks + controls)

| Risk | Severity | Control(s) |
|---|---:|---|
| Workflow schema drift | Medium | schema validation + versioned schema + gateway `help` contract tests |
| Sandbox drift across OSes | Medium | single primary mechanism (jj workspaces) + sparse patterns + fallback ladder |
| Gateway schema rot | Medium | reject unknown fields; schema snapshots tested; `help` output included in tests |
| Accidental secret capture | High | outbound scanning + prompt manifests + export scrubber |
| Logging overhead | Low | shard per step; chunk stdout/stderr; retention/GC |
