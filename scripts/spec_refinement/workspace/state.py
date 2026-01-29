"""Workspace state management for spec refinement."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class PhaseStatus(Enum):
    """Status of a workflow phase."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Phase(Enum):
    """Spec refinement workflow phases."""

    INIT = "init"
    SUMMARIZATION = "summarization"
    LIBRARY_SYNTHESIS = "library_synthesis"
    EVIDENCE_EXPANSION = "evidence_expansion"
    SPEC_BUILDING = "spec_building"
    SUBLIBRARY_DETECTION = "sublibrary_detection"
    ARCHITECTURE = "architecture"
    INTERFACES = "interfaces"
    TASKS = "tasks"
    IMPLEMENTATION = "implementation"
    AUDIT = "audit"


@dataclass
class PhaseResult:
    """Result of a phase execution."""

    phase: Phase
    status: PhaseStatus
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    issues: list[dict[str, Any]] = field(default_factory=list)
    gap_audit_iterations: int = 0
    gap_audit_converged: bool = False
    open_gaps_count: int = 0


@dataclass
class WorkspaceState:
    """Persistent state for spec refinement workspaces."""

    run_id: str
    input_folder: str
    schema_version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    current_phase: Phase = Phase.INIT
    phases: dict[str, PhaseResult] = field(default_factory=dict)
    file_manifest: dict[str, str] = field(default_factory=dict)
    section_manifest: dict[str, list[str]] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def detect_schema_version(state_path: Path) -> str | None:
        """Detect the schema version of a state file without fully loading it."""
        if not state_path.exists():
            return None
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            return data.get("schema_version")
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _log_migration_event(
        workspace_dir: Path,
        event_type: str,
        details: dict[str, Any],
    ) -> None:
        """Log a migration event to the migration log file."""
        try:
            audits_dir = workspace_dir / "audits"
            audits_dir.mkdir(parents=True, exist_ok=True)
            migration_log = audits_dir / "migration.log"

            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "event_type": event_type,
                "details": details,
            }

            with migration_log.open("a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except OSError as e:
            print(f"Warning: Failed to write migration log: {e}", file=sys.stderr)

    def __post_init__(self) -> None:
        """Initialize phase results for all phases not explicitly set."""
        for phase in Phase:
            if phase.value not in self.phases:
                self.phases[phase.value] = PhaseResult(phase=phase, status=PhaseStatus.NOT_STARTED)

    def start_phase(self, phase: Phase) -> None:
        """Mark a phase as started."""
        self.current_phase = phase
        result = self.phases[phase.value]
        result.status = PhaseStatus.IN_PROGRESS
        result.started_at = datetime.now().isoformat()
        self._log_event("phase_started", {"phase": phase.value})

    def complete_phase(self, phase: Phase, outputs: dict[str, Any] | None = None) -> None:
        """Mark a phase as completed."""
        result = self.phases[phase.value]
        result.status = PhaseStatus.COMPLETED
        result.completed_at = datetime.now().isoformat()
        if outputs:
            result.outputs = outputs
        self._log_event("phase_completed", {"phase": phase.value})

    def fail_phase(self, phase: Phase, error: str) -> None:
        """Mark a phase as failed."""
        result = self.phases[phase.value]
        result.status = PhaseStatus.FAILED
        result.completed_at = datetime.now().isoformat()
        result.error = error
        self._log_event("phase_failed", {"phase": phase.value, "error": error})

    def get_next_phase(self) -> Phase | None:
        """Get the next phase to execute."""
        phase_order = [
            Phase.INIT,
            Phase.SUMMARIZATION,
            Phase.LIBRARY_SYNTHESIS,
            Phase.EVIDENCE_EXPANSION,
            Phase.SPEC_BUILDING,
            Phase.SUBLIBRARY_DETECTION,
            Phase.ARCHITECTURE,
            Phase.INTERFACES,
            Phase.TASKS,
            Phase.IMPLEMENTATION,
            Phase.AUDIT,
        ]

        for phase in phase_order:
            status = self.phases[phase.value].status
            if status == PhaseStatus.NOT_STARTED:
                return phase
            if status in {PhaseStatus.IN_PROGRESS, PhaseStatus.FAILED}:
                return phase

        return None

    def is_complete(self) -> bool:
        """Check if all phases are completed."""
        return all(self.phases[phase.value].status == PhaseStatus.COMPLETED for phase in Phase)

    def _log_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Log an event to history."""
        self.history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "event": event_type,
                **data,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary for JSON serialization."""
        return {
            "run_id": self.run_id,
            "input_folder": self.input_folder,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "current_phase": self.current_phase.value,
            "phases": {
                name: {
                    "phase": result.phase.value,
                    "status": result.status.value,
                    "started_at": result.started_at,
                    "completed_at": result.completed_at,
                    "error": result.error,
                    "outputs": result.outputs,
                    "issues": result.issues,
                    "gap_audit_iterations": result.gap_audit_iterations,
                    "gap_audit_converged": result.gap_audit_converged,
                    "open_gaps_count": result.open_gaps_count,
                }
                for name, result in self.phases.items()
            },
            "file_manifest": self.file_manifest,
            "section_manifest": self.section_manifest,
            "history": self.history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], workspace_dir: Path | None = None) -> WorkspaceState:
        """Create state from dictionary with optional migration logging."""
        schema_version = data.get("schema_version", "1.0")

        if schema_version != "1.0":
            migration_timestamp = datetime.now().isoformat()
            if workspace_dir is not None:
                cls._log_migration_event(
                    workspace_dir,
                    "migration_details",
                    {
                        "schema_version_from": schema_version,
                        "schema_version_to": "1.0",
                        "migration_timestamp": migration_timestamp,
                        "phase_reset": True,
                        "data_discarded": [
                            "phases",
                            "file_manifest",
                            "section_manifest",
                            "history",
                        ],
                    },
                )

            return cls(
                run_id=data.get("run_id", workspace_dir.name if workspace_dir else "unknown"),
                input_folder=data.get("input_folder", ""),
                schema_version="1.0",
                created_at=datetime.now().isoformat(),
                current_phase=Phase.INIT,
                file_manifest={},
                section_manifest={},
                history=[],
            )

        raw_phase = data.get("current_phase", Phase.INIT.value)
        try:
            current_phase = Phase(raw_phase)
        except ValueError as e:
            raise ValueError(
                f"Invalid phase value '{raw_phase}'. Valid values are: {[p.value for p in Phase]}"
            ) from e

        state = cls(
            run_id=data["run_id"],
            input_folder=data["input_folder"],
            schema_version=schema_version,
            created_at=data.get("created_at", datetime.now().isoformat()),
            current_phase=current_phase,
            file_manifest=data.get("file_manifest", {}),
            section_manifest=data.get("section_manifest", {}),
            history=data.get("history", []),
        )

        for name, phase_data in data.get("phases", {}).items():
            raw_result_phase = phase_data["phase"]
            try:
                result_phase = Phase(raw_result_phase)
            except ValueError as e:
                raise ValueError(
                    f"Invalid phase value '{raw_result_phase}' in phase '{name}'. "
                    f"Valid values are: {[p.value for p in Phase]}"
                ) from e

            raw_status = phase_data["status"]
            try:
                status = PhaseStatus(raw_status)
            except ValueError as e:
                raise ValueError(
                    f"Invalid status value '{raw_status}' in phase '{name}'. "
                    f"Valid values are: {[s.value for s in PhaseStatus]}"
                ) from e

            state.phases[name] = PhaseResult(
                phase=result_phase,
                status=status,
                started_at=phase_data.get("started_at"),
                completed_at=phase_data.get("completed_at"),
                error=phase_data.get("error"),
                outputs=phase_data.get("outputs", {}),
                issues=phase_data.get("issues", []),
                gap_audit_iterations=phase_data.get("gap_audit_iterations", 0),
                gap_audit_converged=phase_data.get("gap_audit_converged", False),
                open_gaps_count=phase_data.get("open_gaps_count", 0),
            )

        return state

    def save(self, path: Path) -> None:
        """Save state to file."""
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> WorkspaceState:
        """Load state from file with automatic migration and logging."""
        workspace_dir = path.parent

        try:
            detected_version = cls.detect_schema_version(path)
            cls._log_migration_event(
                workspace_dir,
                "schema_detected",
                {
                    "schema_version_detected": detected_version,
                    "state_file": str(path),
                },
            )

            data = json.loads(path.read_text(encoding="utf-8"))

            if detected_version != "1.0":
                cls._log_migration_event(
                    workspace_dir,
                    "migration_started",
                    {
                        "schema_version_from": detected_version,
                        "schema_version_to": "1.0",
                    },
                )
                state = cls.from_dict(data, workspace_dir=workspace_dir)
                cls._log_migration_event(
                    workspace_dir,
                    "migration_completed",
                    {
                        "schema_version_from": detected_version,
                        "schema_version_to": "1.0",
                    },
                )
            else:
                cls._log_migration_event(
                    workspace_dir,
                    "migration_skipped",
                    {
                        "schema_version": detected_version,
                        "reason": "Already at 1.0",
                    },
                )
                state = cls.from_dict(data, workspace_dir=workspace_dir)

            return state
        except (json.JSONDecodeError, OSError) as e:
            run_id = path.parent.name
            cls._log_migration_event(
                workspace_dir,
                "parse_error_ignored",
                {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "state_file": str(path),
                    "action": "Reinitialized to fresh 1.0 state",
                },
            )
            return cls(run_id=run_id, input_folder="", schema_version="1.0")
