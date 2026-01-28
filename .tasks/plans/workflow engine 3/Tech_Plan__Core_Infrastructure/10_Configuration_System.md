# Core Infrastructure — Configuration System

* **Doc**: Tech_Plan__Core_Infrastructure/10_Configuration_System.md
* **Updated**: 2026-01-26
* **Library**: `workflow_engine.config`
* **Depends on**: [`00_Foundation.md`](00_Foundation.md),
  [`12_Privacy_Secrets_and_Export.md`](12_Privacy_Secrets_and_Export.md)
* **Primary responsibility**: Define the TOML-based config format, precedence
  rules, validation requirements, and deterministic model routing.

## 11) Configuration system (explicit, schema-validated)

### 11.1 Config format

All config files are TOML (`.toml`) for readability and easy hand-editing.

### 11.2 Config precedence (highest wins)

Config is loaded from multiple layers; higher layers override lower layers.

1. CLI flags
2. Repo machine-local (per repo per machine): `~/.workflow/repos/<repo_uid>/config.toml`
3. Repo shared (optional, committed): `<repo_root>/.workflow/config.toml`
4. User-global (installation): `~/.workflow/config.toml`
5. Built-in defaults

Notes:

* This precedence applies to **config TOML** only.

**Config reload behavior (normative)**:

* Config is loaded once per **command invocation** (e.g., one `workflowctl
  run`), producing an immutable "effective config" snapshot for that invocation.
* Long-running runs MUST NOT change behavior mid-run due to config file edits.
* Step processes inherit the effective config snapshot from their parent
  (root runtime) via explicit serialization in the step execution doc.
* Workflow and agent precedence are defined separately (Integration §7.1,
  Configuration & Onboarding §6).

### 11.3 Config logging (trust requirement)

On process start, the effective config MUST be logged as:

* `config_hash` (sha256 over canonicalized config)
* `config_redacted_preview` (sensitive keys removed)

Sensitive keys include:

* any key under `[secrets]`, `[providers]`, `[auth]`
* values matching secret-scan regexes (§12.3)

### 11.4 Minimum config schema (v1)

```toml
[sandbox]
# Defaults: cross-platform safe; performance tuning is optional
mode = "workspace"                 # workspace (default)
max_concurrent = 4
default_sparse = "copy"            # copy|full|empty (jj workspace add behavior)
copy_fallback = true               # allow fallback when sparse/workspace is insufficient
ttl_minutes = 120

[queues]
processing_ttl_ms = 300000         # 5 minutes
lease_refresh_ms = 30000           # consumer heartbeat cadence
max_requeue_attempts = 1           # bounded; avoid silent loops
notification_dedupe_window_ms = 60000  # 60 seconds; CLI display deduplication window

[retention]
keep_runs = 50
keep_days = 30
compress_old_logs = true

[pause]
deadline_ms = 10000
tool_stop_grace_ms = 2000

[privacy]
network_mode = "llm_only"          # off|llm_only|unrestricted
redaction_mode = "block_on_secret" # block_on_secret|redact_and_continue
export_scrub_default = true

[models]
default = "chatgpt_5_2"
# routing can be overridden per workflow and per step

[models.routing]
# Routing key → model name (see Configuration & Onboarding §5.3)
planning = "claude-opus"
implementation = "claude-sonnet"
validation = "chatgpt-5"
multimodal = "gemini-3"

[models.fallbacks]
# Fallback mappings for unavailable models (optional)
# format: primary_model_id = "fallback_model_id"
# When a primary model is unavailable, the fallback is used
# Example: claude-opus = "claude-sonnet-4-1-20250515"

[models.budget]
# Budget controls per workflow run (optional)
budget_tokens_per_run = 1000000
budget_usd_per_run = 5.00
# Note: USD enforcement requires a cost table to be configured for
# token-to-USD conversion (see Integration §7.2.9 for gateway contract)

[dependencies]
jj_min_version = "0.22.0"
jj_recommended_version = "0.37.0"
auto_bootstrap_jj = true

[cli]
# Set by configuration agent (see Configuration & Onboarding §4)
default = ""                       # "claude-code"|"opencode"|"cursor"|"windsurf"|""
```

### 11.4.3 Notification Deduplication Window (normative)

The `notification_dedupe_window_ms` setting controls time-based deduplication for
CLI display to reduce notification spam.

**Purpose**: When multiple notifications with the same `(dedupe_key, severity)`
tuple are generated within the configured window, CLI consumers suppress
displaying duplicates while showing a count of suppressed notifications.

**Default value**: `60000` milliseconds (60 seconds)

**Scope**: This setting applies ONLY to CLI display via `workflowctl notifications
tail` and similar commands. It does NOT affect persistence.

**Invariant (normative)**: All notifications MUST be persisted to disk regardless
of deduplication status. The deduplication window affects only what is displayed
to the user, not what is recorded.

**Deduplication key**: `(dedupe_key, severity)` tuple. Two notifications are
considered duplicates for display purposes if and only if both fields match.

**Behavior**: Within the configured window, duplicate notifications are suppressed
from display but counted. The CLI displays a `+N suppressed` indicator showing
how many notifications were suppressed. After the window expires, the next
notification with the same `(dedupe_key, severity)` starts a new deduplication
window.

Cross-reference: See Queues & Notifications §9.1 for the full deduplication
specification, and Integration §2.2.1 for CLI display behavior.

### 11.4.4 Model fallback behavior (normative)

**Fallback trigger conditions**:

* A fallback is used ONLY when the resolved model is not available in the configured
  model catalog AND `[models.fallbacks]` contains an explicit mapping from the
  unavailable model ID to a fallback ID
* Fallbacks DO NOT apply to explicit resolution failures (e.g., routing key not
  found)

