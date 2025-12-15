---
description: Complete implementation from start to finish (Full Implementation Orchestration - all 13 stages)
---

# Create New Code Artifact at Branch - Complete Implementation Orchestration

Execute the FULL Implementation Orchestration (CREATE) from user intent to merged PR with passing tests. This runs **all 13 stages** of the Implementation Orchestration.

Input: `{{input}}` (ticket-id or description)

## What This Command Does

This is the **COMPLETE CREATE orchestration** that:
1. Creates/fetches ticket with structured intake
2. Runs research if needed
3. Creates implementation plan
4. Implements code with reviews
5. Implements tests with reviews
6. Runs final verification (lint + tests + coverage)
7. Creates PR when all checks pass

## Prerequisites

- Access to Linear CLI
- Git worktree support
- Agent specifications at `.ai/agents/`
- Orchestration specifications at `.ai/orchestration/`

## Workspace Structure

```
.tmp/create/implementation/
├── 00_intake/           # Intent, acceptance criteria, constraints, unknowns
├── 10_research/         # Research findings, evidence, crawl artifacts
├── 20_planning/         # Strategy, planning topics, implementation plan
├── 30_code/             # Step logs, lint outputs
├── 40_tests/            # Test strategy, test plan, pytest outputs
├── 90_audit/            # Audit reports (if triggered)
└── 99_receipts/         # All agent receipts
```

## Workflow

### Step 1: Determine Input Type

Check if input is a ticket ID or a description:

**If ticket ID format (XXX-NNN):**
- Fetch ticket from Linear
- Resume from existing state (check what stages are complete)

**If description:**
- Create new ticket with structured intake
- Start from Stage 0

### Step 2: Setup Workspace

Create the full workspace directory structure with all subdirectories.

## STAGE 0-1: Intake + Strategy

If starting from description (not ticket ID), run the create-ticket workflow.
If starting from ticket ID, extract ticket artifacts to workspace.

**Gate**: Verify all intake and strategy artifacts exist.

**Outputs:**
- `00_intake/`: intent, acceptance_criteria, constraints, unknowns, questions_for_human
- `20_planning/`: goals, non_goals, goal_to_acceptance_map, strategy, selected_structures, rejected_structures
- Receipts: 00_intake, 00_5_goals, 01_strategy

## STAGE 2: Research (SUB-ORCHESTRATION)

Check if research is needed by reading unknowns.md.

If unknowns require research, invoke Research Orchestration (CREATE) using orchestration reference.

**Gate**: Pipeline oversight enforcer validates research outputs.

**Outputs:**
- `10_research/`: research_findings, evidence_table, open_gaps, domain_structure_candidates, repo_integration_map
- Receipts: 02_research__*

## STAGE 3: Plan Integration (SUB-ORCHESTRATION)

Invoke Plan Integration Orchestration (INTEGRATE) which will:
1. Decompose acceptance criteria into planning topics
2. For each topic sequentially: invoke integration-planner to add plan section
3. Run plan reviewers

**Gate**: Pipeline oversight enforcer validates planning outputs.

**Outputs:**
- `20_planning/`: planning_topics, implementation_plan
- Receipts: 03_plan_topics, 03_plan_integration__topic_*, 03_plan_review__*

## STAGE 4: Plan Review (SUB-ORCHESTRATION)

Invoke Artifact Review Orchestration (REVIEW) for plan with architecture-review and code-style-review. Loop until all reviewers PASS.

**Gate**: Pipeline oversight enforcer validates review passed.

**Outputs:**
- Updated implementation_plan.md (if patches applied)
- Receipts: 04_artifact_review__*

## STAGE 5-7: Code Implementation + Review

Setup Git Worktree, then:

**Stage 5: Code Implementation** - Invoke implementor agent
**Stage 6: Code Drift Review** - Invoke implementation-drift-review agent (REPAIR if FAIL)
**Stage 7: Code Review** - Run Artifact Review Orchestration for code
**Lint Fixing** - Run ruff check and format

**Gate**: All code reviews and lint PASS.

**Outputs:**
- Code changes in worktree
- `30_code/`: step_log, code_drift_report, lint_output
- Receipts: 05_code, 06_drift, 07_code_review__*

