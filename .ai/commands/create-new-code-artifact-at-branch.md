---
description: Complete implementation from start to finish (Full Implementation Orchestration - all 13 stages)
argument-hint: [ticket-id or description]
allowed-tools: Bash, Read, Write, Glob, Grep, Task
---

# Create New Code Artifact at Branch - Complete Implementation Orchestration

Execute the FULL Implementation Orchestration (CREATE) from user intent to merged PR with passing tests. This command runs **all 13 stages** of the Implementation Orchestration.

## What This Command Does

This is the **COMPLETE CREATE orchestration** that:
1. Creates/fetches ticket with structured intake
2. Runs research if needed
3. Creates implementation plan
4. Implements code with reviews
5. Implements tests with reviews
6. Runs final verification (lint + tests + coverage)
7. Creates PR when all checks pass

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

Check if `$ARGUMENTS` is a ticket ID or a description:

**If ticket ID format (XXX-NNN):**
- Fetch ticket from Linear
- Resume from existing state (check what stages are complete)

**If description:**
- Create new ticket with structured intake
- Start from Stage 0

### Step 2: Setup Workspace

Create the full workspace directory structure:

```bash
mkdir -p .tmp/create/implementation/00_intake
mkdir -p .tmp/create/implementation/10_research
mkdir -p .tmp/create/implementation/10_research/crawl_raw
mkdir -p .tmp/create/implementation/20_planning
mkdir -p .tmp/create/implementation/30_code
mkdir -p .tmp/create/implementation/40_tests
mkdir -p .tmp/create/implementation/90_audit
mkdir -p .tmp/create/implementation/99_receipts
```

---

## STAGE 0-1: Intake + Strategy

**If starting from description (not ticket ID):**

Run the `/create-ticket` command workflow:

1. Write raw input to workspace
2. Invoke `@intent-translator` agent
3. Invoke `@goal-planner` agent
4. Invoke `@strategy-planner` agent
5. Create Linear ticket with all artifacts

**If starting from ticket ID:**

Extract ticket artifacts to workspace (see `/create-plan` Step 3).

**Gate**: Verify all intake and strategy artifacts exist.

**Outputs:**
- `00_intake/`: intent, acceptance_criteria, constraints, unknowns, questions_for_human
- `20_planning/`: goals, non_goals, goal_to_acceptance_map, strategy, selected_structures, rejected_structures
- Receipts: 00_intake, 00_5_goals, 01_strategy

---

## STAGE 2: Research (SUB-ORCHESTRATION)

**Check if research is needed:**

```bash
cat .tmp/create/implementation/00_intake/unknowns.md
```

**If unknowns require research:**

Invoke Research Orchestration (CREATE):

```text
Task(subagent_type="orchestration", prompt="Run Research Orchestration (Create)

Workspace: .tmp/create/implementation/10_research/

Inputs:
- .tmp/create/implementation/00_intake/intent.md
- .tmp/create/implementation/20_planning/strategy.md
- .tmp/create/implementation/00_intake/unknowns.md

This orchestration will:
1. Decompose research into question clusters (@research-question-decomposer)
2. Run crawler swarms (web, repo, dependency, integration, domain)
3. Synthesize and deduplicate findings
4. Bind evidence to claims
5. Check research coverage vs questions

Outputs:
- research_findings.md
- evidence_table.md
- open_gaps.md
- domain_structure_candidates.md
- repo_integration_map.md
- Receipts per step

Follow: .ai/orchestration/research-orchestration.md")
```

**If no research needed:**

Skip to Stage 3.

**Gate**: `@pipeline-oversight-enforcer` validates research outputs.

**Outputs:**
- `10_research/`: research_findings, evidence_table, open_gaps, domain_structure_candidates, repo_integration_map
- Receipts: 02_research__*

---

## STAGE 3: Plan Integration (SUB-ORCHESTRATION)

Invoke Plan Integration Orchestration (INTEGRATE):

```text
Task(subagent_type="orchestration", prompt="Run Plan Integration Orchestration (Integrate)

Workspace: .tmp/create/implementation/20_planning/

Inputs:
- .tmp/create/implementation/00_intake/intent.md
- .tmp/create/implementation/00_intake/acceptance_criteria.md
- .tmp/create/implementation/00_intake/constraints.md
- .tmp/create/implementation/20_planning/strategy.md
[If exists] - .tmp/create/implementation/10_research/research_findings.md
[If exists] - .tmp/create/implementation/10_research/open_gaps.md
[If exists] - .tmp/create/implementation/10_research/repo_integration_map.md
[If exists] - .tmp/create/implementation/10_research/domain_structure_candidates.md

This orchestration will:
1. Decompose acceptance criteria into planning topics (@planning-topic-decomposer)
2. For each topic sequentially:
   - Invoke @integration-planner to add plan section
   - Validate plan structure after each topic
3. Run plan reviewers (@plan-structure-reviewer, @pattern-plan-review, @plan-drift-reviewer)

Output:
- implementation_plan.md (validated, complete)

Follow: .ai/orchestration/plan-integration-orchestration.md")
```

