---
description: >
  Applies spec changes - extracts to libraries, moves sections, removes duplicates
routing:
  - max_chars: 3000
    model: ministral-3b
    ambiguity: false
  - model: cerebras
    ambiguity: true
---

# Spec Manager Merging Agent

Apply planned changes to library files.

## Input

- `spec_folder`: Path to spec folder
- `apply`: Whether to write changes (default: false)
- `batch_id`: Optional specific batch to apply

## Dry-Run Mode (default)

Preview changes without writing:

```bash
uv run python -m scripts.spec_manager merge <spec_folder>
```

Report:
- Sections to extract
- Sections to move
- Duplicates to remove
- Sort operations

## Apply Mode

Apply changes:

```bash
uv run python -m scripts.spec_manager merge <spec_folder> --apply
```

## Operations

1. **Extract**: Copy sections from plan.md to libraries
2. **Move**: Relocate sections to correct primary library
3. **Dedupe**: Remove duplicate sections (keep primary)
4. **Sort**: Sort sections by ID within each library

## Output Contract

- `DRY-RUN: <action_count> actions planned` - Preview only
- `APPLIED: <action_count> actions` - Changes written
- `FAIL: <error>` - Error during merge
