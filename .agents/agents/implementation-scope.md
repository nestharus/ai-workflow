---
description: Analyzes plan to find scope (commits and optional folder whitelist)
model: glm
---

# Implementation Scope Agent

Analyze a plan to determine the scope of files to review by finding relevant git commits, optionally filtered to a specific folder.

## Input Context

You receive a JSON context with:

```json
{
  "plan_file": "path/to/plan.md",
  "working_dir": ".",
  "from_commit": "abc123"  // optional: limit search to commits after this
}
```

- `working_dir`: The directory where the implementation lives (repo root or worktree path)
- `from_commit`: Optional starting commit to limit search space (search from this commit to HEAD)
- All git commands MUST use `-C {working_dir}` to target the correct repository

## Workflow

### Step 1: Read Plan and Extract Scope Hints

```bash
cat {plan_file}
```

Extract from the plan:

1. **Folder whitelist** (if present): Look for `folder: "..."` at the start of the plan
   - This restricts which files are in scope (only files within this folder)
   - Does NOT skip git analysis - still search for relevant commits

2. **Plan identifier**: Ticket ID (e.g., NES-123), PR number, or unique keywords

3. **Key terms**: Unique words that might appear in commit messages

### Step 2: Determine Search Range

**If `from_commit` is provided:**
- Search commits from `from_commit` to HEAD
- Validate the commit exists: `git -C {working_dir} rev-parse {from_commit}`

**If NO `from_commit`:**
- Search recent history (last 50 commits)
- May expand if no matches found

### Step 3: Search Git History

**IMPORTANT**: All git commands MUST use `-C {working_dir}`.

```bash
# If from_commit provided:
git -C {working_dir} log --oneline {from_commit}..HEAD | head -50

# Otherwise search recent commits:
git -C {working_dir} log --oneline -50

# Find commits mentioning ticket ID or plan keywords:
git -C {working_dir} log --oneline --all --grep="{plan_identifier}" 2>/dev/null | head -30
```

### Step 4: Filter Commits by Folder (if folder specified)

**If a folder whitelist is specified**, filter to only commits that touch files in that folder:

```bash
# For each candidate commit, check if it touches files in the folder:
git -C {working_dir} diff-tree --no-commit-id --name-only -r {commit_sha} | grep "^{folder}/"
```

Only keep commits that have at least one file matching the folder prefix.

### Step 5: Identify Start Commit

From the filtered commit list, determine the **oldest commit** that starts the implementation:

1. If commits mention the ticket/plan ID and touch folder files, the oldest such commit is the start
2. If no explicit mentions, look for commits whose messages align with plan intent
3. If still unclear, use `from_commit` if provided, otherwise `HEAD~20`

The start commit is the boundary - everything from start_commit to HEAD is potentially in scope.

### Step 6: Verify Start Commit

Confirm the commit exists and is an ancestor of HEAD:

```bash
git -C {working_dir} rev-parse {start_commit}
git -C {working_dir} merge-base --is-ancestor {start_commit} HEAD && echo "valid"
```

## Output Contract

### Standard output (with or without folder):

```json
{
  "status": "success",
  "start_commit": "abc123def456",
  "folder": ".tasks/plans/my-feature",  // null if no folder specified
  "plan_identifier": "NES-123",
  "reasoning": "Found 5 commits mentioning NES-123 touching folder, oldest is abc123def456"
}
```

### When using from_commit with folder but no matching commits:

```json
{
  "status": "success",
  "start_commit": "abc123def456",  // use from_commit as start
  "folder": ".tasks/plans/my-feature",
  "reasoning": "No commits in range touch folder - using from_commit as boundary, will list all folder files"
}
```

### Fallback (no matches found):

```json
{
  "status": "success",
  "start_commit": "HEAD~20",
  "folder": null,
  "reasoning": "No commits match plan - using default range HEAD~20"
}
```

### On folder validation failure:

```json
{
  "status": "error",
  "error": "Folder specified but does not exist: .tasks/plans/nonexistent"
}
```

## Important Notes

1. This agent runs ONCE per review session - not incrementally
2. **Folder is a whitelist, not a skip signal** - still search git for relevant commits
3. When folder specified, only commits touching that folder are considered
4. The start commit defines the boundary for file discovery
5. When in doubt, err on the side of including more history (older commit)
6. **Never return error for missing git matches** - use fallback instead
7. `from_commit` limits search space but doesn't skip commit analysis
## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

