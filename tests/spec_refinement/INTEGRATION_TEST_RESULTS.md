# Integration Test Results

## Test Summary
- **Last Run**: 2026-01-31
- **Command**: `uv run pytest tests/spec_refinement/test_full_workflow.py -v`
- **Total Tests**: 19
- **Passed**: 19
- **Failed**: 0
- **Notes**: Includes slow performance benchmark; exit status 0 (use-case coverage gate skipped because no `tests/integration/` items were collected).

## Performance Metrics

| Phase | Latency (s) | Token Usage | Cost ($) |
| --- | --- | --- | --- |
| Phase 1: Summarization | 0.31 | 8,000 | 0.0080 |
| Phase 2: Library Synthesis | 0.10 | 10,400 | 0.0104 |
| Phase 3: Evidence Expansion | 0.13 | 16,000 | 0.0160 |
| Phase 4: Spec Building | 0.34 | 17,600 | 0.0176 |
| Phase 5: Sublibrary Detection | 0.06 | 1,600 | 0.0016 |
| Phase 6: Architecture | 0.29 | 5,600 | 0.0056 |

**Total Latency**: 1.24s  
**Total Tokens**: 59,200  
**Total Cost**: $0.0592  

_Metrics captured from a local run using the same `PerformanceBenchmark` tracker as the slow test (`file_count=10`, `violation_rate=0.0`)._

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
| lib_001 | 0 | 0 | 1.00 |
| lib_002 | 0 | 0 | 1.00 |

## Repair Gate Effectiveness
- **Repair Success Rate**: 1.00 (8/8 repairs validated cleanly)
- **Repair Failed Issues**: 0
- **Repaired Artifacts**: summary, library_labels, spec_patches, architecture_selection, architecture_mapping

## Known Issues
- None observed in latest run.

## Recommendations
- Monitor performance bounds as workflow complexity grows.
