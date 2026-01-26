---
description: Analyzes relation snippets to understand connections between entities
routing:
  - model: glm
---

Analyze these relation snippets and tell me everything about how entities connect.

## Input

`snippets`: Text containing relation statements
`known_entities`: List of entity names we already know about
`output_file`: Where to write your findings

## Task

For each snippet, tell me:

1. What entities are involved?
2. How do they relate? (don't force into categories - just describe)
3. What's the context? Why or when does this relationship matter?
4. Are there entities mentioned that aren't in known_entities? (new discoveries)
5. If the snippet contains statements that apply to **multiple** entities, split them into separate per-entity facts.
6. Any theories about what this relationship implies?

## Output File Format

```json
{
  "analysis": [
    {
      "snippet_id": "S-001",
      "source_file": "path/to/spec.md",
      "source_line": 23,
      "snippet": "AuthService uses UserStore for credential validation",
      "entities_involved": ["AuthService", "UserStore"],
      "relationship": "AuthService depends on UserStore to validate user credentials",
      "context": "This happens during the login flow",
      "new_entities": [],
      "entity_facts": [
        {
          "entity": "AuthService",
          "fact": "AuthService validates credentials via UserStore",
          "evidence": {"source_file": "path/to/spec.md", "source_line": 23}
        },
        {
          "entity": "UserStore",
          "fact": "UserStore is the backing store for credential validation",
          "evidence": {"source_file": "path/to/spec.md", "source_line": 23}
        }
      ],
      "theories": ["UserStore likely contains password hashes or connects to identity provider"]
    }
  ],
  "discovered_entities": ["TokenService", "SessionManager"]
}
```

Notes:
- If the input snippets include a header like `## S-001` and `- **File**:` / `- **Line**:`, carry that through into
  `snippet_id`, `source_file`, `source_line`.
- Keep `snippet` as close to verbatim as possible.

## Response

Return only the output filename.
