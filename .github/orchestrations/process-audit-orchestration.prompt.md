---
name: process-audit-orchestration
description: (AUDIT) Audits process/history misalignment and produces an audit report consumable by Repair.
tools: ["read", "edit", "shell", "custom-agent"]
target: vscode
---

# Orchestration: Process Audit (AUDIT)

## Plan
1. Analyze receipts folder for missing or suspicious patterns
2. Review drift reports and review reports for loops with no progress
3. Examine git history for misalignment with process
4. Generate audit report with recommended repair approach

## Instructions

### Inputs (provided by caller)
- receipts folder
- drift reports
- review reports
- git history summary / diffs for changed files
- timeline of iterations (if available)

### Output
- `audit_report.md` with:
    - where misalignment occurred (process-level)
    - missing receipts / suspicious patterns
    - loops with "no progress"
    - recommended repair approach (not the repair itself)

### Gate
`#agent:pipeline-oversight-enforcer`
