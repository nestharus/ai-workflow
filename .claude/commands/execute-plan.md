---
description: Execute an implementation plan in a git worktree
argument-hint: "`ticket-id`"
allowed-tools: Bash, Read, Write, Glob, Grep, Task
---

# Execute Implementation Plan

Execute the plan for ticket `$ARGUMENTS` in a dedicated git worktree.

**Worktree isolation**: Work is done in an isolated git worktree (`.worktrees/<branch>`) to keep the main working directory clean. Sub-agents (implementor, lint-fixer) operate on files in the worktree path, NOT the main repo. The worktree branch PRs back to the base branch.

## Step 1: Setup Worktree

```bash
uv run pr setup-worktree $ARGUMENTS
```

Returns JSON: `{ "worktree_path", "branch_name", "base_branch", "branch_created": true }`

**Important**: This command ALWAYS creates a new branch. It never checks out existing branches.
If branch name exists, it appends a counter (`-2`, `-3`, etc.).

```bash
git rev-parse --show-toplevel
```

Store `repo_root` and compute absolute `worktree_path` = `{{repo_root}}/{{worktree_path from JSON}}`.

## Step 2: Split Plans

```bash
uv run linear split-plans <TICKET_ID> --output-dir .tmp/plans/<TICKET_ID>
```

Creates: `.tmp/plans/<TICKET_ID>/plan1.md`, `plan2.md`, etc.

If fails (no `---` separator or no plans found), suggest `/create-plan` first.

## Step 3: Execute Plans

For each plan file in sequence:

```text
Task(subagent_type="implementor", prompt="plan_file: {{plan_file_path}}
worktree: {{worktree_path}}")
```

Handle implementor output:
- `SUCCESS` - Proceed to next plan
- `TESTS: [...]` - Run test-fixer agent, then retry implementor
- `FAIL: ...` - Analyze failure, may need human intervention

## Step 4: Lint

```text
Task(subagent_type="lint-fixer", prompt="--worktree {{worktree_path}} --changed-only")
```

Only lints modified files (faster for new implementations).

## Step 5: Cleanup

```bash
rm -rf .tmp/plans/<TICKET_ID>
```

## Step 6: Commit and Push

```bash
uv run pr commit-push --worktree {{worktree_path}} --set-upstream --message "<TICKET_ID>: <TITLE>

Implements the plan from Linear ticket <TICKET_ID>.

Changes:
- <Summary of Plan 1>
- <Summary of Plan 2>"
```

This runs: `git add -A`, creates commit, pushes with `-u origin HEAD` (required for new branches).

## Step 7: Create PR

Run from worktree to ensure correct branch detection:

```bash
cd {{worktree_path}} && gh pr create --base <BASE_BRANCH> --title "<TICKET_ID>: <TITLE>" --body "$(cat <<'EOF'
## Summary
Implements [<TICKET_ID>](<LINEAR_TICKET_URL>)

<PLAN_OVERVIEW>

## Changes
* <Summary of changes from each plan>

## Test Plan
* [ ] All tests pass
* [ ] Implementation reviewed against plan
* [ ] Success criteria met

Linear: <LINEAR_TICKET_URL>
EOF
)"
```

**Note**: PR auto-links to Linear when ticket ID casing matches exactly.

## Step 8: Output Summary

```bash
cd {{worktree_path}}
git rev-parse HEAD                    # current_branch_commit
git rev-parse origin/<BASE_BRANCH>    # pr_target_branch_commit
```

Print:
```
================================================================================
IMPLEMENTATION COMPLETE
================================================================================
Ticket: <TICKET_ID> - <TITLE>
PR: <PR_URL>
Worktree: {{worktree_path}}

References:
  current_branch_commit: <SHA>     # HEAD of PR branch
  pr_target_branch_commit: <SHA>   # merge base for diffs

Commands:
  uv run linear get-issue <TICKET_ID>                           # View plan
  cd {{worktree_path}} && git diff <target>..<current>          # All PR changes
================================================================================
```

## Error Handling

- Ticket fetch fails: report error, stop
- Plan split fails (no separator/plans): suggest `/create-plan`
- Worktree creation fails (branch exists): offer to reuse or cleanup
- Agent fails: save progress, report what completed vs failed
- PR fails: keep branch pushed, report error
- Always cleanup `.tmp/plans/<TICKET_ID>` on completion or error

## Notes

- Multiple `/execute-plan` commands can run in parallel for different tickets
- Clean up worktrees after PR merge: `git worktree remove {{worktree_path}}`
