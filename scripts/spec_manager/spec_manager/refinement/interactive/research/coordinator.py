"""Research coordinator - sequential multi-agent research using file IO."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from spec_manager.core.agent_utils import run_agent
from spec_manager.refinement.formats import extract_json_from_llm_output
from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse

if TYPE_CHECKING:
    from spec_manager.core.evidence_index import EvidenceIndex

logger = logging.getLogger(__name__)

# Confidence threshold below which we generate a tradeoff analysis
TRADEOFF_CONFIDENCE_THRESHOLD = 0.5
# Confidence threshold required to auto-apply a tradeoff option.
TRADEOFF_AUTO_RESOLUTION_THRESHOLD = 0.8


class ResearchCoordinator:
    """Sequential multi-agent research using file IO coordination.

    Flow:
    0. [Local] Evidence store search (if index available)
    1. [Opus] Signal extractor: extract search queries
    2. [GLM] Web researcher: search via Firecrawl
    3. [GPT] Synthesizer: synthesize into decision
    4. If confidence < 0.5: run tradeoff analysis
    """

    def __init__(self, evidence_index: EvidenceIndex | None = None) -> None:
        """Initialize the research coordinator.

        Args:
            evidence_index: Optional evidence index for local search.
        """
        self._evidence_index = evidence_index

    def research(self, ambiguity: Ambiguity, workspace: Path) -> SteeringResponse | None:
        """Research an ambiguity using multi-agent coordination.

        Args:
            ambiguity: The ambiguity to research.
            workspace: Working directory.

        Returns:
            SteeringResponse when confidence is sufficient, else None.
        """
        # Step 0: Search evidence store first (if available)
        evidence_response = self._search_evidence_store(ambiguity, workspace)
        if evidence_response is not None:
            return evidence_response

        research_dir = workspace / "research" / ambiguity.ambiguity_id
        research_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Extract search signals
        signals_json = run_agent(
            agent_name="opus-ambiguity-signal-extractor",
            prompt=self._build_signal_prompt(ambiguity),
            workspace=workspace,
        )
        (research_dir / "signals.json").write_text(signals_json, encoding="utf-8")

        # Step 2: Web search + summarize
        findings_json = run_agent(
            agent_name="glm-web-researcher",
            prompt=self._build_search_prompt(signals_json),
            workspace=workspace,
        )
        (research_dir / "findings.json").write_text(findings_json, encoding="utf-8")

        # Step 3: Synthesize into decision
        decision_json = run_agent(
            agent_name="chatgpt-research-synthesizer",
            prompt=self._build_synthesis_prompt(signals_json, findings_json),
            workspace=workspace,
        )
        (research_dir / "decision.json").write_text(decision_json, encoding="utf-8")

        # Step 4: Check confidence and optionally run tradeoff analysis
        confidence = self._extract_confidence(decision_json)
        if confidence is None:
            logger.warning(
                "Research confidence missing for %s; escalating via tradeoff/human path",
                ambiguity.ambiguity_id,
            )
            tradeoff_response = self._run_tradeoff_analysis(
                ambiguity, decision_json, findings_json, research_dir
            )
            if tradeoff_response is not None:
                return tradeoff_response
            self._flag_spec_gap(ambiguity, workspace)
            return None

        if confidence < TRADEOFF_CONFIDENCE_THRESHOLD:
            tradeoff_response = self._run_tradeoff_analysis(
                ambiguity, decision_json, findings_json, research_dir
            )
            if tradeoff_response is not None:
                return tradeoff_response
            self._flag_spec_gap(ambiguity, workspace)
            return None

        # Step 5: Flag as spec gap if web search also fails
        response = self._parse_decision(ambiguity, decision_json)
        if response is None:
            self._flag_spec_gap(ambiguity, workspace)
            return None

        return response

    def _run_tradeoff_analysis(
        self,
        ambiguity: Ambiguity,
        decision_json: str,
        findings_json: str,
        research_dir: Path,
    ) -> SteeringResponse | None:
        """Run tradeoff analysis when confidence is low.

        In auto mode, chooses the highest-confidence option. Returns a
        SteeringResponse with the chosen option, or None if analysis fails.
        """
        best = None
        try:
            from spec_manager.refinement.interactive.research.tradeoff_analyzer import (
                TradeoffAnalyzer,
            )

            analyzer = TradeoffAnalyzer()
            analysis = analyzer.analyze(
                ambiguity_id=ambiguity.ambiguity_id,
                question=ambiguity.suggested_question,
                decision_json=decision_json,
                findings_json=findings_json,
            )

            # Persist the analysis
            analyzer.save(analysis, research_dir / "tradeoff.json")

            best = analysis.best_option()
            if best and best.confidence >= TRADEOFF_AUTO_RESOLUTION_THRESHOLD:
                logger.info(
                    "Tradeoff analysis for %s chose %s (confidence=%.0f%%)",
                    ambiguity.ambiguity_id,
                    best.option_id,
                    best.confidence * 100,
                )
                return SteeringResponse(
                    ambiguity_id=ambiguity.ambiguity_id,
                    response_text=best.description,
                    source="research_tradeoff",
                )
        except Exception as exc:
            logger.warning("Tradeoff analysis failed for %s: %s", ambiguity.ambiguity_id, exc)

        if best is not None:
            logger.info(
                "Tradeoff analysis for %s requires human resolution "
                "(best confidence %.0f%% below %.0f%% threshold)",
                ambiguity.ambiguity_id,
                best.confidence * 100,
                TRADEOFF_AUTO_RESOLUTION_THRESHOLD * 100,
            )

        return None

    def _extract_confidence(self, decision_json: str) -> float | None:
        """Extract confidence from decision JSON."""
        try:
            data = extract_json_from_llm_output(
                decision_json, allow_object=True, location="research_coordinator_confidence"
            )
            if isinstance(data, dict):
                confidence = data.get("confidence")
                if confidence is None:
                    logger.warning("Research decision JSON missing 'confidence' field")
                    return None
                return float(confidence)
        except (ValueError, TypeError) as exc:
            logger.warning("Failed to parse research confidence: %s", exc)
            return None

        logger.warning("Research decision payload is not an object")
        return None

    def _search_evidence_store(
        self, ambiguity: Ambiguity, workspace: Path
    ) -> SteeringResponse | None:
        """Search the evidence store for an answer."""
        if self._evidence_index is None:
            return None
        try:
            from spec_manager.refinement.interactive.research.evidence_store_researcher import (
                EvidenceStoreResearcher,
            )

            researcher = EvidenceStoreResearcher(self._evidence_index)
            return researcher.research(ambiguity, workspace)
        except Exception as exc:
            logger.warning("Evidence store search failed: %s", exc)
            return None

    def _flag_spec_gap(self, ambiguity: Ambiguity, workspace: Path) -> None:
        """Flag an unresolved ambiguity as a spec gap."""
        if self._evidence_index is None:
            return
        try:
            from spec_manager.refinement.interactive.research.evidence_store_researcher import (
                EvidenceStoreResearcher,
            )

            researcher = EvidenceStoreResearcher(self._evidence_index)
            researcher.flag_as_spec_gap(ambiguity, workspace)
        except Exception as exc:
            logger.warning("Failed to flag spec gap: %s", exc)

    def _build_signal_prompt(self, ambiguity: Ambiguity) -> str:
        return f"""Extract search queries to resolve the following ambiguity.

