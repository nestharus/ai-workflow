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
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

STATUS = Literal["NEW", "ASSIGNED", "IN_PROGRESS", "MERGED", "DONE", "BLOCKED"]

_VALID_STATUSES = {"NEW", "ASSIGNED", "IN_PROGRESS", "MERGED", "DONE", "BLOCKED"}


def _normalize(text: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _fingerprint(text: str) -> str:
    """SHA-256 of normalized text, truncated to 12 hex chars."""
    return hashlib.sha256(_normalize(text).encode()).hexdigest()[:12]


def _tokenize(text: str) -> set[str]:
    """Split on whitespace, underscores, and camelCase boundaries."""
    # First expand camelCase: "checkExposure" -> "check Exposure"
    expanded = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    # Split on non-alphanumeric
    parts = re.split(r"[^a-zA-Z0-9]+", expanded)
    return {p.lower() for p in parts if p}


def _is_identifier(text: str) -> bool:
    """True if text looks like a code identifier (CamelCase or snake_case)."""
    return bool(re.match(r"^[A-Z][a-zA-Z0-9]*(\.[A-Z][a-zA-Z0-9]*)*$", text)) or bool(
        re.match(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$", text)
    )


@dataclass
class WorkItemLocation:
    """Where the work item lives in the codebase."""

    file: str = ""
    symbol: str = ""
    line_hint: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkItemLocation:
        return cls(
            file=d.get("file", ""),
            symbol=d.get("symbol", ""),
            line_hint=d.get("line_hint", 0),
        )


@dataclass
class WorkItem:
    """A single unit of spec-driven work."""

    work_item_id: str
    spec_text: str
    owner_slice_id: str
    status: str  # one of STATUS values
    location: WorkItemLocation = field(default_factory=WorkItemLocation)
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    kind: str = "SPEC_WORK"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkItem:
        loc_data = d.get("location", {})
        if isinstance(loc_data, dict):
            loc = WorkItemLocation.from_dict(loc_data)
        else:
            loc = WorkItemLocation()
        return cls(
            work_item_id=d.get("work_item_id", ""),
            spec_text=d.get("spec_text", ""),
            owner_slice_id=d.get("owner_slice_id", ""),
            status=d.get("status", "NEW"),
            location=loc,
            tags=d.get("tags", []),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            kind=d.get("kind", "SPEC_WORK"),
            metadata=d.get("metadata", {}),
        )


@dataclass
class SearchQuery:
    """Input for the 3-stage work-item search."""

    spec_text: str = ""
    artifact_key: str = ""
    keywords: list[str] = field(default_factory=list)
    max_results: int = 20


@dataclass
class SearchResult:
    """A scored match from work-item search."""

    work_item: WorkItem
    score: float
    match_stage: str  # "EXACT", "FUZZY", or "SEMANTIC"
    match_reason: str


# ---------------------------------------------------------------------------
# WorkItemStore
# ---------------------------------------------------------------------------


class WorkItemStore:
    """Persistent JSONL store with in-memory index for work items.

    Files:
        coordination/work_items.jsonl  — append-only audit trail
        coordination/work_items_index.json — compact id→summary lookup
    """

    def __init__(self, coordination_dir: Path) -> None:
        self._dir = coordination_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_path = self._dir / "work_items.jsonl"
        self._index_path = self._dir / "work_items_index.json"
        self._items: dict[str, WorkItem] = {}
        self._load()

    # -- public API ----------------------------------------------------------

    def add(self, item: WorkItem) -> None:
        """Append a work item to JSONL and rebuild index."""
        if not item.created_at:
            item.created_at = datetime.now(UTC).isoformat()
        item.updated_at = item.created_at
        self._items[item.work_item_id] = item
        self._append_jsonl(item)
        self._write_index()

    def update_status(self, work_item_id: str, status: str) -> None:
        """Update the status of an existing work item."""
        if status not in _VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        item = self._items.get(work_item_id)
        if item is None:
            raise KeyError(f"Work item not found: {work_item_id}")
        item.status = status
        item.updated_at = datetime.now(UTC).isoformat()
        self._append_jsonl(item)
        self._write_index()

    def get(self, work_item_id: str) -> WorkItem | None:
        return self._items.get(work_item_id)

    def get_by_slice(self, slice_id: str) -> list[WorkItem]:
        return [it for it in self._items.values() if it.owner_slice_id == slice_id]

    def get_by_status(self, status: str) -> list[WorkItem]:
        return [it for it in self._items.values() if it.status == status]

    def all_items(self) -> list[WorkItem]:
        return list(self._items.values())

    def search(self, query: SearchQuery) -> list[SearchResult]:
        """3-stage retrieval: exact -> fuzzy -> (semantic placeholder)."""
        results: list[SearchResult] = []

        # Stage A: exact fingerprint + substring
        results.extend(self._search_exact(query))
        if len(results) >= query.max_results:
            return results[: query.max_results]

        # Stage B: fuzzy lexical
        seen_ids = {r.work_item.work_item_id for r in results}
        fuzzy = self._search_fuzzy(query, exclude_ids=seen_ids)
        results.extend(fuzzy)

        # Sort by score descending, cap to max_results
        results.sort(key=lambda r: r.score, reverse=True)
        return results[: query.max_results]

    def rerank_with_llm(self, query: SearchQuery, candidates: list[WorkItem]) -> list[SearchResult]:
        """Stage C placeholder: LLM semantic rerank.

        Currently returns candidates sorted by fuzzy score.
        Will be replaced with actual LLM call when wired.
        """
        scored: list[SearchResult] = []
        for item in candidates:
            score = self._fuzzy_score(query, item)
            scored.append(
                SearchResult(
                    work_item=item,
                    score=score,
                    match_stage="SEMANTIC",
                    match_reason="llm_rerank_placeholder",
                )
            )
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored

    # -- Stage A: exact ----------------------------------------------------

    def _search_exact(self, query: SearchQuery) -> list[SearchResult]:
        results: list[SearchResult] = []
        if query.spec_text:
            fp = _fingerprint(query.spec_text)
            # Fingerprint match
            item = self._items.get(fp)
            if item is not None:
                results.append(
                    SearchResult(
                        work_item=item,
                        score=1.0,
                        match_stage="EXACT",
                        match_reason="fingerprint_match",
                    )
                )
            # Substring containment
            query_norm = _normalize(query.spec_text)
            for item in self._items.values():
                if item.work_item_id in {r.work_item.work_item_id for r in results}:
                    continue
                item_norm = _normalize(item.spec_text)
                if query_norm in item_norm or item_norm in query_norm:
                    results.append(
                        SearchResult(
                            work_item=item,
                            score=0.95,
                            match_stage="EXACT",
                            match_reason="substring_containment",
                        )
                    )
        return results

    # -- Stage B: fuzzy ----------------------------------------------------

    def _search_fuzzy(
        self, query: SearchQuery, exclude_ids: set[str] | None = None
    ) -> list[SearchResult]:
        exclude = exclude_ids or set()
        results: list[SearchResult] = []
        for item in self._items.values():
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
        """Jaccard similarity of token sets with identifier substring boost."""
        # Build query tokens from all available fields
        query_parts: list[str] = []
        if query.spec_text:
            query_parts.append(query.spec_text)
        if query.artifact_key:
            query_parts.append(query.artifact_key)
        query_parts.extend(query.keywords)
        if not query_parts:
            return 0.0

        query_tokens = set()
        for part in query_parts:
            query_tokens |= _tokenize(part)

        # Build item tokens
        item_tokens = _tokenize(item.spec_text)
        item_tokens |= _tokenize(item.location.symbol)
        for tag in item.tags:
            item_tokens |= _tokenize(tag)

        if not query_tokens or not item_tokens:
            return 0.0

        intersection = query_tokens & item_tokens
        union = query_tokens | item_tokens
        jaccard = len(intersection) / len(union) if union else 0.0

        # Containment boost: when all query tokens appear in item
        containment = len(intersection) / len(query_tokens) if query_tokens else 0.0
        if containment == 1.0:
            jaccard = max(jaccard, 0.5)  # floor at 0.5 if full query covered
        elif containment >= 0.5:
            jaccard = max(jaccard, containment * 0.5)

        # Identifier substring boost
        boost = 0.0
        if query.artifact_key and _is_identifier(query.artifact_key):
            ak_lower = query.artifact_key.lower()
            if ak_lower in item.location.symbol.lower():
                boost = 0.3
            elif ak_lower in item.spec_text.lower():
                boost = 0.15

        return min(jaccard + boost, 1.0)

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        """Load items from JSONL, rebuilding in-memory state."""
        if not self._jsonl_path.exists():
            return
        items: dict[str, WorkItem] = {}
        for line in self._jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                item = WorkItem.from_dict(d)
                items[item.work_item_id] = item  # last write wins
            except (json.JSONDecodeError, KeyError):
                logger.warning("Skipping malformed JSONL line")
        self._items = items

    def _append_jsonl(self, item: WorkItem) -> None:
        with self._jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item.to_dict()) + "\n")

    def _write_index(self) -> None:
        index: dict[str, dict[str, str]] = {}
        for wid, item in self._items.items():
            index[wid] = {
                "status": item.status,
                "owner": item.owner_slice_id,
                "spec_text_preview": item.spec_text[:80],
            }
        self._index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
