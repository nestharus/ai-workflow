"""Research coordinator - sequential multi-agent research using file IO."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from spec_manager.refinement.agent_utils import run_agent
from spec_manager.refinement.formats import extract_json_from_llm_output
from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse

if TYPE_CHECKING:
    from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex

logger = logging.getLogger(__name__)


class ResearchCoordinator:
    """Sequential multi-agent research using file IO coordination.

    Flow:
    0. [Local] Evidence store search (if index available)
    1. [Opus] Signal extractor: extract search queries
    2. [GLM] Web researcher: search via Firecrawl
    3. [GPT] Synthesizer: synthesize into decision
    """

    def __init__(self, evidence_index: EvidenceIndex | None = None) -> None:
        """Initialize the research coordinator.

        Args:
            evidence_index: Optional evidence index for local search.
        """
        self._evidence_index = evidence_index

    def research(self, ambiguity: Ambiguity, workspace: Path) -> SteeringResponse:
        """Research an ambiguity using multi-agent coordination.

        Args:
            ambiguity: The ambiguity to research.
            workspace: Working directory.

        Returns:
            SteeringResponse with the research result.
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

        # Step 4: Flag as spec gap if web search also fails
        response = self._parse_decision(ambiguity, decision_json)
        if not response.response_text.strip():
            self._flag_spec_gap(ambiguity, workspace)

        return response

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

    def _parse_decision(self, ambiguity: Ambiguity, decision_json: str) -> SteeringResponse:
        """Parse decision JSON into a SteeringResponse."""
        try:
            data = extract_json_from_llm_output(
                decision_json, allow_object=True, location="research_coordinator"
            )
            if isinstance(data, dict):
                return SteeringResponse(
                    ambiguity_id=ambiguity.ambiguity_id,
                    response_text=data.get("decision", decision_json),
                    source="research",
                )
        except (ValueError, TypeError):
            pass

        return SteeringResponse(
            ambiguity_id=ambiguity.ambiguity_id,
            response_text=decision_json,
            source="research",
        )
