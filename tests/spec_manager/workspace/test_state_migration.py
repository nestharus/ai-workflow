"""Unit tests for workspace state schema migration.

Tests cover:
- Schema version detection from state files
- Migration from legacy schemas (pre-v2.0) to v2.0
- Migration logging to .workspace/reports/migration.log
- Data discarding during legacy migration
- Parse error handling returning fresh v2.0 state
- WorkspaceManager integration with migration logging
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from scripts.spec_manager.spec_manager.workspace.manager import WorkspaceManager
from scripts.spec_manager.spec_manager.workspace.state import (
    Phase,
    PhaseStatus,
    WorkspaceState,
)

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Set up a temporary workspace directory structure.

    Creates the standard .workspace/ structure with reports/ subdirectory.
    """
    workspace_dir = tmp_path / ".workspace"
    workspace_dir.mkdir(parents=True)
    reports_dir = workspace_dir / "reports"
    reports_dir.mkdir()
    return workspace_dir


@pytest.fixture
def temp_spec_folder(tmp_path: Path) -> Path:
    """Set up a temporary spec folder with basic structure.

    Creates a spec folder with patches/ directory to satisfy validation.
    """
    spec_folder = tmp_path / "test_spec"
    spec_folder.mkdir(parents=True)
    patches_dir = spec_folder / "patches"
    patches_dir.mkdir()
    # Create a dummy patch file
    (patches_dir / "p1.md").write_text("# Patch 1\n", encoding="utf-8")
    return spec_folder


@pytest.fixture
def legacy_state_v1() -> dict[str, Any]:
    """Return a v1.0 state dict with old phase names (STAGING, PLANNING, MERGING, VERIFICATION)."""
    return {
        "spec_folder": "/test/spec/folder",
        # Note: no schema_version field - this indicates legacy state
        "created_at": "2025-01-01T10:00:00",
        "current_phase": "STAGING",
        "phases": {
            "STAGING": {
                "phase": "STAGING",
                "status": "completed",
                "started_at": "2025-01-01T10:00:00",
                "completed_at": "2025-01-01T10:05:00",
                "error": None,
                "outputs": {},
                "issues": [],
            },
            "PLANNING": {
                "phase": "PLANNING",
                "status": "not_started",
                "started_at": None,
                "completed_at": None,
                "error": None,
                "outputs": {},
                "issues": [],
            },
            "MERGING": {
                "phase": "MERGING",
                "status": "not_started",
                "started_at": None,
                "completed_at": None,
                "error": None,
                "outputs": {},
                "issues": [],
            },
            "VERIFICATION": {
                "phase": "VERIFICATION",
                "status": "not_started",
                "started_at": None,
                "completed_at": None,
                "error": None,
                "outputs": {},
                "issues": [],
            },
        },
        "inputs": ["/test/input1.md", "/test/input2.md"],
        "processed": ["/test/processed1.md"],
        "ambiguous_inputs": [],
        "history": [
            {"timestamp": "2025-01-01T10:00:00", "event": "phase_started", "phase": "STAGING"}
        ],
    }


@pytest.fixture
def v2_state() -> dict[str, Any]:
    """Return a valid v2.0 state dict."""
    return {
        "spec_folder": "/test/spec/folder",
        "schema_version": "2.0",
        "created_at": "2025-01-15T10:00:00",
        "current_phase": "cleaning",
        "phases": {
            "cleaning": {
                "phase": "cleaning",
                "status": "completed",
                "started_at": "2025-01-15T10:00:00",
                "completed_at": "2025-01-15T10:05:00",
                "error": None,
                "outputs": {},
                "issues": [],
            },
            "discovery": {
                "phase": "discovery",
                "status": "not_started",
                "started_at": None,
                "completed_at": None,
                "error": None,
                "outputs": {},
                "issues": [],
            },
            "review": {
                "phase": "review",
                "status": "not_started",
                "started_at": None,
                "completed_at": None,
                "error": None,
                "outputs": {},
                "issues": [],
            },
            "finalization": {
                "phase": "finalization",
                "status": "not_started",
                "started_at": None,
                "completed_at": None,
                "error": None,
                "outputs": {},
                "issues": [],
            },
        },
        "inputs": ["/test/input1.md"],
        "processed": [],
        "ambiguous_inputs": [],
        "history": [],
        "run_id": None,
        "input_hashes": {},
        "metrics": None,
        "strategies": [],
        "conflicts": [],
        "coverage": None,
        "outputs": {},
        "errors": [],
        "warnings": [],
    }


