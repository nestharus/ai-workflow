# Compliance

**Classification**: Business (quality gates)
**Package**: `spec_manager/compliance/`
**Files**: 22
**Role**: Quality validation and gating for layer promotion. Three sub-systems: entity coverage, executable gap detection, and promotion gates.

---

## Systems

### Coverage
**Module**: `coverage/` (analyzer.py, report.py, gate.py, matching.py, cli.py)
**Purpose**: Entity coverage gap detection. Cross-references spec entities with implementation atoms.
**Surface API**:
- `EntityCoverageAnalyzer.analyze(bundle) -> EntityCoverageReport`
- `EntityCoverageReport` — coverage_rate, gaps: list[CoverageGap]
**Dependencies**: `schemas.entities`, `core.gaps`
**Consumers**: `compliance.promotion.algorithmic_gates`

### Detection
**Module**: `detection/` (comment_scanner.py, stub_scanner.py, runtime_detector.py, coverage_analyzer.py, orchestrator.py)
**Purpose**: Executable gap detection. Mechanically identifies unimplemented spec via comment scanning, stub scanning, runtime probes, code coverage analysis.
**Surface API**:
- `scan_executable_gaps(config: ScanConfig) -> ExecutableGapReport`
- `ExecutableGapReport` — gaps: list[ExecutableGap], coverage_analysis
- `integrate_with_gap_queue(report, gap_queue)`
**Dependencies**: `core.code_analysis`, `core.gap_queue`
**Consumers**: `orchestration.promotion_loop.GapExplorationStep`, `branches.gap_detection`

### Promotion
**Module**: `promotion/` (config.py, orchestrator.py, algorithmic_gates.py, architectural_quality.py, result.py)
**Purpose**: Compliance gating for layer promotion. Implements quality gates per layer.

**L1 gates** (5 hard):
- COVERAGE, COMPLETENESS, CORRECTNESS, GOVERNANCE, CLARITY

**L2 gates** (8, LLM-based):
- ARCH_DECOMPOSITION, SERVICE_CONTRACTS, TOPOLOGY, EVENT_FLOW, CONSISTENCY, PIN_EDGES, ARCH_DRIFT, GOVERNANCE

**L3 gates**:
- Quality gaps + diff-impact analysis

**Surface API**:
- `LayerPromotionGate.check(bundle, layer) -> PromotionReport`
- `PromotionReport` — hard_gates: list[GateCheckResult], soft_signals: list[Signal]
**Dependencies**: `compliance.coverage`, `compliance.detection`, `orchestration.evidence`
**Consumers**: `orchestration.promotion_loop.PromoteStep`, `orchestration.scoring`
