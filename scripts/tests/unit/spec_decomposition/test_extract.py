"""Tests for spec_decomposition.extract module."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.spec_decomposition.extract import (
    append_evidence_to_entity,
    create_discovered_entity_document,
    create_rich_relation_document,
    extract_context_to_document,
    extract_entity_to_document,
    extract_relation_to_document,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create workspace directory structure."""
    ws = tmp_path / "workspace"
    (ws / "entities").mkdir(parents=True)
    (ws / "relations").mkdir()
    (ws / "context").mkdir()
    return ws


class TestExtractEntityToDocument:
    """Tests for extract_entity_to_document function."""

    def test_creates_entity_file(self, workspace: Path):
        """Test creates entity markdown file."""
        evidence = [
            {"file": "spec.md", "line": 5, "text": "AuthService handles login."},
        ]
        result = extract_entity_to_document(
            workspace=workspace,
            entity_id="E-001",
            entity_name="Authentication Service",
            evidence=evidence,
        )
        assert result.exists()
        assert result.name == "E-001.md"

    def test_entity_document_has_correct_structure(self, workspace: Path):
        """Test entity document has expected markdown structure."""
        evidence = [
            {"file": "spec.md", "line": 5, "text": "AuthService handles login."},
        ]
        result = extract_entity_to_document(
            workspace=workspace,
            entity_id="E-001",
            entity_name="Authentication Service",
            evidence=evidence,
        )
        content = result.read_text()

        assert "# Authentication Service" in content
        assert "**ID**: `E-001`" in content
        assert "## Evidence" in content
        assert "### Source 1" in content
        assert "**File**: `spec.md`" in content
        assert "**Line**: 5" in content
        assert "> AuthService handles login." in content

    def test_multiple_evidence_items(self, workspace: Path):
        """Test entity with multiple evidence sources."""
        evidence = [
            {"file": "spec.md", "line": 5, "text": "First evidence."},
            {"file": "spec.md", "line": 10, "text": "Second evidence."},
            {"file": "other.md", "line": 3, "text": "Third evidence."},
        ]
        result = extract_entity_to_document(
            workspace=workspace,
            entity_id="E-002",
            entity_name="UserStore",
            evidence=evidence,
        )
        content = result.read_text()

        assert "### Source 1" in content
        assert "### Source 2" in content
        assert "### Source 3" in content
        assert "First evidence" in content
        assert "Second evidence" in content
        assert "Third evidence" in content


class TestExtractRelationToDocument:
    """Tests for extract_relation_to_document function."""

    def test_creates_relation_file(self, workspace: Path):
        """Test creates relation markdown file."""
        evidence = {"file": "spec.md", "line": 15, "text": "AuthService uses UserStore."}
        result = extract_relation_to_document(
            workspace=workspace,
            relation_id="R-001",
            from_entity="E-001",
            to_entity="E-002",
            relation_type="uses",
            evidence=evidence,
        )
        assert result.exists()
        assert result.name == "R-001.md"

    def test_relation_document_structure(self, workspace: Path):
        """Test relation document has correct structure."""
        evidence = {"file": "spec.md", "line": 15, "text": "AuthService uses UserStore."}
        result = extract_relation_to_document(
            workspace=workspace,
            relation_id="R-001",
            from_entity="E-001",
            to_entity="E-002",
            relation_type="uses",
            evidence=evidence,
        )
        content = result.read_text()

        assert "# Relation: E-001 → E-002" in content
        assert "**ID**: `R-001`" in content
        assert "**Type**: `uses`" in content
        assert "**From**: `E-001`" in content
        assert "**To**: `E-002`" in content
        assert "> AuthService uses UserStore." in content


class TestExtractContextToDocument:
    """Tests for extract_context_to_document function."""

    def test_creates_context_file(self, workspace: Path):
        """Test creates context markdown file."""
        evidence = {"file": "spec.md", "line": 20, "text": "We chose OAuth2 for scalability."}
        result = extract_context_to_document(
            workspace=workspace,
            context_id="C-001",
            entity_id="E-001",
            context_type="decision",
            evidence=evidence,
        )
        assert result.exists()
        assert result.name == "C-001.md"

    def test_context_document_structure(self, workspace: Path):
        """Test context document has correct structure."""
        evidence = {"file": "spec.md", "line": 20, "text": "We chose OAuth2 for scalability."}
        result = extract_context_to_document(
            workspace=workspace,
            context_id="C-001",
            entity_id="E-001",
            context_type="decision",
            evidence=evidence,
        )
        content = result.read_text()

        assert "# Context for E-001" in content
        assert "**ID**: `C-001`" in content
        assert "**Type**: `decision`" in content
        assert "**Entity**: `E-001`" in content
        assert "> We chose OAuth2 for scalability." in content

    def test_handles_nested_evidence_structure(self, workspace: Path):
        """Test handles nested evidence dict."""
        evidence = {
            "evidence": {"file": "spec.md", "line": 25, "text": "Nested evidence."},
            "type": "constraint",
        }
        result = extract_context_to_document(
            workspace=workspace,
            context_id="C-002",
            entity_id="E-001",
            context_type="constraint",
            evidence=evidence,
        )
        content = result.read_text()
        assert "> Nested evidence." in content


