---
description: Execute an implementation plan in a git worktree
argument-hint: <ticket-id>
allowed-tools: Bash, Read, Write, Glob, Grep, mcp__linear-server__get_issue, mcp__linear-server__create_comment, mcp__linear-server__update_issue
---

Execute the implementation plan for ticket `$ARGUMENTS` in a dedicated git worktree.

## Git Worktree Workflow

Work is done in an isolated git worktree to keep the main working directory clean.
The worktree branch is created from the current branch and PRs back to it.

## Workflow

### Step 1: Setup Git Worktree

1. Record the current branch: `git branch --show-current` → `<BASE_BRANCH>`
2. Use `mcp__linear-server__get_issue` to fetch the ticket details for the title
3. Generate branch name: `<ticket-id>-<sanitized-title>` (lowercase, hyphens, max 50 chars)
4. Create worktree and branch:
   ```bash
   git worktree add .worktrees/<ticket-id> -b <branch-name>
   ```
5. Change to worktree directory for all subsequent operations

### Step 2: Load Plan

1. The plan is in the ticket description (from Step 1), after the `---` separator
2. Parse the plan to identify individual Plans (Plan 1, Plan 2, etc.)
3. Extract the success criteria

### Step 3: Execute Plans

For each Plan in sequence:

**Implementation Phase:**
```bash
cd .worktrees/<ticket-id>
uv run agent.tasks --agent implementor --prompt "<PLAN_CONTENT>"
```

Where `<PLAN_CONTENT>` is the specific plan section from the ticket description.

Check implementor output:
- `SUCCESS` → proceed to review
- `TESTS: [...]` → run test-debugger, then retry
- `FAIL: ...` → analyze failure, may need human intervention

**Review Phase:**
```bash
cd .worktrees/<ticket-id>
uv run agent.tasks --agent reviewer --prompt "<PLAN_CONTENT>"
```

Check reviewer output:
- `REVIEW: PASS` → proceed to next plan
- `REVIEW: FAIL - ...` → re-run implementor with feedback, then re-review

### Step 4: Commit and Push

After all plans complete successfully:

1. Stage all changes:
   ```bash
   cd .worktrees/<ticket-id>
   git add -A
   ```

2. Create commit with descriptive message:
   ```bash
   git commit -m "$(cat <<'EOF'
   <TICKET_ID>: <TITLE>

   Implements the plan from Linear ticket <TICKET_ID>.

   Changes:
   - <Summary of Plan 1>
   - <Summary of Plan 2>
   - ...

   🤖 Generated with [Claude Code](https://claude.com/claude-code)

   Co-Authored-By: Claude <noreply@anthropic.com>
   EOF
   )"
   ```

3. Push branch:
   ```bash
   git push -u origin <branch-name>
   ```

### Step 5: Create Pull Request

Create PR targeting the base branch:

```bash
gh pr create --base <BASE_BRANCH> --title "<TICKET_ID>: <TITLE>" --body "$(cat <<'EOF'
## Summary

Implements [<TICKET_ID>](<LINEAR_TICKET_URL>)

<PLAN_OVERVIEW>

## Changes

- <Summary of changes from each plan>

## Test Plan

- [ ] All tests pass
- [ ] Implementation reviewed against plan
- [ ] Success criteria met

## Linear Ticket

See the implementation plan on the ticket: <LINEAR_TICKET_URL>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### Step 6: Update Linear and Output

1. Add comment to Linear ticket with PR link using `mcp__linear-server__create_comment`:
   ```markdown
   ## Implementation Complete

   Pull Request: <PR_URL>
   Branch: <branch-name>

   The implementation is ready for review. Please review the PR against the plan above.
   ```

2. Print to terminal:

```
================================================================================
IMPLEMENTATION COMPLETE - REVIEW REQUESTED
================================================================================

Ticket: <TICKET_ID> - <TITLE>
Branch: <branch-name>
Worktree: .worktrees/<ticket-id>
Pull Request: <PR_URL>

Review Process:
1. Go to the Linear ticket: <LINEAR_TICKET_URL>
2. Review the implementation plan in the comments
3. Go to the Pull Request: <PR_URL>
4. Review the code changes against the plan
5. Approve or request changes on the PR

To clean up the worktree after merge:
  git worktree remove .worktrees/<ticket-id>
================================================================================
```

## Error Handling

- If ticket fetch fails, report the error and stop
- If plan not found in ticket description, suggest running /create-plan first
- If worktree creation fails (branch exists), offer to reuse or clean up
- If any agent fails, save progress and report what completed vs what failed
- If PR creation fails, report the error but keep the branch pushed

## Notes

- The worktree isolates work from your main working directory
- You can switch back to main repo anytime: `cd <original-path>`
- Multiple execute-plan commands can run in parallel for different tickets
- Clean up worktrees after PR merge: `git worktree remove .worktrees/<ticket-id>`
