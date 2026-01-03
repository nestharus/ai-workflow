# Algorithm Decomposition Analyzer Prompt

## Context

You are analyzing a complex parallel linter algorithm that needs to be decomposed into loosely coupled components. Five candidate decomposition approaches have been proposed, along with detailed analyses of coupling patterns, cross-cutting concerns, and discovered bugs.

## Your Task

1. **Evaluate each candidate** for risks, implementation complexity, and alignment with the algorithm's structure
2. **Identify the optimal decomposition strategy** (may be a single candidate or hybrid approach)
3. **Produce a final recommended solution** with concrete component boundaries and interfaces
4. **Prioritize the extraction order** based on risk mitigation and coupling reduction

## Input Files

You will receive:
- `algorithm.md` - The source algorithm file (at root)
- `algorithm candidates/` - A folder containing all analysis files (at root)

Read these files in order:

### Source Algorithm
- `algorithm.md` - The original algorithm (Mermaid flowchart with 8 subgraphs, 25 key concepts)

### Candidate Decompositions (in `algorithm candidates/`)
- `candidate-1-state-centric.md` - Split by state ownership (6 components)
- `candidate-2-lifecycle.md` - Split by target lifecycle (8 stages)
- `candidate-3-responsibility.md` - Split by domain responsibility (8 components)
- `candidate-4-event-driven.md` - Event/message-passing architecture
- `candidate-5-layered.md` - Layered abstraction architecture (5 layers)

### Analysis Reports (in `algorithm candidates/`)
- `analysis-coupling.md` - Coupling matrix, circular dependencies, seam boundaries
- `analysis-crosscutting.md` - 7 cross-cutting concerns with isolation strategies
- `analysis-investigation.md` - Investigation lifecycle state machine and edge cases
- `analysis-staleness.md` - Stale linter management analysis, **3 critical bugs discovered**

### Preliminary Summary (in `algorithm candidates/`)
- `SUMMARY.md` - Initial synthesis and recommendations (use as reference, not as authoritative answer)

## Evaluation Criteria

For each candidate, assess:

| Criterion | Weight | Description |
|-----------|--------|-------------|
| Bug Isolation | HIGH | Does it isolate the 3 discovered bugs (especially 6.4, 6.5)? |
| Coupling Reduction | HIGH | Does it break the identified circular dependencies? |
| Implementation Risk | HIGH | How likely is it to introduce regressions during extraction? |
| Testability | MEDIUM | Can components be unit tested in isolation? |
| Incremental Adoption | MEDIUM | Can it be implemented in phases without big-bang refactor? |
| Complexity Overhead | LOW | How much indirection/boilerplate does it add? |

## Known Constraints

- The algorithm must continue functioning during incremental decomposition
- `<PROJECT>` pseudo-target handling spans multiple concerns
- Investigation lifecycle has race conditions that must be preserved correctly
- Stale linter state machine must handle FAILURE case (currently missing)

## Expected Output

Produce a document with:

1. **Risk Assessment Table** - Each candidate rated against criteria
2. **Selected Approach** - Which candidate(s) to use and why
3. **Component Specification** - Final list of components with:
   - Name and purpose
   - Owned state variables
   - API surface (key methods/interfaces)
   - Dependencies on other components
4. **Extraction Plan** - Ordered list of components to extract with:
   - Prerequisites
   - Risk level
   - Validation strategy
5. **Bug Fix Integration** - How the decomposition addresses bugs 6.3, 6.4, 6.5

## Output Location

Write your final solution to:
`algorithm candidates/FINAL_SOLUTION.md`
