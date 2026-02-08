"""Proactive adjacency scanning using call graph and store touch analysis."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex
from spec_manager.refinement.hollowed_spec.searcher import EvidenceSearcher, SearchResult

logger = logging.getLogger(__name__)

_ENTITY_REF_RE = re.compile(r"ENT-\d{4}")
_STORE_KEYWORDS = frozenset(
    {
        "database",
        "table",
        "queue",
        "cache",
        "file",
        "bucket",
        "store",
        "repository",
        "collection",
        "index",
        "schema",
        "storage",
    }
)
# Match snake_case and camelCase function-like identifiers (at least 2 parts)
_FUNCTION_NAME_RE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)+)\b")
_CAMEL_CASE_RE = re.compile(r"\b([a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*)\b")


@dataclass
class AdjacencyContext:
    """Pre-fetched evidence context for a translation unit.

    Attributes:
        target_lib_id: Library being translated
        target_section: Section being translated
        adjacent_evidence: Evidence from related sections/libraries
        store_touch_evidence: Evidence from sections touching shared stores
        call_graph_evidence: Evidence from sections in the call graph
    """

    target_lib_id: str
    target_section: str
    adjacent_evidence: list[SearchResult] = field(default_factory=list)
    store_touch_evidence: list[SearchResult] = field(default_factory=list)
    call_graph_evidence: list[SearchResult] = field(default_factory=list)

    @property
    def all_evidence(self) -> list[SearchResult]:
        """Return all evidence across all categories, deduplicated."""
        seen: set[str] = set()
        results: list[SearchResult] = []
        for result in self.adjacent_evidence + self.store_touch_evidence + self.call_graph_evidence:
            key = f"{result.lib_id}:{result.paragraph.paragraph_id}"
            if key not in seen:
                seen.add(key)
                results.append(result)
        return results


class AdjacencyScanner:
    """Proactively scans the evidence store for related context.

    Uses three signals to find adjacent details:
    1. Entity co-occurrence: sections mentioning the same entities
    2. Store touches: sections describing reads/writes to the same store
    3. Call graph: sections describing functions that call each other
    """

    def __init__(self, index: EvidenceIndex) -> None:
        self._index = index
        self._searcher = EvidenceSearcher(index)

    def scan(
        self,
        lib_id: str,
        section_heading: str,
        section_content: str,
        *,
        max_results_per_signal: int = 3,
    ) -> AdjacencyContext:
        """Scan for adjacent evidence proactively.

        Args:
            lib_id: Library being worked on
            section_heading: Current section heading
            section_content: Current section content
            max_results_per_signal: Max results per signal type

        Returns:
            AdjacencyContext with pre-fetched evidence
        """
        entity_refs = _ENTITY_REF_RE.findall(section_content)
        entity_refs = sorted(set(entity_refs))

        adjacent = self._find_entity_co_occurrences(entity_refs, lib_id)[:max_results_per_signal]

        store_touch = self._find_store_touch_overlaps(section_content, lib_id)[
            :max_results_per_signal
        ]

        call_graph = self._find_call_graph_neighbors(section_content, lib_id)[
            :max_results_per_signal
        ]

        return AdjacencyContext(
            target_lib_id=lib_id,
            target_section=section_heading,
            adjacent_evidence=adjacent,
            store_touch_evidence=store_touch,
            call_graph_evidence=call_graph,
        )

    def _find_entity_co_occurrences(
        self,
        entity_refs: list[str],
        exclude_lib_id: str,
    ) -> list[SearchResult]:
        """Find paragraphs mentioning the same entities."""
        if not entity_refs:
            return []

        results = self._searcher.search(
            query="",
            entity_names=entity_refs,
            max_results=10,
            min_score=0.01,
            exclude_lib_ids=[exclude_lib_id],
        )
        return results

    def _find_store_touch_overlaps(
        self,
        section_content: str,
        exclude_lib_id: str,
    ) -> list[SearchResult]:
        """Find paragraphs describing access to the same stores.

        Looks for store-related keywords (database, table, queue, cache,
        file, bucket) co-occurring with the same named store.
        """
        # Extract store-related terms: look for store keywords followed by names
        content_lower = section_content.lower()
        store_terms: list[str] = []

        for keyword in _STORE_KEYWORDS:
            if keyword in content_lower:
                store_terms.append(keyword)

        if not store_terms:
            return []

        # Search for paragraphs mentioning the same store keywords
        query = " ".join(store_terms)
        results = self._searcher.search(
            query=query,
            max_results=10,
            min_score=0.1,
            exclude_lib_ids=[exclude_lib_id],
        )
        return results

    def _find_call_graph_neighbors(
        self,
        section_content: str,
        exclude_lib_id: str,
    ) -> list[SearchResult]:
        """Find paragraphs describing functions that appear in the call graph.

        Extracts function names from the section content and searches
        for other paragraphs mentioning those same function names.
        """
        # Extract function-like identifiers
        snake_case = _FUNCTION_NAME_RE.findall(section_content)
        camel_case = _CAMEL_CASE_RE.findall(section_content)
        function_names = sorted(set(snake_case + camel_case))

        if not function_names:
            return []

        # Search for paragraphs mentioning these function names
        query = " ".join(function_names[:10])  # Limit to avoid overly broad queries
        results = self._searcher.search(
            query=query,
            max_results=10,
            min_score=0.1,
            exclude_lib_ids=[exclude_lib_id],
        )
        return results
