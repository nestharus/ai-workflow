---
description: >
  Validates and legalizes spec content - checks annotations, formats, duplicates
routing:
  - max_chars: 5000
    model: ministral-3b
    ambiguity: false
  - model: cerebras
    ambiguity: true
---

# Spec Manager Staging Agent

Run staging validation on a spec folder and fix issues.

## Input

- `spec_folder`: Path to spec folder
- `issues`: List of issues from staging phase (if fixing)

## Validation Mode

Run staging and report issues:

```bash
uv run python -m scripts.spec_manager stage <spec_folder>
```

Parse output for:
- ERROR level issues (must fix)
- WARNING level issues (should fix)
- INFO level issues (informational)

## Fix Mode

When given issues to fix:

1. Read the file(s) containing issues
2. Apply fixes:
   - Legacy annotation formats → canonical format
   - Missing declarations → add `([=ID])` to headers
   - Duplicate declarations → remove duplicates
3. Re-run staging to verify fixes

### Fix Patterns

| Issue Type | Fix |
|------------|-----|
| Legacy `[(=ID)]` | Replace with `([=ID])` |
| Legacy `(=[ID])` | Replace with `([=ID])` |
| Legacy `(+[ID])` | Replace with `(@[+ID])` |
| Missing declaration | Add `([=ID])` to header based on content |
| Duplicate declaration | Keep first, remove subsequent |

## Output Contract

- `VALID` - No issues found
- `FIXED: <count>` - Fixed N issues
- `ISSUES: <count> errors, <count> warnings` - Has unfixed issues
