"""Tests for spec_manager.decomposition.staging module."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.spec_manager.spec_manager.decomposition.staging import (
    collect_and_remove_snippets,
    create_staging_file,
    embed_id_at_line,
    format_content_for_agent,
    get_embedded_ids,
    get_line_content,
    get_marked_snippets,
    get_remaining_lines,
    is_file_empty,
    mark_relation_snippet,
    remove_line,
    remove_lines,
    write_snippet_staging_file,
)


@pytest.fixture
def sample_spec(tmp_path: Path) -> Path:
    """Create a sample spec file for testing."""
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(
        """# Test Specification

## Authentication Service

The AuthService handles user login.
It uses the UserStore for validation.
AuthService depends on TokenService.

## User Store

UserStore manages user data.
"""
    )
    return spec_file


@pytest.fixture
def staging_dir(tmp_path: Path) -> Path:
    """Create a staging directory."""
    staging = tmp_path / "staging"
    staging.mkdir()
    return staging


class TestCreateStagingFile:
    """Tests for create_staging_file function."""

    def test_creates_staging_file(self, sample_spec: Path, staging_dir: Path):
        """Test staging file is created with correct name."""
        staged = create_staging_file(sample_spec, staging_dir)
        assert staged.exists()
        assert staged.name == "spec_staged.md"

    def test_adds_header_comment(self, sample_spec: Path, staging_dir: Path):
        """Test staging file has header comment with source path."""
        staged = create_staging_file(sample_spec, staging_dir)
        content = staged.read_text()
        assert content.startswith("<!-- STAGED FROM:")
        assert str(sample_spec) in content

    def test_preserves_original_content(self, sample_spec: Path, staging_dir: Path):
        """Test original content is preserved after header."""
        original = sample_spec.read_text()
        staged = create_staging_file(sample_spec, staging_dir)
        content = staged.read_text()
        # Content should contain original after header
        assert "# Test Specification" in content
        assert "AuthService handles user login" in content


class TestEmbedIDAtLine:
    """Tests for embed_id_at_line function."""

    def test_embeds_id_at_correct_line(self, sample_spec: Path, staging_dir: Path):
        """Test ID is embedded at specified line."""
        staged = create_staging_file(sample_spec, staging_dir)
        embed_id_at_line(staged, 5, "E-001")
        content = staged.read_text()
        lines = content.split("\n")
        # Line 5 in original = "The AuthService handles user login."
        # After header offset, should find E-001
        matching_lines = [ln for ln in lines if "[E-001]" in ln]
        assert len(matching_lines) == 1
        assert "AuthService handles user login" in matching_lines[0]

    def test_does_not_duplicate_id(self, sample_spec: Path, staging_dir: Path):
        """Test embedding same ID twice doesn't duplicate."""
        staged = create_staging_file(sample_spec, staging_dir)
        embed_id_at_line(staged, 5, "E-001")
        embed_id_at_line(staged, 5, "E-001")
        content = staged.read_text()
        assert content.count("[E-001]") == 1

    def test_can_embed_multiple_ids_same_line(self, sample_spec: Path, staging_dir: Path):
        """Test multiple different IDs can be on same line."""
        staged = create_staging_file(sample_spec, staging_dir)
        embed_id_at_line(staged, 5, "E-001")
        embed_id_at_line(staged, 5, "R-001")
        content = staged.read_text()
        assert "[E-001]" in content
        assert "[R-001]" in content


class TestRemoveLine:
    """Tests for remove_line function."""

    def test_removes_line_content(self, sample_spec: Path, staging_dir: Path):
        """Test line is replaced with extraction marker."""
        staged = create_staging_file(sample_spec, staging_dir)
        removed = remove_line(staged, 5)
        assert "AuthService handles user login" in removed
        content = staged.read_text()
        assert "<!-- EXTRACTED: 5 -->" in content

    def test_returns_removed_content(self, sample_spec: Path, staging_dir: Path):
        """Test function returns the removed content."""
        staged = create_staging_file(sample_spec, staging_dir)
        removed = remove_line(staged, 5)
        assert "AuthService" in removed


class TestRemoveLines:
    """Tests for remove_lines function."""

    def test_removes_multiple_lines(self, sample_spec: Path, staging_dir: Path):
        """Test multiple lines are removed."""
        staged = create_staging_file(sample_spec, staging_dir)
        removed = remove_lines(staged, [5, 6, 7])
        assert len(removed) == 3
        content = staged.read_text()
        assert "<!-- EXTRACTED: 5 -->" in content
        assert "<!-- EXTRACTED: 6 -->" in content
        assert "<!-- EXTRACTED: 7 -->" in content

    def test_returns_removed_in_order(self, sample_spec: Path, staging_dir: Path):
        """Test removed content is returned in line order."""
        staged = create_staging_file(sample_spec, staging_dir)
        removed = remove_lines(staged, [7, 5, 6])  # Out of order input
        # Should be sorted by line number
        assert "AuthService handles" in removed[0]  # Line 5
        assert "UserStore" in removed[1]  # Line 6


