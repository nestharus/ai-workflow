"""Tests for spec_manager.decomposition.entity_index module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from spec_manager.decomposition.entity_index import (
    add_entity_to_index,
    add_keywords_to_entity,
    add_source_to_entity,
    check_rediscovery,
    get_all_keywords,
    load_entity_index,
    save_entity_index,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a workspace directory."""
    return tmp_path


class TestLoadSaveEntityIndex:
    """Tests for load_entity_index and save_entity_index functions."""

    def test_load_empty_workspace(self, workspace: Path):
        """Test loading from workspace without index file."""
        result = load_entity_index(workspace)
        assert result == {}

    def test_load_existing_index(self, workspace: Path):
        """Test loading existing entity_index.json."""
        index_data = {
            "E-001": {
                "name": "AuthService",
                "keywords": ["auth", "login"],
                "aliases": [],
                "sources": ["spec.md:5"],
            }
        }
        index_file = workspace / "entity_index.json"
        index_file.write_text(json.dumps(index_data))

        result = load_entity_index(workspace)
        assert result == index_data

    def test_save_creates_file(self, workspace: Path):
        """Test save_entity_index creates file."""
        index = {"E-001": {"name": "Test", "keywords": ["test"]}}
        save_entity_index(workspace, index)

        index_file = workspace / "entity_index.json"
        assert index_file.exists()

    def test_save_load_roundtrip(self, workspace: Path):
        """Test save and load preserves data."""
        original = {
            "E-001": {
                "name": "Authentication Service",
                "keywords": ["auth", "authentication", "login"],
                "aliases": ["AuthSvc"],
                "sources": ["spec.md:5", "spec.md:20"],
            },
            "E-002": {
                "name": "UserStore",
                "keywords": ["user", "store"],
                "aliases": [],
                "sources": ["spec.md:30"],
            },
        }
        save_entity_index(workspace, original)
        loaded = load_entity_index(workspace)
        assert loaded == original


class TestAddEntityToIndex:
    """Tests for add_entity_to_index function."""

    def test_adds_new_entity(self, workspace: Path):
        """Test adds entity to empty index."""
        add_entity_to_index(
            workspace=workspace,
            entity_id="E-001",
            name="Authentication Service",
            keywords=["auth", "login"],
            source="spec.md:5",
        )

        index = load_entity_index(workspace)
        assert "E-001" in index
        assert index["E-001"]["name"] == "Authentication Service"
        assert "auth" in index["E-001"]["keywords"]
        assert "login" in index["E-001"]["keywords"]
        assert "spec.md:5" in index["E-001"]["sources"]

    def test_normalizes_keywords_to_lowercase(self, workspace: Path):
        """Test keywords are normalized to lowercase."""
        add_entity_to_index(
            workspace=workspace,
            entity_id="E-001",
            name="Test",
            keywords=["Auth", "LOGIN", "UserStore"],
            source="spec.md:5",
        )

        index = load_entity_index(workspace)
        keywords = index["E-001"]["keywords"]
        assert "auth" in keywords
        assert "login" in keywords
        assert "userstore" in keywords
        assert "Auth" not in keywords  # Should be lowercase

    def test_adds_name_as_keyword(self, workspace: Path):
        """Test entity name is automatically added as keyword."""
        add_entity_to_index(
            workspace=workspace,
            entity_id="E-001",
            name="Authentication Service",
            keywords=["auth"],
            source="spec.md:5",
        )

        index = load_entity_index(workspace)
        assert "authentication service" in index["E-001"]["keywords"]

    def test_removes_duplicate_keywords(self, workspace: Path):
        """Test duplicate keywords are removed."""
        add_entity_to_index(
            workspace=workspace,
            entity_id="E-001",
            name="Test",
            keywords=["auth", "Auth", "AUTH", "auth"],
            source="spec.md:5",
        )

        index = load_entity_index(workspace)
        keywords = index["E-001"]["keywords"]
        # Count occurrences of 'auth'
        auth_count = sum(1 for kw in keywords if kw == "auth")
        assert auth_count == 1


class TestAddSourceToEntity:
    """Tests for add_source_to_entity function."""

    def test_adds_source_to_existing_entity(self, workspace: Path):
        """Test adds source to existing entity."""
        add_entity_to_index(workspace, "E-001", "Test", ["test"], "spec.md:5")
        add_source_to_entity(workspace, "E-001", "other.md:10")

        index = load_entity_index(workspace)
        assert "spec.md:5" in index["E-001"]["sources"]
        assert "other.md:10" in index["E-001"]["sources"]

    def test_does_not_duplicate_source(self, workspace: Path):
        """Test doesn't add duplicate source."""
        add_entity_to_index(workspace, "E-001", "Test", ["test"], "spec.md:5")
        add_source_to_entity(workspace, "E-001", "spec.md:5")

        index = load_entity_index(workspace)
        assert index["E-001"]["sources"].count("spec.md:5") == 1

    def test_ignores_nonexistent_entity(self, workspace: Path):
        """Test silently ignores nonexistent entity."""
        add_source_to_entity(workspace, "E-999", "spec.md:5")
        index = load_entity_index(workspace)
        assert "E-999" not in index


