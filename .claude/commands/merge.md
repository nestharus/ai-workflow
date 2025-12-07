---
description: Merge a PR by squashing, rebasing, and completing the merge workflow
allowed-tools: Task, Read, Glob, Bash
---

# Merge PR Command

Merge PR for ticket: $ARGUMENTS

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
- `worktree`: `.worktrees/$ARGUMENTS`
- `base_branch`: The target branch from the PR info (NOT hardcoded to `main`)

### 2. Squash and Rebase

Squash all commits and rebase onto the target branch:

```bash
uv run pr squash-rebase --worktree {{worktree}} --base-branch {{base_branch}}
```

This command:
- Fetches the latest target branch
- Squashes all commits into one (if multiple)
- Rebases onto the target branch

If the command returns exit code 1, conflicts need resolution.

### 3. Resolve Conflicts

If there are merge conflicts during rebase:
1. Identify conflicting files
2. For each conflict, analyze and resolve appropriately
3. Stage resolved files: `git add <file>`
4. Continue rebase: `git rebase --continue`
5. Repeat until rebase completes

### 4. Force Push

After successful rebase:

```bash
cd {{worktree}} && git push --force-with-lease
```

### 5. Complete Merge Workflow

Execute the full merge workflow (merge PR, cleanup, sync, mark done):

```bash
uv run pr merge --ticket $ARGUMENTS --pr {{pr_number}} --worktree {{worktree}} --branch {{branch_name}} --base-branch {{base_branch}}
```

This command performs:
1. Merge the PR (squash merge)
2. Remove git worktree
3. Delete local branch
4. Sync target branch (fetch, stash, checkout, pull, stash pop)
5. Mark Linear ticket as Done

**Note**: The remote branch auto-deletes after merge (configured in GitHub). Do NOT manually delete the remote branch.

## Important Rules

- Always force push with `--force-with-lease` (safer than `--force`)
- Resolve all conflicts before proceeding
- The PR merge auto-deletes the remote branch - do not delete it manually
- If stash pop has conflicts after sync, resolve them manually
