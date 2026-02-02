"""Tests for spec_manager.spec_manager.decomposition.cli module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.spec_manager.spec_manager.decomposition.entity_index import save_entity_index
from scripts.spec_manager.spec_manager.decomposition.workspace import init_workspace, load_state, save_state


@pytest.fixture
def sample_spec(tmp_path: Path) -> Path:
    """Create a sample spec file."""
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(
        """# Test Specification

## AuthService

AuthService validates credentials.
AuthService connects to UserStore.

## UserStore

UserStore manages user data.
"""
    )
    return spec_file


@pytest.fixture
def initialized_workspace(tmp_path: Path, sample_spec: Path) -> Path:
    """Create an initialized workspace."""
    workspace = tmp_path / "workspace"
    init_workspace(workspace, sample_spec)
    return workspace


class TestCmdInit:
    """Tests for cmd_init function."""

    def test_creates_staging_discovery_directory(self, tmp_path: Path, sample_spec: Path):
        """Test that init creates staging/discovery subdirectory."""
        workspace = tmp_path / "workspace"
        init_workspace(workspace, sample_spec)

        assert (workspace / "staging" / "discovery").exists()
        staged_files = list((workspace / "staging" / "discovery").rglob("*_staged.md"))
        assert len(staged_files) == 1


class TestCreateInvestigationStaging:
    """Tests for investigation staging functionality."""

    def test_creates_investigation_directory(self, initialized_workspace: Path):
        """Test that create_investigation_staging creates entity directory."""
        from scripts.spec_manager.spec_manager.decomposition.workspace import create_investigation_staging

        investigation_dir = create_investigation_staging(initialized_workspace, "AuthService")

        assert investigation_dir.exists()
        assert investigation_dir.is_dir()
        assert investigation_dir.name == "AuthService"

    def test_creates_investigation_files(self, initialized_workspace: Path):
        """Test that investigation files are created for each original file."""
        from scripts.spec_manager.spec_manager.decomposition.workspace import create_investigation_staging

        investigation_dir = create_investigation_staging(initialized_workspace, "AuthService")

        investigation_files = list(investigation_dir.rglob("*_investigation.md"))
        assert len(investigation_files) >= 1


class TestResolveOriginalCopy:
    """Tests for resolve_original_copy function."""

    def test_resolves_by_source_path(self, initialized_workspace: Path, sample_spec: Path):
        """Test resolving by original source path."""
        from scripts.spec_manager.spec_manager.decomposition.workspace import resolve_original_copy

        result = resolve_original_copy(initialized_workspace, str(sample_spec))

        assert result is not None
        assert result.exists()
        assert "_original.md" in result.name

    def test_returns_none_for_unknown_file(self, initialized_workspace: Path):
        """Test returns None for unknown source file."""
        from scripts.spec_manager.spec_manager.decomposition.workspace import resolve_original_copy

        result = resolve_original_copy(initialized_workspace, "/nonexistent/file.md")

        assert result is None


class TestResolveDiscoveryStaging:
    """Tests for resolve_discovery_staging function."""

    def test_resolves_by_source_path(self, initialized_workspace: Path, sample_spec: Path):
        """Test resolving by original source path."""
        from scripts.spec_manager.spec_manager.decomposition.workspace import resolve_discovery_staging

        result = resolve_discovery_staging(initialized_workspace, str(sample_spec))

        assert result is not None
        assert result.exists()
        assert "_staged.md" in result.name

    def test_returns_none_for_unknown_file(self, initialized_workspace: Path):
        """Test returns None for unknown source file."""
        from scripts.spec_manager.spec_manager.decomposition.workspace import resolve_discovery_staging

        result = resolve_discovery_staging(initialized_workspace, "/nonexistent/file.md")

        assert result is None


class TestProcessInvestigationRequiresEntity:
    """Tests that process-investigation requires an existing entity."""

    def test_fails_for_nonexistent_entity(self, initialized_workspace: Path):
        """Test that process-investigation fails for non-existent entity."""
        import argparse

        from scripts.spec_manager.spec_manager.decomposition.workspace import create_investigation_staging
        from scripts.spec_manager.spec_manager.decomposition.cli import cmd_process_investigation

        # Create investigation staging for a fake entity
        entity_name = "FakeEntity"
        investigation_dir = create_investigation_staging(initialized_workspace, entity_name)

        # Create a fake findings file with proper structure
        findings = {
            "entity": entity_name,
            "findings": [{"lines": [1, 2]}],
        }
        findings_file = initialized_workspace / "findings.json"
        findings_file.write_text(json.dumps(findings))

        # Create map file
        safe_name = entity_name.replace(" ", "_").replace("/", "_")
        map_file = investigation_dir / f"{safe_name}_combined_map.json"
        line_map = {
            "line_map": {
                "1": {"file": "test.md", "line": 1, "text": "test"},
                "2": {"file": "test.md", "line": 2, "text": "test2"},
            }
        }
        map_file.write_text(json.dumps(line_map))

        # Update state
        state = load_state(initialized_workspace)
        state.setdefault("investigation_staging", {})[safe_name] = {
            "map_file": str(map_file),
        }
        save_state(initialized_workspace, state)

        # Entity index is empty so entity won't be found
        from scripts.spec_manager.spec_manager.decomposition.entity_index import load_entity_index

        entity_index = load_entity_index(initialized_workspace)
        assert entity_name not in [info.get("name") for info in entity_index.values()]

        # Call cmd_process_investigation and assert it returns error
        args = argparse.Namespace(
            workspace=initialized_workspace,
            findings=findings_file,
            redact_discovery=False,
        )
        result = cmd_process_investigation(args)

        assert result == 1, (
            "process-investigation should return error code 1 for non-existent entity"
        )


class TestLineRedaction:
    """Tests for line redaction in extract operations."""

    def test_remove_lines_marks_as_extracted(self, initialized_workspace: Path, sample_spec: Path):
        """Test that remove_lines marks lines as extracted."""
        from scripts.spec_manager.spec_manager.decomposition.staging import get_remaining_lines, remove_lines
        from scripts.spec_manager.spec_manager.decomposition.workspace import resolve_discovery_staging

        staging_file = resolve_discovery_staging(initialized_workspace, str(sample_spec))
        assert staging_file is not None

        initial_remaining = get_remaining_lines(staging_file)
        initial_count = len(initial_remaining)

        # Remove first line
        remove_lines(staging_file, [1], note="test")

        final_remaining = get_remaining_lines(staging_file)
        assert len(final_remaining) < initial_count

        # Check the line is marked as extracted in the file
        content = staging_file.read_text()
        assert "<!-- EXTRACTED: 1 (test) -->" in content
