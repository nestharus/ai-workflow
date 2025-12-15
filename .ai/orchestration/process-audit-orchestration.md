---
description: (AUDIT) Audits process/history misalignment and produces an audit report consumable by Repair.
name: Process Audit Orchestration (Audit)
agent: agent
tools: ['githubRepo', 'terminalLastCommand', 'editFiles']
model: Claude Opus 4.5 (Preview)
---

# Process Audit Orchestration (AUDIT)

## Inputs (provided by caller)
- receipts folder
- drift reports
- review reports
- git history summary / diffs for changed files
- timeline of iterations (if available)

## Output
- `audit_report.md` with:
    - where misalignment occurred (process-level)
    - missing receipts / suspicious patterns
    - loops with “no progress”
    - recommended repair approach (not the repair itself)

Gate: `@pipeline-oversight-enforcer`
