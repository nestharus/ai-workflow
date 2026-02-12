# Pin Functions

**Classification**: Business (pin extraction)
**Package**: `spec_manager/pin_functions/`
**Files**: 7
**Role**: Pin-function orchestration — extraction, registration, change tracking. Manages atom-level extraction and import graph building.

---

## System

### Pin Function Orchestrator
**Modules**: `orchestrator.py`, `cli.py`
**Purpose**: Scans source code for pin functions (atoms), extracts via `analyze_source()`, builds import edges, merges P9 LLM proposals.
**Surface API**:
- `PinFunctionOrchestrator(config).run() -> PinFunctionRegistry`
- `PinFunctionOrchestrator.scan()` — extract atoms
- `PinFunctionOrchestrator.merge_proposals()` — handle P9 LLM proposals
- `PinFunctionConfig` — atom_directories, architectural_roots
**Dependencies**: `core.code_analysis`, `projection.lineage`, `schemas.pin_functions`
**Consumers**: `branches.pins`, `orchestration.promotion_loop`
