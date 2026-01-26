---
description: Finds contextual information about a known entity
routing:
  - model: glm
---

Given what we know about an entity, find what it FITS INTO. This is NOT about describing the entity - it's about understanding its role and relationships.

## Input

`entity_name`: The entity we're finding context for
`entity_info`: What we already know about the entity
`content`: Numbered lines from a specification file (already partially redacted)
`output_file`: Where to write your findings

## Task

Using what you know about this entity, search for:

1. What does this entity connect to?
2. What role does it play in the larger system?
3. What surrounds it contextually?
4. What relationships are implied by structure or proximity?

Don't repeat information about the entity itself - find its CONTEXT.

## Output File Format

```json
{
  "entity": "AuthService",
  "context_found": [
    {
      "lines": [45, 46],
      "content": "The security layer relies on AuthService for all access control",
      "relationship": "AuthService is depended on by security layer",
      "role": "Gatekeeper for access control"
    },
    {
      "lines": [89],
      "content": "Metrics are collected from AuthService for compliance",
      "relationship": "Monitoring system observes AuthService",
      "role": "Compliance data source"
    }
  ],
  "theories": [
    "AuthService appears to be central to the security architecture",
    "Multiple systems depend on it, suggesting it's a core service"
  ]
}
```

If no context found:
```json
{
  "entity": "AuthService",
  "context_found": [],
  "note": "No additional context found in remaining content"
}
```

## Response

Return only the output filename.