**Gate**: `@pipeline-oversight-enforcer` validates planning outputs.

**Outputs:**
- `20_planning/`: planning_topics, implementation_plan
- Receipts: 03_plan_topics, 03_plan_integration__topic_*, 03_plan_review__*

---

## STAGE 4: Plan Review (SUB-ORCHESTRATION)

Invoke Artifact Review Orchestration (REVIEW) for plan:

```text
Task(subagent_type="orchestration", prompt="Run Artifact Review Orchestration (Review)

Artifact: .tmp/create/implementation/20_planning/implementation_plan.md

Reviewers (sequential):
- @architecture-review (layer compliance, dependency direction)
- @code-style-review (naming, formatting, docstrings)

Patch agent: @plan-patcher

Workspace: .tmp/create/implementation/
Receipts: .tmp/create/implementation/99_receipts/

Loop until all reviewers PASS.

Follow: .ai/orchestration/artifact-review-orchestration.md")
```

**Gate**: `@pipeline-oversight-enforcer` validates review passed.

**Outputs:**
- Updated implementation_plan.md (if patches applied)
- Receipts: 04_artifact_review__*

---

## STAGE 5-7: Code Implementation + Review

**Setup Git Worktree:**

```bash
uv run pr setup-worktree $TICKET_ID
```

Capture worktree details: `worktree_path`, `branch_name`, `base_branch`.

**Stage 5: Code Implementation**

Invoke `@implementor` agent:

```text
Task(subagent_type="agent", prompt="You are the @implementor agent.

Worktree: $worktree_path
Workspace: .tmp/create/implementation/

Read: .tmp/create/implementation/20_planning/implementation_plan.md

Execute plan step by step:
- Follow plan literally
- Code only, NO tests
- After each step: run lint and record outputs
- Work in worktree: $worktree_path

Produce:
- Code changes in worktree
- .tmp/create/implementation/30_code/step_log.md
- .tmp/create/implementation/99_receipts/05_code__implementor.md

Follow: .ai/agents/20-code-artifact/implementation/implementor.md")
```

**Stage 6: Code Drift Review**

Invoke `@implementation-drift-review` agent:

```text
Task(subagent_type="agent", prompt="You are the @implementation-drift-review agent.

Spec: .tmp/create/implementation/20_planning/implementation_plan.md
Artifact: Code in worktree ($worktree_path)

Compare plan vs implementation, detect drift.

Produce:
- .tmp/create/implementation/30_code/code_drift_report.md (PASS/FAIL)
- .tmp/create/implementation/99_receipts/06_drift__implementation-drift-review.md

If FAIL: Route to REPAIR or re-run implementor.

Follow: .ai/agents/20-code-artifact/reviewers/implementation-drift-review.md")
```

**If drift review FAILS:**
- Invoke Debug & Repair Orchestration (REPAIR)
- Re-run drift review
- Loop until PASS

**Stage 7: Code Review**

Invoke Artifact Review Orchestration (REVIEW) for code:

```text
Task(subagent_type="orchestration", prompt="Run Artifact Review Orchestration (Review)

Artifact: Code in worktree ($worktree_path) - changed files only

Reviewers (sequential, rerun ALL on any fail):
- @code-anatomical-review (CODE-B: function composition, routing)
- @code-bug-review (CODE-E: exceptions, edge cases, bugs)

Patch agent: @code-patcher

Workspace: .tmp/create/implementation/
Receipts: .tmp/create/implementation/99_receipts/

Loop until all PASS.

Pattern vocabulary: CODE-B (Anatomical), CODE-E (Bug/Error)

Follow: .ai/orchestration/artifact-review-orchestration.md")
```

**Lint Fixing:**

```bash
cd $worktree_path && uv run ruff check --fix .
cd $worktree_path && uv run ruff format .
cd $worktree_path && uv run ruff check . > .tmp/create/implementation/30_code/lint_output.txt 2>&1
```

**Gate**: All code reviews and lint PASS.

**Outputs:**
- Code changes in worktree
- `30_code/`: step_log, code_drift_report, lint_output
- Receipts: 05_code, 06_drift, 07_code_review__*

