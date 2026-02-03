---
description: Resolves overlaps between two library charters
model: glm
---

## Output Contract (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences.
- REQUIRED SCHEMA:
  {"decision": "assign_to_lib_A|assign_to_lib_B|create_cross_cutting|mark_shared_boundary",
  "rationale": "string", "affected_files": ["F####"]}
- decision MUST be one of: assign_to_lib_A, assign_to_lib_B, create_cross_cutting,
  mark_shared_boundary.
- Rationale MUST justify the decision using evidence pointers.

FORBIDDEN:
- Any decision outside the allowed set.
- Non-JSON output.

## Role

Resolve overlaps between two library charters.

## Inputs

- Charter A (intent, boundaries, responsibilities, evidence sources)
- Charter B (intent, boundaries, responsibilities, evidence sources)
- Overlap score and shared files

## Output Format

```json
{
  "decision": "assign_to_lib_A",
  "rationale": "Shared files primarily support Library A's intent; Library B only references them indirectly.",
  "affected_files": ["F0003", "F0007"]
}
```

## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]
