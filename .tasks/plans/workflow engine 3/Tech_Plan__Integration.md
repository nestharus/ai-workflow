# Tech Plan: Integration & File Structure (Restructured)

- **Doc**: Tech_Plan__Integration.md
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
- Tech_Plan__Core_Infrastructure.md

This file specifies integration deltas: entrypoints, module boundaries, sandbox wiring, and workflow definition integration.

## 1.1 Terminology (WSS vs sandbox)

To avoid ambiguity:

- **WSS (Workspace State Store)**: the durable state store directory under the runtime root  
  - Path example: `~/.workflow/repos/<repo_uid>/workspace/` (directory name is `workspace/`)
  - In text, always call this **WSS** or **WSS root** (never “workspace” unqualified).

- **Sandbox**: an ephemeral environment used for tool execution (Integration §9).  
  - In this system, a sandbox is implemented as a **jj workspace** created under the repo runtime root.

- **jj workspace**: the Jujutsu term for a working copy created by `jj workspace add`.  
  - When referencing jj documentation, we keep the term “jj workspace”; otherwise we say “sandbox”.
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
1. Create ephemeral sandbox (jj workspace) hydrated from ticket stack tip.
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

**Flag conflict rule (normative)**:
- If both `--workflow <id>` and `--workflow-file <path>` are provided, `--workflow-file` MUST win.
- The runner SHOULD emit a `warn`-severity log event noting the override.


### 7.2 Workflow schema v1

This section defines the **normative** YAML schema for workflows (`schema_version: 1`).

A workflow is a UTF-8 YAML document that declares:
- **inputs** (typed, validated)
- **steps** (a DAG or linear sequence)
- **capabilities required** (trust gating)
- **failure policies** (loud, evidence-preserving)

Workflows are validated **before** execution. Validation failures are **hard errors**.

#### 7.2.1 File format

- File extension: `.yaml` (preferred) or `.yml`
- Encoding: UTF-8
- YAML: 1.2 mapping at the root
- Unknown keys:
  - By default, **rejected** (loud failure)
  - Exception: keys prefixed with `x_` are allowed as opaque extension fields and are preserved as-is.

#### 7.2.2 Top-level fields

Required fields:

- `schema_version` (int)  
  - Must be `1`.

- `workflow_id` (string)  
  - Stable identifier used for selection and overrides.  
  - Regex: `^[a-z][a-z0-9_\-]*_v[0-9]+$`

- `display_name` (string)

- `steps` (array of step objects)  
  - Must contain at least 1 step.

Optional fields:

- `description` (string)

- `inputs` (object, default `{}`)  
  - Defines the **typed** workflow inputs contract.  
  - Must conform to **Workflow Inputs Schema v1** (see §7.2.6).  
  - The effective runtime input value is a JSON object that validates against this schema.

- `capabilities_required` (array of strings, default `[]`)  
  - All steps inherit these capabilities (in addition to per-step requirements).

- `defaults` (object, optional)  
  - `model` (string, optional) — default model routing key or explicit model name  
  - `on_failure` (object, optional) — default failure policy for steps (see §7.2.7)  
  - `sandbox` (object, optional) — default sandbox policy for steps (see §7.2.5)

- `outputs` (object, optional)  
  - Named “exports” for callers. Values are expressions (see §7.2.4), typically referencing step outputs.

#### 7.2.3 Step object schema

Each item in `steps` is a mapping with these fields.

Required:

- `step_id` (string)  
  - Unique within the workflow.  
  - Regex: `^[a-z][a-z0-9_\-]*$`

- `kind` (string enum)  
  - One of:
    - `agent` — invoke an LLM agent prompt
    - `tool` — invoke a gateway tool
    - `script` — run a local script (sandboxed if configured)
    - `subworkflow` — run another workflow (nested run)
    - `gate` — stop and wait for a user control action (approval / selection)
    - `noop` — emit a marker event (no side effects)

Optional:

