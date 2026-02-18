# Audit: Single-Layer Refinement Response vs Design Constraints

## Your Task

You are auditing a research response for divergences from established
design constraints, tradeoffs, and patterns. You are NOT proposing
alternative solutions. You are identifying WHERE the response diverges
from the principles and WHY that divergence is a problem.

For each divergence you find, state:
1. **What the response proposes** (specific quote or section reference)
2. **Which constraint/tradeoff/pattern it diverges from** (specific
   document + specific section)
3. **Why this is a divergence** (the mechanism of the conflict)
4. **Severity** — how much does this diverge from expectations?
   - CRITICAL: fundamentally contradicts a core principle
   - SIGNIFICANT: violates a constraint in a way that would cause
     problems in practice
   - MINOR: tension with a principle but not necessarily wrong

Do NOT:
- Propose alternative solutions
- Try to fix the divergences
- Argue that the divergences are acceptable
- Add new requirements not in the constraints

## Audit Direction (from Opus analysis)

The following 8 divergence signals have been identified. For each one,
find the SPECIFIC text in the response that diverges and the SPECIFIC
constraint text it conflicts with. Also look for divergences NOT in this
list — these are starting points, not exhaustive.

### Signal 1: More extraction, not less
The response proposes extracting edge roles, projection types, algorithm
boundaries, cross-file tokens, and fingerprints. This is MORE extraction
than the current PIN system. Check against C01 "Route information, don't
extract it" and Design Principle #3 "Routing over extraction."

### Signal 2: Separate mechanical extraction passes
The response proposes 4-5 separate extraction steps (adjacency inference,
cross-file resolution, edge role classification, boundary detection,
fingerprint computation). Check against Design Principle #10 "LLM does
work during its actual task — no separate mechanical extraction step."

### Signal 3: Massive upfront schema commitment
Detailed node schemas, edge schemas, fingerprint algorithms,
GraphConstraint types — all without eval evidence. Check against C00
"Plan only as far as current understanding reaches" and "Require evidence
before changing strategy."

### Signal 4: Single graph = tight coupling
Everything depends on one annotated adjacency graph. Check against C04
"Give each agent only the context it needs" and coupling concerns.

### Signal 5: Mixed scopes
Logical and structural edges in one graph representation. Check against
C05 "Avoid mixing scopes in a single pass."

### Signal 6: PIN retirement is PIN renaming
The response's projection_type annotations are functionally identical to
PinFunction ProjectionType. Check whether the response actually retires
the concept or just renames it.

### Signal 7: Fingerprint stability depends on LLM
Convergence relies on LLM-inferred graph fingerprints. Check against C00
"Don't treat unverified output as knowledge" and C03 "Surface errors
immediately."

### Signal 8: Source authority with single codebase
Architecture refactoring changes code which changes the graph which could
invalidate algorithm checkpoints. Check against C02 "Don't invest in
derived work while the source is changing."

## Files to Read

Read these files in this order:

1. `.tasks/plans/spec manager/.research/single-layer-refinement/response.md`
   — THE RESPONSE being audited

2. `.tasks/plans/spec manager/design/constraints/00_PROPORTIONAL_COMMITMENT.md`
3. `.tasks/plans/spec manager/design/constraints/01_INFORMATION_PERMANENCE.md`
4. `.tasks/plans/spec manager/design/constraints/02_SOURCE_AUTHORITY.md`
5. `.tasks/plans/spec manager/design/constraints/03_ERROR_AMPLIFICATION.md`
6. `.tasks/plans/spec manager/design/constraints/04_COUPLING.md`
7. `.tasks/plans/spec manager/design/constraints/05_FRACTAL_SCOPING.md`
8. `.tasks/plans/spec manager/design/constraints/06_STRUCTURED_ERROR_CONTRACTS.md`
9. `.tasks/plans/spec manager/design/constraints/07_EXPLICIT_SERIALIZATION_CONTRACTS.md`
10. `.tasks/plans/spec manager/design/constraints/08_STRUCTURED_DIAGNOSTICS.md`
11. `.tasks/plans/spec manager/design/constraints/10_CANONICAL_IDENTITY_SCHEMES.md`
12. `.tasks/plans/spec manager/design/constraints/11_PATH_CANONICALIZATION.md`
13. `.tasks/plans/spec manager/design/TRADEOFFS.md`
14. `.tasks/plans/spec manager/design/patterns/CORE_PATTERNS.md`
15. `.tasks/plans/spec manager/LONG_TERM_GOALS.md`
    — Read the "When introducing anything new" section (12 design principles)

## Output Format

Produce a numbered list of divergences. For each:

```
## Divergence N: [short title]

**Response text**: [quote or section reference from response.md]
**Constraint**: [document name] → [section name] → [specific text]
**Conflict**: [explanation of why these conflict]
**Severity**: CRITICAL | SIGNIFICANT | MINOR
```

After all divergences, include a summary section:
- Total divergences by severity
- The 3 most fundamental divergences (the ones that, if not addressed,
  would make the solution incompatible with the design philosophy)
