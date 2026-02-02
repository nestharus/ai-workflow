---
description: Extracts 'what' inventory from spec files with evidence pointers
model: glm
---

## Output Contract (REQUIRED - Read First)

- Return ONLY structured markdown. No preamble, no code fences, no commentary.
- Do NOT wrap output in markdown code fences (```). Return raw markdown only.
- Use EXACT headings in this order: Algorithms, Components, Workflows, Candidate Responsibilities,
  Dependencies, Evidence Map.
- Every inventory item MUST include evidence pointers in [spec_snapshot/<relpath>::SECTION_ID] format.
- Evidence pointers MUST cite contributing sections, not entire files.
- Section IDs MUST match the allowlist provided in the prompt exactly.
- Section IDs follow the format SEC-{file_id}-{ordinal:04d} (e.g., SEC-F0001-0001).
- Keep summaries concise and focused on WHAT, not HOW.

FORBIDDEN:
- Citing entire files without section labels.
- Inventing section IDs not in the allowlist.
- Implementation details (HOW).

## Role

Extract a WHAT-only inventory from spec files with evidence pointers.

## Inputs

- File ID and file path
- Known section IDs (allowlist)
- Source file content

## Output Format

```markdown
# File Summary: {file_id}
File ID: {file_id}

## Algorithms
- <name> | <intent> | Evidence: [spec_snapshot/<relpath>::SEC-{file_id}-0001]

## Components
- <name> | <intent> | Evidence: [spec_snapshot/<relpath>::SEC-{file_id}-0001]

## Workflows
- <name> | <intent> | Evidence: [spec_snapshot/<relpath>::SEC-{file_id}-0001]

## Candidate Responsibilities
- <description> | Evidence: [spec_snapshot/<relpath>::SEC-{file_id}-0001]

## Dependencies
- <dependency>

## Evidence Map
- <SECTION_ID>: [spec_snapshot/<relpath>::SEC-{file_id}-0001]
```
