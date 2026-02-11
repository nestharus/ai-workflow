# Research: Designing L2 (Architecture) and L3 (Code Quality) Layer Operations

## What I Need From You

I need the concrete design for how the PromotionLoop operates at L2 (Architecture) and L3 (Code Quality) layers. L1 (Code-as-Spec) is fully working — gaps are spec comments, implementation fills function bodies, compliance gates check for remaining stubs/comments/tests. But L2 and L3 have never been run. I need you to define exactly what each PromotionLoop step does at each layer, what the reviewers look like, and how findings become DemotionTickets that flow back down.

Key constraint from the user: **Reviews cannot be tied to a language or a library.** If we have language-specific or library-specific review rules, those would be "evolutionary strategies" — patterns discovered and refined over time — matched against and used alongside other reviewers. The core review system must be language-agnostic.

---

## What Exists and Works

### L1 (Code-as-Spec) — FULLY EVALUATED

The PromotionLoop at L1 runs 10 steps per slice:

```text
COLLECT → GAP → PLAN → IMPLEMENT → UNDER_SPEC → ANALYZE → PROMOTE → INTEGRATE → VERIFY → ALIGN → DONE?
```

At L1:
- **Slice** = a library (vertical concern boundary)
- **Gap** = spec comments not yet implemented (detected by P3 compliance)
- **Implementation** = LLM writes function bodies from spec comments (P9)
- **Compliance gates**: NO_REMAINING_COMMENTS, NO_STUB_FUNCTIONS, ALL_TESTS_PASS, CALL_GRAPH_CONNECTED, STORE_MONOGAMY
- **Verify** = P6 cross-library connections + P7 lineage traces
- **Align** = POWER alignment check (drift/reward hacking)

### Layer Skeleton Types (from WORKFLOW_ANALYSIS.md)

| Layer | Skeleton Type | Granularity |
|-------|--------------|-------------|
| L1 (Code-as-Spec) | **Libraries** | Concern boundaries (vertical slices) |
| L2 (Architecture) | **Architectural components** | Services, events, middleware |
| L3 (Clean Code) | **Invariants on algorithm components** | Fine-grained function chunks |

### Existing Refinement Methods (in pdd_lifecycle.py)

- `_library_refinement()` — runs at L1 entry/exit (validates library boundaries, overlap, coverage)
- `_architectural_refinement()` — runs at L1→L2 transition and L2 entry/exit. Currently: single LLM call to `opus-architecture-proposer`, parses JSON with proposals, emits DemotionTickets for violations.
- `_code_quality_refinement()` — runs at L2→L3 transition and L3 entry/exit. Currently: 4 `chatgpt-*-reviewer` agents (clarity, completeness, consistency, correctness) per file, emits DemotionTickets for logic/architecture findings.

### VerifyStep — STUB

`VerifyStep.run()` in promotion_loop.py (lines 628-633) currently returns `StepResult(status="OK")` without doing anything. It needs a real implementation.

### Existing Agent Definitions

- `opus-architecture-proposer.md` — architecture proposals
- `chatgpt-clarity-reviewer.md` — code quality (clarity)
- `chatgpt-completeness-reviewer.md` — code quality (completeness)
- `chatgpt-consistency-reviewer.md` — code quality (consistency)
- `chatgpt-correctness-reviewer.md` — code quality (correctness)
- `opus-alignment-checker.md` — POWER alignment (drift/reward hacking)

### Promotion Model (from WORKFLOW_ANALYSIS.md)

```text
Layer 1 → PROMOTION 2 → Layer 2 → PROMOTION 3 → Layer 3
```

- **Architecture (L2)** comes into existence when atoms are promoted via pins
- **Clean code (L3)** emerges from quality reviews identifying specific locations
- **You never edit architecture or clean code directly** — they emerge from promotion
- **Routing is only needed at L1** — upper layers know what to edit because the process identifies targets

### Key Design Principles (from LONG_TERM_GOALS.md)