# =============================================================================
# SCHEMA VERSION DETECTION TESTS
# =============================================================================


class TestDetectSchemaVersion:
    """Tests for WorkspaceState.detect_schema_version static method."""

    def test_detect_schema_version_v2(self, temp_workspace: Path, v2_state: dict[str, Any]) -> None:
        """detect_schema_version returns '2.0' for v2.0 state files."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(v2_state), encoding="utf-8")

        result = WorkspaceState.detect_schema_version(state_file)
        assert result == "2.0"

    def test_detect_schema_version_legacy(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """detect_schema_version returns None for legacy state files without schema_version."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        result = WorkspaceState.detect_schema_version(state_file)
        assert result is None

    def test_detect_schema_version_missing_file(self, temp_workspace: Path) -> None:
        """detect_schema_version returns None for non-existent file."""
        state_file = temp_workspace / "nonexistent.json"

        result = WorkspaceState.detect_schema_version(state_file)
        assert result is None

    def test_detect_schema_version_invalid_json(self, temp_workspace: Path) -> None:
        """detect_schema_version returns None for invalid JSON file."""
        state_file = temp_workspace / "state.json"
        state_file.write_text("{ invalid json }", encoding="utf-8")

        result = WorkspaceState.detect_schema_version(state_file)
        assert result is None

    def test_detect_schema_version_explicit_v1(self, temp_workspace: Path) -> None:
        """detect_schema_version returns '1.0' when explicitly set."""
        state_file = temp_workspace / "state.json"
        state_data = {"spec_folder": "/test", "schema_version": "1.0"}
        state_file.write_text(json.dumps(state_data), encoding="utf-8")

        result = WorkspaceState.detect_schema_version(state_file)
        assert result == "1.0"


# =============================================================================
# MIGRATION FROM LEGACY TO V2 TESTS
# =============================================================================