- `title` (string) — human-readable name (UI/CLI)
- `description` (string)

- `entrypoint` (string, required for `agent|tool|script|subworkflow`)  
  Entry-point URI formats:
  - `agent:<name>` — resolves an agent prompt by **agent precedence** (Config & Onboarding §6)
  - `workflow:<workflow_id>` — resolves a workflow by **workflow precedence** (Integration §7.1)
  - `file:<repo_relative_path>` — repo-relative path (no absolute paths)
  - `builtin:<id>` — packaged built-in

  `tool:` entrypoints are reserved for gateway tools:
  - `tool:<tool_name>` (e.g., `tool:hydrate`, `tool:apply_patch`)

- `depends_on` (array of `step_id`, default `[]`)  
  - Steps form a DAG when any `depends_on` is present.
  - Validation rules (see §7.2.8) enforce:
    - all referenced IDs exist
    - no self-dependency
    - no cycles

- `with` (object, optional)  
  - Step-local input object passed to the step runner.
  - Values support expressions (see §7.2.4).

- `capabilities_required` (array of strings, default `[]`)  
  - Additional capability requirements for this step only.

- `sandbox` (object, optional)  
  Step-level sandbox policy override (see §7.2.5).

- `timeout_ms` (int, optional)  
  - Deadline for the step runner to emit progress.  
  - Timeouts do **not** silently abort work; they trigger the step’s `on_failure` policy.

- `on_failure` (object, optional)  
  Step-level failure policy override (see §7.2.7).

#### 7.2.4 Expression language for `with` and `outputs`

Workflows need a minimal, deterministic way to wire inputs to steps.

Expression strings use the form:

- `${{ inputs.<name> }}` — workflow runtime inputs
- `${{ steps.<step_id>.output }}` — entire step output object
- `${{ steps.<step_id>.output.<field> }}` — a field within a step’s output
- `${{ steps.<step_id>.artifacts.<name> }}` — an artifact reference emitted by a step runner

Rules:

- Expressions are only evaluated inside **string** values.
- If a string contains exactly one expression and nothing else, the result is substituted as the original JSON type (string/number/object/array/bool/null).
- Otherwise, the expression is stringified and interpolated.
- Missing references are a **validation error** unless the step declares `x_allow_missing: true` (extension key).

#### 7.2.5 Sandbox policy object

Sandbox policy governs whether a step runs in a materialized working copy.

Fields:

- `required` (bool, default `false`)  
  - If `true`, the runner MUST execute the step in a sandbox.

- `scope` (string enum, default `step`)  
  - `step` — sandbox lifetime is the step execution
  - `run` — sandbox lifetime is the whole workflow run (may be reused across steps)

- `sparse_mode` (string enum, default `empty`)  
  - Passed to `jj workspace add --sparse-patterns=<MODE>`:
    - `copy` — inherit sparse rules from the parent workspace
    - `full` — full working copy
    - `empty` — empty working copy  
  - After workspace creation, the runner may still apply explicit patterns via `jj sparse set`.

- `include_patterns` (array of strings, optional)  
  - If present, these are applied via `jj sparse set --clear --add ...`.
  - The runner does not interpret pattern syntax; it passes strings verbatim to `jj`.

- `ttl_minutes_override` (int, optional)  
  - Overrides sandbox TTL for this step only (see Core Infrastructure §11.4 sandbox TTL semantics).

#### 7.2.6 Workflow inputs schema v1

`inputs` defines the schema for the workflow runtime input object.

This is a deliberately small subset of JSON Schema, designed to be:
- easy to generate
- easy to validate
- stable across languages

##### Inputs schema root
- Must be an object schema.

Supported keywords:

- `type` (required): `"object"`
- `properties` (required): object mapping property name → property schema
- `required` (optional): array of property names
- `additionalProperties` (optional, default `false`): bool

##### Property schema
Supported keywords:

