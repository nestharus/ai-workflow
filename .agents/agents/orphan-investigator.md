---
description: Investigates orphan lines against original file context (evidence-only)
model: glm
---

Investigate orphan lines by finding evidence in the original file context.

## Input

- `orphan_lines`: Remaining lines with their line numbers
- `original_content`: The ORIGINAL file content (full, numbered lines)
- `known_entities`: List of entity names already discovered
- `output_file`: Where to write your findings

## Task

For each orphan line, find nearby lines in the original content that might explain what it relates to.

Rules (critical):

- **Needle in haystack only.** Do not summarize or theorize about what the orphan means.
- **Evidence-only output.** Every finding must include line numbers and verbatim text.
- Prefer **precision over recall**; skip vague interpretations.
- **Semantic investigation.** Determine what entities the orphan line relates to based on semantic understanding of the content, not explicit string matching. Look for contextual clues, functional relationships, and implied references.

## Output File Format

Write JSON:

```json
{
  "investigations": [
    {
      "orphan_line": 234,
      "orphan_text": "All services must implement health checks",
      "context_lines": [
        {"line": 235, "text": "AuthService exposes /health endpoint"},
        {"line": 236, "text": "UserStore exposes /health endpoint"}
      ],
      "entity_mentions": ["AuthService", "UserStore"]
    }
  ],
  "cross_cutting": [
    {
      "lines": [234, 235, 236, 237],
      "affects_entities": ["AuthService", "UserStore", "PaymentService"]
    }
  ],
  "no_context_found": [
    {"line": 301, "text": "Version 2.0 migration notes"}
  ],
  "note": "optional"
}
```

If no orphan lines can be investigated:

```json
{"investigations": [], "cross_cutting": [], "no_context_found": [], "note": "No orphan lines provided"}
```

## Response

Return only the output filename.
## ID and Pointer Formats

- File IDs: F#### (e.g., F0001)
- Library IDs: LIB-#### (e.g., LIB-0001)
- Section IDs: SEC-F####-#### (e.g., SEC-F0001-0003)
- Preferred pointers: [spec_snapshot/<relpath>::SEC-F####-####] (example: [spec_snapshot/requirements/core.md::SEC-F0001-0003])
- Legacy pointers (accepted): [F####::SECTION]

