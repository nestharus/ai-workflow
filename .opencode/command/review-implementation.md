---
description: Review implementation against a plan with state tracking and auto-repair
---

Review an implementation against its plan with automatic failure recovery.

## Arguments

The plan text describing what should be implemented:

```
/review-implementation Add user authentication with JWT tokens. Users should be able to login and logout. Store sessions in Redis.
```

## Execution

1. Create the workspace and save the plan text:

```bash
mkdir -p .tmp/implementation-review
cat > .tmp/implementation-review/plan.txt << 'EOF'
$ARGUMENTS
EOF
```

2. Run the orchestrator:

```bash
uv run python -m scripts.agents implementation-review-orchestrator '{"plan_file": ".tmp/implementation-review/plan.txt", "workspace": ".tmp/implementation-review"}'
```

## What It Does

1. **Build Scope**: Analyzes git history, classifies files, writes shape
2. **Review**: GPT 5.2 XHigh reviews implementation against the plan text
3. **Fix**: PR agent reads issues from file, makes fixes
4. **Update Scope**: Incremental update (new commits only)
5. **Re-review**: Verifies fixes, marks resolved, finds new issues
6. **Iterate**: Until clean or 3 cycles

## Output

- **CLEAN**: All issues resolved, workspace deleted
- **ISSUES REMAIN**: After 3 iterations, workspace preserved
- **FAILED**: Unrecoverable error, workspace preserved with diagnosis
