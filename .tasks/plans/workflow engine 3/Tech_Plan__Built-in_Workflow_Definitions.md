# Tech Plan: Built-in Workflow Definitions

- **Date**: 2026-01-24
- **Doc**: Tech_Plan__Built-in_Workflow_Definitions.md
- **Depends on**: `Tech_Plan__Integration.md` (§7.2 workflow schema)
- **Purpose**: Provide the complete, canonical YAML for all built-in workflows referenced across the spec set.
- **See Also**: `Tech_Plan__Agent_Prompt_Definitions.md` for agent prompt definitions referenced by these workflows

## 1) Scope and location (normative)

This document defines the built-in workflow YAML for the workflow runner.

The runner MUST package these workflows exactly as written here, and expose them via the `builtin:<workflow_id>` entrypoint resolution rules in Integration §7.1.

Reference file layout (for distribution):

```text
workflows/builtin/<workflow_id>.yaml
```

## 2) Built-in workflows (v1)

### 2.1 task_decompose_v1

```yaml
schema_version: 1
workflow_id: task_decompose_v1
display_name: "Task decompose (v1)"
description: "Decompose a task into a converged, executable step plan."
inputs:
  type: object
  required: [ticket_id, task_id]
  properties:
    ticket_id: { type: string }
    task_id: { type: string }
    force: { type: boolean, default: false }
steps:
  - step_id: decompose
    kind: agent
    entrypoint: "agent:task_decomposer_v1"
    description: "Produce/merge step_plan.yaml and candidates for the task."
    with:
      ticket_id: "${{ inputs.ticket_id }}"
      task_id: "${{ inputs.task_id }}"
      force: "${{ inputs.force }}"
```

### 2.2 step_execute_v1

```yaml
schema_version: 1
workflow_id: step_execute_v1
display_name: "Step execute (v1)"
description: "Execute a single step from a validated step plan."
inputs:
  type: object
  required: [ticket_id, task_id, step_id]
  properties:
    ticket_id: { type: string }
    task_id: { type: string }
    step_id: { type: string }
    step_execution_id: { type: string }
steps:
  - step_id: execute
    kind: agent
    entrypoint: "agent:step_executor_v1"
    description: "Execute the step; may hydrate, run sandbox commands, and apply patches."
    capabilities_required: ["sandbox_exec", "apply_patch", "llm_call"]
    with:
      ticket_id: "${{ inputs.ticket_id }}"
      task_id: "${{ inputs.task_id }}"
      step_id: "${{ inputs.step_id }}"
      step_execution_id: "${{ inputs.step_execution_id }}"
```

### 2.3 ticket_validate_v1

```yaml
schema_version: 1
workflow_id: ticket_validate_v1
display_name: "Ticket validate (v1)"
description: "Run the ticket's validation workflow in a sandbox."
inputs:
  type: object
  required: [ticket_id]
  properties:
    ticket_id: { type: string }
    rev: { type: string, description: "Optional revision/bookmark to validate; defaults to ticket head." }
steps:
  - step_id: validate
    kind: agent
    entrypoint: "agent:ticket_validator_v1"
    description: "Execute validation commands and record results."
    capabilities_required: ["sandbox_exec", "llm_call"]
    with:
      ticket_id: "${{ inputs.ticket_id }}"
      rev: "${{ inputs.rev }}"
```

### 2.4 rebase_enhanced_v1

```yaml
schema_version: 1
workflow_id: rebase_enhanced_v1
display_name: "Enhanced rebase (v1)"
description: "Perform enhanced rebase with deterministic conflict handling and recovery."
inputs:
  type: object
  required: [ticket_id]
  properties:
    ticket_id: { type: string }
    source_ref: { type: string, description: "Optional source ref; defaults to ticket head." }
    target_ref: { type: string, description: "Optional target ref; defaults to trunk/main." }
steps:
  - step_id: rebase
    kind: agent
    entrypoint: "agent:rebase_driver_v1"
    description: "Run rebase, detect conflicts, and resolve using the enhanced protocol."
    capabilities_required: ["sandbox_exec", "apply_patch", "llm_call"]
    with:
      ticket_id: "${{ inputs.ticket_id }}"
      source_ref: "${{ inputs.source_ref }}"
      target_ref: "${{ inputs.target_ref }}"
```

