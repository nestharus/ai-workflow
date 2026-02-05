# No-Hardcoding / No-Regex Policy

## Scope

- Applies to: raw uncontrolled spec text at ingest (source markdown, PDFs converted to text, etc.)
- Does not apply to: system-owned output templates, IDs, stamps, JSON schemas, and generated artifacts

## Allowed

- Line/byte segmentation (newline boundaries, byte offsets)
- Sequence alignment / diffing on atom content
- Parsing of system-owned markers (templates/ directory)
- Validation of JSON outputs against schemas (templates/ directory)
- Deterministic ID allocation (DS/ALG registries)
- LLM-based local pattern inference (must output explicit atom mappings)

## Disallowed

- Regex/keyword rules used to infer meaning from uncontrolled input
- “Header detection” or “keyword spotting” as primary extraction logic
- Fixed phrase lists for semantic classification of requirements
- Rules that assume a universal spec format across files

## Required Mitigations

- If a heuristic is used as a fallback, it MUST:
  - be marked non-authoritative (confidence < 0.5 by policy)
  - route affected atoms to remainder unless confirmed by an auditor model
  - emit a GapElement describing the heuristic use and impacted atoms

## Enforcement Points

- Phase 0 intake: only atomization + hashing allowed
- Phase 1+ LLM steps: must reference atom IDs; all semantic structure comes from LLM outputs
- Validators: only parse system templates; never parse uncontrolled text
