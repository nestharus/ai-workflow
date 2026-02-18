# Research Refinement #2: Complete Single-Layer Design Proposal

## Background

This is the third prompt in a research sequence. The first turn explored whether the three-layer promotion pipeline could
collapse to a single layer. The first response diverged into building a
rich graph extraction system — more machinery, not less. The second turn
redirected back to evaluating existing tools. The second response was
much better aligned — it correctly treats the call graph as a routing hint, proposes
simple phase iteration, and achieves dramatic net simplification.

However, the second response's routing mechanism — placing comments in code
(PDD-TODO markers, PDD-PATH anchors) — is wrong:

- **Spec comments dissolve.** They are consumed by implementation and
  disappear. They are not routing infrastructure.
- **Comments cannot be verified or tested.** Removing a marker doesn't
  prove its intent was satisfied. Not evidence-based convergence.
- **PDD-PATH is a pin by another name.** If the LLM can locate wiring
  points during Phase C (which the response says it can), pre-placed
  markers are redundant.

The fix: **routing by structural pattern matching** — shapes over call
graphs that can be matched, verified, and tested. Not markers in code.
Matching over pinning.

Look at the `design/` folder in context2.zip. The `routing/` summaries
are concrete examples of shapes — structural descriptions of what a
module IS, its surface APIs, dependencies, and consumers. External to
code. Matchable against actual structure. This is how we already manage
spec manager itself. The single-layer system should work the same way.

---

## What We Need

Produce a **complete, self-contained design proposal** for single-layer
iterative refinement with shape-based routing. This replaces all
previous deliverable lists. The proposal is a unified design document —
not a set of answers to questions from previous turns.

The design must account for:

- What the existing call graph can and cannot do, and how shapes
  extend its utility without adding extraction machinery
- How shapes work concretely — what they look like at different
  granularities, how they are derived, stored, updated, and matched
  against actual call graph structure
- How shapes handle non-call relationships (events, DI, middleware)
  without falling back to code markers or pinning
- How shape matching drives routing (change detection, impact
  propagation, work item generation) and convergence (what "all shapes
  satisfied" means, why it is verifiable and testable)
- How the phase mechanism works end-to-end — Build, Algorithm
  Refinement, Architecture Refinement, Quality Refinement — including
  phase ordering, interference prevention, and explicit iteration bounds
- What the pattern library is, what goes in it, how it relates to the
  spec and to the design/ folder model in context2.zip
- Where the extraction boundary falls — which parts of shape derivation
  and matching are deterministic vs LLM-based, and how shapes avoid
  becoming LLM-inferred authority
- How existing compliance gates reorganize for a single layer
- What happens to demotion in a single-layer system
- The complete net simplification — what is eliminated vs introduced,
  with concrete module and concept inventories
- An eval proposal — what experiment validates this works, what success
  and failure look like

---

## Constraints

All constraints from context.zip (C00-C11, TRADEOFFS.md, CORE_PATTERNS.md,
LONG_TERM_GOALS.md design principles) apply. Additionally:

1. **No code markers as routing infrastructure.** Routing is external
   pattern matching, not searching for markers in code.
2. **Convergence must be verifiable and testable.** Not "no comments
   remain."
3. **Shapes must be lighter than pins.** If the pattern library is as
   complex as the PIN system, the simplification fails.
4. **Matching over pinning.** Implementations can change HOW they
   satisfy a shape without breaking routing.
5. **Include explicit iteration bounds.** Not "repeat until convergence"
   without limits.

---

## Context

**context.zip** — codebase files, design/constraints/, design/patterns/,
design/TRADEOFFS.md.

**context2.zip** — design/README.md, design/routing/ (20 per-module
structural summaries — **these are concrete shape examples**),
design/overview/ (system architecture, pipeline, external boundaries).
