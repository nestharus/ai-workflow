# Checkout Branch into Worktree

---

description: Checkout an existing branch into a git worktree
argument-hint: "`ticket-id` or `branch-name`"
allowed-tools: Bash, Read

---

Checkout an existing branch for: $ARGUMENTS

This command creates a worktree for an existing branch. Unlike `/execute-plan`, it does NOT create
new branches - it only works with branches that already exist locally or on the remote.

## Steps

### 1. Run Checkout

```bash
uv run pr checkout $ARGUMENTS
```

Accepts either:
- Linear ticket ID (e.g., `NES-87`) - fetches `branchName` from Linear
- Branch name directly

Creates worktree at `.worktrees/<branch_name>`.

**JSON output structure:**
```json
{
  "status": "created",           // or "exists" if worktree already exists
  "worktree_path": ".worktrees/<branch_name>",
  "branch_name": "<branch_name>",
  "branch_created": false,       // always false (no new branches created)
  "tracked_remote": true         // only present when status is "created"
}
```

Note: `tracked_remote` is only included when `status: "created"`. When `status: "exists"`, the
worktree was already set up in a previous call, and the field is omitted.

### 2. Output Summary

```text
================================================================================
WORKTREE READY
================================================================================

Branch: {{branch_name}}
Worktree: {{worktree_path}}

Commands:
  cd {{worktree_path}}
  cd {{worktree_path}} && git status
  cd {{worktree_path}} && git log --oneline -5
================================================================================
```

## Error Handling

- **Branch does not exist**: Command fails with error message suggesting `/execute-plan` for new branches
- **Worktree already exists**: Reports existing path without recreating (status: "exists")

## Notes

- Only works with existing branches (local or remote)
- Use `/execute-plan` for new branches
- Use cases: resume work on existing PR, collaborate on someone else's branch, checkout remote branch
