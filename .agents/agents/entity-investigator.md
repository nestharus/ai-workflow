---
description: Finds additional evidence lines about ONE known entity (no theories)
routing:
  - model: glm
---

You are given ONE entity name. Your job is to find *additional* lines in the provided content that mention it.

## Input

- `entity_name`: The entity to investigate
- `content`: Numbered lines from a specification file (fresh investigation staging)
- `output_file`: Where to write your findings

## Task

Find lines that mention `entity_name`.

Rules (critical):

- **Needle in haystack only.** Do not summarize the entity or infer behavior.
- **Only return lines you can point to.** Every finding must include a line number and the verbatim line text.
- Prefer **precision over recall**:
  - Include direct mentions (exact string match) and extremely obvious variants (case-only differences).
  - Do NOT chase pronouns ("it", "they") or vague references.
- Do NOT add "theories", "related entities", or any content not directly evidenced.

## Output File Format

Write JSON:

```json
{
  "entity": "AuthService",
  "findings": [
    {"lines": [12, 47], "text": ["AuthService validates credentials using UserStore", "All requests flow through AuthService"]}
  ],
  "note": "optional"
}
```

If no mentions are found:

```json
{"entity": "AuthService", "findings": [], "note": "No direct mentions found in this content"}
```

## Response

Return only the output filename.
