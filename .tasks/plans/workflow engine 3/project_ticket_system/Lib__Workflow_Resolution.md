# Library: Workflow Resolution (`workflow_resolver`)

- **Primary responsibility**: Resolve “workflow IDs” into concrete workflow definitions using deterministic precedence and overrides.
- **Depends on**: `wss_surfaces` (for on-disk locations)
- **Used by**: `tm`, `pm`, `decompose`, `execute`, `validate`, `export`

**Locking / concurrency note (normative):** Any lock acquisition performed by workflow resolution MUST comply with
`Tech_Plan__Core_Infrastructure/05_Multi_Writer_Correctness.md` §6.4.

## 1) Workflow selection model

Every major Ticket Manager action is a workflow invocation:

| Action | Default `workflow_id` | Purpose |
|---|---|---|
| task decomposition | `task_decompose_v1` | input → step plan + approvals |
| step execution | `step_execute_v1` | execute a planned step (hydrate → patch → gate) |
| ticket validation | `ticket_validate_v1` | lint/tests/build in a sandbox |
| enhanced rebase | `rebase_enhanced_v1` | rebase + conflict resolution jobs |
| evaluation | `ticket_evaluate_v1` | planned vs implemented gaps report |

## 2) Override and precedence (normative)

Workflow resolution MUST follow Integration §7.1 precedence, highest to lowest:

1. **CLI file override**: `--workflow-file <path>`
2. **Project-scoped WSS workflows**: `workspace/projects/<project_id>/workflows/*.yaml`
3. **Repo-shared workflows**: `<repo>/.workflow/workflows/*.yaml`
4. **Repo machine-local workflows**: `workspace/workflows/*.yaml`
5. **Built-in workflows**: `builtin:<workflow_id>`

Selection flags:
- `--workflow <workflow_id>` selects by ID using the above resolution rules.
- `--workflow-file <path>` selects an explicit file (highest precedence).

## 3) Determinism and ambiguity (normative)

If multiple candidates exist at the same precedence level, selection MUST be deterministic:
- prefer exact filename match `<workflow_id>.yaml`
- else fail loudly with `WORKFLOW_AMBIGUOUS`
