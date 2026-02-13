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

    source: str  # evidence_store | steering | web_research | external
    text: str
    confidence: float = 0.0
    refs: list[str] = field(default_factory=list)


@dataclass
class ResearchResult:
    """Aggregated research outcome."""

    findings: list[ResearchFinding] = field(default_factory=list)
    synthesis: str = ""
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

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
        dimension = (query.dimension or "local").strip().lower()
        findings: list[ResearchFinding] = []
        metadata: dict[str, Any] = {
            "requested_dimension": dimension,
            "stages": [],
        }

        def log_stage(stage: str, status: str, detail: str) -> None:
            metadata["stages"].append({"stage": stage, "status": status, "detail": detail})

        # 1. Steering script
        if self._steering is not None and dimension in ("local", "layer"):
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
                    log_stage("steering", "hit", "steering script returned a match")
                else:
                    log_stage("steering", "miss", "steering script returned no match")
            except Exception:
                logger.debug("Steering match failed for query: %s", query.question)
                log_stage("steering", "failed", "steering script raised")
        else:
            if self._steering is None:
                log_stage("steering", "skipped", "steering script not configured")
            else:
                log_stage(
                    "steering",
                    "skipped",
                    f"dimension={dimension} does not request local/layer steering",
                )

        # 2. Evidence store
        if self._evidence_searcher is not None:
            try:
                results = self._evidence_searcher.search(
                    query.question,
                    max_results=query.max_results,
                )
                if results:
                    for r in results:
                        findings.append(
                            ResearchFinding(
                                source="evidence_store",
                                text=getattr(r, "text", str(r)),
                                confidence=getattr(r, "score", 0.5),
                                refs=[getattr(r, "lib_id", ""), getattr(r, "section_path", "")],
                            )
                        )
                    log_stage("evidence_store", "hit", f"{len(results)} total matches")
                else:
                    log_stage("evidence_store", "miss", "no matches")
            except Exception:
                logger.debug("Evidence search failed for query: %s", query.question)
                log_stage("evidence_store", "failed", "search raised")
        else:
            log_stage("evidence_store", "skipped", "evidence searcher not configured")

        # 3. Web research (only if dimension requires it)
        if self._coordinator is not None and dimension in ("web", "external"):
            try:
                from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity

                ambiguity = Ambiguity(
                    ambiguity_id=f"research-{query.question[:32]}",
                    source_text=query.question,
                    source_location=query.context or "",
                    ambiguity_type="vague_integration",
                    confidence=0.5,
                    suggested_question=query.question,
                )
                response = self._coordinator.research(ambiguity, self._workspace)
                if response is not None:
                    findings.append(
                        ResearchFinding(
                            source="web_research",
                            text=response.response_text,
                            confidence=0.7,
                        )
                    )
                log_stage("web_research", "hit", "coordinator returned response")
            except Exception as exc:
                logger.warning("Web research failed: %s", exc)
                log_stage("web_research", "failed", str(exc))
        else:
            if dimension in ("web", "external"):
                log_stage("web_research", "skipped", "coordinator not configured")
            else:
                log_stage(
                    "web_research",
                    "skipped",
                    f"dimension={dimension} does not request web",
                )

        # Synthesize
        if findings:
            best = max(findings, key=lambda f: f.confidence)
            return ResearchResult(
                findings=findings,
                synthesis=best.text,
                confidence=best.confidence,
                metadata=metadata,
            )

        return ResearchResult(metadata=metadata)
