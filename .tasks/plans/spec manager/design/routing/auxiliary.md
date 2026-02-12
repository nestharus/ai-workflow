# Auxiliary Systems

Mixed classification. Includes isolated packages, test infrastructure, and stub systems.

---

## Systems

### Decomposition
**Classification**: Business (isolated)
**Package**: `spec_manager/decomposition/`
**Files**: 11
**Purpose**: Spec decomposition — breaking down large specs into smaller documents.
**Surface API**:
- `extract_entity_to_document()`, `extract_relation_to_document()`
- `create_staging_file()`, `tag_facts()`
- `recompose()`
**Dependencies**: `schemas.derived_elements`, `core.annotations`
**Consumers**: None (0 external consumers — isolated)

### Labyrinth
**Classification**: Test/Evaluation
**Package**: `spec_manager/labyrinth/`
**Files**: 73
**Purpose**: Brownfield stress-test codebase for spec refinement evaluation. Synthetic codebase with intentional gaps, cross-service issues, architectural smells.
**Surface API**:
- `generate_codebase(config) -> LabyrinthProject`
- `LabyrinthService` — synthetic services
- `IntegrationScenario` — cross-service issues
**Dependencies**: `schemas.architecture`, `core.code_analysis`
**Consumers**: Evaluation fixtures, e2e tests (not production pipeline)

### Intake Queue & Pattern Library
**Classification**: Structural
**Package**: `spec_manager/orchestration/` (single files)
**Modules**: `intake_queue.py`, `pattern_library.py`
**Purpose**: Intake queue holds pending Phase 0 inputs. Pattern library stores reusable architectural patterns.
**Surface API**:
- `IntakeQueue.enqueue(item)`, `dequeue()`, `process_batch()`
- `PatternLibrary.find_pattern(criteria) -> ArchitecturePattern`
**Dependencies**: `intake.types`, `schemas.architecture`
**Consumers**: `orchestration.pdd_lifecycle`