---

## CODE COMPLETE - PROCEED TO TESTS

Print checkpoint message:

```text
================================================================================
CODE COMPLETE - PROCEEDING TO TESTS (Stage 8-12)
================================================================================
```

---

## STAGE 8: Test Strategy

Invoke `@testing-strategy` agent:

```text
Task(subagent_type="agent", prompt="You are the @testing-strategy agent.

Workspace: .tmp/create/implementation/

Read:
- .tmp/create/implementation/00_intake/acceptance_criteria.md
- .tmp/create/implementation/20_planning/implementation_plan.md
- Code in worktree: $worktree_path

Identify:
- Use-cases to test
- Components to test
- Codepaths to cover

Produce:
- .tmp/create/implementation/40_tests/testing_strategy.md
- .tmp/create/implementation/99_receipts/08_test_strategy__testing-strategy.md

Follow: .ai/agents/40-test-artifact/planners/testing-strategy.md")
```

**Gate**: `@pipeline-oversight-enforcer` validates test strategy.

**Outputs:**
- `40_tests/`: testing_strategy
- Receipts: 08_test_strategy

---

## STAGE 9: Test Plan Integration (SUB-ORCHESTRATION)

Invoke Plan Integration Orchestration (INTEGRATE) for tests:

```text
Task(subagent_type="orchestration", prompt="Run Test Plan Integration Orchestration (Integrate)

Workspace: .tmp/create/implementation/40_tests/

Inputs:
- .tmp/create/implementation/40_tests/testing_strategy.md
- .tmp/create/implementation/00_intake/acceptance_criteria.md
- .tmp/create/implementation/20_planning/implementation_plan.md
- Code surfaces summary from $worktree_path

This orchestration will:
1. Decompose test strategy into planning topics (@planning-topic-decomposer)
2. For each topic sequentially:
   - Invoke @integration-planner to add test plan section
   - Validate plan structure after each topic

Output:
- test_implementation_plan.md

Follow: .ai/orchestration/plan-integration-orchestration.md")
```

**Gate**: `@pipeline-oversight-enforcer` validates test plan.

**Outputs:**
- `40_tests/`: test_implementation_plan
- Receipts: 09_test_plan__*

---

## STAGE 10: Test Implementation

Invoke `@test-implementor` agent:

```text
Task(subagent_type="agent", prompt="You are the @test-implementor agent.

Worktree: $worktree_path
Workspace: .tmp/create/implementation/

Read: .tmp/create/implementation/40_tests/test_implementation_plan.md

Execute test plan step by step:
- Follow test plan literally
- After each test file: run targeted tests and record outputs
- Work in worktree: $worktree_path

Produce:
- Test files in worktree
- .tmp/create/implementation/40_tests/test_step_log.md
- .tmp/create/implementation/99_receipts/10_tests__test-implementor.md

Follow: .ai/agents/40-test-artifact/implementation/test-implementor.md")
```

**Gate**: `@pipeline-oversight-enforcer` validates test implementation.

**Outputs:**
- Test files in worktree
- `40_tests/`: test_step_log
- Receipts: 10_tests

---

## STAGE 11: Test Drift Review

Invoke `@implementation-drift-review` agent for tests:

```text
Task(subagent_type="agent", prompt="You are the @implementation-drift-review agent.

Spec: .tmp/create/implementation/40_tests/test_implementation_plan.md
Artifact: Tests in worktree ($worktree_path)

Compare test plan vs test implementation, detect drift.

Produce:
- .tmp/create/implementation/40_tests/test_drift_report.md (PASS/FAIL)
- .tmp/create/implementation/99_receipts/11_drift__implementation-drift-review.md

If FAIL: Route to REPAIR or re-run test-implementor.

Follow: .ai/agents/20-code-artifact/reviewers/implementation-drift-review.md")
```

**If drift review FAILS:**
- Invoke Debug & Repair Orchestration (REPAIR)
- Re-run drift review
- Loop until PASS

**Gate**: Drift review PASS.

**Outputs:**
- `40_tests/`: test_drift_report
- Receipts: 11_drift

---

## STAGE 12: Test Review (SUB-ORCHESTRATION)

Invoke Artifact Review Orchestration (REVIEW) for tests:

