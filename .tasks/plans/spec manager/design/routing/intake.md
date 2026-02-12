# Intake

**Classification**: Business (Phase 0 routing)
**Package**: `spec_manager/intake/`
**Files**: 5
**Role**: Phase 0 prose-to-spec routing pipeline. Transforms raw specification text into structured library proposals.

---

## System

### Intake Pipeline
**Modules**: `types.py`, `router.py`, `assemble.py`, `orchestrator.py`, `cli.py`
**Purpose**: 5-step routing pipeline for Phase 0. Sections the raw spec, discovers libraries, routes requirements, assembles library charters.
**Surface API**:
- `run_phase0(spec_path, workspace_root) -> IntakeResult`
- `IntakeOrchestrator(config).run() -> IntakeResult`
- `IntakeResult` — libraries: list[LibraryCharter], sections, routing_table
- `assemble_library(name, requirements, constraints) -> LibraryCharter`
**Dependencies**: `refinement` (workspace), `core` (agent_utils, sections)
**Consumers**: `orchestration.pdd_lifecycle` (first step of pipeline)

**Key output**: Libraries are skeletons (proposed by Phase 0, analyzed by refinement engine). Each library gets:
- `charter.md` — purpose and scope
- `constraints.md` — parsed constraints with element IDs
- `details.md` — detailed requirements
- `constraints_index.json` — subtype classification
