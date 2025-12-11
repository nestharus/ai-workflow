# Rebase PR Command

---

description: Rebase a PR branch onto target using persistent sandbox server
allowed-tools: Task, Read, Glob, Bash

---

Rebase PR: $ARGUMENTS

## Arguments

* If `$ARGUMENTS` is empty: Use current branch (must be on PR branch)
* If `$ARGUMENTS` is a PR ID (e.g., `17` or `#17`): Get branch from GitHub PR
* If `$ARGUMENTS` is a ticket ID (e.g., `NES-87`): Look up branch from Linear
* If `$ARGUMENTS` is a branch name: Use branch directly

## Prerequisites

The sandbox server starts automatically via `uv run dev.ensure-env` (triggered by
SessionStart hook). If not running, start manually:

```bash
docker compose -p ai-workflow-devtools -f docker-compose.dev.yml up -d
```

## Workflow

### 1. Get PR Information

```bash
uv run pr get-pr $ARGUMENTS
```

This returns JSON with:

* `branch_name`: Git branch name
* `worktree_path`: Path to the worktree (or `null` if on branch)
* `working_directory`: Where to run commands
* `is_worktree`: Boolean
* `pr_number`: PR number
* `pr_url`: PR URL
* `base_branch`: Target branch the PR will merge into

### 2. Execute Sandbox Rebase

Run the sandbox-rebase command:

```bash
uv run pr sandbox-rebase --branch {{branch_name}} --target {{base_branch}} -v
```

This command:

* Connects to the sandbox server via Unix domain socket
* Fetches the latest branches in the sandbox
* Performs the rebase operation in the isolated `.git/sandbox/` checkout
* Pushes the rebased branch with `--force-with-lease`

**Exit codes:**

* `0`: Success, rebase completed and pushed
* `2`: Conflicts detected - proceed to step 3
* `1`: Error - check logs and abort

### 3. Resolve Conflicts (if needed)

When conflicts occur (exit code 2), the CLI outputs the list of conflicted files.
Use the conflict-resolver agent for each conflicted file:

```python
Task(subagent_type="conflict-resolver", model="opus", prompt=<JSON>)
```

Where JSON contains:

```json
{
  "file_path": "<relative path to conflicted file>",
  "sandbox_path": ".git/sandbox",
  "source_path": "{{working_directory}}",
  "base_commit": "<merge-base SHA>",
  "target_branch": "origin/{{base_branch}}",
  "target_commits": ["<sha1>", "<sha2>", ...],
  "source_commit": "<squashed commit SHA>"
}
```

To obtain the required SHA values, run git commands via docker exec (the sandbox runs inside a container):

```bash
# Get merge-base SHA (base_commit)
docker exec ai-workflow-sandbox-server-dev bash -c 'cd /repo/.git/sandbox && git merge-base HEAD origin/{{base_branch}}'

# Get current HEAD SHA (source_commit)
docker exec ai-workflow-sandbox-server-dev bash -c 'cd /repo/.git/sandbox && git rev-parse HEAD'

# Get target commits since merge-base (for conflict-resolver)
docker exec ai-workflow-sandbox-server-dev bash -c 'cd /repo/.git/sandbox && git rev-list $(git merge-base HEAD origin/{{base_branch}})..origin/{{base_branch}}'
```

**Note**: The agent uses `.git/sandbox` for conflict editing and `source_path`
for researching clean code context.

After all files are resolved, continue the rebase via docker exec:

```bash
docker exec ai-workflow-sandbox-server-dev bash -c 'cd /repo/.git/sandbox && git add -A && GIT_EDITOR=true git rebase --continue'
```

**Note**: `GIT_EDITOR=true` prevents the "Terminal is dumb, but EDITOR unset" error.

If more conflicts appear, repeat step 3.

### 4. Push After Manual Conflict Resolution

After resolving all conflicts manually, push from the sandbox via docker exec:

```bash
docker exec ai-workflow-sandbox-server-dev bash -c 'cd /repo/.git/sandbox && git push --force-with-lease origin {{branch_name}}'
```

## Architecture

The rebase operation runs entirely in the `.git/sandbox/` checkout, managed by
the sandbox server. This isolates git operations from your main checkout and
worktrees.

For detailed architecture information, see `docs/development/sandbox-architecture.md`.

## Important Rules

* The sandbox server must be running before executing rebase
* Always use `--force-with-lease` (handled automatically by the server)
* The conflict-resolver agent analyzes BOTH sides' intent and stitches changes
  together
* Never just pick one side of a conflict - always analyze and merge properly
* The source_path remains clean for code research during conflict resolution
