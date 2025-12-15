---
description: (REPAIR) Repairs failing artifacts (code/tests) via investigator in isolated worktree, producing patch + root cause.
name: Debug & Repair Orchestration (Repair)
agent: agent
tools: ['runInTerminal', 'editFiles']
model: Claude Opus 4.5 (Preview)
---

# Debug & Repair Orchestration (REPAIR)

## Inputs (provided by caller)
- failing command outputs (saved files)
- current repo state
- artifact target (code/tests/both)
- relevant plans (implementation_plan.md, test_implementation_plan.md)

## Steps (delegate)
1) CALL AGENT: `@investigator` (Investigator slice)
    - reproduce failure in isolated worktree
    - fix artifact until tests pass
    - write `repair_root_cause.md` and `repair_patch_summary.md`

2) CALL ORCHESTRATION: `Artifact Review Orchestration (Review)`
    - run the same review set that governs the repaired artifact
    - enforce PASS before returning

3) Return patch + root cause + updated receipts.

Gate: `@pipeline-oversight-enforcer`
