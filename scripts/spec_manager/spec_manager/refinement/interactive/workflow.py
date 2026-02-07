"""Interactive refinement workflow orchestrator."""

from __future__ import annotations

import logging
from pathlib import Path

from spec_manager.refinement.interactive.ambiguity_detector import (
    Ambiguity,
    AmbiguityDetector,
)
from spec_manager.refinement.interactive.question_generator import QuestionGenerator
from spec_manager.refinement.interactive.spec_patcher import SpecPatcher, SteeringResponse
from spec_manager.refinement.interactive.steering.auto_responder import AutoResponder
from spec_manager.refinement.interactive.steering.interactive_io import InteractiveIO
from spec_manager.refinement.interactive.steering.steering_script import SteeringScript

logger = logging.getLogger(__name__)


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
    ) -> None:
        """Initialize the interactive workflow.

        Args:
            workspace: Working directory for spec and artifacts.
            interactive: Whether to prompt user when auto-responder fails.
            steering_path: Optional path to steering script JSON.
            use_research: Whether to enable web research fallback.
            use_evidence_store: Whether to enable evidence store search.
            max_iterations: Maximum number of refinement iterations.
        """
        self._workspace = workspace
        self._interactive = interactive
        self._max_iterations = max_iterations

        self._detector = AmbiguityDetector()
        self._question_gen = QuestionGenerator()
        self._patcher = SpecPatcher()

        # Load evidence index if requested
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

        # Set up responders
        steering = SteeringScript.from_file(steering_path) if steering_path else None
        self._auto_responder = AutoResponder(
            steering_script=steering,
            use_research=use_research,
            workspace=workspace,
            evidence_index=evidence_index,
        )
        self._interactive_io = InteractiveIO()

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

            ambiguities = self._detector.detect(current_spec, self._workspace)

            if not ambiguities:
                logger.info("No ambiguities detected - spec is complete")
                break

            logger.info("Found %d ambiguities", len(ambiguities))

            responses: list[SteeringResponse] = []
            for ambiguity in ambiguities:
                question = self._question_gen.generate(ambiguity)
                response = self._resolve_ambiguity(ambiguity, question)
                if response is not None:
                    responses.append(response)

            if not responses:
                logger.info("No responses obtained - stopping")
                break

            current_spec = self._patcher.apply(current_spec, responses)
            logger.info("Patched spec with %d responses", len(responses))

        return current_spec

    def _resolve_ambiguity(self, ambiguity: Ambiguity, question: str) -> SteeringResponse | None:
        """Resolve a single ambiguity."""
        # Try auto-responder first
        if not self._interactive:
            return self._auto_responder.respond(ambiguity)

        # Try auto first, fall back to interactive
        auto_response = self._auto_responder.respond(ambiguity)
        if auto_response is not None:
            return auto_response

        return self._interactive_io.ask(ambiguity, question)
