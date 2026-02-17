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
# IMPL(single-layer): `ShapeMatchReport.status` is deterministic-state driven:
# `MATCHED` requires empty dependency drift + passing required verifiers; `DRIFT`
# captures deterministic dependency/contract deltas; `AMBIGUOUS` is reserved for
# unresolved intra-scope targeting; `BLOCKED` is for missing deterministic inputs or
# scanner/tooling failure states.
# IMPL(single-layer): Treat `routing.verifiers.VerifierResult` as the canonical
# verifier payload contract when normalizing matcher input/output surfaces.
#   Interface contracts:
#     - def build_observed_dependency_graph(workspace_root: Path) -> dict[str, set[str]]
#     - def match_shape(shape: Shape, index: ShapePackIndex, observed_graph: dict[str, set[str]], verifier_results: list[VerifierResult], policy: MatchPolicy) -> ShapeMatchReport
#     - def match_all_shapes(index: ShapePackIndex, observed_graph: dict[str, set[str]], verifier_results_by_shape: dict[ShapeId, list[VerifierResult]], policy: MatchPolicy) -> dict[ShapeId, ShapeMatchReport]
#     - def generate_work_items_from_reports(reports: dict[ShapeId, ShapeMatchReport], phase: PhaseId, cycle: int) -> list[WorkItem]
#     - def propagate_changes(changed_files: list[str], index: ShapePackIndex, observed_graph: dict[str, set[str]]) -> set[ShapeId]
# IMPL(single-layer): `generate_work_items_from_reports` emits external work items
# (never code markers) keyed by `shape_id`, with `required_change_type` and evidence
# refs; file/function anchors are optional targeting hints only (Section 8.1/8.2).
#   Control flow:
#     1. Build deterministic observations (file ownership, import edges, test/verifier results, manifests); never use LLM output as authority.
#     2. For each shape, evaluate ownership, dependency policy deltas, and contract/verifier outcomes; construct ShapeMatchReport.
#     3. For failing contract verifiers, route to producer/consumer shapes from contract metadata, not only failing file owner.
# IMPL(single-layer): Contract-linked routing fans out per contract role so producer
# and consumer shapes each receive phase-local remediation work when their shared
# verifier fails.
#     4. For import-boundary violations, route remediation to violating producer shape per Section 8.2.
#     5. Generate work items for the current phase's PromotionLoop; each phase (Libraries, Architecture, Quality) edits code via IMPLEMENT step (evaluation modification #2).
#     6. For ambiguity in intra-scope targeting (call graph/text search hints disagree or empty), emit blocking coordination signal and no auto-targeting.
#     7. On cycle 1 (first Libraries pass), if reports are sparse because shapes are proposals, still allow spec-input work and emit verifier-creation work items.
#     8. For later cycles, changed files -> owning shapes -> neighbor shapes (declared + observed deps) -> rerun verifiers -> emit follow-up work items.
# IMPL(single-layer): `propagate_changes` neighborhood expansion must union declared
# deps/consumers from shape docs with observed import edges before scheduling verifier
# reruns (Section 8.3).
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
# IMPL(single-layer): Downstream modules should import matcher contracts via
# `spec_manager.routing` re-exports to keep a single stable routing API surface.
#   Test requirements:
#     - Dependency drift scenarios for each policy mode.
#     - Contract failure routes to producer+consumer shape IDs.
#     - Ambiguity causes block signal, not guessed file/function target.
#     - Change propagation fans out to neighbor shapes and schedules verifier reruns.
#     - First-cycle behavior allows Libraries phase from spec input even with proposal-only shapes.
#     - Call graph classification: algorithm membership labels, communication path types, logical-vs-structural edge classification.

"""Shape matching: compare declared vs observed structure, emit work items."""

from __future__ import annotations

import ast
import hashlib
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NewType

from spec_manager.compliance.promotion.config import PhaseId
from spec_manager.routing.shapes import Shape, ShapeId, ShapePackIndex, resolve_shape_for_file

logger = logging.getLogger(__name__)

MatchStatus = Literal["MATCHED", "DRIFT", "AMBIGUOUS", "BLOCKED"]
DependencyMode = Literal["declared_superset", "exact", "allowlist_only"]
RequiredChangeType = Literal["behavior_change", "wiring_only", "refactor_only", "spec_change"]


class _ShapeIdSet(set[str]):
    pass