```text
Task(subagent_type="orchestration", prompt="Run Artifact Review Orchestration (Review)

Artifact: Tests in worktree ($worktree_path) - changed test files only

Reviewers (PARALLEL, rerun ALL on any fail):
- @test-clarity-review (PAT-C: test readability, naming)
- @test-structure-review (PAT-A: AAA pattern, single assertion)
- @test-async-review (PAT-T: async patterns, mocking)

Patch agent: @test-patcher

Workspace: .tmp/create/implementation/
Receipts: .tmp/create/implementation/99_receipts/

Loop until all PASS.

Pattern vocabulary: PAT-A, PAT-B, PAT-C, PAT-E, PAT-T

Follow: .ai/orchestration/artifact-review-orchestration.md")
```

**Gate**: All test reviews PASS.

**Outputs:**
- Updated test files (if patches applied)
- Receipts: 12_test_review__*

---

## STAGE 13: Final Verification

Invoke `@verification-runner` agent:

```text
Task(subagent_type="agent", prompt="You are the @verification-runner agent.

Worktree: $worktree_path
Workspace: .tmp/create/implementation/

Run full verification:
1. uv run ruff check .
2. uv run pytest tests/ --cov=app --cov-report=term-missing --cov-branch

Save outputs:
- .tmp/create/implementation/30_code/final_lint_output.txt
- .tmp/create/implementation/40_tests/final_pytest_output.txt
- .tmp/create/implementation/99_receipts/13_verify__verification-runner.md

Follow: .ai/agents/20-code-artifact/implementation/verification-runner.md")
```

**Check verification results:**

```bash
cat .tmp/create/implementation/30_code/final_lint_output.txt
cat .tmp/create/implementation/40_tests/final_pytest_output.txt
```

**If FAIL:**

Invoke Debug & Repair Orchestration (REPAIR):

```text
Task(subagent_type="orchestration", prompt="Run Debug & Repair Orchestration (Repair)

Inputs:
- .tmp/create/implementation/30_code/final_lint_output.txt
- .tmp/create/implementation/40_tests/final_pytest_output.txt
- Current repo state in worktree: $worktree_path
- Plans: implementation_plan.md, test_implementation_plan.md

This orchestration will:
1. Invoke @investigator to reproduce failure and fix
2. Run artifact review for repaired artifact
3. Return patch + root cause

Then: Return to drift -> review -> verify loop

Follow: .ai/orchestration/debug-repair-orchestration.md")
```

Loop until verification PASS.

**If >2 consecutive failures or suspicious behavior:**

Invoke Process Audit Orchestration (AUDIT):

```text
Task(subagent_type="orchestration", prompt="Run Process Audit Orchestration (Audit)

Inputs:
- .tmp/create/implementation/99_receipts/ (all receipts)
- Drift reports
- Review reports
- Git history in worktree

Output:
- .tmp/create/implementation/90_audit/audit_report.md

Analyze process-level misalignment.

Follow: .ai/orchestration/process-audit-orchestration.md")
```

**Gate**: `@pipeline-oversight-enforcer` validates final verification PASS.

**Outputs:**
- `30_code/`: final_lint_output (PASS)
- `40_tests/`: final_pytest_output (PASS)
- Receipts: 13_verify

---

## FINAL STEPS: Commit, Push, PR

### Commit Changes

Stage all changes:

```bash
cd $worktree_path && git add -A
```

Create commit:

```bash
cd $worktree_path && git commit -m "$TICKET_ID: <TICKET_TITLE>

Complete implementation with tests from Linear ticket $TICKET_ID.

Changes:
- <Summary from step_log.md>
- <Summary from test_step_log.md>

All verifications passed:
- Lint: PASS
- Tests: PASS
- Coverage: <COVERAGE_PERCENTAGE>%

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

### Push Branch

```bash
cd $worktree_path && git push -u origin HEAD
```

### Create Pull Request

```bash
cd $worktree_path && gh pr create --base $base_branch \
  --title "$TICKET_ID: <TICKET_TITLE>" \
  --body "$(cat <<'EOF'
## Summary

Implements [$TICKET_ID](<LINEAR_TICKET_URL>)

<PLAN_OVERVIEW from implementation_plan.md>

## Changes

### Code
<Summary from step_log.md>

### Tests
<Summary from test_step_log.md>

## Verification Status

✓ Lint: PASS
✓ Tests: PASS
✓ Coverage: <COVERAGE_PERCENTAGE>%
✓ Code Drift Review: PASS
✓ Code Reviews: PASS (Anatomical, Bug)
✓ Test Drift Review: PASS
✓ Test Reviews: PASS (Clarity, Structure, Async)

## Test Plan

- [x] All tests pass
- [x] Implementation reviewed against plan
- [x] Success criteria met
- [x] Coverage target achieved

## Linear Ticket

See the implementation plan: <LINEAR_TICKET_URL>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Capture PR URL.

