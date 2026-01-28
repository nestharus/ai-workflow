# Tech Plan: Integration — Workflow Runner, Capability Gating & Built-ins (v1)

* **Doc**: Tech_Plan__Integration/07_Workflows__Runner_Catalog_and_Capabilities_v1.md
* **Updated**: 2026-01-26
* **Shard**: Integration §7.2.9–§7.4
* **Libraries / packages**:
  * `scripts/core/workflows/runner.py` — workflow execution loop + step scheduling
  * `scripts/core/workflows/registry.py` — built-in catalog + overrides
  * `scripts/core/runtime/step.py` — step spawning / progress guard integration
    (by contract)
* **Depends on**:
  * `Tech_Plan__Core_Infrastructure.md` (run/step docs, errors, retention)
  * Integration §8 (`08_Workflow_Engine_Gateway.md`) for gateway tool invocation
    contracts

## 7) Workflows as a first-class integration surface (user-defined)

This document continues Integration §7. For workflow discovery, precedence, and schema
definitions through §7.2.8, see:

* `Tech_Plan__Integration/07_Workflows__Surface_and_Schema_v1.md`

### 7.2 Workflow schema v1 (continued)

#### 7.2.9 Workflow runner execution model (v1)

This section defines the **normative** execution behavior of `workflowctl run`.

##### A) Determinism and ordering

* A workflow defines a DAG via `depends_on`.
* In v1, the runner is **single-threaded** (no parallel step execution).
* When multiple steps become ready at the same time, the runner MUST choose the next
  step by **file order** (the order in `steps:`).

##### B) Run initialization

On `workflowctl run --workflow <id-or-path>`:

1. Resolve the workflow definition file (precedence §7.1) and validate against
   schema (§7.2).
2. Resolve and validate workflow `inputs` (see §7.2.6 + prompt rules below).
3. **Model selection** ( precedence resolution):
   * CLI flag `--model <value>` (highest precedence)
   * Step-level `steps[].model` (if defined)
   * Workflow-level `workflow.defaults.model` (if defined, see §7.2.8)
   * Config `models.default` (lowest precedence)
   * Model routing resolution:
     * If model value starts with `route:<key>`, resolve via
       `models.routing.<key>` in config
     * If routing key not found → fail loudly with `E_MODEL_ROUTE_NOT_FOUND`
   * Model availability validation:
     * If the resolved model is not available in the configured model catalog,
       fail loudly with `E_DEPENDENCY_MISSING` (explicit model name in error)
     * Fallback model use is ONLY permitted when `[models.fallbacks]` contains
       an explicit mapping from the unavailable model to a fallback ID

4. Allocate `run_id` (ULID).
5. Write `workspace/runs/<run_id>/run.json` with:
   * `workflow_id`
   * `status: "running"`
   * `started_at`
   * A plan view:
     * `plan.steps[] = {step_id, depends_on[], kind, status:"pending"}`

##### C) Step execution loop

The runner repeatedly selects and executes steps until the plan is terminal.

A step is **ready** when:

* Its plan status is `pending`, AND
* All `depends_on` steps have plan status `completed`

DAG traversal algorithm (v1, deterministic, single-threaded):

```text
parse workflow YAML → workflow
validate schema_version, unique step_id, DAG acyclic

order = workflow.steps in file order
state[step_id] = PENDING

while exists PENDING step:
  ready = [s in order where state[s] == PENDING and all deps are COMPLETED]
  if ready is empty:
     blocked = [s in order where state[s] == PENDING and
                any dep in {FAILED, BLOCKED, SKIPPED}]
     if blocked is non-empty:
        for s in blocked:
           state[s] = BLOCKED with blocked_by = list of failed deps
        continue
     else:
        fail loudly: E_VALIDATION_FAILED ("deadlock / unsatisfied deps")
  s = ready[0]  # earliest in file order
  execute s → result (COMPLETED | FAILED | NEEDS_USER)
  if result == COMPLETED:
     state[s] = COMPLETED
  else:
     state[s] = FAILED (or NEEDS_USER mapped to FAILED with error_code)
     apply on_failure policy:
       * stop: mark remaining PENDING as BLOCKED(reason="run_stopped")
         and end run
       * pause: same as stop + emit PAUSE
       * investigate: spawn investigator workflow, then end run (unless
         explicit resume)
       * continue: keep going; dependents will become BLOCKED by the rule
         above
end
```

Execution of a ready step:

1. Allocate `step_execution_id` (ULID).
2. Create step execution doc `workspace/runs/<run_id>/steps/<step_execution_id>.json`
   with:
   * `workflow_id`, `step_id`, `step_execution_id`, `run_id`
   * `status: "running"`, `started_at`
   * The fully materialized step input object (result of evaluating `with:`
     expressions)
