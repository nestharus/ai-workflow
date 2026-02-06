"""Patches specifications with disambiguation responses."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class SteeringResponse:
    """Response to an ambiguity.

    Attributes:
        ambiguity_id: ID of the resolved ambiguity.
        response_text: The clarifying response.
        source: How the response was obtained.
    """
    ambiguity_id: str
    response_text: str
    source: str  # interactive | steering_script | research


class SpecPatcher:
    """Applies disambiguation responses to specification text."""

    def apply(self, spec_text: str, responses: list[SteeringResponse]) -> str:
        """Apply responses to patch the specification.

        Appends clarification sections to the spec for each response.

        Args:
            spec_text: Original specification text.
            responses: List of responses to apply.

        Returns:
            Patched specification text.
        """
        if not responses:
            return spec_text

        patches: list[str] = [spec_text.rstrip()]
        patches.append("")
        patches.append("## Clarifications")
        patches.append("")

        for response in responses:
            patches.append(f"### {response.ambiguity_id}")
            patches.append(f"**Source:** {response.source}")
            patches.append(f"**Clarification:** {response.response_text}")
            patches.append("")

        return "\n".join(patches)
