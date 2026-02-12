# Projection

**Classification**: Structural (lineage + drift)
**Package**: `spec_manager/projection/`
**Files**: 11
**Role**: Lineage tracking, import graph construction, pin drift detection, and change propagation.

---

## Systems

### Lineage
**Module**: `lineage/` (edges.py, table.py, builder.py, data_flow.py, drift_detector.py, persistence.py)
**Purpose**: Import graph construction and pin lineage tracing. Forward/backward trace through pin function connections.
**Surface API**:
- `LineageBuilder.build(atoms, imports) -> ProjectionLineageTable`
- `ProjectionLineageTable.forward_trace(pin) -> list[Hop]`
- `ProjectionLineageTable.backward_trace(target) -> list[Hop]`
- `PinDriftDetector.detect(old_table, new_table) -> PinDriftReport`
- `DataFlowTracker.track(signal_source) -> DataFlowReport`
- `scan_imports_from_files()` / `scan_imports_from_directory()` → `RawImportRecord`
**Dependencies**: `core.code_analysis`, `schemas.pin_functions`
**Consumers**: `projection.generator`, `projection.drift`, `orchestration.downward_flow`

### Drift & Pin Propagation
**Modules**: `drift.py`, `pin_propagation.py`, `generator.py`
**Purpose**: Atom-aware drift detection (spec vs code) and pin change propagation through call graph.
**Surface API**:
- `AtomAwareDriftComparator.compare(spec, code) -> DriftReport`
- `DriftReport` — drifts: list[DriftItem], policy: DriftPolicy
- `PinChangePropagator.propagate(changes) -> PropagationReport`
- Classifies urgency: auto_propagated | review_required | breaking_change
- `convert_drift_to_gaps()`, `convert_propagation_to_drift()`
- `ProjectionGenerator.generate(libraries) -> Plan`
**Dependencies**: `projection.lineage`, `core.gaps`, `schemas.pin_functions`
**Consumers**: `orchestration.promotion_loop.AnalyzeStep`, `branches.pins`
