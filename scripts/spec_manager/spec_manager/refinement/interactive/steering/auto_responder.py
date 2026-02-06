"""Auto-responder that uses steering scripts or research to resolve ambiguities."""

from __future__ import annotations

import logging
from pathlib import Path

from spec_manager.refinement.interactive.ambiguity_detector import Ambiguity
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse
from spec_manager.refinement.interactive.steering.steering_script import SteeringScript

logger = logging.getLogger(__name__)


class AutoResponder:
    """Automatically resolves ambiguities using steering scripts or research."""

    def __init__(
        self,
        steering_script: SteeringScript | None = None,
        use_research: bool = False,
        workspace: Path | None = None,
    ) -> None:
        self._steering = steering_script
        self._use_research = use_research
        self._workspace = workspace

    def respond(self, ambiguity: Ambiguity) -> SteeringResponse | None:
        """Try to automatically resolve an ambiguity.

        Args:
            ambiguity: The detected ambiguity.

        Returns:
            SteeringResponse if resolved, None otherwise.
        """
        # Try steering script first
        if self._steering is not None:
            response = self._steering.match(ambiguity)
            if response is not None:
                logger.info(
                    "Steering script matched %s", ambiguity.ambiguity_id
                )
                return response

        # Try research if enabled
        if self._use_research and self._workspace is not None:
            return self._research_respond(ambiguity)

        return None

    def _research_respond(self, ambiguity: Ambiguity) -> SteeringResponse | None:
        """Use research coordinator to resolve ambiguity."""
        try:
            from spec_manager.refinement.interactive.research.coordinator import (
                ResearchCoordinator,
            )
            coordinator = ResearchCoordinator()
            return coordinator.research(ambiguity, self._workspace)
        except Exception as exc:
            logger.error("Research failed for %s: %s", ambiguity.ambiguity_id, exc)
            return None