Ambiguity ID: {ambiguity.ambiguity_id}
Type: {ambiguity.ambiguity_type}
Text: {ambiguity.source_text}
Question: {ambiguity.suggested_question}

Return JSON with:
- search_queries: list of search query strings
- relevance_reasons: list of why each query is relevant
"""

    def _build_search_prompt(self, signals_json: str) -> str:
        return f"""Search the web using Firecrawl for information related to these signals.
Summarize findings relevant to resolving the ambiguity.

SIGNALS:
{signals_json}

Return JSON with:
- findings: list of {{source, summary, relevance}} objects
- overall_summary: string
"""

    def _build_synthesis_prompt(self, signals_json: str, findings_json: str) -> str:
        return f"""Synthesize the following research signals and findings into a decision.

SIGNALS:
{signals_json}

FINDINGS:
{findings_json}

Return JSON with:
- decision: the recommended resolution text
- confidence: 0.0-1.0
- reasoning: why this decision was made
"""

    def _parse_decision(self, ambiguity: Ambiguity, decision_json: str) -> SteeringResponse | None:
        """Parse decision JSON into a SteeringResponse."""
        try:
            data = extract_json_from_llm_output(
                decision_json, allow_object=True, location="research_coordinator"
            )
            if isinstance(data, dict):
                decision = str(data.get("decision", "")).strip()
                if not decision:
                    logger.warning(
                        "Research decision for %s was empty after parsing",
                        ambiguity.ambiguity_id,
                    )
                    return None
                return SteeringResponse(
                    ambiguity_id=ambiguity.ambiguity_id,
                    response_text=decision,
                    source="research_web",
                )
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Failed to parse research decision for %s: %s",
                ambiguity.ambiguity_id,
                exc,
            )
            return None

        logger.warning("Research decision for %s is not a JSON object", ambiguity.ambiguity_id)
        return None
