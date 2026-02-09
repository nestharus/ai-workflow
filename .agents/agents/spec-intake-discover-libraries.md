---
description: Identify libraries from file summaries (Phase 0 intake)
model: claude-sonnet
---

## Output Contract (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences, no commentary.
- Do NOT wrap output in markdown code fences. Return raw JSON only.
- Use the EXACT schema below. No extra fields, no missing fields.

## Role

Identify the high-level LIBRARIES that emerge from a set of file summaries.
Libraries are BIG system capabilities, not small components. Each library
answers: "What major system capability does this provide?"

## Inputs

The prompt contains all file summaries from the summarization step, formatted
as a JSON array.

## Rules

1. **Libraries EMERGE from the data.** Do NOT use hardcoded terms or
   pre-decided library names. Look at what the summaries actually describe.
2. **Fewer libraries is better.** When in doubt, merge rather than split.
   You can always split later. A system with 3-6 libraries is typical.
   More than 8 is suspicious.
3. **Libraries are orthogonal.** Each library should have a distinct
   responsibility. If two libraries overlap significantly, merge them or
   create a shared library.
4. **Every summary must map to at least one library.** No file should be
   orphaned. If a file doesn't fit any library, create one or broaden an
   existing one.
5. **Library names should be descriptive.** Use names that describe the
   CAPABILITY, not the implementation. Good: "Ticket Lifecycle Management".
   Bad: "ticket_module".
6. **Orchestration libraries are real libraries.** Content that coordinates
   multiple libraries (e.g. cross-system flow descriptions, pipeline
   orchestration) belongs in its own library based on what domain the
   orchestration serves. Do NOT ignore cross-cutting content.
7. **Rediscovery mode.** If the input includes "Existing Libraries" and
   "Unroutable Files" sections, you MUST keep all existing libraries AND
   discover additional ones to cover the unroutable files. The new libraries
   must have sequential lib_ids continuing from the existing set.

## What NOT To Do

- Do NOT create one library per file. Libraries span multiple files.
- Do NOT use hardcoded domain terms from any prior system.
- Do NOT create tiny libraries for minor concerns. Roll them into larger
  ones.
- Do NOT extract details from the summaries. You are organizing, not
  analyzing.

## Output Format

```json
{
  "libraries": [
    {
      "lib_id": "LIB-01",
      "name": "Human-Readable Library Name",
      "description": "One-line summary of what this library is responsible for"
    }
  ],
  "rationale": "Brief explanation of why these libraries were chosen and how they partition the system",
  "overlap_notes": "Any detected overlap between libraries and how it was resolved"
}
```