- `type` (required): `"string"|"integer"|"number"|"boolean"|"object"|"array"`
- `description` (optional): string
- `default` (optional): any JSON value
- `enum` (optional): array of literals

String:
- `minLength`, `maxLength` (int, optional)
- `pattern` (string, optional; RE2-compatible)

Number / integer:
- `minimum`, `maximum` (number, optional)

Array:
- `items` (property schema, required)
- `minItems`, `maxItems` (int, optional)

Object:
- `properties`, `required`, `additionalProperties` (same as root)

##### Canonical meta-schema (for validators)

```json
{
  "schema_version": 1,
  "type": "object",
  "required": ["type", "properties"],
  "properties": {
    "type": { "const": "object" },
    "properties": { "type": "object", "additionalProperties": { "$ref": "#/$defs/prop" } },
    "required": { "type": "array", "items": { "type": "string" } },
    "additionalProperties": { "type": "boolean" }
  },
  "additionalProperties": false,
  "$defs": {
    "prop": {
      "type": "object",
      "required": ["type"],
      "properties": {
        "type": { "enum": ["string","integer","number","boolean","object","array"] },
        "description": { "type": "string" },
        "default": {},
        "enum": { "type": "array" },
        "minLength": { "type": "integer", "minimum": 0 },
        "maxLength": { "type": "integer", "minimum": 0 },
        "pattern": { "type": "string" },
        "minimum": { "type": "number" },
        "maximum": { "type": "number" },
        "items": { "$ref": "#/$defs/prop" },
        "minItems": { "type": "integer", "minimum": 0 },
        "maxItems": { "type": "integer", "minimum": 0 },
        "properties": { "type": "object", "additionalProperties": { "$ref": "#/$defs/prop" } },
        "required": { "type": "array", "items": { "type": "string" } },
        "additionalProperties": { "type": "boolean" }
      },
      "additionalProperties": false
    }
  }
}
```

##### Prompt generation rules (workflowctl interactive mode) (normative)

When the user does not provide a complete `inputs` object non-interactively, `workflowctl` MAY prompt.

Prompt order:
1. required properties (in `properties` key order)
2. optional properties (in `properties` key order)

Prompt behavior by type:

- `string`:
  - prompt with `description` (if present)
  - empty input is allowed only if the property is not required
  - enforce `minLength/maxLength/pattern`

- `integer` / `number`:
  - parse strictly (no trailing junk)
  - enforce `minimum/maximum`

- `boolean`:
  - accept `y/n`, `yes/no`, `true/false` (case-insensitive)

- `enum`:
  - display allowed values
  - accept either the literal value or the 1-based index of the option

- `object` / `array`:
  - prompt for JSON input (single line) OR `@<path>` to load JSON from a file
  - validate recursively

Defaults:
- If a property has `default`, the prompt MUST display it and the user may accept it by submitting an empty line.

##### Validation errors (normative)

If input validation fails (prompted or non-interactive), the runner MUST fail loudly with:

- structured error code: `E_VALIDATION_FAILED` (Core §8.2.5)
- error details:
  - `instance_path` (e.g., `inputs.task_id`)
  - `schema_path` (e.g., `inputs.properties.task_id.pattern`)
  - `reason` (short string)
  - `expected` (optional)
  - `actual` (optional)

Prompted mode MAY reprompt until valid input is provided or the user aborts (Ctrl+C). Each prompt read MUST time out after `prompt_timeout_ms` (default `60000`).

On prompt timeout:
- fail loudly with `E_VALIDATION_FAILED`
- set `details.reason = "PROMPT_TIMEOUT"` The runner MUST NOT silently coerce invalid inputs.
#### 7.2.7 Failure policy object `on_failure`

`on_failure` defines what happens when a step fails loudly.

Fields:

- `policy` (string enum, required)  
  - `investigate` — spawn investigator with bounded evidence  
  - `retry` — re-run the step under progress-guard rules  
  - `escalate` — stop and require user action  
  - `abort` — stop the workflow run and mark failed

