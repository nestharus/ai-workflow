"""Research coordinator - sequential multi-agent research using file IO."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from spec_manager.refinement.agent_utils import run_agent
from spec_manager.refinement.formats import extract_json_from_llm_output
from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse

logger = logging.getLogger(__name__)


class ResearchCoordinator:
    """Sequential multi-agent research using file IO coordination.

    Flow:
    1. [Opus] Signal extractor: extract search queries
    2. [GLM] Web researcher: search via Firecrawl
    3. [GPT] Synthesizer: synthesize into decision
    """

    def research(self, ambiguity: Ambiguity, workspace: Path) -> SteeringResponse:
        """Research an ambiguity using multi-agent coordination.

        Args:
            ambiguity: The ambiguity to research.
            workspace: Working directory.

        Returns:
            SteeringResponse with the research result.
        """
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

        return self._parse_decision(ambiguity, decision_json)

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
