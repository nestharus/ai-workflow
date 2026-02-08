"""Tests for spec_manager.decomposition.id_generator module."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.spec_manager.spec_manager.decomposition.id_generator import (
    IDType,
    generate_id,
    get_ids_by_type,
    get_source_lines,
    load_id_map,
    save_id_map,
)


class TestIDType:
    """Tests for IDType enum."""

    def test_entity_type_value(self):
        """Test entity type has correct value."""
        assert IDType.ENTITY.value == "E"

    def test_relation_type_value(self):
        """Test relation type has correct value."""
        assert IDType.RELATION.value == "R"

    def test_context_type_value(self):
        """Test context type has correct value."""
        assert IDType.CONTEXT.value == "C"

    def test_composition_type_value(self):
        """Test composition type has correct value."""
        assert IDType.COMPOSITION.value == "X"

    def test_orphan_type_value(self):
        """Test orphan type has correct value."""
        assert IDType.ORPHAN.value == "O"

    def test_snippet_type_value(self):
        """Test snippet type has correct value."""
        assert IDType.SNIPPET.value == "S"


class TestGenerateID:
    """Tests for generate_id function."""

    def test_generate_first_entity_id(self):
        """Test generating first entity ID from empty map."""
        id_map: dict = {}
        new_id = generate_id(IDType.ENTITY, id_map)
        assert new_id == "E-001"

    def test_generate_sequential_entity_ids(self):
        """Test generating sequential entity IDs."""
        id_map = {"E-001": [], "E-002": []}
        new_id = generate_id(IDType.ENTITY, id_map)
        assert new_id == "E-003"

    def test_generate_first_relation_id(self):
        """Test generating first relation ID."""
        id_map: dict = {}
        new_id = generate_id(IDType.RELATION, id_map)
        assert new_id == "R-001"

    def test_generate_id_with_mixed_types(self):
        """Test generating ID when map has multiple types."""
        id_map = {
            "E-001": [],
            "E-002": [],
            "R-001": [],
            "C-001": [],
        }
        entity_id = generate_id(IDType.ENTITY, id_map)
        relation_id = generate_id(IDType.RELATION, id_map)
        context_id = generate_id(IDType.CONTEXT, id_map)

        assert entity_id == "E-003"
        assert relation_id == "R-002"
        assert context_id == "C-002"

    def test_generate_snippet_id(self):
        """Test generating snippet ID."""
        id_map = {"S-001": [], "S-002": [], "S-003": []}
        new_id = generate_id(IDType.SNIPPET, id_map)
        assert new_id == "S-004"

    def test_generate_id_with_gaps_in_sequence(self):
        """Test that ID generation finds max, not fills gaps."""
        id_map = {"E-001": [], "E-005": [], "E-003": []}
        new_id = generate_id(IDType.ENTITY, id_map)
        assert new_id == "E-006"

    def test_generate_id_formatting_three_digits(self):
        """Test ID is always 3 digits zero-padded."""
        id_map: dict = {}
        new_id = generate_id(IDType.ORPHAN, id_map)
        assert new_id == "O-001"
        assert len(new_id.split("-")[1]) == 3


class TestLoadSaveIDMap:
    """Tests for load_id_map and save_id_map functions."""

    def test_load_id_map_empty_workspace(self, tmp_path: Path):
        """Test loading from workspace without id_map.json."""
        result = load_id_map(tmp_path)
        assert result == {}

    def test_load_id_map_existing_file(self, tmp_path: Path):
        """Test loading existing id_map.json."""
        id_map_data = {
            "E-001": [{"file": "spec.md", "line": 10, "type": "entity"}],
            "R-001": [{"file": "spec.md", "line": 20, "type": "relation"}],
        }
        id_map_file = tmp_path / "id_map.json"
        id_map_file.write_text(json.dumps(id_map_data))

        result = load_id_map(tmp_path)
        assert result == id_map_data

    def test_save_id_map_creates_file(self, tmp_path: Path):
        """Test save_id_map creates id_map.json."""
        id_map = {"E-001": [{"file": "spec.md", "line": 10}]}
        save_id_map(tmp_path, id_map)

        id_map_file = tmp_path / "id_map.json"
        assert id_map_file.exists()

        loaded = json.loads(id_map_file.read_text())
        assert loaded == id_map

    def test_save_load_roundtrip(self, tmp_path: Path):
        """Test save and load preserves data."""
        original = {
            "E-001": [{"file": "spec.md", "line": 5, "type": "entity"}],
            "E-002": [
                {"file": "spec.md", "line": 10, "type": "entity"},
                {"file": "spec.md", "line": 15, "type": "entity"},
            ],
            "R-001": [
                {"file": "spec.md", "line": 20, "type": "relation", "from": "E-001", "to": "E-002"}
            ],
        }
        save_id_map(tmp_path, original)
        loaded = load_id_map(tmp_path)
        assert loaded == original


class TestGetIDsByType:
    """Tests for get_ids_by_type function."""

    def test_get_entity_ids(self):
        """Test getting all entity IDs."""
        id_map = {
            "E-001": [],
            "E-002": [],
            "R-001": [],
            "C-001": [],
        }
        entity_ids = get_ids_by_type(id_map, IDType.ENTITY)
        assert set(entity_ids) == {"E-001", "E-002"}

    def test_get_relation_ids(self):
        """Test getting all relation IDs."""
        id_map = {
            "E-001": [],
            "R-001": [],
            "R-002": [],
            "R-003": [],
        }
        relation_ids = get_ids_by_type(id_map, IDType.RELATION)
        assert set(relation_ids) == {"R-001", "R-002", "R-003"}

    def test_get_ids_empty_result(self):
        """Test getting IDs when none of that type exist."""
        id_map = {"E-001": [], "E-002": []}
        context_ids = get_ids_by_type(id_map, IDType.CONTEXT)
        assert context_ids == []

    def test_get_ids_empty_map(self):
        """Test getting IDs from empty map."""
        id_map: dict = {}
        entity_ids = get_ids_by_type(id_map, IDType.ENTITY)
        assert entity_ids == []


class TestGetSourceLines:
    """Tests for get_source_lines function."""

    def test_get_source_lines_existing_id(self):
        """Test getting source lines for existing ID."""
        id_map = {
            "E-001": [
                {"file": "spec.md", "line": 5},
                {"file": "spec.md", "line": 10},
            ]
        }
        sources = get_source_lines(id_map, "E-001")
        assert len(sources) == 2
        assert sources[0]["line"] == 5
        assert sources[1]["line"] == 10

    def test_get_source_lines_nonexistent_id(self):
        """Test getting source lines for nonexistent ID."""
        id_map = {"E-001": []}
        sources = get_source_lines(id_map, "E-999")
        assert sources == []

    def test_get_source_lines_empty_map(self):
        """Test getting source lines from empty map."""
        id_map: dict = {}
        sources = get_source_lines(id_map, "E-001")
        assert sources == []
