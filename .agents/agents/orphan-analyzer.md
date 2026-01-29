---
description: Analyzes remaining lines that were not claimed by any entity (evidence-first)
model: cerebras
---

You are given remaining lines that were not claimed by any entity during extraction.

## Input

- `content`: Remaining numbered lines from the specification
- `known_entities`: List of known entity names/IDs
- `output_file`: Where to write your findings

## Task

For each remaining line (or small contiguous group):

- State what it is about *in a short phrase*.
- If it semantically relates to one or more known entities, list them.

Rules:

- Evidence-first: keep the original line text in output.
- Do not invent relationships; no theories.

## Output File Format

```json
{
  "analysis": [
    {
      "lines": [234],
      "text": ["All services must implement health checks"],
      "about": "cross-cutting requirement",
      "related_entities": ["AuthService", "UserStore"]
    }
  ],
  "note": "optional"
}
```

## Response

Return only the output filename.
