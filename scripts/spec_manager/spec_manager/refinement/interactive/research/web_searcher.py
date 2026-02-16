"""Web search for research-based ambiguity resolution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from spec_manager.core.agent_utils import run_agent
from spec_manager.refinement.formats import extract_json_from_llm_output

logger = logging.getLogger(__name__)


class WebSearchError(RuntimeError):
    """Raised when web research output is invalid or incomplete."""


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
            data = extract_json_from_llm_output(output, allow_object=True, location="web_searcher")
        except (ValueError, TypeError) as exc:
            logger.exception("Failed to parse web searcher output")
            raise WebSearchError("Web searcher output was not valid JSON") from exc

        if not isinstance(data, dict):
            raise WebSearchError("Web searcher output must be a JSON object")

        findings = data.get("findings")
        overall_summary = data.get("overall_summary")
        if not isinstance(findings, list):
            raise WebSearchError("Web searcher output missing list field 'findings'")
        if not isinstance(overall_summary, str):
            raise WebSearchError("Web searcher output missing string field 'overall_summary'")

        normalized_findings: list[dict[str, str]] = []
        for index, item in enumerate(findings, start=1):
            if not isinstance(item, dict):
                raise WebSearchError(f"Finding {index} is not an object")

            source = str(item.get("source", "")).strip()
            summary = str(item.get("summary", "")).strip()
            relevance = str(item.get("relevance", "")).strip()
            if not source or not summary:
                raise WebSearchError(
                    f"Finding {index} must include non-empty 'source' and 'summary'"
                )
            normalized_findings.append(
                {
                    "source": source,
                    "summary": summary,
                    "relevance": relevance,
                }
            )

        return {"findings": normalized_findings, "overall_summary": overall_summary.strip()}
