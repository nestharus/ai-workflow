# Tech Plan: Integration — Entrypoints & CLI Contract

- **Doc**: Tech_Plan__Integration/02_Entrypoints_and_CLI_Contract.md
- **Updated**: 2026-01-26
- **Shard**: Integration §2–§2.2
- **Libraries / packages**:
  - `workflowctl/` (stable non-interactive automation surface)
  - `scripts/core/runtime/*` (bootstrap + repo discovery)
  - `scripts/project_manager/*` and `scripts/ticket_manager/*` (interactive CLI shims)
- **Depends on**:
  - `Tech_Plan__Core_Infrastructure.md` (repo UID derivation, errors, WSS layout)
  - `Tech_Plan__Configuration_&_Onboarding.md` (onboarding + provider configuration)

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


### 2.1 CLI bootstrap sequence (normative)

All entry points (interactive CLIs and `workflowctl`) share the same bootstrap logic so they behave consistently.

#### 2.1.1 Runtime root discovery

- Determine `WORKFLOW_HOME`:
  1. If env var `WORKFLOW_HOME` is set, use it.
  2. Else default to `~/.workflow` (user home, expanded).
- `WORKFLOW_HOME` MUST be treated as an absolute path after expansion.

#### 2.1.2 Repo context discovery (when running inside a repo)

When a command requires a repo context, it MUST:

1. Determine `repo_root`:
   - `git rev-parse --show-toplevel`
2. Compute the derived `repo_uid` per Core Infrastructure §3.
3. If `~/.workflow/repos/<repo_uid>/repo.json` exists:
   - load it and treat it as authoritative
4. Otherwise:
   - treat the repo as “not initialized”

Commands that require an initialized repo MUST fail loudly when the repo is not initialized:

- Structured error: `E_NOT_FOUND`
- Message: `Repository is not initialized. Run: workflowctl init`
- Details MUST include: `repo_root`, derived `repo_uid`, and the expected path to `repo.json`.

#### 2.1.3 Interactive CLIs (`/project-manager`, `/ticket-manager`)

Interactive CLIs are **slash-command entry points** installed into the user’s AI coding tool (Configuration & Onboarding §4).

Implementation requirement (normative):
- Each interactive CLI command MUST invoke `workflowctl` as a subprocess (no in-process import coupling).
- The interactive CLI MUST:
  - capture stdout/stderr as evidence (log events `tool_start` / `tool_stop`)
  - display notifications surfaced via `workflowctl notifications tail`

### 2.2 Entrypoint implementation notes (packaging)

- `workflowctl` is the only required OS-level executable.
- All other “entrypoints” (project-manager/ticket-manager) are *logical commands* provided via skills and map to `workflowctl` subcommands or `workflowctl run --workflow ...`.