3. Execute the step based on its kind:
   * `kind: tool` → call the gateway tool (Integration §8)
   * `kind: agent` → spawn a step process (Monitoring §2.2) which performs
     LLM calls via the gateway
   * `kind: script` → run a registered script artifact via the gateway
   * `kind: subworkflow` → run a nested workflow (child run) and capture its
     outputs
   * `kind: gate` → pause execution, wait for control action (user approval,
     selection, or resume), then either resume with user-provided data or fail
     with specified error
   * `kind: noop` → mark step as completed immediately with no side effects,
     useful for checkpoints, markers, or conditional no-ops
4. On success:
   * Update step execution doc: `status:"completed"`, `ended_at`, and
     `output` (bounded JSON object)
   * Update the run plan: `plan.steps[step_id].status="completed"`
5. On failure:
   * Update step execution doc: `status:"failed"`, `ended_at`, and `error`
     (structured error object)
   * Apply failure policy (`on_failure`, §7.2.7), updating run status
     accordingly.

##### D) Step inputs/outputs and expression resolution

* Workflow runtime inputs are a JSON object that validates against `inputs`
  schema.
* Each step has a **materialized input object**, computed by:
  * Taking the step's `with:` mapping (if present)
  * Evaluating expressions per §7.2.4 using:
    * `inputs.*`
    * `steps.<step_id>.output` from already-completed steps

Expression evaluation (${{ }}) — evaluation order + errors (v1):

* **Evaluation timing**: Expressions MUST be evaluated before starting the step
  process.
* **Recursive evaluation**: Evaluation is recursive over objects/arrays.
* **Map iteration order**: MUST use YAML order as parsed (deterministic display;
  not required for correctness).
* **Allowed references**: Expressions may only reference:
  * `inputs.<field>`
  * `steps.<step_id>.output` (entire output object)
  * `steps.<step_id>.output.<field>`
  * `steps.<step_id>.artifacts.<name>` (artifact reference emitted by step runner)
* **Forbidden references**: Expressions MUST NOT reference siblings in the same
  `with` object (no `with.foo` access).
* **Error handling**:
  * Missing reference or type mismatch → fail `E_VALIDATION_FAILED`
  * Exception: If the step declares `x_allow_missing: true` (extension key),
    missing references are not treated as errors (may resolve to null)
* **Type rules**:
  * If the entire string is exactly one expression token, preserve the
    referenced JSON type.
  * Otherwise, perform string interpolation.

Step output storage (schema + size limits)—normative storage rules (v1):

* **Step execution doc location**:
  `workspace/runs/<run_id>/steps/<step_execution_id>.json`
* **Inline output location**: `step_exec.output` (JSON object only).
* **Artifact outputs location**:
  `workspace/runs/<run_id>/artifacts/steps/<step_execution_id>/...`
* **Size limit** (v1, to avoid bloat and silent truncation):
  * `max_inline_step_output_bytes = 262144` (256 KiB) after canonical JSON
    encoding.
* **Oversize handling**: If exceeded, step MUST fail loudly with
  `E_VALIDATION_FAILED` and message "step output too large; store as artifact
  and reference it".
* **Schema validation**: If the step definition includes an `output_schema`,
  runner MUST validate output against it.
* **Validation failure**: On mismatch, fail loudly `E_VALIDATION_FAILED` with
  field-level errors (best effort).

##### E) LLM usage tracking and budget enforcement

**Fallback model configuration** (optional):

* Config may include `[models.fallbacks]` mapping from primary model IDs to
  fallback model IDs
* When a fallback is used:
  * Emit explicit informational notification to user (not silent)
  * Set run metric `llm_model_fallback_used=true` in run metadata
* Fallback selection logic is governed by the gateway contract (Integration §8)

**Usage tracking**:

* Each `llm_call` returns usage object (gateway contract, Integration §8):
  * `prompt_tokens`: int
  * `completion_tokens`: int
  * `total_tokens`: int
  * `latency_ms`: int
