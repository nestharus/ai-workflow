"""Workspace state management with schema versioning and migration.

Provides:
- Phase: Enum of v2.0 workflow phases
- PhaseStatus: Enum of phase execution statuses
- PhaseState: State of a single phase
- WorkspaceState: Full workspace state with migration support
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CURRENT_SCHEMA_VERSION = "2.0"

_V2_PHASES = ["cleaning", "discovery", "review", "finalization"]


class Phase(str, Enum):
    """V2.0 workflow phases."""

    CLEANING = "cleaning"
    DISCOVERY = "discovery"
    REVIEW = "review"
    FINALIZATION = "finalization"


class PhaseStatus(str, Enum):
    """Status of a workflow phase."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PhaseState:
    """State of a single workflow phase.

    Attributes:
        phase: Phase name
        status: Current status
        started_at: ISO8601 start timestamp
        completed_at: ISO8601 completion timestamp
        error: Error message if failed
        outputs: Phase output artifacts
        issues: Issues encountered during phase
    """

    phase: str
    status: PhaseStatus = PhaseStatus.NOT_STARTED
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "phase": self.phase,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "outputs": self.outputs,
            "issues": self.issues,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PhaseState:
        """Deserialize from dictionary."""
        return cls(
            phase=data.get("phase", ""),
            status=PhaseStatus(data.get("status", "not_started")),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
            outputs=data.get("outputs", {}),
            issues=data.get("issues", []),
        )


