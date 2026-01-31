# Spec Refinement Validation

## Overview
Structural validation replaces brittle regex stripping by parsing evidence pointers and
checking file references against the workspace manifest. This ensures only valid
source file citations remain and prevents new, unknown derived-pointer patterns from
slipping through.

## Pointer Formats

Source file pointers (Phase 1 + Phase 4 allowed, Phase 6 stripped if present):
- `[F####::SECTION]`

Library pointers (Phase 6 allowed and validated separately):
- `[lib_###::charter.md]`
- `[lib_###::spec.md::SECTION]`

## Validation Flow
1. Parse evidence pointers with `EVIDENCE_POINTER_RE`.
2. Validate file references against the run file manifest.
3. Strip invalid source file pointers from content.
4. Re-render cleaned markdown with collapsed horizontal whitespace (newlines preserved).

## Applied Phases
- Phase 1 (summarization): remove invalid source file pointers before writing summaries.
- Phase 4 (spec building): remove invalid source file pointers before validating specs.
- Phase 6 (architecture): strip any accidental source file pointers from rationale/mapping;
  library citations remain and are validated structurally.

## Examples
Valid in Phase 1/4:
- `Built on request intake [F0001::INTRO]`

Invalid in Phase 1/4 (stripped):
- `Derived reference [charter::INTENT]`
- `Derived reference [libraries/lib_001/spec.md::REQS]`

Valid in Phase 6:
- `Component defined in spec [lib_001::spec.md::Requirements]`

Invalid in Phase 6 (stripped if present):
- `Source file reference [F0002::REQS]`