### 2.5 ticket_evaluate_v1

```yaml
schema_version: 1
workflow_id: ticket_evaluate_v1
display_name: "Ticket evaluate (v1)"
description: "Evaluate a ticket against its requirements and produce an evaluation report."
inputs:
  type: object
  required: [ticket_id]
  properties:
    ticket_id: { type: string }
    rev: { type: string, description: "Optional revision/bookmark to evaluate; defaults to ticket head." }
steps:
  - step_id: evaluate
    kind: agent
    entrypoint: "agent:ticket_evaluator_v1"
    description: "Run evaluation and record findings."
    capabilities_required: ["sandbox_exec", "llm_call"]
    with:
      ticket_id: "${{ inputs.ticket_id }}"
      rev: "${{ inputs.rev }}"
```

### 2.6 investigate_v1

```yaml
schema_version: 1
workflow_id: investigate_v1
display_name: "Investigate (v1)"
description: "Collect evidence and classify failures into actionable next steps."
inputs:
  type: object
  required: [run_id]
  properties:
    run_id: { type: string }
    step_execution_id: { type: string }
    error_code: { type: string }
steps:
  - step_id: investigate
    kind: agent
    entrypoint: "agent:investigator_v1"
    description: "Gather evidence (logs, artifacts) and emit a classification + repair plan."
    capabilities_required: ["sandbox_exec", "llm_call"]
    with:
      run_id: "${{ inputs.run_id }}"
      step_execution_id: "${{ inputs.step_execution_id }}"
      error_code: "${{ inputs.error_code }}"
```

### 2.7 ticket_repair_v1

```yaml
schema_version: 1
workflow_id: ticket_repair_v1
display_name: "Ticket repair (v1)"
description: "Attempt an automated repair for a failed step/run, then re-validate."
inputs:
  type: object
  required: [ticket_id, run_id]
  properties:
    ticket_id: { type: string }
    run_id: { type: string }
    step_execution_id: { type: string }
steps:
  - step_id: repair
    kind: agent
    entrypoint: "agent:ticket_repairer_v1"
    description: "Apply repair changes, update evidence, and rerun targeted validation."
    capabilities_required: ["apply_patch", "sandbox_exec", "llm_call"]
    with:
      ticket_id: "${{ inputs.ticket_id }}"
      run_id: "${{ inputs.run_id }}"
      step_execution_id: "${{ inputs.step_execution_id }}"
```

### 2.8 gc_v1

```yaml
schema_version: 1
workflow_id: gc_v1
display_name: "Garbage collect (v1)"
description: "Run runtime GC: clean expired sandboxes and compact logs."
inputs:
  type: object
  required: []
  properties: {}
steps:
  - step_id: gc
    kind: tool
    entrypoint: "tool:gc"
    description: "Invoke the gateway GC routine."
    with: {}
```

### 2.9 migrate_v1

```yaml
schema_version: 1
workflow_id: migrate_v1
display_name: "Migrate (v1)"
description: "Migrate runtime state and schemas to the current version."
inputs:
  type: object
  required: []
  properties: {}
steps:
  - step_id: migrate
    kind: tool
    entrypoint: "tool:migrate"
    description: "Invoke the gateway migration routine."
    with: {}
```

## 3) Notes (non-normative)

- These workflows intentionally declare broad `capabilities_required` for agent steps. Implementations may later refine capability declarations as agents and gateway schemas stabilize.
- Workflow IDs and filenames MUST remain stable; version by creating new IDs (e.g., `*_v2`) rather than modifying semantics in-place.
- Agent prompt definitions referenced by these workflows are defined in `Tech_Plan__Agent_Prompt_Definitions.md`. Each workflow step with `kind: agent` and `entrypoint: agent:<agent_id>` resolves to the corresponding agent prompt definition.
