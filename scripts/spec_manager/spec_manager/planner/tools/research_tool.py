"""Research tool adapter for the planner.

Wraps ResearchCoordinator and EvidenceStoreResearcher, providing
a unified research interface for the planner to consume.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ResearchQuery:
    """A research question from the planner."""

    question: str
    context: str = ""
    dimension: str = "local"  # local | layer | web | external
    max_results: int = 5


@dataclass
class ResearchFinding:
    """A single finding from research."""

    source: str  # evidence_store | steering | web | external
    text: str
    confidence: float = 0.0
    refs: list[str] = field(default_factory=list)


@dataclass
class ResearchResult:
    """Aggregated research outcome."""

    findings: list[ResearchFinding] = field(default_factory=list)
    synthesis: str = ""
    confidence: float = 0.0

    @property
    def has_answer(self) -> bool:
        return self.confidence > 0.0 and bool(self.synthesis)


class ResearchTool:
    """Planner-facing research adapter.

    Accepts optional injected dependencies:
    - evidence_searcher: for local evidence store search
    - research_coordinator: for multi-agent web research
    - steering_script: for pre-defined steering responses

    All dependencies are optional. If not provided, that research
    dimension is skipped.
    """

    def __init__(
        self,
        evidence_searcher: Any = None,
        research_coordinator: Any = None,
        steering_script: Any = None,
        workspace: Path | None = None,
    ) -> None:
        self._evidence_searcher = evidence_searcher
        self._coordinator = research_coordinator
        self._steering = steering_script
        self._workspace = workspace

    def research(self, query: ResearchQuery) -> ResearchResult:
        """Execute a research query across available dimensions.

        Resolution order (gated escalation):
        1. Steering script match (if available)
        2. Evidence store search (if available)
        3. Research coordinator / web (if available and dimension requires it)
        """
        findings: list[ResearchFinding] = []

        # 1. Steering script
        if self._steering is not None and query.dimension in ("local", "layer"):
            try:
                match = self._steering.match(query.question)
                if match:
                    findings.append(
                        ResearchFinding(
                            source="steering",
                            text=str(match),
                            confidence=0.9,
                        )
                    )
            except Exception:
                logger.debug("Steering match failed for query: %s", query.question)

        # 2. Evidence store
        if self._evidence_searcher is not None:
            try:
                results = self._evidence_searcher.search(
                    query.question,
                    max_results=query.max_results,
                )
                for r in results:
                    findings.append(
                        ResearchFinding(
                            source="evidence_store",
                            text=getattr(r, "text", str(r)),
                            confidence=getattr(r, "score", 0.5),
                            refs=[getattr(r, "lib_id", ""), getattr(r, "section_path", "")],
                        )
                    )
            except Exception:
                logger.debug("Evidence search failed for query: %s", query.question)

        # 3. Web research (only if dimension requires it)
        if self._coordinator is not None and query.dimension in ("web", "external"):
            try:
                # ResearchCoordinator.research() takes Ambiguity + workspace
                # We'll need to adapt when fully wired — for now, log and skip
                logger.debug("Web research requested but coordinator wiring pending")
            except Exception:
                logger.debug("Research coordinator failed for query: %s", query.question)

        # Synthesize
        if findings:
            best = max(findings, key=lambda f: f.confidence)
            return ResearchResult(
                findings=findings,
                synthesis=best.text,
                confidence=best.confidence,
            )

        return ResearchResult()
