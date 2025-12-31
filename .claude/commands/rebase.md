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

**CRITICAL: All paths returned are relative to the main repository root. Store the absolute path:**

```bash
MAIN_REPO=$(git rev-parse --show-toplevel)
WORKTREE_PATH="$MAIN_REPO/{{working_directory}}"
```

## 2. Preflight Checks

**CRITICAL: All git commands MUST use absolute paths to ensure correct directory context.**

```bash
git -C "$WORKTREE_PATH" fetch origin {{base_branch}}
git -C "$WORKTREE_PATH" status --porcelain
git -C "$WORKTREE_PATH" ls-files -u
```

- Fetch must succeed (network/auth check)
- Status must be empty (no uncommitted changes)
- No unresolved merge conflicts

### 2a. Verify Branch

**CRITICAL: Verify we're operating on the correct branch before any destructive operations.**

```bash
git -C "$WORKTREE_PATH" rev-parse --abbrev-ref HEAD
```

Output MUST match `{{branch_name}}`. If not, **ABORT** - wrong branch checked out.

### 2b. Sync Local with Remote

Ensure local branch matches remote before proceeding:

```bash
git -C "$WORKTREE_PATH" fetch origin {{branch_name}}
LOCAL_SHA=$(git -C "$WORKTREE_PATH" rev-parse HEAD)
REMOTE_SHA=$(git -C "$WORKTREE_PATH" rev-parse origin/{{branch_name}} 2>/dev/null || echo "none")
```

If `$REMOTE_SHA` is "none", remote doesn't exist yet (new branch).
If `$LOCAL_SHA != $REMOTE_SHA`, reset local to match remote:

```bash
git -C "$WORKTREE_PATH" reset --hard origin/{{branch_name}}
```

### 2c. Check for Commits to Rebase

```bash
git -C "$WORKTREE_PATH" log --oneline origin/{{base_branch}}..HEAD
```

If empty, branch is up-to-date with base - nothing to rebase.

## 3. Capture Original State

Before rebasing, capture state needed for verification and the two-commit structure.

### 3a. Get Old Base (Merge Base Before Rebase)

This is the common ancestor - the point where our branch diverged from the base:

```bash
OLD_BASE=$(git -C "$WORKTREE_PATH" merge-base HEAD origin/{{base_branch}})
```

### 3b. Get Squash Commit Message

Get the oldest ticket-prefixed commit message (this will be the squash message):

```bash
git -C "$WORKTREE_PATH" log --oneline origin/{{base_branch}}..HEAD | cut -d' ' -f2- | grep -E '^[A-Z]+-[0-9]+( |:|$)' | tail -1
```

Fallback to oldest commit if no ticket prefix found:

```bash
git -C "$WORKTREE_PATH" log --oneline origin/{{base_branch}}..HEAD | tail -1 | cut -d' ' -f2-
```

Store as `ORIGINAL_MSG`.

### 3c. Capture Original Tree

The tree representing all our commits combined (final state before rebase):

```bash
ORIGINAL_TREE=$(git -C "$WORKTREE_PATH" rev-parse HEAD^{tree})
```

### 3d. Capture Target Tree

The tree of the branch we're rebasing onto:

```bash
TARGET=$(git -C "$WORKTREE_PATH" rev-parse origin/{{base_branch}})
TARGET_TREE=$(git -C "$WORKTREE_PATH" rev-parse origin/{{base_branch}}^{tree})
```

## 4. Initialize Conflict Cache

```bash
rm -rf "$MAIN_REPO/.git/sandbox/.tmp/conflict-answers"
mkdir -p "$MAIN_REPO/.git/sandbox/.tmp/conflict-answers"
```

## 5. Execute Sandbox Rebase

Fetch the branch to sandbox and run rebase:

```bash
git -C "$MAIN_REPO/.git/sandbox" fetch origin {{branch_name}}
uv run pr sandbox-rebase --branch {{branch_name}} --target {{base_branch}} -v
```

Exit codes: `0` = success, `2` = conflicts, `1` = error

## 6. Resolve Conflicts (if exit code 2)

### 6a. Commit-Level Analysis

First, analyze the current commit:

```python
Task(subagent_type="commit-conflict-resolver", model="opus", prompt=<JSON>)
```