## CODE COMPLETE - PROCEED TO TESTS

Print checkpoint message.

## STAGE 8: Test Strategy

Invoke testing-strategy agent to identify use-cases, components, and codepaths to test.

**Gate**: Pipeline oversight enforcer validates test strategy.

**Outputs:**
- `40_tests/`: testing_strategy
- Receipts: 08_test_strategy

## STAGE 9: Test Plan Integration (SUB-ORCHESTRATION)

Invoke Plan Integration Orchestration (INTEGRATE) for tests which will decompose test strategy into planning topics and build test_implementation_plan.md.

**Gate**: Pipeline oversight enforcer validates test plan.

**Outputs:**
- `40_tests/`: test_implementation_plan
- Receipts: 09_test_plan__*

## STAGE 10: Test Implementation

Invoke test-implementor agent to execute test plan step by step.

**Gate**: Pipeline oversight enforcer validates test implementation.

**Outputs:**
- Test files in worktree
- `40_tests/`: test_step_log
- Receipts: 10_tests

## STAGE 11: Test Drift Review

Invoke implementation-drift-review agent for tests. REPAIR if FAIL, loop until PASS.

**Gate**: Drift review PASS.

**Outputs:**
- `40_tests/`: test_drift_report
- Receipts: 11_drift

## STAGE 12: Test Review (SUB-ORCHESTRATION)

Invoke Artifact Review Orchestration (REVIEW) for tests with test-clarity-review, test-structure-review, and test-async-review (PARALLEL). Loop until all PASS.

**Gate**: All test reviews PASS.

**Outputs:**
- Updated test files (if patches applied)
- Receipts: 12_test_review__*

## STAGE 13: Final Verification

Invoke verification-runner agent to run full verification (lint + pytest + coverage).

If FAIL, invoke Debug & Repair Orchestration (REPAIR), then loop back to verification.

If >2 consecutive failures or suspicious behavior, invoke Process Audit Orchestration (AUDIT).

**Gate**: Pipeline oversight enforcer validates final verification PASS.

**Outputs:**
- `30_code/`: final_lint_output (PASS)
- `40_tests/`: final_pytest_output (PASS)
- Receipts: 13_verify

## FINAL STEPS: Commit, Push, PR

Stage all changes, create commit with comprehensive message including coverage percentage, push branch, create PR with detailed body including verification status.

Capture PR URL.

## Completion Receipt

Write final completion receipt in `99_receipts/implementation_complete.md` documenting all 13 stages.

## Final Output Summary

Print comprehensive summary including:
- Ticket ID, title, and Linear URL
- Pull Request URL
- All 13 stages completion status
- Final verification status (lint, tests, coverage)
- References (workspace, receipts, worktree, branch)
- Next steps (review PR, merge, cleanup)

## Output

The command will output:
- Complete implementation summary (all 13 stages)
- Final verification status (all PASS)
- Ticket and PR information
- Workspace and worktree details
- Next steps for PR review and merge

## Error Handling

- If any stage fails, stop and report which stage failed
- If drift review fails >2 times, invoke REPAIR orchestration
- If code review fails >2 times, invoke REPAIR orchestration
- If test review fails >2 times, invoke REPAIR orchestration
- If verification fails >2 times, invoke REPAIR orchestration
- If suspicious behavior detected, invoke AUDIT orchestration
- If any agent fails to write receipt, stop and report error
- Always preserve workspace and worktree on errors for debugging
- Report clear escalation paths for human intervention

## Escalation Triggers (AUDIT)

Invoke AUDIT orchestration if:
- >2 consecutive drift failures on same artifact
- >2 consecutive review loops with "no progress"
- Missing receipts detected
- Pipeline oversight flags suspicious instruction injection

## Notes

- This command implements the FULL Implementation Orchestration (all 13 stages)
- It references the complete orchestration at: `.ai/orchestration/implementation-orchestration.md`
- It uses sub-orchestrations: Research, Plan Integration, Artifact Review, Debug & Repair, Process Audit
- All agents write receipts to `99_receipts/` directory
- Pipeline oversight enforcer validates at every gate
- Workspace and worktree are preserved for reference and debugging
- This is the complete CREATE orchestration from intent to merged PR
