# Rebase PR Command

---

description: Rebase a PR branch by squashing, rebasing onto target, resolving conflicts, and pushing
allowed-tools: Task, Read, Glob, Bash

---

Rebase PR for ticket: $ARGUMENTS

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
* `base_branch`: The target branch from the PR info (NOT hardcoded to `main`)

### 2. Gather Merge Context (Before Squash)

Before squashing, gather context needed for conflict resolution:

```bash
cd {{working_dir}} && git fetch origin {{base_branch}}
```

Find the merge-base (original base commit before branches diverged):

```bash
cd {{working_dir}} && git merge-base origin/{{base_branch}} HEAD
```

Store this as `base_commit`.

Find commits added to target branch since the base:

```bash
cd {{working_dir}} && git log --oneline {{base_commit}}..origin/{{base_branch}}
```

Store these commit SHAs as `target_commits` (list from oldest to newest).

### 3. Squash and Rebase

Squash all commits and rebase onto the target branch:

```bash
uv run pr squash-rebase --worktree {{working_dir}} --base-branch {{base_branch}}
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
   cd {{working_dir}} && git status --porcelain | grep "^UU" | cut -c4-
   ```

2. Get the source commit SHA (the squashed commit being rebased):

   ```bash
   cd {{working_dir}} && git rev-parse HEAD
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
     "worktree": "{{working_dir}}",
     "base_commit": "{{base_commit}}",
     "target_branch": "origin/{{base_branch}}",
     "target_commits": ["<sha1>", "<sha2>", ...],
     "source_commit": "{{source_commit}}"
   }
   ```

4. After all files are resolved, continue the rebase:

   ```bash
   cd {{working_dir}} && git rebase --continue
   ```

5. If more conflicts appear, repeat step 4.

### 5. Force Push

After successful rebase:

```bash
cd {{working_dir}} && git push --force-with-lease
```

## Important Rules

* Always force push with `--force-with-lease` (safer than `--force`)
* The conflict-resolver agent analyzes BOTH sides' intent and stitches changes together
* Never just pick one side of a conflict - always analyze and merge properly
