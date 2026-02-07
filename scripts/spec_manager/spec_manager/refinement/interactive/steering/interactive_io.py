"""Interactive IO for human-in-the-loop disambiguation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse

if TYPE_CHECKING:
    from spec_manager.refinement.interactive.input_signal import InputSignal


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

    def ask_signal(self, signal: InputSignal, question: str) -> SteeringResponse:
        """Present a rich signal to the user with full context.

        Args:
            signal: The InputSignal with work context.
            question: The question to ask.

        Returns:
            SteeringResponse with the user's answer and signal traceability.
        """
        ctx = signal.work_context

        print(f"\n{'=' * 60}")
        print(f"Signal: {signal.signal_id} ({signal.signal_type})")
        print(f"Severity: {signal.severity}")
        print(f"{'=' * 60}")

        print(f"\nPhase: {ctx.current_phase} (iteration {ctx.iteration})")
        if ctx.current_library:
            print(f"Library: {ctx.current_library}")
        print(f"Task: {ctx.current_task}")
        if ctx.related_libraries:
            print(f"Related: {', '.join(ctx.related_libraries)}")

        print(f"\nGoal: {signal.goal}")
        print(f"Location: {signal.encountered_location}")
        print(f"Text: {signal.encountered_text[:300]}")

        print(f"\nQuestion: {question}")

        if signal.options:
            print("\nSuggested options:")
            for i, opt in enumerate(signal.options, 1):
                print(f"  {i}. {opt}")

        print()
        response_text = input("Your response: ").strip()

        return SteeringResponse(
            ambiguity_id=signal.signal_id,
            response_text=response_text,
            source="interactive",
            signal=signal,
        )
