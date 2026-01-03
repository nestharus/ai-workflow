# Ticket 7: Lint Fixer Agent

Implements: [TASK-05](plan.md#task-05--implement-lint-fixer-agent)

## Implements

- Component: [COM-05](design-map.md#component-com-05-lint-fixer)
- Algorithms: ALG-LINT-01, ALG-LINT-02
- Contracts: [CON-11](design-map.md#component-com-05-lint-fixer)
- PRD Rules: INV-01, ROUTE-05

## Dependencies

- Requires: [TASK-02](plan.md#task-02--define-state-schemas)

## Files to Create/Modify

| Action | Path |
|--------|------|
| create | `.agents/agents/pr-lint-fixer.md` |

## Acceptance Criteria

- [ ] Agent instruction file created
- [ ] Always uses Minimax model (per [ROUTE-05](requirements.md#route-05))
- [ ] Runs project linters via `uv run lint`
- [ ] Applies fixes for:
  - ruff formatting
  - ruff linting
  - mypy type errors
  - shellcheck warnings
- [ ] Returns result with status and fixes applied

## Model Selection

Per [ROUTE-05](requirements.md#route-05) and [INV-01](requirements.md#inv-01):

Linting ALWAYS uses Minimax. No routing decision needed.

## Lint Process

1. Run `uv run lint --files {file_path}`
2. Parse lint output for issues
3. Apply auto-fixes where possible
4. Manual fixes for remaining issues
5. Re-run lint to verify

## Input Context

```json
{
  "file_path": "path/to/file.py"
}
```

## Output Result

```json
{
  "file_path": "path/to/file.py",
  "status": "success | error",
  "issues_found": 5,
  "issues_fixed": 5,
  "fixes_applied": [
    "Formatted with ruff",
    "Fixed unused import",
    "Added type annotation"
  ]
}
```
