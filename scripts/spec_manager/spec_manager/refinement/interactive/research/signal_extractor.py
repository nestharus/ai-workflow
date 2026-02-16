"""Signal extraction for research-based ambiguity resolution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from spec_manager.core.agent_utils import run_agent
from spec_manager.refinement.formats import extract_json_from_llm_output
from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity

logger = logging.getLogger(__name__)


class SignalExtractionError(RuntimeError):
    """Raised when search signals cannot be extracted authoritatively."""


class SignalExtractor:
    """Extracts search signals from ambiguities using Opus agent."""

    def extract(self, ambiguity: Ambiguity, workspace: Path) -> dict[str, Any]:
        """Extract search queries and relevance reasons.

        Args:
            ambiguity: The ambiguity to analyze.
            workspace: Working directory.

        Returns:
            Dict with search_queries and relevance_reasons.
        """
        prompt = self._build_prompt(ambiguity)

        output = run_agent(
            agent_name="opus-ambiguity-signal-extractor",
            prompt=prompt,
            workspace=workspace,
        )

        return self._parse_output(output)

    def _build_prompt(self, ambiguity: Ambiguity) -> str:
        return f"""Extract search queries to resolve the following ambiguity.

Ambiguity ID: {ambiguity.ambiguity_id}
Type: {ambiguity.ambiguity_type}
Text: {ambiguity.source_text}
Question: {ambiguity.suggested_question}

Return JSON with:
- search_queries: list of search query strings
- relevance_reasons: list of why each query is relevant
"""

    def _parse_output(self, output: str) -> dict[str, Any]:
        try:
            data = extract_json_from_llm_output(
                output, allow_object=True, location="signal_extractor"
            )
        except (ValueError, TypeError) as exc:
            logger.exception("Failed to parse signal extractor output")
            raise SignalExtractionError("Signal extractor output was not valid JSON") from exc

        if not isinstance(data, dict):
            raise SignalExtractionError("Signal extractor output must be a JSON object")

        search_queries = data.get("search_queries")
        relevance_reasons = data.get("relevance_reasons")

        if not isinstance(search_queries, list):
            raise SignalExtractionError(
                "Signal extractor output missing list field 'search_queries'"
            )
        if not isinstance(relevance_reasons, list):
            raise SignalExtractionError(
                "Signal extractor output missing list field 'relevance_reasons'"
            )

        normalized_queries = [str(query).strip() for query in search_queries if str(query).strip()]
        normalized_reasons = [
            str(reason).strip() for reason in relevance_reasons if str(reason).strip()
        ]
        return {
            "search_queries": normalized_queries,
            "relevance_reasons": normalized_reasons,
        }
