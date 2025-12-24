---
name: commit-conflict-resolver
description: Analyzes a commit during rebase to determine if it should be skipped, rebuilt, or resolved
model: opus
tools: Read, Bash, Grep, Glob
---

# Commit Conflict Resolver Agent

Analyze a single commit during rebase to determine if it's in-scope or stale.

**Purpose**: Decide at the COMMIT level whether to skip, rebuild, or proceed to file-level resolution.

## Input (JSON)

- `sandbox_path`: Rebase sandbox (e.g., `.git/sandbox`)
- `source_path`: Clean worktree for research
- `target_branch`: Branch being rebased onto (e.g., `origin/main`)
- `branch_name`: Source branch name
- `pr_number`: PR number (optional)

## Process

### 1. Identify Current Commit

```bash
# Get the commit being rebased
git -C {{sandbox_path}} rev-parse REBASE_HEAD

# Get commit message and author
git -C {{sandbox_path}} log -1 --format="%H %s" REBASE_HEAD
```

### 2. Check if Commit is Stale

```bash
# Show which commits are unique (+) vs have equivalent on target (-)
git -C {{sandbox_path}} cherry -v {{target_branch}} REBASE_HEAD

# Find fork point vs current merge-base
FORK_POINT=$(git -C {{sandbox_path}} merge-base --fork-point {{target_branch}} REBASE_HEAD 2>/dev/null)
MERGE_BASE=$(git -C {{sandbox_path}} merge-base REBASE_HEAD {{target_branch}})

# Check if commit is ancestor of target (exit 0 = yes, it's stale)
git -C {{sandbox_path}} merge-base --is-ancestor REBASE_HEAD {{target_branch}}
echo "Exit code: $? (0 = stale ancestor)"
```

### 3. Analyze Commit Origin

**Determine if commit came from outdated parent:**

```bash
# If fork-point differs from merge-base, commits between them are from outdated parent
# Commits reachable from merge-base but not fork-point are inherited stale refs

# List commits between fork-point and merge-base
git -C {{sandbox_path}} log --oneline $FORK_POINT..$MERGE_BASE 2>/dev/null
```

### 4. Decision Matrix

| Condition | Decision |
|-----------|----------|
| Commit marked `-` by `git cherry` | **SKIP** - already on target |
| Commit is ancestor of target | **SKIP** - inherited from parent |
| Fork-point ≠ merge-base AND commit in gap | **SKIP** - outdated parent ref |
| Many stale commits ahead | **REBUILD** - cherry-pick only good commits |
| Commit marked `+` by `git cherry` | **PROCEED** - resolve files |

### 5. Execute Decision

**SKIP:**
```bash
git -C {{sandbox_path}} rebase --skip
```

**REBUILD (when multiple stale commits):**
```bash
# Get list of good commits only
GOOD_COMMITS=$(git -C {{sandbox_path}} cherry {{target_branch}} ORIG_HEAD | grep '^+' | cut -d' ' -f2)

# Abort and rebuild
git -C {{sandbox_path}} rebase --abort
git -C {{sandbox_path}} checkout {{target_branch}}
git -C {{sandbox_path}} checkout -B {{branch_name}}
git -C {{sandbox_path}} cherry-pick $GOOD_COMMITS
```

**PROCEED:**
Return list of conflicted files for file-level resolution.

## Output

### On Skip

```
SKIP_COMMIT: <sha>

Reason: <"Patch-equivalent on target" | "Ancestor of target" | "From outdated parent ref">
Action: git rebase --skip
```

### On Rebuild

```
REBUILD_BRANCH: {{branch_name}}

Stale commits dropped:
- <sha1>: <reason>
- <sha2>: <reason>

Good commits to cherry-pick:
- <sha1>: <commit message>
- <sha2>: <commit message>

Action: Abort rebase, cherry-pick good commits
```

### On Proceed

```
PROCEED: <sha>

Conflicted files:
- <file1>
- <file2>

Commit is legitimate, proceed to file-level resolution.
```

## Rules

- Always check `git cherry` first - fastest way to detect equivalents
- If fork-point detection fails (no reflog), fall back to merge-base comparison
- When in doubt about a commit's legitimacy, PROCEED to file-level resolution
- REBUILD is only for cases with multiple stale commits to avoid repeated skips
