---
name: debug-repair-orchestration
description: (REPAIR) Repairs failing artifacts (code/tests) via investigator in isolated worktree, producing patch + root cause.
tools: ["read", "edit", "shell", "custom-agent"]
target: vscode
---

# Orchestration: Debug & Repair (REPAIR)

## Plan
1. Call investigator to reproduce failure in isolated worktree
2. Fix artifact until tests pass
3. Generate repair root cause and patch summary
4. Run artifact review orchestration with same review set
5. Return patch + root cause + updated receipts

## Instructions

### Inputs (provided by caller)
- failing command outputs (saved files)
- current repo state
- artifact target (code/tests/both)
- relevant plans (implementation_plan.md, test_implementation_plan.md)

### Steps (delegate)
1) CALL AGENT: `#agent:investigator` (Investigator slice)
    - reproduce failure in isolated worktree
    - fix artifact until tests pass
    - write `repair_root_cause.md` and `repair_patch_summary.md`

2) CALL ORCHESTRATION: `Artifact Review Orchestration (Review)`
    - run the same review set that governs the repaired artifact
    - enforce PASS before returning

3) Return patch + root cause + updated receipts.

### Gate
`#agent:pipeline-oversight-enforcer`
