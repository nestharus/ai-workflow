---
description: REVIEW orchestration - Runs reviewer sets and patches artifacts until all reviewers pass
argument-hint: [artifact-path] [reviewer-set] [--parallel|--sequential]
allowed-tools: Bash, Read, Write, Glob, Grep, Task
---

# REVIEW Orchestration Command - Branch Review

Runs reviewer sets (sequential or parallel) on an artifact and loops until all reviewers pass.
Applies patches via patch agent on failures.

## Orchestration Type

**REVIEW** - Enforces domain rules on artifacts through specialist reviewers.

## Reference

See `.ai/orchestration/artifact-review-orchestration.md` for complete orchestration design.

## Workspace Setup

All review artifacts are created under `.tmp/review/`:

```bash
mkdir -p .tmp/review/{artifacts,reports,patches,99_receipts}
```

Required subfolders:
- `artifacts/` - Copies of artifacts under review
- `reports/` - Reviewer reports and aggregated findings
- `patches/` - Patch agent outputs
- `99_receipts/` - Agent receipts for pipeline oversight

## Arguments

`$ARGUMENTS` format:
- `artifact-path` - Path to artifact to review (required)
- `reviewer-set` - Name of reviewer set to invoke (required)
- `--parallel` - Run reviewers in parallel (optional, default: sequential)
- `--sequential` - Run reviewers sequentially (optional, explicit)

Example:
```bash
.ai/commands/review-branch.md .tmp/create/implementation/20_planning/implementation_plan.md plan-reviewers --sequential
```

## Reviewer Sets

Common reviewer sets:

**plan-reviewers** (sequential):
- `@architecture-review`
- `@code-style-review`

**code-reviewers** (sequential):
- `@code-anatomical-review`
- `@code-bug-review`

**test-reviewers** (parallel):
- `@test-clarity-review`
- `@test-structure-review`
- `@test-async-review`

## Workflow

### Step 1: Setup Workspace

Create the workspace directory structure:

```bash
mkdir -p .tmp/review/{artifacts,reports,patches,99_receipts}
```

### Step 2: Parse Arguments

Extract artifact path and reviewer set from `$ARGUMENTS`:

```bash
# Parse arguments
ARTIFACT_PATH=$(echo "$ARGUMENTS" | awk '{print $1}')
REVIEWER_SET=$(echo "$ARGUMENTS" | awk '{print $2}')
REVIEW_MODE=$(echo "$ARGUMENTS" | grep -o '\-\-parallel\|\-\-sequential' || echo '--sequential')
```

### Step 3: Validate Artifact

Verify the artifact exists and is readable:

```bash
if [ ! -f "$ARTIFACT_PATH" ]; then
    echo "ERROR: Artifact not found: $ARTIFACT_PATH"
    exit 1
fi
```

### Step 4: Copy Artifact to Workspace

Create a working copy in the review workspace:

```bash
cp "$ARTIFACT_PATH" .tmp/review/artifacts/
ARTIFACT_NAME=$(basename "$ARTIFACT_PATH")
```

### Step 5: Invoke Review Orchestration

Use the Task tool to invoke the REVIEW orchestration agent:

```text
Task(subagent_type="orchestrator", prompt="## Run REVIEW Orchestration

Execute the artifact review orchestration following `.ai/orchestration/artifact-review-orchestration.md`.

Artifact: .tmp/review/artifacts/<ARTIFACT_NAME>
Reviewer set: <REVIEWER_SET>
Review mode: <REVIEW_MODE>
Workspace root: .tmp/review/

## Review Loop

1. Run reviewers (<REVIEW_MODE>)
2. Aggregate findings into reports/review_report.md
3. If any FAIL:
   - Invoke patch agent to apply fixes
   - Patch agent must write receipt with changes and rationale
   - Re-run full reviewer set
4. Exit only when all PASS

## Patch Agent Selection

Select patch agent based on artifact type:
- Plans: @plan-patcher
- Code: @code-patcher
- Tests: @test-patcher

## Pipeline Oversight

After each loop iteration, invoke @pipeline-oversight-enforcer to verify:
- Reviewers produced explicit pass/fail
- Patch agent produced receipt
- No decision injection or suspicious modifications

Write all receipts to 99_receipts/.")
```

### Step 6: Monitor Review Loop

The orchestration will loop until all reviewers pass. Each iteration produces:
- `reports/review_report_iteration_N.md` - Aggregated reviewer findings
- `reports/<reviewer>_iteration_N.md` - Individual reviewer reports
- `patches/patch_iteration_N.md` - Patch agent changes (if failures)
- `99_receipts/<reviewer>__iteration_N.md` - Reviewer receipts
- `99_receipts/patcher__iteration_N.md` - Patch agent receipt (if applied)

### Step 7: Apply Final Artifact

After PASS, copy the reviewed artifact back to original location:

```bash
cp .tmp/review/artifacts/"$ARTIFACT_NAME" "$ARTIFACT_PATH"
```

### Step 8: Final Report

Print summary to terminal:

```text
================================================================================
REVIEW ORCHESTRATION COMPLETE - ALL REVIEWERS PASSED
================================================================================

Artifact: <ARTIFACT_PATH>
Reviewer set: <REVIEWER_SET>
Review mode: <REVIEW_MODE>
Iterations required: <N>

Reports: .tmp/review/reports/
Receipts: .tmp/review/99_receipts/

Final artifact updated at: <ARTIFACT_PATH>
================================================================================
```

## Receipt Format

Every reviewer and patch agent must write a receipt to `99_receipts/`:

Template: `99_receipts/<reviewer_or_patcher>__iteration_<N>.md`

```markdown
- **Artifact reviewed**:
- **Review result** (PASS/FAIL):
- **Findings**:
- **Fixes applied** (patch agent only):
- **Deviations** (required; "None" allowed):
- **Assumptions**:
- **Next action recommended**:
```

## Error Handling

- If artifact not found, report error and stop
- If reviewer set unknown, report error and stop
- If reviewer fails to produce pass/fail, flag via pipeline oversight
- If patch agent fails, report error and preserve workspace
- If loop exceeds 5 iterations, escalate to AUDIT orchestration
- Always preserve workspace artifacts for debugging

## Review Loop Exit Conditions

Exit the loop when:
- All reviewers return PASS
- Pipeline oversight enforcer approves

Do NOT exit if:
- Any reviewer returns FAIL
- Reviewer doesn't produce explicit pass/fail
- Patch agent receipt missing
- Pipeline oversight flags suspicious patterns
