---
description: AUDIT orchestration - Analyzes receipts, drift reports, git history for process misalignment
argument-hint: [workspace-path] [audit-scope]
allowed-tools: Bash, Read, Write, Glob, Grep, Task
---

# AUDIT Orchestration Command - Branch Audit

Analyzes receipts, drift reports, review reports, and git history to produce an audit report
identifying process misalignment, missing receipts, and suspicious patterns.

## Orchestration Type

**AUDIT** - Investigates process and history to detect pipeline violations and misalignment.

## Reference

See `.ai/orchestration/process-audit-orchestration.md` for complete orchestration design.

## Workspace Setup

All audit artifacts are created under `.tmp/audit/`:

```bash
mkdir -p .tmp/audit/{input,analysis,reports,99_receipts}
```

Required subfolders:
- `input/` - Receipts, drift reports, review reports, git history
- `analysis/` - Analysis artifacts from audit agents
- `reports/` - Final audit report and recommendations
- `99_receipts/` - Agent receipts for pipeline oversight

## Arguments

`$ARGUMENTS` format:
- `workspace-path` - Path to workspace to audit (required)
- `audit-scope` - Scope of audit: `full`, `receipts`, `drift`, `reviews`, `git` (optional, default: full)

Example:
```bash
.ai/commands/audit-branch.md .tmp/create/implementation/ full
```

## Audit Scopes

- `full` - Analyze all aspects (receipts, drift, reviews, git history)
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

Extract workspace path and audit scope from `$ARGUMENTS`:

```bash
# Parse arguments
WORKSPACE_PATH=$(echo "$ARGUMENTS" | awk '{print $1}')
AUDIT_SCOPE=$(echo "$ARGUMENTS" | awk '{print $2}')

# Default to full if not specified
if [ -z "$AUDIT_SCOPE" ]; then
    AUDIT_SCOPE="full"
fi
```

### Step 3: Validate Workspace

Verify the workspace exists:

```bash
if [ ! -d "$WORKSPACE_PATH" ]; then
    echo "ERROR: Workspace not found: $WORKSPACE_PATH"
    exit 1
fi
```

### Step 4: Collect Input Artifacts

Copy relevant artifacts from the workspace to audit input:

```bash
# Collect receipts
if [ -d "$WORKSPACE_PATH/99_receipts" ]; then
    mkdir -p .tmp/audit/input/receipts
    cp -r "$WORKSPACE_PATH/99_receipts/"* .tmp/audit/input/receipts/ 2>/dev/null || true
fi

# Collect drift reports
find "$WORKSPACE_PATH" -name "*drift*report*.md" -exec cp {} .tmp/audit/input/ \; 2>/dev/null || true

# Collect review reports
find "$WORKSPACE_PATH" -name "*review*report*.md" -exec cp {} .tmp/audit/input/ \; 2>/dev/null || true

# Collect iteration logs
find "$WORKSPACE_PATH" -name "*iteration*.md" -o -name "*loop*.md" -exec cp {} .tmp/audit/input/ \; 2>/dev/null || true
```

### Step 5: Collect Git History

Extract relevant git history for the time period of the workspace:

```bash
# Get workspace creation time
WORKSPACE_TIME=$(stat -c %Y "$WORKSPACE_PATH" 2>/dev/null || stat -f %B "$WORKSPACE_PATH")

# Get git log since workspace creation
git log --since="@$WORKSPACE_TIME" --oneline --name-status > .tmp/audit/input/git_log.txt

# Get detailed diff for changed files
git log --since="@$WORKSPACE_TIME" -p > .tmp/audit/input/git_diff.txt
```

### Step 6: Build Timeline

Use the Task tool to create a timeline of events:

```text
Task(subagent_type="analyzer", prompt="file:.tmp/audit/input/

## Build Event Timeline

Analyze all input artifacts to construct a chronological timeline of:
- Agent invocations (from receipts)
- Drift detection events (from drift reports)
- Review iterations (from review reports)
- Git commits (from git history)
- Failures and repairs
- Escalations

Output: .tmp/audit/analysis/timeline.md

Format:
```markdown
# Event Timeline

