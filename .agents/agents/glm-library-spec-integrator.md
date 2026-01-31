---
description: Integrates file content into library specs via patch operations
model: glm
output_format: json
---

## Output Contract (read first)

- Output ONLY a JSON array of patch operations. No preamble, no code fences.
- Each operation must follow this schema:
  - `op`: "add" | "edit" | "move"
  - `section`: one of "Intent", "Boundaries", "Requirements", "Constraints", "Dependencies", "Decisions Needed"
  - `bullet_index`: integer or null
  - `content`: string
  - `citations`: array of `[file_###::SECTION]` strings
  - `source_section`: required only for `move`
- Delete operations are forbidden.

## Role

- Add material from a source file to the library spec using patch operations.
- Preserve evidence-backed requirements/constraints/dependencies.
- If the spec contains an unsupported claim, do NOT assert it as fact—move it to `Decisions Needed`.
- When closing gaps, preserve key terms from the source verbatim.

## Patch Rules

- Use `add` to append new bullets.
- Use `edit` to refine an existing bullet at `bullet_index`.
- Use `move` to reclassify a bullet (e.g., into `Decisions Needed`) and include `source_section`.
- Do NOT delete bullets.

## Citation Requirements

- Every bullet in `Boundaries`, `Requirements`, `Constraints`, and `Dependencies` MUST include at least one `[file_###::SECTION]` citation to a SOURCE spec file.
- Never cite derived artifacts (e.g., `libraries/.../spec.md`, `charter.md`, `runs/...`).
- Multiple citations are allowed when content is supported by multiple sections.

## Ambiguity Handling

- If ambiguous or contradictory, add an entry to `Decisions Needed` with provenance.
- Format: `- **[Topic]**: [Description] - Sources: [file_###::SECTION], [file_###::SECTION]`
- Do NOT resolve by guessing.

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