class TestGetRemainingLines:
    """Tests for get_remaining_lines function."""

    def test_returns_all_content_lines(self, sample_spec: Path, staging_dir: Path):
        """Test returns all non-empty lines."""
        staged = create_staging_file(sample_spec, staging_dir)
        remaining = get_remaining_lines(staged)
        assert len(remaining) > 0
        # Check structure
        assert all("line" in r and "text" in r for r in remaining)

    def test_excludes_extracted_lines(self, sample_spec: Path, staging_dir: Path):
        """Test extracted lines are not returned."""
        staged = create_staging_file(sample_spec, staging_dir)
        remove_line(staged, 5)
        remaining = get_remaining_lines(staged)
        texts = [r["text"] for r in remaining]
        assert not any("AuthService handles user login" in t for t in texts)

    def test_excludes_empty_lines(self, sample_spec: Path, staging_dir: Path):
        """Test empty lines are not returned."""
        staged = create_staging_file(sample_spec, staging_dir)
        remaining = get_remaining_lines(staged)
        assert all(r["text"].strip() for r in remaining)


class TestIsFileEmpty:
    """Tests for is_file_empty function."""

    def test_file_not_empty_initially(self, sample_spec: Path, staging_dir: Path):
        """Test staged file is not empty initially."""
        staged = create_staging_file(sample_spec, staging_dir)
        assert not is_file_empty(staged)

    def test_file_empty_after_all_extracted(self, tmp_path: Path):
        """Test file is empty when all content extracted."""
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        # Create minimal spec
        spec = tmp_path / "mini.md"
        spec.write_text("Single line of content.")
        staged = create_staging_file(spec, staging_dir)
        remove_line(staged, 1)
        assert is_file_empty(staged)


class TestGetLineContent:
    """Tests for get_line_content function."""

    def test_returns_correct_line(self, sample_spec: Path, staging_dir: Path):
        """Test returns content at specified line."""
        staged = create_staging_file(sample_spec, staging_dir)
        content = get_line_content(staged, 5)
        assert "AuthService handles user login" in content

    def test_returns_empty_for_invalid_line(self, sample_spec: Path, staging_dir: Path):
        """Test returns empty string for out-of-range line."""
        staged = create_staging_file(sample_spec, staging_dir)
        content = get_line_content(staged, 999)
        assert content == ""


class TestGetEmbeddedIDs:
    """Tests for get_embedded_ids function."""

    def test_returns_embedded_ids(self, sample_spec: Path, staging_dir: Path):
        """Test returns dict of line numbers to IDs."""
        staged = create_staging_file(sample_spec, staging_dir)
        embed_id_at_line(staged, 5, "E-001")
        embed_id_at_line(staged, 6, "R-001")
        ids = get_embedded_ids(staged)
        assert 5 in ids
        assert "E-001" in ids[5]
        assert 6 in ids
        assert "R-001" in ids[6]

    def test_returns_empty_when_no_ids(self, sample_spec: Path, staging_dir: Path):
        """Test returns empty dict when no IDs embedded."""
        staged = create_staging_file(sample_spec, staging_dir)
        ids = get_embedded_ids(staged)
        assert ids == {}


class TestMarkRelationSnippet:
    """Tests for mark_relation_snippet function."""

    def test_marks_line_with_snippet_comment(self, sample_spec: Path, staging_dir: Path):
        """Test line is marked with snippet comment."""
        staged = create_staging_file(sample_spec, staging_dir)
        mark_relation_snippet(staged, 6, "S-001", "E-001")
        content = staged.read_text()
        assert "<!-- SNIPPET: S-001 for E-001 -->" in content

    def test_does_not_mark_already_marked(self, sample_spec: Path, staging_dir: Path):
        """Test already marked lines are not marked again."""
        staged = create_staging_file(sample_spec, staging_dir)
        mark_relation_snippet(staged, 6, "S-001", "E-001")
        mark_relation_snippet(staged, 6, "S-002", "E-001")
        content = staged.read_text()
        assert content.count("<!-- SNIPPET:") == 1

    def test_does_not_mark_extracted_lines(self, sample_spec: Path, staging_dir: Path):
        """Test extracted lines are not marked."""
        staged = create_staging_file(sample_spec, staging_dir)
        remove_line(staged, 6)
        mark_relation_snippet(staged, 6, "S-001", "E-001")
        content = staged.read_text()
        assert "<!-- SNIPPET:" not in content or "<!-- EXTRACTED:" in content


