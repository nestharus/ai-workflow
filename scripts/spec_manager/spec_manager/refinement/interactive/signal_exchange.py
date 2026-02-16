"""File-based signal exchange for async human interaction.

The system writes ``pending.json`` with a per-request ``request_id`` and
signals awaiting response. The human writes ``responses.json`` with the
same ``request_id`` plus a ``responses`` list. ``SignalExchange``
mediates this round-trip and consumes responses after reading.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from spec_manager.refinement.interactive.spec_patcher import SteeringResponse

if TYPE_CHECKING:
    from spec_manager.refinement.interactive.input_signal import InputSignal

logger = logging.getLogger(__name__)


class SignalExchange:
    """Read/write signals and responses via the filesystem.

    Args:
        signals_dir: Directory for ``pending.json`` / ``responses.json``.
    """

    PENDING_FILE = "pending.json"
    RESPONSES_FILE = "responses.json"

    def __init__(self, signals_dir: Path) -> None:
        self._dir = signals_dir
        self._active_request_id: str | None = None

    def post_signals(self, signals: list[InputSignal]) -> Path:
        """Write pending signals to disk.

        Args:
            signals: Signals awaiting human response.

        Returns:
            Path to the written ``pending.json``.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        request_id = uuid4().hex
        self._active_request_id = request_id

        payload = {
            "request_id": request_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "signals": [self._signal_to_dict(s) for s in signals],
        }

        path = self._dir / self.PENDING_FILE
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Posted %d signals to %s", len(signals), path)
        return path

    def check_responses(self) -> list[SteeringResponse]:
        """Read responses from disk (non-blocking).

        Returns:
            List of ``SteeringResponse`` objects, or empty list if no file.
        """
        path = self._dir / self.RESPONSES_FILE
        if not path.exists():
            return []
        if self._active_request_id is None:
            raise RuntimeError(
                "No active signal request; call post_signals() before checking responses"
            )

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read responses: %s", exc)
            return []

        if not isinstance(data, dict):
            raise TypeError("responses.json must be an object with request_id and responses fields")

        response_request_id = str(data.get("request_id", "")).strip()
        if response_request_id != self._active_request_id:
            raise ValueError(
                f"Response request_id mismatch: expected {self._active_request_id}, "
                f"got {response_request_id or '<missing>'}"
            )

        items = data.get("responses")
        if not isinstance(items, list):
            raise TypeError("responses.json field 'responses' must be a list")

        responses = [
            SteeringResponse(
                ambiguity_id=item["signal_id"],
                response_text=item["response_text"],
                source=item.get("source", "human"),
            )
            for item in items
            if isinstance(item, dict) and "signal_id" in item and "response_text" in item
        ]
        path.unlink(missing_ok=True)
        return responses

    def wait_for_responses(
        self,
        timeout_seconds: int = 300,
        poll_interval: float = 2.0,
    ) -> list[SteeringResponse]:
        """Poll for responses until they appear or timeout expires.

        Args:
            timeout_seconds: Maximum wait time.
            poll_interval: Seconds between polls.

        Returns:
            List of ``SteeringResponse`` objects.

        Raises:
            TimeoutError: If no responses arrive within *timeout_seconds*.
        """
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            responses = self.check_responses()
            if responses:
                return responses
            time.sleep(poll_interval)

        raise TimeoutError(
            f"No responses received within {timeout_seconds}s "
            f"(polling {self._dir / self.RESPONSES_FILE})"
        )

    def clear(self) -> None:
        """Remove both pending and response files."""
        for name in (self.PENDING_FILE, self.RESPONSES_FILE):
            path = self._dir / name
            if path.exists():
                path.unlink()
                logger.info("Removed %s", path)

    @staticmethod
    def _signal_to_dict(signal: InputSignal) -> dict:
        """Serialize an ``InputSignal`` to a JSON-friendly dict."""
        return {
            "signal_id": signal.signal_id,
            "signal_type": signal.signal_type,
            "question": signal.question,
            "encountered_text": signal.encountered_text,
            "encountered_location": signal.encountered_location,
            "options": signal.options,
            "goal": signal.goal,
            "confidence": signal.confidence,
            "severity": signal.severity,
            "timestamp": signal.timestamp,
            "work_context": {
                "current_phase": signal.work_context.current_phase,
                "current_library": signal.work_context.current_library,
                "current_task": signal.work_context.current_task,
                "iteration": signal.work_context.iteration,
                "artifacts_produced": signal.work_context.artifacts_produced,
                "related_libraries": signal.work_context.related_libraries,
            },
        }