```json
{
  "sandbox_path": "$MAIN_REPO/.git/sandbox",
  "source_path": "$WORKTREE_PATH",
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
| `PROCEED` | Continue to file-level resolution (6b) |

### 6b. File-Level Resolution

For each conflicted file from PROCEED output:

```python
Task(subagent_type="file-conflict-resolver", model="opus", prompt=<JSON>)
```

```json
{
  "file_path": "<conflicted file>",
  "sandbox_path": "$MAIN_REPO/.git/sandbox",
  "source_path": "$WORKTREE_PATH",
  "base_commit": "<git -C $MAIN_REPO/.git/sandbox merge-base REBASE_HEAD origin/{{base_branch}}>",
  "target_branch": "origin/{{base_branch}}",
  "target_commits": ["<sha1>", ...],
  "source_commit": "<git -C $MAIN_REPO/.git/sandbox rev-parse REBASE_HEAD>",
  "branch_name": "{{branch_name}}",
  "pr_number": "{{pr_number}}"
}
```

**Handle file-conflict-resolver output:**

| Output | Action |
|--------|--------|
| `RESOLVED` | Continue to next file |
| `FAIL` | Abort rebase, report failure |

### 6c. Continue Rebase

After all files resolved:

```bash
git -C "$MAIN_REPO/.git/sandbox" add -A && GIT_EDITOR=true git -C "$MAIN_REPO/.git/sandbox" rebase --continue
```

If more conflicts appear, loop back to 6a.

## 7. Run Test Debugger (if conflicts)

**Skip if no conflicts (step 5 exit code 0).**

```python
Task(subagent_type="test-debugger", prompt="worktree: $MAIN_REPO/.git/sandbox")
```

## 8. Run Lint Fixer (if conflicts)

**Skip if no conflicts (step 5 exit code 0).**

```python
Task(subagent_type="lint-fixer", prompt="--worktree $MAIN_REPO/.git/sandbox --changed-only")
```

Only lints modified files (faster, appropriate for rebased branches).

## 9. Verify Rebase Integrity

**This step ensures our PR still "does the same thing" after rebase.**

### 9a. Capture Final State

Stage any uncommitted changes and capture the final tree:

```bash
git -C "$MAIN_REPO/.git/sandbox" add -A
FINAL_TREE=$(git -C "$MAIN_REPO/.git/sandbox" write-tree)
```

### 9b. Compare PR Diffs (Before vs After)

The core verification: our PR should produce the same changes regardless of base.

```bash
# What our PR changed BEFORE rebase (relative to old base)
BEFORE_DIFF=$(git -C "$MAIN_REPO/.git/sandbox" diff $OLD_BASE $ORIGINAL_TREE)

# What our PR changes AFTER rebase (relative to new target)
AFTER_DIFF=$(git -C "$MAIN_REPO/.git/sandbox" diff $TARGET $FINAL_TREE)
```

Compare the diffs:

```bash
# Get diff stats for comparison
BEFORE_STATS=$(git -C "$MAIN_REPO/.git/sandbox" diff --stat $OLD_BASE $ORIGINAL_TREE)
AFTER_STATS=$(git -C "$MAIN_REPO/.git/sandbox" diff --stat $TARGET $FINAL_TREE)

echo "=== PR Diff BEFORE rebase (vs OLD_BASE) ==="
echo "$BEFORE_STATS"

echo "=== PR Diff AFTER rebase (vs TARGET) ==="
echo "$AFTER_STATS"
```

**What to look for:**
- Same files should appear in both diffs (with possible additions for new target files we now touch)
- Line counts should be similar (insertions/deletions)
- If AFTER_DIFF has significantly fewer insertions, our code may have been dropped
- If AFTER_DIFF has significantly more deletions, we may be reverting target changes

**Generate a diff-of-diffs for detailed review:**

```bash
# Save diffs to temp files for comparison
git -C "$MAIN_REPO/.git/sandbox" diff $OLD_BASE $ORIGINAL_TREE > /tmp/before_rebase.diff
git -C "$MAIN_REPO/.git/sandbox" diff $TARGET $FINAL_TREE > /tmp/after_rebase.diff

# Compare the diffs (shows what changed about our PR)
diff /tmp/before_rebase.diff /tmp/after_rebase.diff > /tmp/diff_of_diffs.txt || true

# Show summary
echo "=== Changes to our PR diff ==="
head -100 /tmp/diff_of_diffs.txt
```

**If diffs diverge significantly:** Investigate which changes were lost or altered. Common causes:
- Conflict resolver dropped our changes
- Target deleted files we modified (our changes correctly disappear)
- Target modified same lines (merge should combine both)

### 9c. Detailed File Analysis

The following provides granular verification if the diff comparison reveals issues.

#### Identify Changed Files

Get files changed by each side relative to OLD_BASE:

```bash
# Files our branch changed
OUR_FILES=$(git -C "$MAIN_REPO/.git/sandbox" diff-tree --no-commit-id --name-only -r $OLD_BASE $ORIGINAL_TREE | sort)

# Files target branch changed
TARGET_FILES=$(git -C "$MAIN_REPO/.git/sandbox" diff-tree --no-commit-id --name-only -r $OLD_BASE $TARGET_TREE | sort)

# Files only we changed (no conflict expected)
OUR_ONLY=$(comm -23 <(echo "$OUR_FILES") <(echo "$TARGET_FILES"))

# Files only target changed (no conflict expected)
TARGET_ONLY=$(comm -13 <(echo "$OUR_FILES") <(echo "$TARGET_FILES"))

