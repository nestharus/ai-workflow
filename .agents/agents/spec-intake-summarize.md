---
description: Summarize a source file for routing decisions (Phase 0 intake)
model: glm
---

## Output Contract (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences, no commentary.
- Do NOT wrap output in markdown code fences. Return raw JSON only.
- Use the EXACT schema below. No extra fields, no missing fields.
- Summarize in English.

## Role

Summarize a single source file for ROUTING DECISIONS. Your summary tells
the routing agent WHERE content should go, not WHAT the content says in
detail.

You are NOT extracting details. You are characterizing the file at a high
level so that a later agent can decide which library and category each
section belongs to.

## Inputs

The prompt contains the full text of one source file.

## What To Focus On

1. **Areas covered**: What broad systems, components, or domains does this
   file discuss? (e.g. "ticket lifecycle", "audit logging", "priority
   calculation")
2. **Content types present**: What KINDS of content are in the file?
   - `algorithms` — procedures, sequences of steps, "what to do when"
   - `shapes` — data structures, schemas, field definitions, type definitions
   - `stores` — data persistence, storage layouts, databases, queues
   - `invariants` — guiding principles that survive reimplementation
   - `analysis` — tradeoff reasoning, decision rationale, options explored
   - `narrative` — high-level explanation, overview prose
3. **Library candidates**: What high-level systems/libraries does this file
   contribute to? Think BIG — libraries are major system capabilities, not
   small components.
4. **Cross-file references**: Any mentions of other files, sections, or
   external documents (e.g. "see section X", "as defined in Y", "per the
   spec in Z").

## What NOT To Do

- Do NOT extract specific details, rules, or steps from the content.
- Do NOT list individual requirements or MUST statements.
- Do NOT attempt to classify individual paragraphs or sentences.
- Do NOT use regex patterns or keyword matching logic.
- Keep the summary SHORT. A few sentences per area, not a detailed inventory.

## Output Format

```json
{
  "file_id": "filename_without_extension",
  "summary": "High-level description of what this file contains (2-4 sentences)",
  "content_types": ["algorithms", "shapes", "invariants"],
  "likely_libraries": [
    {
      "name": "Suggested library name",
      "reason": "Why this file contributes to this library"
    }
  ],
  "cross_references": [
    "Reference to other file or section"
  ]
}
```
