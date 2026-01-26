---
description: Analyzes remaining content that wasn't assigned to entities
routing:
  - model: glm
---

Here's content that wasn't assigned to any specific entity. Tell me what you can figure out about it.

## Input

`content`: Remaining lines from the specification
`known_entities`: List of entities we've already identified
`output_file`: Where to write your findings

## Task

For each piece of remaining content:

1. What is it about?
2. Does it relate to any known entities? Which ones and why?
3. Is it important? Why or why not?
4. Any theories about what it means or why it's here?

Don't force categorization. Just tell me what you notice.

## Output File Format

```json
{
  "analysis": [
    {
      "lines": [234, 235],
      "content": "All services must implement health checks",
      "interpretation": "This is a cross-cutting requirement that applies to all services",
      "related_entities": ["AuthService", "UserStore", "TokenService"],
      "importance": "High - affects system reliability",
      "theories": ["Likely required for Kubernetes deployment or load balancer integration"]
    }
  ],
  "summary": "Found 5 cross-cutting concerns and 2 metadata items"
}
```

## Response

Return only the output filename.
