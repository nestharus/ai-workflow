# Rebase PR Command

---

description: Rebase a PR branch by squashing, rebasing onto target, resolving
  conflicts, and pushing
allowed-tools: Task, Read, Glob, Bash

---

Rebase PR: $ARGUMENTS

## Arguments

* If `$ARGUMENTS` is empty: Use current branch (must be on PR branch)
* If `$ARGUMENTS` is a PR ID (e.g., `17` or `#17`): Get branch from GitHub PR
* If `$ARGUMENTS` is a ticket ID (e.g., `NES-87`): Look up branch from Linear
* If `$ARGUMENTS` is a branch name: Use branch directly

## Workflow

### 1. Start Rebase

Run the rebase-start command (from repo root):

```bash
uv run pr rebase-start $ARGUMENTS
```

This command:

* Creates an isolated sandbox for the rebase operation
* Fetches the latest target branch
* Gathers merge context (base commit, target commits)
* Squashes all commits into one (if multiple)
* Rebases onto the target branch

**Exit codes:**

* `0`: Success, no conflicts - proceed to step 3
* `1`: Conflicts detected - proceed to step 2
* `2`: Error - abort

**JSON output includes:**

* `sandbox_path`: Path to the sandbox (where rebase happens)
* `source_path`: Path to the original worktree (for reading clean code)
* `branch_name`: Git branch name
* `base_branch`: Target branch the PR will merge into
* `pr_number`: PR number
* `base_commit`: The merge-base commit SHA
* `target_commits`: List of commit SHAs added to base branch since divergence
* `has_conflicts`: Boolean indicating if conflicts occurred
* `conflicted_files`: (only if conflicts) List of files with conflicts
* `source_commit`: (only if conflicts) SHA of the squashed commit being rebased

### 2. Resolve Conflicts (if needed)

When conflicts occur (exit code 1), use the conflict-resolver agent for each
conflicted file:

```python
Task(subagent_type="conflict-resolver", model="opus", prompt=<JSON>)
```

Where JSON contains the context from step 1:

```json
{
  "file_path": "<relative path to conflicted file>",
  "sandbox_path": "{{sandbox_path}}",
  "source_path": "{{source_path}}",
  "base_commit": "{{base_commit}}",
  "target_branch": "origin/{{base_branch}}",
  "target_commits": ["<sha1>", "<sha2>", ...],
  "source_commit": "{{source_commit}}"
}
```

**Note**: The agent uses `sandbox_path` for conflict editing and `source_path`
for researching clean code context.

After all files are resolved, continue the rebase:

```bash
cd {{sandbox_path}} && git add -A && git rebase --continue
```

If more conflicts appear, repeat step 2.

### 3. Finish Rebase

After successful rebase (or after resolving all conflicts), run:

```bash
uv run pr rebase-finish $ARGUMENTS
```

This command:

* Force pushes from the sandbox (with `--force-with-lease`)
* Syncs the source worktree to match the rebased branch
* Cleans up the sandbox

## Important Rules

* Always use `--force-with-lease` (handled automatically by rebase-finish)
* The conflict-resolver agent analyzes BOTH sides' intent and stitches changes
  together
* Never just pick one side of a conflict - always analyze and merge properly
* The source_path remains clean for code research during conflict resolution