Optional sub-objects:

- `retry` (object, optional; used when `policy: retry`)
  - `strategy` (string enum, default `progress_guarded`)  
    - `progress_guarded` means: only retry if there is evidence of novelty; repeated failure signatures trigger escalation.
  - `repeat_signature_threshold` (int, default `2`)  
    - If the same failure signature repeats this many times, the runner MUST stop retrying and apply the next action:
      - if Mode A was used, switch to Mode B and retry once
      - otherwise escalate
  - `switch_to_mode_b_on_repeat` (bool, default `true`)

- `investigate` (object, optional; used when `policy: investigate`)
  - `pause_before_investigate` (bool, default `true`)
  - `bundle_event_limit` (int, default `200`)

- `escalate` (object, optional; used when `policy: escalate`)
  - `notification_severity` (string enum, default `error`) — `info|warn|error|critical`
  - `require_user_ack` (bool, default `true`)

#### 7.2.8 Validation rules for `depends_on` and ordering

A workflow run order is derived as:

- If **no** step specifies `depends_on`: execute steps in listed order.
- If **any** step specifies `depends_on`: treat the steps as a DAG.

Validation:

- Every `depends_on` entry MUST refer to an existing `step_id`.
- A step MUST NOT depend on itself.
- The graph MUST be acyclic.

Cycle detection (normative algorithm):

1. Build adjacency list from `depends_on`.
2. Run Kahn topological sort.
3. If not all nodes are emitted, fail validation with `E_VALIDATION_FAILED` and include:
   - `details.reason = "CYCLE_DETECTED"`
   - `details.cycle_nodes = [<step_id>...]`



##### Subworkflow nesting limits (normative)

Workflows may contain steps with `kind: subworkflow`.

Validation MUST enforce:
- `max_subworkflow_depth = 10`
- no circular subworkflow references (A → … → A)

If either rule is violated, validation MUST fail with `E_VALIDATION_FAILED` and include:
- `details.reason = "SUBWORKFLOW_GRAPH_INVALID"`
- `details.path = [<workflow_id>...]` (best-effort)

#### 7.2.9 Workflow runner execution model (v1)

This section defines the **normative** execution behavior of `workflowctl run`.

##### A) Determinism and ordering

- A workflow defines a DAG via `depends_on`.
- In v1, the runner is **single-threaded** (no parallel step execution).
- When multiple steps become ready at the same time, the runner MUST choose the next step by **file order** (the order in `steps:`).

##### B) Run initialization

On `workflowctl run --workflow <id-or-path>`:

1. Resolve the workflow definition file (precedence §7.1) and validate against schema (§7.2).
2. Resolve and validate workflow `inputs` (see §7.2.6 + prompt rules below).
3. Allocate `run_id` (ULID).
4. Write `workspace/runs/<run_id>/run.json` with:
   - `workflow_id`
   - `status: "running"`
   - `started_at`
   - a plan view:
     - `plan.steps[] = {step_id, depends_on[], kind, status:"pending"}`

##### C) Step execution loop

The runner repeatedly selects and executes steps until the plan is terminal.

A step is **ready** when:
- its plan status is `pending`, AND
- all `depends_on` steps have plan status `completed`

Execution of a ready step:

1. Allocate `step_execution_id` (ULID).
2. Create step execution doc `workspace/runs/<run_id>/steps/<step_execution_id>.json` with:
   - `workflow_id`, `step_id`, `step_execution_id`, `run_id`
   - `status: "running"`, `started_at`
   - the fully materialized step input object (result of evaluating `with:` expressions)
3. Execute the step based on its kind:
   - `kind: tool` → call the gateway tool (Integration §8)
   - `kind: agent` → spawn a step process (Monitoring §2.2) which performs LLM calls via the gateway
   - `kind: script` → run a registered script artifact via the gateway
   - `kind: workflow` → run a nested workflow (child run) and capture its outputs
