---
description: Finds what OTHER files say about a target file (evidence-only)
routing:
  - model: glm
---

Given a file name, find what OTHER files say about it. Do not look at the file itself.

## Input

- `file_name`: The file we're finding information about
- `content`: Numbered lines from OTHER files (not the target file)
- `output_file`: Where to write your findings

## Task

Search the content for anything that relates to the target file:

- Direct references to the file name
- Mentions of sections/symbols that clearly live in that file
- Clear statements of dependency or relationship with that file

Rules (critical):

- Evidence-only: each finding must include source line numbers + verbatim line text.
- Do not add theories or summarization.

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
