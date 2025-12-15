---
description: REVIEW orchestration - Runs reviewer sets and patches artifacts until all reviewers pass
---

# REVIEW Orchestration - Branch Review

Runs reviewer sets (sequential or parallel) on an artifact and loops until all reviewers pass. Applies patches via patch agent on failures.

Input: `{{input}}` (artifact-path reviewer-set [--parallel|--sequential])

Format: `<artifact-path> <reviewer-set> [--parallel|--sequential]`
Example: `.tmp/create/implementation/20_planning/implementation_plan.md plan-reviewers --sequential`

## Orchestration Type

**REVIEW** - Enforces domain rules on artifacts through specialist reviewers.

## Prerequisites

- Artifact to review must exist
- Reviewer set must be defined
- Workspace for review artifacts

## Reference

See `.ai/orchestration/artifact-review-orchestration.md` for complete orchestration design.

## Workspace Setup

All review artifacts are created under `.tmp/review/`:

```
.tmp/review/
├── artifacts/           # Copies of artifacts under review
├── reports/             # Reviewer reports and aggregated findings
├── patches/             # Patch agent outputs
└── 99_receipts/         # Agent receipts for pipeline oversight
```

## Reviewer Sets

Common reviewer sets:

**plan-reviewers** (sequential):
- architecture-review
- code-style-review

**code-reviewers** (sequential):
- code-anatomical-review
- code-bug-review

**test-reviewers** (parallel):
- test-clarity-review
- test-structure-review
- test-async-review

## Workflow

### Step 1: Setup Workspace

Create the workspace directory structure:

```bash
mkdir -p .tmp/review/{artifacts,reports,patches,99_receipts}
```

### Step 2: Parse Arguments

Extract artifact path, reviewer set, and review mode (parallel or sequential) from input.

### Step 3: Validate Artifact

Verify the artifact exists and is readable.

### Step 4: Copy Artifact to Workspace

Create a working copy in the review workspace.

### Step 5: Invoke Review Orchestration

Invoke the REVIEW orchestration using orchestration reference following `.ai/orchestration/artifact-review-orchestration.md`.

The orchestration will:
1. Run reviewers (sequential or parallel based on mode)
2. Aggregate findings into reports/review_report.md
3. If any FAIL:
   - Invoke patch agent to apply fixes
   - Patch agent must write receipt with changes and rationale
   - Re-run full reviewer set
4. Exit only when all PASS

**Patch Agent Selection** based on artifact type:
- Plans: plan-patcher
- Code: code-patcher
- Tests: test-patcher

**Pipeline Oversight** after each loop iteration to verify:
- Reviewers produced explicit pass/fail
- Patch agent produced receipt
- No decision injection or suspicious modifications

### Step 6: Monitor Review Loop

The orchestration will loop until all reviewers pass. Each iteration produces:
- Aggregated reviewer findings
- Individual reviewer reports
- Patch agent changes (if failures)
- Reviewer receipts
- Patch agent receipt (if applied)

### Step 7: Apply Final Artifact

After PASS, copy the reviewed artifact back to original location.

### Step 8: Final Report

Print summary including:
- Artifact path
- Reviewer set and mode
- Iterations required
- Reports and receipts locations
- Final artifact update confirmation

## Output

The command will output:
- Summary of review process
- Number of iterations required
- Final status (all reviewers PASSED)
- Artifact update confirmation

## Receipt Format

Every reviewer and patch agent must write a receipt to `99_receipts/`:

Template: `99_receipts/<reviewer_or_patcher>__iteration_<N>.md`

Required sections:
- Artifact reviewed
- Review result (PASS/FAIL)
- Findings
- Fixes applied (patch agent only)
- Deviations (required; "None" allowed)
- Assumptions
- Next action recommended

## Review Loop Exit Conditions

Exit the loop when:
- All reviewers return PASS
- Pipeline oversight enforcer approves

Do NOT exit if:
- Any reviewer returns FAIL
- Reviewer doesn't produce explicit pass/fail
- Patch agent receipt missing
- Pipeline oversight flags suspicious patterns

## Error Handling

- If artifact not found, report error and stop
- If reviewer set unknown, report error and stop
- If reviewer fails to produce pass/fail, flag via pipeline oversight
- If patch agent fails, report error and preserve workspace
- If loop exceeds 5 iterations, escalate to AUDIT orchestration
- Always preserve workspace artifacts for debugging

## Notes

- This is a sub-orchestration called by higher-level orchestrations
- Reviewers can run sequentially or in parallel depending on configuration
- Patch agents automatically fix issues found by reviewers
- Pipeline oversight ensures no malicious modifications
- All decisions are tracked in receipts for audit
