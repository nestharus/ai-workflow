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

## 2. Initialize Conflict Cache

```bash
rm -rf .git/sandbox/.tmp/conflict-answers
mkdir -p .git/sandbox/.tmp/conflict-answers
```

## 3. Execute Sandbox Rebase

```bash
uv run pr sandbox-rebase --branch {{branch_name}} --target {{base_branch}} -v
```

Exit codes: `0` = success, `2` = conflicts, `1` = error

## 4. Resolve Conflicts (if exit code 2)

### 4a. Commit-Level Analysis

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
| `PROCEED` | Continue to file-level resolution (4b) |

### 4b. File-Level Resolution

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

### 4c. Continue Rebase

After all files resolved:

```bash
git -C .git/sandbox add -A && GIT_EDITOR=true git -C .git/sandbox rebase --continue
```

If more conflicts appear, loop back to 4a.

## 5. Run Test Debugger (if conflicts)

**Skip if no conflicts (step 3 exit code 0).**

```python
Task(subagent_type="test-debugger", prompt="worktree: .git/sandbox")
```

## 6. Run Lint Fixer (if conflicts)

**Skip if no conflicts (step 3 exit code 0).**

```python
Task(subagent_type="lint-fixer", prompt="--worktree .git/sandbox --changed-only")
```

Only lints modified files (faster, appropriate for rebased branches).

## 7. Push

```bash
git -C .git/sandbox push origin {{branch_name}} --force-with-lease
```

## 8. Sync Worktree to Origin

**Skip if `worktree_path` is null (no worktree exists).**

After push, sync the worktree to match origin:

```bash
git -C {{worktree_path}} fetch origin {{branch_name}}
git -C {{worktree_path}} reset --hard origin/{{branch_name}}
```

## 9. Abort (on failure)

```bash
git -C .git/sandbox rebase --abort
```

The server automatically unblocks the queue when the sandbox is clean.
