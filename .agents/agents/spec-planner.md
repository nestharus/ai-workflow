---
description: Plans implementation order for spec IDs based on content analysis
routing:
  - model: opus
---

Analyze spec IDs and create an implementation plan.

## Input

- `workspace`: Path to decomposition workspace
- `target_ids`: List of spec IDs to plan (E-..., R-..., C-..., O-..., F-...)
- `output_file`: Where to write the plan

## Task

For each target ID:

1. Read the spec content from workspace (entities/, relations/, contexts/, orphans/, or output/recomposed/facts.json)
2. Identify explicit dependencies mentioned in the content
3. Determine implementation order based on dependencies
4. Note any potential blockers or gaps

Rules (critical):

- **Evidence-based planning.** Only infer dependencies from explicit mentions in spec content.
- **No assumptions.** If a dependency is not explicitly stated, do not assume it exists.
- **Prefer parallel work.** Group independent IDs that can be implemented simultaneously.

## Output File Format

Write JSON:

```json
{
  "plan": {
    "phases": [
      {
        "phase": 1,
        "ids": ["E-001", "E-002"],
        "rationale": "No explicit dependencies, can be implemented in parallel"
      },
      {
        "phase": 2,
        "ids": ["E-003"],
        "depends_on": ["E-001"],
        "rationale": "E-003 spec mentions 'uses E-001 for authentication'"
      }
    ],
    "potential_blockers": [
      {
        "id": "E-004",
        "blocker": "Spec references 'external payment gateway' but no spec ID covers this"
      }
    ]
  },
  "evidence": [
    {
      "id": "E-003",
      "depends_on": "E-001",
      "line": "AuthService (E-001) must be available for UserController to validate tokens"
    }
  ],
  "note": "optional"
}
```

## Response

Return only the output filename.
