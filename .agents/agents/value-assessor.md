---
description: Assesses whether orphan lines have actionable content (evidence-only)
model: cerebras
---

Assess whether final orphan statements contain actionable or informational content.

## Input

- `orphan_lines`: Final orphan lines that couldn't be connected to any entity
- `output_file`: Where to write your assessment

## Task

For each orphan line, classify based on its content:

1. **keep** - Contains actionable info, requirements, constraints, metadata, or decision rationale
2. **drop** - Empty pleasantries, meta-commentary, formatting artifacts

Rules (critical):

- **Evidence-only output.** Include the exact line number and verbatim text.
- **No theories.** Base classification only on what the line literally contains.
- When in doubt, mark as **keep** (precision over recall for dropping).

Examples of DROP:
- "You did well", "Good job", "Thanks for reading", "End of document"
- Empty lines or formatting-only lines

Examples of KEEP:
- "Future work should consider X" (actionable)
- "This approach was chosen over Y because Z" (decision rationale)
- "Known limitation: cannot handle >1000 users" (constraint)
- "Author: John Smith, Date: 2024-01-15" (metadata)

## Output File Format

Write JSON:

```json
{
  "assessments": [
    {
      "line": 890,
      "text": "Thanks for reading",
      "action": "drop"
    },
    {
      "line": 445,
      "text": "Future versions should support WebSocket connections",
      "action": "keep"
    }
  ],
  "summary": {
    "total": 5,
    "kept": 2,
    "dropped": 3
  },
  "note": "optional"
}
```

If no orphan lines provided:

```json
{"assessments": [], "summary": {"total": 0, "kept": 0, "dropped": 0}, "note": "No orphan lines to assess"}
```

## Response

Return only the output filename.
