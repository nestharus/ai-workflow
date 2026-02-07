"""Ambiguity detection in specifications using LLM agents."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from spec_manager.core.agent_utils import run_agent
from spec_manager.refinement.formats import extract_json_from_llm_output

if TYPE_CHECKING:
    from spec_manager.refinement.interactive.input_signal import (
        InputSignal,
        WorkContext,
    )

logger = logging.getLogger(__name__)


@dataclass
class Ambiguity:
    """A detected ambiguity in a specification.

    Attributes:
        ambiguity_id: Unique identifier.
        source_text: The ambiguous text.
        source_location: Location in spec (file_id::section_id).
        ambiguity_type: Type of ambiguity.
        confidence: Detection confidence (0.0-1.0).
        suggested_question: Question to resolve the ambiguity.
    """

    ambiguity_id: str
    source_text: str
    source_location: str
    ambiguity_type: str  # missing_condition | vague_integration | undefined_boundary
    confidence: float
    suggested_question: str


class AmbiguityDetector:
    """Detects ambiguities in specifications using an Opus agent."""

    def detect(
        self,
        spec_text: str,
        workspace: Path,
        work_context: WorkContext | None = None,
    ) -> list[Ambiguity]:
        """Detect ambiguities in a specification.

        Args:
            spec_text: The specification text to analyze.
            workspace: Working directory for agent execution.
            work_context: Optional context for enriching results as InputSignals.

        Returns:
            List of detected Ambiguity objects.
        """
        prompt = self._build_prompt(spec_text)

        try:
            output = run_agent(
                agent_name="opus-ambiguity-detector",
                prompt=prompt,
                workspace=workspace,
            )
        except Exception:
            logger.exception("Ambiguity detection failed")
            return []

        return self._parse_output(output)

    def detect_signals(
        self,
        spec_text: str,
        workspace: Path,
        work_context: WorkContext,
    ) -> list[InputSignal]:
        """Detect ambiguities and return rich ``InputSignal`` objects.

        Args:
            spec_text: The specification text to analyze.
            workspace: Working directory for agent execution.
            work_context: Current work context for signal enrichment.

        Returns:
            List of InputSignal objects with full context.
        """
        from spec_manager.refinement.interactive.input_signal import InputSignal

        ambiguities = self.detect(spec_text, workspace, work_context=work_context)
        return [InputSignal.from_ambiguity(amb, work_context) for amb in ambiguities]

    def _build_prompt(self, spec_text: str) -> str:
        """Build the detection prompt."""
        return f"""Analyze the following specification for ambiguities.

For each ambiguity found, identify:
1. The ambiguous text
2. Its location in the spec
3. The type of ambiguity (missing_condition, vague_integration, undefined_boundary)
4. Your confidence (0.0-1.0)
5. A specific question that would resolve it

Return a JSON array of objects with fields:
ambiguity_id, source_text, source_location, ambiguity_type, confidence, suggested_question

SPECIFICATION:
{spec_text}
"""

    def _parse_output(self, output: str) -> list[Ambiguity]:
        """Parse agent output into Ambiguity objects."""
        try:
            data = extract_json_from_llm_output(
                output, allow_array=True, allow_object=True, location="ambiguity_detector"
            )
        except (ValueError, TypeError):
            logger.exception("Failed to parse ambiguity detector output")
            return []

        items = data if isinstance(data, list) else data.get("ambiguities", [])

        ambiguities: list[Ambiguity] = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            ambiguities.append(
                Ambiguity(
                    ambiguity_id=item.get("ambiguity_id", f"AMB-{i + 1:03d}"),
                    source_text=item.get("source_text", ""),
                    source_location=item.get("source_location", ""),
                    ambiguity_type=item.get("ambiguity_type", "undefined_boundary"),
                    confidence=float(item.get("confidence", 0.5)),
                    suggested_question=item.get("suggested_question", ""),
                )
            )

        return ambiguities
