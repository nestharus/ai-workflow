---
description: Checkout an existing branch into a git worktree
name: checkout
argument-hint: "`ticket-id` or `branch-name`"
agent: agent
tools:
  - "*"
---

# Checkout Branch into Worktree

Checkout an existing branch for the provided ticket ID or branch name: ${input:branch}

This prompt creates a worktree for an existing branch. Unlike the execute-plan agent (use #runSubagent to delegate to it), it does NOT create new branches - it only works with branches that already exist locally or on the remote.

## Workflow

### Step 1: Checkout into Worktree

Run the checkout command with the provided argument (ticket-id or branch-name) using #tool:terminal:

```bash
uv run pr checkout ${input:branch}
```

This command:

1. Accepts either a Linear ticket ID (e.g., `NES-87`) or a branch name directly
2. If given a ticket ID, fetches the `branchName` from Linear
3. Checks if the branch exists locally or on the remote
4. If neither exists, returns an error (use execute-plan agent for new branches)
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

Note: `tracked_remote` is only included when `status: "created"`. When `status: "exists"`, the worktree was already set up in a previous call, and the field is omitted.

### Step 2: Output Summary

Print to #tool:terminal:

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
================================================================================
```

## Use Cases

* **Resume work on an existing PR**: Checkout a branch that already has a PR open
* **Collaborate on a branch**: Checkout someone else's branch to review or contribute
* **Work on a branch from another machine**: Checkout a branch that exists on the remote

## Error Cases

* **Branch does not exist**: If the branch doesn't exist locally or on remote, the command will fail with an error message suggesting to use execute-plan agent to create a new branch.

* **Worktree already exists**: If a worktree already exists for this branch, the command will report the existing worktree path without creating a new one.

## Comparison with execute-plan

| Feature | checkout | execute-plan |
|---------|-----------|---------------|
| Creates new branches | No | Yes |
| Works with existing branches | Yes | No |
| Requires ticket with plan | No | Yes |
| Creates PR | No | Yes |
