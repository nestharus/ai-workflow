---
description: Merge a PR via GitHub and perform cleanup (worktree removal, branch sync, ticket completion)
---

# Merge Branch Command

Merge PR for the specified branch, PR, or ticket.

Input: `{{input}}` (ticket-id, PR-id, branch-name, or empty for current branch)

## Prerequisites

- PR must exist for the branch
- PR must be approved and ready to merge
- Run rebase-branch first if needed to ensure branch is up-to-date

## Arguments

- If input is empty: Use current branch (must be on PR branch)
- If input is a PR ID (e.g., `17` or `#17`): Get branch from GitHub PR
- If input is a ticket ID (e.g., `NES-87`): Look up branch from Linear
- If input is a branch name: Use branch directly

## Workflow

### Step 1: Get PR Information

```bash
pr get-pr {{input}}
```

This returns JSON with:
- `branch_name`: Git branch name (may contain slashes)
- `worktree_path`: Path to the worktree, or `null` if on branch directly
- `working_directory`: Where to run commands
- `is_worktree`: Boolean - `true` if using worktree, `false` if on branch directly
- `pr_number`: PR number
- `pr_url`: PR URL
- `base_branch`: Target branch the PR will merge into (e.g., `main`, `develop`)

### Step 2: Extract Ticket ID

```bash
pr extract-ticket-id {{branch_name}}
```

This returns JSON with:
- `ticket_id`: The Linear ticket ID (e.g., `NES-87`), or `null` if not found
- `valid`: Boolean indicating if the ticket exists in Linear

### Step 2b: Get Repository Root

```bash
git rev-parse --show-toplevel
```

Store this as `repo_root`.

Set up variables:
- `ticket_id`: From extract-ticket-id output (may be `null`)
- `repo_root`: From the git command
- `working_dir`: `{{repo_root}}/{{working_directory}}` (absolute path)
- `is_worktree`: From get-pr output
- `base_branch`: The target branch from the PR info (NOT hardcoded)

### Step 3: Complete Merge Workflow

Execute the full merge workflow:

```bash
pr merge --pr {{pr_number}} --working-dir {{working_dir}} --branch {{branch_name}} --base-branch {{base_branch}} {{#if ticket_id}}--ticket {{ticket_id}}{{/if}} {{#if is_worktree}}--is-worktree{{/if}}
```

This command performs:
1. Merge the PR (squash merge)
2. **If `--is-worktree` flag is passed**:
   - Remove git worktree
   - Delete local branch
3. Fetch and prune remote tracking branches
4. **If `--ticket` provided**: Check for remaining open PRs:
   - If **no remaining open PRs**: Mark Linear ticket as Done
   - If **remaining open PRs exist**: Report the next open PR and skip marking done

**Note**: The remote branch auto-deletes after merge (configured in GitHub). Do NOT manually delete the remote branch.

### Step 4: Output Summary

After successful merge, print to terminal:

```text
================================================================================
MERGE COMPLETE
================================================================================

PR #{{pr_number}} merged successfully
Branch: {{branch_name}}
Target: {{base_branch}}

Cleanup performed:
{{#if is_worktree}}
  - Worktree removed
  - Local branch deleted
{{else}}
  - Local branch kept (not a worktree)
{{/if}}
  - Remote branches pruned

{{#if ticket_id}}
Ticket {{ticket_id}}:
{{#if marked_done}}
  - Status updated to Done
{{else}}
  - Not marked Done ({{remaining_prs_count}} remaining open PR(s))
  - Next PR: {{next_pr_url}}
{{/if}}
{{/if}}

Commands:
  # Switch back to main
  cd {{repo_root}} && git checkout {{base_branch}}

  # Pull latest changes
  cd {{repo_root}} && git pull origin {{base_branch}}
================================================================================
```

## Sandbox Merge (Alternative Workflow)

To merge main INTO your feature branch (instead of merging your PR into main), use the sandbox merge operation. This is useful for incorporating upstream changes into your branch before submitting your PR.

### Prerequisites

The sandbox server starts automatically via `dev.ensure-env`. If not running, start manually:

```bash
docker compose -p ai-workflow-devtools -f docker-compose.dev.yml up -d
```

### Execute Sandbox Merge

```bash
pr sandbox-merge --branch {{branch_name}} --target main -v
```

This operation:
- Runs entirely in the `.git/sandbox/` checkout managed by the sandbox server
- Leaves your main checkout untouched
- Merges the target branch (e.g., `main`) INTO your feature branch
- Pushes the result automatically

**Exit codes:**
- `0`: Success, merge completed and pushed
- `2`: Conflicts detected - resolve in `.git/sandbox/` then push manually
- `1`: Error - check logs

For detailed architecture information, see `docs/development/sandbox-architecture.md`.

## Output

The command will output:
- PR merge confirmation
- Cleanup actions performed
- Ticket status update (if applicable)
- Commands for switching to base branch

## Important Rules

- Run rebase-branch before merge-branch to ensure the branch is up-to-date with the target
- The PR merge auto-deletes the remote branch - do not delete it manually
- This command does NOT checkout or pull the target branch - do that manually if needed
- The sandbox merge workflow is separate from the GitHub PR merge - use the right one for your use case

## Error Cases

- **PR not found**: If no PR exists for the branch, the command will fail
- **PR already merged**: If the PR is already merged, the command will fail
- **Merge conflicts**: Should be resolved before merging (use rebase-branch first)
- **Worktree removal fails**: If the worktree is in use or has uncommitted changes
- **Linear ticket not found**: Ticket status update will be skipped
