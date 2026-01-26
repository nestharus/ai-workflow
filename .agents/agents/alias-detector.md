---
description: Determines if entities might be the same thing
routing:
  - model: glm
---

Here are two entities. Tell me if they might be the same thing with different names.

## Input

`entity_a`: First entity (name, what we know about it)
`entity_b`: Second entity (name, what we know about it)
`output_file`: Where to write your findings

## Task

Could these be the same entity? Tell me:

1. What makes you think they might be the same?
2. What makes you think they might be different?
3. What's your overall conclusion?
4. How confident are you?

Don't use a formula. Just reason about it and explain your thinking.

## Output File Format

```json
{
  "entity_a": "UserStore",
  "entity_b": "UserRepository",
  "same_thing": true,
  "confidence": "high",
  "reasoning": {
    "similarities": [
      "Both deal with user data persistence",
      "Both are used by AuthService in similar ways",
      "Repository and Store are common synonyms in this codebase"
    ],
    "differences": [
      "UserStore appears in older sections, UserRepository in newer ones"
    ],
    "conclusion": "Likely the same entity - UserRepository appears to be the new name after a refactoring"
  }
}
```

## Response

Return only the output filename.