class TestMigrationFromLegacyToV2:
    """Tests for migration from legacy schema to v2.0."""

    def test_migration_from_legacy_to_v2(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """Loading a legacy state file results in a v2.0 state."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        state = WorkspaceState.load(state_file)

        assert state.schema_version == "2.0"

    def test_migration_resets_to_cleaning_phase(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """Migrated state resets current_phase to CLEANING."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        state = WorkspaceState.load(state_file)

        assert state.current_phase == Phase.CLEANING

    def test_migration_uses_v2_phase_names(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """Migrated state uses new v2.0 phase names."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        state = WorkspaceState.load(state_file)

        # Check that v2.0 phase names are used
        assert "cleaning" in state.phases
        assert "discovery" in state.phases
        assert "review" in state.phases
        assert "finalization" in state.phases

        # Check old phase names are NOT present
        assert "STAGING" not in state.phases
        assert "PLANNING" not in state.phases
        assert "MERGING" not in state.phases
        assert "VERIFICATION" not in state.phases

    def test_migration_preserves_spec_folder(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """Migration preserves the spec_folder value."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        state = WorkspaceState.load(state_file)

        assert state.spec_folder == legacy_state_v1["spec_folder"]


# =============================================================================
# MIGRATION LOG TESTS
# =============================================================================


class TestMigrationLogCreation:
    """Tests for migration log file creation."""

    def test_migration_log_created(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """Loading a legacy state creates migration.log in reports directory."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        WorkspaceState.load(state_file)

        migration_log = temp_workspace / "reports" / "migration.log"
        assert migration_log.exists()

    def test_migration_log_contains_schema_detected(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """Migration log contains schema_detected event."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        WorkspaceState.load(state_file)

        migration_log = temp_workspace / "reports" / "migration.log"
        entries = [json.loads(line) for line in migration_log.read_text().splitlines()]

        event_types = [e["event_type"] for e in entries]
        assert "schema_detected" in event_types

    def test_migration_log_contains_migration_started(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """Migration log contains migration_started event for legacy schemas."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        WorkspaceState.load(state_file)

        migration_log = temp_workspace / "reports" / "migration.log"
        entries = [json.loads(line) for line in migration_log.read_text().splitlines()]

        event_types = [e["event_type"] for e in entries]
        assert "migration_started" in event_types

    def test_migration_log_contains_migration_completed(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """Migration log contains migration_completed event for legacy schemas."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        WorkspaceState.load(state_file)

        migration_log = temp_workspace / "reports" / "migration.log"
        entries = [json.loads(line) for line in migration_log.read_text().splitlines()]

        event_types = [e["event_type"] for e in entries]
        assert "migration_completed" in event_types


class TestMigrationLogStructure:
    """Tests for migration log entry structure."""

    def test_log_entry_has_timestamp(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """Each log entry has a timestamp field."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        WorkspaceState.load(state_file)

        migration_log = temp_workspace / "reports" / "migration.log"
        entries = [json.loads(line) for line in migration_log.read_text().splitlines()]

        for entry in entries:
            assert "timestamp" in entry

    def test_log_entry_timestamp_is_valid_iso(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """Log entry timestamps are valid ISO format."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        WorkspaceState.load(state_file)

        migration_log = temp_workspace / "reports" / "migration.log"
        entries = [json.loads(line) for line in migration_log.read_text().splitlines()]

        for entry in entries:
            # This will raise ValueError if not valid ISO format
            datetime.fromisoformat(entry["timestamp"])

    def test_log_entry_has_event_type(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """Each log entry has an event_type field."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        WorkspaceState.load(state_file)

        migration_log = temp_workspace / "reports" / "migration.log"
        entries = [json.loads(line) for line in migration_log.read_text().splitlines()]

        for entry in entries:
            assert "event_type" in entry
            assert entry["event_type"] in [
                "schema_detected",
                "migration_started",
                "migration_completed",
                "migration_skipped",
                "migration_details",
            ]

    def test_log_entry_has_details(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """Each log entry has a details field."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        WorkspaceState.load(state_file)

        migration_log = temp_workspace / "reports" / "migration.log"
        entries = [json.loads(line) for line in migration_log.read_text().splitlines()]

        for entry in entries:
            assert "details" in entry

    def test_migration_events_have_version_info(
        self, temp_workspace: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """Migration started/completed events contain version information."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        WorkspaceState.load(state_file)

        migration_log = temp_workspace / "reports" / "migration.log"
        entries = [json.loads(line) for line in migration_log.read_text().splitlines()]

        migration_events = [
            e for e in entries if e["event_type"] in ("migration_started", "migration_completed")
        ]

        for event in migration_events:
            assert "schema_version_from" in event["details"]
            assert "schema_version_to" in event["details"]
            assert event["details"]["schema_version_to"] == "2.0"


# =============================================================================
# NO MIGRATION FOR V2 STATE TESTS
# =============================================================================


class TestNoMigrationForV2State:
    """Tests for v2.0 state files that don't need migration."""

    def test_no_migration_for_v2_state(
        self, temp_workspace: Path, v2_state: dict[str, Any]
    ) -> None:
        """Loading a v2.0 state file does not trigger migration."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(v2_state), encoding="utf-8")

        WorkspaceState.load(state_file)

        migration_log = temp_workspace / "reports" / "migration.log"
        entries = [json.loads(line) for line in migration_log.read_text().splitlines()]

        event_types = [e["event_type"] for e in entries]
        assert "migration_skipped" in event_types
        assert "migration_started" not in event_types
        assert "migration_completed" not in event_types

    def test_v2_state_preserves_phase_status(
        self, temp_workspace: Path, v2_state: dict[str, Any]
    ) -> None:
        """Loading a v2.0 state preserves phase status values."""
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(v2_state), encoding="utf-8")

        state = WorkspaceState.load(state_file)

        assert state.phases["cleaning"].status == PhaseStatus.COMPLETED
        assert state.phases["discovery"].status == PhaseStatus.NOT_STARTED


# =============================================================================
# DATA DISCARDING DURING MIGRATION TESTS
# =============================================================================


class TestFromDictDiscardsDataDuringMigration:
    """Tests for data discarding during migration via from_dict."""

    def test_discards_inputs(self, legacy_state_v1: dict[str, Any]) -> None:
        """Migration discards inputs list."""
        state = WorkspaceState.from_dict(legacy_state_v1)

        assert state.inputs == []
        assert state.inputs != legacy_state_v1["inputs"]

    def test_discards_processed(self, legacy_state_v1: dict[str, Any]) -> None:
        """Migration discards processed list."""
        state = WorkspaceState.from_dict(legacy_state_v1)

        assert state.processed == []
        assert state.processed != legacy_state_v1["processed"]

    def test_discards_ambiguous_inputs(self, legacy_state_v1: dict[str, Any]) -> None:
        """Migration discards ambiguous_inputs list."""
        state = WorkspaceState.from_dict(legacy_state_v1)

        assert state.ambiguous_inputs == []

    def test_discards_history(self, legacy_state_v1: dict[str, Any]) -> None:
        """Migration discards history list."""
        state = WorkspaceState.from_dict(legacy_state_v1)

        assert state.history == []
        assert state.history != legacy_state_v1["history"]

    def test_preserves_spec_folder(self, legacy_state_v1: dict[str, Any]) -> None:
        """Migration preserves spec_folder (only required field)."""
        state = WorkspaceState.from_dict(legacy_state_v1)

        assert state.spec_folder == legacy_state_v1["spec_folder"]

    def test_creates_new_created_at(self, legacy_state_v1: dict[str, Any]) -> None:
        """Migration creates a new created_at timestamp."""
        state = WorkspaceState.from_dict(legacy_state_v1)

        assert state.created_at != legacy_state_v1["created_at"]
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(state.created_at)

    def test_initializes_v2_fields(self, legacy_state_v1: dict[str, Any]) -> None:
        """Migration initializes all v2.0 fields with defaults."""
        state = WorkspaceState.from_dict(legacy_state_v1)

        assert state.run_id is None
        assert state.metrics is None
        assert state.strategies == []
        assert state.conflicts == []
        assert state.coverage is None
        assert state.outputs == {}
        assert state.errors == []
        assert state.warnings == []


# =============================================================================
# WORKSPACE MANAGER INTEGRATION TESTS
# =============================================================================


class TestWorkspaceManagerMigrationIntegration:
    """Tests for WorkspaceManager integration with migration logging."""

    def test_manager_loads_legacy_state_as_v2(
        self, temp_spec_folder: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """WorkspaceManager loads legacy state and migrates to v2.0."""
        # Set up workspace with legacy state
        workspace_dir = temp_spec_folder / ".workspace"
        workspace_dir.mkdir()
        reports_dir = workspace_dir / "reports"
        reports_dir.mkdir()

        # Update legacy state to use correct spec_folder
        legacy_state_v1["spec_folder"] = str(temp_spec_folder)

        state_file = workspace_dir / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        manager = WorkspaceManager(spec_folder=temp_spec_folder)

        assert manager.state.schema_version == "2.0"

    def test_manager_migration_log_exists(
        self, temp_spec_folder: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """WorkspaceManager creates migration log when loading legacy state."""
        # Set up workspace with legacy state
        workspace_dir = temp_spec_folder / ".workspace"
        workspace_dir.mkdir()
        reports_dir = workspace_dir / "reports"
        reports_dir.mkdir()

        # Update legacy state to use correct spec_folder
        legacy_state_v1["spec_folder"] = str(temp_spec_folder)

        state_file = workspace_dir / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        manager = WorkspaceManager(spec_folder=temp_spec_folder)

        migration_log = manager.get_migration_log_path()
        assert migration_log.exists()

    def test_manager_read_migration_log(
        self, temp_spec_folder: Path, legacy_state_v1: dict[str, Any]
    ) -> None:
        """WorkspaceManager.read_migration_log() returns migration events."""
        # Set up workspace with legacy state
        workspace_dir = temp_spec_folder / ".workspace"
        workspace_dir.mkdir()
        reports_dir = workspace_dir / "reports"
        reports_dir.mkdir()

        # Update legacy state to use correct spec_folder
        legacy_state_v1["spec_folder"] = str(temp_spec_folder)

        state_file = workspace_dir / "state.json"
        state_file.write_text(json.dumps(legacy_state_v1), encoding="utf-8")

        manager = WorkspaceManager(spec_folder=temp_spec_folder)
        entries = manager.read_migration_log()

        assert isinstance(entries, list)
        assert len(entries) > 0

        event_types = [e["event_type"] for e in entries]
        assert "schema_detected" in event_types
        assert "migration_started" in event_types
        assert "migration_completed" in event_types

    def test_manager_read_migration_log_empty_when_no_log(self, temp_spec_folder: Path) -> None:
        """WorkspaceManager.read_migration_log() returns empty list when no log exists."""
        manager = WorkspaceManager(spec_folder=temp_spec_folder)

        # Initialize to create workspace (but no migration occurs for new state)
        manager.initialize()

        # Delete migration log if it was created
        migration_log = manager.get_migration_log_path()
        if migration_log.exists():
            migration_log.unlink()

        entries = manager.read_migration_log()
        assert entries == []

    def test_manager_get_migration_log_path(self, temp_spec_folder: Path) -> None:
        """WorkspaceManager.get_migration_log_path() returns correct path."""
        manager = WorkspaceManager(spec_folder=temp_spec_folder)

        expected_path = temp_spec_folder / ".workspace" / "reports" / "migration.log"
        assert manager.get_migration_log_path() == expected_path


# =============================================================================
# EDGE CASE TESTS
# =============================================================================


class TestMigrationEdgeCases:
    """Tests for edge cases in migration handling."""

    def test_migration_with_empty_history(self, temp_workspace: Path) -> None:
        """Migration handles empty history list."""
        legacy_state = {
            "spec_folder": "/test",
            "current_phase": "STAGING",
            "phases": {},
            "inputs": [],
            "processed": [],
            "ambiguous_inputs": [],
            "history": [],
        }
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state), encoding="utf-8")

        state = WorkspaceState.load(state_file)

        assert state.schema_version == "2.0"
        assert state.history == []

    def test_migration_with_partial_v2_fields(self, temp_workspace: Path) -> None:
        """Migration discards legacy state even with some v2.0 fields present."""
        legacy_state = {
            "spec_folder": "/test",
            # No schema_version - treated as legacy
            "current_phase": "STAGING",
            "phases": {},
            "inputs": [],
            "processed": [],
            "ambiguous_inputs": [],
            "history": [],
            # Some v2.0 fields present
            "run_id": "test-run-123",
            "input_hashes": {"file.md": "abc123"},
        }
        state_file = temp_workspace / "state.json"
        state_file.write_text(json.dumps(legacy_state), encoding="utf-8")

        state = WorkspaceState.load(state_file)

        assert state.schema_version == "2.0"
        # Partial v2.0 fields should also be discarded during legacy migration
        assert state.run_id is None
        assert state.input_hashes == {}

    def test_migration_log_malformed_line_handling(self, temp_spec_folder: Path) -> None:
        """WorkspaceManager.read_migration_log() handles malformed JSON lines gracefully."""
        # Set up workspace
        workspace_dir = temp_spec_folder / ".workspace"
        workspace_dir.mkdir()
        reports_dir = workspace_dir / "reports"
        reports_dir.mkdir()

        # Write a migration log with mixed valid/invalid lines
        migration_log = reports_dir / "migration.log"
        migration_log.write_text(
            '{"event_type": "test", "timestamp": "2025-01-01T10:00:00", "details": {}}\n'
            "{ invalid json line }\n"
            '{"event_type": "test2", "timestamp": "2025-01-01T10:01:00", "details": {}}\n',
            encoding="utf-8",
        )

        manager = WorkspaceManager(spec_folder=temp_spec_folder)
        entries = manager.read_migration_log()

        # Should skip malformed line and return valid entries
        assert len(entries) == 2
        assert entries[0]["event_type"] == "test"
        assert entries[1]["event_type"] == "test2"

    def test_load_invalid_json_returns_fresh_v2_state(self, temp_workspace: Path) -> None:
        """Loading invalid JSON returns a fresh v2.0 state."""
        state_file = temp_workspace / "state.json"
        state_file.write_text("{ invalid json }", encoding="utf-8")

        state = WorkspaceState.load(state_file)

        assert state.schema_version == "2.0"
        assert state.current_phase == Phase.CLEANING
        assert state.inputs == []
        assert state.processed == []
        assert state.history == []

    def test_load_invalid_json_creates_parse_error_log(self, temp_workspace: Path) -> None:
        """Loading invalid JSON creates a parse_error_ignored migration event."""
        state_file = temp_workspace / "state.json"
        state_file.write_text("{ invalid json }", encoding="utf-8")

        WorkspaceState.load(state_file)

        migration_log = temp_workspace / "reports" / "migration.log"
        entries = [json.loads(line) for line in migration_log.read_text().splitlines()]

        event_types = [e["event_type"] for e in entries]
        assert "parse_error_ignored" in event_types

        parse_error_entry = next(e for e in entries if e["event_type"] == "parse_error_ignored")
        assert "error" in parse_error_entry["details"]
        assert "state_file" in parse_error_entry["details"]
        assert "action" in parse_error_entry["details"]

    def test_load_os_error_returns_fresh_v2_state(self, temp_workspace: Path) -> None:
        """Loading with OS error returns a fresh v2.0 state."""
        state_file = temp_workspace / "state.json"
        # Create a directory with the same name to cause read issues
        state_dir = temp_workspace / "state.json"
        state_dir.mkdir()

        # This will cause an OSError when trying to read as file
        state = WorkspaceState.load(state_file)

        assert state.schema_version == "2.0"
        assert state.current_phase == Phase.CLEANING
