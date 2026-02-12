# Schemas

**Classification**: Utility (shared data models)
**Package**: `spec_manager/schemas/`
**Files**: 35+
**Role**: Structured schema definitions for all agent outputs. 40+ Pydantic dataclasses. Depended on by 9 packages.

---

## Key Schema Groups

### Architecture
- `ArchitectureProposal`, `InterfaceContract`, `ServiceDefinition`
- Used by: orchestration.architecture, planner.architecture, compliance.promotion

### Entities
- `Entity`, `EntityReference`, `EntityRelation`
- Used by: compliance.coverage, decomposition

### Evidence
- `Finding`, `Evidence`, `EvidenceRef`
- Used by: orchestration.evidence, refinement.hollowed_spec

### Pin Functions
- `PinFunction`, `ImportEdge`, `PinFunctionRegistry`, `ProjectionType`
- `ProjectionType` enum: PASS_THROUGH, EVENT_BRIDGE, MIDDLEWARE_WRAP, etc.
- Used by: projection, pin_functions, branches

### Tasks
- `Task`, `SpecPatch`, `TaskResult`
- Used by: strategies, orchestration

### Judges
- Pydantic schemas for judge outputs (architecture quality, code quality, spec fidelity, pairwise)
- Used by: refinement.evals.judges

---

## Surface API

All schemas provide:
- Pydantic validation (constructor, `.model_validate()`)
- JSON serialization (`.model_dump()`, `.model_dump_json()`)
- Read/write helpers for common formats

## Dependencies

None (pure schemas). This package has no imports from other spec_manager packages.

## Consumers

`core`, `orchestration`, `compliance`, `projection`, `pin_functions`, `analysis`, `branches`, `discovery`, `refinement`
