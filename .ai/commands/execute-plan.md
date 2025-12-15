---
description: Execute implementation plan from ticket (Stage 5-7 of Implementation Orchestration)
argument-hint: [ticket-id or plan-path]
allowed-tools: Bash, Read, Write, Glob, Grep, Task
---

# Execute Implementation Plan

Execute the implementation plan for a ticket. This command implements **Stage 5-7** of the Implementation Orchestration (CREATE): Code Implementation, Code Drift Review, and Code Review.

## Prerequisites

- Implementation plan must exist (from `/create-plan` or in workspace)
- Git worktree for isolated work
- All plan reviews must have passed

## Workspace Structure

```
.tmp/create/implementation/
├── 20_planning/         # Implementation plan (from create-plan)
├── 30_code/             # Step logs, lint outputs
└── 99_receipts/         # All agent receipts
```

## Workflow

### Step 1: Determine Input Source

Check if `$ARGUMENTS` is a ticket ID or a plan file path:

**If ticket ID format (XXX-NNN):**
- Fetch plan from Linear ticket
- Extract implementation plan section

**If file path:**
- Use the provided plan file directly
- Extract ticket ID from plan if available

### Step 2: Setup Git Worktree

Run the setup-worktree command:

```bash
uv run pr setup-worktree $ARGUMENTS
```

This creates an isolated worktree at `.worktrees/<branchName>` with a new branch.

Capture from output:
- `worktree_path` - absolute path to worktree
- `branch_name` - the branch name
- `base_branch` - PR target branch

**Get repository root:**

```bash
repo_root=$(git rev-parse --show-toplevel)
```

Store the absolute worktree path: `$repo_root/$worktree_path`

### Step 3: Setup Workspace

Create workspace directories:

```bash
mkdir -p .tmp/create/implementation/20_planning
mkdir -p .tmp/create/implementation/30_code
mkdir -p .tmp/create/implementation/99_receipts
```

### Step 4: Extract Implementation Plan

**If from ticket:**

```bash
uv run linear get-issue-description $ARGUMENTS > .tmp/create/implementation/ticket_full.md
```

Extract the implementation plan section (after `# Implementation Plan` header):

```bash
# Parse ticket_full.md and extract implementation plan
# Write to: .tmp/create/implementation/20_planning/implementation_plan.md
```

**If from file:**

```bash
cp $ARGUMENTS .tmp/create/implementation/20_planning/implementation_plan.md
```

### Step 5: Code Implementation (Stage 5)

Use the Task tool to invoke the implementor agent:

```text
Task(subagent_type="agent", prompt="You are the @implementor agent.

Worktree: $worktree_path
Workspace: .tmp/create/implementation/

Read the implementation plan:
- .tmp/create/implementation/20_planning/implementation_plan.md

Execute the plan step by step:
- Follow the plan literally
- Do NOT write tests (code only)
- After each step: run lint and record outputs
- Work in the worktree directory: $worktree_path

Produce:
- Code changes in worktree
- .tmp/create/implementation/30_code/step_log.md (execution log)
- .tmp/create/implementation/99_receipts/05_code__implementor.md (receipt)

Rules:
- Must follow plan literally (no deviations without justification)
- Code first, tests after (do NOT write tests)
- Record all decisions and deviations in receipt

Follow the agent specification at: .ai/agents/20-code-artifact/implementation/implementor.md")
```

Wait for the implementor to complete.

### Step 6: Code Drift Review (Stage 6)

Use the Task tool to invoke the implementation drift review agent:

```text
Task(subagent_type="agent", prompt="You are the @implementation-drift-review agent.

Spec: .tmp/create/implementation/20_planning/implementation_plan.md
Artifact: Code changes in worktree ($worktree_path)

Compare:
- What the plan specifies
- What code was actually implemented

Detect drift:
- Missing implementation steps
- Extra implementation not in plan
- Different approach than specified

Produce:
- .tmp/create/implementation/30_code/code_drift_report.md (PASS/FAIL + findings)
- .tmp/create/implementation/99_receipts/06_drift__implementation-drift-review.md (receipt)

If FAIL: Document specific drift items for repair.

Follow the agent specification at: .ai/agents/20-code-artifact/reviewers/implementation-drift-review.md")
```

Wait for drift review to complete.

**Check drift review result:**

```bash
cat .tmp/create/implementation/30_code/code_drift_report.md
```

**If drift review FAILS:**
- Route to REPAIR orchestration OR re-run @implementor with drift report
- Then re-run drift review
- Loop until PASS

### Step 7: Code Review Orchestration (Stage 7)

Run the Artifact Review Orchestration for code:

```text
Task(subagent_type="orchestration", prompt="Run Artifact Review Orchestration (Review)

Artifact: Code in worktree ($worktree_path) - scoped to changed files

Reviewers (sequential, rerun ALL on any fail):
- @code-anatomical-review (CODE-B: function composition, routing)
- @code-bug-review (CODE-E: exceptions, edge cases, bugs)

Patch agent: @code-patcher

Workspace: .tmp/create/implementation/
Receipts: .tmp/create/implementation/99_receipts/

Loop until all reviewers PASS.

Pattern vocabulary: CODE-B (Anatomical), CODE-E (Bug/Error)

Follow: .ai/orchestration/artifact-review-orchestration.md")
```

**This orchestration will:**
1. Run code-anatomical-review and code-bug-review sequentially
2. Aggregate findings into review_report.md
3. If any FAIL: call @code-patcher to fix, then re-run ALL reviewers
4. Exit only when all PASS

Wait for the orchestration to complete.

### Step 8: Lint Fixing

Run lint-fixer in the worktree (changed files only):

```bash
cd $worktree_path && uv run ruff check --fix .
cd $worktree_path && uv run ruff format .
```

