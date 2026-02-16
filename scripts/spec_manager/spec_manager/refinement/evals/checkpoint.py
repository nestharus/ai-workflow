"""Checkpoint management for evaluation runs.

Provides state persistence to enable resume of interrupted evaluation runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from spec_manager.refinement.evals.loop_detector import LoopDetector
from spec_manager.refinement.evals.metrics import PhaseMetrics


@dataclass
class PhaseCheckpoint:
    """Checkpoint state for a single phase.

    Attributes:
        phase_name: Name of the phase.
        status: Current status (pending, in_progress, completed, failed).
        iteration: Current iteration number.
        started_at: Timestamp when phase started.
        completed_at: Timestamp when phase completed.
        metrics: Phase metrics if completed.
        loop_detector_state: Serialized loop detector state.
        workspace_hash: Hash of workspace state at checkpoint.
    """

    phase_name: str
    status: str = "pending"
    iteration: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    metrics: dict[str, Any] | None = None
    loop_detector_state: dict[str, Any] | None = None
    workspace_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "phase_name": self.phase_name,
            "status": self.status,
            "iteration": self.iteration,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "metrics": self.metrics,
            "loop_detector_state": self.loop_detector_state,
            "workspace_hash": self.workspace_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhaseCheckpoint:
        """Deserialize from dictionary."""
        return cls(
            phase_name=data.get("phase_name", ""),
            status=data.get("status", "pending"),
            iteration=data.get("iteration", 0),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            metrics=data.get("metrics"),
            loop_detector_state=data.get("loop_detector_state"),
            workspace_hash=data.get("workspace_hash"),
        )


@dataclass
class EvalCheckpoint:
    """Checkpoint state for an entire evaluation run.

    Attributes:
        run_id: Unique identifier for the evaluation run.
        spec_id: ID of the spec being evaluated.
        created_at: Timestamp when checkpoint was created.
        updated_at: Timestamp when checkpoint was last updated.
        current_phase: Name of the current phase.
        phases: Checkpoint state for each phase.
        overall_metrics: Aggregate metrics across all phases.
        config: Configuration used for the run.
    """

    run_id: str
    spec_id: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    current_phase: str | None = None
    phases: dict[str, PhaseCheckpoint] = field(default_factory=dict)
    overall_metrics: dict[str, Any] | None = None
    config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "run_id": self.run_id,
            "spec_id": self.spec_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "current_phase": self.current_phase,
            "phases": {name: phase.to_dict() for name, phase in self.phases.items()},
            "overall_metrics": self.overall_metrics,
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalCheckpoint:
        """Deserialize from dictionary."""
        return cls(
            run_id=data.get("run_id", ""),
            spec_id=data.get("spec_id", ""),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            current_phase=data.get("current_phase"),
            phases={
                name: PhaseCheckpoint.from_dict(phase_data)
                for name, phase_data in data.get("phases", {}).items()
            },
            overall_metrics=data.get("overall_metrics"),
            config=data.get("config", {}),
        )

    def get_phase(self, phase_name: str) -> PhaseCheckpoint:
        """Get or create checkpoint for a phase.

        Args:
            phase_name: Name of the phase.

        Returns:
            PhaseCheckpoint for the phase.
        """
        if phase_name not in self.phases:
            self.phases[phase_name] = PhaseCheckpoint(phase_name=phase_name)
        return self.phases[phase_name]

    def is_phase_completed(self, phase_name: str) -> bool:
        """Check if a phase is completed.

        Args:
            phase_name: Name of the phase.

        Returns:
            True if the phase is completed.
        """
        phase = self.phases.get(phase_name)
        return phase is not None and phase.status == "completed"

    def get_completed_phases(self) -> list[str]:
        """Get list of completed phase names.

        Returns:
            List of completed phase names.
        """
        return [name for name, phase in self.phases.items() if phase.status == "completed"]

    def get_pending_phases(self) -> list[str]:
        """Get list of pending phase names.

        Returns:
            List of pending phase names.
        """
        return [name for name, phase in self.phases.items() if phase.status == "pending"]


class CheckpointCorruptedError(RuntimeError):
    """Raised when a checkpoint file exists but cannot be decoded/validated."""

    def __init__(self, *, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Checkpoint file is corrupted: {path} ({reason})")


class CheckpointManager:
    """Manages checkpoint persistence for evaluation runs.

    Attributes:
        checkpoint_dir: Directory for storing checkpoints.
    """

    def __init__(self, checkpoint_dir: Path) -> None:
        """Initialize the checkpoint manager.

        Args:
            checkpoint_dir: Directory for storing checkpoints.
        """
        self.checkpoint_dir = checkpoint_dir
        self._ensure_dir_exists()

    def _ensure_dir_exists(self) -> None:
        """Ensure the checkpoint directory exists."""
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _checkpoint_path(self, run_id: str) -> Path:
        """Get the path to a checkpoint file.

        Args:
            run_id: Run identifier.

        Returns:
            Path to the checkpoint file.
        """
        return self.checkpoint_dir / f"{run_id}.checkpoint.json"

    def save(self, checkpoint: EvalCheckpoint) -> Path:
        """Save a checkpoint to disk.

        Args:
            checkpoint: Checkpoint to save.

        Returns:
            Path to the saved checkpoint file.
        """
        checkpoint.updated_at = datetime.now().isoformat()
        path = self._checkpoint_path(checkpoint.run_id)
        path.write_text(
            json.dumps(checkpoint.to_dict(), indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, run_id: str) -> EvalCheckpoint | None:
        """Load a checkpoint from disk.

        Args:
            run_id: Run identifier.

        Returns:
            Loaded checkpoint, or None if not found.

        Raises:
            CheckpointCorruptedError: If the checkpoint exists but cannot be decoded.
        """
        path = self._checkpoint_path(run_id)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CheckpointCorruptedError(path=path, reason=f"invalid JSON: {exc}") from exc
        except OSError as exc:
            raise CheckpointCorruptedError(path=path, reason=f"unreadable: {exc}") from exc

        if not isinstance(data, dict):
            raise CheckpointCorruptedError(path=path, reason="top-level payload is not an object")

        try:
            return EvalCheckpoint.from_dict(data)
        except Exception as exc:
            raise CheckpointCorruptedError(
                path=path, reason=f"invalid checkpoint payload: {exc}"
            ) from exc

    def exists(self, run_id: str) -> bool:
        """Check if a checkpoint exists.

        Args:
            run_id: Run identifier.

        Returns:
            True if checkpoint exists.
        """
        return self._checkpoint_path(run_id).exists()

    def delete(self, run_id: str) -> bool:
        """Delete a checkpoint.

        Args:
            run_id: Run identifier.

        Returns:
            True if checkpoint was deleted.
        """
        path = self._checkpoint_path(run_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_checkpoints(self) -> list[str]:
        """List all checkpoint run IDs.

        Returns:
            List of run IDs with existing checkpoints.
        """
        return [
            path.stem.replace(".checkpoint", "")
            for path in self.checkpoint_dir.glob("*.checkpoint.json")
        ]

    def create_checkpoint(
        self,
        run_id: str,
        spec_id: str,
        config: dict[str, Any] | None = None,
    ) -> EvalCheckpoint:
        """Create a new checkpoint.

        Args:
            run_id: Run identifier.
            spec_id: Spec identifier.
            config: Run configuration.

        Returns:
            New checkpoint.
        """
        checkpoint = EvalCheckpoint(
            run_id=run_id,
            spec_id=spec_id,
            config=config or {},
        )
        self.save(checkpoint)
        return checkpoint

    def update_phase_start(
        self,
        checkpoint: EvalCheckpoint,
        phase_name: str,
    ) -> None:
        """Update checkpoint when starting a phase.

        Args:
            checkpoint: Checkpoint to update.
            phase_name: Name of the phase starting.
        """
        phase = checkpoint.get_phase(phase_name)
        phase.status = "in_progress"
        phase.started_at = datetime.now().isoformat()
        checkpoint.current_phase = phase_name
        self.save(checkpoint)

    def update_phase_iteration(
        self,
        checkpoint: EvalCheckpoint,
        phase_name: str,
        iteration: int,
        loop_detector: LoopDetector | None = None,
        workspace_hash: str | None = None,
    ) -> None:
        """Update checkpoint after an iteration.

        Args:
            checkpoint: Checkpoint to update.
            phase_name: Name of the current phase.
            iteration: Current iteration number.
            loop_detector: Loop detector state.
            workspace_hash: Hash of current workspace state.
        """
        phase = checkpoint.get_phase(phase_name)
        phase.iteration = iteration
        if loop_detector is not None:
            phase.loop_detector_state = loop_detector.to_dict()
        if workspace_hash is not None:
            phase.workspace_hash = workspace_hash
        self.save(checkpoint)

    def update_phase_complete(
        self,
        checkpoint: EvalCheckpoint,
        phase_name: str,
        metrics: PhaseMetrics | None = None,
    ) -> None:
        """Update checkpoint when a phase completes.

        Args:
            checkpoint: Checkpoint to update.
            phase_name: Name of the completed phase.
            metrics: Phase metrics.
        """
        phase = checkpoint.get_phase(phase_name)
        phase.status = "completed"
        phase.completed_at = datetime.now().isoformat()
        if metrics is not None:
            phase.metrics = metrics.to_dict()
        self.save(checkpoint)

    def update_phase_failed(
        self,
        checkpoint: EvalCheckpoint,
        phase_name: str,
        error: str,
    ) -> None:
        """Update checkpoint when a phase fails.

        Args:
            checkpoint: Checkpoint to update.
            phase_name: Name of the failed phase.
            error: Error message.
        """
        phase = checkpoint.get_phase(phase_name)
        phase.status = "failed"
        phase.completed_at = datetime.now().isoformat()
        if phase.metrics is None:
            phase.metrics = {}
        phase.metrics["error"] = error
        self.save(checkpoint)

    def restore_loop_detector(
        self,
        checkpoint: EvalCheckpoint,
        phase_name: str,
    ) -> LoopDetector | None:
        """Restore loop detector state from checkpoint.

        Args:
            checkpoint: Checkpoint to restore from.
            phase_name: Phase name.

        Returns:
            Restored LoopDetector, or None if not available.
        """
        phase = checkpoint.phases.get(phase_name)
        if phase is None or phase.loop_detector_state is None:
            return None
        return LoopDetector.from_dict(phase.loop_detector_state)
