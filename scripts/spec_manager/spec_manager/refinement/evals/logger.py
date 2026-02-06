"""JSONL logging for evaluation observability.

Provides structured logging of evaluation events in JSONL format for
post-hoc analysis and debugging.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class EvalLogEntry:
    """A single log entry for evaluation events.

    Attributes:
        timestamp: ISO format timestamp.
        event_type: Type of event (e.g., phase_start, iteration_complete).
        spec_id: ID of the spec being evaluated.
        phase: Current phase name.
        iteration: Current iteration number within the phase.
        data: Additional event-specific data.
    """

    timestamp: str
    event_type: str
    spec_id: str
    phase: str | None = None
    iteration: int | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        result = {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "spec_id": self.spec_id,
        }
        if self.phase is not None:
            result["phase"] = self.phase
        if self.iteration is not None:
            result["iteration"] = self.iteration
        if self.data:
            result.update(self.data)
        return result

    def to_jsonl(self) -> str:
        """Convert to JSONL string."""
        return json.dumps(self.to_dict(), default=str)


class EvalLogger:
    """JSONL logger for evaluation events.

    Writes structured log entries to a JSONL file for observability
    and debugging of evaluation runs.

    Attributes:
        log_path: Path to the JSONL log file.
        spec_id: ID of the current spec being evaluated.
    """

    def __init__(self, log_path: Path, spec_id: str = "unknown") -> None:
        """Initialize the logger.

        Args:
            log_path: Path to the JSONL log file.
            spec_id: ID of the current spec being evaluated.
        """
        self.log_path = log_path
        self.spec_id = spec_id
        self._ensure_parent_exists()

    def _ensure_parent_exists(self) -> None:
        """Ensure the parent directory exists."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _write_entry(self, entry: EvalLogEntry) -> None:
        """Write a log entry to the file."""
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(entry.to_jsonl() + "\n")

    def _now(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.now().isoformat()

    def log_event(
        self,
        event_type: str,
        phase: str | None = None,
        iteration: int | None = None,
        **data: Any,
    ) -> None:
        """Log a generic event.

        Args:
            event_type: Type of event.
            phase: Current phase name.
            iteration: Current iteration number.
            **data: Additional event data.
        """
        entry = EvalLogEntry(
            timestamp=self._now(),
            event_type=event_type,
            spec_id=self.spec_id,
            phase=phase,
            iteration=iteration,
            data=data,
        )
        self._write_entry(entry)

    def log_eval_start(self, config: dict[str, Any] | None = None) -> None:
        """Log evaluation start."""
        self.log_event("eval_start", config=config or {})

    def log_eval_end(self, success: bool, summary: dict[str, Any] | None = None) -> None:
        """Log evaluation end."""
        self.log_event("eval_end", success=success, summary=summary or {})

    def log_phase_start(self, phase: str) -> None:
        """Log phase start."""
        self.log_event("phase_start", phase=phase)

    def log_phase_end(
        self,
        phase: str,
        success: bool,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        """Log phase end with metrics."""
        self.log_event(
            "phase_end",
            phase=phase,
            success=success,
            metrics=metrics or {},
        )

    def log_iteration(
        self,
        phase: str,
        iteration: int,
        gaps_open: int = 0,
        content_hash: str = "",
        duration_ms: float = 0.0,
        convergence_ratio: float = 0.0,
    ) -> None:
        """Log an iteration within a phase."""
        self.log_event(
            "iteration",
            phase=phase,
            iteration=iteration,
            gaps_open=gaps_open,
            content_hash=content_hash,
            duration_ms=duration_ms,
            convergence_ratio=convergence_ratio,
        )

    def log_loop_warning(
        self,
        phase: str,
        loop_status: str,
        iteration: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log a loop detection warning."""
        self.log_event(
            "loop_warning",
            phase=phase,
            iteration=iteration,
            loop_status=loop_status,
            details=details or {},
        )

    def log_error(
        self,
        phase: str | None,
        error_type: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log an error."""
        self.log_event(
            "error",
            phase=phase,
            error_type=error_type,
            message=message,
            details=details or {},
        )

    def log_metrics(
        self,
        phase: str,
        metrics: dict[str, Any],
    ) -> None:
        """Log metrics for a phase."""
        self.log_event("metrics", phase=phase, **metrics)

    def set_spec_id(self, spec_id: str) -> None:
        """Update the current spec ID."""
        self.spec_id = spec_id

    def read_entries(self) -> list[EvalLogEntry]:
        """Read all log entries from the file.

        Returns:
            List of EvalLogEntry objects.
        """
        if not self.log_path.exists():
            return []

        entries: list[EvalLogEntry] = []
        with self.log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = EvalLogEntry(
                        timestamp=data.get("timestamp", ""),
                        event_type=data.get("event_type", ""),
                        spec_id=data.get("spec_id", ""),
                        phase=data.get("phase"),
                        iteration=data.get("iteration"),
                        data={
                            k: v
                            for k, v in data.items()
                            if k not in {"timestamp", "event_type", "spec_id", "phase", "iteration"}
                        },
                    )
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
        return entries

    def get_phase_entries(self, phase: str) -> list[EvalLogEntry]:
        """Get all entries for a specific phase.

        Args:
            phase: Phase name to filter by.

        Returns:
            List of EvalLogEntry objects for the phase.
        """
        return [entry for entry in self.read_entries() if entry.phase == phase]

    def get_iteration_count(self, phase: str) -> int:
        """Get the number of iterations logged for a phase.

        Args:
            phase: Phase name.

        Returns:
            Number of iteration entries for the phase.
        """
        return len(
            [
                entry
                for entry in self.read_entries()
                if entry.phase == phase and entry.event_type == "iteration"
            ]
        )
