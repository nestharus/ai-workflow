---
description: Fix lint errors using lint-fixer agent
agent: orchestrator
subtask: true
---

Run `uv run lint-fix` to fix lint errors.

## Arguments

Pass through to the script:
- `--changed-only`: Only lint changed files
- `--commit <sha>`: Only lint files from specific commit
- `--files <file1> ...`: Only lint specific files
- `--pr <TICKET>`: Lint files changed in PR (e.g., `NES-123`)

These are mutually exclusive.

## Workflow

1. Run `uv run lint-fix $ARGUMENTS`
2. Output the result