4. On success:
   - Update step execution doc: `status:"completed"`, `ended_at`, and `output` (bounded JSON object)
   - Update the run plan: `plan.steps[step_id].status="completed"`
5. On failure:
   - Update step execution doc: `status:"failed"`, `ended_at`, `error` (structured error object)
   - Apply failure policy (`on_failure`, §7.2.7), updating run status accordingly.

##### D) Step inputs/outputs and expression resolution

- Workflow runtime inputs are a JSON object that validates against `inputs` schema.
- Each step has a **materialized input object**, computed by:
  - taking the step’s `with:` mapping (if present)
  - evaluating expressions per §7.2.4 using:
    - `inputs.*`
    - `steps.<step_id>.output` from already-completed steps
    - `steps.<step_id>.artifacts.*` from already-completed steps
- The runner MUST fail loudly with `E_VALIDATION_FAILED` if an expression references a missing value, unless `x_allow_missing: true`.

Step output storage (normative):
- The step’s **bounded** output object is stored in the step execution doc as `output`.
- Large results MUST be written as artifacts under `workspace/runs/<run_id>/artifacts/` and referenced via `output.artifacts`.

##### E) Failure policy semantics (interaction with DAG)

`on_failure.mode` applies to the step that failed:

- `stop`:
  - set `run.json.status="failed"` and stop scheduling new steps.
- `pause`:
  - set `run.json.status="paused"` and stop scheduling new steps until resumed.
- `investigate`:
  - set `run.json.status="investigating"`
  - enqueue a control action requesting investigation (Monitoring §5)
  - do not schedule new steps until a resume plan is applied.
- `continue`:
  - mark the step as failed and continue scheduling any steps that are still runnable.
  - Any step that depends (directly or transitively) on a failed step is left `blocked` in the plan.
  - The run ends as `failed` if any step is `failed` or `blocked`; otherwise it ends `completed`.

Terminal condition:
- `completed` when all plan steps are `completed`.
- `failed` when:
  - any step is `failed` and `on_failure.mode != "pause"/"investigate"` OR
  - any step is `blocked` at end of scheduling.
### 7.3 Capability gating (trust)
Workflows may request capabilities. The runner enforces:

- if capability is not enabled in config → fail loudly
- if capability is marked “dangerous” → require explicit user ack (per run) unless allowlisted

Example dangerous capabilities:
- network beyond LLM providers
- write outside sandbox
- git/jj push
- file deletion outside sandbox


### 7.4 Built-in workflow catalog v1

This catalog enumerates the workflow IDs that ship with the tool (the `builtin:` namespace).

Built-ins exist so the system can run out-of-the-box. Users may override them via the normal workflow precedence rules (Integration §7.1). If an override is present, it is used; otherwise the built-in is used.

#### 7.4.1 Built-in workflow IDs

**Normative definitions**: The complete YAML for each built-in workflow is specified in:
- `Tech_Plan__Built-in_Workflow_Definitions.md`

The runner MUST package built-in workflows exactly as specified there.


| workflow_id | Primary responsibility | Typical caller |
|---|---|---|
| `task_decompose_v1` | Convert a user task input into a step plan + candidate set | Ticket Manager |
| `step_execute_v1` | Execute one step (hydrate context, generate patch, hunk-lint, apply) | Ticket Manager / Runner |
| `ticket_validate_v1` | Run user-defined validation commands in a sandbox | Ticket Manager / Close flow |
| `rebase_enhanced_v1` | Perform rebase and conflict resolution with evidence | Ticket Manager / PGS adapter |
| `ticket_evaluate_v1` | Compare planned vs implemented changes and emit gaps report | Ticket Manager |
| `investigate_v1` | Bounded investigation and resume-plan proposal | Root runtime / Monitoring |
| `ticket_repair_v1` | Apply a repair patch, validate, and prepare resume | Root runtime / Monitoring |
| `gc_v1` | Garbage collection and retention enforcement | `workflowctl gc` |
| `migrate_v1` | Schema migrations for WSS/runtime roots | `workflowctl migrate` |

