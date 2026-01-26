---
description: Assesses whether orphan statements add any value
routing:
  - model: glm
---

Assess whether final orphan statements add any value or should be dropped.

## Input

`orphan_lines`: Final orphan lines that couldn't be connected to anything
`output_file`: Where to write your assessment

## Task

For each orphan, assess:

1. Does this statement convey actionable information?
2. Does it add knowledge about ANYTHING?
3. Or is it noise with no informational value?

Examples of NO VALUE (drop these):
- "You did well"
- "Good job on this section"
- "Thanks for reading"
- "End of document"
- Empty pleasantries or meta-commentary

Examples of VALUE (keep these):
- "Future work should consider X" (actionable)
- "This approach was chosen over Y because Z" (decision rationale)
- "Known limitation: cannot handle more than 1000 users" (constraint)
- "Author: John Smith, Date: 2024-01-15" (metadata)

## Output File Format

```json
{
  "assessments": [
    {
      "line": 890,
      "content": "Thanks for reading",
      "has_value": false,
      "reason": "Closing pleasantry with no informational content",
      "action": "drop"
    },
    {
      "line": 445,
      "content": "Future versions should support WebSocket connections",
      "has_value": true,
      "reason": "Actionable future requirement",
      "action": "keep",
      "category": "future_work"
    }
  ],
  "summary": {
    "total_assessed": 5,
    "kept": 2,
    "dropped": 3
  }
}
```

## Response

Return only the output filename.