---

## Completion Receipt

Write final completion receipt:

```bash
cat > .tmp/create/implementation/99_receipts/implementation_complete.md << 'EOF'
# Implementation Complete Receipt (All 13 Stages)

**Ticket ID**: $TICKET_ID
**Title**: <TICKET_TITLE>
**Worktree**: $worktree_path
**Branch**: $branch_name
**Base Branch**: $base_branch
**PR URL**: <PR_URL>

## Stages Completed

### Stage 0-1: Intake + Strategy
- Intent translation
- Goal planning
- Strategy planning

### Stage 2: Research
[If run] - Research orchestration complete

### Stage 3: Plan Integration
- Planning topic decomposition
- Iterative plan integration
- Plan reviews

### Stage 4: Plan Review
- Architecture review: PASS
- Code style review: PASS

### Stage 5: Code Implementation
- Code implementation complete
- Step log recorded

### Stage 6: Code Drift Review
- Drift review: PASS

### Stage 7: Code Review
- Anatomical review: PASS
- Bug review: PASS
- Lint: PASS

### Stage 8: Test Strategy
- Test strategy defined

### Stage 9: Test Plan Integration
- Test planning topics
- Test plan integration

### Stage 10: Test Implementation
- Test implementation complete
- Test step log recorded

### Stage 11: Test Drift Review
- Test drift review: PASS

### Stage 12: Test Review
- Clarity review: PASS
- Structure review: PASS
- Async review: PASS

### Stage 13: Final Verification
- Lint: PASS
- Tests: PASS
- Coverage: <COVERAGE_PERCENTAGE>%

## All Receipts

Count: <TOTAL_RECEIPT_COUNT> receipts
Location: .tmp/create/implementation/99_receipts/

## PR Created

PR URL: <PR_URL>
Status: Ready for review
All checks: PASSED

## Workspace

Location: .tmp/create/implementation/
Preserved: Yes (for reference and debugging)

To clean up:
- rm -rf .tmp/create/implementation/
- git worktree remove $worktree_path (after PR merge)
EOF
```

---

## Final Output Summary

Print to terminal:

```text
================================================================================
COMPLETE IMPLEMENTATION FINISHED - ALL STAGES COMPLETE
================================================================================

Ticket: $TICKET_ID - <TICKET_TITLE>
Linear Ticket: uv run linear get-issue $TICKET_ID
Pull Request: <PR_URL>

## Implementation Summary (All 13 Stages)

✓ Stage 0-1: Intake + Strategy (COMPLETE)
✓ Stage 2: Research (COMPLETE or SKIPPED)
✓ Stage 3: Plan Integration (COMPLETE)
✓ Stage 4: Plan Review (PASS)
✓ Stage 5: Code Implementation (COMPLETE)
✓ Stage 6: Code Drift Review (PASS)
✓ Stage 7: Code Review (PASS)
✓ Stage 8: Test Strategy (COMPLETE)
✓ Stage 9: Test Plan Integration (COMPLETE)
✓ Stage 10: Test Implementation (COMPLETE)
✓ Stage 11: Test Drift Review (PASS)
✓ Stage 12: Test Review (PASS)
✓ Stage 13: Final Verification (PASS)

## Final Verification Status

✓ Lint: PASS (ruff)
✓ Tests: PASS (pytest)
✓ Coverage: <COVERAGE_PERCENTAGE>%
✓ All code reviews: PASS
✓ All test reviews: PASS
✓ All drift reviews: PASS

## References

Workspace: .tmp/create/implementation/
Receipts: .tmp/create/implementation/99_receipts/ (<TOTAL_RECEIPT_COUNT> receipts)
Worktree: $worktree_path
Branch: $branch_name

## Next Steps

1. Review the PR on GitHub: <PR_URL>
2. Verify all checks passed
3. Merge PR or request changes
4. Clean up worktree after merge: git worktree remove $worktree_path
5. Clean up workspace: rm -rf .tmp/create/implementation/

================================================================================
FULL IMPLEMENTATION ORCHESTRATION COMPLETE
================================================================================
```

---

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

---

## Notes

- This command implements the FULL Implementation Orchestration (all 13 stages)
- It references the complete orchestration at: `.ai/orchestration/implementation-orchestration.md`
- It uses sub-orchestrations: Research, Plan Integration, Artifact Review, Debug & Repair, Process Audit
- All agents write receipts to `99_receipts/` directory
- Pipeline oversight enforcer validates at every gate
- Workspace and worktree are preserved for reference and debugging
- This is the complete CREATE orchestration from intent to merged PR
