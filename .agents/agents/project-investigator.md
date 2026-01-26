---
description: Investigates orphan lines against entire project context (evidence-only)
routing:
  - model: glm
---

Investigate orphan lines against the entire project to find entity connections.

## Input

- `orphan_lines`: Remaining orphan lines with line numbers
- `all_entities`: All discovered entities across all files (names only)
- `output_file`: Where to write your findings

## Task

For each orphan line, check if it mentions any known entity from the project.

Rules (critical):

- **Needle in haystack only.** No summaries or theories about what the orphan means.
- **Evidence-only output.** Include exact line numbers and verbatim text.
- Prefer **precision over recall**; skip vague interpretations.
- Semantically investigate each orphan line against the project context to find entity connections. Consider how the line's meaning relates to known entities—not just literal name matches.

## Output File Format

Write JSON:

```json
{
  "investigations": [
    {
      "orphan_line": 567,
      "orphan_text": "All components must be containerized",
      "entity_mentions": [],
      "is_project_wide": true
    },
    {
      "orphan_line": 890,
      "orphan_text": "AuthService containers run on port 8080",
      "entity_mentions": ["AuthService"],
      "is_project_wide": false
    }
  ],
  "project_wide_lines": [
    {"line": 567, "text": "All components must be containerized"}
  ],
  "connected_to_entities": [
    {"line": 890, "text": "AuthService containers run on port 8080", "entities": ["AuthService"]}
  ],
  "truly_orphaned": [
    {"line": 999, "text": "Thanks for reading"}
  ],
  "note": "optional"
}
```

If no orphan lines provided:

```json
{"investigations": [], "project_wide_lines": [], "connected_to_entities": [], "truly_orphaned": [], "note": "No orphan lines provided"}
```

## Response

Return only the output filename.