## T0: [Timestamp] - Orchestration Start
- Event: [Description]
- Artifacts: [References]

## T1: [Timestamp] - [Stage/Agent]
- Event: [Description]
- Artifacts: [References]
- Status: [PASS/FAIL/SUSPICIOUS]
...
```

Write receipt to: .tmp/audit/99_receipts/01_timeline_builder.md")
```

### Step 7: Analyze Receipts

Invoke receipt analyzer to detect missing or suspicious receipts:

```text
Task(subagent_type="analyzer", prompt="file:.tmp/audit/input/receipts/
file:.tmp/audit/analysis/timeline.md

## Analyze Receipts

Check for:
1. Missing receipts (agents that ran but didn't produce receipts)
2. Incomplete receipts (missing required sections)
3. Empty deviation sections when deviations likely occurred
4. Suspicious patterns:
   - Decision injection (agent claims decisions were made elsewhere)
   - Artifact tampering indicators
   - Responsibility deflection

Output: .tmp/audit/analysis/receipt_analysis.md

Format:
```markdown
# Receipt Analysis

## Missing Receipts
- [Agent/Stage]: [Expected receipt path] - NOT FOUND

## Incomplete Receipts
- [Receipt path]: Missing [sections]

## Suspicious Patterns
- [Receipt path]: [Description of suspicious pattern]
- [Evidence]: [Quotes from receipt]

## Compliance Score
[Percentage of receipts that are complete and compliant]
```

Write receipt to: .tmp/audit/99_receipts/02_receipt_analyzer.md")
```

### Step 8: Analyze Drift Patterns

Invoke drift analyzer to detect repeated failures:

```text
Task(subagent_type="analyzer", prompt="file:.tmp/audit/input/
file:.tmp/audit/analysis/timeline.md

## Analyze Drift Patterns

Check for:
1. Repeated drift on the same artifact
2. Drift with no progress (same issues reported multiple times)
3. Drift patterns suggesting plan issues vs implementation issues
4. Unjustified deviations from plans

Output: .tmp/audit/analysis/drift_analysis.md

Format:
```markdown
# Drift Analysis

## Repeated Drift Events
- [Artifact]: [Number of drift failures]
- [Pattern]: [Description of recurring issue]

## No-Progress Indicators
- [Artifact]: [Iterations with no improvement]

## Root Cause Hypotheses
- [Hypothesis 1]: [Evidence]
- [Hypothesis 2]: [Evidence]

## Recommendations
- [Recommendation for addressing drift]
```

Write receipt to: .tmp/audit/99_receipts/03_drift_analyzer.md")
```

### Step 9: Analyze Review Loops

Invoke review loop analyzer:

```text
Task(subagent_type="analyzer", prompt="file:.tmp/audit/input/
file:.tmp/audit/analysis/timeline.md

## Analyze Review Loops

Check for:
1. Excessive review iterations (>3 on same artifact)
2. Review loops with no progress
3. Conflicting reviewer feedback
4. Patch agent introducing new issues

Output: .tmp/audit/analysis/review_analysis.md

Format:
```markdown
# Review Loop Analysis

## Excessive Iterations
- [Artifact]: [Number of iterations] - [Reviewer set]

## No-Progress Loops
- [Artifact]: [Description of stagnation]

## Conflicting Feedback
- [Iteration N]: [Reviewer A] vs [Reviewer B]

## Patch Quality Issues
- [Iteration N]: [Patch introduced new issue]

## Recommendations
- [Recommendation for improving review process]
```

Write receipt to: .tmp/audit/99_receipts/04_review_analyzer.md")
```

### Step 10: Analyze Git History

Invoke git history analyzer:

```text
Task(subagent_type="analyzer", prompt="file:.tmp/audit/input/git_log.txt
file:.tmp/audit/input/git_diff.txt
file:.tmp/audit/analysis/timeline.md

## Analyze Git History

Check for:
1. Commits without corresponding receipts
2. Large uncommitted changes
3. Suspicious commit patterns (e.g., rapid reverts)
4. Drift between commits and documented decisions

Output: .tmp/audit/analysis/git_analysis.md

Format:
```markdown
# Git History Analysis

## Orphaned Commits
- [Commit hash]: [Message] - No corresponding receipt

