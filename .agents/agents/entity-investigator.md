---
description: Finds everything about a known entity in content
routing:
  - model: glm
---

I'll give you an entity name. Find everything you can about it in this content.

## Input

`entity_name`: The entity to investigate
`content`: Numbered lines from a specification file
`output_file`: Where to write your findings

## Task

Find everything about this entity. Don't filter or categorize - just report what you find:

1. Every line that mentions it (directly or indirectly)
2. What it does or what it is
3. What it connects to or depends on
4. Any constraints, requirements, or context
5. Your theories about what else might be related

Theorize. Make guesses. Provide evidence (line numbers) for each finding.

## Output File Format

Write your findings as JSON:
```json
{
  "entity": "AuthService",
  "findings": [
    {"lines": [5, 6], "content": "Handles user login and session management"},
    {"lines": [12], "content": "Uses UserStore for credential validation"},
    {"lines": [23, 24, 25], "content": "Supports OAuth2 and SAML protocols"},
    {"lines": [45], "content": "Has a 30 second timeout configured"}
  ],
  "theories": [
    "Likely the main entry point for authentication based on how other services reference it",
    "May have been refactored recently - line 67 mentions 'new auth flow'"
  ],
  "related_entities": ["UserStore", "TokenService", "SessionManager"]
}
```

If you can't find anything about this entity:
```json
{"entity": "AuthService", "findings": [], "note": "No mentions found in this content"}
```

## Response

Return only the output filename.
