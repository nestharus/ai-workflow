---
description: Investigates orphan lines to determine their meaning relative to known entities
routing:
  - model: glm
---

Orphan lines are content that wasn't claimed by any entity during discovery. Investigate them against the original file to determine what they mean.

## Input

`orphan_lines`: Remaining lines with their line numbers
`original_content`: The ORIGINAL file content (full, unredacted)
`known_entities`: All discovered entities with their info
`output_file`: Where to write your findings

## Task

For each orphan line, investigate:

1. What is this line actually about?
2. Does it relate to any known entity? How?
3. Is it a cross-cutting concern affecting multiple entities?
4. Is it truly standalone information?

Use the original content for context - see what surrounds each orphan line.

## Output File Format

```json
{
  "investigations": [
    {
      "line": 234,
      "content": "All services must implement health checks",
      "analysis": {
        "about": "System-wide health check requirement",
        "relates_to_entities": ["AuthService", "UserStore", "PaymentService"],
        "relationship_type": "cross-cutting-requirement",
        "evidence": "Line 235-237 list specific endpoints for each service"
      }
    },
    {
      "line": 301,
      "content": "Version 2.0 migration notes",
      "analysis": {
        "about": "Migration documentation",
        "relates_to_entities": [],
        "relationship_type": "metadata",
        "evidence": "Standalone section header with no entity references"
      }
    }
  ],
  "cross_cutting_concerns": [
    {
      "concern": "Health checks",
      "affects": ["AuthService", "UserStore", "PaymentService"],
      "lines": [234, 235, 236, 237]
    }
  ],
  "truly_orphan": [
    {
      "line": 301,
      "reason": "Migration metadata, not related to any entity"
    }
  ]
}
```

## Response

Return only the output filename.
