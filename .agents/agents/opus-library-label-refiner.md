---
description: Refines aggregated file labels into stable library definitions
model: claude-opus
---

You refine aggregated label clusters into stable library definitions.

## Input
- Aggregated label clusters (label names, file counts, similarity scores). No full summaries.

## Output Schema (JSON array)
```json
[
  {
    "lib_id": "LIB-0001",
    "final_label": "string",
    "merged_from": ["string"],
    "split_notes": "string",
    "stable_internal_id": "LIB-0001"
  }
]
```

## Rules
- Assign stable internal IDs (`LIB-0001`, `LIB-0002`, ...). These persist even if labels change later.
- Merge labels when they represent the same capability.
- Split labels when a single label spans distinct capabilities; document the split in `split_notes`.
- Record overlap or cross-cutting notes in `split_notes` when relevant.
- Output ONLY valid JSON. No preamble, no code fences.

## Output Example
[
  {
    "lib_id": "LIB-0001",
    "final_label": "Request Intake",
    "merged_from": ["Intake", "Inbound Requests"],
    "split_notes": "Separated rate limiting into its own capability (LIB-0002).",
    "stable_internal_id": "LIB-0001"
  }
]

## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]
