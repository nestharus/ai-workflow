# Cohesion

**Classification**: Business (coupling/cohesion)
**Package**: `spec_manager/cohesion/`
**Files**: 2
**Role**: Continuous coupling/cohesion refinement. Detects structural issues in entity graph and proposes atomic operations.

---

## System

### Coupling/Cohesion Detector
**Modules**: `detector.py`, `executor.py`, `operations.py`
**Purpose**: Detects overlap, divergence, and overload patterns in entity graphs. Proposes merge/split/move operations.
**Surface API**:
- `detect_all(graph) -> list[CouplingIssue]`
- `detect_overlap()`, `detect_divergence()`, `detect_overload()`
- `RefinementExecutor.execute(operation) -> bool`
- `propose_operations(issues) -> list[RefinementOperation]`
**Dependencies**: `analysis.adjacency`, `core.data_structures`
**Consumers**: `orchestration.promotion_loop.PromoteStep`
