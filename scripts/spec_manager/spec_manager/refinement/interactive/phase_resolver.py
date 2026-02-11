"""Phase-boundary ambiguity resolution.

``PhaseResolver`` wraps a ``SignalResolver`` with ``AmbiguityDetector`` and
``SpecPatcher`` to provide a single-call detect-resolve-patch loop that
can be used at phase boundaries outside the interactive workflow.
"""

from __future__ import annotations

import logging
from pathlib import Path

from spec_manager.refinement.interactive.ambiguity_detector import AmbiguityDetector
from spec_manager.refinement.interactive.input_signal import WorkContext
from spec_manager.refinement.interactive.signal_resolver import SignalResolver
from spec_manager.refinement.interactive.spec_patcher import SpecPatcher, SteeringResponse

logger = logging.getLogger(__name__)


class PhaseResolver:
    """Detect-resolve-patch loop for phase-boundary ambiguity resolution.

    Args:
        signal_resolver: Strategy used to resolve each detected signal.
        max_iterations: Maximum detect-resolve-patch iterations.
    """

    def __init__(
        self,
        signal_resolver: SignalResolver,
        max_iterations: int = 3,
    ) -> None:
        self._resolver = signal_resolver
        self._max_iterations = max_iterations
        self._detector = AmbiguityDetector()
        self._patcher = SpecPatcher()

    def resolve_phase_output(
        self,
        workspace: Path,
        phase_name: str,
        spec_text: str,
        library_id: str | None = None,
    ) -> str:
        """Run detect-resolve-patch loop on phase output text.

        Args:
            workspace: Workspace directory for agent execution.
            phase_name: Name of the phase being resolved.
            spec_text: The phase output text to refine.
            library_id: Optional library ID for context.

        Returns:
            Refined text after all iterations.
        """
        current_text = spec_text

        for iteration in range(1, self._max_iterations + 1):
            logger.info(
                "PhaseResolver %s iteration %d: detecting ambiguities",
                phase_name,
                iteration,
            )

            work_context = WorkContext(
                current_phase=phase_name,
                current_library=library_id,
                current_task=f"Resolving ambiguities in {phase_name} output",
                iteration=iteration,
            )

            signals = self._detector.detect_signals(current_text, workspace, work_context)

            if not signals:
                logger.info(
                    "PhaseResolver %s: no ambiguities at iteration %d",
                    phase_name,
                    iteration,
                )
                break

            logger.info(
                "PhaseResolver %s: found %d ambiguities",
                phase_name,
                len(signals),
            )

            responses: list[SteeringResponse] = []
            for signal in signals:
                response = self._resolver.resolve(signal)
                if response is not None:
                    responses.append(response)

            if not responses:
                logger.info(
                    "PhaseResolver %s: no responses obtained - stopping",
                    phase_name,
                )
                break

            current_text = self._patcher.apply(current_text, responses)
            logger.info(
                "PhaseResolver %s: patched with %d responses",
                phase_name,
                len(responses),
            )

        return current_text
