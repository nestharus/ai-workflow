# Usage — Workflow Debugging Commands

- **Doc**: Usage__Workflow_Debugging.md
- **Updated**: 2026-01-29
- **Primary responsibility**: User-facing guidance for validating workflows, dry-running expression evaluation, and testing `${{ ... }}` expressions without executing any tools or agents.
- **Related specs**:
  - Integration §2: CLI contract (`Tech_Plan__Integration/02_Entrypoints_and_CLI_Contract.md`)
  - Integration §7: Workflow schema + expression rules (`Tech_Plan__Integration/07_Workflows__Surface_and_Schema_v1.md`)
  - Core Infrastructure §8.2.5: Error codes

## Overview

These commands help workflow authors catch errors early and understand evaluation behavior without side effects:

- `workflowctl workflow validate <path-or-id>`
- `workflowctl workflow dry-run <workflow_id> --inputs <json|@file>`
- `workflowctl workflow eval-expr --expr '${{ ... }}' --inputs <json|@file> [--run <run_id>]`

All commands:
- print structured JSON to stdout
- print human-readable errors to stderr
- exit `0` on success and `1` on validation/evaluation errors
- use error code `E_VALIDATION_FAILED` for workflow/schema/expression failures

## Validate

Validate a workflow without executing anything:

```bash
workflowctl workflow validate <path-or-id>
```

`<path-or-id>` can be:
- a file path (YAML), or
- a workflow ID resolved by workflow precedence (Integration §7.1)

Example:

```bash
workflowctl workflow validate task_decompose_v1
workflowctl workflow validate .workflow/workflows/task_decompose_v1.yaml
```

## Dry-run

Compute execution order and evaluate `with:` expressions without running entrypoints:

```bash
workflowctl workflow dry-run <workflow_id> --inputs <json|@file>
```

`--inputs` formats:
- inline JSON string:
  ```bash
  workflowctl workflow dry-run task_decompose_v1 --inputs '{"task_text":"Implement user authentication"}'
  ```
- `@<file>` containing JSON (UTF-8):
  ```bash
  workflowctl workflow dry-run task_decompose_v1 --inputs @./inputs.json
  ```

Dry-run behavior:
- validates the workflow and its inputs schema
- evaluates expressions per Integration §7.2.4
- simulates step outputs (v1 default: empty object) so downstream expressions can reference `steps.<step_id>.output`
- reports dependency-ready `parallel_groups` derived from the DAG (even if the v1 runner is single-threaded)

## Evaluate expression

Evaluate a single `${{ ... }}` expression:

```bash
workflowctl workflow eval-expr --expr '${{ ... }}' --inputs <json|@file> [--run <run_id>]
```

Examples:

```bash
workflowctl workflow eval-expr --expr '${{ inputs.task_id }}' --inputs '{"task_id":"TASK-123"}'
```

Run-context mode (debug using real run state):

```bash
workflowctl workflow eval-expr --expr '${{ steps.plan.output }}' --inputs '{}' --run 01J...
```

In run-context mode, evaluation loads state from WSS under:
- `workspace/runs/<run_id>/`
- `workspace/runs/<run_id>/steps/*.json`

## Troubleshooting

All failures return `E_VALIDATION_FAILED` with a structured reason in details (best-effort). Common reasons:

- `CYCLE_DETECTED`: a `depends_on` cycle exists; remove or break the cycle.
- `INVALID_ENTRYPOINT`: an `entrypoint` reference cannot be resolved; verify agent/workflow/tool availability.
- `SUBWORKFLOW_GRAPH_INVALID`: subworkflow depth exceeded or circular subworkflow references were detected.
- `MISSING_REFERENCE`: an expression references an unavailable path; provide inputs or ensure upstream step outputs exist.
- `INVALID_EXPRESSION_SYNTAX`: expression is not a valid `${{ ... }}` form.
- `TYPE_MISMATCH`: expression evaluation produced an unexpected type for the target field.