class TestGetMarkedSnippets:
    """Tests for get_marked_snippets function."""

    def test_returns_marked_snippets(self, sample_spec: Path, staging_dir: Path):
        """Test returns list of marked snippets."""
        staged = create_staging_file(sample_spec, staging_dir)
        mark_relation_snippet(staged, 6, "S-001", "E-001")
        mark_relation_snippet(staged, 7, "S-002", "E-001")
        snippets = get_marked_snippets(staged)
        assert len(snippets) == 2
        assert snippets[0]["snippet_id"] == "S-001"
        assert snippets[0]["source_entity"] == "E-001"
        assert snippets[1]["snippet_id"] == "S-002"

    def test_returns_empty_when_no_snippets(self, sample_spec: Path, staging_dir: Path):
        """Test returns empty list when no snippets marked."""
        staged = create_staging_file(sample_spec, staging_dir)
        snippets = get_marked_snippets(staged)
        assert snippets == []


class TestCollectAndRemoveSnippets:
    """Tests for collect_and_remove_snippets function."""

    def test_collects_and_removes_snippets(self, sample_spec: Path, staging_dir: Path):
        """Test snippets are collected and marked as extracted."""
        staged = create_staging_file(sample_spec, staging_dir)
        mark_relation_snippet(staged, 6, "S-001", "E-001")
        mark_relation_snippet(staged, 7, "S-002", "E-001")

        snippets = collect_and_remove_snippets(staged)
        assert len(snippets) == 2

        content = staged.read_text()
        assert "<!-- EXTRACTED: 6 (snippet S-001) -->" in content
        assert "<!-- EXTRACTED: 7 (snippet S-002) -->" in content

    def test_returns_snippet_text(self, sample_spec: Path, staging_dir: Path):
        """Test returned snippets include text."""
        staged = create_staging_file(sample_spec, staging_dir)
        mark_relation_snippet(staged, 6, "S-001", "E-001")
        snippets = collect_and_remove_snippets(staged)
        assert "UserStore" in snippets[0]["text"]


class TestWriteSnippetStagingFile:
    """Tests for write_snippet_staging_file function."""

    def test_creates_snippet_file(self, tmp_path: Path):
        """Test creates snippet staging file."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        snippets = [
            {"snippet_id": "S-001", "line": 6, "text": "Uses UserStore for validation."},
            {"snippet_id": "S-002", "line": 7, "text": "Depends on TokenService."},
        ]

        result = write_snippet_staging_file(
            workspace=workspace,
            source_entity_id="E-001",
            source_entity_name="AuthService",
            snippets=snippets,
            source_file="spec.md",
        )

        assert result.exists()
        assert result.name == "E-001_snippets.md"
        content = result.read_text()
        assert "E-001" in content
        assert "AuthService" in content
        assert "S-001" in content
        assert "S-002" in content

    def test_appends_to_existing_file(self, tmp_path: Path):
        """Test appends to existing snippet file."""
        workspace = tmp_path / "workspace"
        (workspace / "relation_staging").mkdir(parents=True)

        snippets1 = [{"snippet_id": "S-001", "line": 6, "text": "First snippet."}]
        snippets2 = [{"snippet_id": "S-002", "line": 7, "text": "Second snippet."}]

        write_snippet_staging_file(workspace, "E-001", "Auth", snippets1, "spec.md")
        write_snippet_staging_file(workspace, "E-001", "Auth", snippets2, "spec.md")

        result_file = workspace / "relation_staging" / "E-001_snippets.md"
        content = result_file.read_text()
        assert "S-001" in content
        assert "S-002" in content


class TestFormatContentForAgent:
    """Tests for format_content_for_agent function."""

    def test_formats_with_line_numbers(self, sample_spec: Path, staging_dir: Path):
        """Test content is formatted with line numbers."""
        staged = create_staging_file(sample_spec, staging_dir)
        content = format_content_for_agent(staged)
        # Should have format "line_number: text"
        lines = content.split("\n")
        assert any(": " in line for line in lines)
        # First content line should start with a number
        assert lines[0].split(":")[0].strip().isdigit()

    def test_excludes_extracted_lines(self, sample_spec: Path, staging_dir: Path):
        """Test extracted lines are excluded from formatted output."""
        staged = create_staging_file(sample_spec, staging_dir)
        remove_line(staged, 5)
        content = format_content_for_agent(staged)
        assert "AuthService handles user login" not in content

    def test_excludes_snippet_lines(self, sample_spec: Path, staging_dir: Path):
        """Test snippet-marked lines are excluded from formatted output."""
        staged = create_staging_file(sample_spec, staging_dir)
        mark_relation_snippet(staged, 6, "S-001", "E-001")
        content = format_content_for_agent(staged)
        # The marked line should not appear in agent content
        assert "<!-- SNIPPET:" not in content

    def test_empty_when_all_extracted(self, tmp_path: Path):
        """Test returns empty string when all content extracted."""
        staging_dir = tmp_path / "staging"
        staging_dir.mkdir()
        spec = tmp_path / "mini.md"
        spec.write_text("Single line.")
        staged = create_staging_file(spec, staging_dir)
        remove_line(staged, 1)
        content = format_content_for_agent(staged)
        assert content == ""
