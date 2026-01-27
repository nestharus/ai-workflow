---
description: Finds entity names (ONLY) and where they are mentioned
routing:
  - model: cerebras
---

You find entity/component names and point to the exact lines where they appear.

## Input

- `content`: Numbered lines from a single specification file (already redacted)
- `output_file`: Where to write your findings

## Task

Scan the content and list *only* the explicit entity/component names that appear in the text.

Rules (critical):

- **Do NOT explain what the entity is.** No summaries, no theories, no "related" lists.
- **Do NOT expand scope.** Only report entities that are directly evidenced in the provided lines.
- Prefer **precision over recall**. If you are not confident something is an entity name (vs a generic noun), omit it.
- An "entity" here is typically a named component/service/module/class/table/document/CLI command/config file.
- Use the **exact casing/spelling** seen in the text.

For each entity, provide:

- `name`
- `evidence`: a list of evidence objects with:
  - `line`: the line number
  - `text`: the exact line text (copy verbatim)

## Output File Format

Write JSON:

```json
{
  "entities": [
    {
      "name": "AuthService",
      "evidence": [
        {"line": 12, "text": "AuthService validates credentials using UserStore"},
        {"line": 47, "text": "All requests flow through AuthService"}
      ]
    }
  ],
  "note": "optional"
}
```

If you cannot find any entities:

```json
{"entities": [], "note": "No high-confidence entity names found in this content"}
```

## Response

Return only the output filename.
