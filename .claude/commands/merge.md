# Merge PR Command

---

description: Merge a PR via GitHub and perform cleanup (worktree removal, branch sync, ticket completion)
allowed-tools: Task, Read, Glob, Bash

---

Merge PR: $ARGUMENTS

**Note**: Use `/rebase` first if needed to ensure the branch is up-to-date.

## Arguments

* If `$ARGUMENTS` is empty: Use current branch (must be on PR branch)
* If `$ARGUMENTS` is a PR ID (e.g., `17` or `#17`): Get branch from GitHub PR
* If `$ARGUMENTS` is a ticket ID (e.g., `NES-87`): Look up branch from Linear
* If `$ARGUMENTS` is a branch name: Use branch directly

## Workflow

### 1. Get PR Information

```bash
uv run pr get-pr $ARGUMENTS
```

This returns JSON with:

* `branch_name`: Git branch name (may contain slashes, e.g., `mrasolomon/nes-87-...`)
* `worktree_path`: Path to the worktree, or `null` if on branch directly
* `working_directory`: Where to run commands - `.` or worktree path
* `is_worktree`: Boolean - `true` if using worktree, `false` if on branch directly
* `pr_number`: PR number
* `pr_url`: PR URL
* `base_branch`: Target branch the PR will merge into (e.g., `main`, `develop`)

### 2. Extract Ticket ID

```bash
uv run pr extract-ticket-id {{branch_name}}
```

This returns JSON with:

* `ticket_id`: The Linear ticket ID (e.g., `NES-87`), or `null` if not found
* `valid`: Boolean indicating if the ticket exists in Linear

### 2b. Get Repository Root

```bash
git rev-parse --show-toplevel
```

Store this as `repo_root`.

Set up variables:

* `ticket_id`: From `extract-ticket-id` output (may be `null`)
* `repo_root`: From the git command above
* `working_dir`: `{{repo_root}}/{{working_directory}}` (absolute path)
* `is_worktree`: `{{is_worktree}}` from `get-pr`
* `base_branch`: The target branch from the PR info (NOT hardcoded to `main`)

### 3. Complete Merge Workflow

Execute the full merge workflow (merge PR, cleanup, sync, conditionally mark done):

```bash
uv run pr merge --pr {{pr_number}} --working-dir {{working_dir}} --branch {{branch_name}} --base-branch {{base_branch}} {{#if ticket_id}}--ticket {{ticket_id}}{{/if}} {{#if is_worktree}}--is-worktree{{/if}}
```

This command performs:

1. Merge the PR (squash merge)
2. **If `--is-worktree` flag is passed**:
   * Remove git worktree
   * Delete local branch
3. Fetch and prune remote tracking branches
4. **If `--ticket` provided**: Check for remaining open PRs:
   * If **no remaining open PRs**: Mark Linear ticket as Done
   * If **remaining open PRs exist**: Report the next open PR and skip marking done

**Note**: The remote branch auto-deletes after merge (configured in GitHub). Do NOT manually delete the remote branch.

## Sandbox Merge (Alternative Workflow)

To merge main INTO your feature branch (instead of merging your PR into main),
use the sandbox merge operation. This is useful for incorporating upstream changes
into your branch before submitting your PR.

### Prerequisites

Ensure the sandbox server is running:

```bash
# Create the socket directory first (required for host access)
mkdir -p /tmp/sandbox-sockets && chmod 1777 /tmp/sandbox-sockets

# Start the sandbox server
docker compose -f scripts/pr/sandbox/docker-compose.yml up -d
```

### Execute Sandbox Merge

```bash
uv run pr sandbox-merge --branch {{branch_name}} --target main -v
```

This operation:

* Runs entirely in the `.git/sandbox/` checkout managed by the sandbox server
* Leaves your main checkout untouched
* Merges the target branch (e.g., `main`) INTO your feature branch
* Pushes the result automatically

**Exit codes:**

* `0`: Success, merge completed and pushed
* `2`: Conflicts detected - resolve in `.git/sandbox/` then push manually
* `1`: Error - check logs

**Socket configuration:**

* Default socket path: `/tmp/sandbox-sockets/sandbox.sock`
* Override with `--socket <path>` if needed
* Docker users: Set `SANDBOX_SOCKET_HOST_DIR` when starting the container for non-default paths

For detailed architecture information, see `docs/development/sandbox-architecture.md`.

## Important Rules

* Run `/rebase` before `/merge` to ensure the branch is up-to-date with the target
* The PR merge auto-deletes the remote branch - do not delete it manually
* This command does NOT checkout or pull the target branch - do that manually if needed
* The sandbox merge workflow is separate from the GitHub PR merge - use the right one for your use case