1. No extraction (route instead)
2. No language-specific parsing (LLM only)
3. Graph operations not code operations
4. Dynamic structures not rigid types
5. LLM does work during its task (no redundant mechanical steps)
6. Promotion not direct editing

---

## Reference Patterns (from .ai/docs/)

These are patterns from a reference codebase. Not all apply directly, but the review patterns are relevant.

### Quality Gate Loop Pattern
Iterative review-patch-re-review until ALL reviewers pass. On loop exhaustion → escalation (audit or human). A patcher agent fixes issues between iterations.

### Review Orchestration (from reference docs)
```text
Artifact → Parallel Reviewers → Gate (aggregate PASS/FAIL)
  → PASS → Reviewed Artifact
  → FAIL → Patcher → loop back to reviewers
```
- Multiple reviewers evaluate artifact concurrently
- All-pass requirement before proceeding
- Patcher can auto-fix certain categories
- Loop limit prevents infinite cycling

### Two Verification Modes (Domain 7)
1. **Rule-based artifact review**: enforce best practices, conventions, patterns
2. **Conformance/drift review**: compare spec→artifact (missing items, extra items, mismatched items)

### Code Reviewer Categories (reference — language-specific examples)
- **CODE-A**: Architecture (layered compliance, dependency direction, separation of concerns, port/adapter, circular deps, domain purity, service boundaries, config injection)
- **CODE-B**: Anatomical (bool params, nested depth, composition, router pattern, guard clauses, side effect isolation, traversal extraction)
- **CODE-E**: Bug/Error (exception specificity, null safety, boundary conditions, resource cleanup, race conditions, type confusion, injection vulnerabilities)
- **CODE-S**: Style (naming, function length, parameter count, docstrings, imports, type annotations, dead code, formatting)

**Important**: These specific rules (PEP8 naming, Python-specific patterns) are examples of evolutionary strategies. The core review system should express rules in language-agnostic terms, with language-specific instantiation as a separate concern.

### Progressive Automation with HITL
Strategy always needs human approval. Plan/artifact can be auto-approved after first integration. Convert repeated human approvals into permanent heuristics. This is how evolutionary strategies get created.

### Investigator Agent (Repair/Remediation — from .ai/agents/shared/)
When verification fails, the Investigator reproduces the failure in an isolated worktree, fixes the artifact (and tests if needed) until it works, then reports root cause and patch. Key properties:
- Works in isolation (git worktree, never touches main repo)
- Produces root cause analysis + patch summary + diff
- Escalates if can't fix (fundamental architectural issue, missing deps, ambiguous criteria)
- "Fix pragmatically — modify code AND tests if needed to align them"
- "Preserve intent — don't change what the code is supposed to do (per plan)"
- Decision logic: modify code when logic/bug/arch issue, modify tests when test assumptions wrong, escalate when fundamental plan revision needed

### Pipeline Oversight Enforcer (Governance — from .ai/agents/shared/)
The enforcer verifies receipts exist at every stage gate, detects decision injection/trickery in artifacts, and flags undocumented deviations. Key properties:
- Receipt verification: every agent must produce a receipt, missing = FAIL
- Decision injection detection: agents embedding unauthorized decisions in artifacts
- Deviation accountability: all deviations must be documented with justification
- PASS/WARN/FAIL gate enforcement — pipeline MUST NOT proceed on FAIL
- "Only the enforcer can clear justified deviations — trust no other agent"
- Detects: inline decision overrides, log output trickery, comment-based instruction injection, authority claims without receipts, scope expansion, test/validation skipping

---

## Questions for L2 (Architecture Layer)

### Q1: What is a "gap" at L2?

At L1, a gap is a spec comment without implementation. At L2, architecture emerges from pin promotion. What does the PromotionLoop's GapExplorationStep look for at L2?

Options I see:
- a) Missing architectural wiring — atoms exist but aren't assembled into services/events
- b) Service decomposition issues — too many atoms in one service, or a service that's too thin
- c) Missing integration points — two services that need to communicate but don't
- d) Some combination

