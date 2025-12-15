---
description: Checkout an existing branch into a git worktree
argument-hint: "`ticket-id` or `branch-name`"
allowed-tools: Bash, Read
---

# Checkout Branch into Worktree

Checkout an existing branch for: $ARGUMENTS

This command creates a worktree for an existing branch. Unlike `/execute-plan`, it does NOT create
new branches - it only works with branches that already exist locally or on the remote.

## Workflow

### Step 1: Checkout into Worktree

Run the checkout command:

```bash
uv run pr checkout $ARGUMENTS
```

This command:

1. Accepts either a Linear ticket ID (e.g., `NES-87`) or a branch name directly
2. If given a ticket ID, fetches the `branchName` from Linear
3. Checks if the branch exists locally or on the remote
4. If neither exists, returns an error (use `/execute-plan` for new branches)
5. Creates a worktree at `.worktrees/<branch_name>` for the existing branch

The command outputs JSON with the worktree details:

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

### Step 2: Output Summary

Print to terminal:

```text
================================================================================
WORKTREE READY
================================================================================

Branch: {{branch_name}}
Worktree: {{worktree_path}}

Commands:
  # Switch to worktree
  cd {{worktree_path}}

  # Check status
  cd {{worktree_path}} && git status

  # View recent commits
  cd {{worktree_path}} && git log --oneline -5

  # Pull latest changes (if tracking remote)
  cd {{worktree_path}} && git pull
================================================================================
```

## Use Cases

* **Resume work on an existing PR**: Checkout a branch that already has a PR open
* **Collaborate on a branch**: Checkout someone else's branch to review or contribute
* **Work on a branch from another machine**: Checkout a branch that exists on the remote
* **Review a branch locally**: Checkout a branch to test changes before merging

## Error Cases

* **Branch does not exist**: If the branch doesn't exist locally or on remote, the command
  will fail with an error message suggesting to use `/execute-plan` to create a new branch.

* **Worktree already exists**: If a worktree already exists for this branch, the command
  will report the existing worktree path without creating a new one.

* **Invalid ticket ID**: If a Linear ticket ID is provided but not found, the command will fail.

## Comparison with /execute-plan

| Feature | /checkout-branch | /execute-plan |
|---------|------------------|---------------|
| Creates new branches | No | Yes |
| Works with existing branches | Yes | No |
| Requires ticket with plan | No | Yes |
| Creates PR | No | Yes |
| Creates worktree | Yes | Yes |
| Updates Linear ticket | No | Yes |

## Important Rules

* This command does NOT create new branches - only checks out existing ones
* The worktree is created at `.worktrees/<branch_name>` relative to the repository root
* If the branch tracks a remote, you can pull latest changes after checkout
* Do NOT use this for new feature development - use `/execute-plan` instead
