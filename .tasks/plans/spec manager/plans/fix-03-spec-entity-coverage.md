# Implementation Plan

## Overview

Build a spec entity coverage gap detector that cross-references hollowed spec entities (ENT-####) against registered atom functions, producing a coverage report that identifies unmatched entities (spec concepts lacking implementation) and unmatched atoms (implementations lacking spec documentation).

## Current State (Problems)

1. **No cross-referencing between spec entities and atoms.** The `EvidenceIndex` (`scripts/spec_manager/spec_manager/refinement/hollowed_spec/indexer.py`) maintains a `global_entity_index` mapping `entity_name -> list[(lib_id, paragraph_id)]`, and the `AtomRegistry` (`scripts/spec_manager/spec_manager/branches/atoms.py`) tracks `AtomDescriptor` instances with `atom_id`, `function_name`, `kind`, and `vertical_slice`. These two registries exist in isolation -- there is no mechanism to compare them.

2. **Entity-to-atom relationships exist but are scattered.** The `EntityMention` schema (`scripts/spec_manager/spec_manager/schemas/entities.py`, line 66) already has an `atom_ids` field linking entities to atoms, and `EntitiesArtifact.get_atom_ids_for_entity()` aggregates these. However, no tool uses this to produce a completeness report.

3. **Existing compliance gates do not check spec entity coverage.** The promotion gate orchestrator (`scripts/spec_manager/spec_manager/compliance/promotion/orchestrator.py`) checks pin coverage, provenance, call graph connectivity, stub functions, and architectural quality -- but nothing validates that spec entities have corresponding atom implementations or vice versa.

4. **No CLI command for entity coverage analysis.** The CLI (`scripts/spec_manager/spec_manager/cli.py`) has `evidence-store status` and `branches gaps` but no coverage-gap command bridging the evidence store and atom registry.

## Target State

- A `CoverageReport` dataclass that enumerates:
  - **Unmatched entities**: ENT-#### IDs present in the hollowed spec entity index but with no corresponding atom function.
  - **Unmatched atoms**: Atom IDs in the registry with no entity reference in any spec.
  - **Matched pairs**: Entity-to-atom linkages with a confidence score.
  - **Coverage ratios**: entity_coverage (matched entities / total entities) and atom_coverage (matched atoms / total atoms).
- A matching engine supporting three strategies (applied in priority order): explicit linkage via `EntityMention.atom_ids`, naming heuristic (entity name tokens overlap with atom function name), and keyword overlap (entity paragraph keywords vs atom docstring keywords).
- A compliance gate (`ENTITY_COVERAGE`) that plugs into the existing `LayerPromotionGate` orchestrator.
- A CLI subcommand `coverage entity-gaps` that produces human-readable and JSON output.

## Additional Info

### Key Data Structures

**Entity side** (from evidence store):
- `EvidenceIndex.global_entity_index`: `dict[str, list[tuple[str, str]]]` -- entity_name -> list of (lib_id, paragraph_id)
- `Entity` schema: `entity_id` (ENT-####), `name`, `kind` (EntityKind enum), `canonical_symbol`, `description`
- `EntityMention`: links `entity_id` to `section_id` and `atom_ids` with confidence
- `EntitiesArtifact.get_atom_ids_for_entity()`: aggregates atom_ids from mentions and tags

**Atom side** (from branch registry):
- `AtomRegistry._atoms`: `dict[str, AtomDescriptor]`
- `AtomDescriptor`: `atom_id`, `kind` (AtomKind), `function_name`, `signature`, `content_hash`, `vertical_slice`
- `AtomCandidate` (from AST extractor): `function_name`, `qualified_name`, `docstring`, `keywords` (extractable), `called_functions`

### Matching Strategy Priority
1. **Explicit linkage** (confidence 1.0): `EntityMention.atom_ids` and `EntityTag.atom_ids` directly link entities to atoms. Use `EntitiesArtifact.get_atom_ids_for_entity()`.
2. **Naming heuristic** (confidence 0.7): Tokenize entity `name` and atom `function_name` into word sets (split on `_`, `-`, camelCase). If Jaccard similarity >= 0.5, consider matched.
3. **Keyword overlap** (confidence 0.4): Extract keywords from entity paragraph text (already indexed in `HollowedParagraph.keywords`) and from atom docstrings (via `AtomCandidate.docstring`). If >= 3 shared keywords, consider matched.

### Integration Points
- Evidence index loading: `EvidenceIndex.load(path)` or `build_evidence_index(workspace_root)`
- Atom registry loading: `AtomRegistry.load(layout)`
- Entities artifact: loaded from `workspace/entities/entities.json` per library
- Compliance gate pattern: follows `GateCheckResult` + `GateSpec` from `scripts/spec_manager/spec_manager/compliance/promotion/result.py` and `config.py`

## Plans

### Plan 1: Core Coverage Analyzer Module

**Goal**: Create the matching engine and coverage report data structures.

**Files to create**:
- `scripts/spec_manager/spec_manager/compliance/coverage/__init__.py`
- `scripts/spec_manager/spec_manager/compliance/coverage/analyzer.py`
- `scripts/spec_manager/spec_manager/compliance/coverage/matching.py`
- `scripts/spec_manager/spec_manager/compliance/coverage/report.py`

**Steps**:

1. Create `report.py` with dataclasses:
   - `CoverageMatch`: `entity_id: str`, `atom_id: str`, `match_method: str` (explicit/naming/keyword), `confidence: float`, `entity_name: str`, `atom_function_name: str`
   - `UnmatchedEntity`: `entity_id: str`, `name: str`, `kind: str`, `paragraph_ids: list[str]`, `lib_ids: list[str]`
   - `UnmatchedAtom`: `atom_id: str`, `function_name: str`, `kind: str`, `vertical_slice: str | None`
   - `EntityCoverageReport`: `matched: list[CoverageMatch]`, `unmatched_entities: list[UnmatchedEntity]`, `unmatched_atoms: list[UnmatchedAtom]`, `entity_coverage: float`, `atom_coverage: float`, `total_entities: int`, `total_atoms: int`
   - `to_dict()` and `save(path)` methods on `EntityCoverageReport`

2. Create `matching.py` with the matching strategies:
   - `_tokenize_name(name: str) -> set[str]`: splits on `_`, `-`, camelCase boundaries, lowercases all tokens, filters tokens < 3 chars
   - `match_explicit(entities_artifact: EntitiesArtifact, atom_ids: set[str]) -> list[CoverageMatch]`: uses `get_atom_ids_for_entity()`, returns matches for entity-atom pairs where atom_id exists in the atom registry
   - `match_by_naming(entities: list[Entity], atom_descriptors: list[AtomDescriptor]) -> list[CoverageMatch]`: tokenizes entity name and atom function_name, computes Jaccard similarity, returns matches above 0.5 threshold
   - `match_by_keywords(entity_paragraphs: dict[str, list[HollowedParagraph]], atom_candidates: list[AtomCandidate]) -> list[CoverageMatch]`: compares paragraph keywords with atom docstring keywords, returns matches with >= 3 shared keywords
   - `resolve_matches(explicit: list, naming: list, keyword: list) -> list[CoverageMatch]`: merges match lists with priority ordering (explicit > naming > keyword), keeping highest-confidence match per entity-atom pair

3. Create `analyzer.py` as the orchestration layer:
   - `EntityCoverageAnalyzer` class with:
     - `__init__(evidence_index: EvidenceIndex, atom_registry: AtomRegistry, entities_artifact: EntitiesArtifact | None = None)`
     - `analyze() -> EntityCoverageReport`: runs all three matching strategies, resolves, computes coverage ratios
     - `_collect_entity_paragraphs() -> dict[str, list[HollowedParagraph]]`: groups paragraphs by entity ID using the evidence index
     - `_identify_unmatched(matched_entity_ids: set, matched_atom_ids: set) -> tuple[list[UnmatchedEntity], list[UnmatchedAtom]]`

4. Create `__init__.py` exporting `EntityCoverageAnalyzer`, `EntityCoverageReport`.

**Tests to create**:
- `scripts/spec_manager/tests/compliance/coverage/__init__.py`
- `scripts/spec_manager/tests/compliance/coverage/test_matching.py`: unit tests for each matching strategy with synthetic entities and atoms
- `scripts/spec_manager/tests/compliance/coverage/test_analyzer.py`: integration test with a small EvidenceIndex and AtomRegistry

### Plan 2: Compliance Gate Integration

**Goal**: Add an `ENTITY_COVERAGE` gate to the existing promotion gate framework.

**Files to modify**:
- `scripts/spec_manager/spec_manager/compliance/promotion/config.py`: add `ENTITY_COVERAGE` to `GateId` enum
- `scripts/spec_manager/spec_manager/compliance/promotion/orchestrator.py`: wire entity coverage check into `run_all_checks()` and `run_single_check()`

**Files to create**:
- `scripts/spec_manager/spec_manager/compliance/coverage/gate.py`

**Steps**:

1. In `config.py` (line 29), add `ENTITY_COVERAGE = "entity_coverage"` to the `GateId` enum after `PROVENANCE_COMPLETE`.

2. Create `gate.py` with:
   - `check_entity_coverage(evidence_index: EvidenceIndex, atom_registry: AtomRegistry, gate_spec: GateSpec, entities_artifact: EntitiesArtifact | None = None) -> GateCheckResult`: instantiates `EntityCoverageAnalyzer`, runs analysis, builds findings list from unmatched entities, compares `entity_coverage` ratio against `gate_spec.threshold`, returns `GateCheckResult` with `gate_id=GateId.ENTITY_COVERAGE.value`
   - `build_entity_coverage_report(evidence_index, atom_registry, entities_artifact) -> EntityCoverageReport`: convenience wrapper

3. In `orchestrator.py`:
   - Add import for `check_entity_coverage` from the new gate module
   - In `__init__()`, accept optional `evidence_index: EvidenceIndex | None = None` and `entities_artifact: EntitiesArtifact | None = None` parameters
   - In `run_all_checks()`, add step 6 for entity coverage (after architectural quality checks), following the same skip pattern used for pin coverage when the evidence index is not provided
   - In `run_single_check()`, add `GateId.ENTITY_COVERAGE` to the runners dict
   - Default mode: `GateMode.ADVISORY` (not blocking) since this is a new gate

4. In `config.py`, update `PromotionGateConfig.default()` to set `ENTITY_COVERAGE` to `GateMode.ADVISORY`.

**Tests to create**:
- `scripts/spec_manager/tests/compliance/coverage/test_gate.py`: test gate pass/fail with threshold, test skip when evidence index not provided

**Tests to modify**:
- `scripts/spec_manager/tests/compliance/promotion/test_config.py`: verify new gate ID exists
- `scripts/spec_manager/tests/compliance/promotion/test_orchestrator.py`: verify gate is wired (may need to mock evidence index)

### Plan 3: CLI Subcommand

**Goal**: Add a `coverage entity-gaps` CLI command for on-demand coverage analysis.

**Files to modify**:
- `scripts/spec_manager/spec_manager/cli.py`

**Files to create**:
- `scripts/spec_manager/spec_manager/compliance/coverage/cli.py`

**Steps**:

1. Create `cli.py` with:
   - `setup_coverage_parser(subparsers)`: adds `coverage` subparser with `entity-gaps` subcommand
   - `handle_coverage_command(args) -> int`: dispatches to subcommand handlers
   - `cmd_entity_gaps(args) -> int`: main handler that:
     - Accepts `run_id`, `--input-folder` (default "."), `--threshold` (default 0.0), `--format` (json/text, default text), `--output` (optional file path)
     - Loads `EvidenceIndex` from the workspace
     - Loads `AtomRegistry` from the branch layout
     - Optionally loads `EntitiesArtifact` if available
     - Runs `EntityCoverageAnalyzer.analyze()`
     - Prints coverage summary: total entities, total atoms, matched count, entity coverage %, atom coverage %
     - Lists unmatched entities with their names, kinds, and originating libraries
     - Lists unmatched atoms with their function names and kinds
     - If `--format json`, outputs `report.to_dict()` as JSON
     - If `--output`, writes to file
     - Returns 0 if coverage >= threshold, 1 otherwise

2. In `cli.py` main function:
   - Import and call `setup_coverage_parser(subparsers)` alongside the existing `setup_eval_parser` and `setup_pin_parser` calls (around line 1636)
   - Add `coverage` to the command dispatch (around line 1680), following the same pattern as `pin` and `eval` subgroups:
     ```python
     if args.command == "coverage":
         from spec_manager.compliance.coverage.cli import handle_coverage_command
         return handle_coverage_command(args)
     ```

**Tests to create**:
- `scripts/spec_manager/tests/compliance/coverage/test_cli.py`: test CLI argument parsing and basic output format

## Execution Instructions

Execute plans in order (Plan 1, then Plan 2, then Plan 3). Each plan is independently testable:

- **Plan 1**: Run `pytest scripts/spec_manager/tests/compliance/coverage/test_matching.py scripts/spec_manager/tests/compliance/coverage/test_analyzer.py -v`
- **Plan 2**: Run `pytest scripts/spec_manager/tests/compliance/coverage/test_gate.py scripts/spec_manager/tests/compliance/promotion/test_config.py -v`
- **Plan 3**: Run `pytest scripts/spec_manager/tests/compliance/coverage/test_cli.py -v` and manually test with `uv run spec-manager coverage entity-gaps <run_id>`

Use `uv run pytest -p no:randomly` if test ordering causes flakiness.

## Success Criteria

1. `EntityCoverageAnalyzer.analyze()` correctly identifies all three match types (explicit, naming, keyword) and produces accurate coverage ratios on synthetic test data.
2. The `ENTITY_COVERAGE` gate passes when entity coverage meets the configured threshold and fails when it does not.
3. The `coverage entity-gaps` CLI command prints a human-readable report and supports `--format json` output.
4. Existing compliance gate tests continue to pass (no regressions in `test_orchestrator.py`, `test_config.py`).
5. At least 90% line coverage on the new `compliance/coverage/` module.
6. All new modules follow existing patterns: dataclass-based results, `to_dict()` serialization, `GateCheckResult` integration.
