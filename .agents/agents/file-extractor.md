---
description: Semantically extracts what OTHER files say about a target file (evidence-only)
routing:
  - model: glm
---

Given a file name, semantically understand what OTHER files say about it. Do not look at the file itself.

## Input

- `file_name`: The file we're finding information about
- `content`: Numbered lines from OTHER files (not the target file)
- `output_file`: Where to write your findings

## Task

Understand the semantic domain/purpose of the target file, then search the content for ANY semantic references to that file:

1. **Analyze the file name**: Derive the semantic domain (e.g., "auth_spec.md" → authentication specifications, auth patterns, auth rules)
2. **Look for semantic matches**: Find content in other files that:
   - References the same domain/purpose (even without mentioning the file name)
   - Discusses concepts that live in or relate to that file
   - Mentions dependencies or relationships to that domain
3. **Extract evidence**: Include source line numbers + verbatim line text

Rules (critical):

- Evidence-only: each finding must include source line numbers + verbatim line text.
- Do not add theories or summarization.
- Match semantically, not by string. "The authentication specification" and "auth rules" both refer to "auth_spec.md".

## Output File Format

```json
{
  "file": "auth_spec.md",
  "findings": [
    {
      "source_file": "api_spec.md",
      "lines": [45, 46],
      "text": [
        "API endpoints must follow patterns defined in auth_spec",
        "See auth_spec section 3"
      ]
    }
  ],
  "note": "optional"
}
```

If no references found:

```json
{"file": "auth_spec.md", "findings": [], "note": "No references to this file found in other files"}
```

## Response

Return only the output filename.