# Files both changed (potential conflicts)
BOTH_CHANGED=$(comm -12 <(echo "$OUR_FILES") <(echo "$TARGET_FILES"))
```

#### Verify Our-Only Changes

For files only we modified, our changes should be preserved exactly:

```bash
for file in $OUR_ONLY; do
  # Get our version (from ORIGINAL_TREE)
  OUR_BLOB=$(git -C "$MAIN_REPO/.git/sandbox" ls-tree $ORIGINAL_TREE -- "$file" | awk '{print $3}')
  # Get final version
  FINAL_BLOB=$(git -C "$MAIN_REPO/.git/sandbox" ls-tree $FINAL_TREE -- "$file" | awk '{print $3}')

  if [ "$OUR_BLOB" != "$FINAL_BLOB" ]; then
    echo "WARNING: Our change to $file was modified during rebase"
    git -C "$MAIN_REPO/.git/sandbox" diff $OUR_BLOB $FINAL_BLOB
  fi
done
```

**If any our-only files differ:** Review the diff. This could indicate:
- Test/lint fixes modified the file (acceptable)
- Conflict resolver incorrectly altered the file (needs investigation)

#### Verify Target-Only Changes

For files only target modified, target's changes should be preserved exactly:

```bash
for file in $TARGET_ONLY; do
  # Get target version
  TARGET_BLOB=$(git -C "$MAIN_REPO/.git/sandbox" ls-tree $TARGET_TREE -- "$file" | awk '{print $3}')
  # Get final version
  FINAL_BLOB=$(git -C "$MAIN_REPO/.git/sandbox" ls-tree $FINAL_TREE -- "$file" | awk '{print $3}')

  if [ "$TARGET_BLOB" != "$FINAL_BLOB" ]; then
    echo "ERROR: Target's change to $file was lost or modified"
    git -C "$MAIN_REPO/.git/sandbox" diff $TARGET_BLOB $FINAL_BLOB
  fi
done
```

**If any target-only files differ:** This is an error - target changes should never be modified. Investigate and fix.

#### Review Both-Changed Files (Conflicts)

For files both sides modified, verify the merge includes changes from both:

```bash
for file in $BOTH_CHANGED; do
  echo "=== Reviewing merged file: $file ==="

  # Show what we changed
  echo "Our changes (OLD_BASE → ORIGINAL):"
  git -C "$MAIN_REPO/.git/sandbox" diff $OLD_BASE:$file $ORIGINAL_TREE:$file 2>/dev/null || echo "(file added/deleted)"

  # Show what target changed
  echo "Target changes (OLD_BASE → TARGET):"
  git -C "$MAIN_REPO/.git/sandbox" diff $OLD_BASE:$file $TARGET_TREE:$file 2>/dev/null || echo "(file added/deleted)"

  # Show final result
  echo "Final result (TARGET → FINAL):"
  git -C "$MAIN_REPO/.git/sandbox" diff $TARGET_TREE:$file $FINAL_TREE:$file 2>/dev/null || echo "(no additional changes)"
done
```

**Review each merged file to ensure:**
- Our additions/modifications are present
- Target's additions/modifications are present
- No unintended deletions occurred

### 9d. Abort on Integrity Failure

If verification reveals lost changes that cannot be explained by legitimate test/lint fixes:

```bash
git -C "$MAIN_REPO/.git/sandbox" rebase --abort
```

Report the integrity failure and do not proceed with push.

## 10. Create Two-Commit Structure

This step creates a clean two-commit history that isolates rebase changes.

### 10a. Create Commit 1 (Original Squashed Work)

This commit represents all original work squashed onto the target base.
The tree is what we *intended* before any conflict resolution:

```bash
COMMIT1=$(git -C "$MAIN_REPO/.git/sandbox" commit-tree $ORIGINAL_TREE -p $TARGET -m "$ORIGINAL_MSG")
```

### 10b. Create Commit 2 (Rebase Resolution Delta)

This commit shows ONLY what changed during conflict resolution + test/lint fixes:

```bash
COMMIT2=$(git -C "$MAIN_REPO/.git/sandbox" commit-tree $FINAL_TREE -p $COMMIT1 -m "rebase: resolve conflicts and apply fixes")
```

### 10c. Update Branch

```bash
git -C "$MAIN_REPO/.git/sandbox" reset --hard $COMMIT2
```

**Result:** Exactly 2 commits:
- **Commit 1**: Original squashed work (our intended changes, new parent)
- **Commit 2**: Delta showing what rebase + conflict resolution changed

If no conflicts occurred (step 5 exit code 0), `$ORIGINAL_TREE == $FINAL_TREE`, so Commit 2 will be empty.
In this case, just create a single squashed commit:

```bash
git -C "$MAIN_REPO/.git/sandbox" reset --hard $COMMIT1
```

## 11. Push

```bash
git -C "$MAIN_REPO/.git/sandbox" push origin {{branch_name}} --force-with-lease
```

## 12. Sync Worktree to Origin

**Skip if `worktree_path` is null (no worktree exists).**

After push, sync the worktree to match origin:

```bash
git -C "$WORKTREE_PATH" fetch origin {{branch_name}}
git -C "$WORKTREE_PATH" reset --hard origin/{{branch_name}}
```

## 13. Abort (on failure)

```bash
git -C "$MAIN_REPO/.git/sandbox" rebase --abort
```

The server automatically unblocks the queue when the sandbox is clean.
