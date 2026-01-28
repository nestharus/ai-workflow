# Tech Plan: Integration — Workflows Surface & Schema (v1)

- **Doc**: Tech_Plan__Integration/07_Workflows__Surface_and_Schema_v1.md
- **Updated**: 2026-01-26
- **Shard**: Integration §7.0–§7.2.8
- **Libraries / packages**:
  - `scripts/core/workflows/registry.py` — workflow discovery + precedence
  - `scripts/core/workflows/schema.py` — schema validation (workflow YAML + inputs schema subset)
- **Depends on**:
  - `Tech_Plan__Core_Infrastructure.md` (WSS layout, error codes, TTL semantics)
  - `Tech_Plan__Configuration_&_Onboarding.md` (agent precedence + provider config)

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
    - `copy` — inherit sparse patterns from parent jj workspace
    - `full` — full working copy
    - `empty` — empty working copy
  - After sandbox creation, the runner may still apply explicit patterns via `jj sparse set`.

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

- `mode` (string enum, required)
  - `stop` — stop the workflow run and mark failed
  - `pause` — stop and require user action
  - `investigate` — spawn investigator with bounded evidence
  - `continue` — continue to the next step despite failure

Optional sub-objects:

- `investigate` (object, optional; used when `mode: investigate`)
  - `pause_before_investigate` (bool, default `true`)
  - `bundle_event_limit` (int, default `200`)

- `pause` (object, optional; used when `mode: pause`)
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
