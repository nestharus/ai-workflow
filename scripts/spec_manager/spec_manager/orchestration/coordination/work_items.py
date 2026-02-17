# TODO(single-layer): RESTRUCTURE — Work items gain shape_id as primary routing handle
#   (Section 8.1). Add fields: shape_id, required_change_type (behavior_change |
#   wiring_only | refactor_only | spec_change), evidence references (failing tests,
#   drift report, constraint refs). The 3-stage search and JSONL audit store KEEP.
#   Work items become the universal mechanism replacing both TODO comments and
#   demotion tickets — external, durable, shape-routed (Section 8).
#   Work items are routed within the current phase (not re-triaged across phases).
# ALGORITHM(single-layer):
#   References: response3 Sections 8.1, 8.2, 8.3; evaluation modification #3.
#   Data structures (authoritative shared interface):
#     - WorkItem dataclass must include: {work_item_id: str, run_id: str, slice_id: str, title: str, description: str, shape_id: ShapeId, created_in_phase: PhaseId, required_change_type: Literal['behavior_change','wiring_only','refactor_only','spec_change'], status: STATUS, kind: str, priority: str, file_locations: list[WorkItemLocation], evidence_refs: list[str], contract_ids: list[str], verifier_ids: list[str], created_at: str, updated_at: str, metadata: dict[str, Any]}.
#     - Routing uses shape_id + required_change_type + active phase authority (not target_phase).
#       created_in_phase is metadata (audit trail), not a routing field.
#     - PhaseId = Literal['libraries', 'architecture', 'quality'] (3 forward-only phases; no cycling back).
#     - Each phase edits code via its own PromotionLoop with IMPLEMENT step (no "refinement-only" phases).
#     - WorkItemLocation: {file_path: str, line_start: int|None, line_end: int|None, symbol: str|None}.
#   Interface contracts:
#     - def create(self, item: WorkItem) -> WorkItem
#     - def upsert(self, item: WorkItem, merge_policy: Literal['replace','append_evidence']) -> WorkItem
#     - def list_open(self, phase: PhaseId|None = None, shape_id: ShapeId|None = None) -> list[WorkItem]
#     - def search(self, query: SearchQuery) -> list[SearchResult]
#   Control flow:
#     1. Validate required shape_id/created_in_phase/required_change_type before persistence.
#     2. Persist append-only JSONL event and update compact index atomically.
#     3. Keep existing 3-stage search pipeline, adding shape_id and phase filters to candidate narrowing.
#     4. Work items are resolved within the owning phase's PromotionLoop cycle (phase-local remediation or block); no re-triage to a different phase.
#   Error handling:
#     - Invalid status transition by kind rejects update with explicit error.
#     - Corrupt JSONL/index triggers rebuild from audit log.
#   Integration points:
#     - Called by matcher, demotion router, findings converter, lifecycle planners.
#     - Provides shared WorkItem contract to triage/router/monitors.
#   Test requirements:
#     - Validation of new required fields.
#     - JSONL/index consistency after create/update/search.
#     - Phase-local routing: work items stay within their originating phase.
# IMPL(single-layer): Replace legacy `WorkItem` payload fields (`spec_text`,
# `owner_slice_id`, single `location`) with the Section 8.1 shared contract
# (`run_id`, `slice_id`, `title`, `description`, `shape_id`, `created_in_phase`,
# `required_change_type`, `file_locations`, `evidence_refs`, `contract_ids`,
# `verifier_ids`, `priority`) in one migration.
# IMPL(single-layer): Promote store API surface to
# `create`/`upsert(merge_policy=...)`/`list_open(phase, shape_id)` while updating
# all known callers in the same change; do not keep dual API paths.
# IMPL(single-layer): Evaluation modification #3 handoff from
# `routing.shapes.requires_verifier_refresh=True` should materialize verifier
# create/update work items keyed by `shape_id` in the active phase.

