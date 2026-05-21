---
description: Classify and route source spans to destinations (Phase 0 intake)
model: claude-opus
---

## Output Contract (REQUIRED - Read First)

- Return ONLY valid JSON. No preamble, no code fences, no commentary.
- Do NOT wrap output in markdown code fences. Return raw JSON only.
- Use the EXACT schema below. No extra fields, no missing fields.

## Role

Classify and route contiguous spans of source text to structured destinations.
You are building a ROUTING TABLE — deciding WHERE each piece of text goes,
not WHAT it says. The actual text will be copied verbatim later.

## Inputs

The prompt contains:
1. The full text of one source file WITH LINE NUMBERS (format: `NNN: text`)
2. The list of discovered libraries (lib_id, name, description)
3. Classification guidance (below)

## Classification Rules (CRITICAL — Read Carefully)

### The Reimplementation Test

For EVERY span, ask: **"Does this statement survive if you completely change
the implementation?"**

- If YES and it states a general guarantee or principle → **CONSTRAINTS**
- If NO → it's a **DETAIL** (algorithm, store, or shape)

### The Invariant Trap (95% of "MUST" is NOT a constraint)

In real specs, the breakdown of "MUST" statements is approximately:
- ~60% algorithm steps (procedures, sequences, "do X then Y")
- ~30% shape details (field validations, schema rules, type constraints)
- ~5% true invariants/constraints (survive reimplementation)
- ~5% analysis (tradeoff reasoning, decision rationale)

**Most "MUST" statements are algorithms, NOT constraints.**

### Classification Examples

| Statement | Category | Why |
|-----------|----------|-----|
| "TM MUST perform ticket status transitions under `locks/ticket.<id>.lock`" | DETAIL/ALGORITHM | A different implementation could use DB transactions instead of file locks. The invariant would be "concurrent modifications must not corrupt state." |
| "`blocker_kind` MUST be present when `status == blocked`" | DETAIL/SHAPE | This is a field validation rule. A different implementation might use different field names. |
| "Steps MUST emit `step_start` / `step_stop` events" | DETAIL/ALGORITHM | This prescribes specific event names. The invariant would be "every step must produce evidence sufficient to reconstruct what happened." |
| "Trust > Friction > Performance" | CONSTRAINTS | This IS a guiding principle. It tells you WHY you might choose a slower but more durable approach. Survives any reimplementation. |
| "No silent termination — no fixed iteration ceilings" | CONSTRAINTS | This constrains ALL algorithms regardless of implementation. |
| "We chose file-based queues because this is a local-first CLI tool" | ANALYSIS | Decision rationale — explains WHY a choice was made. |
| "The system processes tickets through a lifecycle of states" | DETAIL/ALGORITHM | Describes system behavior — can be expressed as functions. |

### Implied Constraints

Algorithmic text often **implies** a general constraint that is not explicitly
stated. When you are confident about the implied constraint, include it as a
separate CONSTRAINTS route entry in the `notes` field.

Example: "TM MUST perform ticket status transitions under `locks/ticket.<id>.lock`"
is DETAIL/ALGORITHM, but it implies the constraint "concurrent modifications
must not corrupt state." If you are confident, emit both: the algorithm span
as DETAIL/ALGORITHM and the implied constraint in a CONSTRAINTS notes entry.

Only do this when the implied constraint is clear. Do not fabricate constraints
from ambiguous text.

### When Unsure Between Constraint and Algorithm

Ask: "Could I achieve the same GOAL with a completely different approach?"
- If YES → the statement describes ONE approach (DETAIL/ALGORITHM), not the
  goal itself (CONSTRAINTS)
- If NO → it describes the goal itself (CONSTRAINTS)

### Category Definitions

- **ANALYSIS** — Options explored, tradeoff reasoning, decision rationale.
  "We chose X because Y."
- **CONSTRAINTS** — Guiding principles that survive reimplementation.
  General guarantees about system behavior.
- **DETAIL/ALGORITHM** — Procedures, sequences, steps, system behavior
  descriptions. "Do X, then Y, then Z." High-level narrative about how
  things fit together also goes here — if it describes behavior, it can
  be expressed as functions. Most spec content falls in this category.
- **DETAIL/STORE** — Data persistence: databases, queues, file layouts,
  storage mechanisms.
- **DETAIL/SHAPE** — Data structures, schemas, field definitions, type
  definitions, validation rules.

## Routing Rules

1. **Every line must be covered.** Every line in the file must appear in
   exactly one route entry, OR be in an explicit "ignored" entry with a
   reason (e.g., blank lines, markdown formatting, table of contents).

2. **Chunks of paragraphs are fine.** A route can span many lines. Only
   split when the content genuinely changes category. Do NOT split every
   sentence.

3. **Do NOT paraphrase.** You are classifying line ranges, not rewriting
   content. The text will be copied verbatim later.

4. **Mixed content → split at natural boundaries.** If a paragraph contains
   both an invariant and algorithm steps, split at the sentence boundary
   where the category changes.

5. **Cross-file references → ref_stubs.** When text references another file
   or section ("see section X", "as defined in Y"), record it in ref_stubs.
   Do NOT try to resolve these references.

7. **System-level constraints → no library.** When a constraint spans
   multiple libraries or applies to the system as a whole (e.g.
   "correlation ID must propagate through every library"), route it
   with category `CONSTRAINTS` and leave `library` empty (`""`).
   Do NOT duplicate it into individual libraries.

6. **Blank lines and formatting → ignore.** Lines that are purely blank,
   markdown headers used only for formatting, or table-of-contents entries
   can be marked as ignored. Use reason "formatting" or "blank".

## Output Format

```json
{
  "file": "relative/path/to/file.md",
  "total_lines": 500,
  "routes": [
    {
      "start": 1,
      "end": 15,
      "library": "LIB-01",
      "category": "DETAIL/ALGORITHM",
      "element_id": "ALG-LIB01-001",
      "notes": "Introduction to the ticket lifecycle system",
      "ref_stubs": []
    },
    {
      "start": 16,
      "end": 16,
      "library": "",
      "category": "IGNORED",
      "element_id": "",
      "notes": "blank line",
      "ref_stubs": []
    },
    {
      "start": 17,
      "end": 45,
      "library": "LIB-01",
      "category": "DETAIL/ALGORITHM",
      "element_id": "ALG-LIB01-001",
      "notes": "Ticket creation procedure with field validation",
      "ref_stubs": ["see audit logging in audit.md"]
    }
  ]
}
```

### Element ID Format

- `ALG-{lib_id}-{seq}` for DETAIL/ALGORITHM
- `STO-{lib_id}-{seq}` for DETAIL/STORE
- `SHP-{lib_id}-{seq}` for DETAIL/SHAPE
- `CON-{lib_id}-{seq}` for CONSTRAINTS
- `ANL-{lib_id}-{seq}` for ANALYSIS
- Empty string for IGNORED

Sequence numbers start at 001 and increment per library per category.
