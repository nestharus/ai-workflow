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

### 2. Gather Merge Context (Before Squash)

Before squashing, gather context needed for conflict resolution:

```bash
cd {{worktree}} && git fetch origin {{base_branch}}
```

Find the merge-base (original base commit before branches diverged):

```bash
cd {{worktree}} && git merge-base origin/{{base_branch}} HEAD
```

Store this as `base_commit`.

Find commits added to target branch since the base:

```bash
cd {{worktree}} && git log --oneline {{base_commit}}..origin/{{base_branch}}
```

Store these commit SHAs as `target_commits` (list from oldest to newest).

### 3. Squash and Rebase

Squash all commits and rebase onto the target branch:

```bash
uv run pr squash-rebase --worktree {{worktree}} --base-branch {{base_branch}}
```

This command:
- Fetches the latest target branch
- Squashes all commits into one (if multiple)
- Rebases onto the target branch

If the command returns exit code 0, skip to step 5 (Force Push).

If the command returns exit code 1, conflicts need resolution.

### 4. Resolve Conflicts with Agent

When conflicts occur during rebase:

1. Get the list of conflicted files:
   ```bash
   cd {{worktree}} && git status --porcelain | grep "^UU" | cut -c4-
   ```

2. Get the source commit SHA (the squashed commit being rebased):
   ```bash
   cd {{worktree}} && git rev-parse HEAD
   ```
   Store as `source_commit`.

3. For EACH conflicted file, invoke the conflict-resolver agent with context:

   ```
   Task(subagent_type="conflict-resolver", model="opus", prompt=<JSON>)
   ```

   Where JSON contains:
   ```json
   {
     "file_path": "<relative path to conflicted file>",
     "worktree": "{{worktree}}",
     "base_commit": "{{base_commit}}",
     "target_branch": "origin/{{base_branch}}",
     "target_commits": ["<sha1>", "<sha2>", ...],
     "source_commit": "{{source_commit}}"
   }
   ```

4. After all files are resolved, continue the rebase:
   ```bash
   cd {{worktree}} && git rebase --continue
   ```

5. If more conflicts appear, repeat step 4.

### 5. Force Push

After successful rebase:

```bash
cd {{worktree}} && git push --force-with-lease
```

### 6. Complete Merge Workflow

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

- Always force push with `--force-with-lease` (safer than `--force`)
- The conflict-resolver agent analyzes BOTH sides' intent and stitches changes together
- Never just pick one side of a conflict - always analyze and merge properly
- The PR merge auto-deletes the remote branch - do not delete it manually
- If stash pop has conflicts after sync, resolve them manually
