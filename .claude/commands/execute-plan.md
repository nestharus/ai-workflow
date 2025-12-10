---
description: Execute an implementation plan in a git worktree
argument-hint: "`ticket-id`"
allowed-tools: Bash, Read, Write, Glob, Grep, Task
---

# Execute Implementation Plan in Git Worktree

Execute the implementation plan for ticket `$ARGUMENTS` in a dedicated git worktree.

## Git Worktree Workflow

Work is done in an isolated git worktree to keep the main working directory clean.
The worktree branch is created from the current branch and PRs back to it.

## Workflow

### Step 1: Setup Git Worktree

Run the setup-worktree command to create a worktree for the ticket:

```bash
uv run pr setup-worktree $ARGUMENTS
```

This command:
1. Fetches the `branchName` from Linear for the ticket
2. Records the current branch as `<BASE_BRANCH>` for PR targeting
3. Fetches from origin to get latest remote refs
4. Finds an available branch name:
   * If the branch name from Linear doesn't exist: uses it as-is
   * If the branch name already exists (locally or remote): appends a counter (`-2`, `-3`, etc.)
5. Creates a new worktree at `.worktrees/<branchName>` with a new branch

**Important**: This command ALWAYS creates a new branch. It never checks out an existing branch.
If you need to work on an existing branch, use `git worktree add` directly.

The command outputs JSON with the worktree details:
```json
{
  "status": "created",        // or "exists" if worktree already exists at that path
  "worktree_path": ".worktrees/<branchName>",
  "branch_name": "<branchName>",
  "base_branch": "<BASE_BRANCH>",
  "branch_created": true      // always true (new branch is always created)
}
```

### Step 1b: Get Repository Root

```bash
git rev-parse --show-toplevel
```

Store this as `repo_root`.

Store these values for subsequent operations:
* `repo_root` - absolute path to the repository root
* `<branchName>` - the branch name from Linear
* `<worktree_path>` - absolute path: `{{repo_root}}/{{worktree_path from JSON}}`
* `<BASE_BRANCH>` - the current branch, used as PR target

### Step 2: Split Plans into Files

Split the ticket plans into individual files:

```bash
uv run linear split-plans <TICKET_ID> --output-dir .tmp/plans/<TICKET_ID>
```

This extracts each `### Plan N:` section into separate files:
- `.tmp/plans/<TICKET_ID>/plan1.md`
- `.tmp/plans/<TICKET_ID>/plan2.md`
- etc.

The command outputs JSON listing the plan files:
```json
{
  "ok": true,
  "data": {
    "plans": [
      {"file": ".tmp/plans/NES-24/plan1.md", "header": "### Plan 1: Title"},
      {"file": ".tmp/plans/NES-24/plan2.md", "header": "### Plan 2: Title"}
    ],
    "count": 2
  }
}
```

If the command fails (no `---` separator or no plans found), suggest running `/create-plan` first.

### Step 3: Execute Plans

For each plan file in sequence:

**Implementation Phase:**

```text
Task(subagent_type="implementor", prompt="{{plan_file_path}}")
```

Handle implementor output:
* `SUCCESS` - Proceed to review
* `TESTS: [...]` - Run test-fixer agent, then retry implementor
* `FAIL: ...` - Analyze failure, may need human intervention

### Step 4: Lint Phase

Run the lint-fixer sub-agent against the worktree in changed-only mode:

```text
Task(subagent_type="lint-fixer", prompt="--worktree {{worktree_path}} --changed-only")
```

This only lints files that were modified, which is faster and appropriate for new implementations.

### Step 5: Cleanup Plan Files

Remove the temporary plan files:

```bash
rm -rf .tmp/plans/<TICKET_ID>
```

### Step 6: Commit and Push

After all plans complete successfully, use the commit-push command:

```bash
uv run pr commit-push --worktree {{worktree_path}} --set-upstream --message "<TICKET_ID>: <TITLE>

Implements the plan from Linear ticket <TICKET_ID>.

Changes:
- <Summary of Plan 1>
- <Summary of Plan 2>
- ..."
```

This command:
1. Stages all changes (`git add -A`)
2. Creates the commit with the provided message
3. Pushes with `-u origin HEAD` to set upstream tracking (required for new branches)

### Step 7: Create Pull Request

Create PR targeting the base branch:

1. Use the following command:

   ```bash
   gh pr create --base <BASE_BRANCH> --title "<TICKET_ID>: <TITLE>" --body "$(cat <<'EOF'
   ## Summary

   Implements [<TICKET_ID>](<LINEAR_TICKET_URL>)

   <PLAN_OVERVIEW>

   ## Changes

   * <Summary of changes from each plan>

   ## Test Plan

   * [ ] All tests pass
   * [ ] Implementation reviewed against plan
   * [ ] Success criteria met

   ## Linear Ticket

   See the implementation plan on the ticket: <LINEAR_TICKET_URL>
   EOF
   )"
   ```

### Step 8: Output Summary

**Note**: The PR and branch are automatically linked to the Linear ticket when the ticket ID
casing matches exactly. No manual linking is required.

Get commit information:

```bash
cd {{worktree_path}}
# Current branch commit (HEAD of PR branch)
git rev-parse HEAD
# Target branch commit (what PR merges into)
git rev-parse origin/<BASE_BRANCH>
```

Print to terminal:

```text
================================================================================
IMPLEMENTATION COMPLETE - REVIEW REQUESTED
================================================================================

Ticket: <TICKET_ID> - <TITLE>
Linear Ticket: <LINEAR_TICKET_URL>
Pull Request: <PR_URL>

Get plan description with `uv run linear get-issue <TICKET_ID>`

References:
  worktree_directory: {{worktree_path}}
  current_branch_commit: <CURRENT_SHA>   # HEAD of PR branch (latest changes)
  pr_target_branch_commit: <TARGET_SHA>  # HEAD of target branch (merge base)

Review Process:
1. Read ticket description for the implementation plan
2. Read worktree files for complete implementation understanding
3. Look at current commit to see the latest changes
4. Diff branch against pr_target_branch_commit for all changes

Commands:
  # View implementation plan
  Open <LINEAR_TICKET_URL>

  # Read implementation files
  cd {{worktree_path}}

  # See latest commit details
  cd {{worktree_path}} && git log -1

  # Diff all PR changes against target branch
  cd {{worktree_path}} && git diff <pr_target_branch_commit>...<current_branch_commit>
================================================================================
```

## Error Handling

* If ticket fetch fails, report the error and stop
* If plan split fails (no separator or no plans), suggest running /create-plan first
* If worktree creation fails (branch exists), offer to reuse or clean up
* If any agent fails, save progress and report what completed vs what failed
* If PR creation fails, report the error but keep the branch pushed
* Always clean up `.tmp/plans/<TICKET_ID>` directory on completion or error

## Notes

* The worktree isolates work from your main working directory
* You can switch back to main repo anytime: `cd <original-path>`
* Multiple execute-plan commands can run in parallel for different tickets
* Clean up worktrees after PR merge: `git worktree remove {{worktree_path}}`