#### 7.4.2 Built-in agent IDs referenced by built-ins

Built-in workflows reference built-in agent prompts. These are identified by `agent:<name>` and resolved either from:
- user overrides (agent precedence in Config & Onboarding §6), or
- the packaged built-in prompt.

Minimum required built-in agent IDs:

- `agent:task_decomposer_v1`
- `agent:step_patch_author_v1`
- `agent:conflict_resolver_v1`
- `agent:evaluator_v1`
- `agent:investigator_v1`
- `agent:repairer_v1`

If a user overrides a built-in agent prompt, the override MUST preserve the declared input/output contract (Config & Onboarding §6.4).



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
| `sandbox_create` | create sandbox (jj workspace) | `sandbox_exec` |
| `sandbox_run` | run tool in sandbox/workspace | `sandbox_exec` |
| `sandbox_destroy` | cleanup sandbox (jj workspace) | `sandbox_exec` |
| `llm_call` | cancellable LLM call wrapper | `net_llm` |
| `spawn_step` | request child step | `spawn_child` |
| `wait_step` | wait for step completion | none |
| `control_write` | write control actions | `control_send` |
| `export_scrub` | build scrubbed bundle | `export_scrub` |
| `graph_static` | generate static graph | none |
| `graph_run` | generate dynamic graph | none |
| `run_python_script` | run registered script artifact | `script_exec` |

### Subcommand `hydrate` (Mode A)

`hydrate` reconstructs file content at a given revision **without** creating a working copy.

It is used to support Mode A step execution (Core Flows Flow 8).

#### Request

```json
{
  "subcommand": "hydrate",
  "repo_uid": "<repo_uid>",
  "run_id": "<run_id>",
  "rev": "<revset or commit id>",
  "paths": ["path/to/file.ext", "dir/"],
  "mode": "file|tree",
  "max_inline_bytes": 65536,
  "text_encoding": "utf-8",
  "slices": [
    { "path": "path/to/file.ext", "start_line": 1, "end_line": 200 }
  ]
}
```

Rules:

- `paths` are repo-relative (validated; no absolute paths, no `..`).
- `mode=file` treats each entry in `paths` as a file path.
- `mode=tree` treats each entry as a directory prefix and hydrates all files under it (subject to size limits).
- `slices` are optional; if present, the gateway returns only the requested line ranges for those paths.

#### Response

```json
{
  "ok": true,
  "resolved_rev": "<commit id>",
  "items": [
    {
      "path": "path/to/file.ext",
      "status": "ok|not_found|binary|too_large|error",
      "size_bytes": 1234,
      "sha256": "sha256:<hex>",
      "is_binary": false,
      "content": "…optional inline text…",
      "slice": { "start_line": 1, "end_line": 200 }
    }
  ],
  "errors": []
}
```

Response rules:

- If `size_bytes <= max_inline_bytes` and the file is text, `content` SHOULD be included.
- If `size_bytes > max_inline_bytes`, the gateway MUST:
  - set `status: "too_large"`
  - include `sha256` and `size_bytes`
  - omit `content` unless the caller requested `slices`
- If a file is binary, the gateway MUST:
  - set `status: "binary"`
  - omit `content` (unless a future binary-slice mode is added)
- The gateway MUST be deterministic: identical `(rev, path, slice)` requests yield identical `sha256`.

#### Implementation (jj backend; normative baseline)

This section defines a baseline implementation for a `jj`-backed repo. Implementations MAY optimize, but MUST preserve semantics.

- Resolve `rev` to a single commit id using `jj` (error if ambiguous).
- For `mode=file`:
  - For each `path`, obtain content via `jj file show --revision <rev> --template '' -- <path>`
- For `mode=tree`:
  1. List files under the directory prefix via:
     - `jj file list --revision <rev> --template '{path}\n' -- <dir>`
  2. For each returned file path, call `jj file show` as above.