What gap detection mechanism should run? Something analogous to P3 compliance scanning but for architectural completeness?

### Q2: What does "implement" mean at L2?

At L1, implement = write function bodies. At L2, the WORKFLOW_ANALYSIS says "you never edit architecture directly — it emerges from promotion." But the PromotionLoop has an IMPLEMENT step.

Does L2's ImplementStep:
- a) Assemble services/events/middleware from promoted atoms (the architectural implementation agent)?
- b) Write integration code (glue between services, event handlers, middleware chains)?
- c) Nothing — L2 only runs analysis/verification, not implementation?
- d) Something else?

How does this interact with the fact that atoms come up from L1 via pins? Does L2 implementation mean "decide how to wire pins into a service topology"?

### Q3: What compliance gates apply at L2?

At L1 we have: NO_REMAINING_COMMENTS, NO_STUB_FUNCTIONS, ALL_TESTS_PASS, CALL_GRAPH_CONNECTED, STORE_MONOGAMY.

At L2, what gates enforce quality? From WORKFLOW_ANALYSIS.md:
- `NO_INLINED_ATOM_LOGIC` — enforces that business logic lives in atoms (L1), not in services
- `FUNCTION_RECOMPOSITION` — architectural functions properly compose atoms

What else? Should there be equivalents to L1 gates? For example:
- Service connectivity (all services reachable)?
- Event completeness (all events have at least one handler)?
- Middleware ordering (correct chain)?
- Integration test pass?

### Q4: What does VerifyStep do at L2?

Currently a stub. At L1, Verify should run P6 (cross-library connections) and P7 (lineage traces). What does verification look like at L2?

Options:
- a) All promoted atoms are exercised by architectural code
- b) Service graph is connected (no orphan services)
- c) All pins from L1 are consumed in L2
- d) Architectural drift check (does the architecture match the proposals from architectural refinement)?
- e) Pipeline Oversight Enforcer gate (receipt verification + trickery detection)?

Note: The Investigator agent pattern (`.ai/agents/shared/investigator.md`) is specifically for **workflow repair** — invoked when verification/CI fails, not part of the verification step itself. It would inform the recovery flow (what happens AFTER VerifyStep or IntegrateStep fails), not the verification logic.

### Q5: What are L2 slices?

Currently `_discover_slices("l2")` wraps each library as `arch-{lib_name}`. Should a slice at L2 be:
- a) One slice per library (current implementation)
- b) One slice per service (after architectural decomposition)
- c) One slice per architectural component type (services, events, middleware each)
- d) Something else entirely

The slice definition determines what runs in parallel and what the PromotionLoop iterates on.

### Q6: How does L2 architectural refinement become language-agnostic reviews?

The reference docs have CODE-A rules (layered compliance, dependency direction, etc.) but those reference Python imports and framework-specific patterns.

For our system:
- What are the language-agnostic equivalents of architectural review rules?
- How do evolutionary strategies (language-specific patterns discovered over time) layer on top?
- Should the architecture review use the same "LLM as judge" pattern that drives our other analysis, or should it have structured rules?

---

## Questions for L3 (Code Quality Layer)

### Q7: What is a "gap" at L3?

At L3, the input is working but messy architecture. Quality reviewers identify findings. Does a "gap" at L3 mean:
- a) A reviewer finding (violation of a quality rule)?
- b) A function/file that hasn't been reviewed yet?
- c) A finding that hasn't been addressed (patched)?
- d) Some combination?

### Q8: What does "implement" mean at L3?

At L3, implementation should be refactoring — cleaning up code without changing behavior. But WORKFLOW_ANALYSIS says:

> If refactoring touches logic → demotion (see below)

So L3 implementation = refactoring. But:
- What agent does the refactoring?
- How does it know WHAT to refactor? (From reviewer findings?)
- How does it verify behavior isn't changed? (Test regression?)
- What happens when a "quality fix" requires a logic change?

### Q9: What compliance gates apply at L3?

At L3, what gates must pass for a function/file to be promoted?

