"""Evidence tool adapter for the planner.

Wraps EvidenceIndex and EvidenceSearcher, providing a planner-facing
interface for searching hollowed specs and evidence artifacts.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class EvidenceParagraphProtocol(Protocol):
    """Projection contract for paragraph-backed search rows."""

    text: str


class EvidenceSearchRowProtocol(Protocol):
    """Projection contract for raw evidence search rows."""

    lib_id: str
    score: float
    section_path: str
    matched_keywords: list[str]
    paragraph: EvidenceParagraphProtocol
    text: str


@runtime_checkable
class EvidenceSearcherProtocol(Protocol):
    """Explicit backend contract expected by :class:`EvidenceTool`."""

    def search(
        self,
        query: str,
        *,
        max_results: int = ...,
        min_score: float = ...,
    ) -> Sequence[EvidenceSearchRowProtocol]: ...


@runtime_checkable
class AmbiguityEvidenceSearcherProtocol(EvidenceSearcherProtocol, Protocol):
    """Optional backend capability for ambiguity-specific search."""

    def search_for_ambiguity(
        self,
        ambiguity_text: str,
        ambiguity_question: str,
        context_section: str = ...,
    ) -> Sequence[EvidenceSearchRowProtocol]: ...


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
    status: str = "ok"  # ok | skipped | failed
    error: str = ""

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

    def __init__(self, evidence_searcher: EvidenceSearcherProtocol | None = None) -> None:
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
            return EvidenceSearchResult(status="skipped", error="evidence searcher not configured")

        try:
            raw_results = self._searcher.search(
                query,
                max_results=max_results,
                min_score=min_score,
            )
            hits = [self._project_hit(row) for row in raw_results]
            return EvidenceSearchResult(hits=hits, status="ok")
        except Exception as exc:
            logger.debug("Evidence search failed for query: %s", query, exc_info=True)
            return EvidenceSearchResult(
                status="failed",
                error=str(exc).strip() or "evidence search failed",
            )

    def search_for_ambiguity(
        self,
        ambiguity_text: str,
        question: str,
        context_section: str = "",
    ) -> EvidenceSearchResult:
        """Specialized search for ambiguity resolution."""
        if not self._searcher:
            return EvidenceSearchResult(status="skipped", error="evidence searcher not configured")

        if not isinstance(self._searcher, AmbiguityEvidenceSearcherProtocol):
            return self.search(f"{ambiguity_text} {question}")

        try:
            raw_results = self._searcher.search_for_ambiguity(
                ambiguity_text=ambiguity_text,
                ambiguity_question=question,
                context_section=context_section,
            )
            hits = [self._project_hit(row) for row in raw_results]
            return EvidenceSearchResult(hits=hits, status="ok")
        except Exception as exc:
            logger.debug("Ambiguity evidence search failed", exc_info=True)
            return EvidenceSearchResult(
                status="failed",
                error=str(exc).strip() or "ambiguity evidence search failed",
            )

    @staticmethod
    def _project_hit(row: object) -> EvidenceHit:
        if isinstance(row, EvidenceHit):
            return row

        if isinstance(row, dict):
            text = str(row.get("text", "") or "").strip()
            paragraph = row.get("paragraph")
            if not text and isinstance(paragraph, dict):
                text = str(paragraph.get("text", "") or "").strip()
            return EvidenceHit(
                lib_id=str(row.get("lib_id", "") or ""),
                text=text,
                score=float(row.get("score", 0.0) or 0.0),
                section_path=str(row.get("section_path", "") or ""),
                matched_keywords=[str(token) for token in row.get("matched_keywords", [])],
            )

        paragraph = getattr(row, "paragraph", None)
        paragraph_text = str(getattr(paragraph, "text", "") or "").strip() if paragraph else ""
        text = paragraph_text or str(getattr(row, "text", "") or "").strip()
        return EvidenceHit(
            lib_id=str(getattr(row, "lib_id", "") or ""),
            text=text,
            score=float(getattr(row, "score", 0.0) or 0.0),
            section_path=str(getattr(row, "section_path", "") or ""),
            matched_keywords=[str(token) for token in getattr(row, "matched_keywords", [])],
        )
