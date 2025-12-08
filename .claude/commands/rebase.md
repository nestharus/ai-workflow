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

### 1. Create Rebase Sandbox

Create an isolated sandbox for the rebase operation:

```bash
uv run pr promote-worktree $ARGUMENTS
```

This returns JSON with:

* `sandbox_path`: Path to the shared clone (where rebase happens)
* `source_path`: Path to the original worktree (for reading clean code)
* `branch_name`: Git branch name
* `base_branch`: Target branch the PR will merge into (e.g., `main`, `develop`)
* `pr_number`: PR number

Store these values for use throughout the workflow.

### 2. Gather Merge Context (Before Squash)

Before squashing, gather context needed for conflict resolution:

```bash
cd {{sandbox_path}} && git fetch origin {{base_branch}}
```

Find the merge-base (original base commit before branches diverged):

```bash
cd {{sandbox_path}} && git merge-base origin/{{base_branch}} HEAD
```

Store this as `base_commit`.

Find commits added to target branch since the base:

```bash
cd {{sandbox_path}} && git log --oneline {{base_commit}}..origin/{{base_branch}}
```

Store these commit SHAs as `target_commits` (list from oldest to newest).

### 3. Squash and Rebase

Squash all commits and rebase onto the target branch:

```bash
uv run pr squash-rebase --worktree {{sandbox_path}} --base-branch {{base_branch}}
```

This command:

* Fetches the latest target branch
* Squashes all commits into one (if multiple)
* Rebases onto the target branch

If the command returns exit code 0, skip to step 5 (Force Push).

If the command returns exit code 1, conflicts need resolution.

### 4. Resolve Conflicts with Agent

When conflicts occur during rebase:

1. Get the list of conflicted files:

   ```bash
   cd {{sandbox_path}} && git status --porcelain | grep "^UU" | cut -c4-
   ```

2. Get the source commit SHA (the squashed commit being rebased):

   ```bash
   cd {{sandbox_path}} && git rev-parse HEAD
   ```

   Store as `source_commit`.

3. For EACH conflicted file, invoke the conflict-resolver agent with context:

   ```python
   Task(subagent_type="conflict-resolver", model="opus", prompt=<JSON>)
   ```

   Where JSON contains:

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

   **Note**: The agent uses `sandbox_path` for conflict editing and `source_path` for researching clean code context.

4. After all files are resolved, continue the rebase:

   ```bash
   cd {{sandbox_path}} && git rebase --continue
   ```

5. If more conflicts appear, repeat step 4.

### 5. Force Push

After successful rebase, push from the sandbox:

```bash
cd {{sandbox_path}} && git push --force-with-lease
```

### 6. Sync Source Worktree

After the force push, sync the source worktree to match the rebased branch:

```bash
cd {{source_path}} && git fetch origin && git reset --hard origin/{{branch_name}}
```

This ensures the original worktree has the rebased history and is ready for continued work.

### 7. Cleanup Sandbox

After successful sync, remove the sandbox:

```bash
uv run pr cleanup-sandbox $ARGUMENTS
```

## Important Rules

* Always force push with `--force-with-lease` (safer than `--force`)
* The conflict-resolver agent analyzes BOTH sides' intent and stitches changes
  together
* Never just pick one side of a conflict - always analyze and merge properly
* **Always use sandbox**: Whether working from repo root or a worktree, rebase
  happens in the sandbox to keep the source unblocked
* The source_path remains clean for code research during conflict resolution