From WORKFLOW_ANALYSIS: "N code quality reviewers (each enforces different standards): Clarity, completeness, consistency, correctness." Plus "Collect findings → Refactor → If logic touched → demotion → Re-review until quality standards pass."

But the user said reviews must be language-agnostic. So:
- What are the language-agnostic dimensions of code quality?
- How does a "clarity" or "consistency" reviewer work without language-specific rules?
- Are the 4 current chatgpt reviewers (clarity/completeness/consistency/correctness) the right decomposition, or should we use something closer to the reference doc categories (Architecture/Anatomical/Bug/Style)?

### Q10: What does VerifyStep do at L3?

At L3, verification presumably means:
- All reviewer findings addressed?
- No behavior regressions (all tests still pass)?
- Something else?

### Q11: What are L3 slices?

Currently `_discover_slices("l3")` creates one slice per `.py` file. Should it be:
- a) One slice per file (current)
- b) One slice per module/package
- c) One slice per function
- d) Groups of related files

### Q12: How do L3 findings become DemotionTickets?

When a quality reviewer identifies a logic issue (not just cosmetic), it should demote. The demotion chain is:

```text
L3 quality finding → DemotionTicket
  → Is it a style/naming issue? → Fix at L3 (no demotion)
  → Is it an architectural issue? → Demote to L2
  → Is it a logic/algorithmic issue? → Demote to L1
```

We have `review/findings_to_tickets.py` and `demotion/triage.py` but they've never been tested with real findings. How should the triage logic work? What categories of findings exist and how do they map to demotion targets?

---

## Questions for Review Design (Cross-Layer)

### Q13: Language-Agnostic Review Architecture

The user explicitly stated reviews cannot be tied to a language or library. The reference docs have language-specific rules (PEP8, Python patterns, etc.).

How should we design reviews that are:
- **Core**: Language-agnostic quality dimensions that any code must satisfy (e.g., "functions should have a single responsibility", "error paths should be handled", "naming should be consistent with context")
- **Evolutionary**: Language-specific patterns discovered over time (e.g., "in Python, use snake_case", "in Rust, prefer Result over panic") that are accumulated as heuristics

Should the review system:
- a) Use pure LLM judgment with general principles (no rule catalogs)?
- b) Use a rule catalog expressed in natural language that the LLM checks against?
- c) Use LLM judgment + a pattern librarian that maintains discovered patterns?
- d) Something else?

### Q14: Review Loop Integration with PromotionLoop

The reference docs describe a Quality Gate Loop (review → patch → re-review). Our PromotionLoop already has a loop structure. How do these compose?

Options:
- a) PromotionLoop step "PROMOTE" internally runs a review loop (review → patch → re-review) before declaring the slice promoted
- b) Review findings feed back as new gaps, causing the PromotionLoop to cycle again from GAP step
- c) Review is a separate loop AFTER the PromotionLoop converges
- d) Some combination based on layer

### Q15: Drift Review vs Rule-Based Review

The reference docs distinguish two orthogonal verification modes:
1. **Rule-based review** (artifact vs rules): conventions, best practices
2. **Conformance/drift review** (artifact pair comparison): spec → implementation fidelity

At each layer, what is the "spec" that the drift reviewer compares against?
- L1: spec comments → function bodies
- L2: library atoms → architectural assembly (are all atoms used? does the assembly match proposals?)
- L3: architectural design → clean code (is the refactored code faithful to the design?)

How do drift review and rule-based review compose at each layer?

---

## What I Need Back

For each question, provide:
1. Your recommended answer (pick one option or propose your own)
2. Brief rationale (1-3 sentences)
3. If there are design implications that affect other questions, call them out

Also provide:
1. A **step-by-step mapping** of what each PromotionLoop step does at L2 and L3 (analogous to the L1 mapping above)
2. A **compliance gate list** for L2 and L3
3. A **reviewer design** that is language-agnostic with evolutionary strategy layering
4. A **VerifyStep implementation** that works across all three layers
