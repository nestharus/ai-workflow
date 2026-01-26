---
description: Investigates orphans against entire project context
routing:
  - model: glm
---

Investigate orphan lines against the entire project to find any connection or meaning.

## Input

`orphan_lines`: Remaining orphan lines with line numbers
`project_context`: Summary of all entities, files, and relationships discovered
`output_file`: Where to write your findings

## Task

For each orphan line, investigate against the full project:

1. Does it relate to ANY known entity across all files?
2. Does it relate to ANY file as a whole?
3. Is it a project-wide concern or constraint?
4. Is it metadata about the project itself?
5. Or is it truly orphaned with no apparent connection?

## Output File Format

```json
{
  "investigations": [
    {
      "line": 567,
      "content": "All components must be containerized",
      "analysis": {
        "connection_found": true,
        "connection_type": "project-wide-constraint",
        "relates_to": ["all entities", "deployment"],
        "evidence": "Applies to every service entity discovered"
      }
    },
    {
      "line": 890,
      "content": "Thanks for reading",
      "analysis": {
        "connection_found": false,
        "connection_type": "none",
        "relates_to": [],
        "evidence": "Appears to be closing remark with no technical content"
      }
    }
  ],
  "project_wide_constraints": [
    {
      "constraint": "Containerization requirement",
      "lines": [567],
      "affects": "all entities"
    }
  ],
  "truly_orphaned": [
    {
      "line": 890,
      "content": "Thanks for reading",
      "reason": "No technical connection to project"
    }
  ]
}
```

## Response

Return only the output filename.
