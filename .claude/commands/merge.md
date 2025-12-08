# Merge PR Command

---

description: Merge a PR and perform cleanup (worktree removal, branch sync, ticket completion)
allowed-tools: Task, Read, Glob, Bash

---

Merge PR for ticket: $ARGUMENTS

**Note**: This command assumes the branch has already been rebased and pushed. Use `/rebase` first if needed.

## Workflow

### 1. Get PR Information

```bash
uv run pr get-pr $ARGUMENTS
```

This returns JSON with:

* `branch_name`: Git branch name (may contain slashes, e.g., `mrasolomon/nes-87-...`)
* `worktree_path`: Path to the worktree (e.g., `.worktrees/mrasolomon/nes-87-...`)
* `working_directory`: Where to run commands - either `.` (repo root) or the worktree path
* `is_worktree`: Boolean - `true` if working in worktree, `false` if on current branch
* `pr_number`: PR number
* `pr_url`: PR URL
* `base_branch`: Target branch the PR will merge into (e.g., `main`, `develop`)

Set up variables:

* `ticket_id`: $ARGUMENTS
* `working_dir`: `{{working_directory}}` (from `working_directory` in JSON)
* `is_worktree`: `{{is_worktree}}` (from `is_worktree` in JSON)
* `base_branch`: The target branch from the PR info (NOT hardcoded to `main`)

### 2. Complete Merge Workflow

Execute the full merge workflow (merge PR, cleanup, sync, conditionally mark done):

```bash
uv run pr merge --ticket $ARGUMENTS --pr {{pr_number}} --working-dir {{working_dir}} --branch {{branch_name}} --base-branch {{base_branch}} {{#if is_worktree}}--is-worktree{{/if}}
```

This command performs:

1. Merge the PR (squash merge)
2. **If `--is-worktree` flag is passed**:
   * Remove git worktree
   * Delete local branch
3. Sync target branch (fetch, stash, checkout, pull, stash pop)
4. Check for remaining open PRs:
   * If **no remaining open PRs**: Mark Linear ticket as Done
   * If **remaining open PRs exist**: Report the next open PR and skip marking done

**Note**: The remote branch auto-deletes after merge (configured in GitHub). Do NOT manually delete the remote branch.

## Important Rules

* Run `/rebase` before `/merge` to ensure the branch is up-to-date with the target
* The PR merge auto-deletes the remote branch - do not delete it manually
* If stash pop has conflicts after sync, resolve them manually
