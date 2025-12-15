---
name: artifact-review-orchestration
description: (REVIEW) Generic review orchestration that runs reviewer set(s) and patches the artifact until PASS.
tools: ["read", "edit", "custom-agent"]
target: vscode
---

# Orchestration: Artifact Review (REVIEW)

## Plan
1. Run reviewers (parallel or sequential as provided)
2. Aggregate findings into review_report.md
3. If any FAIL, call patch agent to apply fixes and require receipt
4. Re-run full reviewer set after fixes
5. Exit only when all PASS

## Instructions

### Inputs (provided by caller)
- Artifact path(s)
- Reviewers:
    - sequential list OR parallel list
- Patch agent to apply fixes
- Workspace root for receipts

### Loop
1) Run reviewers (parallel or sequential as provided).
2) Aggregate findings into `review_report.md`.
3) If any FAIL:
    - call patch agent to apply fixes
    - require patch agent to write a receipt including what changed and why
    - re-run full reviewer set
4) Exit only when all PASS.

### Gates
After each loop iteration:
- call `#agent:pipeline-oversight-enforcer` to ensure:
    - reviewers produced explicit pass/fail
    - patch agent produced receipt
    - no "decision injection" / suspicious modifications
