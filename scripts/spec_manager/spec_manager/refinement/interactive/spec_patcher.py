"""Patches specifications with disambiguation responses."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from spec_manager.planner.constraints.store import Constraint, ConstraintsStore

if TYPE_CHECKING:
    from spec_manager.refinement.interactive.input_signal import InputSignal


@dataclass
class SteeringResponse:
    """Response to an ambiguity.

    Attributes:
        ambiguity_id: ID of the resolved ambiguity.
        response_text: The clarifying response.
        source: How the response was obtained.
        signal: Optional InputSignal for traceability.
    """

    ambiguity_id: str
    response_text: str
    source: str  # interactive | steering_script | research
    signal: InputSignal | None = None


class SpecPatcher:
    """Applies disambiguation responses to specification text."""

    def __init__(self, workspace: Path | None = None) -> None:
        self._workspace = workspace
        self.last_constraints_path: Path | None = None

    def apply(
        self,
        spec_text: str,
        responses: list[SteeringResponse],
        *,
        slice_id: str = "__interactive__",
        workspace: Path | None = None,
    ) -> str:
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

        workspace_root = workspace or self._workspace
        if workspace_root is not None:
            self.last_constraints_path = self._persist_constraints(
                workspace=workspace_root,
                slice_id=slice_id,
                responses=responses,
            )
        else:
            self.last_constraints_path = None

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

    def _persist_constraints(
        self,
        *,
        workspace: Path,
        slice_id: str,
        responses: list[SteeringResponse],
    ) -> Path | None:
        constraints: list[Constraint] = []
        for response in responses:
            answer = response.response_text.strip()
            if not answer:
                continue

            question = ""
            if response.signal is not None:
                question = response.signal.question
            if not question:
                question = response.ambiguity_id

            mapped_source = self._map_source(response.source)
            confidence, validated = self._source_quality(mapped_source)
            trace = [f"response_source={response.source}"]
            if response.signal is not None:
                trace.append(f"signal_id={response.signal.signal_id}")
                trace.append(f"signal_type={response.signal.signal_type}")

            constraints.append(
                Constraint(
                    constraint_id=response.ambiguity_id,
                    question=question,
                    answer=answer,
                    source=mapped_source,
                    confidence=confidence,
                    validated=validated,
                    trace=trace,
                )
            )

        if not constraints:
            return None

        store = ConstraintsStore(workspace)
        return store.save(slice_id, constraints)

    @staticmethod
    def _map_source(source: str) -> str:
        normalized = source.strip().lower()
        if normalized in {"interactive", "user"}:
            return "user"
        if normalized in {"steering", "steering_script"}:
            return "steering"
        if normalized in {
            "research",
            "research_web",
            "research_tradeoff",
            "evidence_store",
            "planner",
        }:
            return "research"
        return "existing"

    @staticmethod
    def _source_quality(source: str) -> tuple[float, bool]:
        if source == "user":
            return (1.0, True)
        if source == "steering":
            return (0.9, True)
        if source == "research":
            return (0.6, False)
        return (0.5, False)