## Uncommitted Work
- [File paths]: [Description of changes]

## Suspicious Patterns
- [Pattern]: [Evidence from git log]

## Alignment Issues
- [Commit] vs [Receipt/Plan]: [Description of misalignment]
```

Write receipt to: .tmp/audit/99_receipts/05_git_analyzer.md")
```

### Step 11: Generate Audit Report

Aggregate all analyses into final audit report:

```text
Task(subagent_type="reporter", prompt="file:.tmp/audit/analysis/

## Generate Final Audit Report

Aggregate findings from all analyses into a comprehensive audit report.

Output: .tmp/audit/reports/audit_report.md

Format:
```markdown
# Process Audit Report

## Executive Summary
[High-level findings and severity]

## Workspace Audited
- Path: [workspace path]
- Scope: [audit scope]
- Time period: [start] to [end]

## Findings

### Critical Issues
1. [Issue]: [Description and evidence]

### Warnings
1. [Issue]: [Description and evidence]

### Informational
1. [Observation]: [Description]

## Misalignment Analysis

### Process Violations
- [Violation]: [Which pipeline rule was broken]

### Missing Receipts
- [List of missing receipts]

### Suspicious Patterns
- [Pattern]: [Evidence and implications]

### Drift Patterns
- [Pattern]: [Root cause hypothesis]

### Review Loop Issues
- [Issue]: [Impact on process]

### Git History Issues
- [Issue]: [Alignment problems]

## Impact Assessment
[How these issues affected the orchestration outcome]

## Recommended Repair Approach
1. [Action]: [Rationale]
2. [Action]: [Rationale]

## Prevention Recommendations
1. [Recommendation]: [How to prevent similar issues]
2. [Recommendation]: [How to prevent similar issues]

## Compliance Metrics
- Receipt completeness: [percentage]
- Drift recurrence rate: [number]
- Review loop efficiency: [metric]
- Git-receipt alignment: [percentage]
```

Write receipt to: .tmp/audit/99_receipts/06_report_generator.md")
```

### Step 12: Pipeline Oversight Gate

Invoke pipeline oversight enforcer:

```text
Task(subagent_type="enforcer", prompt="## Pipeline Oversight Gate - AUDIT

Workspace: .tmp/audit/

Verify:
1. Timeline was built from all available artifacts
2. All analyzers ran and produced outputs
3. Audit report was generated
4. All receipts exist in 99_receipts/
5. Findings are evidence-based (no speculation)

Output gate result to: .tmp/audit/99_receipts/99_pipeline_oversight.md")
```

### Step 13: Final Report

Print summary to terminal:

```text
================================================================================
AUDIT ORCHESTRATION COMPLETE
================================================================================

Workspace audited: <WORKSPACE_PATH>
Audit scope: <AUDIT_SCOPE>

Audit report: .tmp/audit/reports/audit_report.md
Analysis artifacts: .tmp/audit/analysis/
Receipts: .tmp/audit/99_receipts/

## Key Findings:
- Critical issues: <COUNT>
- Warnings: <COUNT>
- Missing receipts: <COUNT>
- Drift recurrence: <COUNT>
- Review loop issues: <COUNT>

See audit report for detailed findings and recommendations.
================================================================================
```

## Receipt Format

Every analyzer must write a receipt to `99_receipts/`:

Template: `99_receipts/<analyzer>.md`

```markdown
- **Inputs analyzed**:
- **Analysis scope**:
- **Findings summary**:
- **Evidence sources**:
- **Deviations** (required; "None" allowed):
- **Assumptions**:
- **Confidence level**:
- **Next action recommended**:
```

## Error Handling

- If workspace not found, report error and stop
- If no artifacts to audit, report and exit gracefully
- If analyzer fails, report error and continue with other analyzers
- If report generation fails, report error and preserve analysis artifacts
- Always preserve workspace artifacts for review

## Escalation Triggers

Invoke AUDIT when:
- >2 consecutive drift failures on same artifact
- >2 consecutive review loops with no progress
- Missing receipts detected by pipeline oversight
- Suspicious patterns flagged by pipeline oversight
- REPAIR orchestration fails repeatedly
