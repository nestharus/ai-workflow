---
description: Discovers entities in content, reports everything found
routing:
  - model: glm
---

Read this content and tell me about every entity/concept/component you can find.

## Input

`content`: Numbered lines from a specification file
`output_file`: Where to write your findings

## Task

Read the content. Find every entity, concept, or component mentioned. For each one:

1. What is it called?
2. What do you think it is? (theorize based on evidence)
3. What lines mention it? (provide line numbers)
4. What else seems related to it?

Don't categorize. Don't filter. Report everything you notice.

## Output File Format

Write your findings as JSON:
```json
{
  "entities": [
    {
      "name": "AuthService",
      "theory": "Appears to be an authentication service that handles user login and session management",
      "evidence": [5, 12, 23, 45],
      "related": ["UserStore", "TokenService", "login", "session"]
    }
  ]
}
```

If you can't find any entities, write:
```json
{"entities": [], "note": "No clear entities found in this content"}
```

## Response

Return only the output filename.
