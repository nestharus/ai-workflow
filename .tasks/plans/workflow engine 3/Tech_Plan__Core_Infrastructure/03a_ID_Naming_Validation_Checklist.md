# Core Infrastructure — ID Naming Validation Checklist

- **Doc**: Tech_Plan__Core_Infrastructure/03a_ID_Naming_Validation_Checklist.md
- **Updated**: 2026-01-28
- **Authoritative definitions**:
  - Tech_Plan__Core_Infrastructure/03_IDs_and_Time.md §4.1
  - Tech_Plan__Integration/01_Scope_and_Terminology.md §1.2

## 1) Quick reference (correct usage)

| Context | Correct field name | Meaning | Example |
|---|---|---|---|
| Step plan YAML | `step_id` | Semantic plan step identifier | `step-001` |
| Workflow YAML | `step_id` | Workflow step identifier | `validate_inputs` |
| Runtime (disambiguation) | `workflow_step_id` | Workflow YAML `step_id` when ambiguity exists | `validate_inputs` |
| Runtime execution | `step_execution_id` | ULID for a specific step execution attempt/instance | `01J...` |
| Logs shard naming | `writer_id` | For step processes: MUST equal `step_execution_id` | `01J...` |
| Step artifacts | `.../artifacts/steps/<step_execution_id>/...` | Artifact directory is keyed by `step_execution_id` | `workspace/runs/<run_id>/artifacts/steps/<step_execution_id>/patch.diff` |

## 2) Common mistakes to avoid

- Using `step_id` to refer to a ULID execution instance.
- Writing artifacts under `workspace/runs/<run_id>/steps/<step_id>/...` (wrong ID and missing `artifacts/`).
- Omitting `step_execution_id` from step-related log events (makes correlation unreliable).
- Setting `writer_id` to the semantic `step_id` for step executions (must be the ULID `step_execution_id`).
- Mixing workflow YAML `step_id` (workflow step identifier) with plan `step_id` (semantic plan step identifier) in runtime contexts without using `workflow_step_id`.

## 3) Grep patterns for incorrect usage

Placeholders / spec text:

- Find deprecated artifact path placeholders: `rg -n 'workspace/runs/<run_id>/steps/<step_id>/' .tasks/plans/workflow\\ engine\\ 3`
- Find missing `artifacts/` layer: `rg -n 'workspace/runs/<run_id>/steps/' .tasks/plans/workflow\\ engine\\ 3`
- Find ambiguous step ID language: `rg -n '\\bstep_id\\b.*ULID|ULID.*\\bstep_id\\b' .tasks/plans/workflow\\ engine\\ 3`

Runtime-like patterns (when scanning real artifacts/logs):

- Find paths that look like semantic step IDs under runs: `rg -n 'workspace/runs/[0-9A-HJKMNP-TV-Z]{26}/steps/step-' workspace/`
- Find writer shards that look semantic: `rg -n 'logs/runs/[0-9A-HJKMNP-TV-Z]{26}/writers/step-' logs/`

## 4) Examples (correct vs incorrect)

Step plan YAML (semantic ID):

- Correct: `step_id: step-001`
- Incorrect: `step_execution_id: 01J...` (execution IDs do not belong in the plan)

Workflow YAML step object (workflow step identifier):

- Correct: `- step_id: validate_inputs`
- Incorrect (runtime docs/events): using `step_id` to mean both plan step and workflow step without disambiguation (use `workflow_step_id` where needed)

Runtime artifacts (execution-scoped):

- Correct: `workspace/runs/<run_id>/artifacts/steps/<step_execution_id>/patch.diff`
- Incorrect: `workspace/runs/<run_id>/steps/<step_id>/patch.diff`

Runtime log events (correlation):

- Correct: include both `step_id` (semantic) and `step_execution_id` (ULID) in all step-related events.
- Incorrect: only `step_id` present (cannot reliably correlate to a specific execution attempt).
