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


class AmbiguityDetectionError(RuntimeError):
    """Raised when ambiguity detection cannot produce authoritative output."""


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
        except Exception as exc:
            logger.exception("Ambiguity detection failed")
            raise AmbiguityDetectionError("Failed to run ambiguity detector agent") from exc

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
        except (ValueError, TypeError) as exc:
            logger.exception("Failed to parse ambiguity detector output")
            raise AmbiguityDetectionError("Ambiguity detector output was not valid JSON") from exc

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("ambiguities")
        else:
            raise AmbiguityDetectionError("Ambiguity detector payload must be a list or object")

        if not isinstance(items, list):
            raise AmbiguityDetectionError("Ambiguity detector 'ambiguities' field must be a list")

        ambiguities: list[Ambiguity] = []
        for i, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                raise AmbiguityDetectionError(
                    f"Ambiguity entry at index {i} is not an object: {item!r}"
                )

            missing_fields = [
                field_name
                for field_name in (
                    "ambiguity_id",
                    "source_text",
                    "source_location",
                    "ambiguity_type",
                    "suggested_question",
                )
                if not str(item.get(field_name, "")).strip()
            ]
            if missing_fields:
                raise AmbiguityDetectionError(
                    f"Ambiguity entry at index {i} missing required fields: {missing_fields}"
                )

            try:
                confidence = float(item["confidence"])
            except (KeyError, TypeError, ValueError) as exc:
                raise AmbiguityDetectionError(
                    "Ambiguity entry at index "
                    f"{i} has invalid confidence: {item.get('confidence')!r}"
                ) from exc

            ambiguities.append(
                Ambiguity(
                    ambiguity_id=str(item["ambiguity_id"]).strip(),
                    source_text=str(item["source_text"]),
                    source_location=str(item["source_location"]),
                    ambiguity_type=str(item["ambiguity_type"]).strip(),
                    confidence=confidence,
                    suggested_question=str(item["suggested_question"]),
                )
            )

        return ambiguities
