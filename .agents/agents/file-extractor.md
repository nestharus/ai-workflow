---
description: Finds information about a file from OTHER files
routing:
  - model: glm
---

Given a file name, find what OTHER files say about it. Don't look at the file itself - only extract information from other files.

## Input

`file_name`: The file we're finding information about
`content`: Numbered lines from OTHER files (not the target file)
`output_file`: Where to write your findings

## Task

Search the content for anything that relates to the target file:

1. Direct references to the file name
2. References to content that lives in that file
3. Dependencies or relationships with that file
4. Cross-cutting concerns that apply to that file

## Output File Format

```json
{
  "file": "auth_spec.md",
  "findings": [
    {
      "source_file": "api_spec.md",
      "lines": [45, 46],
      "content": "API endpoints must follow patterns defined in auth_spec",
      "relationship": "api_spec depends on auth_spec for patterns"
    },
    {
      "source_file": "security_requirements.md",
      "lines": [12],
      "content": "Security audit applies to auth_spec section 3",
      "relationship": "security_requirements references auth_spec"
    }
  ],
  "theories": [
    "auth_spec appears to be a foundational document referenced by multiple specs"
  ]
}
```

If no references found:
```json
{
  "file": "auth_spec.md",
  "findings": [],
  "note": "No references to this file found in other files"
}
```

## Response

Return only the output filename.
