"""Steering script matching for automated disambiguation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from spec_manager.refinement.evals.metrics import _fuzzy_ratio
from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse


class SteeringScript:
    """Matches ambiguities against a pre-defined steering script.

    Uses pattern matching with fuzzy fallback from evals/metrics.py.
    """

    def __init__(self, script_data: dict[str, Any]) -> None:
        self._level = script_data.get("level", 0)
        self._ambiguities = script_data.get("ambiguities", [])

    @classmethod
    def from_file(cls, path: Path) -> SteeringScript:
        """Load a steering script from a JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data)

    def match(self, ambiguity: Ambiguity) -> SteeringResponse | None:
        """Try to match an ambiguity against the script.

        Uses regex pattern matching first, then fuzzy matching as fallback.

        Args:
            ambiguity: The detected ambiguity.

        Returns:
            SteeringResponse if matched, None otherwise.
        """
        question = ambiguity.suggested_question.lower()
        source_text = ambiguity.source_text.lower()

        for entry in self._ambiguities:
            # Try trigger patterns (regex)
            trigger_patterns = entry.get("trigger_patterns", [])
            for pattern in trigger_patterns:
                try:
                    if re.search(pattern, source_text, re.IGNORECASE):
                        return SteeringResponse(
                            ambiguity_id=ambiguity.ambiguity_id,
                            response_text=entry["response"],
                            source="steering_script",
                        )
                except re.error:
                    continue

            # Try question patterns (regex)
            question_patterns = entry.get("question_patterns", [])
            for pattern in question_patterns:
                try:
                    if re.search(pattern, question, re.IGNORECASE):
                        return SteeringResponse(
                            ambiguity_id=ambiguity.ambiguity_id,
                            response_text=entry["response"],
                            source="steering_script",
                        )
                except re.error:
                    continue

        # Fuzzy fallback
        return self._fuzzy_match(ambiguity)

    def _fuzzy_match(self, ambiguity: Ambiguity) -> SteeringResponse | None:
        """Fuzzy match using _fuzzy_ratio from metrics."""
        best_score = 0.0
        best_entry = None

        combined = f"{ambiguity.source_text} {ambiguity.suggested_question}"

        for entry in self._ambiguities:
            response = entry.get("response", "")
            score = _fuzzy_ratio(combined, response)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry is not None and best_score >= 0.4:
            return SteeringResponse(
                ambiguity_id=ambiguity.ambiguity_id,
                response_text=best_entry["response"],
                source="steering_script",
            )

        return None
