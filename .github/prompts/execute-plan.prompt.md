---
description: Execute implementation plan from ticket (Stage 5-7 of Implementation Orchestration)
---

# Execute Implementation Plan

Execute the implementation plan for a ticket. This implements **Stage 5-7** of the Implementation Orchestration (CREATE): Code Implementation, Code Drift Review, and Code Review.

Input: `{{input}}` (ticket-id or plan-path)

## Prerequisites

- Implementation plan must exist (from create-plan or in workspace)
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

Check if input is a ticket ID or a plan file path:

**If ticket ID format (XXX-NNN):**
- Fetch plan from Linear ticket
- Extract implementation plan section

**If file path:**
- Use the provided plan file directly
- Extract ticket ID from plan if available

### Step 2: Setup Git Worktree

Run the setup-worktree command:

```bash
pr setup-worktree {{input}}
```

This creates an isolated worktree at `.worktrees/<branchName>` with a new branch.

Capture: worktree_path, branch_name, base_branch

Get repository root:

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

Extract the implementation plan from the ticket or file to:
`.tmp/create/implementation/20_planning/implementation_plan.md`

### Step 5: Code Implementation (Stage 5)

Invoke the implementor agent using #agent:implementor:

```text
#agent:implementor

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
```

Wait for the implementor to complete.

### Step 6: Code Drift Review (Stage 6)

Invoke the implementation drift review agent using #agent:implementation-drift-review:

```text
#agent:implementation-drift-review

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
```

Wait for drift review to complete. If drift review FAILS, route to REPAIR orchestration or re-run implementor with drift report, then re-run drift review. Loop until PASS.

### Step 7: Code Review Orchestration (Stage 7)

Run the Artifact Review Orchestration for code with code-anatomical-review and code-bug-review. Loop until all PASS.

### Step 8: Lint Fixing

Run lint-fixer in the worktree (changed files only):

```bash
cd $worktree_path && ruff check --fix .
cd $worktree_path && ruff format .
```

Save lint outputs. If lint fails, fix manually or use lint-fixer agent, then re-run until clean.

### Step 9: Commit Changes

Stage all changes in worktree:

```bash
cd $worktree_path && git add -A
```

Create commit message with ticket ID, title, and summary from step_log.md.

### Step 10: Push Branch

Push with upstream tracking:

```bash
cd $worktree_path && git push -u origin HEAD
```

### Step 11: Create Pull Request

Create PR targeting the base branch with comprehensive description including:
- Summary linking to Linear ticket
- Plan overview
- Changes summary
- Code review status (all PASS)
- Test plan (tests in follow-up)

Capture the PR URL from output.

### Step 12: Write Completion Receipt

Create a final receipt in `99_receipts/execution_complete.md` documenting all stages completed.

### Step 13: Output Summary

Print a comprehensive summary including:
- Ticket ID, title, and Linear URL
- Pull Request URL
- Worktree and branch information
- Implementation status (Stage 5-7)
- Code review status (all PASS)
- References (workspace, receipts, commits)
- Review commands for viewing changes
- Next steps (review PR, manual testing, merge or request changes)
- Worktree cleanup instructions

## Output

The command will output:
- Ticket and PR information
- Implementation and review status
- Worktree and branch details
- Commands for reviewing the implementation
- Next steps for PR review

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
- Use create-new-code-artifact-at-branch for full implementation including tests
