"""Evidence tool adapter for the planner.

Wraps EvidenceIndex and EvidenceSearcher, providing a planner-facing
interface for searching hollowed specs and evidence artifacts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EvidenceHit:
    """A single evidence search hit."""

    lib_id: str
    text: str
    score: float = 0.0
    section_path: str = ""
    matched_keywords: list[str] = field(default_factory=list)


@dataclass
class EvidenceSearchResult:
    """Result of an evidence search."""

    hits: list[EvidenceHit] = field(default_factory=list)

    @property
    def best_hit(self) -> EvidenceHit | None:
        if not self.hits:
            return None
        return max(self.hits, key=lambda h: h.score)

    @property
    def has_results(self) -> bool:
        return len(self.hits) > 0


class EvidenceTool:
    """Planner-facing evidence search adapter.

    Wraps the evidence searcher (TF-IDF over hollowed specs) and
    provides a simplified interface for the planner.

    Dependencies injected optionally:
    - evidence_searcher: EvidenceSearcher instance (from refinement.hollowed_spec.searcher)
    """

    def __init__(self, evidence_searcher: Any = None) -> None:
        self._searcher = evidence_searcher

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        min_score: float = 0.1,
    ) -> EvidenceSearchResult:
        """Search the evidence store for relevant spec paragraphs."""
        if not self._searcher:
            return EvidenceSearchResult()

        try:
            raw_results = self._searcher.search(
                query,
                max_results=max_results,
                min_score=min_score,
            )
            hits = []
            for r in raw_results:
                text = ""
                if hasattr(r, "paragraph") and hasattr(r.paragraph, "text"):
                    text = r.paragraph.text
                elif hasattr(r, "text"):
                    text = r.text

                hits.append(
                    EvidenceHit(
                        lib_id=getattr(r, "lib_id", ""),
                        text=text,
                        score=getattr(r, "score", 0.0),
                        section_path=getattr(r, "section_path", ""),
                        matched_keywords=getattr(r, "matched_keywords", []),
                    )
                )
            return EvidenceSearchResult(hits=hits)
        except Exception:
            logger.debug("Evidence search failed for query: %s", query)
            return EvidenceSearchResult()

    def search_for_ambiguity(
        self,
        ambiguity_text: str,
        question: str,
        context_section: str = "",
    ) -> EvidenceSearchResult:
        """Specialized search for ambiguity resolution."""
        if not self._searcher or not hasattr(self._searcher, "search_for_ambiguity"):
            return self.search(f"{ambiguity_text} {question}")

        try:
            raw_results = self._searcher.search_for_ambiguity(
                ambiguity_text=ambiguity_text,
                ambiguity_question=question,
                context_section=context_section,
            )
            hits = []
            for r in raw_results:
                text = ""
                if hasattr(r, "paragraph") and hasattr(r.paragraph, "text"):
                    text = r.paragraph.text
                elif hasattr(r, "text"):
                    text = r.text

                hits.append(
                    EvidenceHit(
                        lib_id=getattr(r, "lib_id", ""),
                        text=text,
                        score=getattr(r, "score", 0.0),
                        section_path=getattr(r, "section_path", ""),
                        matched_keywords=getattr(r, "matched_keywords", []),
                    )
                )
            return EvidenceSearchResult(hits=hits)
        except Exception:
            logger.debug("Ambiguity evidence search failed")
            return EvidenceSearchResult()
