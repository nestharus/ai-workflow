# Spec Refinement Integration Tests

## Overview
Comprehensive end-to-end tests for the 6-phase spec refinement workflow.

## Running Tests

### Full Suite
```bash
uv run pytest tests/spec_refinement/test_full_workflow.py -v
```

### Quick Tests (Skip Benchmarks)
```bash
uv run pytest tests/spec_refinement/test_full_workflow.py -m "not slow"
```

### Performance Benchmarks
```bash
uv run pytest tests/spec_refinement/test_full_workflow.py --benchmark-only
```

## Interface Tests
Interface tests validate the Phase 8 workflow: edge discovery, contract drafting, and validation/repair.

### Fixture Structure
- `create_interface_test_libraries` builds cross-referenced libraries under `runs/<run_id>/libraries/`.
- `interface_workspace` fixture initializes a workspace with interface libraries.
- `mock_interface_agents` provides interface-specific agent mocks with configurable violation modes.

### Running Interface Suites
```bash
uv run pytest tests/spec_refinement/test_interface_*.py -v
```

## Test Coverage
- Phase 1: Summarization (5 tests)
- Phase 2: Library Synthesis (6 tests)
- Phase 3: Evidence Expansion (4 tests)
- Phase 4: Spec Building (7 tests)
- Phase 5: Sublibrary Detection (3 tests)
- Phase 6: Architecture (5 tests)
- Full Workflow (3 tests)
- Edge Cases (10 tests)

## Fixtures
- Test corpus: 5-10 markdown files with known edge cases
- Mock agents: All 12 agent types with configurable failure rates
- Expected outputs: Validation schemas for all artifact types

## Performance Targets
- Total workflow time: < 60 seconds (mocked)
- Token usage: ~100,000 tokens for 10-file corpus
- Gap convergence: >= 80% per library
- Repair success rate: >= 80%

## Workflow Diagram

```mermaid
sequenceDiagram
    participant Test as Integration Test
    participant WS as WorkspaceManager
    participant P1 as Phase 1: Summarization
    participant P2 as Phase 2: Library Synthesis
    participant P3 as Phase 3: Evidence Expansion
    participant P4 as Phase 4: Spec Building
    participant P5 as Phase 5: Sublibrary Detection
    participant P6 as Phase 6: Architecture
    participant Repair as Repair Gate
    participant Validate as Validator

    Test->>WS: Initialize workspace with test corpus
    Test->>WS: Monkeypatch all agent runners

    Test->>P1: summarize_all(run_id)
    P1->>Validate: Validate summaries
    alt Invalid Output
        Validate->>Repair: Repair summary
        Repair-->>Validate: Repaired output
    end
    P1->>WS: Complete phase, update state
    P1-->>Test: {summaries_written, issues}

    Test->>P2: synthesize_libraries(run_id)
    P2->>P2: Label files -> Aggregate -> Refine -> Generate charters -> Resolve overlaps
    P2->>Validate: Validate charters
    alt Invalid Output
        Validate->>Repair: Repair charter
        Repair-->>Validate: Repaired output
    end
    P2->>WS: Complete phase, update state
    P2-->>Test: {libraries_created, overlap_decisions}

    Test->>P3: expand_evidence(run_id)
    P3->>P3: Priority ranking -> Map evidence -> Aggregate
    P3->>Validate: Validate evidence JSON
    alt Invalid Output
        Validate->>Repair: Repair evidence JSON
        Repair-->>Validate: Repaired output
    end
    P3->>WS: Complete phase, update state
    P3-->>Test: {evidence_sources_added}

    Test->>P4: build_specs(run_id)
    loop Until Convergence
        P4->>P4: Generate patches -> Apply patches -> Gap audit
        P4->>Validate: Validate spec.md
        alt Invalid Output
            Validate->>Repair: Repair spec
            Repair-->>Validate: Repaired output
        end
    end
    P4->>WS: Complete phase, update state, record coverage metrics
    P4-->>Test: {converged_count, coverage_metrics}

    Test->>P5: detect_sublibraries(run_id)
    P5->>WS: Complete phase, update state
    P5-->>Test: {sublibraries_created}

    Test->>P6: propose_architectures(run_id)
    P6->>P6: Extract briefs -> Propose candidates
    P6->>WS: Complete phase, update state
    P6-->>Test: {candidates_created}

    Test->>P6: select_architecture(run_id)
    P6->>P6: Evaluate candidates -> Select best
    P6->>WS: Complete phase, update state
    P6-->>Test: {selected_arch_id}

    Test->>P6: map_libraries_to_architecture(run_id)
    P6->>P6: Map per library -> Aggregate fragments
    P6->>Validate: Validate mapping.md
    alt Invalid Output
        Validate->>Repair: Repair mapping
        Repair-->>Validate: Repaired output
    end
    P6->>WS: Complete phase, update state
    P6-->>Test: {libraries_mapped}

    Test->>Test: Validate all phases COMPLETED
    Test->>Test: Validate gap convergence >= 0.8
    Test->>Test: Validate all libraries mapped
    Test->>Test: Generate performance report
```
