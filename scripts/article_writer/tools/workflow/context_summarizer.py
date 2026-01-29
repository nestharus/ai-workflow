"""Context summarizer using GLM.

Summarizes agent session context for pause/resume functionality.
Uses the glm wrapper script for compression.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PartialState:
    """Structured partial completion state for resume.

    Contains all the information needed to resume a workflow:
    - work_items: Tasks that need attention
    - gaps: Issues or missing information identified
    - questions: Questions for the user
    - next_steps: Clear next actions
    - summary: Overall summary of what happened
    """

    work_items: list[str]
    gaps: list[str]
    questions: list[str]
    next_steps: list[str]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON storage."""
        return {
            "work_items": self.work_items,
            "gaps": self.gaps,
            "questions": self.questions,
            "next_steps": self.next_steps,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PartialState:
        """Create from dictionary."""
        return cls(
            work_items=data.get("work_items", []),
            gaps=data.get("gaps", []),
            questions=data.get("questions", []),
            next_steps=data.get("next_steps", []),
            summary=data.get("summary", ""),
        )


class ContextSummarizer:
    """Summarizes session context using GLM.

    Usage:
        summarizer = ContextSummarizer()
        summary = summarizer.summarize_session(session_log_text)
        partial_state = summarizer.extract_partial_state(summary)
    """

    # Prompt template for summarization
    SUMMARIZE_PROMPT = """Summarize this agent session for workflow resume. Be concise but comprehensive.

Structure your response with these exact headers:

## Summary
Brief overview of what was accomplished and current state.

## Work Items
- List items that need attention
- Each on its own line with a dash

## Gaps
- List any issues, missing information, or blockers
- Each on its own line with a dash

## Questions
- List any questions that need user input
- Each on its own line with a dash

## Next Steps
- List clear next actions in order
- Each on its own line with a dash

---

Session Log:
{session_log}
"""

    def __init__(self, glm_cmd: str | Path = "./glm") -> None:
        """Initialize context summarizer.

        Args:
            glm_cmd: Path to glm wrapper script
        """
        self.glm_cmd = str(glm_cmd)

    def summarize_session(self, session_log: str, max_chars: int = 50000) -> str:
        """Summarize session log using GLM.

        Args:
            session_log: Formatted session log text
            max_chars: Maximum characters to include (truncates from start)

        Returns:
            Summary text from GLM
        """
        # Truncate if too long (keep recent context)
        if len(session_log) > max_chars:
            session_log = "...[truncated]...\n" + session_log[-max_chars:]

        prompt = self.SUMMARIZE_PROMPT.format(session_log=session_log)

        # Call GLM
        result = subprocess.run(
            [self.glm_cmd, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout
        )

        if result.returncode != 0:
            # Return error context for manual handling
            return f"Error summarizing: {result.stderr or 'Unknown error'}"

        return result.stdout.strip()

    def extract_partial_state(self, summary: str) -> PartialState:
        """Parse summary into structured PartialState.

        Args:
            summary: Summary text from summarize_session

        Returns:
            PartialState with extracted components
        """

        # Extract sections using regex
        def extract_section(header: str) -> list[str]:
            """Extract bullet points from a section."""
            pattern = rf"## {header}\s*\n(.*?)(?=\n## |\Z)"
            match = re.search(pattern, summary, re.DOTALL | re.IGNORECASE)
            if not match:
                return []

            section_text = match.group(1).strip()
            # Extract lines starting with - or *
            items = []
            for line in section_text.split("\n"):
                line = line.strip()
                if line.startswith(("-", "*", "•")):
                    items.append(line.lstrip("-*• ").strip())
                elif line and not line.startswith("#"):
                    # Include non-empty lines that aren't headers
                    items.append(line)
            return items

        def extract_summary_text() -> str:
            """Extract the summary section text."""
            pattern = r"## Summary\s*\n(.*?)(?=\n## |\Z)"
            match = re.search(pattern, summary, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
            # Fallback: return first paragraph
            paragraphs = summary.split("\n\n")
            return paragraphs[0].strip() if paragraphs else ""

        return PartialState(
            work_items=extract_section("Work Items"),
            gaps=extract_section("Gaps"),
            questions=extract_section("Questions"),
            next_steps=extract_section("Next Steps"),
            summary=extract_summary_text(),
        )

    def format_resume_context(self, partial_state: PartialState) -> str:
        """Format partial state as resume context for injection into prompts.

        Args:
            partial_state: PartialState from extract_partial_state

        Returns:
            Formatted markdown text for prompt injection
        """
        parts: list[str] = [
            "## Resume Context",
            "",
            "You are resuming this workflow. Here's what happened:",
            "",
            partial_state.summary,
            "",
        ]

        if partial_state.work_items:
            parts.append("### Work Items to Focus On")
            for item in partial_state.work_items:
                parts.append(f"- {item}")
            parts.append("")

        if partial_state.gaps:
            parts.append("### Known Gaps")
            for gap in partial_state.gaps:
                parts.append(f"- {gap}")
            parts.append("")

        if partial_state.questions:
            parts.append("### Questions (Now Resolved)")
            for q in partial_state.questions:
                parts.append(f"- {q}")
            parts.append("")

        if partial_state.next_steps:
            parts.append("### Next Steps")
            for i, step in enumerate(partial_state.next_steps, 1):
                parts.append(f"{i}. {step}")
            parts.append("")

        return "\n".join(parts)


def create_checkpoint_summary(
    session_log: str,
    glm_cmd: str = "./glm",
) -> tuple[str, PartialState]:
    """Convenience function to create a checkpoint summary.

    Args:
        session_log: Formatted session log text
        glm_cmd: Path to glm script

    Returns:
        Tuple of (resume_context_text, partial_state)
    """
    summarizer = ContextSummarizer(glm_cmd)
    summary = summarizer.summarize_session(session_log)
    partial_state = summarizer.extract_partial_state(summary)
    resume_context = summarizer.format_resume_context(partial_state)
    return resume_context, partial_state