def _utcnow() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


@dataclass
class MatchPolicy:
    dependency_mode: DependencyMode = "declared_superset"
    allow_unknown_shapes: bool = False
    ambiguity_blocking: bool = True


@dataclass
class VerifierResult:
    shape_id: str
    verifier_id: str
    kind: str
    passed: bool
    evidence_refs: list[str] = field(default_factory=list)
    summary: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    deterministic: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ShapeMatchReport:
    shape_id: ShapeId
    declared_dependencies: set[str] = field(default_factory=set)
    observed_dependencies: set[str] = field(default_factory=set)
    missing_dependencies: set[str] = field(default_factory=set)
    unexpected_dependencies: set[str] = field(default_factory=set)
    contract_results: dict[str, VerifierResult] = field(default_factory=dict)
    verifier_results: list[VerifierResult] = field(default_factory=list)
    ownership_files: list[str] = field(default_factory=list)
    targeting_hints: dict[str, list[str]] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)
    status: MatchStatus = "MATCHED"


WorkItemId = NewType("WorkItemId", str)


@dataclass
class WorkItemLocation:
    file: str = ""
    symbol: str = ""
    line_start: int = 0


@dataclass
class WorkItem:
    work_item_id: str
    run_id: str
    slice_id: str
    title: str
    description: str
    shape_id: ShapeId
    created_in_phase: PhaseId
    required_change_type: RequiredChangeType
    status: str
    kind: str = "SHAPE_MATCH"
    priority: str = "normal"
    file_locations: list[WorkItemLocation] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    contract_ids: list[str] = field(default_factory=list)
    verifier_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


