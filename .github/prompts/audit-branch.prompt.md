---
description: AUDIT orchestration - Analyzes receipts, drift reports, git history for process misalignment
---

# AUDIT Orchestration - Branch Audit

Analyzes receipts, drift reports, review reports, and git history to produce an audit report identifying process misalignment, missing receipts, and suspicious patterns.

Input: `{{input}}` (workspace-path [audit-scope])

Format: `<workspace-path> [audit-scope]`
Example: `.tmp/create/implementation/ full`

## Orchestration Type

**AUDIT** - Investigates process and history to detect pipeline violations and misalignment.

## Prerequisites

- Workspace to audit must exist
- Workspace should contain receipts, reports, and artifacts

## Reference

See `.ai/orchestration/process-audit-orchestration.md` for complete orchestration design.

## Workspace Setup

All audit artifacts are created under `.tmp/audit/`:

```
.tmp/audit/
├── input/               # Receipts, drift reports, review reports, git history
├── analysis/            # Analysis artifacts from audit agents
├── reports/             # Final audit report and recommendations
└── 99_receipts/         # Agent receipts for pipeline oversight
```

## Audit Scopes

- `full` - Analyze all aspects (receipts, drift, reviews, git history) [default]
- `receipts` - Focus on missing/incomplete receipts
- `drift` - Focus on repeated drift failures
- `reviews` - Focus on review loop anomalies
- `git` - Focus on git history and commit patterns

## Workflow

### Step 1: Setup Workspace

Create the workspace directory structure:

```bash
mkdir -p .tmp/audit/{input,analysis,reports,99_receipts}
```

### Step 2: Parse Arguments

Extract workspace path and audit scope from input. Default to 'full' if not specified.

### Step 3: Validate Workspace

Verify the workspace exists.

### Step 4: Collect Input Artifacts

Copy relevant artifacts from the workspace to audit input:
- Collect receipts from `99_receipts/`
- Collect drift reports
- Collect review reports
- Collect iteration logs

### Step 5: Collect Git History

Extract relevant git history for the time period of the workspace:

```bash
# Get workspace creation time
WORKSPACE_TIME=$(stat -c %Y "$WORKSPACE_PATH")

# Get git log since workspace creation
git log --since="@$WORKSPACE_TIME" --oneline --name-status > .tmp/audit/input/git_log.txt

# Get detailed diff for changed files
git log --since="@$WORKSPACE_TIME" -p > .tmp/audit/input/git_diff.txt
```

### Step 6: Build Timeline

Invoke analyzer using #agent to create a chronological timeline of:
- Agent invocations (from receipts)
- Drift detection events (from drift reports)
- Review iterations (from review reports)
- Git commits (from git history)
- Failures and repairs
- Escalations

Output: `.tmp/audit/analysis/timeline.md`

### Step 7: Analyze Receipts

Invoke receipt analyzer using #agent to detect:
1. Missing receipts (agents that ran but didn't produce receipts)
2. Incomplete receipts (missing required sections)
3. Empty deviation sections when deviations likely occurred
4. Suspicious patterns (decision injection, artifact tampering, responsibility deflection)

Output: `.tmp/audit/analysis/receipt_analysis.md`

### Step 8: Analyze Drift Patterns

Invoke drift analyzer using #agent to check for:
1. Repeated drift on the same artifact
2. Drift with no progress (same issues reported multiple times)
3. Drift patterns suggesting plan issues vs implementation issues
4. Unjustified deviations from plans

Output: `.tmp/audit/analysis/drift_analysis.md`

### Step 9: Analyze Review Loops

Invoke review loop analyzer using #agent to check for:
1. Excessive review iterations (>3 on same artifact)
2. Review loops with no progress
3. Conflicting reviewer feedback
4. Patch agent introducing new issues

Output: `.tmp/audit/analysis/review_analysis.md`

### Step 10: Analyze Git History

Invoke git history analyzer using #agent to check for:
1. Commits without corresponding receipts
2. Large uncommitted changes
3. Suspicious commit patterns (e.g., rapid reverts)
4. Drift between commits and documented decisions

Output: `.tmp/audit/analysis/git_analysis.md`

### Step 11: Generate Audit Report

Aggregate all analyses into final audit report using #agent.

The report includes:
- Executive Summary
- Workspace Audited details
- Findings (Critical Issues, Warnings, Informational)
- Misalignment Analysis (Process Violations, Missing Receipts, Suspicious Patterns, Drift Patterns, Review Loop Issues, Git History Issues)
- Impact Assessment
- Recommended Repair Approach
- Prevention Recommendations
- Compliance Metrics

Output: `.tmp/audit/reports/audit_report.md`

### Step 12: Pipeline Oversight Gate

Invoke pipeline oversight enforcer using #agent to verify:
1. Timeline was built from all available artifacts
2. All analyzers ran and produced outputs
3. Audit report was generated
4. All receipts exist
5. Findings are evidence-based (no speculation)

### Step 13: Final Report

Print summary including:
- Workspace audited and scope
- Audit report location
- Analysis artifacts location
- Key findings summary (counts of issues, warnings, missing receipts, etc.)
- Recommendation to see audit report for details

## Output

The command will output:
- Summary of audit process
- Key findings counts
- Audit report location
- Recommendation to review detailed report

## Receipt Format

Every analyzer must write a receipt to `99_receipts/`:

Template: `99_receipts/<analyzer>.md`

Required sections:
- Inputs analyzed
- Analysis scope
- Findings summary
- Evidence sources
- Deviations (required; "None" allowed)
- Assumptions
- Confidence level
- Next action recommended

## Escalation Triggers

Invoke AUDIT when:
- >2 consecutive drift failures on same artifact
- >2 consecutive review loops with no progress
- Missing receipts detected by pipeline oversight
- Suspicious patterns flagged by pipeline oversight
- REPAIR orchestration fails repeatedly

## Error Handling

- If workspace not found, report error and stop
- If no artifacts to audit, report and exit gracefully
- If analyzer fails, report error and continue with other analyzers
- If report generation fails, report error and preserve analysis artifacts
- Always preserve workspace artifacts for review

## Notes

- This is a sub-orchestration called when process misalignment is detected
- Analyzes historical data to identify patterns and root causes
- Provides actionable recommendations for repair and prevention
- All findings are evidence-based, not speculative
- Compliance metrics help track process adherence
