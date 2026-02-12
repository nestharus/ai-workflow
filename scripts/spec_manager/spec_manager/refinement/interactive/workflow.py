"""Interactive refinement workflow orchestrator."""

from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path

from spec_manager.refinement.interactive.ambiguity_detector import (
    AmbiguityDetector,
)
from spec_manager.refinement.interactive.input_signal import (
    InputSignal,
    WorkContext,
)
from spec_manager.refinement.interactive.question_generator import QuestionGenerator
from spec_manager.refinement.interactive.signal_resolver import (
    InteractiveSignalResolver,
    PlannerSignalResolver,
    SignalResolver,
)
from spec_manager.refinement.interactive.spec_patcher import SpecPatcher, SteeringResponse
from spec_manager.refinement.interactive.steering.steering_script import SteeringScript

logger = logging.getLogger(__name__)


class RefineMode(Enum):
    """How the interactive workflow resolves ambiguities."""

    AUTO = "auto"
    INTERACTIVE = "interactive"


class InteractiveWorkflow:
    """Orchestrates the interactive spec refinement workflow.

    Flow:
    1. Detect ambiguities in spec
    2. For each ambiguity: ask interactively or use auto-responder
    3. Patch spec with responses
    4. Re-detect until no ambiguities or max iterations
    """

    def __init__(
        self,
        workspace: Path,
        interactive: bool = True,
        steering_path: Path | None = None,
        use_research: bool = False,
        use_evidence_store: bool = False,
        max_iterations: int = 5,
        signal_resolver: SignalResolver | None = None,
    ) -> None:
        """Initialize the interactive workflow.

        Args:
            workspace: Working directory for spec and artifacts.
            interactive: Whether to prompt user when auto-responder fails.
            steering_path: Optional path to steering script JSON.
            use_research: Whether to enable web research fallback.
            use_evidence_store: Whether to enable evidence store search.
            max_iterations: Maximum number of refinement iterations.
            signal_resolver: Optional pre-built resolver.  When provided
                the *interactive*, *steering_path*, *use_research*, and
                *use_evidence_store* flags are ignored.
        """
        self._workspace = workspace
        self._mode = RefineMode.INTERACTIVE if interactive else RefineMode.AUTO
        self._max_iterations = max_iterations

        self._detector = AmbiguityDetector()
        self._question_gen = QuestionGenerator()
        self._patcher = SpecPatcher()

        if signal_resolver is not None:
            self._resolver = signal_resolver
        else:
            # Build resolver from legacy flags
            evidence_index = None
            if use_evidence_store:
                try:
                    from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex

                    index_path = workspace / "workspace" / "indexes" / "evidence_store_index.json"
                    if index_path.exists():
                        evidence_index = EvidenceIndex.load(index_path)
                        logger.info("Loaded evidence index from %s", index_path)
                except Exception as exc:
                    logger.warning("Failed to load evidence index: %s", exc)

            steering = SteeringScript.from_file(steering_path) if steering_path else None

            if interactive:
                self._resolver = InteractiveSignalResolver(
                    steering_script=steering,
                    use_research=use_research,
                    workspace=workspace,
                    evidence_index=evidence_index,
                )
            else:
                self._resolver = PlannerSignalResolver(
                    steering_script=steering,
                    use_research=use_research,
                    workspace=workspace,
                    evidence_index=evidence_index,
                )

    def run(self, spec_text: str) -> str:
        """Run the interactive refinement workflow.

        Args:
            spec_text: Initial specification text.

        Returns:
            Refined specification text.
        """
        current_spec = spec_text

        for iteration in range(1, self._max_iterations + 1):
            logger.info("Iteration %d: detecting ambiguities", iteration)

            work_context = WorkContext(
                current_phase="interactive_refinement",
                current_library=None,
                current_task="Detecting and resolving specification ambiguities",
                iteration=iteration,
                artifacts_produced=[],
                related_libraries=[],
            )

            signals = self._detector.detect_signals(current_spec, self._workspace, work_context)

            if not signals:
                logger.info("No ambiguities detected - spec is complete")
                break

            logger.info("Found %d ambiguities", len(signals))

            responses: list[SteeringResponse] = []
            for signal in signals:
                response = self._resolve_signal(signal)
                if response is not None:
                    responses.append(response)

            if not responses:
                logger.info("No responses obtained - stopping")
                break

            current_spec = self._patcher.apply(current_spec, responses)
            logger.info("Patched spec with %d responses", len(responses))

        return current_spec

    def _resolve_signal(self, signal: InputSignal) -> SteeringResponse | None:
        """Resolve a single signal."""
        return self._resolver.resolve(signal)