def _write_migration_log_entry(log_path: Path, entry: dict[str, Any]) -> None:
    """Append a JSON-line entry to the migration log.

    Args:
        log_path: Path to the migration log file
        entry: Log entry dictionary
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _get_migration_log_path(state_file: Path) -> Path:
    """Derive migration log path from state file path.

    The migration log lives at {workspace_dir}/reports/migration.log
    where workspace_dir is the parent of state.json.
    """
    workspace_dir = state_file.parent
    return workspace_dir / "reports" / "migration.log"


def _is_legacy_schema(data: dict[str, Any]) -> bool:
    """Check if data is from a legacy (pre-v2.0) schema.

    Legacy schemas have no schema_version field, or have schema_version < 2.0.
    """
    version = data.get("schema_version")
    return version is None or version == "1.0"


@dataclass
class WorkspaceState:
    """Full workspace state with schema versioning and migration support.

    Attributes:
        spec_folder: Path to the spec folder
        schema_version: Schema version string
        created_at: ISO8601 creation timestamp
        current_phase: Current workflow phase
        phases: Phase states keyed by phase name
        inputs: Input file paths
        processed: Processed file paths
        ambiguous_inputs: Ambiguous input file paths
        history: Event history
        run_id: Current run identifier
        input_hashes: Input file content hashes
        metrics: Accumulated metrics
        strategies: Strategy execution records
        conflicts: Detected conflicts
        coverage: Coverage data
        outputs: Output artifacts
        errors: Error messages
        warnings: Warning messages
    """

    spec_folder: str = ""
    schema_version: str = _CURRENT_SCHEMA_VERSION
    created_at: str = ""
    current_phase: Phase = Phase.CLEANING
    phases: dict[str, PhaseState] = field(default_factory=dict)
    inputs: list[str] = field(default_factory=list)
    processed: list[str] = field(default_factory=list)
    ambiguous_inputs: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    run_id: str | None = None
    input_hashes: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] | None = None
    strategies: list[Any] = field(default_factory=list)
    conflicts: list[Any] = field(default_factory=list)
    coverage: Any = None
    outputs: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Initialize default phases if empty."""
        if not self.phases:
            self.phases = self._default_phases()
        if not self.created_at:
            self.created_at = datetime.now().isoformat()

    @staticmethod
    def _default_phases() -> dict[str, PhaseState]:
        """Create default v2.0 phase states."""
        return {phase_name: PhaseState(phase=phase_name) for phase_name in _V2_PHASES}

    @staticmethod
    def detect_schema_version(state_file: Path) -> str | None:
        """Detect schema version from a state file.

        Args:
            state_file: Path to the state JSON file

        Returns:
            Schema version string, or None if not detectable
        """
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            return data.get("schema_version")
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceState:
        """Create WorkspaceState from a dictionary, with migration if needed.

        Legacy schemas are migrated to v2.0 by discarding all data except
        spec_folder and creating a fresh v2.0 state.

        Args:
            data: State dictionary

        Returns:
            WorkspaceState instance
        """
        if _is_legacy_schema(data):
            # Migration: discard all data except spec_folder
            return cls(
                spec_folder=data.get("spec_folder", ""),
                schema_version=_CURRENT_SCHEMA_VERSION,
                created_at=datetime.now().isoformat(),
                current_phase=Phase.CLEANING,
                phases=cls._default_phases(),
                inputs=[],
                processed=[],
                ambiguous_inputs=[],
                history=[],
                run_id=None,
                input_hashes={},
                metrics=None,
                strategies=[],
                conflicts=[],
                coverage=None,
                outputs={},
                errors=[],
                warnings=[],
            )

        # V2.0 state: parse directly
        phases: dict[str, PhaseState] = {}
        for phase_name, phase_data in data.get("phases", {}).items():
            if isinstance(phase_data, dict):
                phases[phase_name] = PhaseState.from_dict(phase_data)

        current_phase_str = data.get("current_phase", "cleaning")
        try:
            current_phase = Phase(current_phase_str)
        except ValueError:
            current_phase = Phase.CLEANING

        return cls(
            spec_folder=data.get("spec_folder", ""),
            schema_version=data.get("schema_version", _CURRENT_SCHEMA_VERSION),
            created_at=data.get("created_at", datetime.now().isoformat()),
            current_phase=current_phase,
            phases=phases or cls._default_phases(),
            inputs=data.get("inputs", []),
            processed=data.get("processed", []),
            ambiguous_inputs=data.get("ambiguous_inputs", []),
            history=data.get("history", []),
            run_id=data.get("run_id"),
            input_hashes=data.get("input_hashes", {}),
            metrics=data.get("metrics"),
            strategies=data.get("strategies", []),
            conflicts=data.get("conflicts", []),
            coverage=data.get("coverage"),
            outputs=data.get("outputs", {}),
            errors=data.get("errors", []),
            warnings=data.get("warnings", []),
        )

    @classmethod
    def load(cls, state_file: Path) -> WorkspaceState:
        """Load workspace state from a JSON file with migration support.

        Handles:
        - Missing files: returns fresh v2.0 state
        - Invalid JSON: returns fresh v2.0 state with parse_error log
        - Legacy schemas: migrates to v2.0 with migration log
        - V2.0 schemas: loads directly with migration_skipped log

        Args:
            state_file: Path to the state JSON file

        Returns:
            WorkspaceState instance
        """
        migration_log_path = _get_migration_log_path(state_file)

        # Try to read and parse the file
        try:
            raw_text = state_file.read_text(encoding="utf-8")
        except OSError:
            # File doesn't exist or can't be read
            return cls()

        try:
            data = json.loads(raw_text)
        except (json.JSONDecodeError, ValueError) as exc:
            # Invalid JSON: log parse error and return fresh state
            _write_migration_log_entry(
                migration_log_path,
                {
                    "timestamp": datetime.now().isoformat(),
                    "event_type": "parse_error_ignored",
                    "details": {
                        "error": str(exc),
                        "state_file": str(state_file),
                        "action": "Created fresh v2.0 state due to parse error",
                    },
                },
            )
            return cls(spec_folder="")

        if not isinstance(data, dict):
            return cls()

        # Detect schema version
        detected_version = data.get("schema_version")

        if _is_legacy_schema(data):
            # Legacy schema: migrate
            _write_migration_log_entry(
                migration_log_path,
                {
                    "timestamp": datetime.now().isoformat(),
                    "event_type": "schema_detected",
                    "details": {
                        "detected_version": detected_version,
                        "state_file": str(state_file),
                    },
                },
            )
            _write_migration_log_entry(
                migration_log_path,
                {
                    "timestamp": datetime.now().isoformat(),
                    "event_type": "migration_started",
                    "details": {
                        "schema_version_from": detected_version or "legacy",
                        "schema_version_to": _CURRENT_SCHEMA_VERSION,
                    },
                },
            )

            state = cls.from_dict(data)

            _write_migration_log_entry(
                migration_log_path,
                {
                    "timestamp": datetime.now().isoformat(),
                    "event_type": "migration_completed",
                    "details": {
                        "schema_version_from": detected_version or "legacy",
                        "schema_version_to": _CURRENT_SCHEMA_VERSION,
                    },
                },
            )

            return state
        else:
            # V2.0 state: no migration needed
            _write_migration_log_entry(
                migration_log_path,
                {
                    "timestamp": datetime.now().isoformat(),
                    "event_type": "schema_detected",
                    "details": {
                        "detected_version": detected_version,
                        "state_file": str(state_file),
                    },
                },
            )
            _write_migration_log_entry(
                migration_log_path,
                {
                    "timestamp": datetime.now().isoformat(),
                    "event_type": "migration_skipped",
                    "details": {
                        "schema_version": detected_version,
                        "reason": "Already at target schema version",
                    },
                },
            )

            return cls.from_dict(data)

    def to_dict(self) -> dict[str, Any]:
        """Serialize state to dictionary."""
        return {
            "spec_folder": self.spec_folder,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "current_phase": self.current_phase.value,
            "phases": {name: phase.to_dict() for name, phase in self.phases.items()},
            "inputs": self.inputs,
            "processed": self.processed,
            "ambiguous_inputs": self.ambiguous_inputs,
            "history": self.history,
            "run_id": self.run_id,
            "input_hashes": self.input_hashes,
            "metrics": self.metrics,
            "strategies": self.strategies,
            "conflicts": self.conflicts,
            "coverage": self.coverage,
            "outputs": self.outputs,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def save(self, path: Path) -> None:
        """Save state to JSON file.

        Args:
            path: File path to write to
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
