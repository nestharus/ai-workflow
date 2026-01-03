# Linter Algorithm Decomposition Analysis

You are analyzing a complex parallel linter algorithm to select the best decomposition strategy for reducing coupling, improving testability, and enabling incremental optimization.

## Input Files

1. **linter algorithm.md** - The complete algorithm specification as a Mermaid flowchart with detailed annotations
2. **linter algorithm candidates/** - A folder containing:
    - `README.md` - Summary comparison of all candidates
    - `candidate-1-data-flow-pipeline.md` - Pipeline decomposition (11 stages)
    - `candidate-2-domain-driven.md` - Domain decomposition (5 domains)
    - `candidate-3-layered.md` - Layered architecture (5 layers)
    - `candidate-4-state-machine.md` - State machine decomposition (6 states)
    - `candidate-5-process-centric.md` - Process-centric decomposition (5 concerns)
    - `cross-cutting-concerns.md` - Shared abstractions needed across all approaches

## Your Task

Analyze all candidates and produce a final recommendation. Your analysis must include:

### 1. Risk Assessment

For each candidate, evaluate:
- **Implementation Risk** - How likely is the refactoring to introduce bugs?
- **Scope Creep Risk** - How likely is this to expand beyond initial boundaries?
- **Integration Risk** - How difficult is it to integrate extracted components?
- **Regression Risk** - How likely are existing behaviors to break?
- **Complexity Risk** - Does this add more complexity than it removes?

### 2. Trade-off Analysis

Compare candidates on:
- Testability improvements vs. abstraction overhead
- Isolation benefits vs. interface proliferation
- Platform abstraction vs. performance impact
- Explicit control flow vs. code verbosity

### 3. Critical Path Identification

Identify which parts of the algorithm are:
- Most error-prone and would benefit most from isolation
- Most tightly coupled and hardest to extract
- Most likely to change in the future
- Most critical for correctness (e.g., snapshot restoration, shutdown coordination)

### 4. Final Recommendation

Provide:
- **Selected Strategy** - Which candidate (or hybrid) to pursue
- **Rationale** - Why this choice minimizes risk while maximizing benefit
- **First Extraction Target** - Which component to extract first
- **Extraction Order** - Sequence for subsequent extractions
- **Success Criteria** - How to verify the decomposition succeeded
- **Rollback Plan** - How to recover if extraction causes problems

## Output Format

Structure your response as:

Risk Assessment Summary

[Table of candidates vs. risk categories: Low/Medium/High]

Critical Coupling Points

[List of tightest couplings that require careful handling]

Recommendation

Selected Strategy: [Name]

Rationale: [Why]

Extraction Plan:

1. [First component] - [Why first]
2. [Second component] - [Dependencies on first]
3. ...

Success Criteria:

- Criterion 1
- Criterion 2
  ...

Risks to Monitor:


## Context

The goal is to break down a growing, complex algorithm into loosely coupled pieces to:
1. Find bugs more easily through isolation
2. Optimize individual components independently
3. Test components in isolation
4. Reduce cognitive load when making changes

The algorithm manages parallel linter execution with:
- Multiple file discovery modes (git-based)
- Linter scheduling with resource conflict detection
- Mutating vs. read-only linter phases
- Process tree management (POSIX/Windows)
- Snapshot/restore for crash recovery
- Fail-fast and SIGINT handling
- Ordered output buffering
- ARG_MAX chunking

Prioritize **safety and incremental progress** over ambitious restructuring.