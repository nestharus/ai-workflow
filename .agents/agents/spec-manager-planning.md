---
description: >
  Plans spec changes - compares IDs, detects sequences, creates batches for merging
routing:
  - model: glm
    ambiguity: true
---

# Spec Manager Planning Agent

Plan changes for a spec folder by comparing sources and creating batches.

## Input

- `spec_folder`: Path to spec folder
- `conflicts`: List of conflicts to resolve (if resolving)

## Planning Mode

Run planning:

```bash
uv run python -m scripts.spec_manager plan <spec_folder>
```

Parse output for:
- Batches created
- Missing IDs in registry
- Missing IDs in libraries
- Sequence issues
- Conflicts (blocking)

## Conflict Resolution

When given conflicts:

1. Analyze each conflict (ID in multiple libraries)
2. Determine correct primary library from `libs.md`
3. For each conflicting ID:
   - Keep the section in primary library
   - Remove from other libraries
4. Re-run planning to verify

## Output Contract

- `PLANNED: <batch_count> batches` - Planning complete
- `CONFLICTS: <count>` - Has blocking conflicts
- `RESOLVED: <count>` - Resolved conflicts
