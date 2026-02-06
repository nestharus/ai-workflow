"""Interactive IO for human-in-the-loop disambiguation."""

from __future__ import annotations

import sys

from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse


class InteractiveIO:
    """Handles interactive disambiguation via stdin/stdout."""

    def ask(self, ambiguity: Ambiguity, question: str) -> SteeringResponse:
        """Present a question to the user and get a response.

        Args:
            ambiguity: The detected ambiguity.
            question: The question to ask.

        Returns:
            SteeringResponse with the user's answer.
        """
        print(f"\n--- Ambiguity Detected ({ambiguity.ambiguity_id}) ---")
        print(f"Type: {ambiguity.ambiguity_type}")
        print(f"Location: {ambiguity.source_location}")
        print(f"Text: {ambiguity.source_text[:200]}")
        print(f"\nQuestion: {question}")
        print()

        response_text = input("Your response: ").strip()

        return SteeringResponse(
            ambiguity_id=ambiguity.ambiguity_id,
            response_text=response_text,
            source="interactive",
        )
