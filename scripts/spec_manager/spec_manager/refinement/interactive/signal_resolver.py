"""Signal resolution strategies for interactive refinement.

Provides a ``SignalResolver`` protocol and concrete implementations that
decouple *how* signals are resolved from the orchestration logic in
``InteractiveWorkflow``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from spec_manager.refinement.interactive.spec_patcher import SteeringResponse

if TYPE_CHECKING:
    from spec_manager.refinement.interactive.input_signal import InputSignal

logger = logging.getLogger(__name__)


@runtime_checkable
class SignalResolver(Protocol):
    """Protocol for resolving an ``InputSignal`` into a ``SteeringResponse``."""

    def resolve(self, signal: InputSignal) -> SteeringResponse | None:
        """Attempt to resolve a signal.

        Args:
            signal: The input signal to resolve.

        Returns:
            A ``SteeringResponse`` if resolved, ``None`` otherwise.
        """
        ...


class AutoSignalResolver:
    """Resolves signals via ``AutoResponder`` (steering script / research).

    Use case: CLI ``--auto`` mode.
    """

    def __init__(
        self,
        steering_script: object | None = None,
        use_research: bool = False,
        workspace: Path | None = None,
        evidence_index: object | None = None,
    ) -> None:
        from spec_manager.refinement.interactive.steering.auto_responder import AutoResponder

        self._auto_responder = AutoResponder(
            steering_script=steering_script,
            use_research=use_research,
            workspace=workspace,
            evidence_index=evidence_index,
        )

    def resolve(self, signal: InputSignal) -> SteeringResponse | None:
        return self._auto_responder.respond(signal)


class InteractiveSignalResolver:
    """Auto-resolve first, fall back to stdin prompt.

    Use case: CLI default (interactive) mode.
    """

    def __init__(
        self,
        steering_script: object | None = None,
        use_research: bool = False,
        workspace: Path | None = None,
        evidence_index: object | None = None,
    ) -> None:
        from spec_manager.refinement.interactive.question_generator import QuestionGenerator
        from spec_manager.refinement.interactive.steering.auto_responder import AutoResponder
        from spec_manager.refinement.interactive.steering.interactive_io import InteractiveIO

        self._auto_responder = AutoResponder(
            steering_script=steering_script,
            use_research=use_research,
            workspace=workspace,
            evidence_index=evidence_index,
        )
        self._interactive_io = InteractiveIO()
        self._question_gen = QuestionGenerator()

    def resolve(self, signal: InputSignal) -> SteeringResponse | None:
        auto_response = self._auto_responder.respond(signal)
        if auto_response is not None:
            return auto_response

        question = self._question_gen.generate_from_signal(signal)
        return self._interactive_io.ask_signal(signal, question)


class FileSignalResolver:
    """Posts signals to disk and polls for responses.

    Use case: CLI ``--file-signals`` mode for async human interaction.
    """

    def __init__(
        self,
        signals_dir: Path,
        timeout_seconds: int = 300,
        poll_interval: float = 2.0,
    ) -> None:
        from spec_manager.refinement.interactive.signal_exchange import SignalExchange

        self._exchange = SignalExchange(signals_dir)
        self._timeout = timeout_seconds
        self._poll_interval = poll_interval

    def resolve(self, signal: InputSignal) -> SteeringResponse | None:
        self._exchange.post_signals([signal])
        responses = self._exchange.wait_for_responses(
            timeout_seconds=self._timeout,
            poll_interval=self._poll_interval,
        )
        for resp in responses:
            if resp.ambiguity_id == signal.signal_id:
                return resp
        return None


class SteeringOnlyResolver:
    """Matches against a ``SteeringScript`` only — no LLM, no fallback.

    Use case: deterministic eval runs with a pre-defined steering script.
    """

    def __init__(self, steering_script: object) -> None:
        from spec_manager.refinement.interactive.steering.steering_script import SteeringScript

        if not isinstance(steering_script, SteeringScript):
            raise TypeError(
                f"Expected SteeringScript, got {type(steering_script).__name__}"
            )
        self._steering = steering_script

    def resolve(self, signal: InputSignal) -> SteeringResponse | None:
        ambiguity = signal.to_ambiguity()
        response = self._steering.match(ambiguity)
        if response is not None:
            response.signal = signal
        return response


def create_resolver(
    mode: str,
    workspace: Path | None = None,
    steering_path: Path | None = None,
    use_research: bool = False,
    use_evidence_store: bool = False,
    timeout_seconds: int = 300,
) -> SignalResolver:
    """Factory for creating a ``SignalResolver`` by mode name.

    Args:
        mode: One of ``"auto"``, ``"interactive"``, ``"file"``,
            ``"steering-only"``.
        workspace: Workspace directory (used by auto/interactive/file).
        steering_path: Path to steering script JSON.
        use_research: Enable web-research fallback (auto/interactive).
        use_evidence_store: Enable evidence-store search (auto/interactive).
        timeout_seconds: Timeout for file-based polling.

    Returns:
        A concrete ``SignalResolver`` instance.

    Raises:
        ValueError: If *mode* is not recognised.
    """
    from spec_manager.refinement.interactive.steering.steering_script import SteeringScript

    steering = SteeringScript.from_file(steering_path) if steering_path else None

    evidence_index = None
    if use_evidence_store and workspace is not None:
        try:
            from spec_manager.refinement.hollowed_spec.indexer import EvidenceIndex

            index_path = workspace / "workspace" / "indexes" / "evidence_store_index.json"
            if index_path.exists():
                evidence_index = EvidenceIndex.load(index_path)
                logger.info("Loaded evidence index from %s", index_path)
        except Exception as exc:
            logger.warning("Failed to load evidence index: %s", exc)

    if mode == "auto":
        return AutoSignalResolver(
            steering_script=steering,
            use_research=use_research,
            workspace=workspace,
            evidence_index=evidence_index,
        )

    if mode == "interactive":
        return InteractiveSignalResolver(
            steering_script=steering,
            use_research=use_research,
            workspace=workspace,
            evidence_index=evidence_index,
        )

    if mode == "file":
        if workspace is None:
            raise ValueError("workspace is required for file mode")
        signals_dir = workspace / "signals"
        return FileSignalResolver(
            signals_dir=signals_dir,
            timeout_seconds=timeout_seconds,
        )

    if mode == "steering-only":
        if steering is None:
            raise ValueError("steering_path is required for steering-only mode")
        return SteeringOnlyResolver(steering)

    raise ValueError(f"Unknown resolver mode: {mode!r}")
