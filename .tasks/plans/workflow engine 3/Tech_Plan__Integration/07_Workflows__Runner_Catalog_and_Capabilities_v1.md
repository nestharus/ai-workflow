# Tech Plan: Integration — Workflow Runner, Capability Gating & Built-ins (v1)

- **Doc**: Tech_Plan__Integration/07_Workflows__Runner_Catalog_and_Capabilities_v1.md
- **Updated**: 2026-01-26
- **Shard**: Integration §7.2.9–§7.4
- **Libraries / packages**:
  - `scripts/core/workflows/runner.py` — workflow execution loop + step scheduling
  - `scripts/core/workflows/registry.py` — built-in catalog + overrides
  - `scripts/core/runtime/step.py` — step spawning / progress guard integration (by contract)
- **Depends on**:
  - `Tech_Plan__Core_Infrastructure.md` (run/step docs, errors, retention)
  - Integration §8 (`08_Workflow_Engine_Gateway.md`) for gateway tool invocation contracts

## 7) Workflows as a first-class integration surface (user-defined)

This document continues Integration §7. For workflow discovery, precedence, and schema definitions through §7.2.8, see:
- `Tech_Plan__Integration/07_Workflows__Surface_and_Schema_v1.md`

### 7.2 Workflow schema v1 (continued)

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
