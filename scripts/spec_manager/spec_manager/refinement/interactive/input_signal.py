"""Rich input signaling for interactive refinement.

InputSignal replaces bare Ambiguity objects across the interactive pipeline,
carrying full work context so that auto-responders and human reviewers can
make informed decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity

SIGNAL_TYPES = frozenset({
    "ambiguity",
    "missing_implementation",
    "conflict",
    "undefined_boundary",
    "no_evidence",
    "tradeoff_needed",
})

SEVERITY_LEVELS = frozenset({"blocking", "degraded", "informational"})


@dataclass
class WorkContext:
    """Snapshot of the agent's current work when a signal was raised.

    Attributes:
        current_phase: Pipeline phase name (e.g. "sectionization").
        current_library: Library ID being processed, or ``None``.
        current_task: Human-readable task description.
        iteration: Current iteration number within the phase.
        artifacts_produced: List of artifact paths produced so far.
        related_libraries: Library IDs related to the current work.
    """

    current_phase: str
    current_library: str | None
    current_task: str
    iteration: int
    artifacts_produced: list[str] = field(default_factory=list)
    related_libraries: list[str] = field(default_factory=list)


@dataclass
class InputSignal:
    """Rich signal carrying full context about an issue encountered during refinement.

    Attributes:
        signal_id: Unique identifier (e.g. ``SIG-001``).
        signal_type: Category of signal (see ``SIGNAL_TYPES``).
        encountered_text: The problematic text that triggered the signal.
        encountered_location: Location in the spec (``file_id::section_id``).
        work_context: What the agent was doing when it encountered the issue.
        goal: What the agent is trying to accomplish.
        question: The clarifying question to resolve this signal.
        options: Suggested answer options (empty for open-ended).
        confidence: Detection confidence (0.0-1.0).
        severity: How critical the signal is.
        timestamp: ISO-8601 timestamp of when the signal was raised.
    """

    signal_id: str
    signal_type: str
    encountered_text: str
    encountered_location: str
    work_context: WorkContext
    goal: str
    question: str
    options: list[str] = field(default_factory=list)
    confidence: float = 0.5
    severity: str = "blocking"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_ambiguity(self) -> Ambiguity:
        """Convert this signal to a legacy ``Ambiguity`` object."""
        from spec_manager.refinement.interactive.ambiguity_detector import (
            Ambiguity,
        )

        _type_map = {
            "ambiguity": "undefined_boundary",
            "missing_implementation": "missing_condition",
            "conflict": "undefined_boundary",
            "undefined_boundary": "undefined_boundary",
            "no_evidence": "missing_condition",
            "tradeoff_needed": "vague_integration",
        }

        return Ambiguity(
            ambiguity_id=self.signal_id,
            source_text=self.encountered_text,
            source_location=self.encountered_location,
            ambiguity_type=_type_map.get(self.signal_type, "undefined_boundary"),
            confidence=self.confidence,
            suggested_question=self.question,
        )

    @classmethod
    def from_ambiguity(
        cls,
        ambiguity: Ambiguity,
        work_context: WorkContext,
    ) -> InputSignal:
        """Wrap a legacy ``Ambiguity`` in a rich ``InputSignal``."""
        _type_map = {
            "missing_condition": "ambiguity",
            "vague_integration": "ambiguity",
            "undefined_boundary": "undefined_boundary",
        }

        return cls(
            signal_id=ambiguity.ambiguity_id,
            signal_type=_type_map.get(ambiguity.ambiguity_type, "ambiguity"),
            encountered_text=ambiguity.source_text,
            encountered_location=ambiguity.source_location,
            work_context=work_context,
            goal=f"Resolve {ambiguity.ambiguity_type} in spec",
            question=ambiguity.suggested_question,
            confidence=ambiguity.confidence,
            severity="blocking",
        )
