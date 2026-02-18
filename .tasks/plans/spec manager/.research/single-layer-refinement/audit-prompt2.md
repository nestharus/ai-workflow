# Audit: Refined Single-Layer Response vs Design Constraints

## Your Task

You are auditing a REFINED research response (response2.md) for
divergences from established design constraints, tradeoffs, and patterns.
This is the second response — it was produced after the first response
was found to have 10 divergences (3 CRITICAL). The refined response is
expected to be much better aligned, but may still have issues.

You are NOT proposing alternative solutions. You are identifying WHERE
the response diverges from the principles and WHY that divergence is a
problem.

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

The following 5 divergence signals have been identified. For each one,
find the SPECIFIC text in the response that diverges and the SPECIFIC
constraint text it conflicts with. Also look for divergences NOT in this
list — these are starting points, not exhaustive.

### Signal 1: PDD-PATH as residual pinning

Section 6 proposes `PDD-PATH: SETTLEMENT_COMPLETE_NOTIFIES_RISK_ENGINE`
markers for non-call wiring points (event subscriptions, middleware
ordering, DI wiring, framework registration). But Phase C in section 3
already says: "Locate the boundary/orchestrator functions where those
paths should be realized (usually explicit in code structure + component
boundaries; call graph is only a helper)."

If the LLM can find those locations during Phase C (its actual task),
PDD-PATH may be unnecessary machinery — a pin by another name. Check
against Design Principle #7 "Pins as the bridge" (pins bridge layers;
single-layer has no layers to bridge) and Design Principle #10 "LLM does
work during its actual task" (if the LLM already locates wiring points
in Phase C, pre-placed anchors are redundant mechanical markers).

### Signal 2: Phase B re-runs call graph as a separate step

Section 3 says Phase B: "Re-run call graph on changed files (as a hint
map). If an algorithm change likely impacts neighbors, add new TODO/spec
notes to the impacted functions/callsites."

This is a separate mechanical pass outside the primary implementation
task. Check against Design Principle #10: "LLM does work during its
actual task — there is no separate mechanical extraction step. If the
LLM already understands the code while doing its job, a separate parsing
step is redundant."

Counter-argument: the existing system already runs call graphs, and the
response treats it as routing hints not extraction. Evaluate whether
this structural tension with DP#10 is a real divergence or an acceptable
use of existing infrastructure.

### Signal 3: PDD-TODO three-category typing creates scope classification

Section 4 proposes `PDD-TODO[behavior]`, `PDD-TODO[wiring]`,
`PDD-TODO[refactor]` — three categories mapping 1:1 to phases B, C, D.
This is a classification system for scoping work items.

Check whether this recreates layer-style scope separation under a
different format. Also check against C05 "Avoid mixing scopes in a
single pass" — is this the mechanism for scope separation? Is it
sufficient? Does it conflict with anything?

### Signal 4: No eval evidence proposed

The refinement prompt said "Do not commit to schemas without evidence"
and the response avoids detailed schemas. But it also doesn't propose
any specific evaluations that would validate the single-layer approach
works before committing to it. Check against C00 "Require evidence
before changing strategy" — adopting single-layer IS a strategy change.

### Signal 5: PDD-PATH + PDD-TODO + existing spec comments = three comment systems

The response proposes PDD-PATH markers (section 6), PDD-TODO markers
(section 4), and references the existing spec comment system (section 4:
"TODO-routing can be as simple as: Phase B/C/D produce new spec comments
(or PDD-TODO comments)").

This is potentially three comment systems in code. Check against C02
"Don't maintain parallel representations of the same truth" — are
PDD-PATH, PDD-TODO, and spec comments three representations of routing
truth? Or are they genuinely distinct (spec comments = implementation
intent, PDD-TODO = routing signal, PDD-PATH = wiring anchor)?

## Files to Read

Read these files in this order:

1. `.tasks/plans/spec manager/.research/single-layer-refinement/response2.md`
   — THE RESPONSE being audited

2. `.tasks/plans/spec manager/.research/single-layer-refinement/refinement-prompt.md`
   — THE PROMPT that produced the response

3. `.tasks/plans/spec manager/design/constraints/00_PROPORTIONAL_COMMITMENT.md`
4. `.tasks/plans/spec manager/design/constraints/01_INFORMATION_PERMANENCE.md`
5. `.tasks/plans/spec manager/design/constraints/02_SOURCE_AUTHORITY.md`
6. `.tasks/plans/spec manager/design/constraints/03_ERROR_AMPLIFICATION.md`
7. `.tasks/plans/spec manager/design/constraints/04_COUPLING.md`
8. `.tasks/plans/spec manager/design/constraints/05_FRACTAL_SCOPING.md`
9. `.tasks/plans/spec manager/design/constraints/06_STRUCTURED_ERROR_CONTRACTS.md`
10. `.tasks/plans/spec manager/design/constraints/07_EXPLICIT_SERIALIZATION_CONTRACTS.md`
11. `.tasks/plans/spec manager/design/constraints/08_STRUCTURED_DIAGNOSTICS.md`
12. `.tasks/plans/spec manager/design/constraints/10_CANONICAL_IDENTITY_SCHEMES.md`
13. `.tasks/plans/spec manager/design/constraints/11_PATH_CANONICALIZATION.md`
14. `.tasks/plans/spec manager/design/TRADEOFFS.md`
15. `.tasks/plans/spec manager/design/patterns/CORE_PATTERNS.md`
16. `.tasks/plans/spec manager/LONG_TERM_GOALS.md`
    — Read the "When introducing anything new" section (12 design principles)

## Output Format

Produce a numbered list of divergences. For each:

```
## Divergence N: [short title]

**Response text**: [quote or section reference from response2.md]
**Constraint**: [document name] → [section name] → [specific text]
**Conflict**: [explanation of why these conflict]
**Severity**: CRITICAL | SIGNIFICANT | MINOR
```

After all divergences, include a summary section:
- Total divergences by severity
- The 3 most fundamental divergences (the ones that, if not addressed,
  would make the solution incompatible with the design philosophy)
- An assessment: is this response broadly aligned or fundamentally
  divergent from the constraints?