_WORK_ITEM_SCANNING_SENTINEL = "__matcher_import_scanner_error__"
_FILE_UNKNOWN_PREFIX = "file:"
_IGNORE_DIRS = {
    ".git",
    ".venv",
    "dist",
    "build",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


def _normalize_shape_id(value: Any) -> str:
    normalized = str(value).strip()
    return normalized


def _normalize_graph_path(path: str | Path) -> str:
    text = str(path).replace("\\", "/").replace(" ", "-").lower().strip()
    if len(text) >= 2 and text[1] == ":":
        text = text[2:]
    if text.startswith("/"):
        text = text.lstrip("/")
    if text.startswith("workspace/"):
        text = text[len("workspace/") :]
    if text.startswith("runs/"):
        text = text[len("runs/") :]
    if text.startswith("routing/"):
        text = text[len("routing/") :]
    if text.endswith("/"):
        text = text.rstrip("/")
    return text


def _is_hidden_dir(path: Path) -> bool:
    return any(part in _IGNORE_DIRS for part in path.parts)


def _iter_python_files(workspace_root: Path) -> list[Path]:
    if not workspace_root.exists():
        return []
    files: list[Path] = []
    for path in workspace_root.rglob("*.py"):
        if not path.is_file():
            continue
        if _is_hidden_dir(path):
            continue
        files.append(path)
    return sorted(files)


def _candidate_targets_from_import_parts(
    workspace_root: Path,
    source_path: Path,
    *,
    base_modules: list[str],
    rel_level: int,
) -> set[str]:
    candidates: set[str] = set()
    source_parent = source_path.parent
    for module_name in base_modules:
        if rel_level:
            anchor = source_parent
            for _ in range(rel_level):
                if anchor.parent == anchor:
                    break
                anchor = anchor.parent
            module_parts = [part for part in module_name.split(".") if part]
            module_path = anchor.joinpath(*module_parts) if module_parts else anchor
        else:
            module_parts = [part for part in module_name.split(".") if part]
            module_path = workspace_root.joinpath(*module_parts) if module_parts else workspace_root
        if module_path.is_file():
            candidates.add(_normalize_graph_path(module_path))
            continue
        module_file = module_path.with_suffix(".py")
        if module_file.is_file():
            candidates.add(_normalize_graph_path(module_file))
        package_file = module_path / "__init__.py"
        if package_file.is_file():
            candidates.add(_normalize_graph_path(package_file))
    return candidates


def _parse_verifier_result_item(
    raw: Any,
) -> VerifierResult:
    if isinstance(raw, VerifierResult):
        return raw
    if isinstance(raw, dict):
        shape_id = _normalize_shape_id(raw.get("shape_id"))
        verifier_id = _normalize_shape_id(raw.get("verifier_id"))
        kind = str(raw.get("kind", "") or "").strip().upper() or "UNKNOWN"
        passed = bool(raw.get("passed", False))
        evidence_refs = [str(item).strip() for item in raw.get("evidence_refs", []) if str(item).strip()]
        summary = str(raw.get("summary", "") or "")
        started_at = str(raw.get("started_at", ""))
        finished_at = str(raw.get("finished_at", ""))
        duration = float(raw.get("duration_ms", 0.0) or 0.0)
        deterministic = bool(raw.get("deterministic", True))
        error = raw.get("error")
        metadata = raw.get("metadata", {})
        return VerifierResult(
            shape_id=shape_id,
            verifier_id=verifier_id,
            kind=kind,
            passed=passed,
            evidence_refs=evidence_refs,
            summary=summary,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration,
            deterministic=deterministic,
            error=error if error is None or isinstance(error, str) else str(error),
            metadata=metadata if isinstance(metadata, dict) else {},
        )
    return VerifierResult(
        shape_id="",
        verifier_id="",
        kind="UNKNOWN",
        passed=False,
        summary="invalid verifier payload",
        deterministic=True,
    )


def _missing_verifier_result(shape_id: ShapeId, verifier_id: str) -> VerifierResult:
    normalized = _normalize_shape_id(verifier_id)
    return VerifierResult(
        shape_id=str(shape_id),
        verifier_id=normalized,
        kind="UNKNOWN",
        passed=False,
        summary=f"Missing verifier result for {normalized}",
        evidence_refs=[f"missing-verifier:{normalized}"],
        error="missing verifier result",
        deterministic=True,
    )


def _coerce_shape_refs(values: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(values, (list, tuple, set, frozenset)):
        for item in values:
            normalized = _normalize_shape_id(item)
            if normalized:
                refs.add(normalized)
    else:
        normalized = _normalize_shape_id(values)
        if normalized:
            refs.add(normalized)
    return refs


def _extract_verifier_result_errors(verifiers: list[VerifierResult]) -> tuple[bool, bool, list[str], list[str]]:
    missing = [v for v in verifiers if v.error == "missing verifier result"]
    failing = [v for v in verifiers if not v.passed]
    missing_verifiers = [v.verifier_id for v in missing]
    failing_verifiers = [v.verifier_id for v in failing]
    return bool(missing), bool(failing), missing_verifiers, failing_verifiers


def _contains_ownership_gap(report: ShapeMatchReport) -> bool:
    return any("no currently observable owned files" in item for item in report.diagnostics)


def build_observed_dependency_graph(workspace_root: Path) -> dict[str, set[str]]:
    workspace_root = Path(workspace_root)
    graph: dict[str, set[str]] = defaultdict(set)

    python_files = _iter_python_files(workspace_root)
    for source in python_files:
        normalized_source = _normalize_graph_path(source)
        if not normalized_source:
            continue
        try:
            content = source.read_text(encoding="utf-8", errors="ignore")
            module = ast.parse(content)
        except Exception as exc:
            graph[normalized_source]
            graph[_WORK_ITEM_SCANNING_SENTINEL].add(f"{normalized_source}: {exc}")
            logger.warning("Dependency scan parse failure for %s", source)
            continue

        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                base_names: list[str] = []
                for item in node.names:
                    if not str(item.name).strip():
                        continue
                    base_names.append(str(item.name).strip())
                targets = _candidate_targets_from_import_parts(
                    workspace_root=workspace_root,
                    source_path=source,
                    base_modules=base_names,
                    rel_level=0,
                )
                graph[normalized_source].update(targets)
            elif isinstance(node, ast.ImportFrom):
                base_module = str(node.module or "").strip()
                alias_names = [str(item.name).strip() for item in node.names if str(item.name).strip() and item.name != "*"]
                module_names = [base_module] if base_module else []
                for alias_name in alias_names:
                    if base_module:
                        module_names.append(f"{base_module}.{alias_name}")
                    else:
                        module_names.append(alias_name)
                targets = _candidate_targets_from_import_parts(
                    workspace_root=workspace_root,
                    source_path=source,
                    base_modules=[m for m in module_names if m],
                    rel_level=int(getattr(node, "level", 0) or 0),
                )
                graph[normalized_source].update(targets)

    return dict(graph)


def match_shape(
    shape: Shape,
    index: ShapePackIndex,
    observed_graph: dict[str, set[str]],
    verifier_results: list[Any],
    policy: MatchPolicy,
) -> ShapeMatchReport:
    policy_mode = policy.dependency_mode
    normalized_shape_id = str(shape.shape_id)
    ownership_files = [
        _normalize_graph_path(item)
        for item in sorted(set(shape.files))
        if str(item).strip()
    ]
    for source_path in sorted(observed_graph):
        if source_path == _WORK_ITEM_SCANNING_SENTINEL:
            continue
        owner = resolve_shape_for_file(source_path, index)
        if owner == shape.shape_id and source_path not in ownership_files:
            ownership_files.append(source_path)

    if _WORK_ITEM_SCANNING_SENTINEL in observed_graph:
        return ShapeMatchReport(
            shape_id=shape.shape_id,
            declared_dependencies=set(_normalize_shape_id(item) for item in shape.dependencies_declared),
            observed_dependencies=set(),
            missing_dependencies=set(),
            unexpected_dependencies=set(),
            contract_results={},
            verifier_results=[],
            ownership_files=ownership_files,
            diagnostics=[
                "Import scanner failure detected. Matching is blocked until scanner inputs are restored."
            ],
            status="BLOCKED",
        )

    declared_dependencies = _coerce_shape_refs(shape.dependencies_declared)
    declared_dependencies.discard(normalized_shape_id)
    normalized_verifier_results: list[VerifierResult] = []
    for raw_result in verifier_results:
        parsed_result = _parse_verifier_result_item(raw_result)
        result_shape_id = _normalize_shape_id(parsed_result.shape_id)
        if result_shape_id in ("", normalized_shape_id):
            normalized_verifier_results.append(parsed_result)

    normalized_by_id: dict[str, VerifierResult] = {}
    for result in normalized_verifier_results:
        normalized_by_id[result.verifier_id] = result

    required_verifiers = [v.verifier_id for v in shape.verifiers if str(v.verifier_id).strip()]
    for required_id in required_verifiers:
        if required_id not in normalized_by_id:
            normalized_by_id[required_id] = _missing_verifier_result(shape.shape_id, required_id)

    normalized_verifiers = list(normalized_by_id.values())
    observed_dependencies: set[str] = set()
    unknown_dependencies: set[str] = set()
    for owned_file in ownership_files:
        for target in observed_graph.get(owned_file, set()):
            if target == _WORK_ITEM_SCANNING_SENTINEL:
                continue
            target_shape = resolve_shape_for_file(target, index)
            if target_shape is None:
                if policy.allow_unknown_shapes:
                    continue
                unknown_dependencies.add(f"{_FILE_UNKNOWN_PREFIX}{target}")
                continue
            if str(target_shape) == normalized_shape_id:
                continue
            observed_dependencies.add(str(target_shape))

    missing_dependencies = declared_dependencies - observed_dependencies

    if policy_mode == "exact":
        unexpected_dependencies = observed_dependencies - declared_dependencies
    elif policy_mode in {"declared_superset", "allowlist_only"}:
        unexpected_dependencies = {
            dep
            for dep in observed_dependencies | unknown_dependencies
            if dep not in declared_dependencies
        }
    else:
        unexpected_dependencies = observed_dependencies - declared_dependencies
    unexpected_dependencies |= unknown_dependencies

    missing_required = [item for item in required_verifiers if item in normalized_by_id and normalized_by_id[item].error == "missing verifier result"]
    failing_verifiers = [item for item in normalized_by_id.values() if not item.passed]
    contract_results: dict[str, VerifierResult] = {}
    failing_contracts: list[str] = []
    for contract in shape.contracts:
        contract_verifiers: list[VerifierResult] = []
        for contract_verifier in contract.verifier_ids:
            ref = _normalize_shape_id(contract_verifier)
            if not ref:
                continue
            contract_verifiers.append(
                normalized_by_id.get(ref, _missing_verifier_result(shape.shape_id, ref))
            )

        if not contract.verifier_ids:
            missing = [
                VerifierResult(
                    shape_id=str(shape.shape_id),
                    verifier_id=f"contract:{contract.contract_id}",
                    kind="CONTRACT",
                    passed=False,
                    evidence_refs=[f"contract:{contract.contract_id}:missing-verifier-ids"],
                    summary=f"contract '{contract.contract_id}' has no verifier ids",
                    error="missing contract verifier metadata",
                    deterministic=True,
                )
            ]
            contract_verifiers.extend(missing)

        passed = all(item.passed for item in contract_verifiers)
        evidence_refs: list[str] = []
        for item in contract_verifiers:
            if item.verifier_id:
                evidence_refs.extend(item.evidence_refs or [])
                if item.error:
                    evidence_refs.append(item.error)
        if not passed:
            failing_contracts.append(contract.contract_id)
        route_shape_ids = [
            _normalize_shape_id(contract.producer_shape_id),
            *[_normalize_shape_id(item) for item in contract.consumer_shape_ids],
        ]
        route_shape_ids = [item for item in route_shape_ids if item]
        route_shape_ids = list(dict.fromkeys(route_shape_ids))
        metadata = {
            "producer_shape_id": route_shape_ids[0] if route_shape_ids else str(shape.shape_id),
            "consumer_shape_ids": [item for item in route_shape_ids if item != route_shape_ids[0]],
            "route_shape_ids": route_shape_ids,
        }
        route = route_shape_ids[0] if route_shape_ids else str(shape.shape_id)
        if route:
            route_shape = route
        else:
            route_shape = str(shape.shape_id)
        contract_results[contract.contract_id] = VerifierResult(
            shape_id=route_shape,
            verifier_id=contract.contract_id,
            kind="CONTRACT",
            passed=passed,
            evidence_refs=evidence_refs,
            summary="contract check failed" if not passed else "contract check passed",
            deterministic=True,
            metadata=metadata,
        )

    diagnostics: list[str] = []
    if not ownership_files and shape.files:
        diagnostics.append("shape has no currently observable owned files")

    has_missing = bool(missing_required)
    has_dependency_violation = False
    if policy_mode == "exact":
        has_dependency_violation = bool(missing_dependencies or unexpected_dependencies)
    elif policy_mode in {"declared_superset", "allowlist_only"}:
        has_dependency_violation = bool(unexpected_dependencies)

    has_contract_failure = any(not item.passed for item in contract_results.values())
    has_verifier_failure = any(not item.passed for item in normalized_verifiers if item.kind != "CONTRACT")

    targeting_hints: dict[str, list[str]] = {}
    if ownership_files:
        targeting_hints["owned_files"] = ownership_files[:25]
    if shape.surface_api:
        targeting_hints["surface_api"] = list(shape.surface_api)
    if shape.contracts:
        targeting_hints["contracts"] = [str(contract.contract_id) for contract in shape.contracts]

    status: MatchStatus = "MATCHED"
    if has_dependency_violation or has_verifier_failure or has_contract_failure or has_missing:
        status = "DRIFT"
    if (
        policy.ambiguity_blocking
        and status == "DRIFT"
        and not ownership_files
        and not shape.surface_api
    ):
        status = "AMBIGUOUS"
    if has_missing:
        diagnostics.append(
            "missing verifier result(s): " + ", ".join(sorted(missing_required))
        )
    if missing_dependencies:
        diagnostics.append(
            "missing declared dependencies: " + ", ".join(sorted(missing_dependencies))
        )
    if unexpected_dependencies:
        diagnostics.append(
            "unexpected observed dependencies: " + ", ".join(sorted(unexpected_dependencies))
        )
    if has_contract_failure:
        diagnostics.append(
            "contract verifier failures: " + ", ".join(sorted(failing_contracts or ["<none>"]))
        )

    return ShapeMatchReport(
        shape_id=shape.shape_id,
        declared_dependencies=declared_dependencies,
        observed_dependencies=observed_dependencies,
        missing_dependencies=missing_dependencies,
        unexpected_dependencies=unexpected_dependencies,
        contract_results=contract_results,
        verifier_results=normalized_verifiers,
        ownership_files=ownership_files,
        targeting_hints=targeting_hints,
        diagnostics=diagnostics,
        status=status,
    )


def match_all_shapes(
    index: ShapePackIndex,
    observed_graph: dict[str, set[str]],
    verifier_results_by_shape: dict[ShapeId, list[Any]],
    policy: MatchPolicy,
) -> dict[ShapeId, ShapeMatchReport]:
    reports: dict[ShapeId, ShapeMatchReport] = {}
    for shape_id in sorted(index.shapes, key=lambda item: str(item)):
        shape = index.shapes[shape_id]
        verifier_input = verifier_results_by_shape.get(shape_id, [])
        report = match_shape(shape, index, observed_graph, verifier_input, policy)
        reports[shape_id] = report
    return reports


def _make_work_item(
    *,
    shape_id: ShapeId,
    phase: PhaseId,
    title: str,
    description: str,
    required_change_type: RequiredChangeType,
    status: str,
    evidence_refs: list[str] | None = None,
    file_locations: list[str] | None = None,
    contract_ids: list[str] | None = None,
    verifier_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> WorkItem:
    item_suffix = "|".join(
        part for part in [str(shape_id), str(required_change_type), title.lower()] if part
    )
    item_hash = hashlib.sha1(item_suffix.encode("utf-8")).hexdigest()[:16]
    return WorkItem(
        work_item_id=str(WorkItemId(f"{shape_id}:{required_change_type}:{item_hash}")),
        run_id="",
        slice_id="",
        title=title,
        description=description,
        shape_id=shape_id,
        created_in_phase=phase,
        required_change_type=required_change_type,
        status=status,
        kind="SHAPE_MATCH",
        priority="normal",
        file_locations=[
            WorkItemLocation(file=str(file), symbol="", line_start=0)
            for file in (file_locations or [])
        ],
        evidence_refs=evidence_refs or [],
        contract_ids=contract_ids or [],
        verifier_ids=verifier_ids or [],
        metadata=metadata or {},
    )


def _collect_verifier_failures(verifier_results: list[VerifierResult]) -> list[VerifierResult]:
    return [item for item in verifier_results if not item.passed]


def generate_work_items_from_reports(
    reports: dict[ShapeId, ShapeMatchReport],
    phase: PhaseId,
    cycle: int,
) -> list[WorkItem]:
    work_items: list[WorkItem] = []
    for shape_id, report in reports.items():
        status = report.status
        if status == "BLOCKED":
            # blocked states should always create a spec-facing remediation item.
            work_items.append(
                _make_work_item(
                    shape_id=shape_id,
                    phase=phase,
                    title="Matcher blocked for shape",
                    description=" | ".join(report.diagnostics) or "Matcher reported blocked state without details.",
                    required_change_type="spec_change",
                    status="BLOCKED",
                    evidence_refs=[f"matcher:{shape_id}:blocked"],
                    file_locations=report.ownership_files,
                    metadata={"status": "blocked", "cycle": cycle},
                )
            )
            continue
        if status == "AMBIGUOUS":
            work_items.append(
                _make_work_item(
                    shape_id=shape_id,
                    phase=phase,
                    title="Matcher ambiguous targeting",
                    description="Intra-scope targeting is ambiguous; coordination block required.",
                    required_change_type="spec_change",
                    status="BLOCKED",
                    evidence_refs=[f"matcher:{shape_id}:ambiguous"],
                    file_locations=report.ownership_files,
                    metadata={"status": "ambiguous", "cycle": cycle},
                )
            )
            continue

        if _contains_ownership_gap(report):
            work_items.append(
                _make_work_item(
                    shape_id=shape_id,
                    phase=phase,
                    title="Shape ownership missing",
                    description="Shape files are not matched by current workspace ownership rules.",
                    required_change_type="spec_change",
                    status="NEW",
                    evidence_refs=[f"shape_missing_owner:{shape_id}"],
                    file_locations=[],
                    metadata={"status": status, "cycle": cycle},
                )
            )

        if status == "DRIFT" or status == "MATCHED":
            if report.missing_dependencies:
                work_items.append(
                    _make_work_item(
                        shape_id=shape_id,
                        phase=phase,
                        title="Shape dependency drift",
                        description="Missing declared dependencies from observed execution graph.",
                        required_change_type="wiring_only",
                        status="NEW",
                        evidence_refs=[
                            f"missing:{item}" for item in sorted(report.missing_dependencies)
                        ],
                        file_locations=report.ownership_files,
                        metadata={
                            "declared": sorted(report.declared_dependencies),
                            "observed": sorted(report.observed_dependencies),
                            "status": status,
                            "cycle": cycle,
                        },
                    )
                )

            if report.unexpected_dependencies:
                work_items.append(
                    _make_work_item(
                        shape_id=shape_id,
                        phase=phase,
                        title="Unexpected dependency boundary",
                        description="Observed dependency observed outside allowlist.",
                        required_change_type="wiring_only",
                        status="NEW",
                        evidence_refs=[
                            f"unexpected:{item}" for item in sorted(report.unexpected_dependencies)
                        ],
                        file_locations=report.ownership_files,
                        metadata={
                            "declared": sorted(report.declared_dependencies),
                            "observed": sorted(report.observed_dependencies),
                            "status": status,
                            "cycle": cycle,
                        },
                    )
                )

            failing_verifiers = _collect_verifier_failures(report.verifier_results)
            if failing_verifiers:
                verifier_refs = [f"{item.verifier_id}" for item in failing_verifiers if item.verifier_id]
                work_items.append(
                    _make_work_item(
                        shape_id=shape_id,
                        phase=phase,
                        title="Verifier failure",
                        description="One or more required verifiers failed.",
                        required_change_type="behavior_change",
                        status="NEW",
                        evidence_refs=[f"verifier:{item.verifier_id}" for item in failing_verifiers],
                        file_locations=report.ownership_files,
                        verifier_ids=verifier_refs,
                        metadata={
                            "failed_verifiers": verifier_refs,
                            "cycle": cycle,
                        },
                    )
                )

            for contract_id, contract_result in report.contract_results.items():
                if contract_result.passed:
                    continue
                route_shape_ids = list(
                    dict.fromkeys(
                        [str(contract_result.shape_id)]
                        + [
                            str(item)
                            for item in contract_result.metadata.get("route_shape_ids", [])
                        ]
                    )
                )
                for route_shape in route_shape_ids:
                    target_shape = ShapeId(_normalize_shape_id(route_shape)) if route_shape else shape_id
                    work_items.append(
                        _make_work_item(
                            shape_id=target_shape,
                            phase=phase,
                            title=f"Contract verification failed: {contract_id}",
                            description=contract_result.summary or "Contract check failed.",
                            required_change_type="behavior_change",
                            status="NEW",
                            evidence_refs=[f"contract:{contract_id}"],
                            contract_ids=[contract_id],
                            metadata={
                                "producer": contract_result.metadata.get("producer_shape_id"),
                                "consumers": contract_result.metadata.get("consumer_shape_ids", []),
                                "cycle": cycle,
                            },
                        )
                    )

        if (
            phase == "libraries"
            and cycle <= 1
            and status != "BLOCKED"
            and status != "AMBIGUOUS"
            and not report.verifier_results
        ):
            work_items.append(
                _make_work_item(
                    shape_id=shape_id,
                    phase=phase,
                    title="Proposal shape needs verifier refresh",
                    description="No verifier evidence available for PROPOSAL shape; schedule verifier bootstrap.",
                    required_change_type="spec_change",
                    status="NEW",
                    evidence_refs=[f"verifier_refresh:{shape_id}"],
                    file_locations=report.ownership_files,
                    metadata={"reason": "proposal_or_missing_verifier", "cycle": cycle},
                )
            )
    return work_items


def propagate_changes(
    changed_files: list[str],
    index: ShapePackIndex,
    observed_graph: dict[str, set[str]],
) -> set[ShapeId]:
    affected: set[ShapeId] = set()
    queue: deque[ShapeId] = deque()

    for path in changed_files:
        shape_id = resolve_shape_for_file(str(path), index)
        if shape_id is None:
            continue
        if shape_id not in affected:
            affected.add(shape_id)
            queue.append(shape_id)

    file_owner: dict[str, ShapeId] = {}
    for source in observed_graph:
        if source == _WORK_ITEM_SCANNING_SENTINEL:
            continue
        owner = resolve_shape_for_file(source, index)
        if owner is not None:
            file_owner[source] = owner

    while queue:
        current = queue.popleft()
        shape = index.shapes.get(current)
        if shape is None:
            continue

        outbound: set[ShapeId] = set()
        for item in shape.dependencies_declared + shape.consumers_declared:
            candidate = _normalize_shape_id(item)
            if not candidate:
                continue
            if candidate in index.shapes:
                outbound.add(index.shapes[candidate].shape_id)
        for source, target_shape in file_owner.items():
            if target_shape != current:
                continue
            for observed in observed_graph.get(source, set()):
                target = resolve_shape_for_file(observed, index)
                if target is None:
                    continue
                if target not in index.shapes:
                    continue
                outbound.add(target)

        for neighbor in outbound:
            if neighbor in affected:
                continue
            affected.add(neighbor)
            queue.append(neighbor)

    return affected
