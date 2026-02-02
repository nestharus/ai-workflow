# Spec Refinement QA: Known Bad Signatures

Concrete output patterns ("signatures") that correlate with failed or low-quality agent steps.

These are intended to be used by the manual QA harness (see `scripts/spec_refinement/qa/`).

## Signatures

1) Derived pointers leaking into source-citation spaces
- Examples: `[charter::INTENT]`, `[libraries/LIB-0001/spec.md::...]`, `[runs/...::...]`

2) Architecture artifacts citing source files instead of libraries
- Example: `[F0001::REQS]` appearing in architecture proposal/selection/mapping output.

3) Runner file-pointer output instead of real content
- Example: `See \`ARCHITECTURE-MAPPING.md\` for details.`

4) Evidence mapper using summary headings as section IDs
- Example: `"relevant_sections": ["Components", "Workflows"]`