Binary detection:

- Treat a file as binary if:
  - it contains NUL bytes, OR
  - it fails UTF‑8 decoding after applying `text_encoding`

Large file handling:

- The gateway MUST stream `jj` output and compute `sha256` as bytes are read.
- Inline content is capped by `max_inline_bytes` (default 64 KiB). Callers that need more must request `slices` or use a sandbox.

Caching:

- The gateway MAY cache hydrated results for the duration of a run keyed by `(resolved_rev, path, slice)`.



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

### 9.2 Sandbox creation algorithm

A **sandbox** is an ephemeral `jj` workspace created under the repo runtime root:

`~/.workflow/repos/<repo_uid>/sandboxes/<run_id>/<sandbox_id>/`

A sandbox is used to:
- execute tool commands in a materialized working copy
- preserve tool outputs as durable evidence (logs, exit codes)
- avoid mutating the user’s primary working copy

#### 9.2.1 Inputs

Sandbox creation is called with:

- `repo_root` (absolute path)
- `baseline_revset` (string; resolves to a single revision)
- `purpose` (string enum): `step_edit|validation|rebase_conflict|evaluation`
- `sparse_mode` (string enum): `copy|full|empty`
- optional `include_patterns` (array of strings)

#### 9.2.2 Pattern syntax and normalization

- Patterns are passed **verbatim** to `jj sparse set --add <pattern>`.
- The runner does not interpret pattern semantics beyond basic safety checks.

Normalization rules applied by the runner:

- Convert Windows `\` separators to `/`
- Reject absolute paths
- Reject paths containing `..` segments
- Reject empty strings

Notes:

- Current `jj` sparse patterns are effectively an **unordered list of path prefixes** (e.g., `src/`, `README.md`). Future `jj` versions may support richer include/exclude rules; this system treats patterns as opaque strings and relies on `jj` for interpretation.

#### 9.2.3 Sparse pattern selection and derivation

Patterns are selected from one of the following sources, in priority order:

1. **Workflow explicit include patterns**  
   - Workflow YAML step: `sandbox.include_patterns: [...]` (Workflow schema §7.2.5)  
   - If present, these patterns are applied exactly.

2. **Step-plan declared file inputs**  
   - If the step is derived from a step plan, use `step.inputs.files[*].path` (Project & Ticket System §6.4).

3. **Fallback defaults by sandbox purpose**  
   - Used only when neither (1) nor (2) is available.

Default derivation (normative):

- If `purpose` is `validation`, `rebase_conflict`, or `evaluation`:
  - Use a full working copy (`sparse_mode = full`)
  - Do not apply derived include patterns (full means full).

- If `purpose` is `step_edit`:
  - Use an empty working copy (`sparse_mode = empty`)
  - Derive `include_patterns` from the declared step file list:
    - For each file `p`:
      - add `p`
      - add the immediate parent directory of `p` (e.g., `src/` for `src/app/main.py`)
    - Add toolchain “root” files to increase tool correctness:
      - `.editorconfig`, `.gitignore`
      - `pyproject.toml`, `requirements.txt`, `poetry.lock`
      - `package.json`, `pnpm-lock.yaml`, `yarn.lock`, `package-lock.json`
      - `go.mod`, `go.sum`
      - `Cargo.toml`, `Cargo.lock`
      - `Makefile`
  - If the step file list is missing or empty, fail loudly with `E_SPARSE_DERIVATION_FAILED` (Core §8.2.5).

#### 9.2.4 Algorithm

Given `(repo_root, baseline_revset, purpose, sparse_mode, include_patterns)`:

1. Allocate `sandbox_id` (ULID)
2. Create directory:
   `~/.workflow/repos/<repo_uid>/sandboxes/<run_id>/<sandbox_id>/`
3. Create a `jj` workspace:
   - `jj workspace add <sandbox_path> --name <sandbox_id> --revision <baseline_revset> --sparse-patterns <copy|full|empty>`
4. Apply sparse patterns (if any):
   - If `include_patterns` is present and non-empty:
     - `jj sparse set --clear --add <pattern> ...` inside the sandbox (jj workspace)
5. Record sandbox metadata:
   - `sandbox_id`, `run_id`, `repo_uid`
   - baseline revset / resolved commit id
   - `purpose`
   - `sparse_mode` and the final applied pattern list
   - `jj` version and platform info
   - → `workspace/runs/<run_id>/artifacts/env/sandbox_<sandbox_id>.json`

#### 9.2.5 Additivity and expansion within a step

- Sandboxes are **per step** by default. Sparse patterns are **not** additive across steps.
- Within a single step execution, sparse patterns may be expanded **monotonically** if:
  - a tool command fails due to missing files that the runner can deterministically identify, and
  - the step’s sandbox policy allows expansion (`x_allow_sparse_expand: true`).

Any expansion MUST:
- be recorded in the sandbox manifest for the step run
- be visible to the user (notification at `info` severity)
- only ever **add** patterns (never remove)

##### Detecting “missing file due to sparse patterns” (normative)

After a sandbox tool invocation fails (non-zero exit code), the runner MAY attempt sparse expansion only if it can extract one or more repo-relative missing paths from the tool output.

Deterministic extraction rules (v1):
- Scan the combined `stdout+stderr` for lines matching common “missing file” patterns, including:
  - `No such file or directory` with a path
  - `cannot open` / `file not found` with a path
- Extract candidate paths and normalize:
  - convert to repo-relative paths (strip sandbox absolute prefix if present)
  - reject absolute paths, paths containing `..`, or paths that escape the repo root
- If zero safe paths are extracted, DO NOT expand; treat the failure as a normal tool failure.

Expansion action (v1):
- Add each extracted file path AND its parent directory pattern to the sandbox sparse set:
  - `jj sparse set --add <path> --add <parent_dir/>`
- Re-run the tool exactly once after the expansion.
- If the second run also fails with missing file output:
  - do not loop;
  - surface `E_SPARSE_DERIVATION_FAILED` and include the extracted paths in error `details`.

The runner MUST NOT automatically remove patterns during a run.
### 9.3 Copy/full fallback (enabled by default; guarded)

Some repos/tools require more files than sparse heuristics capture. The system supports a guarded fallback path to reduce user friction.

Config:
- `[sandbox].copy_fallback = true` by default (Core Infrastructure §11.4)

#### 9.3.1 When fallback triggers (normative)

Fallback may trigger only when ALL are true:

1. The failing step is running inside a sandbox with sparse patterns (i.e., not already `sparse_mode="full"`), AND
2. The tool invocation fails, AND
3. The failure looks like “missing file due to sparse patterns” per §9.2.5, AND
4. Sparse expansion (if allowed) did not resolve the failure OR was not allowed.

If the failure does not match missing-file patterns, fallback MUST NOT trigger.

#### 9.3.2 Fallback algorithm (v1; bounded) (normative)

When fallback triggers, the runner MUST attempt at most two fallback escalations in this order:

1. **Copy fallback**  
   - Recreate the sandbox with `sparse_mode="copy"` (copy sparse patterns from the source workspace)
   - Apply the current include pattern list (if any)
   - Re-run the tool once

2. **Full fallback**  
   - If the copy fallback still fails with missing-file output:
     - Recreate the sandbox with `sparse_mode="full"`
     - Re-run the tool once

If full fallback fails, the runner MUST fail loudly with `E_SPARSE_DERIVATION_FAILED` and include:
- the tool command
- the extracted missing paths (if any)
- the sandbox modes attempted (`empty|copy|full`)

#### 9.3.3 User visibility and evidence

Every fallback escalation MUST:
- write a notification (`warn`) describing the fallback and the mode used
- record the fallback in the sandbox manifest artifact (Integration §9.2.4)
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