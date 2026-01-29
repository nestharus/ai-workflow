# Tech Plan: Integration — Entrypoints & CLI Contract

- **Doc**: Tech_Plan__Integration/02_Entrypoints_and_CLI_Contract.md
- **Updated**: 2026-01-29
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
- `workflowctl doctor [--check-tools] [--tool <tool_name>]`
- `workflowctl bootstrap` (optional)
- `workflowctl version`

**Configuration** (see Configuration & Onboarding §5, §7)
- `workflowctl config show [--explain]`
- `workflowctl config get <key>`
- `workflowctl config set <key> <value>`
- `workflowctl config export [--redact-secrets]`
- `workflowctl providers list|add|remove|test <name>`
- `workflowctl models list`

**CLI Integration** (see Configuration & Onboarding §4)
- `workflowctl install --cli <name> [--project]` (installs commands + workflow-manager skill)
- `workflowctl uninstall --cli <name> [--project]`

**Agents** (see Configuration & Onboarding §6)
- `workflowctl agents list|show|run <name> [--input <file>]`

**Workflow execution**
- `workflowctl run --workflow <id-or-path> ...`
- `workflowctl workflow list|show`
- `workflowctl workflow validate <path-or-id>`
- `workflowctl workflow dry-run <workflow_id> --inputs <json|@file>`
- `workflowctl workflow eval-expr --expr '${{ ... }}' --inputs <json|@file> [--run <run_id>]`

#### Workflow debugging commands (normative)

The `workflowctl workflow` group includes **debugging commands** for workflow authors. These commands never execute tools/agents; they validate, evaluate expressions, and compute execution plans.

All workflow debugging commands:
- emit structured JSON to stdout
- emit human-readable error messages to stderr
- exit `0` on success, `1` on validation/evaluation errors
- use structured error code `E_VALIDATION_FAILED` for workflow/schema/expression errors (Core Infrastructure §8.2.5)

##### `workflowctl workflow validate <path-or-id>`

Purpose:
- validate workflow YAML (schema + DAG + entrypoints + capabilities + subworkflow nesting) without executing anything

Resolution:
- `<path-or-id>` MAY be a file path or a workflow ID
- workflow IDs MUST be resolved by workflow precedence (Integration §7.1)

Output (success):
```json
{
  "valid": true,
  "workflow_id": "task_decompose_v1",
  "steps_count": 3,
  "execution_order": ["plan", "validate", "commit"],
  "capabilities_required": ["patch_write", "sandbox_exec"]
}
```

Output (failure):
- MUST include `code: "E_VALIDATION_FAILED"` and an `errors[]` list of structured issues (best-effort):
  - `instance_path` (e.g., `steps[2].depends_on[0]`)
  - `schema_path` (e.g., `steps.items.properties.depends_on`)
  - `reason` (e.g., `CYCLE_DETECTED`, `INVALID_ENTRYPOINT`)
  - `expected` / `actual` (optional)
  - `details` (optional; e.g., `cycle_path`)

##### `workflowctl workflow dry-run <workflow_id> --inputs <json|@file>`

Purpose:
- compute the workflow execution plan and evaluate `with:` expressions across the DAG without executing entrypoints

Rules:
- `--inputs` MUST accept either an inline JSON string or `@<file>` containing JSON (UTF-8).
- inputs MUST validate against the workflow inputs schema (Integration §7.2.6).
- `with:` expressions MUST evaluate per the expression rules (Integration §7.2.4).
- step outputs MUST be simulated (v1 default: empty object) so downstream expressions can reference `steps.<step_id>.output`.

Parallelism reporting:
- output MUST include dependency-ready groupings derived from the DAG (even though the v1 runner is single-threaded; Integration §7.2.9).

Output (example):
```json
{
  "workflow_id": "task_decompose_v1",
  "execution_order": ["plan", "validate", "commit"],
  "parallel_groups": [["plan"], ["validate", "commit"]],
  "steps": [
    {
      "step_id": "plan",
      "kind": "agent",
      "entrypoint": "agent:task_decomposer_v1",
      "evaluated_with": { "task_text": "Implement user authentication" },
      "dependencies_satisfied": true
    }
  ]
}
```

##### `workflowctl workflow eval-expr --expr '${{ ... }}' --inputs <json|@file> [--run <run_id>]`

Purpose:
- evaluate a single expression in isolation, either using standalone inputs or a real run context

Modes:
- standalone mode (no `--run`): evaluate with only `--inputs`
- run mode (`--run <run_id>`): load WSS run state from `workspace/runs/<run_id>/` and build a `steps.*` context from step execution outputs under `workspace/runs/<run_id>/steps/*.json`