**Fallback behavior (normative)**:

1. When a fallback is applied, emit an explicit informational notification to the
   user (must not be silent)
2. Set run metric `llm_model_fallback_used = true` in run.json metadata
3. The gateway usage payload (see §11.4.4 below) applies to the actual model used
   (whether fallback or primary)
4. Fallback selection logic is governed by the gateway contract (Integration
   §7.2.9.E)

### 11.4.5 Gateway usage payload schema (normative)

The gateway returns a usage object on each LLM call with the following fields:

```json
{
  "prompt_tokens": 12345,
  "completion_tokens": 6789,
  "total_tokens": 19134,
  "latency_ms": 3250
}
```

Field definitions (normative):

* `prompt_tokens` (int): Number of tokens in the request prompt
* `completion_tokens` (int): Number of tokens in the model response
* `total_tokens` (int): Sum of prompt_tokens and completion_tokens
* `latency_ms` (int): Request-to-response latency in milliseconds

This schema is the contract between gateway, config, and runner. All three MUST
use these exact field names and types.

### 11.4.6 Aggregated LLM usage artifact schema (normative)

The runner aggregates all LLM usage across a workflow run and writes to:
`workspace/runs/<run_id>/artifacts/llm_usage.json`

```json
{
  "run_id": "<run_id>",
  "workflow_id": "<workflow_id>",
  "total_prompt_tokens": 12345,
  "total_completion_tokens": 54321,
  "total_tokens": 66666,
  "total_latency_ms": 15000,
  "calls_by_model": {
    "claude-opus-4-5-20251101": {
      "prompt_tokens": 10000,
      "completion_tokens": 40000,
      "total_tokens": 50000,
      "call_count": 5
    },
    "gemini-3-pro-20250115": {
      "prompt_tokens": 2345,
      "completion_tokens": 14321,
      "total_tokens": 16666,
      "call_count": 2
    }
  },
  "fallback_used": false
}
```

Field definitions (normative):

* `run_id` (string): The ULID of the run
* `workflow_id` (string): The workflow identifier
* `total_prompt_tokens` (int): Sum of all prompt_tokens across all calls
* `total_completion_tokens` (int): Sum of all completion_tokens across all calls
* `total_tokens` (int): Sum of all total_tokens across all calls
* `total_latency_ms` (int): Sum of all latency_ms across all calls
* `calls_by_model` (object): Nested object keyed by model ID with per-model stats:
  * `prompt_tokens` (int): Total prompt tokens for that model
  * `completion_tokens` (int): Total completion tokens for that model
  * `total_tokens` (int): sum of prompt_tokens and completion_tokens for that model
  * `call_count` (int): Number of calls made to that model
* `fallback_used` (boolean): true iff any model fallback occurred during the run

**Run metadata field (normative)**:

* `llm_model_fallback_used` (boolean, in run.json): Mirror of fallback_used for
  quick query; MUST match fallback_used in llm_usage.json

Cross-reference: Integration §7.2.9.E defines the execution behavior for
collecting and aggregating this data. This section defines the normative schema.

### 11.4.1 Sandbox TTL semantics

Sandbox cleanup is governed by `[sandbox] ttl_minutes`.

* Each sandbox metadata record MUST include:
  * `created_at`
  * `last_used_at`
* `last_used_at` is initialized to `created_at` and updated:
  * after every sandbox command invocation (success or failure)

Expiration rule (normative):

* A sandbox is eligible for cleanup when:
  * `now - last_used_at > ttl_minutes`
  * AND the sandbox is not referenced by an active run

If `last_used_at` is missing (legacy sandboxes), cleanup uses `created_at` as the
start time.

**Enforcement (normative)**:

* Sandbox TTL is enforced by `workflowctl gc` (Core §11.5) and MAY also be enforced
  opportunistically at the end of `workflowctl run` / `workflowctl validate`.
* Enforcement MUST:
  1. acquire `locks/gc.lock`
  2. enumerate sandboxes under `~/.workflow/repos/<repo_uid>/sandboxes/`
  3. delete only sandboxes eligible by the rule above
  4. record a `gc_sandbox_deleted` event (or `fsck_issue` on failure) with
     `sandbox_id` and path

Note: Skills are managed by the AI coding CLI, not by the workflow engine config.

### 11.4.2 Model selection and override precedence (normative)

A workflow run selects a model for each **step execution**.

Model selection is **deterministic** and follows this precedence (highest wins):

1. CLI override: `workflowctl run ... --model <model_ref>` (applies to all
   steps unless a step explicitly overrides again via
   `--respect-step-model=false`, which is NOT supported in v1)
2. Step-level override (workflow YAML): `steps[*].model: <model_ref>`
3. Workflow default (workflow YAML): `defaults.model: <model_ref>`
4. Effective config default: `[models].default = <model_ref>`

Where `<model_ref>` is either:

* an explicit model name (e.g., `chatgpt_5_2`, `gemini_3`), OR
* a routing key (e.g., `planning`, `implementation`, `validation`, `multimodal`)

**Routing resolution (normative)**:

Convention: **implicit key resolution** (no `route:` prefix).

* If `<model_ref>` matches a known explicit model name, use it.
* Otherwise treat it as a routing key and resolve via `[models.routing].<key>`.
* If no mapping exists, fail loudly with `E_MODEL_ROUTE_NOT_FOUND` and include:
  * the unresolved key
  * the effective config file(s) used (paths only)
  * the workflow and step IDs (if applicable)

This section defines only **intra-run** precedence. File-level config precedence
is defined in §11.2.

> Retention and garbage collection are specified in **Core §11.5**, split into:
> [`11_Retention_and_GC.md`](11_Retention_and_GC.md).
