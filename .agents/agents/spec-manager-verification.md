---
description: 'Verifies spec integrity - checks content matches, no duplicates, correct
  assignments

  '
model: glm
---

# Spec Manager Verification Agent

Verify spec folder integrity after merging.

## Input

- `spec_folder`: Path to spec folder
- `issues`: List of issues to fix (if fixing)

## Verification Mode

Run verification:

```bash
uv run spec-manager verify <spec_folder>
```

Check for:
- Content mismatches between plan.md and libraries
- Duplicate IDs across libraries
- Empty stubs (sections with no body)
- Assignment issues (IDs in wrong library)

## Fix Mode

When given issues to fix:

### Duplicate IDs
1. Find primary library from libs.md
2. Remove section from non-primary libraries

### Wrong Library
1. Read section from current location
2. Move to primary library
3. Remove from wrong location

### Empty Stubs
1. Check if plan.md has content
2. If yes, copy body from plan.md to library

## Output Contract

- `VALID` - All checks passed
- `ISSUES: <count> duplicates, <count> wrong, <count> empty` - Has issues
- `FIXED: <count>` - Fixed issues
## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