Output (example):
```json
{
  "expression": "${{ inputs.task_id }}",
  "result": "TASK-123",
  "result_type": "string",
  "context_used": { "inputs": true, "run_id": null }
}
```

**Task control**
- `workflowctl task approve-plan <ticket_id> <task_id> --plan <path>`
- `workflowctl task decompose <ticket_id> <task_id> [--workflow ...]`
- `workflowctl task abort <ticket_id> <task_id>`
- `workflowctl task create --ticket <ticket_id> --from-validation <run_id>`

**Observability + control**
- `workflowctl runs list|show`
- `workflowctl logs tail --run <run_id>`
- `workflowctl logs export --run <run_id> [--error <error_id>]`
- `workflowctl ticket show-stack|diff|list-patches --ticket <ticket_id>`
- `workflowctl pause|resume --run <run_id> | --step <step_execution_id>`
- `workflowctl investigate --step <step_execution_id>`
- `workflowctl notifications tail`

**Metrics and aggregation**
- `workflowctl metrics summary [--since <rfc3339>] [--since-days <N>] [--format json|table]`
- `workflowctl metrics failures [--group-by signature|code] [--since-days <N>] [--format json|table]`

**Export/sharing**
- `workflowctl export --ticket <ticket_id> --mode validated|review`
- `workflowctl export scrub --ticket <ticket_id> [--run <run_id>]`
- `workflowctl export metrics --out <path> [--since <rfc3339>] [--since-days <N>]`

**Export command hierarchy (normative)**

`workflowctl export` is a command group with three distinct parser shapes:
- **Ticket export (default action)**: `workflowctl export --ticket <ticket_id> --mode validated|review ...`
- **Scrub**: `workflowctl export scrub --ticket <ticket_id> ...`
- **Metrics export**: `workflowctl export metrics --out <path> ...`

Parser disambiguation rule (normative):
- If the first token after `export` is `scrub` or `metrics`, it MUST be parsed as a subcommand invocation.
- Otherwise, `export` MUST be parsed as the ticket export action and MUST require `--ticket`.

Examples (disambiguating expected invocation syntax):
- Ticket export: `workflowctl export --ticket NES-47 --mode validated --out ./export.zip`
- Scrub ticket export: `workflowctl export scrub --ticket NES-47 --run 01J... --out ./export.scrubbed.zip`
- Metrics export: `workflowctl export metrics --since-days 7 --out ./metrics.jsonl`


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
- All other "entrypoints" (project-manager/ticket-manager) are *logical commands* provided via skills and map to `workflowctl` subcommands or `workflowctl run --workflow ...`.

#### 2.2.1 `workflowctl notifications tail` — Display Deduplication

**Persistence invariant (normative):** The tail command MUST NOT delete or skip persisted notifications. Every notification written to the persistence layer MUST be observed and emitted exactly once per invocation; deduplication applies ONLY to terminal display output.

**Display deduplication behavior (normative):**

1. **Deduplication condition (normative):** Display deduplication ONLY applies when `dedupe_key` is provided and non-empty. If `dedupe_key` is missing or blank, consumers MUST NOT dedupe and MUST display all notifications.

2. Within a configurable time window (default: 60 seconds per `notification_dedupe_window_ms`), suppress display of duplicate notifications where duplicates are defined as notifications sharing the same:
   - `dedupe_key`: normalized content fingerprint (e.g., hash of notification template + resolved parameter values)
   - `severity`: notification severity level

2. When a duplicate suppression occurs:
   - Display the first occurrence normally
   - For subsequent duplicates within the window, display a suppression counter instead of the full notification
   - Suppress counter format: `+N suppressed` where N is the count of suppressed duplicates
   - Counter placement: On a line following the notification details, indented to align with the notification body

**Example output:**

```text
[2026-01-28 14:32:15] ERROR: Step execution failed
  step_id: step_01J3ZQK9X5J9H6R8V2S4J2E9P3
  error: E_TOOL_TIMEOUT
  +5 suppressed

[2026-01-28 14:33:20] WARN: Sandbox cleanup delayed
  sandbox_id: sb_01J3ZQK9X5J9H6R8V2S4J2E9P4
```

3. Window tracking:
   - Window tracking is based on `created_at` timestamps of notifications
   - Window expiry behavior: When the first occurrence's `created_at` timestamp exceeds the window duration, that entry is no longer considered for deduplication matching and subsequent identical notifications are treated as new (displayed with their suppression counter reset)

**Implementation notes:**

- Maintain an in-memory cache of `(dedupe_key, severity, first_seen_timestamp)` tuples
- Evict entries from the cache after the window expires based on `first_seen_timestamp`
- The cache is per-invocation of the tail command (not persisted)

**Configuration**: See Configuration System §11.4.3 for the `notification_dedupe_window_ms` setting.
