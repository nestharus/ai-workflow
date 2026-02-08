"""Search the evidence store for ambiguity resolution."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

# Reuse the same stop words filter from the extractor
from spec_manager.refinement.hollowed_spec.extractor import _ENTITY_REF_RE, _STOP_WORDS
from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex
from spec_manager.schemas.hollowed_spec import HollowedParagraph

_WORD_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


@dataclass
class SearchResult:
    """A single search result from the evidence store.

    Attributes:
        lib_id: Library containing the match
        paragraph: The matching paragraph
        score: Relevance score (0.0-1.0)
        matched_keywords: Keywords that matched the query
        matched_entities: Entities that matched the query
        section_path: Section hierarchy path
    """

    lib_id: str
    paragraph: HollowedParagraph
    score: float
    matched_keywords: list[str] = field(default_factory=list)
    matched_entities: list[str] = field(default_factory=list)
    section_path: str = ""


class EvidenceSearcher:
    """Search the hollowed-out spec evidence store.

    Supports three search modes:
    1. Keyword search: match query terms against keyword index
    2. Entity search: match entity names/IDs against entity index
    3. Hybrid search: combine keyword + entity with weighted scoring
    """

    def __init__(self, index: EvidenceIndex) -> None:
        self._index = index

    def search(
        self,
        query: str,
        *,
        entity_names: list[str] | None = None,
        max_results: int = 10,
        min_score: float = 0.1,
        exclude_lib_ids: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search the evidence store.

        Args:
            query: Free-text query (split into keywords)
            entity_names: Optional entity names to boost matches
            max_results: Maximum results to return
            min_score: Minimum relevance score threshold
            exclude_lib_ids: Libraries to exclude from results

        Returns:
            Ranked list of SearchResult objects
        """
        exclude_set = set(exclude_lib_ids) if exclude_lib_ids else set()
        query_terms = _extract_query_terms(query)
        entity_refs = entity_names or []

        if not query_terms and not entity_refs:
            return []

        # Collect candidate paragraphs with scores
        # Key: (lib_id, paragraph_id)
        candidate_scores: dict[tuple[str, str], float] = {}
        candidate_keywords: dict[tuple[str, str], list[str]] = {}
        candidate_entities: dict[tuple[str, str], list[str]] = {}

        total_paragraphs = max(self._index.total_paragraphs, 1)

        # Keyword search with TF-IDF scoring (smoothed IDF)
        for term in query_terms:
            entries = self._index.global_keyword_index.get(term, [])
            if not entries:
                continue
            # Smoothed IDF: log(1 + total_paragraphs / paragraphs_containing_term)
            # This ensures IDF > 0 even when all paragraphs contain the term
            idf = math.log(1.0 + total_paragraphs / max(len(entries), 1))

            for lib_id, para_id in entries:
                if lib_id in exclude_set:
                    continue
                key = (lib_id, para_id)
                # Compute TF for this paragraph
                spec = self._index.specs.get(lib_id)
                if spec is None:
                    continue
                para = spec.paragraphs.get(para_id)
                if para is None:
                    continue
                total_terms = max(len(para.keywords), 1)
                tf = para.keywords.count(term) / total_terms
                score = tf * idf

                candidate_scores[key] = candidate_scores.get(key, 0.0) + score
                kw_list = candidate_keywords.setdefault(key, [])
                if term not in kw_list:
                    kw_list.append(term)

        # Entity search with 2x boost (smoothed IDF)
        for entity in entity_refs:
            entries = self._index.global_entity_index.get(entity, [])
            if not entries:
                continue
            idf = math.log(1.0 + total_paragraphs / max(len(entries), 1))

            for lib_id, para_id in entries:
                if lib_id in exclude_set:
                    continue
                key = (lib_id, para_id)
                # Entity match gets 2x boost
                score = 2.0 * idf

                candidate_scores[key] = candidate_scores.get(key, 0.0) + score
                ent_list = candidate_entities.setdefault(key, [])
                if entity not in ent_list:
                    ent_list.append(entity)

        if not candidate_scores:
            return []

        # Normalize scores to 0.0-1.0
        max_score = max(candidate_scores.values()) if candidate_scores else 1.0
        if max_score <= 0:
            max_score = 1.0

        results: list[SearchResult] = []
        for key, raw_score in candidate_scores.items():
            normalized = raw_score / max_score
            if normalized < min_score:
                continue
            lib_id, para_id = key
            spec = self._index.specs.get(lib_id)
            if spec is None:
                continue
            para = spec.paragraphs.get(para_id)
            if para is None:
                continue

            results.append(
                SearchResult(
                    lib_id=lib_id,
                    paragraph=para,
                    score=normalized,
                    matched_keywords=candidate_keywords.get(key, []),
                    matched_entities=candidate_entities.get(key, []),
                    section_path=para.section_path,
                )
            )

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:max_results]

    def search_for_ambiguity(
        self,
        ambiguity_text: str,
        ambiguity_question: str,
        context_section: str = "",
        max_results: int = 5,
    ) -> list[SearchResult]:
        """Search specifically for ambiguity resolution.

        Combines the ambiguity text, question, and context section
        into a weighted query optimized for finding spec answers.

        Args:
            ambiguity_text: The ambiguous text
            ambiguity_question: The question to resolve
            context_section: Surrounding context from the translation
            max_results: Maximum results to return

        Returns:
            Ranked list of SearchResult objects
        """
        # Combine all text sources for keyword extraction
        combined = f"{ambiguity_text} {ambiguity_question} {context_section}"

        # Extract entity refs from all text
        entity_refs = _ENTITY_REF_RE.findall(combined)
        entity_refs = sorted(set(entity_refs))

        return self.search(
            query=combined,
            entity_names=entity_refs if entity_refs else None,
            max_results=max_results,
            min_score=0.1,
        )


def _extract_query_terms(query: str) -> list[str]:
    """Extract search terms from a query string."""
    words = _WORD_RE.findall(query)
    terms: list[str] = []
    seen: set[str] = set()

    for word in words:
        lower = word.lower()
        if len(lower) < 3:
            continue
        if lower in _STOP_WORDS:
            continue
        if lower in seen:
            continue
        seen.add(lower)
        terms.append(lower)

    return terms
