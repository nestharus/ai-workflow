# TODO(single-layer) Audit: Completeness Check

## Your Task

Audit whether the `TODO(single-layer)` comments placed across the codebase fully represent every actionable point in the design proposal (response3.md). Find gaps — proposal sections or concepts that have no corresponding TODO.

## How to Audit

### Step 1: Gather all TODOs

Run this command to collect every TODO(single-layer) comment with file paths:

```bash
cd /mnt/c/Users/xteam/IdeaProjects/ai-workflow/scripts/spec_manager
grep -rn "TODO(single-layer)" --include="*.py" | head -200
```

Also check the tests directory:

```bash
grep -rn "TODO(single-layer)" tests/ --include="*.py" | head -50
```

**CRITICAL**: Some TODO blocks span 30+ lines. Do NOT truncate at 20 lines. For key files like `routing/matcher.py`, `routing/shapes.py`, `orchestration/pdd_lifecycle.py`, read the FULL file (at least first 40 lines) to see the complete TODO block. Truncating will cause false-positive gaps.

### Step 2: Read the design proposal

Read the complete proposal:

```
/mnt/c/Users/xteam/IdeaProjects/ai-workflow/.tasks/plans/spec manager/.research/single-layer-refinement/response3.md
```

### Step 3: Cross-reference

For each numbered section in response3.md, verify that:

1. **Every concept introduced** has at least one TODO referencing it
2. **Every file mentioned for deletion** has a DELETE TODO
3. **Every file mentioned for restructuring** has a RESTRUCTURE TODO
4. **Every NEW module** has a placeholder file with a TODO
5. **Section references** in TODOs (e.g., "Section 6.3") actually match the proposal content

### Step 4: Check for these specific proposal sections

The proposal has these major sections — verify each is represented:

| Section | Topic | Expected TODO coverage |
|---------|-------|----------------------|
| 1 | Executive Summary | Covered implicitly by all TODOs |
| 2 | Motivation (L1→L2→L3 problems) | Covered by pdd_lifecycle.py, promotion_loop.py |
| 3 | Core Concepts (shapes, verifiers, contracts) | routing/shapes.py, routing/verifiers.py |
| 3.2 | What Shapes Replace (pins→shapes) | All pin DELETE TODOs |
| 4 | Shape Document Format | routing/shapes.py |
| 4.1 | Verifier declarations | routing/verifiers.py |
| 4.2 | Granularity (package, not function) | Referenced in shapes.py, pin DELETE rationales |
| 5 | Shape Lifecycle (creation, updates) | Should be in shapes.py or lifecycle file |
| 5.1 | Storage (workspace/routing/) | shapes.py TODO |
| 5.2 | Derivation from spec decomposition | shapes.py TODO |
| 6 | Shape Matching | routing/matcher.py |
| 6.1 | Observed sources (deterministic + LLM hints) | matcher.py |
| 6.2 | ShapeMatchReport | matcher.py |
| 6.3 | Matching rules (4 rules) | matcher.py |
| 7 | Contract Patterns | pattern_library.py KEEP/EXTEND |
| 7.1 | Pattern types (EVENT_FLOW, DI_BINDING, etc.) | pattern_library.py |
| 7.2 | Contract pattern templates | pattern_library.py |
| 8 | Work Item Routing | work_items.py, findings_to_tickets.py |
| 8.1 | Work item schema (shape_id, phase, etc.) | work_items.py |
| 8.2 | Routing to Build phase | matcher.py, findings_to_tickets.py |
| 8.3 | Change propagation (git diff→shapes→neighbors) | matcher.py |
| 9 | Phase Cycle | pdd_lifecycle.py, promotion_loop.py |
| 9.1 | Four phases (Build→Algorithm→Arch→Quality) | pdd_lifecycle.py |
| 9.2 | Phase transitions | pdd_lifecycle.py |
| 9.3 | Bounded iteration (max cycles, stagnation) | run_state.py |
| 9.4 | Convergence criteria | verifiers.py |
| 10 | Gate Restructuring | compliance/promotion/ files |
| 10.1 | Aspect gates (Behavior/Arch/Quality) | orchestrator.py, config.py |
| 11 | Demotion Restructuring | demotion/ files |
| 11.1 | Work item escalation | demotion/__init__.py |
| 12 | Migration Plan | Covered by DELETE/RESTRUCTURE/NEW markers |
| 12.1 | Files to delete | All DELETE TODOs |
| 12.2 | Files to restructure | All RESTRUCTURE TODOs |
| 12.3 | Files to keep | All KEEP TODOs |
| 12.4 | New modules | routing/ package |
| 13 | Design Constraints Compliance | Implicit in all TODOs |
| 13.1 | Deterministic authority boundary | matcher.py, orchestrator.py |
| 13.2 | LLM outputs advisory only | matcher.py, findings_to_tickets.py |
| 13.3 | No LLM convergence authority | verifiers.py, orchestrator.py |
| 14 | Evaluation Proposal | evals/runner.py, evals/metrics.py |
| 14.1 | A/B evaluation setup (same fixtures/seeds/budgets) | evals/runner.py |
| 14.2 | Success criteria | evals/runner.py, evals/metrics.py |
| 14.3 | Failure criteria (stagnation, escape, LLM reliance) | evals/runner.py, evals/metrics.py |
| 14.4 | Proof-of-feasibility milestone | evals/runner.py |
| 15 | Non-ship safety condition | verifiers.py, orchestrator.py |

### Step 5: Report

Produce a report with:

1. **Coverage summary**: X of Y proposal sections have TODO coverage
2. **Gaps found**: List each proposal concept that has NO corresponding TODO, with:
   - Which section of response3.md
   - What the concept is
   - Which file should get the TODO (or "NEW file needed")
3. **Misalignments**: Any TODOs that contradict or misrepresent the proposal
4. **Section reference accuracy**: Any TODOs citing wrong section numbers

Write the report to:
```
/mnt/c/Users/xteam/IdeaProjects/ai-workflow/.tasks/plans/spec manager/.research/single-layer-refinement/todo-audit-results.md
```

## Important Notes

- The proposal is in response3.md, NOT response2.md or response1.md
- TODOs use format: `# TODO(single-layer): ACTION — description`
- Actions are: DELETE, RESTRUCTURE, KEEP, KEEP/EXTEND, KEEP/RESTRUCTURE, NEW
- The routing/ package (shapes.py, verifiers.py, matcher.py) are NEW placeholder files
- Focus on MISSING coverage, not on judging TODO quality — that's the next step