class TestAppendEvidenceToEntity:
    """Tests for append_evidence_to_entity function."""

    def test_appends_evidence_to_existing_entity(self, workspace: Path):
        """Test appends new evidence to existing entity file."""
        # Create initial entity
        evidence = [{"file": "spec.md", "line": 5, "text": "Initial evidence."}]
        entity_file = extract_entity_to_document(
            workspace=workspace,
            entity_id="E-001",
            entity_name="Test Entity",
            evidence=evidence,
        )

        # Append new evidence
        new_evidence = {"file": "other.md", "line": 10, "text": "Additional evidence."}
        append_evidence_to_entity(workspace, "E-001", new_evidence)

        content = entity_file.read_text()
        assert "### Source 1" in content
        assert "### Source 2" in content
        assert "Initial evidence" in content
        assert "Additional evidence" in content

    def test_raises_for_nonexistent_entity(self, workspace: Path):
        """Test raises FileNotFoundError for missing entity."""
        evidence = {"file": "spec.md", "line": 5, "text": "Test."}
        with pytest.raises(FileNotFoundError):
            append_evidence_to_entity(workspace, "E-999", evidence)


class TestCreateRichRelationDocument:
    """Tests for create_rich_relation_document function."""

    def test_creates_rich_relation_file(self, workspace: Path):
        """Test creates rich relation markdown file."""
        targets = [
            {"id": "E-002", "name": "UserStore", "discovered_from_snippet": False},
        ]
        result = create_rich_relation_document(
            workspace=workspace,
            relation_id="R-001",
            snippet_id="S-001",
            source_entity="E-001",
            source_entity_name="AuthService",
            targets=targets,
            relationship_type="uses",
            relationship_context="for credential validation",
            original_text="AuthService uses UserStore for validation.",
            file="spec.md",
            line=15,
        )
        assert result.exists()
        assert result.name == "R-001.md"

    def test_rich_relation_structure(self, workspace: Path):
        """Test rich relation has complete structure."""
        targets = [
            {"id": "E-002", "name": "UserStore", "discovered_from_snippet": False},
            {"id": "E-003", "name": "TokenService", "discovered_from_snippet": True},
        ]
        result = create_rich_relation_document(
            workspace=workspace,
            relation_id="R-001",
            snippet_id="S-001",
            source_entity="E-001",
            source_entity_name="AuthService",
            targets=targets,
            relationship_type="depends_on",
            relationship_context="for JWT creation",
            original_text="AuthService depends on TokenService for JWT creation.",
            file="spec.md",
            line=20,
        )
        content = result.read_text()

        assert "# Relation R-001" in content
        assert "**Snippet**: `S-001`" in content
        assert "**Source**: `E-001` (AuthService)" in content
        assert "`E-002` (UserStore)" in content
        assert "`E-003` (TokenService) - *discovered from this snippet*" in content
        assert "**Type**: `depends_on`" in content
        assert "**Context**: for JWT creation" in content
        assert "> AuthService depends on TokenService" in content
        assert "**File**: `spec.md`" in content
        assert "**Line**: 20" in content


class TestCreateDiscoveredEntityDocument:
    """Tests for create_discovered_entity_document function."""

    def test_creates_discovered_entity_file(self, workspace: Path):
        """Test creates discovered entity markdown file."""
        result = create_discovered_entity_document(
            workspace=workspace,
            entity_id="E-003",
            entity_name="TokenService",
            keywords=["token", "TokenService", "JWT"],
            discovered_from_snippet="S-001",
            context_text="AuthService depends on TokenService for JWT creation.",
        )
        assert result.exists()
        assert result.name == "E-003.md"

    def test_discovered_entity_structure(self, workspace: Path):
        """Test discovered entity has correct structure."""
        result = create_discovered_entity_document(
            workspace=workspace,
            entity_id="E-003",
            entity_name="TokenService",
            keywords=["token", "TokenService", "JWT"],
            discovered_from_snippet="S-001",
            context_text="AuthService depends on TokenService for JWT creation.",
        )
        content = result.read_text()

        assert "# TokenService" in content
        assert "**ID**: `E-003`" in content
        assert "**Discovered From**: `S-001`" in content
        assert "## Discovery Context" in content
        assert "> AuthService depends on TokenService" in content
        assert "## Keywords" in content
        assert "- token" in content
        assert "- TokenService" in content
        assert "- JWT" in content
        assert "## Evidence" in content
        assert "*Entity discovered from relation snippet - no direct definition found yet.*" in content
