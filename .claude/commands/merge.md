---
description: Merge a PR and perform cleanup (worktree removal, branch sync, ticket completion)
allowed-tools: Task, Read, Glob, Bash
---

# Merge PR Command

Merge PR for ticket: $ARGUMENTS

**Note**: This command assumes the branch has already been rebased and pushed. Use `/rebase` first if needed.

## Workflow

### 1. Get PR Information

```bash
uv run pr get-pr $ARGUMENTS
```

This returns JSON with:
- `branch_name`: Git branch name
- `pr_number`: PR number
- `pr_url`: PR URL
- `base_branch`: Target branch the PR will merge into (e.g., `main`, `develop`)

Set up variables:
- `ticket_id`: $ARGUMENTS
- `worktree`: `.worktrees/{{branch_name}}`
- `base_branch`: The target branch from the PR info (NOT hardcoded to `main`)

### 2. Complete Merge Workflow

Execute the full merge workflow (merge PR, cleanup, sync, conditionally mark done):

```bash
uv run pr merge --ticket $ARGUMENTS --pr {{pr_number}} --worktree {{worktree}} --branch {{branch_name}} --base-branch {{base_branch}}
```

This command performs:
1. Merge the PR (squash merge)
2. Remove git worktree
3. Delete local branch
4. Sync target branch (fetch, stash, checkout, pull, stash pop)
5. Check for remaining open PRs:
   - If **no remaining open PRs**: Mark Linear ticket as Done
   - If **remaining open PRs exist**: Report the next open PR and skip marking done

**Note**: The remote branch auto-deletes after merge (configured in GitHub). Do NOT manually delete the remote branch.

## Important Rules

- Run `/rebase` before `/merge` to ensure the branch is up-to-date with the target
- The PR merge auto-deletes the remote branch - do not delete it manually
- If stash pop has conflicts after sync, resolve them manually
