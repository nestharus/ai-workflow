"""Interactive refinement workflow orchestrator."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from spec_manager.refinement.interactive.ambiguity_detector import (
    AmbiguityDetector,
)
from spec_manager.refinement.interactive.input_signal import (
    InputSignal,
    WorkContext,
)
from spec_manager.refinement.interactive.signal_resolver import (
    SignalResolver,
    create_resolver,
)
from spec_manager.refinement.interactive.spec_patcher import SpecPatcher, SteeringResponse

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
        self._patcher = SpecPatcher(workspace)

        if signal_resolver is not None:
            self._resolver = signal_resolver
        else:
            mode = "interactive" if interactive else "auto"
            self._resolver = create_resolver(
                mode=mode,
                workspace=workspace,
                steering_path=steering_path,
                use_research=use_research,
                use_evidence_store=use_evidence_store,
            )

    def run(
        self,
        spec_text: str,
        *,
        slice_id: str = "__interactive__",
        on_resume_requested: Callable[[dict[str, str]], None] | None = None,
    ) -> str:
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

            unresolved_ids = self._find_unresolved_signal_ids(signals, responses)
            if unresolved_ids:
                raise RuntimeError(
                    "Interactive refinement stopped with unresolved ambiguities: "
                    + ", ".join(unresolved_ids)
                )

            resolved_slice_id = slice_id
            if resolved_slice_id == "__interactive__":
                inferred_slice_id = self._infer_slice_id(signals)
                if inferred_slice_id:
                    resolved_slice_id = inferred_slice_id

            current_spec = self._patcher.apply(
                current_spec,
                responses,
                slice_id=resolved_slice_id,
                workspace=self._workspace,
            )
            if self._patcher.last_constraints_path is not None:
                resume_payload = self._write_resume_request(
                    slice_id=resolved_slice_id,
                    iteration=iteration,
                    constraints_path=self._patcher.last_constraints_path,
                )
                if on_resume_requested is not None:
                    on_resume_requested(resume_payload)
            logger.info("Patched spec with %d responses", len(responses))

        return current_spec

    def _resolve_signal(self, signal: InputSignal) -> SteeringResponse | None:
        """Resolve a single signal."""
        return self._resolver.resolve(signal)

    @staticmethod
    def _find_unresolved_signal_ids(
        signals: list[InputSignal], responses: list[SteeringResponse]
    ) -> list[str]:
        resolved_ids = {response.ambiguity_id for response in responses}
        unresolved: list[str] = []
        for signal in signals:
            if signal.signal_id not in resolved_ids:
                unresolved.append(signal.signal_id)
        return unresolved

    @staticmethod
    def _infer_slice_id(signals: list[InputSignal]) -> str:
        for signal in signals:
            current_library = signal.work_context.current_library
            if current_library:
                return current_library
        return ""

    def _write_resume_request(
        self,
        *,
        slice_id: str,
        iteration: int,
        constraints_path: Path,
    ) -> dict[str, str]:
        out_dir = self._workspace / "analysis" / "under_spec" / slice_id
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "resume_request.json"
        payload = {
            "action": "RETRY_FROM_PLAN",
            "slice_id": slice_id,
            "iteration": str(iteration),
            "constraints_path": str(constraints_path),
            "created_at": datetime.now(UTC).isoformat(),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
