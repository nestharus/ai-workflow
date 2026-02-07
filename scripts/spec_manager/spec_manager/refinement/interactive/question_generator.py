"""Question generation from detected ambiguities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity

if TYPE_CHECKING:
    from spec_manager.refinement.interactive.input_signal import InputSignal


class QuestionGenerator:
    """Generates clarifying questions from ambiguities or input signals."""

    def generate(self, ambiguity: Ambiguity) -> str:
        """Generate a clarifying question for an ambiguity.

        If the ambiguity already has a suggested question, refine it.
        Otherwise, generate one based on the ambiguity type.
        """
        if ambiguity.suggested_question:
            return ambiguity.suggested_question

        templates = {
            "missing_condition": (
                f"What are the specific conditions under which "
                f"'{ambiguity.source_text[:100]}' should apply?"
            ),
            "vague_integration": (
                f"Where exactly should '{ambiguity.source_text[:100]}' "
                f"be integrated in the pipeline? What topics and positions?"
            ),
            "undefined_boundary": (
                f"What are the exact boundaries for "
                f"'{ambiguity.source_text[:100]}'? "
                f"What is in scope vs out of scope?"
            ),
        }

        return templates.get(
            ambiguity.ambiguity_type, f"Can you clarify: '{ambiguity.source_text[:100]}'?"
        )

    def generate_from_signal(self, signal: InputSignal) -> str:
        """Generate a richer question from an InputSignal.

        Uses work context, goal, and options to produce a more
        informative question than the bare ambiguity version.
        """
        if signal.question:
            parts = [signal.question]

            ctx = signal.work_context
            if ctx.current_library:
                parts.append(
                    f"(While working on {ctx.current_library}, "
                    f"phase: {ctx.current_phase}, "
                    f"iteration {ctx.iteration})"
                )

            if signal.goal:
                parts.append(f"Goal: {signal.goal}")

            if signal.options:
                options_text = ", ".join(signal.options)
                parts.append(f"Suggested options: {options_text}")

            return "\n".join(parts)

        # Fall back to legacy generation
        return self.generate(signal.to_ambiguity())
