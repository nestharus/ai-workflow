"""Tests for spec_decomposition.workspace module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.spec_decomposition.workspace import (
    init_workspace,
    load_state,
    save_state,
)


@pytest.fixture
def sample_spec(tmp_path: Path) -> Path:
    """Create a sample spec file."""
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(
        """# Test Specification

## Component A

Description of component A.

## Component B

Description of component B.
"""
    )
    return spec_file


@pytest.fixture
def spec_directory(tmp_path: Path) -> Path:
    """Create a directory with multiple spec files."""
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    (spec_dir / "spec1.md").write_text("# Spec 1\nContent 1.")
    (spec_dir / "spec2.md").write_text("# Spec 2\nContent 2.")
    (spec_dir / "readme.txt").write_text("Not a markdown file.")
    return spec_dir


class TestInitWorkspace:
    """Tests for init_workspace function."""

    def test_creates_directory_structure(self, tmp_path: Path, sample_spec: Path):
        """Test creates all required directories."""
        workspace = tmp_path / "workspace"
        init_workspace(workspace, sample_spec)

        assert (workspace / "staging").exists()
        assert (workspace / "relation_staging").exists()
        assert (workspace / "entities").exists()
        assert (workspace / "relations").exists()
        assert (workspace / "context").exists()
        assert (workspace / "orphans").exists()
        assert (workspace / "output").exists()

    def test_creates_initial_files(self, tmp_path: Path, sample_spec: Path):
        """Test creates initial json files."""
        workspace = tmp_path / "workspace"
        init_workspace(workspace, sample_spec)

        assert (workspace / "state.json").exists()
        assert (workspace / "id_map.json").exists()
        assert (workspace / "entity_index.json").exists()

    def test_stages_single_file(self, tmp_path: Path, sample_spec: Path):
        """Test stages single spec file."""
        workspace = tmp_path / "workspace"
        init_workspace(workspace, sample_spec)

        staged_files = list((workspace / "staging").glob("*.md"))
        assert len(staged_files) == 1
        assert staged_files[0].name == "spec_staged.md"

    def test_stages_multiple_files_from_directory(self, tmp_path: Path, spec_directory: Path):
        """Test stages all .md files from directory."""
        workspace = tmp_path / "workspace"
        init_workspace(workspace, spec_directory)

        staged_files = list((workspace / "staging").glob("*.md"))
        assert len(staged_files) == 2
        names = {f.name for f in staged_files}
        assert "spec1_staged.md" in names
        assert "spec2_staged.md" in names

    def test_initializes_state_correctly(self, tmp_path: Path, sample_spec: Path):
        """Test state.json is initialized with correct structure."""
        workspace = tmp_path / "workspace"
        init_workspace(workspace, sample_spec)

        state = load_state(workspace)
        assert state["phase"] == "definition_extraction"
        assert state["current_file"] is None
        assert state["current_entity"] is None
        assert state["files_completed"] == []
        assert len(state["files_remaining"]) == 1
        assert state["extracted_entities"] == []
        assert state["extracted_relations"] == []
        assert state["spec_path"] == str(sample_spec)

    def test_cleans_existing_workspace(self, tmp_path: Path, sample_spec: Path):
        """Test existing workspace is cleaned before init."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        (workspace / "old_file.txt").write_text("old content")

        init_workspace(workspace, sample_spec)

        assert not (workspace / "old_file.txt").exists()

    def test_id_map_initialized_empty(self, tmp_path: Path, sample_spec: Path):
        """Test id_map.json is initialized as empty dict."""
        workspace = tmp_path / "workspace"
        init_workspace(workspace, sample_spec)

        id_map_content = json.loads((workspace / "id_map.json").read_text())
        assert id_map_content == {}

    def test_entity_index_initialized_empty(self, tmp_path: Path, sample_spec: Path):
        """Test entity_index.json is initialized as empty dict."""
        workspace = tmp_path / "workspace"
        init_workspace(workspace, sample_spec)

        index_content = json.loads((workspace / "entity_index.json").read_text())
        assert index_content == {}


class TestLoadState:
    """Tests for load_state function."""

    def test_loads_existing_state(self, tmp_path: Path):
        """Test loads state from existing file."""
        state = {
            "phase": "snippet_decomposition",
            "current_file": "spec_staged.md",
            "extracted_entities": ["E-001", "E-002"],
        }
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps(state))

        loaded = load_state(tmp_path)
        assert loaded == state

    def test_returns_empty_dict_when_no_file(self, tmp_path: Path):
        """Test returns empty dict when state.json doesn't exist."""
        loaded = load_state(tmp_path)
        assert loaded == {}


class TestSaveState:
    """Tests for save_state function."""

    def test_saves_state_to_file(self, tmp_path: Path):
        """Test saves state to state.json."""
        state = {
            "phase": "entity_extraction",
            "current_file": "spec_staged.md",
            "entities": ["E-001"],
        }
        save_state(tmp_path, state)

        state_file = tmp_path / "state.json"
        assert state_file.exists()
        loaded = json.loads(state_file.read_text())
        assert loaded == state

    def test_overwrites_existing_state(self, tmp_path: Path):
        """Test overwrites existing state.json."""
        old_state = {"phase": "old"}
        new_state = {"phase": "new", "extra": "data"}

        save_state(tmp_path, old_state)
        save_state(tmp_path, new_state)

        loaded = load_state(tmp_path)
        assert loaded == new_state

    def test_save_load_roundtrip(self, tmp_path: Path):
        """Test save and load preserves all data."""
        state = {
            "phase": "definition_extraction",
            "current_file": "spec_staged.md",
            "current_entity": "E-001",
            "files_completed": ["spec1.md"],
            "files_remaining": ["spec2.md", "spec3.md"],
            "extracted_entities": ["E-001", "E-002"],
            "extracted_relations": ["R-001"],
            "extracted_contexts": ["C-001"],
            "snippets_marked": 5,
            "snippets_decomposed": 3,
            "entities_from_snippets": 2,
            "orphans_found": 1,
        }
        save_state(tmp_path, state)
        loaded = load_state(tmp_path)
        assert loaded == state