"""Work-item store and 3-stage search for agent coordination.

Work items are the universal coordination key: each one represents a
piece of spec text that an agent is responsible for implementing.  The
store is workspace-level (not per-slice) and uses append-only JSONL for
audit plus a compact JSON index for fast lookups.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from spec_manager.compliance.promotion.config import PhaseId
from spec_manager.routing.shapes import ShapeId

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

STATUS = Literal[
    "NEW",
    "ASSIGNED",
    "IN_PROGRESS",
    "MERGED",
    "DONE",
    "BLOCKED",
    "OPEN",
    "EXPLORING",
    "DECIDED",
]

RequiredChangeType = Literal[
    "behavior_change",
    "wiring_only",
    "refactor_only",
    "spec_change",
]

_SPEC_WORK_STATUSES = {
    "NEW",
    "ASSIGNED",
    "IN_PROGRESS",
    "MERGED",
    "DONE",
    "BLOCKED",
}
_ARCH_DECISION_STATUSES = {"OPEN", "EXPLORING", "BLOCKED", "DECIDED"}
_STATUS_TRANSITION_MAP: dict[str, dict[str, set[str]]] = {
    "SPEC_WORK": {
        "NEW": {"ASSIGNED", "IN_PROGRESS", "MERGED", "DONE", "BLOCKED"},
        "ASSIGNED": {"IN_PROGRESS", "MERGED", "DONE", "BLOCKED"},
        "IN_PROGRESS": {"MERGED", "DONE", "BLOCKED"},
        "MERGED": {"DONE", "BLOCKED"},
        "DONE": {"DONE"},
        "BLOCKED": {"BLOCKED"},
    },
    "SHAPE_MATCH": {
        "NEW": {"ASSIGNED", "IN_PROGRESS", "MERGED", "DONE", "BLOCKED"},
        "ASSIGNED": {"IN_PROGRESS", "MERGED", "DONE", "BLOCKED"},
        "IN_PROGRESS": {"MERGED", "DONE", "BLOCKED"},
        "MERGED": {"DONE", "BLOCKED"},
        "DONE": {"DONE"},
        "BLOCKED": {"BLOCKED"},
    },
    "ARCH_DECISION": {
        "OPEN": {"EXPLORING", "BLOCKED", "DECIDED"},
        "EXPLORING": {"OPEN", "BLOCKED", "DECIDED"},
        "BLOCKED": {"OPEN", "EXPLORING", "DECIDED"},
        "DECIDED": {"DECIDED"},
    },
}
_OPEN_STATUSES = {
    "NEW",
    "ASSIGNED",
    "IN_PROGRESS",
    "OPEN",
    "EXPLORING",
    "BLOCKED",
}
_OPEN_CHANGE_TYPES = {
    "behavior_change",
    "wiring_only",
    "refactor_only",
    "spec_change",
}

_KIND_STATUS_MAP: dict[str, set[str]] = {
    "SPEC_WORK": _SPEC_WORK_STATUSES,
    "SHAPE_MATCH": _SPEC_WORK_STATUSES,
    "ARCH_DECISION": _ARCH_DECISION_STATUSES,
}


def _utcnow() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _normalize_kind(kind: str) -> str:
    normalized = str(kind).strip().upper()
    return normalized if normalized else "SPEC_WORK"


def _normalize_phase(value: str) -> PhaseId:
    normalized = str(value).strip().lower()
    if normalized not in {"libraries", "architecture", "quality"}:
        raise ValueError(
            f"Invalid phase '{value}'. Expected one of: libraries, architecture, quality."
        )
    return cast("PhaseId", normalized)


def _normalize_required_change_type(value: str) -> RequiredChangeType:
    normalized = str(value).strip().lower()
    if normalized not in _OPEN_CHANGE_TYPES:
        raise ValueError(
            "Invalid required_change_type. Expected one of: behavior_change, wiring_only, "
            "refactor_only, spec_change."
        )
    return cast("RequiredChangeType", normalized)


def _normalize_shape_id(value: ShapeId | str | None) -> ShapeId:
    normalized = str(value).strip() if value is not None else ""
    if not normalized:
        raise ValueError("WorkItem.shape_id is required.")
    return cast("ShapeId", normalized)


def _valid_statuses_for_kind(kind: str) -> set[str]:
    normalized_kind = _normalize_kind(kind)
    return _KIND_STATUS_MAP.get(normalized_kind, _SPEC_WORK_STATUSES)


def _default_status_for_kind(kind: str) -> str:
    normalized_kind = _normalize_kind(kind)
    if normalized_kind == "ARCH_DECISION":
        return "OPEN"
    return "NEW"


def _valid_status_transition(kind: str, current: str, next_status: str) -> bool:
    normalized_kind = _normalize_kind(kind)
    transitions = _STATUS_TRANSITION_MAP.get(normalized_kind)
    if transitions is None:
        return True
    allowed = transitions.get(current)
    if allowed is None:
        return True
    return next_status in allowed


def _normalize(text: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _fingerprint(text: str) -> str:
    """SHA-256 of normalized text, truncated to 12 hex chars."""
    return hashlib.sha256(_normalize(text).encode()).hexdigest()[:12]


def _tokenize(text: str) -> set[str]:
    """Split on whitespace, underscores, and camelCase boundaries."""
    expanded = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    parts = re.split(r"[^a-zA-Z0-9]+", expanded)
    return {p.lower() for p in parts if p}


def _trigrams(text: str) -> set[str]:
    """Return normalized character trigrams for approximate string matching."""
    norm = _normalize(text)
    if not norm:
        return set()
    if len(norm) < 3:
        return {norm}
    return {norm[i : i + 3] for i in range(len(norm) - 2)}


def _trigram_similarity(a: str, b: str) -> float:
    """Jaccard similarity over character trigrams."""
    a_tri = _trigrams(a)
    b_tri = _trigrams(b)
    if not a_tri or not b_tri:
        return 0.0
    union = a_tri | b_tri
    if not union:
        return 0.0
    return len(a_tri & b_tri) / len(union)


def _is_identifier(text: str) -> bool:
    """True if text looks like a code identifier (CamelCase or snake_case)."""
    return bool(re.match(r"^[A-Z][a-zA-Z0-9]*(\.[A-Z][a-zA-Z0-9]*)*$", text)) or bool(
        re.match(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$", text)
    )


def _unique_ordered(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


@dataclass
class WorkItemLocation:
    """Where the work item lives in the codebase."""
    # IMPL(single-layer): Move to multi-anchor shape for Section 8.1:
    # `{file_path, line_start, line_end, symbol}` and replace single `location`
    # usage with `file_locations: list[WorkItemLocation]`.
    file_path: str = ""
    line_start: int | None = None
    line_end: int | None = None
    symbol: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkItemLocation:
        file_path = str(d.get("file_path", d.get("file", ""))).strip()
        symbol = d.get("symbol")
        symbol_value = str(symbol).strip() if symbol is not None else None

        def _to_int(value: Any) -> int | None:
            if value is None:
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        line_start = _to_int(d.get("line_start", d.get("line_hint")))
        line_end = _to_int(d.get("line_end", d.get("end_line")))
        return cls(
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            symbol=symbol_value,
        )


@dataclass
class WorkItem:
    """A single unit of spec-driven work."""
    # IMPL(single-layer): This dataclass becomes the canonical cross-module work-item
    # contract consumed by matcher/router/planners/monitors; keep one schema only.

    work_item_id: str
    run_id: str
    slice_id: str
    title: str
    description: str
    shape_id: ShapeId
    created_in_phase: PhaseId
    required_change_type: RequiredChangeType
    status: str
    kind: str = "SPEC_WORK"
    priority: str = "normal"
    file_locations: list[WorkItemLocation] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    contract_ids: list[str] = field(default_factory=list)
    verifier_ids: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkItem:
        kind = _normalize_kind(d.get("kind", "SPEC_WORK"))
        raw_status = str(d.get("status", "")).strip().upper()
        status = raw_status or _default_status_for_kind(kind)
        valid_statuses = _valid_statuses_for_kind(kind)
        if status not in valid_statuses:
            raise ValueError(
                f"Invalid status '{status}' for kind '{kind}'. "
                f"Expected one of {sorted(valid_statuses)}."
            )

        raw_locations = d.get("file_locations", [])
        if isinstance(raw_locations, dict):
            raw_locations = [raw_locations]
        elif not isinstance(raw_locations, list):
            raw_locations = []
        locations: list[WorkItemLocation] = []
        for item in raw_locations:
            if isinstance(item, WorkItemLocation):
                locations.append(item)
            elif isinstance(item, dict):
                locations.append(WorkItemLocation.from_dict(item))

        if not locations:
            legacy = d.get("location", {})
            if isinstance(legacy, dict):
                locations = [WorkItemLocation.from_dict(legacy)]

        metadata = d.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}

        raw_shape_id = d.get("shape_id", "")
        if not raw_shape_id:
            raw_shape_id = metadata.get("shape_id", "")
        raw_phase = d.get("created_in_phase", "")
        if not raw_phase:
            raw_phase = metadata.get("created_in_phase", "")
        raw_required_change_type = d.get("required_change_type", "")
        if not raw_required_change_type:
            raw_required_change_type = metadata.get("required_change_type", "")
        title = str(d.get("title", "")).strip()
        description = str(d.get("description", "")).strip()
        spec_text = str(d.get("spec_text", "")).strip()
        if not title and spec_text:
            title = spec_text
        if not description and spec_text:
            description = spec_text

        return cls(
            work_item_id=str(d.get("work_item_id", "")),
            run_id=str(d.get("run_id", "")).strip(),
            slice_id=str(d.get("slice_id", "")).strip(),
            title=title,
            description=description,
            shape_id=_normalize_shape_id(raw_shape_id),
            created_in_phase=_normalize_phase(raw_phase),
            required_change_type=_normalize_required_change_type(raw_required_change_type),
            status=status,
            kind=kind,
            priority=str(d.get("priority", "normal")).strip() or "normal",
            file_locations=locations,
            evidence_refs=_unique_ordered(
                [str(item).strip() for item in d.get("evidence_refs", []) if str(item).strip()]
                if isinstance(d.get("evidence_refs", []), list)
                else []
            ),
            contract_ids=_unique_ordered(
                [str(item).strip() for item in d.get("contract_ids", []) if str(item).strip()]
                if isinstance(d.get("contract_ids", []), list)
                else []
            ),
            verifier_ids=_unique_ordered(
                [str(item).strip() for item in d.get("verifier_ids", []) if str(item).strip()]
                if isinstance(d.get("verifier_ids", []), list)
                else []
            ),
            created_at=str(d.get("created_at", "")).strip(),
            updated_at=str(d.get("updated_at", "")).strip(),
            metadata=metadata,
        )


@dataclass
class SearchQuery:
    """Input for the 3-stage work-item search."""

    spec_text: str = ""
    artifact_key: str = ""
    need_summary: str = ""
    spec_refs: list[dict[str, Any]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    max_results: int = 20
    phase: PhaseId | None = None
    shape_id: ShapeId | None = None


@dataclass
class SearchResult:
    """A scored match from work-item search."""

    work_item: WorkItem
    score: float
    match_stage: str  # "EXACT", "FUZZY", or "SEMANTIC"
    match_reason: str


@dataclass
class SearchCoverage:
    """Coverage assessment produced by semantic reranking."""

    primary_match_id: str = ""
    secondary_match_ids: list[str] = field(default_factory=list)
    coverage: Literal["FULL_COVERAGE", "PARTIAL_COVERAGE", "NO_COVERAGE"] = "NO_COVERAGE"
    confidence: float = 0.0
    why: str = ""
    missing_detail: str = ""


# ---------------------------------------------------------------------------
# WorkItemStore
# ---------------------------------------------------------------------------


class WorkItemStore:
    """Persistent JSONL store with in-memory index for work items.

    Files:
        coordination/work_items.jsonl  — append-only audit trail
        coordination/work_items_index.json — compact id→summary lookup
    """

    def __init__(
        self,
        coordination_dir: Path,
        semantic_rerank_tool: Any | None = None,
    ) -> None:
        self._dir = coordination_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_path = self._dir / "work_items.jsonl"
        self._index_path = self._dir / "work_items_index.json"
        self._items: dict[str, WorkItem] = {}
        self._spec_fingerprint_index: dict[str, list[str]] = {}
        self._semantic_rerank_tool = semantic_rerank_tool
        self._load()

    # -- public API ----------------------------------------------------------

    # IMPL(single-layer): Rename to `create` and enforce required routing fields
    # (`shape_id`, `created_in_phase`, `required_change_type`) before persistence.
    def create(self, item: WorkItem) -> WorkItem:
        item = self._normalize_item(item)
        if not item.work_item_id:
            raise ValueError("Work item creation requires a non-empty work_item_id.")
        if item.work_item_id in self._items:
            raise ValueError(f"Work item already exists: {item.work_item_id}")
        return self._persist(item, merge_policy="replace", exists=False)

    # IMPL(single-layer): Fold status-only updates into `upsert` with explicit
    # merge policy (`replace` vs `append_evidence`) for evidence provenance updates.
    def upsert(
        self,
        item: WorkItem,
        merge_policy: Literal["replace", "append_evidence"] = "replace",
    ) -> WorkItem:
        status_provided = bool(str(item.status).strip())
        if merge_policy not in {"replace", "append_evidence"}:
            raise ValueError(
                "Invalid merge_policy. Expected 'replace' or 'append_evidence'."
            )
        if not item.work_item_id:
            raise ValueError("Work item upsert requires a non-empty work_item_id.")
        normalized = self._normalize_item(item)
        existing = self._items.get(normalized.work_item_id)
        if existing is None:
            return self._persist(normalized, merge_policy="replace", exists=False)

        if not status_provided:
            normalized.status = existing.status

        if normalized.kind != existing.kind:
            raise ValueError(
                f"Cannot change work item kind for {normalized.work_item_id}: "
                f"{existing.kind} -> {normalized.kind}"
            )
        if normalized.shape_id != existing.shape_id:
            raise ValueError(
                f"Cannot change shape_id for {normalized.work_item_id}: "
                f"{existing.shape_id} -> {normalized.shape_id}"
            )
        if normalized.created_in_phase != existing.created_in_phase:
            raise ValueError(
                f"Cannot change created_in_phase for {normalized.work_item_id}: "
                f"{existing.created_in_phase} -> {normalized.created_in_phase}"
            )

        if normalized.required_change_type != existing.required_change_type:
            raise ValueError(
                f"Cannot change required_change_type for {normalized.work_item_id}: "
                f"{existing.required_change_type} -> {normalized.required_change_type}"
            )

        if not _valid_status_transition(
            normalized.kind, existing.status, normalized.status
        ):
            raise ValueError(
                f"Invalid status transition for {existing.work_item_id} "
                f"kind={normalized.kind}: {existing.status} -> {normalized.status}"
            )

        return self._persist(normalized, merge_policy=merge_policy, exists=True)

    # IMPL(single-layer): Replace slice/status getters with `list_open` filters
    # keyed by phase + shape to support phase-local routing.
    def list_open(
        self,
        phase: PhaseId | None = None,
        shape_id: ShapeId | None = None,
    ) -> list[WorkItem]:
        normalized_phase = _normalize_phase(phase) if phase else None
        normalized_shape = _normalize_shape_id(shape_id) if shape_id else None
        return [
            item
            for item in self._iter_open_items(normalized_phase, normalized_shape)
            if item.status in _OPEN_STATUSES
        ]

    def get(self, work_item_id: str) -> WorkItem | None:
        return self._items.get(work_item_id)

    def all_items(self) -> list[WorkItem]:
        return list(self._items.values())

    def search(self, query: SearchQuery) -> list[SearchResult]:
        """3-stage retrieval: exact -> fuzzy -> semantic rerank."""
        outcome = self.search_with_coverage(query)
        return outcome["results"]

    def search_with_coverage(self, query: SearchQuery) -> dict[str, Any]:
        """Run retrieval and return matches plus semantic coverage classification."""
        # IMPL(single-layer): Keep the 3-stage exact/fuzzy/semantic pipeline and add
        # phase/shape-aware narrowing in candidate selection (Section 8.2).
        candidates = self._iter_open_items(
            phase=_normalize_phase(query.phase) if query.phase else None,
            shape_id=_normalize_shape_id(query.shape_id) if query.shape_id else None,
        )
        results: list[SearchResult] = []
        exact = self._search_exact(query, candidates)
        results.extend(exact)

        if len(results) < query.max_results:
            seen_ids = {r.work_item.work_item_id for r in results}
            fuzzy = self._search_fuzzy(query, candidates, exclude_ids=seen_ids)

            semantic_top_k = fuzzy[:20]
            semantic_results: list[SearchResult] = []
            coverage = SearchCoverage()
            if semantic_top_k:
                semantic_results, coverage = self._rerank_with_llm_internal(
                    query,
                    [r.work_item for r in semantic_top_k],
                )
                semantic_ids = {r.work_item.work_item_id for r in semantic_results}
                results.extend(semantic_results)
                results.extend(r for r in fuzzy if r.work_item.work_item_id not in semantic_ids)
            else:
                coverage = SearchCoverage(
                    coverage="NO_COVERAGE",
                    confidence=0.0,
                    why="no_semantic_candidates",
                    missing_detail=self._default_missing_detail(query),
                )
        else:
            coverage = SearchCoverage()

        results.sort(key=lambda r: r.score, reverse=True)
        capped = results[: query.max_results]

        # Exact spec-text hit is authoritative and fully covers the request.
        if exact:
            primary = exact[0].work_item
            return {
                "results": capped,
                "primary_match": primary,
                "secondary_matches": [],
                "coverage": "FULL_COVERAGE",
                "confidence": 1.0,
                "why": "exact_spec_text_match",
                "missing_detail": "",
            }

        primary_match = (
            self._items.get(coverage.primary_match_id) if coverage.primary_match_id else None
        )
        secondary_matches = [
            self._items[wid] for wid in coverage.secondary_match_ids if wid in self._items
        ]
        return {
            "results": capped,
            "primary_match": primary_match,
            "secondary_matches": secondary_matches,
            "coverage": coverage.coverage,
            "confidence": coverage.confidence,
            "why": coverage.why,
            "missing_detail": coverage.missing_detail,
        }

    def rerank_with_llm(self, query: SearchQuery, candidates: list[WorkItem]) -> list[SearchResult]:
        """Stage C semantic rerank over top lexical candidates."""
        reranked, _ = self._rerank_with_llm_internal(query, candidates)
        return reranked

    def _rerank_with_llm_internal(
        self,
        query: SearchQuery,
        candidates: list[WorkItem],
    ) -> tuple[list[SearchResult], SearchCoverage]:
        if not candidates:
            return (
                [],
                SearchCoverage(
                    coverage="NO_COVERAGE",
                    confidence=0.0,
                    why="no_candidates",
                    missing_detail=self._default_missing_detail(query),
                ),
            )

        parsed = self._call_semantic_reranker(query, candidates)
        if parsed is None:
            fallback = self._fallback_semantic_rerank(query, candidates)
            primary_id = fallback[0].work_item.work_item_id if fallback else ""
            return (
                fallback,
                SearchCoverage(
                    primary_match_id=primary_id,
                    secondary_match_ids=[],
                    coverage="NO_COVERAGE",
                    confidence=0.0,
                    why="semantic_classifier_unavailable",
                    missing_detail=self._default_missing_detail(query),
                ),
            )

        candidate_ids = [c.work_item_id for c in candidates]
        primary_id = self._extract_candidate_id(
            parsed, candidate_ids, "primary_match_id", "primary_match"
        )

        secondary_raw = parsed.get("secondary_match_ids", parsed.get("secondary_matches", []))
        secondary_ids: list[str] = []
        if isinstance(secondary_raw, list):
            for item in secondary_raw:
                candidate_id = self._extract_candidate_id(item, candidate_ids)
                if (
                    candidate_id
                    and candidate_id not in secondary_ids
                    and candidate_id != primary_id
                ):
                    secondary_ids.append(candidate_id)

        coverage_raw = str(parsed.get("coverage", "NO_COVERAGE")).upper()
        coverage_value: Literal["FULL_COVERAGE", "PARTIAL_COVERAGE", "NO_COVERAGE"] = (
            coverage_raw
            if coverage_raw in {"FULL_COVERAGE", "PARTIAL_COVERAGE", "NO_COVERAGE"}
            else "NO_COVERAGE"
        )
        if not primary_id and coverage_value != "NO_COVERAGE" and candidate_ids:
            primary_id = candidate_ids[0]

        confidence = self._safe_float(parsed.get("confidence", 0.0))
        why = str(parsed.get("why", parsed.get("rationale", "")))
        missing_detail = str(parsed.get("missing_detail", "")).strip()
        if not missing_detail and coverage_value != "FULL_COVERAGE":
            missing_detail = self._default_missing_detail(query)

        ordered_ids: list[str] = []
        if primary_id:
            ordered_ids.append(primary_id)
        ordered_ids.extend(sid for sid in secondary_ids if sid not in ordered_ids)
        ordered_ids.extend(wid for wid in candidate_ids if wid not in ordered_ids)
        if not ordered_ids:
            ordered_ids = list(candidate_ids)

        denominator = max(len(ordered_ids) - 1, 1)
        rank_to_score = {
            wid: max(0.1, 1.0 - (idx / denominator) * 0.4)
            for idx, wid in enumerate(ordered_ids)
        }
        reranked = [
            SearchResult(
                work_item=self._items[wid],
                score=rank_to_score[wid],
                match_stage="SEMANTIC",
                match_reason=why or "semantic_rerank",
            )
            for wid in ordered_ids
            if wid in self._items
        ]
        reranked.sort(key=lambda r: r.score, reverse=True)

        coverage = SearchCoverage(
            primary_match_id=primary_id,
            secondary_match_ids=secondary_ids,
            coverage=coverage_value,
            confidence=max(0.0, min(confidence, 1.0)),
            why=why,
            missing_detail=missing_detail,
        )
        return reranked, coverage

    # -- Stage A: exact ----------------------------------------------------

    def _search_exact(
        self,
        query: SearchQuery,
        candidates: list[WorkItem],
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        candidate_ids = {item.work_item_id for item in candidates}
        query_text = self._compose_query_text(query)
        query_norm = _normalize(query_text)
        if query_norm:
            fp = _fingerprint(query_norm)
            # Fingerprint match via explicit fingerprint -> work_item_id index.
            for work_item_id in self._spec_fingerprint_index.get(fp, []):
                if work_item_id not in candidate_ids:
                    continue
                item = self._items.get(work_item_id)
                if item is None:
                    continue
                results.append(
                    SearchResult(
                        work_item=item,
                        score=1.0,
                        match_stage="EXACT",
                        match_reason="fingerprint_match",
                    )
                )
            # Substring containment
            seen = {r.work_item.work_item_id for r in results}
            for item in candidates:
                if item.work_item_id in seen:
                    continue
                item_norm = _normalize(self._work_item_search_text(item))
                if not item_norm:
                    continue
                if query_norm in item_norm or item_norm in query_norm:
                    results.append(
                        SearchResult(
                            work_item=item,
                            score=0.95,
                            match_stage="EXACT",
                            match_reason="substring_containment",
                        )
                    )
                    seen.add(item.work_item_id)
        return results

    # -- Stage B: fuzzy ----------------------------------------------------

    def _search_fuzzy(
        self,
        query: SearchQuery,
        candidates: list[WorkItem],
        exclude_ids: set[str] | None = None,
    ) -> list[SearchResult]:
        exclude = exclude_ids or set()
        results: list[SearchResult] = []
        for item in candidates:
            if item.work_item_id in exclude:
                continue
            score = self._fuzzy_score(query, item)
            if score >= 0.3:
                results.append(
                    SearchResult(
                        work_item=item,
                        score=score,
                        match_stage="FUZZY",
                        match_reason="token_similarity",
                    )
                )
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _fuzzy_score(self, query: SearchQuery, item: WorkItem) -> float:
        """Token overlap + trigram similarity + identifier substring boost."""
        # Build query tokens from all available fields
        query_parts: list[str] = []
        if query.spec_text:
            query_parts.append(query.spec_text)
        if query.artifact_key:
            query_parts.append(query.artifact_key)
        if query.need_summary:
            query_parts.append(query.need_summary)
        for ref in query.spec_refs:
            if isinstance(ref, dict):
                ref_text = ref.get("spec_text")
                if isinstance(ref_text, str) and ref_text.strip():
                    query_parts.append(ref_text)
        query_parts.extend(query.keywords)
        if not query_parts:
            return 0.0

        query_tokens = set()
        for part in query_parts:
            query_tokens |= _tokenize(part)

        # Build item tokens
        item_tokens = _tokenize(self._work_item_search_text(item))
        for loc in item.file_locations:
            item_tokens |= _tokenize(loc.file_path)
            if loc.symbol:
                item_tokens |= _tokenize(loc.symbol)
        for evidence_ref in item.evidence_refs:
            item_tokens |= _tokenize(str(evidence_ref))
        for contract_id in item.contract_ids:
            item_tokens |= _tokenize(str(contract_id))
        for verifier_id in item.verifier_ids:
            item_tokens |= _tokenize(str(verifier_id))

        if not query_tokens or not item_tokens:
            return 0.0

        intersection = query_tokens & item_tokens
        union = query_tokens | item_tokens
        jaccard = len(intersection) / len(union) if union else 0.0

        # Coverage of query tokens by item tokens.
        containment = len(intersection) / len(query_tokens) if query_tokens else 0.0
        query_text = " ".join(query_parts)
        item_text = " ".join(
            [self._work_item_search_text(item), " ".join(loc.file_path for loc in item.file_locations)]
        )
        trigram = _trigram_similarity(query_text, item_text)

        # Identifier substring boost
        boost = 0.0
        if query.artifact_key and _is_identifier(query.artifact_key):
            ak_lower = query.artifact_key.lower()
            for loc in item.file_locations:
                file_path = (loc.file_path or "").lower()
                symbol = (loc.symbol or "").lower()
                if ak_lower in symbol:
                    boost = max(boost, 0.3)
                    break
                if ak_lower in file_path:
                    boost = max(boost, 0.2)
        if not boost:
            desc = (item.description or "").lower()
            artifact = (query.artifact_key or "").strip().lower()
            if artifact and artifact in desc:
                boost = 0.15

        combined = (0.5 * jaccard) + (0.3 * trigram) + (0.2 * containment)
        return min(combined + boost, 1.0)

    def _call_semantic_reranker(
        self,
        query: SearchQuery,
        candidates: list[WorkItem],
    ) -> dict[str, Any] | None:
        """Invoke configured semantic reranker and parse structured JSON response."""
        tool = self._semantic_rerank_tool
        if tool is None:
            return None

        payload = {
            "need_summary": query.need_summary,
            "artifact_key": query.artifact_key,
            "spec_refs": query.spec_refs,
            "spec_text": self._compose_query_text(query),
            "keywords": list(query.keywords),
            "candidates": [
                {
                    "work_item_id": item.work_item_id,
                    "title": item.title,
                    "description": item.description,
                    "status": item.status,
                    "kind": item.kind,
                    "shape_id": item.shape_id,
                    "created_in_phase": item.created_in_phase,
                    "required_change_type": item.required_change_type,
                    "priority": item.priority,
                    "file_locations": [loc.to_dict() for loc in item.file_locations],
                }
                for item in candidates
            ],
        }
        prompt = self._build_semantic_prompt(payload)

        raw: Any = None
        try:
            if callable(tool):
                for kwargs in (
                    {"prompt": prompt, "payload": payload, "task": "semantic_rerank"},
                    {"prompt": prompt},
                    {"query": payload},
                    {"query": prompt},
                ):
                    try:
                        raw = tool(**kwargs)
                        break
                    except TypeError:
                        continue
                if raw is None:
                    try:
                        raw = tool(prompt)
                    except TypeError:
                        raw = tool(payload)
            elif hasattr(tool, "research"):
                from spec_manager.planner.tools.research_tool import ResearchQuery

                query_obj = ResearchQuery(
                    question=prompt,
                    context=json.dumps(payload, ensure_ascii=True),
                    dimension="layer",
                    max_results=1,
                )
                raw = tool.research(query_obj)
        except Exception:
            logger.warning(
                "Semantic rerank tool failed for artifact_key=%r spec_text_preview=%r; "
                "falling back to lexical order",
                query.artifact_key,
                self._compose_query_text(query)[:120],
                exc_info=True,
            )
            return None

        parsed = self._parse_semantic_output(raw)
        if parsed is None:
            logger.warning(
                "Semantic rerank output was not parseable for artifact_key=%r; "
                "falling back to lexical order",
                query.artifact_key,
            )
        return parsed

    def _build_semantic_prompt(self, payload: dict[str, Any]) -> str:
        """Build reranking prompt for LLM semantic matching."""
        need_summary = str(payload.get("need_summary", ""))
        artifact_key = str(payload.get("artifact_key", ""))
        spec_text = str(payload.get("spec_text", ""))
        spec_refs = payload.get("spec_refs", [])
        candidates = payload.get("candidates", [])

        refs_lines: list[str] = []
        if isinstance(spec_refs, list):
            for ref in spec_refs[:10]:
                if not isinstance(ref, dict):
                    continue
                text = str(ref.get("spec_text", "")).strip()
                if not text:
                    continue
                source_file = str(ref.get("source_file", "")).strip()
                source_symbol = str(ref.get("source_symbol", "")).strip()
                refs_lines.append(
                    f"- {text[:220]} (file={source_file or '?'}, symbol={source_symbol or '?'})"
                )
        refs_block = "\n".join(refs_lines) if refs_lines else "- (none)"

        candidate_lines: list[str] = []
        if isinstance(candidates, list):
            for c in candidates[:20]:
                if not isinstance(c, dict):
                    continue
                locations = c.get("file_locations", [])
                first_location = {}
                if isinstance(locations, list) and locations:
                    first_location = locations[0] if isinstance(locations[0], dict) else {}
                candidate_lines.append(
                    f"- id={c.get('work_item_id', '')} "
                    f"status={c.get('status', '')} "
                    f"shape={c.get('shape_id', '')} "
                    f"phase={c.get('created_in_phase', '')} "
                    f"file={first_location.get('file_path', '')} "
                    f"symbol={first_location.get('symbol', '')} "
                    f"title={str(c.get('title', ''))[:120]} "
                    f"desc={str(c.get('description', ''))[:120]}"
                )
        candidates_block = "\n".join(candidate_lines) if candidate_lines else "- (none)"

        return (
            "You are reranking dependency work items.\n"
            "Choose which candidates satisfy the dependency request.\n"
            "Return strict JSON only with keys:\n"
            "primary_match_id (string or empty),\n"
            "secondary_match_ids (array of strings),\n"
            "coverage (FULL_COVERAGE|PARTIAL_COVERAGE|NO_COVERAGE),\n"
            "confidence (0..1),\n"
            "why (short string),\n"
            "missing_detail (string; what interface/behavior is still missing).\n\n"
            f"Need summary: {need_summary}\n"
            f"Artifact key: {artifact_key}\n"
            f"Spec text channel: {spec_text[:400]}\n"
            f"Spec refs:\n{refs_block}\n\n"
            f"Candidates:\n{candidates_block}\n"
        )

    def _parse_semantic_output(self, raw: Any) -> dict[str, Any] | None:
        """Extract structured JSON from LLM/tool output."""
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            for entry in raw:
                parsed = self._parse_semantic_output(entry)
                if parsed is not None:
                    return parsed
            return None

        synthesis = getattr(raw, "synthesis", None)
        if isinstance(synthesis, str) and synthesis.strip():
            parsed = self._parse_semantic_output(synthesis)
            if parsed is not None:
                return parsed

        if isinstance(raw, str):
            text = raw.strip()
            if text.startswith("```"):
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
            try:
                parsed_json = json.loads(text)
                if isinstance(parsed_json, dict):
                    return parsed_json
            except json.JSONDecodeError:
                start = text.find("{")
                end = text.rfind("}")
                if start != -1 and end != -1 and end > start:
                    try:
                        parsed_json = json.loads(text[start : end + 1])
                        if isinstance(parsed_json, dict):
                            return parsed_json
                    except json.JSONDecodeError:
                        return None
            return None

        return None

    def _fallback_semantic_rerank(
        self,
        query: SearchQuery,
        candidates: list[WorkItem],
    ) -> list[SearchResult]:
        """Deterministic fallback ordering when LLM rerank is unavailable."""
        ranked = [
            SearchResult(
                work_item=item,
                score=self._fuzzy_score(query, item),
                match_stage="SEMANTIC",
                match_reason="llm_rerank_placeholder",
            )
            for item in candidates
        ]
        ranked.sort(key=lambda r: r.score, reverse=True)
        return ranked

    def _extract_candidate_id(
        self,
        value: Any,
        candidate_ids: list[str],
        *keys: str,
    ) -> str:
        candidate_set = set(candidate_ids)
        if value is None:
            return ""
        if isinstance(value, str):
            if value in candidate_set:
                return value
            if value.isdigit():
                index = int(value)
                if 0 <= index < len(candidate_ids):
                    return candidate_ids[index]
            return ""
        if isinstance(value, int):
            if 0 <= value < len(candidate_ids):
                return candidate_ids[value]
            return ""
        if isinstance(value, dict):
            lookup_keys = list(keys) if keys else ["work_item_id", "id", "candidate_id", "match_id"]
            for key in lookup_keys:
                candidate_id = self._extract_candidate_id(value.get(key), candidate_ids)
                if candidate_id:
                    return candidate_id
            return ""
        return ""

    def _safe_float(self, value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _default_missing_detail(self, query: SearchQuery) -> str:
        """Return a concrete missing-detail statement for unresolved coverage."""
        if query.need_summary and query.need_summary.strip():
            return query.need_summary.strip()
        if query.artifact_key and query.artifact_key.strip():
            return f"Missing concrete interface/behavior for {query.artifact_key.strip()}."
        return "Missing concrete interface/behavior details needed by the blocked consumer."

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        """Load items from JSONL, rebuilding in-memory state."""
        # IMPL(single-layer): Corrupt JSONL/index recovery should rebuild compact index
        # from append-only audit entries instead of silently accepting divergence.
        if not self._jsonl_path.exists():
            if self._index_path.exists():
                # If only index exists, discard and rebuild from source of truth (jsonl is absent).
                self._items = {}
                self._rebuild_fingerprint_index()
                self._write_index()
            return

        items: dict[str, WorkItem] = {}
        for line_no, line in enumerate(
            self._jsonl_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                item = WorkItem.from_dict(d)
                items[item.work_item_id] = item
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "Skipping malformed work item JSONL line %s in %s: %s",
                    line_no,
                    self._jsonl_path,
                    exc,
                )
        self._items = items
        self._rebuild_fingerprint_index()
        self._write_index()

    def _append_jsonl(self, item: WorkItem) -> None:
        # IMPL(single-layer): Event append + index update should be committed atomically
        # so crash recovery preserves a consistent audit/index pair.
        with self._jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

    def _write_index(self) -> None:
        index: dict[str, Any] = {}
        for wid, item in self._items.items():
            spec_fingerprint = _fingerprint(self._work_item_search_text(item))
            index[wid] = {
                "status": item.status,
                "shape_id": item.shape_id,
                "created_in_phase": item.created_in_phase,
                "required_change_type": item.required_change_type,
                "kind": item.kind,
                "priority": item.priority,
                "owner_slice_id": item.slice_id,
                "title": item.title,
                "description": item.description[:160],
                "spec_fingerprint": spec_fingerprint,
            }
        index["__spec_fingerprint_index__"] = self._spec_fingerprint_index
        temp_path = self._index_path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
        temp_path.replace(self._index_path)

    def _rebuild_fingerprint_index(self) -> None:
        index: dict[str, list[str]] = {}
        for wid, item in self._items.items():
            item.metadata = dict(item.metadata or {})
            spec_fingerprint = _fingerprint(self._work_item_search_text(item))
            item.metadata["spec_fingerprint"] = spec_fingerprint
            ids = index.setdefault(spec_fingerprint, [])
            ids.append(wid)
        self._spec_fingerprint_index = index

    def _iter_open_items(
        self,
        phase: PhaseId | None = None,
        shape_id: ShapeId | None = None,
    ) -> list[WorkItem]:
        normalized_shape = str(shape_id).strip() if shape_id else None
        items: list[WorkItem] = []
        for item in self._items.values():
            if item.status not in _OPEN_STATUSES:
                continue
            if phase and item.created_in_phase != phase:
                continue
            if normalized_shape and item.shape_id != ShapeId(normalized_shape):
                continue
            items.append(item)
        return items

    def _compose_query_text(self, query: SearchQuery) -> str:
        parts: list[str] = []
        if query.spec_text:
            parts.append(query.spec_text)
        if query.artifact_key:
            parts.append(query.artifact_key)
        if query.need_summary:
            parts.append(query.need_summary)
        for ref in query.spec_refs:
            if isinstance(ref, dict):
                text = str(ref.get("spec_text", "")).strip()
                if text:
                    parts.append(text)
        parts.extend(query.keywords)
        return " ".join(parts)

    def _work_item_search_text(self, item: WorkItem) -> str:
        return f"{item.title}\n{item.description}".strip()

    def _normalize_item(self, item: WorkItem) -> WorkItem:
        kind = _normalize_kind(item.kind)
        status = str(item.status).strip().upper() or _default_status_for_kind(kind)
        valid_statuses = _valid_statuses_for_kind(kind)
        if status not in valid_statuses:
            raise ValueError(
                f"Invalid status '{status}' for kind '{kind}'. "
                f"Expected one of {sorted(valid_statuses)}."
            )

        created_at = str(item.created_at).strip() or _utcnow()
        updated_at = str(item.updated_at).strip() or created_at
        if isinstance(item.created_in_phase, str):
            created_in_phase = _normalize_phase(item.created_in_phase)
        else:
            created_in_phase = item.created_in_phase
        if created_in_phase is None:
            raise ValueError("WorkItem.created_in_phase is required.")
        if not item.shape_id:
            raise ValueError("WorkItem.shape_id is required.")

        file_locations: list[WorkItemLocation] = []
        raw_locations = item.file_locations
        if isinstance(raw_locations, list):
            for value in raw_locations:
                if isinstance(value, WorkItemLocation):
                    file_locations.append(value)
                elif isinstance(value, dict):
                    file_locations.append(WorkItemLocation.from_dict(value))
        elif isinstance(raw_locations, dict):
            file_locations.append(WorkItemLocation.from_dict(raw_locations))

        return WorkItem(
            work_item_id=str(item.work_item_id).strip(),
            run_id=str(item.run_id).strip(),
            slice_id=str(item.slice_id).strip(),
            title=str(item.title).strip(),
            description=str(item.description).strip(),
            shape_id=_normalize_shape_id(item.shape_id),
            created_in_phase=created_in_phase,
            required_change_type=_normalize_required_change_type(item.required_change_type),
            status=status,
            kind=kind,
            priority=str(item.priority).strip() or "normal",
            file_locations=file_locations,
            evidence_refs=_unique_ordered(
                [str(value).strip() for value in item.evidence_refs if str(value).strip()]
                if isinstance(item.evidence_refs, list)
                else []
            ),
            contract_ids=_unique_ordered(
                [str(value).strip() for value in item.contract_ids if str(value).strip()]
                if isinstance(item.contract_ids, list)
                else []
            ),
            verifier_ids=_unique_ordered(
                [str(value).strip() for value in item.verifier_ids if str(value).strip()]
                if isinstance(item.verifier_ids, list)
                else []
            ),
            created_at=created_at,
            updated_at=updated_at,
            metadata=dict(item.metadata or {}),
        )

    def _merge_items(
        self,
        existing: WorkItem,
        incoming: WorkItem,
        merge_policy: str,
    ) -> WorkItem:
        now = _utcnow()
        if merge_policy == "append_evidence":
            merged_locations = list(existing.file_locations)
            merged_locations.extend(incoming.file_locations or [])
            return replace(
                existing,
                status=incoming.status,
                run_id=incoming.run_id or existing.run_id,
                slice_id=incoming.slice_id or existing.slice_id,
                title=incoming.title or existing.title,
                description=incoming.description or existing.description,
                priority=incoming.priority or existing.priority,
                file_locations=merged_locations,
                evidence_refs=_unique_ordered(
                    list(existing.evidence_refs) + list(incoming.evidence_refs)
                ),
                contract_ids=_unique_ordered(
                    list(existing.contract_ids) + list(incoming.contract_ids)
                ),
                verifier_ids=_unique_ordered(
                    list(existing.verifier_ids) + list(incoming.verifier_ids)
                ),
                metadata={**dict(existing.metadata or {}), **dict(incoming.metadata or {})},
                updated_at=now,
            )

        if incoming.run_id:
            existing.run_id = incoming.run_id
        if incoming.slice_id:
            existing.slice_id = incoming.slice_id
        existing.title = incoming.title
        existing.description = incoming.description
        existing.priority = incoming.priority
        existing.file_locations = incoming.file_locations or []
        existing.evidence_refs = incoming.evidence_refs
        existing.contract_ids = incoming.contract_ids
        existing.verifier_ids = incoming.verifier_ids
        existing.status = incoming.status
        existing.kind = incoming.kind
        existing.metadata = incoming.metadata
        existing.updated_at = now
        return existing

    def _persist(
        self,
        item: WorkItem,
        merge_policy: str,
        *,
        exists: bool,
    ) -> WorkItem:
        if not item.work_item_id:
            raise ValueError("Work item id is required.")

        if exists:
            existing = self._items[item.work_item_id]
            merged = self._merge_items(existing, item, merge_policy)
            self._items[item.work_item_id] = merged
            persisted = merged
        else:
            item.updated_at = _utcnow() if not item.updated_at else item.updated_at
            item.created_at = item.created_at or item.updated_at
            if not item.created_at:
                item.created_at = _utcnow()
                item.updated_at = item.created_at
            self._items[item.work_item_id] = item
            persisted = item

        persisted.updated_at = _utcnow()
        if not persisted.created_at:
            persisted.created_at = persisted.updated_at
        persisted.metadata["spec_fingerprint"] = _fingerprint(
            self._work_item_search_text(persisted)
        )
        self._rebuild_fingerprint_index()
        self._append_jsonl(persisted)
        self._write_index()
        return persisted
