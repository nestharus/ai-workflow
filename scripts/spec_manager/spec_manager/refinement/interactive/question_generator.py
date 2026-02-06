"""Question generation from detected ambiguities."""

from __future__ import annotations

from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity


class QuestionGenerator:
    """Generates clarifying questions from ambiguities."""

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
            ambiguity.ambiguity_type,
            f"Can you clarify: '{ambiguity.source_text[:100]}'?"
        )
