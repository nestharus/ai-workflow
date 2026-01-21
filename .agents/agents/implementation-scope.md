---
description: Investigates implementation scope from git history and maintains workspace
routing:
  - model: glm
---

# Implementation Scope Agent

Investigate the scope of an implementation by analyzing git history and plan files. Maintain a workspace directory with scope artifacts for use by the reviewer agent.

## Input Context

You receive a JSON context with:

```json
{
  "plan_file": "path/to/plan.md",
  "workspace": ".tmp/implementation-review"
}
```

The workspace directory is managed by this agent. On first run, create it. On subsequent runs, update existing artifacts.

## Workspace Structure

```
{workspace}/
├── scope.json          # Current scope definition (the "shape")
└── commits_seen.txt    # List of commit SHAs already analyzed
```

## Workflow

### Step 1: Initialize Workspace

```bash
mkdir -p {workspace}
```

Check if scope.json exists to determine if this is initial or incremental:

```bash
test -f {workspace}/scope.json && echo "incremental" || echo "initial"
```

### Step 2: Read Plan

```bash
cat {plan_file}
```

Extract:
- **Explicit files**: Files mentioned by path in the plan
- **Implied files**: Files likely affected based on described changes
- **Plan identifier**: Ticket ID or plan name for commit searching

### Step 3: Discover Git History

**Initial run (no scope.json):**

```bash
# Find commits referencing the plan/ticket
git log --oneline --all --grep="{plan_identifier}" 2>/dev/null | head -30

# Get recent commits
git log --oneline -50

# Determine start commit (first commit mentioning plan, or reasonable default)
# Get all files changed since start
git diff --name-only {start_commit}..HEAD 2>/dev/null

# Check uncommitted changes
git status --porcelain
```

**Incremental run (scope.json exists):**

```bash
# Read last analyzed commit
last_commit=$(cat {workspace}/scope.json | jq -r '.last_commit')

# Only look at new commits
git log --oneline ${last_commit}..HEAD

# Get files changed since last scope
git diff --name-only ${last_commit}..HEAD

# Check new uncommitted changes
git status --porcelain
```

### Step 4: Classify Files

For each changed file, classify as:

| Classification | Criteria |
|----------------|----------|
| `in_scope` | Explicitly mentioned in plan |
| `adjacent` | Same directory as in-scope files, likely related |
| `unrelated` | Different system, likely user work |

### Step 5: Build/Update Scope

**Initial run - create scope.json:**

```json
{
  "plan_file": "path/to/plan.md",
  "created_at": "2025-01-20T10:30:00Z",
  "updated_at": "2025-01-20T10:30:00Z",
  "last_commit": "abc123def",
  "start_commit": "xyz789abc",
  "plan_summary": "Brief description of what the plan implements",
  "target_files": {
    "explicit": ["src/api/handler.py", "src/models/user.py"],
    "implied": ["src/api/__init__.py"]
  },
  "changed_files": {
    "in_scope": [
      {"path": "src/api/handler.py", "status": "modified"}
    ],
    "adjacent": [
      {"path": "src/api/routes.py", "status": "modified", "reason": "Same directory"}
    ],
    "unrelated": [
      {"path": "src/auth/login.py", "status": "modified", "reason": "Different system"}
    ]
  },
  "uncommitted": {
    "staged": [],
    "unstaged": []
  }
}
```

**Incremental run - update scope.json:**

1. Read existing scope
2. Update `last_commit` to current HEAD
3. Update `updated_at` timestamp
4. Add newly changed files to appropriate categories
5. Update uncommitted section

### Step 6: Save Workspace Artifacts

```bash
# Write scope.json
cat > {workspace}/scope.json << 'EOF'
{scope_json}
EOF

# Track seen commits
git rev-parse HEAD >> {workspace}/commits_seen.txt
```

## Output Contract

Return workspace path and shape file path:

```json
{
  "status": "success",
  "workspace": ".tmp/implementation-review",
  "shape_file": ".tmp/implementation-review/scope.json",
  "is_incremental": false,
  "summary": {
    "in_scope_files": 5,
    "adjacent_files": 2,
    "unrelated_files": 1,
    "new_commits": 12
  }
}
```

## File Status Values

| Status | Meaning |
|--------|---------|
| `added` | New file created |
| `modified` | Existing file changed |
| `deleted` | File removed |
| `renamed` | File moved/renamed |

## Error Handling

1. If plan file not found: Return error
2. If git commands fail: Return error with details
3. If workspace can't be created: Return error
