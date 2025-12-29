# Rebase PR Command

---

description: Rebase a PR branch onto target using persistent sandbox server
allowed-tools: Task, Read, Glob, Bash

---

Rebase PR: $ARGUMENTS

## 1. Get PR Information

```bash
uv run pr get-pr $ARGUMENTS
```

Returns `branch_name`, `base_branch`, `working_directory`, `pr_number`, etc.

## 2. Squash Commits (Pre-Rebase)

Squash all commits before rebasing so the rebase operation is visible as a distinct change.
This makes it easier to identify if something went wrong during the rebase.

### 2a. Preflight Checks

```bash
cd {{working_directory}} && git fetch origin {{base_branch}}
cd {{working_directory}} && git status --porcelain
cd {{working_directory}} && git ls-files -u
```

- Fetch must succeed (network/auth check)
- Status must be empty (no uncommitted changes)
- No unresolved merge conflicts

### 2b. Check for Commits to Squash

```bash
cd {{working_directory}} && git log --oneline origin/{{base_branch}}..HEAD
```

If empty, skip squash (branch is up-to-date with base).

### 2c. Get Commit Message

Get the oldest ticket-prefixed commit message:

```bash
cd {{working_directory}} && git log --oneline origin/{{base_branch}}..HEAD | cut -d' ' -f2- | grep -E '^[A-Z]+-[0-9]+( |:|$)' | tail -1
```

Fallback to oldest commit if no ticket prefix found:

```bash
cd {{working_directory}} && git log --oneline origin/{{base_branch}}..HEAD | tail -1 | cut -d' ' -f2-
```

### 2d. Squash and Push

```bash
cd {{working_directory}} && git fetch origin {{branch_name}}
```

Verify local HEAD matches remote (abort if diverged to prevent data loss):

```bash
cd {{working_directory}} && git rev-parse HEAD
cd {{working_directory}} && git rev-parse origin/{{branch_name}}
```

If SHAs match (or remote doesn't exist), proceed with squash:

```bash
cd {{working_directory}} && git reset --soft origin/{{base_branch}} && git commit -m "<commit_message>" && git push --force-with-lease
```

## 3. Initialize Conflict Cache

```bash
rm -rf .git/sandbox/.tmp/conflict-answers
mkdir -p .git/sandbox/.tmp/conflict-answers
```

## 4. Execute Sandbox Rebase

First, capture the original tree and message before rebasing:

```bash
git -C .git/sandbox fetch origin {{branch_name}}
ORIGINAL_TREE=$(git -C .git/sandbox rev-parse origin/{{branch_name}}^{tree})
ORIGINAL_MSG=$(git -C .git/sandbox log -1 --format=%B origin/{{branch_name}})
```

Then run the rebase:

```bash
uv run pr sandbox-rebase --branch {{branch_name}} --target {{base_branch}} -v
```

Exit codes: `0` = success, `2` = conflicts, `1` = error

## 5. Resolve Conflicts (if exit code 2)

### 5a. Commit-Level Analysis

First, analyze the current commit:

```python
Task(subagent_type="commit-conflict-resolver", model="opus", prompt=<JSON>)
```

```json
{
  "sandbox_path": ".git/sandbox",
  "source_path": "{{working_directory}}",
  "target_branch": "origin/{{base_branch}}",
  "branch_name": "{{branch_name}}",
  "pr_number": "{{pr_number}}"
}
```

**Handle commit-conflict-resolver output:**

| Output | Action |
|--------|--------|
| `SKIP_COMMIT` | Agent ran `rebase --skip`, loop back to check for more conflicts |
| `REBUILD_BRANCH` | Agent rebuilt via cherry-pick, skip to push |
| `PROCEED` | Continue to file-level resolution (5b) |

### 5b. File-Level Resolution

For each conflicted file from PROCEED output:

```python
Task(subagent_type="file-conflict-resolver", model="opus", prompt=<JSON>)
```

```json
{
  "file_path": "<conflicted file>",
  "sandbox_path": ".git/sandbox",
  "source_path": "{{working_directory}}",
  "base_commit": "<git -C .git/sandbox merge-base REBASE_HEAD origin/{{base_branch}}>",
  "target_branch": "origin/{{base_branch}}",
  "target_commits": ["<sha1>", ...],
  "source_commit": "<git -C .git/sandbox rev-parse REBASE_HEAD>",
  "branch_name": "{{branch_name}}",
  "pr_number": "{{pr_number}}"
}
```

**Handle file-conflict-resolver output:**

| Output | Action |
|--------|--------|
| `RESOLVED` | Continue to next file |
| `FAIL` | Abort rebase, report failure |

### 5c. Continue Rebase

After all files resolved:

```bash
git -C .git/sandbox add -A && GIT_EDITOR=true git -C .git/sandbox rebase --continue
```

If more conflicts appear, loop back to 5a.

## 6. Run Test Debugger (if conflicts)

**Skip if no conflicts (step 4 exit code 0).**

```python
Task(subagent_type="test-debugger", prompt="worktree: .git/sandbox")
```

## 7. Run Lint Fixer (if conflicts)

**Skip if no conflicts (step 4 exit code 0).**

```python
Task(subagent_type="lint-fixer", prompt="--worktree .git/sandbox --changed-only")
```

Only lints modified files (faster, appropriate for rebased branches).

## 8. Create Two-Commit Structure

Stage any uncommitted changes from test/lint fixes:

```bash
git -C .git/sandbox add -A
```

Capture the final tree (after rebase + all fixes):

```bash
FINAL_TREE=$(git -C .git/sandbox write-tree)
```

Get the target commit:

```bash
TARGET=$(git -C .git/sandbox rev-parse origin/{{base_branch}})
```

Create commit 1 (original squashed work, rebased onto target):

```bash
COMMIT1=$(git -C .git/sandbox commit-tree $ORIGINAL_TREE -p $TARGET -m "$ORIGINAL_MSG")
```

Create commit 2 (rebase changes + test/lint fixes):

```bash
COMMIT2=$(git -C .git/sandbox commit-tree $FINAL_TREE -p $COMMIT1 -m "rebase: apply rebase and fixes")
```

Update branch to point to the new structure:

```bash
git -C .git/sandbox reset --hard $COMMIT2
```

This produces exactly 2 commits:
- **Commit 1**: Original squashed work (unchanged content, new parent)
- **Commit 2**: Delta showing what rebase + fixes changed

## 9. Push

```bash
git -C .git/sandbox push origin {{branch_name}} --force-with-lease
```

## 10. Sync Worktree to Origin

**Skip if `worktree_path` is null (no worktree exists).**

After push, sync the worktree to match origin:

```bash
git -C {{worktree_path}} fetch origin {{branch_name}}
git -C {{worktree_path}} reset --hard origin/{{branch_name}}
```

## 11. Abort (on failure)

```bash
git -C .git/sandbox rebase --abort
```

The server automatically unblocks the queue when the sandbox is clean.
