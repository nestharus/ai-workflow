"""Auto-responder that uses steering scripts or research to resolve ambiguities."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse
from spec_manager.refinement.interactive.steering.steering_script import SteeringScript

if TYPE_CHECKING:
    from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex
    from spec_manager.refinement.interactive.input_signal import InputSignal

logger = logging.getLogger(__name__)


class AutoResponder:
    """Automatically resolves ambiguities using steering scripts or research."""

    def __init__(
        self,
        steering_script: SteeringScript | None = None,
        use_research: bool = False,
        workspace: Path | None = None,
        evidence_index: EvidenceIndex | None = None,
    ) -> None:
        """Initialize the auto responder.

        Args:
            steering_script: Optional steering script for pre-defined responses.
            use_research: Whether to enable web research fallback.
            workspace: Workspace directory for research output.
            evidence_index: Optional evidence index for local search.
        """
        self._steering = steering_script
        self._use_research = use_research
        self._workspace = workspace
        self._evidence_index = evidence_index

    def respond(self, ambiguity_or_signal: Ambiguity | InputSignal) -> SteeringResponse | None:
        """Try to automatically resolve an ambiguity or input signal.

        Accepts both legacy ``Ambiguity`` and rich ``InputSignal`` objects.

        Args:
            ambiguity_or_signal: The detected ambiguity or signal.

        Returns:
            SteeringResponse if resolved, None otherwise.
        """
        # Normalise to Ambiguity for downstream compatibility
        ambiguity = self._to_ambiguity(ambiguity_or_signal)
        signal = self._to_signal(ambiguity_or_signal)

        # Try steering script first
        if self._steering is not None:
            response = self._steering.match(ambiguity)
            if response is not None:
                logger.info("Steering script matched %s", ambiguity.ambiguity_id)
                if signal is not None:
                    response.signal = signal
                return response

        # Try evidence store before web research
        if self._evidence_index is not None and self._workspace is not None:
            evidence_response = self._evidence_store_respond(ambiguity)
            if evidence_response is not None:
                if signal is not None:
                    evidence_response.signal = signal
                return evidence_response

        # Try research if enabled
        if self._use_research and self._workspace is not None:
            response = self._research_respond(ambiguity)
            if response is not None and signal is not None:
                response.signal = signal
            return response

        return None

    @staticmethod
    def _to_ambiguity(obj: Ambiguity | InputSignal) -> Ambiguity:
        if isinstance(obj, Ambiguity):
            return obj
        return obj.to_ambiguity()

    @staticmethod
    def _to_signal(obj: Ambiguity | InputSignal) -> InputSignal | None:
        from spec_manager.refinement.interactive.input_signal import InputSignal

        if isinstance(obj, InputSignal):
            return obj
        return None

    def _evidence_store_respond(self, ambiguity: Ambiguity) -> SteeringResponse | None:
        """Use evidence store to resolve ambiguity."""
        try:
            from spec_manager.refinement.interactive.research.evidence_store_researcher import (
                EvidenceStoreResearcher,
            )

            researcher = EvidenceStoreResearcher(self._evidence_index)
            return researcher.research(ambiguity, self._workspace)
        except Exception as exc:
            logger.warning(
                "Evidence store research failed for %s: %s",
                ambiguity.ambiguity_id,
                exc,
            )
            return None

    def _research_respond(self, ambiguity: Ambiguity) -> SteeringResponse | None:
        """Use research coordinator to resolve ambiguity."""
        try:
            from spec_manager.refinement.interactive.research.coordinator import (
                ResearchCoordinator,
            )

            coordinator = ResearchCoordinator(evidence_index=self._evidence_index)
            return coordinator.research(ambiguity, self._workspace)
        except Exception:
            logger.exception("Research failed for %s", ambiguity.ambiguity_id)
            return None
