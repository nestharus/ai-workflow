# TODO(single-layer): NEW — Shape parser/loader (Sections 4, 5).
#   - Parse shape docs (controlled markdown format matching design/routing/*.md)
#   - Header fields: Classification, Package, Files, Role
#   - Sections: Systems, Surface API, Dependencies, Consumers, Verifiers
#   - Path→shape ownership mapping: file belongs to most specific shape whose
#     Package prefix contains it (Section 6.3 rule #1)
#   - Shape IDs (typed, stable)
#   - Dual storage (Section 5.1): system shapes in design/routing/ (committed),
#     run shapes in workspace/routing/ or workspace/shapes/ (per-run). Loader must
#     handle both paths.
#   - Derivation: from spec decomposition, design docs, planner decisions (Section 5.2)
#   - LLM may draft shapes as proposals; only active when saved + referenced by verifiers
#   - No function-level shapes — package/component granularity only (Section 4.2)
#   - Embedded contract blocks (Section 4.2/7): parse contract metadata within shape
#     docs as first-class data (EVENT_FLOW, DI_BINDING, etc.) for routing/verification
#   - Update rule (Section 5.3): shapes are used across all 3 phases
#     (Libraries, Architecture, Quality) — each phase may update shapes within its
#     authority scope. Verifiers must be updated alongside structural changes.
#     No auto-regeneration from code — updates are controlled spec-artifact edits.
#   - Skeleton lifecycle: shapes are proposed in Phase 0 as draft (PROPOSAL status),
#     then refined to non-draft (ACTIVE) during Libraries phase skeleton freeze.
#   - Index artifacts: routing/INDEX.md (human-readable) and routing/index.json
#     (machine-readable shape-pack index) generated/maintained on shape changes (Section 5.1)
# ALGORITHM(single-layer):
#   References: response3 Sections 4, 4.2, 5, 5.1, 5.2, 5.3, 6.3; evaluation modifications #1, #3, #5.
#   Phase model: 3 forward-only phases — Libraries → Architecture → Quality.
#     PhaseId = Literal['libraries', 'architecture', 'quality'].
#     Each phase edits code via its own PromotionLoop with IMPLEMENT step.
#     No backtracking: phases block (not demote) if they encounter something
#     outside their authority.
#   Skeleton lifecycle: shapes are proposed in Phase 0 as draft (PROPOSAL status).
#     During Libraries phase, library shapes are refined to non-draft (ACTIVE)
#     once verifiers are attached. Architecture phase creates/updates component-level
#     shapes and contracts within its own skeleton; library shapes remain ACTIVE.
#     Quality phase uses all shapes as-is (read-only).
#   Data structures (authoritative shared interface):
#     - ShapeId = NewType('ShapeId', str)  # canonical ID used across routing/work-items.
#     - VerifierSpec: {verifier_id: str, kind: Literal['TEST','IMPORT_BOUNDARY','COMMAND'], params: dict[str, Any], source_ref: str}.
#     - ShapeContract: {contract_id: str, kind: Literal['EVENT_FLOW','DI_BINDING','MIDDLEWARE_ORDERING','CUSTOM'], producer_shape_id: ShapeId|None, consumer_shape_ids: list[ShapeId], payload_schema_ref: str|None, verifier_ids: list[str], metadata: dict[str, Any]}.
#     - Shape: {shape_id: ShapeId, classification: str, package: str, files: list[str], role: str, systems: list[str], surface_api: list[str], dependencies_declared: list[ShapeId|str], consumers_declared: list[ShapeId|str], verifiers: list[VerifierSpec], contracts: list[ShapeContract], status: Literal['PROPOSAL','ACTIVE'], source_path: str, last_updated_phase: PhaseId|None}.
#     - ShapePackIndex: {system_shapes_dir: str, run_shapes_dir: str, shapes: dict[ShapeId, Shape], ownership_prefixes: list[tuple[str, ShapeId]], generated_at: str}.
#   Interface contracts:
#     - def parse_shape_document(path: Path) -> Shape
#     - def load_shape_pack(workspace_root: Path, run_root: Path|None = None) -> ShapePackIndex
#     - def resolve_shape_for_file(path: str, index: ShapePackIndex) -> ShapeId|None
#     - def bootstrap_shapes_from_spec(spec_components: list[dict[str, Any]], workspace_root: Path) -> list[Shape]
#     - def write_shape_index(index: ShapePackIndex) -> tuple[Path, Path]  # INDEX.md and index.json
#   Control flow:
#     1. Parse markdown deterministically: header keys (Classification/Package/Files/Role), required sections, optional sections, and embedded contract blocks.
#     2. Normalize package prefixes to POSIX-style path prefixes and sort descending by specificity for ownership rule (Section 6.3 rule #1).
#     3. Mark shape status ACTIVE only when verifier list is non-empty; otherwise PROPOSAL (evaluation modification #3).
#     4. Load both storage roots (design/routing and workspace/routing or workspace/shapes), merge by ShapeId with run-shape override, and emit deterministic index artifacts.
#     5. On Phase 0 bootstrap, derive initial shapes from spec decomposition outputs; first Libraries pass can run from spec inputs even if all shapes are PROPOSAL (evaluation modifications #1 and #5).
#     6. When shape document changes, emit metadata flag requires_verifier_refresh=True so Libraries phase can auto-create verifier work items (evaluation modification #3).
#   Error handling:
#     - Invalid header/section: raise ShapeParseError with file and line; caller records blocked ambiguity signal.
#     - Duplicate ShapeId with conflicting package prefix: raise ShapeConflictError.
#     - Unknown contract shape references: keep contract but add diagnostic and mark shape PROPOSAL until resolved.
#     - Missing both storage roots: return empty index plus diagnostic list; do not crash lifecycle.
#   Integration points:
#     - Called by: pdd_orchestrator Phase 0 bootstrap, matcher, monitor executor, planner/implementation scoping.
#     - Calls: config.PhaseId (IMPL(single-layer):
#       PhaseId lives in config.py, not run_state),
#       work_items for verifier-refresh metadata.
#   Test requirements:
#     - Parse valid/invalid markdown, including long contract sections.
#     - Ownership chooses most-specific package prefix.
#     - PROPOSAL vs ACTIVE status transition when verifiers are added/removed.
#     - Dual storage merge precedence and deterministic index.json/INDEX.md generation.
#     - Bootstrap creates initial shapes from spec decomposition and leaves first Libraries pass unblocked.

"""Shape document parsing, loading, and ownership mapping."""
