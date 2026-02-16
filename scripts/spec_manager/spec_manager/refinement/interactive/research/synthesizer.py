"""Research synthesis for ambiguity resolution."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from spec_manager.core.agent_utils import run_agent
from spec_manager.refinement.formats import extract_json_from_llm_output

logger = logging.getLogger(__name__)


class SynthesisError(RuntimeError):
    """Raised when synthesis output is invalid or unresolved."""


class Synthesizer:
    """Synthesizes research findings into decisions using GPT agent."""

    def synthesize(
        self, signals: dict[str, Any], findings: dict[str, Any], workspace: Path
    ) -> dict[str, Any]:
        """Synthesize signals and findings into a decision.

        Args:
            signals: Extracted search signals.
            findings: Web search findings.
            workspace: Working directory.

        Returns:
            Dict with decision, confidence, and reasoning.
        """
        import json

        prompt = self._build_prompt(
            json.dumps(signals, indent=2),
            json.dumps(findings, indent=2),
        )

        output = run_agent(
            agent_name="chatgpt-research-synthesizer",
            prompt=prompt,
            workspace=workspace,
        )

        return self._parse_output(output)

    def _build_prompt(self, signals_json: str, findings_json: str) -> str:
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

    def _parse_output(self, output: str) -> dict[str, Any]:
        try:
            data = extract_json_from_llm_output(output, allow_object=True, location="synthesizer")
        except (ValueError, TypeError) as exc:
            logger.exception("Failed to parse synthesizer output")
            raise SynthesisError("Synthesizer output was not valid JSON") from exc

        if not isinstance(data, dict):
            raise SynthesisError("Synthesizer output must be a JSON object")

        decision = str(data.get("decision", "")).strip()
        reasoning = str(data.get("reasoning", "")).strip()
        if not decision:
            raise SynthesisError("Synthesizer output missing non-empty 'decision'")

        try:
            confidence = float(data.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise SynthesisError("Synthesizer output has invalid 'confidence' value") from exc

        return {
            "decision": decision,
            "confidence": confidence,
            "reasoning": reasoning,
        }
