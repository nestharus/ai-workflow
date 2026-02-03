---
description: 'Validates and legalizes spec content - checks annotations, formats,
  duplicates

  '
model: glm
---

# Spec Manager Staging Agent

Run staging validation on a spec folder and fix issues.

## Input

- `spec_folder`: Path to spec folder
- `issues`: List of issues from staging phase (if fixing)

## Validation Mode

Run staging and report issues:

```bash
uv run spec-manager stage <spec_folder>
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
## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

