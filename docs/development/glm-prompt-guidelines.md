# GLM Prompt Guidelines (Cerebras 4.7)

These guidelines define the contract-first prompt structure for GLM agents. They are optimized for
Cerebras GLM 4.7 behavior and are REQUIRED for new GLM agents and prompt builders.

See also: docs/development/writing-agents.md

## Cerebras GLM 4.7 Characteristics

- High-throughput model with heightened attention to the beginning of the prompt.
- Instruction-following degrades as the prompt approaches max context.
- Contract rules must be front-loaded to avoid dilution by later content.

## Three-Part Prompt Template (REQUIRED)

All GLM prompts MUST follow this order:

1. Contract Section (lines 1-N)
   - All MUST/REQUIRED rules.
   - Output schema constraints.
   - Allowlists and forbidden patterns.
2. Content Section (lines N+1-M)
   - Input data only (charter, spec, file content, evidence blocks).
   - No rules or instructions here.
3. Output Format Section (lines M+1-end)
   - Schema definition and example output.
   - Output formatting requirements.

### Template Skeleton

```text
## OUTPUT CONTRACT (REQUIRED)

Return ONLY valid JSON. No preamble, no code fences.

REQUIRED SCHEMA:
{"field": "type", "list": ["type"]}

REQUIRED RULES:
- MUST include ...
- MUST use allowlist ...
- DO NOT ...

FORBIDDEN:
- ...

## INPUT DATA

[charter/spec/file content goes here]

## OUTPUT FORMAT

Example:
{"field": "value"}
```

## Imperative Language Rules

Use strong imperatives. Avoid passive language.

- Use: "Return ONLY", "MUST include", "Do NOT cite", "Every bullet MUST".
- Avoid: "should", "prefer", "try to", "ideally", "if possible".

## Breaking Down Complex Tasks

Use separate agents when:
- The prompt would exceed safe context after adding all contract rules.
- Outputs require different schemas or validation logic.
- The task mixes extraction and synthesis with different constraints.

Use sub-tasks within a single agent when:
- The same schema can handle all outputs.
- Contract rules remain stable across sub-steps.
- The input data is tightly coupled and must be processed together.

## Allowlist Patterns

Always provide explicit allowlists for IDs and labels.

- File IDs: "Valid file IDs for citations: file_001, file_002"
- Section labels: "Valid section labels for file_001: INTRO, REQS, CONSTRAINTS"
- Spec sections: "Valid spec sections: Intent, Boundaries, Requirements, Constraints"

Place allowlists in the Contract Section as REQUIRED RULES.

## Anti-Patterns (Forbidden)

- Mixing rules with content blocks.
- Burying constraints mid-prompt or at the end.
- Using passive language or suggestions.
- Repeating rules across sections (keep all rules in the Contract Section).

## Examples

### Before (mixed rules and content)

```text
Summarize the file.

File ID: file_001
Known Sections: INTRO, REQS

Rules:
- Use evidence pointers.

FILE CONTENT:
...
```

### After (contract-first)

```text
## OUTPUT CONTRACT (REQUIRED)

Return structured markdown with EXACT headings:
- Algorithms
- Components

REQUIRED RULES:
- Every item MUST include [FILE_ID::SECTION]
- Section labels MUST match allowlist: INTRO, REQS

FORBIDDEN:
- Invented sections

## INPUT DATA

File ID: file_001
Known Sections: INTRO, REQS

FILE CONTENT:
...

## OUTPUT FORMAT

# File Summary: file_001
## Algorithms
- <name> | <intent> | Evidence: [FILE_ID::SECTION]
```

## References

- General agent guidance: docs/development/writing-agents.md
- Follow Cerebras inference documentation patterns for contract-first prompts.