* Runner aggregates usage across all LLM calls in the workflow run
* Write aggregated usage to `workspace/runs/<run_id>/artifacts/llm_usage.json`:

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
      }
    },
    "fallback_used": false
  }
  ```

**Budget enforcement**:

* Config may include `models` section with token and USD limits:
  * `budget_tokens_per_run`: int (optional, e.g., 1000000)
  * `budget_usd_per_run`: decimal (optional, e.g., 5.00)
    * Note: USD enforcement requires a cost table to be configured for token-
      to-USD conversion
* After each LLM call, runner checks if any budget would be exceeded:
  * If exceeded: stop the run, set `status="needs_user"`, and halt step
    execution
  * Rationale: User intervention required to either increase budget or
    modify workflow
* Budget status is tracked in `run.json`:

  ```json
  {
    "budget_status": {
      "tokens_used": 66666,
      "tokens_limit": 1000000,
      "usd_used": 0.33,
      "usd_limit": 5.00,
      "budget_exceeded": false
    }
  }
  ```

##### F) Failure policy semantics (explicit statuses and propagation)

`on_failure.mode` applies to the step that failed:

* `stop`:
  * Set `run.json.status="failed"` and stop scheduling new steps.
* `pause`:
  * Set `run.json.status="paused"` and stop scheduling new steps until
    resumed.
* `investigate`:
  * Set `run.json.status="investigating"`
  * Enqueue a control action requesting investigation (Monitoring §5)
  * Do not schedule new steps until a resume plan is applied.
* `continue`:
  * Mark the step as failed and continue scheduling any steps that are still
    runnable.
  * Any step that depends (directly or transitively) on a failed step is left
    `blocked` in the plan.
  * The run ends as `failed` if any step is `failed` or `blocked`; otherwise it
    ends `completed`.

Failure propagation semantics (explicit statuses):

* **If a step fails**:
  * Any step that depends (directly or transitively) on the failed step becomes
    **BLOCKED** with `blocked_by=[...]`.
* **`continue` mode**:
  * Runner continues executing steps whose deps are satisfied.
  * Blocked steps remain blocked (never silently skipped).
* **`stop`/`pause`/`investigate` mode**:
  * Runner stops scheduling any further steps.
  * Remaining pending steps MUST be marked **BLOCKED**(reason="run_stopped").

Terminal condition:

* `completed` when all plan steps are `completed`.
* `failed` when:
  * Any step is `failed` and `on_failure.mode != "pause"/"investigate"` OR
  * Any step is `blocked` at end of scheduling.
* `needs_user` when budget limits are exceeded (see §E).

### 7.3 Capability gating (trust)

Workflows may request capabilities. The runner enforces:

* If capability is not enabled in config → fail loudly
* If capability is marked "dangerous" → require explicit user ack (per run)
  unless allowlisted

Example dangerous capabilities:

* Network beyond LLM providers
* Write outside sandbox
* Git/jj push
* File deletion outside sandbox

### 7.4 Built-in workflow catalog v1

This catalog enumerates the workflow IDs that ship with the tool (the `builtin:`
namespace).

Built-ins exist so the system can run out-of-the-box. Users may override them via
the normal workflow precedence rules (Integration §7.1). If an override is
present, it is used; otherwise the built-in is used.

#### 7.4.1 Built-in workflow IDs

**Normative definitions**: The complete YAML for each built-in workflow is
specified in:

* `Tech_Plan__Built-in_Workflow_Definitions.md`

The runner MUST package built-in workflows exactly as specified there.

| workflow_id | Primary responsibility | Typical caller |
|---|---|---|
| `task_decompose_v1` | Convert task → step plan + cand. | Ticket Manager |
| `step_execute_v1` | Execute step (hydrate, patch, lint) | Ticket Manager / Runner |
| `ticket_validate_v1` | Run user validations in sandbox | Ticket Manager / Close |
| `rebase_enhanced_v1` | Rebase + conflict resolution w/ evidence | Ticket Manager / PGS |
| `ticket_evaluate_v1` | Compare vs implemented changes; gaps | Ticket Manager |
| `investigate_v1` | Investigation and resume-plan proposal | Root / Monitoring |
| `ticket_repair_v1` | Apply repair, validate, prepare resume | Root / Monitoring |
| `gc_v1` | Garbage collection + retention enf. | `workflowctl gc` |
| `migrate_v1` | Schema migrations for WSS/runtime | `workflowctl migrate` |

#### 7.4.2 Built-in agent IDs referenced by built-ins

Built-in workflows reference built-in agent prompts. These are identified by
`agent:<name>` and resolved either from:

* User overrides (agent precedence in Config & Onboarding §6), or
* The packaged built-in prompt.

Minimum required built-in agent IDs:

* `agent:task_decomposer_v1`
* `agent:step_patch_author_v1`
* `agent:conflict_resolver_v1`
* `agent:evaluator_v1`
* `agent:investigator_v1`
* `agent:repairer_v1`

If a user overrides a built-in agent prompt, the override MUST preserve the
declared input/output contract (Config & Onboarding §6.4).
