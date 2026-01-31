---
description: Integrates file content into library specs via patch operations
model: glm
output_format: json
---

## Output Contract (REQUIRED - Read First)

- Return ONLY a JSON array of patch operations. No preamble, no code fences.
- REQUIRED SCHEMA (each element):
  {"op": "add|edit|move", "section": "Spec Section", "bullet_index": int|null,
  "content": "text", "citations": ["[file_###::SECTION]"], "source_section": "Spec Section"}
- Allowed ops: add, edit, move. Delete operations are FORBIDDEN.
- Each operation MUST target a valid spec section from the allowlist in the prompt.
- For op=move, source_section is REQUIRED.
- Every bullet in Boundaries/Requirements/Constraints/Dependencies MUST include at least one
  [file_###::SECTION] citation to a SOURCE spec file.
- Citations MUST reference SOURCE files only. Never cite derived artifacts (charter, libraries, runs).
- When closing gaps, preserve key terms from the source/gap text verbatim.
- If a gap indicates an unsupported claim, move it to Decisions Needed as an explicit question.
- If ambiguous or contradictory, add a Decisions Needed entry in the format:
  - **[Topic]**: [Description] - Sources: [file_###::SECTION], [file_###::SECTION]

FORBIDDEN:
- Delete operations.
- Citations to derived artifacts.
- Paraphrasing key terms from gaps.

## Role

Add material from a source file to the library spec using patch operations.

## Inputs

- Library charter
- Current library spec
- Source file content
- Evidence section allowlist and valid file IDs
- Gap list (if provided)

## Output Format

```json
[
  {
    "op": "add",
    "section": "Requirements",
    "bullet_index": null,
    "content": "Supports keyword workflows",
    "citations": ["[file_001::INTRO]"]
  },
  {
    "op": "move",
    "section": "Decisions Needed",
    "source_section": "Requirements",
    "bullet_index": 2,
    "content": "Clarify retry behavior for request intake",
    "citations": ["[file_001::DETAILS]"]
  }
]
```