class TestAddKeywordsToEntity:
    """Tests for add_keywords_to_entity function."""

    def test_adds_keywords_to_existing_entity(self, workspace: Path):
        """Test adds keywords to existing entity."""
        add_entity_to_index(workspace, "E-001", "Test", ["test"], "spec.md:5")
        add_keywords_to_entity(workspace, "E-001", ["new", "keywords"])

        index = load_entity_index(workspace)
        assert "new" in index["E-001"]["keywords"]
        assert "keywords" in index["E-001"]["keywords"]

    def test_does_not_duplicate_keywords(self, workspace: Path):
        """Test doesn't add duplicate keywords."""
        add_entity_to_index(workspace, "E-001", "Test", ["test"], "spec.md:5")
        add_keywords_to_entity(workspace, "E-001", ["test", "Test", "TEST"])

        index = load_entity_index(workspace)
        # Count 'test' occurrences
        test_count = sum(1 for kw in index["E-001"]["keywords"] if kw == "test")
        assert test_count == 1


class TestCheckRediscovery:
    """Tests for check_rediscovery function."""

    def test_no_match_in_empty_index(self, workspace: Path):
        """Test returns no match for empty index."""
        result = check_rediscovery(workspace, "AuthService", ["auth", "login"])
        assert result["match"] is None

    def test_exact_keyword_match(self, workspace: Path):
        """Test finds match with exact keyword overlap."""
        add_entity_to_index(workspace, "E-001", "AuthService", ["auth", "login"], "spec.md:5")

        result = check_rediscovery(workspace, "Authentication", ["auth", "login"])
        assert result["match"] == "E-001"
        assert result["confidence"] > 0.5

    def test_partial_keyword_match(self, workspace: Path):
        """Test finds match with partial keyword overlap."""
        add_entity_to_index(
            workspace, "E-001", "AuthService", ["authentication", "login"], "spec.md:5"
        )

        result = check_rediscovery(workspace, "Auth", ["auth"])
        assert result["match"] == "E-001"  # "auth" is substring of "authentication"

    def test_name_as_keyword(self, workspace: Path):
        """Test matches by entity name."""
        add_entity_to_index(workspace, "E-001", "UserStore", ["user", "store"], "spec.md:5")

        result = check_rediscovery(workspace, "UserStore", [])
        assert result["match"] == "E-001"

    def test_no_match_below_threshold(self, workspace: Path):
        """Test no match when confidence is below threshold."""
        add_entity_to_index(
            workspace, "E-001", "AuthService", ["auth", "login", "session", "token"], "spec.md:5"
        )

        # Completely unrelated keywords
        result = check_rediscovery(workspace, "Database", ["db", "sql", "query"])
        assert result["match"] is None

    def test_returns_matched_keywords(self, workspace: Path):
        """Test returns list of matched keywords."""
        add_entity_to_index(
            workspace, "E-001", "AuthService", ["auth", "login", "session"], "spec.md:5"
        )

        result = check_rediscovery(workspace, "Auth", ["auth", "session"])
        assert result["match"] == "E-001"
        assert "auth" in result["matched_keywords"]
        assert "session" in result["matched_keywords"]

    def test_finds_best_match_among_multiple(self, workspace: Path):
        """Test finds best match when multiple entities exist."""
        add_entity_to_index(workspace, "E-001", "AuthService", ["auth", "login"], "spec.md:5")
        add_entity_to_index(workspace, "E-002", "UserStore", ["user", "store", "db"], "spec.md:10")
        add_entity_to_index(
            workspace, "E-003", "TokenService", ["token", "jwt", "auth"], "spec.md:15"
        )

        # Should match E-001 better than E-003 for "login"
        result = check_rediscovery(workspace, "Login", ["auth", "login"])
        assert result["match"] == "E-001"


class TestGetAllKeywords:
    """Tests for get_all_keywords function."""

    def test_empty_index(self, workspace: Path):
        """Test returns empty dict for empty index."""
        result = get_all_keywords(workspace)
        assert result == {}

    def test_maps_keywords_to_entities(self, workspace: Path):
        """Test returns correct keyword to entity mapping."""
        add_entity_to_index(workspace, "E-001", "Auth", ["auth", "login"], "spec.md:5")
        add_entity_to_index(workspace, "E-002", "User", ["user", "profile"], "spec.md:10")

        result = get_all_keywords(workspace)
        assert result["auth"] == "E-001"
        assert result["login"] == "E-001"
        assert result["user"] == "E-002"
        assert result["profile"] == "E-002"

    def test_later_entity_overwrites_keyword(self, workspace: Path):
        """Test later entity overwrites keyword mapping if same keyword."""
        add_entity_to_index(workspace, "E-001", "Auth", ["auth"], "spec.md:5")
        add_entity_to_index(workspace, "E-002", "Auth2", ["auth"], "spec.md:10")

        result = get_all_keywords(workspace)
        # E-002 was added later, so it should own "auth"
        assert result["auth"] == "E-002"
