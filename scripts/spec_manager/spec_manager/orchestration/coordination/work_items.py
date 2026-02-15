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
from collections.abc import Callable
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
    need_summary: str = ""
    spec_refs: list[dict[str, Any]] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    max_results: int = 20


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
    coverage: Literal["FULL", "PARTIAL", "NONE"] = "NONE"
    confidence: float = 0.0
    why: str = ""
    missing_coverage: bool = False


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
        semantic_rerank_tool: Callable[..., Any] | Any | None = None,
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

    def add(self, item: WorkItem) -> None:
        """Append a work item to JSONL and rebuild index."""
        if not item.created_at:
            item.created_at = datetime.now(UTC).isoformat()
        item.updated_at = item.created_at
        item.metadata = dict(item.metadata or {})
        item.metadata["spec_fingerprint"] = _fingerprint(item.spec_text)
        self._items[item.work_item_id] = item
        self._rebuild_fingerprint_index()
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
        item.metadata = dict(item.metadata or {})
        item.metadata["spec_fingerprint"] = _fingerprint(item.spec_text)
        self._rebuild_fingerprint_index()
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
        """3-stage retrieval: exact -> fuzzy -> semantic rerank."""
        outcome = self.search_with_coverage(query)
        return outcome["results"]

    def search_with_coverage(self, query: SearchQuery) -> dict[str, Any]:
        """Run retrieval and return matches plus FULL/PARTIAL/NONE coverage."""
        results: list[SearchResult] = []
        exact = self._search_exact(query)
        results.extend(exact)

        if len(results) < query.max_results:
            seen_ids = {r.work_item.work_item_id for r in results}
            fuzzy = self._search_fuzzy(query, exclude_ids=seen_ids)

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
                coverage = SearchCoverage(coverage="NONE", missing_coverage=True)
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
                "coverage": "FULL",
                "confidence": 1.0,
                "why": "exact_spec_text_match",
                "missing_coverage": False,
            }

        if coverage.coverage == "NONE" and capped:
            coverage = self._infer_coverage_from_ranked_results(capped)

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
            "missing_coverage": coverage.missing_coverage,
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
            return [], SearchCoverage(coverage="NONE", missing_coverage=True)

        parsed = self._call_semantic_reranker(query, candidates)
        if parsed is None:
            fallback = self._fallback_semantic_rerank(query, candidates)
            return fallback, self._infer_coverage_from_ranked_results(fallback)

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

        coverage_raw = str(parsed.get("coverage", "NONE")).upper()
        coverage_value: Literal["FULL", "PARTIAL", "NONE"] = (
            coverage_raw if coverage_raw in {"FULL", "PARTIAL", "NONE"} else "NONE"
        )
        if not primary_id and coverage_value != "NONE" and candidate_ids:
            primary_id = candidate_ids[0]

        confidence = self._safe_float(parsed.get("confidence", 0.0))
        why = str(parsed.get("why", parsed.get("rationale", "")))
        missing_raw = parsed.get("missing_coverage", coverage_value != "FULL")
        if isinstance(missing_raw, str):
            missing_coverage = missing_raw.strip().lower() in {"1", "true", "yes"}
        else:
            missing_coverage = bool(missing_raw)

        ordered_ids: list[str] = []
        if primary_id:
            ordered_ids.append(primary_id)
        ordered_ids.extend(sid for sid in secondary_ids if sid not in ordered_ids)
        ordered_ids.extend(wid for wid in candidate_ids if wid not in ordered_ids)
        if not ordered_ids:
            ordered_ids = list(candidate_ids)

        denominator = max(len(ordered_ids) - 1, 1)
        rank_to_score = {
            wid: max(0.1, 1.0 - (idx / denominator) * 0.4) for idx, wid in enumerate(ordered_ids)
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
            missing_coverage=missing_coverage,
        )
        return reranked, coverage

    # -- Stage A: exact ----------------------------------------------------

    def _search_exact(self, query: SearchQuery) -> list[SearchResult]:
        results: list[SearchResult] = []
        if query.spec_text:
            fp = _fingerprint(query.spec_text)
            # Fingerprint match via explicit fingerprint -> work_item_id index.
            for work_item_id in self._spec_fingerprint_index.get(fp, []):
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
            query_norm = _normalize(query.spec_text)
            seen = {r.work_item.work_item_id for r in results}
            for item in self._items.values():
                if item.work_item_id in seen:
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
                    seen.add(item.work_item_id)
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
        item_tokens = _tokenize(item.spec_text)
        item_tokens |= _tokenize(item.location.file)
        item_tokens |= _tokenize(item.location.symbol)
        for tag in item.tags:
            item_tokens |= _tokenize(tag)

        if not query_tokens or not item_tokens:
            return 0.0

        intersection = query_tokens & item_tokens
        union = query_tokens | item_tokens
        jaccard = len(intersection) / len(union) if union else 0.0

        # Coverage of query tokens by item tokens.
        containment = len(intersection) / len(query_tokens) if query_tokens else 0.0
        query_text = " ".join(query_parts)
        item_text = " ".join([item.spec_text, item.location.file, item.location.symbol, *item.tags])
        trigram = _trigram_similarity(query_text, item_text)

        # Identifier substring boost
        boost = 0.0
        if query.artifact_key and _is_identifier(query.artifact_key):
            ak_lower = query.artifact_key.lower()
            if ak_lower in item.location.symbol.lower():
                boost = 0.3
            elif ak_lower in item.location.file.lower():
                boost = 0.2
            elif ak_lower in item.spec_text.lower():
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
            "spec_text": query.spec_text,
            "keywords": list(query.keywords),
            "candidates": [
                {
                    "work_item_id": item.work_item_id,
                    "spec_text": item.spec_text,
                    "status": item.status,
                    "location": item.location.to_dict(),
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
            logger.debug(
                "Semantic rerank tool failed; falling back to lexical order", exc_info=True
            )
            return None

        parsed = self._parse_semantic_output(raw)
        if parsed is None:
            logger.debug("Semantic rerank output was not parseable; falling back to lexical order")
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
                loc = c.get("location", {}) if isinstance(c.get("location", {}), dict) else {}
                candidate_lines.append(
                    f"- id={c.get('work_item_id', '')} "
                    f"status={c.get('status', '')} "
                    f"file={loc.get('file', '')} "
                    f"symbol={loc.get('symbol', '')} "
                    f"spec={str(c.get('spec_text', ''))[:220]}"
                )
        candidates_block = "\n".join(candidate_lines) if candidate_lines else "- (none)"

        return (
            "You are reranking dependency work items.\n"
            "Choose which candidates satisfy the dependency request.\n"
            "Return strict JSON only with keys:\n"
            "primary_match_id (string or empty),\n"
            "secondary_match_ids (array of strings),\n"
            "coverage (FULL|PARTIAL|NONE),\n"
            "confidence (0..1),\n"
            "why (short string),\n"
            "missing_coverage (boolean).\n\n"
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
                match_reason="semantic_rerank_fallback",
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

    def _infer_coverage_from_ranked_results(
        self,
        ranked: list[SearchResult],
    ) -> SearchCoverage:
        if not ranked:
            return SearchCoverage(
                coverage="NONE", confidence=0.0, why="no_candidates", missing_coverage=True
            )

        top = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        score_gap = top.score - second.score if second is not None else top.score

        if top.score >= 0.75 and score_gap >= 0.15:
            return SearchCoverage(
                primary_match_id=top.work_item.work_item_id,
                secondary_match_ids=[],
                coverage="FULL",
                confidence=min(1.0, max(top.score, 0.85)),
                why="single_clear_match",
                missing_coverage=False,
            )

        if top.score >= 0.35:
            secondary_ids = [
                r.work_item.work_item_id for r in ranked[1:4] if r.score >= top.score - 0.1
            ]
            return SearchCoverage(
                primary_match_id=top.work_item.work_item_id,
                secondary_match_ids=secondary_ids,
                coverage="PARTIAL",
                confidence=max(0.0, min(top.score, 1.0)),
                why="ambiguous_or_partial_match",
                missing_coverage=True,
            )

        return SearchCoverage(
            coverage="NONE",
            confidence=max(0.0, min(top.score, 1.0)),
            why="low_similarity_candidates",
            missing_coverage=True,
        )

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
                item.metadata = dict(item.metadata or {})
                item.metadata["spec_fingerprint"] = _fingerprint(item.spec_text)
                items[item.work_item_id] = item  # last write wins
            except (json.JSONDecodeError, KeyError):
                logger.warning("Skipping malformed JSONL line")
        self._items = items
        self._rebuild_fingerprint_index()

    def _append_jsonl(self, item: WorkItem) -> None:
        with self._jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item.to_dict()) + "\n")

    def _write_index(self) -> None:
        index: dict[str, Any] = {}
        for wid, item in self._items.items():
            spec_fingerprint = _fingerprint(item.spec_text)
            index[wid] = {
                "status": item.status,
                "owner": item.owner_slice_id,
                "spec_text_preview": item.spec_text[:80],
                "spec_fingerprint": spec_fingerprint,
            }
        index["__spec_fingerprint_index__"] = self._spec_fingerprint_index
        self._index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    def _rebuild_fingerprint_index(self) -> None:
        index: dict[str, list[str]] = {}
        for wid, item in self._items.items():
            spec_fingerprint = _fingerprint(item.spec_text)
            item.metadata = dict(item.metadata or {})
            item.metadata["spec_fingerprint"] = spec_fingerprint
            ids = index.setdefault(spec_fingerprint, [])
            ids.append(wid)
        self._spec_fingerprint_index = index
