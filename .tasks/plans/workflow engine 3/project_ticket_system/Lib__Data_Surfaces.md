# Library: Data Surfaces (`wss_surfaces`)

- **Primary responsibility**: Define which WSS files this layer reads/writes directly, and how the patch stack (jj/PGS) is referenced.
- **Depends on**: (none)
- **Used by**: `pm`, `tm`, `lifecycle`, `decompose`, `execute`, `validate`, `export`, `indexer`

## 1) Authoritative schema source

Durable shapes are defined in:
- `Tech_Plan__Core_Infrastructure.md` (single source of truth)

This library enumerates paths and surface contracts only.

## 2) WSS docs used directly (normative)

- `workspace/projects/<project_id>/project.json`
- `workspace/tickets/<ticket_id>/ticket.json`
- `workspace/tickets/<ticket_id>/tasks/<task_id>/task.json`
- `workspace/runs/<run_id>/run.json`
- `workspace/runs/<run_id>/steps/<step_execution_id>.json`
- (optional) `workspace/projects/<project_id>/workflows/*.yaml`

## 3) Task filesystem layout (normative)

On task creation, TM creates:

```text
workspace/tickets/<ticket_id>/tasks/<task_id>/
  task.json
  input.md
  steps/
  deviations/
  evaluation/
```

`task.json` contains (at minimum):
- `task_id`, `ticket_id`
- `status`
- references to step definitions in `steps/`
- references to runs/patches produced for the task

## 4) PGS (jj) surface used indirectly

Ticket stacks are managed in jj; Ticket Manager persists stack metadata in:
- `workspace/tickets/<ticket_id>/ticket.json`

All “stack operations” (base/tip rev IDs, patch IDs, export bookmarks, etc.) are reflected back into `ticket.json` as durable metadata.

Minimum required fields for stack-aware operations (authoritative schema is in Core Infrastructure):
- `ticket.json.stack_bookmark`
- `ticket.json.base_rev`
- `ticket.json.tip_rev`
- `ticket.json.patches[]`
- `ticket.json.export` (when exported)
