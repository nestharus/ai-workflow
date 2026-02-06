"""Web search for research-based ambiguity resolution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from spec_manager.refinement.agent_utils import run_agent
from spec_manager.refinement.formats import extract_json_from_llm_output

logger = logging.getLogger(__name__)


class WebSearcher:
    """Searches the web for information using GLM agent with Firecrawl."""

    def search(self, signals: dict[str, Any], workspace: Path) -> dict[str, Any]:
        """Search the web based on extracted signals.

        Args:
            signals: Dict with search_queries and relevance_reasons.
            workspace: Working directory.

        Returns:
            Dict with findings and overall_summary.
        """
        import json

        prompt = self._build_prompt(json.dumps(signals, indent=2))

        output = run_agent(
            agent_name="glm-web-researcher",
            prompt=prompt,
            workspace=workspace,
        )

        return self._parse_output(output)

    def _build_prompt(self, signals_json: str) -> str:
        return f"""Search the web using Firecrawl for information related to these signals.
Summarize findings relevant to resolving the ambiguity.

SIGNALS:
{signals_json}

Return JSON with:
- findings: list of {{source, summary, relevance}} objects
- overall_summary: string
"""

    def _parse_output(self, output: str) -> dict[str, Any]:
        try:
            data = extract_json_from_llm_output(
                output, allow_object=True, location="web_searcher"
            )
            if isinstance(data, dict):
                return data
        except (ValueError, TypeError) as exc:
            logger.error("Failed to parse web searcher output: %s", exc)

        return {"findings": [], "overall_summary": ""}
