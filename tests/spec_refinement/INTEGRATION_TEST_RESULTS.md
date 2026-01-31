# Integration Test Results

## Test Summary
- **Last Run**: 2026-01-31
- **Command**: `uv run pytest tests/spec_refinement/test_full_workflow.py -m "not slow"`
- **Total Tests**: 18 (1 deselected: slow)
- **Passed**: 18
- **Failed**: 0
- **Notes**: Session exit status was non-zero due to use-case coverage threshold (0% < 100%).

## Performance Metrics

| Phase | Latency (s) | Token Usage | Cost ($) |
| --- | --- | --- | --- |
| Phase 1: Summarization | Not run (slow test skipped) | Not run | Not run |
| Phase 2: Library Synthesis | Not run | Not run | Not run |
| Phase 3: Evidence Expansion | Not run | Not run | Not run |
| Phase 4: Spec Building | Not run | Not run | Not run |
| Phase 5: Sublibrary Detection | Not run | Not run | Not run |
| Phase 6: Architecture | Not run | Not run | Not run |

## Failure Modes Tested
- Invalid file pointers repaired
- Missing sections repaired
- Non-monotonic patch operations rejected
- Unmapped libraries detected
- Gap convergence failure handling
- Phase dependency validation

## Gap Convergence Analysis

| Library | Total Gaps | Closed Gaps | Convergence Ratio |
| --- | --- | --- | --- |
| lib_001 | TBD | TBD | TBD |
| lib_002 | TBD | TBD | TBD |

## Repair Gate Effectiveness
- **Repair Success Rate**: TBD
- **Common Failure Patterns**: TBD

## Known Issues
- Use-case coverage threshold fails when running integration tests without `@pytest.mark.usecase` coverage.

## Recommendations
- Execute integration suite and populate metrics after first run
- Review repair gate timing for complex artifacts