Save lint outputs:

```bash
cd $worktree_path && uv run ruff check . > .tmp/create/implementation/30_code/lint_output.txt 2>&1
```

**If lint fails:**
- Review errors
- Fix manually or use lint-fixer agent
- Re-run until clean

### Step 9: Commit Changes

Stage all changes in worktree:

```bash
cd $worktree_path && git add -A
```

Create commit message:

```bash
cd $worktree_path && git commit -m "$ARGUMENTS: <TICKET_TITLE>

Implements the plan from Linear ticket $ARGUMENTS.

Changes:
- <Summary from step_log.md>

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

### Step 10: Push Branch

Push with upstream tracking:

```bash
cd $worktree_path && git push -u origin HEAD
```

### Step 11: Create Pull Request

Create PR targeting the base branch:

```bash
cd $worktree_path && gh pr create --base $base_branch \
  --title "$ARGUMENTS: <TICKET_TITLE>" \
  --body "$(cat <<'EOF'
## Summary

Implements [$ARGUMENTS](<LINEAR_TICKET_URL>)

<PLAN_OVERVIEW from implementation_plan.md>

## Changes

<Summary of changes from step_log.md>

## Code Review Status

- Code Drift Review: PASS
- Code Anatomical Review: PASS
- Code Bug Review: PASS
- Lint: PASS

## Test Plan

Tests will be implemented in a follow-up (Stage 8-12).

For now:
- [ ] Code review
- [ ] Manual testing if needed
- [ ] Verify implementation matches plan

## Linear Ticket

See the implementation plan: <LINEAR_TICKET_URL>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Capture the PR URL from output.

### Step 12: Write Completion Receipt

Create a final receipt:

```bash
cat > .tmp/create/implementation/99_receipts/execution_complete.md << 'EOF'
# Execution Receipt (Stage 5-7)

**Ticket ID**: $ARGUMENTS
**Title**: <TICKET_TITLE>
**Worktree**: $worktree_path
**Branch**: $branch_name
**Base Branch**: $base_branch
**PR URL**: <PR_URL>

## Artifacts Created (Stage 5-7)

### Code Implementation
- step_log.md (execution log)
- Code changes in worktree

### Drift Review
- code_drift_report.md (PASS)

### Code Reviews
- code_anatomical_review.md (PASS)
- code_bug_review.md (PASS)
- artifact_review_report.md (PASS)

### Lint
- lint_output.txt (PASS)

## Receipts
- 05_code__implementor.md
- 06_drift__implementation-drift-review.md
- 07_code_review__*.md (anatomical, bug)
- execution_complete.md

## Review Status

All code reviews PASSED:
- Drift Review: PASS
- Anatomical Review: PASS
- Bug Review: PASS
- Lint: PASS

## Next Steps

Code implementation is complete. Tests not yet implemented.

To continue with tests (Stage 8-12):
- Run test strategy planning
- Run test implementation
- Run test reviews
- Run final verification

Or merge PR if tests not required.
EOF
```

### Step 13: Output Summary

Get commit information:

```bash
current_commit=$(cd $worktree_path && git rev-parse HEAD)
target_commit=$(cd $worktree_path && git rev-parse origin/$base_branch)
```

Print to terminal:

```text
================================================================================
IMPLEMENTATION COMPLETE - REVIEW REQUESTED
================================================================================

Ticket: $ARGUMENTS - <TICKET_TITLE>
Linear Ticket: uv run linear get-issue $ARGUMENTS
Pull Request: <PR_URL>

Worktree: $worktree_path
Branch: $branch_name
Base Branch: $base_branch

## Implementation Status (Stage 5-7)

Code implementation: COMPLETE
Code drift review: PASS
Code reviews: PASS
Lint: PASS

## Code Review Status

✓ Drift Review: PASS (code matches plan)
✓ Anatomical Review: PASS (function composition, routing)
✓ Bug Review: PASS (exceptions, edge cases)
✓ Lint: PASS (ruff check)

## References

Workspace: .tmp/create/implementation/
Receipts: .tmp/create/implementation/99_receipts/

Current commit: $current_commit (HEAD of PR branch)
Target commit: $target_commit (HEAD of base branch)

## Review Commands

# View implementation plan
uv run linear get-issue $ARGUMENTS

# Read implementation files
cd $worktree_path

# See latest commit details
cd $worktree_path && git log -1

# Diff all PR changes against target branch
cd $worktree_path && git diff $target_commit...$current_commit

## Next Steps

1. Review the PR on GitHub
2. Verify implementation matches plan
3. Manual testing if needed
4. Merge PR or request changes

Tests not yet implemented (Stage 8-12 not run).

To clean up worktree after merge:
git worktree remove $worktree_path

================================================================================
```

## Error Handling

- If ticket/plan fetch fails, report the error and stop
- If worktree creation fails, report the error and stop
- If workspace creation fails, report the error and stop
- If implementor fails, save progress and report error
- If drift review fails repeatedly (>2 times), escalate to REPAIR orchestration
- If code review fails repeatedly (>2 times), escalate to REPAIR orchestration
- If lint fails, report errors and stop (or use lint-fixer)
- If commit fails, report error and preserve worktree
- If push fails, report error and preserve worktree
- If PR creation fails, report error but keep branch pushed
- Always preserve workspace on errors for debugging

## Notes

- This command implements Stage 5-7 of the Implementation Orchestration (code only)
- Tests are NOT implemented in this command (Stage 8-12 not included)
- The worktree isolates work from the main working directory
- All code reviews must PASS before PR is created
- Drift review ensures code matches the plan
- Workspace is preserved for potential test implementation or debugging
- Use `/create-code` for full implementation including tests
