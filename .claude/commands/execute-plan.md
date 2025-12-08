# Execute Implementation Plan in Git Worktree

---

description: Execute an implementation plan in a git worktree
argument-hint: "`ticket-id`"
allowed-tools: Bash, Read, Write, Glob, Grep

---

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

### Step 2: Load Plan

1. The plan is in the ticket description (from Step 1), after the `---` separator
2. Parse the plan to identify individual Plans (Plan 1, Plan 2, etc.)
3. Extract the success criteria

### Step 3: Execute Plans

For each Plan in sequence:

**Implementation Phase (use `timeout: 600000`):**

```bash
cd {{worktree_path}} && uv run agent.mcp wait --command "uv run agent.tasks --agent implementor --prompt \"<PLAN_CONTENT>\"" --max-seconds 600
```

Where `<PLAN_CONTENT>` is the specific plan section from the ticket description.

The `agent.mcp wait` command handles all polling internally and returns a final status.
No re-running is required in the normal case.

Handle each status:
* `"status": "completed"` → Check implementor output:
  * `SUCCESS` → proceed to review
  * `TESTS: [...]` → run test-debugger, then retry
  * `FAIL: ...` → analyze failure, may need human intervention
* `"status": "failed"` → Check `error` field and `stderr` for details
* `"status": "timeout"` → Job exceeded time limit. Options:
  1. Increase `--max-seconds` and re-run if more time is needed
  2. Check agent logs for stuck processes
  3. Manually intervene if the task is inherently too long
* `"status": "killed"` → Job was externally terminated

**Review Phase (use `timeout: 600000`):**

```bash
cd {{worktree_path}} && uv run agent.mcp wait --command "uv run agent.tasks --agent reviewer --prompt \"<PLAN_CONTENT>\"" --max-seconds 600
```

Handle each status:
* `"status": "completed"` → Check reviewer output:
  * `REVIEW: PASS` → proceed to next plan
  * `REVIEW: FAIL - ...` → re-run implementor with feedback, then re-review
* `"status": "failed"` → Check `error` field and `stderr` for details
* `"status": "timeout"` → Job exceeded time limit (see options above)
* `"status": "killed"` → Job was externally terminated

### Step 4: Lint Phase

Run the lint-fixer sub-agent against the worktree in changed-only mode:

```yaml
Task(subagent_type="lint-fixer", prompt="--worktree {{worktree_path}} --changed-only")
```

This only lints files that were modified, which is faster and appropriate for new implementations.

### Step 5: Commit and Push

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

### Step 6: Create Pull Request

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

### Step 7: Output Summary

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
* If plan not found in ticket description, suggest running /create-plan first
* If worktree creation fails (branch exists), offer to reuse or clean up
* If any agent fails, save progress and report what completed vs what failed
* If PR creation fails, report the error but keep the branch pushed

## Notes

* The worktree isolates work from your main working directory
* You can switch back to main repo anytime: `cd <original-path>`
* Multiple execute-plan commands can run in parallel for different tickets
* Clean up worktrees after PR merge: `git worktree remove {{worktree_path}}`
