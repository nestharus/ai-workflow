---
description: REPAIR orchestration - Invokes investigator to reproduce failures and fix artifacts until tests pass
argument-hint: [artifact-path] [failure-output]
allowed-tools: Bash, Read, Write, Glob, Grep, Task
---

# REPAIR Orchestration Command - Branch Repair

Invokes investigator to reproduce failures in an isolated worktree, fixes the artifact until
tests pass, and produces root cause analysis.

## Orchestration Type

**REPAIR** - Debugs and repairs failing artifacts through isolated investigation and patching.

## Reference

See `.ai/orchestration/debug-repair-orchestration.md` for complete orchestration design.

## Workspace Setup

All repair artifacts are created under `.tmp/repair/`:

```bash
mkdir -p .tmp/repair/{input,worktree,analysis,patches,99_receipts}
```

Required subfolders:
- `input/` - Failing command outputs and context artifacts
- `worktree/` - Isolated git worktree for investigation
- `analysis/` - Root cause analysis and repair summaries
- `patches/` - Generated patches for artifact fixes
- `99_receipts/` - Agent receipts for pipeline oversight

## Arguments

`$ARGUMENTS` format:
- `artifact-path` - Path to failing artifact (code/tests) (required)
- `failure-output` - Path to file containing failure output (required)

Example:
```bash
.ai/commands/repair-branch.md src/app/core.py .tmp/create/implementation/40_tests/final_pytest_output.txt
```

## Workflow

### Step 1: Setup Workspace

Create the workspace directory structure:

```bash
mkdir -p .tmp/repair/{input,worktree,analysis,patches,99_receipts}
```

### Step 2: Parse Arguments

Extract artifact path and failure output from `$ARGUMENTS`:

```bash
# Parse arguments
ARTIFACT_PATH=$(echo "$ARGUMENTS" | awk '{print $1}')
FAILURE_OUTPUT=$(echo "$ARGUMENTS" | awk '{print $2}')
```

### Step 3: Validate Inputs

Verify the artifact and failure output exist:

```bash
if [ ! -f "$ARTIFACT_PATH" ]; then
    echo "ERROR: Artifact not found: $ARTIFACT_PATH"
    exit 1
fi

if [ ! -f "$FAILURE_OUTPUT" ]; then
    echo "ERROR: Failure output not found: $FAILURE_OUTPUT"
    exit 1
fi
```

### Step 4: Copy Inputs to Workspace

Copy failure outputs and context to workspace:

```bash
cp "$FAILURE_OUTPUT" .tmp/repair/input/failure_output.txt

# Determine artifact type
if [[ "$ARTIFACT_PATH" == *"/tests/"* ]]; then
    ARTIFACT_TYPE="tests"
    PLAN_PATH=".tmp/create/implementation/40_tests/test_implementation_plan.md"
elif [[ "$ARTIFACT_PATH" == *"/src/"* ]] || [[ "$ARTIFACT_PATH" == *"/app/"* ]]; then
    ARTIFACT_TYPE="code"
    PLAN_PATH=".tmp/create/implementation/20_planning/implementation_plan.md"
else
    ARTIFACT_TYPE="unknown"
    PLAN_PATH=""
fi

# Copy relevant plan if exists
if [ -n "$PLAN_PATH" ] && [ -f "$PLAN_PATH" ]; then
    cp "$PLAN_PATH" .tmp/repair/input/
fi
```

### Step 5: Create Isolated Worktree

Create a git worktree for isolated investigation:

```bash
# Get current branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Create worktree in repair workspace
git worktree add .tmp/repair/worktree "$CURRENT_BRANCH"
```

### Step 6: Invoke Investigator

Use the Task tool to invoke the investigator agent:

```text
Task(subagent_type="investigator", prompt="file:.tmp/repair/input/failure_output.txt
file:.tmp/repair/input/

## Investigate and Repair Failure

Artifact: <ARTIFACT_PATH>
Artifact type: <ARTIFACT_TYPE>
Worktree: .tmp/repair/worktree/

## Investigation Steps

1. Navigate to isolated worktree: cd .tmp/repair/worktree/
2. Reproduce the failure using the failure output
3. Analyze the root cause:
   - Review error messages and stack traces
   - Examine the failing artifact and related code
   - Compare against the plan (if available)
   - Identify the specific issue causing failure
4. Fix the artifact:
   - Apply minimal changes to resolve the issue
   - Ensure changes align with the plan
   - Preserve existing functionality
5. Verify the fix:
   - Re-run tests until they pass
   - Run lint to ensure code quality
   - Document any remaining issues
6. Produce outputs:
   - Root cause analysis: .tmp/repair/analysis/root_cause.md
   - Repair summary: .tmp/repair/analysis/repair_summary.md
   - Patch: git diff > .tmp/repair/patches/repair.patch
7. Write receipt: .tmp/repair/99_receipts/01_investigator.md

## Root Cause Analysis Format

```markdown
# Root Cause Analysis

