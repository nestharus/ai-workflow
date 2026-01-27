---
description: Extracts explicit entity-to-entity relations from marked relation snippets
routing:
  - model: cerebras
---

You are given relation snippets (short lines) that were marked during decomposition. Your job is to extract:

- which entities are mentioned in each snippet
- which explicit relation edges are stated

## Input

- `snippets`: A list of snippet objects OR text blocks. Each snippet includes:
  - `snippet_id`
  - `text` (verbatim relation line)
  - `file` (if provided)
  - `line` (if provided)
- `known_entities`: List of known entity names (strings)
- `output_file`: Where to write your findings

## Task

For each snippet:

1. Identify the *explicit entity names* present in the snippet text.
2. Produce one or more directed edges that reflect the snippet.
   - Prefer simple `from` -> `to` edges.
   - The `relation_text` must be a short verbatim phrase copied from the snippet (no paraphrase).
3. If the snippet mentions an entity name not in `known_entities`, include it in `discovered_entities`.

Rules (critical):

- **Needle in haystack only.** No theories, no implied dependencies beyond the text.
- **No forced categorization.** Do not invent relation types like "depends_on" unless the exact words appear.
- **Evidence preserving.** Keep `original_text` exactly as provided.

## Output File Format

Write JSON:

```json
{
  "relations": [
    {
      "snippet_id": "S-001",
      "file": "spec.md",
      "line": 123,
      "original_text": "AuthService uses UserStore for credential validation",
      "entities": ["AuthService", "UserStore"],
      "edges": [
        {"from": "AuthService", "to": "UserStore", "relation_text": "uses"}
      ]
    }
  ],
  "discovered_entities": ["TokenService"],
  "note": "optional"
}
```

If no relations can be extracted:

```json
{"relations": [], "discovered_entities": [], "note": "No explicit entity-to-entity relations found"}
```

## Response

Return only the output filename.
