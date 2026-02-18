# Audit Results: Refined Single-Layer Response (response2.md)

## Audit Process
- **Direction**: Opus (identified 5 divergence signals)
- **Execution**: Codex High2 (validated all 5, found 1 additional)
- **Interpretation**: Opus (this document)

## Divergence Summary

| # | Title | Severity | Constraint |
|---|-------|----------|------------|
| 1 | PDD-PATH as residual bridge machinery | SIGNIFICANT | DP#7 + DP#10 |
| 2 | Phase B as separate call graph step | MINOR | DP#10 |
| 3 | Strategy change without eval evidence | CRITICAL | C00 |
| 4 | Parallel comment systems for routing truth | SIGNIFICANT | C02 |
| 5 | Open-ended iteration without bounds | MINOR | C04 |
| 6 | PDD-PATH identifiers are ad-hoc labels | MINOR | C10 |

**Totals**: 1 CRITICAL, 2 SIGNIFICANT, 3 MINOR
**Comparison**: Response1 had 3 CRITICAL, 7 SIGNIFICANT. Dramatic improvement.

## Assessment

Response2 is **broadly aligned in intent and mostly aligned operationally**.
The core mechanism — call graph as routing hint, deterministic convergence,
simple phase iteration, constraints from spec not extraction — is correct.

However, the response's proposed routing mechanism (code comments as TODO
markers) has a fundamental problem that the audit did not initially flag
because it was in the constraints' blind spot: **spec comments dissolve**.

### The comment problem

Response2 proposes PDD-TODO markers and PDD-PATH anchors as the routing
mechanism. But:

1. **Spec comments are consumed by implementation and disappear** — they
   are not durable routing markers. Using them as routing infrastructure
   abuses their purpose.

2. **Comments cannot be verified or tested** — the convergence criterion
   "no TODO markers remain" depends on literal search. But removing a
   marker doesn't prove its intent was satisfied. This is the opposite
   of evidence-based convergence.

3. **Three parallel comment systems** (spec comments, PDD-TODO, PDD-PATH)
   violates C02 and creates ambiguity about what constitutes routing truth.

### What response2 got right

1. Call graph as routing hint, not authority
2. Deterministic convergence direction (tests + structural checks)
3. Simple phase mechanism (only Build edits, refiners only route)
4. Honest limits assessment of existing call graph
5. Net simplification is dramatic
6. Constraints originate in spec, not code extraction
7. Phase-scoped authority preserves sequential stabilization

### What needs to change

The routing mechanism needs to move from **markers in code** to
**structural pattern matching** — shapes over call graphs that can be
matched, verified, and tested. This follows the existing routing
philosophy (classify-and-dispatch, matching, not pinning) and is
consistent with how we already manage spec manager itself via the
design/ folder (constraints, patterns, routing summaries).
