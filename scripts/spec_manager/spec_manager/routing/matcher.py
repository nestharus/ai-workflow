# TODO(single-layer): NEW — Shape matcher (Section 6).
#   - Compare declared (shape doc) vs observed (deterministic sources) structure
#   - Observed sources (Section 6.1):
#     Deterministic: file tree, import dependency scan, test results, manifests
#     LLM hints: call graph (CALL edges), analyze_source spans
#   - Produces ShapeMatchReport per shape (Section 6.2):
#     observed deps, declared deps, drift deltas, verifier results, diagnostics
#   - Matching rules (Section 6.3):
#     1. Ownership match (file → shape via path prefix, deterministic)
#     2. Dependency match (declared superset of observed, policy-controlled)
#     3. Contract match (verifier-backed)
#     4. Call graph match (non-authoritative, intra-scope targeting hint only)
#   - Intra-scope targeting hints (Section 8.2 step 2): call graph AND textual search
#     used to suggest where inside an owned file to apply a fix — both non-authoritative
#   - Outputs work items routed to the current phase's PromotionLoop (Section 8.2).
#     All 3 phases (Libraries, Architecture, Quality) edit code via IMPLEMENT step.
# IMPL(single-layer): Consume ownership via `routing.shapes.resolve_shape_for_file` so
# matcher/router/introduction checks share one most-specific-prefix rule.
# IMPL(single-layer): Shape pack input comes from merged `load_shape_pack` output; run
# shapes override system shapes on ShapeId collision before matching begins.
#   - Call graph classification role: the matcher does deterministic matching against
#     shapes. After matching, the call graph becomes the algorithm representation:
#     * Algorithm membership: surface API entrypoints as roots → reachable subgraphs
#       within shape → labeled with shape_id + algorithm_id
#     * Communication paths: cross-shape edges classified by declared contracts
#     * Logical vs structural: within-shape non-contract = logical;
#       contract-realizing or cross-shape = structural
#     * Classified call graph is authoritative as internal representation,
#       NOT as convergence evidence
#   - Contract-linked failure routing (Section 6.3/7.2/8.2): failing contract verifier
#     maps to the contract's referenced shapes (producer + consumer roles), not just
#     the file's owning shape. Producer/consumer role resolution is deterministic.
#   - Import-boundary violation routing (Section 8.2): boundary failure routes work
#     item to the producer shape (the shape whose boundary was violated)
#   - Ambiguity contract (Section 8.2): if intra-scope targeting is ambiguous,
#     emit CoordinationSignal and block — no guessing allowed
#   - Change propagation: git diff → changed files → shapes → neighbor shapes
#     via declared deps/consumers AND observed deps (import scan) → rerun verifiers
#     → emit work items (Section 8.3)
#   - Spec-change propagation (Section 8.3): when spec changes, emit work items for
#     contract updates and for adding missing contract-verification tests
#   - Deterministic authority boundary (Section 13.1): the authoritative evidence set
#     for matching is ONLY: shape doc parsing, import dependency scans, test pass/fail
#     results, file hashes/diffs, controlled manifests, config file parsing. LLM outputs
#     (call graph hints, analyze_source spans) are non-authoritative — they inform
#     intra-scope targeting but NEVER determine convergence or gate outcomes.
# ALGORITHM(single-layer):
#   References: response3 Sections 6, 6.1, 6.2, 6.3, 8.2, 8.3, 13.1; evaluation modifications #2 and #5.
#   Phase model: 3 forward-only phases — Libraries → Architecture → Quality.
#     PhaseId = Literal['libraries', 'architecture', 'quality'].
#     Each phase edits code via its own PromotionLoop with IMPLEMENT step.
#     No backtracking: phases block (not demote) if they encounter something
#     outside their authority.
#   Call graph classification (post-matching):
#     The call graph is a hint BEFORE classification. After deterministic
#     classification against shapes:
#     - Algorithm membership: surface API entrypoints as roots → reachable
#       subgraphs within shape → labeled with shape_id + algorithm_id.
#     - Communication paths: cross-shape edges classified by declared contracts.
#     - Logical vs structural: within-shape non-contract = logical;
#       contract-realizing or cross-shape = structural.
#     - Classified call graph is authoritative as internal representation,
#       NOT as convergence evidence.
#   Data structures (authoritative shared interface):
#     - ShapeMatchReport (defined here): {shape_id: ShapeId, declared_dependencies: set[str], observed_dependencies: set[str], missing_dependencies: set[str], unexpected_dependencies: set[str], contract_results: dict[str, VerifierResult], verifier_results: list[VerifierResult], ownership_files: list[str], targeting_hints: dict[str, list[str]], diagnostics: list[str], status: Literal['MATCHED','DRIFT','AMBIGUOUS','BLOCKED']}.
#     - MatchPolicy: {dependency_mode: Literal['declared_superset','exact','allowlist_only'], allow_unknown_shapes: bool, ambiguity_blocking: bool}.
#   Interface contracts:
#     - def build_observed_dependency_graph(workspace_root: Path) -> dict[str, set[str]]
#     - def match_shape(shape: Shape, index: ShapePackIndex, observed_graph: dict[str, set[str]], verifier_results: list[VerifierResult], policy: MatchPolicy) -> ShapeMatchReport
#     - def match_all_shapes(index: ShapePackIndex, observed_graph: dict[str, set[str]], verifier_results_by_shape: dict[ShapeId, list[VerifierResult]], policy: MatchPolicy) -> dict[ShapeId, ShapeMatchReport]
#     - def generate_work_items_from_reports(reports: dict[ShapeId, ShapeMatchReport], phase: PhaseId, cycle: int) -> list[WorkItem]
#     - def propagate_changes(changed_files: list[str], index: ShapePackIndex, observed_graph: dict[str, set[str]]) -> set[ShapeId]
#   Control flow:
#     1. Build deterministic observations (file ownership, import edges, test/verifier results, manifests); never use LLM output as authority.
#     2. For each shape, evaluate ownership, dependency policy deltas, and contract/verifier outcomes; construct ShapeMatchReport.
#     3. For failing contract verifiers, route to producer/consumer shapes from contract metadata, not only failing file owner.
#     4. For import-boundary violations, route remediation to violating producer shape per Section 8.2.
#     5. Generate work items for the current phase's PromotionLoop; each phase (Libraries, Architecture, Quality) edits code via IMPLEMENT step (evaluation modification #2).
#     6. For ambiguity in intra-scope targeting (call graph/text search hints disagree or empty), emit blocking coordination signal and no auto-targeting.
#     7. On cycle 1 (first Libraries pass), if reports are sparse because shapes are proposals, still allow spec-input work and emit verifier-creation work items.
#     8. For later cycles, changed files -> owning shapes -> neighbor shapes (declared + observed deps) -> rerun verifiers -> emit follow-up work items.
# IMPL(single-layer): Treat `Shape.status` as verifier-derived authority (`ACTIVE` only with
# verifiers); proposal-only shapes in first Libraries cycle should trigger verifier-refresh
# work item generation, not hard convergence failure.
#   Error handling:
#     - Missing ownership: create spec_change work item tagged 'shape_missing_owner'.
#     - Import scanner failure: mark report BLOCKED with deterministic diagnostic; do not fallback to LLM inference.
#     - Verifier result missing for ACTIVE shape: treat as failure and emit work item for current phase.
#   Integration points:
#     - Called by: pdd_lifecycle all phases (libraries/architecture/quality), monitors, demotion router.
#     - Calls: routing.shapes, routing.verifiers, coordination.work_items, call_graph hint provider (non-authoritative only).
#   Test requirements:
#     - Dependency drift scenarios for each policy mode.
#     - Contract failure routes to producer+consumer shape IDs.
#     - Ambiguity causes block signal, not guessed file/function target.
#     - Change propagation fans out to neighbor shapes and schedules verifier reruns.
#     - First-cycle behavior allows Libraries phase from spec input even with proposal-only shapes.
#     - Call graph classification: algorithm membership labels, communication path types, logical-vs-structural edge classification.

"""Shape matching: compare declared vs observed structure, emit work items."""
