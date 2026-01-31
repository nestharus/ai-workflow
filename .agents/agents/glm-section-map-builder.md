---
description: Generates human-readable section map from section spans. Evidence pointers will migrate to [spec_snapshot/<relpath>::SEC-...].
model: glm
---

## OUTPUT CONTRACT (REQUIRED - Read First)

- Return ONLY structured markdown. No preamble, no code fences, no commentary.
- Use EXACT heading: "# Section Map: {file_id}"
- Each section entry MUST include: section_id, line range, label, brief description.
- Format: "## {section_id}: {label} (Lines {start_line}-{end_line})"
- Brief description MUST be 1-2 sentences summarizing section content.
- Descriptions MUST focus on WHAT, not HOW.
- Sections MUST appear in sequential order.
- Outputs MUST reflect the provided sections_json exactly (no invented sections).
- NOTE: Section IDs are used for evidence pointers; current format [FILE_ID::SECTION] will migrate to
  [spec_snapshot/<relpath>::SEC-...] in a later phase.

FORBIDDEN:
- Missing section IDs.
- Incorrect line ranges.
- Invented sections.
- Any output outside the markdown structure.

## INPUT DATA

- File ID: {file_id}
- File path: {relpath}
- Sections JSON: {sections_json}
- Source file content: {content}

## OUTPUT FORMAT

```markdown
# Section Map: file_001

## SEC-file_001-0001: Introduction (Lines 1-12)
Summarizes the document purpose and scope for the spec file.

## SEC-file_001-0002: Requirements (Lines 13-44)
Lists core functional requirements and success criteria for the system.

## SEC-file_001-0003: Constraints (Lines 45-78)
Details technical constraints, limits, and non-functional considerations.
```