## Failure Summary
[Brief description of the failure]

## Root Cause
[Detailed explanation of why the failure occurred]

## Contributing Factors
- [Factor 1]
- [Factor 2]

## Evidence
- [Stack trace excerpts]
- [Relevant code snippets]
- [Error messages]

## Plan Alignment
[Whether the failure was due to implementation drift or plan issues]
```

## Repair Summary Format

```markdown
# Repair Summary

## Changes Made
- [File 1]: [Description of changes]
- [File 2]: [Description of changes]

## Verification
- Tests passing: [YES/NO]
- Lint passing: [YES/NO]

## Remaining Issues
[None or list of issues]

## Recommendations
[Any recommendations for preventing similar failures]
```")
```

### Step 7: Validate Investigator Outputs

Verify all required outputs were produced:

```bash
if [ ! -f .tmp/repair/analysis/root_cause.md ]; then
    echo "ERROR: Root cause analysis not produced"
    exit 1
fi

if [ ! -f .tmp/repair/analysis/repair_summary.md ]; then
    echo "ERROR: Repair summary not produced"
    exit 1
fi

if [ ! -f .tmp/repair/patches/repair.patch ]; then
    echo "ERROR: Repair patch not produced"
    exit 1
fi
```

### Step 8: Apply Patch to Main Repository

Apply the repair patch to the main repository:

```bash
# Navigate to repo root
cd /mnt/c/Users/xteam/IdeaProjects/ai-workflow

# Apply patch
git apply .tmp/repair/patches/repair.patch

if [ $? -ne 0 ]; then
    echo "ERROR: Failed to apply repair patch"
    exit 1
fi
```

### Step 9: Invoke Review Orchestration

Invoke the REVIEW orchestration to ensure the repaired artifact passes domain rules:

```text
Task(subagent_type="orchestrator", prompt="## Run REVIEW Orchestration on Repaired Artifact

Artifact: <ARTIFACT_PATH>
Artifact type: <ARTIFACT_TYPE>

Select appropriate review set based on artifact type:
- code: code-reviewers
- tests: test-reviewers

Run review orchestration following `.ai/orchestration/artifact-review-orchestration.md`.

Output workspace: .tmp/repair/review/
Write receipts to: .tmp/repair/99_receipts/02_<reviewer>.md

Ensure artifact passes all reviewers before proceeding.")
```

### Step 10: Pipeline Oversight Gate

Invoke pipeline oversight enforcer:

```text
Task(subagent_type="enforcer", prompt="## Pipeline Oversight Gate - REPAIR

Workspace: .tmp/repair/

Verify:
1. Investigator produced root cause analysis
2. Investigator produced repair summary
3. Investigator produced patch
4. Patch was successfully applied
5. Artifact passed review orchestration
6. All receipts exist in 99_receipts/
7. No decision injection or suspicious patterns

Output gate result to: .tmp/repair/99_receipts/99_pipeline_oversight.md")
```

### Step 11: Cleanup Worktree

Remove the isolated worktree:

```bash
git worktree remove .tmp/repair/worktree
```

### Step 12: Final Report

Print summary to terminal:

```text
================================================================================
REPAIR ORCHESTRATION COMPLETE
================================================================================

Artifact repaired: <ARTIFACT_PATH>
Artifact type: <ARTIFACT_TYPE>

Root cause: .tmp/repair/analysis/root_cause.md
Repair summary: .tmp/repair/analysis/repair_summary.md
Patch applied: .tmp/repair/patches/repair.patch

Review result: PASS
Receipts: .tmp/repair/99_receipts/

The repaired artifact has been applied to the repository.
Re-run verification to ensure tests pass.
================================================================================
```

## Receipt Format

Every agent must write a receipt to `99_receipts/`:

Template: `99_receipts/<agent>.md`

```markdown
- **Artifact investigated**:
- **Failure reproduced** (YES/NO):
- **Root cause identified**:
- **Changes applied**:
- **Verification status** (tests/lint):
- **Deviations** (required; "None" allowed):
- **Assumptions**:
- **Remaining issues**:
- **Next action recommended**:
```

## Error Handling

- If artifact not found, report error and stop
- If failure output not found, report error and stop
- If worktree creation fails, report error and stop
- If investigator fails to reproduce failure, report detailed findings
- If patch application fails, report error and preserve workspace
- If review orchestration fails, report findings and stop
- Always cleanup worktree, even on errors
- Always preserve workspace artifacts for debugging

## Escalation to AUDIT

If REPAIR fails repeatedly (>2 times on same artifact):
- Invoke AUDIT orchestration to analyze process misalignment
- Feed audit report back into repair strategy
