---
description: REPAIR orchestration - Invokes investigator to reproduce failures and fix artifacts until tests pass
---

# REPAIR Orchestration - Branch Repair

Invokes investigator to reproduce failures in an isolated worktree, fixes the artifact until tests pass, and produces root cause analysis.

Input: `{{input}}` (artifact-path failure-output)

Format: `<artifact-path> <failure-output-path>`
Example: `src/app/core.py .tmp/create/implementation/40_tests/final_pytest_output.txt`

## Orchestration Type

**REPAIR** - Debugs and repairs failing artifacts through isolated investigation and patching.

## Prerequisites

- Failing artifact must exist
- Failure output must be available
- Git worktree support for isolated investigation

## Reference

See `.ai/orchestration/debug-repair-orchestration.md` for complete orchestration design.

## Workspace Setup

All repair artifacts are created under `.tmp/repair/`:

```
.tmp/repair/
├── input/               # Failing command outputs and context artifacts
├── worktree/            # Isolated git worktree for investigation
├── analysis/            # Root cause analysis and repair summaries
├── patches/             # Generated patches for artifact fixes
└── 99_receipts/         # Agent receipts for pipeline oversight
```

## Workflow

### Step 1: Setup Workspace

Create the workspace directory structure:

```bash
mkdir -p .tmp/repair/{input,worktree,analysis,patches,99_receipts}
```

### Step 2: Parse Arguments

Extract artifact path and failure output from input.

### Step 3: Validate Inputs

Verify the artifact and failure output exist.

### Step 4: Copy Inputs to Workspace

Copy failure outputs and context to workspace.

Determine artifact type (tests or code) and copy relevant plan if exists.

### Step 5: Create Isolated Worktree

Create a git worktree for isolated investigation:

```bash
# Get current branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Create worktree in repair workspace
git worktree add .tmp/repair/worktree "$CURRENT_BRANCH"
```

### Step 6: Invoke Investigator

Invoke the investigator agent using #agent:investigator with reference to input files.

The investigator will:
1. Navigate to isolated worktree
2. Reproduce the failure using the failure output
3. Analyze the root cause
4. Fix the artifact with minimal changes aligned with the plan
5. Verify the fix by re-running tests until they pass
6. Produce outputs:
   - Root cause analysis
   - Repair summary
   - Patch (git diff)
7. Write receipt

**Root Cause Analysis Format:**
- Failure Summary
- Root Cause (detailed explanation)
- Contributing Factors
- Evidence (stack traces, code snippets, error messages)
- Plan Alignment (whether failure was due to drift or plan issues)

**Repair Summary Format:**
- Changes Made (per file)
- Verification (tests passing, lint passing)
- Remaining Issues
- Recommendations

### Step 7: Validate Investigator Outputs

Verify all required outputs were produced:
- Root cause analysis
- Repair summary
- Repair patch

### Step 8: Apply Patch to Main Repository

Apply the repair patch to the main repository:

```bash
cd /mnt/c/Users/xteam/IdeaProjects/ai-workflow
git apply .tmp/repair/patches/repair.patch
```

If patch application fails, report error and stop.

### Step 9: Invoke Review Orchestration

Invoke the REVIEW orchestration to ensure the repaired artifact passes domain rules.

Select appropriate review set based on artifact type:
- code: code-reviewers
- tests: test-reviewers

Output workspace: `.tmp/repair/review/`

Ensure artifact passes all reviewers before proceeding.

### Step 10: Pipeline Oversight Gate

Invoke pipeline oversight enforcer using #agent to verify:
1. Investigator produced root cause analysis
2. Investigator produced repair summary
3. Investigator produced patch
4. Patch was successfully applied
5. Artifact passed review orchestration
6. All receipts exist
7. No decision injection or suspicious patterns

### Step 11: Cleanup Worktree

Remove the isolated worktree:

```bash
git worktree remove .tmp/repair/worktree
```

### Step 12: Final Report

Print summary including:
- Artifact repaired and type
- Root cause location
- Repair summary location
- Patch applied location
- Review result (PASS)
- Receipts location
- Next action (re-run verification)

## Output

The command will output:
- Summary of repair process
- Root cause and repair summary locations
- Patch application confirmation
- Review result (PASS)
- Next action recommendation

## Receipt Format

Every agent must write a receipt to `99_receipts/`:

Template: `99_receipts/<agent>.md`

Required sections:
- Artifact investigated
- Failure reproduced (YES/NO)
- Root cause identified
- Changes applied
- Verification status (tests/lint)
- Deviations (required; "None" allowed)
- Assumptions
- Remaining issues
- Next action recommended

## Escalation to AUDIT

If REPAIR fails repeatedly (>2 times on same artifact):
- Invoke AUDIT orchestration to analyze process misalignment
- Feed audit report back into repair strategy

## Error Handling

- If artifact not found, report error and stop
- If failure output not found, report error and stop
- If worktree creation fails, report error and stop
- If investigator fails to reproduce failure, report detailed findings
- If patch application fails, report error and preserve workspace
- If review orchestration fails, report findings and stop
- Always cleanup worktree, even on errors
- Always preserve workspace artifacts for debugging

## Notes

- This is a sub-orchestration called when artifacts fail validation
- Investigation happens in an isolated worktree to protect main checkout
- Root cause analysis provides detailed explanation of the failure
- Patch is applied to main repository after validation
- Review orchestration ensures repaired artifact meets quality standards
