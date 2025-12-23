"""Tests for scripts.naturalize_yaml module."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from unittest import mock

from scripts.naturalize_yaml import (
    generate_id,
    main,
    process_yaml_file,
)


class TestGenerateId:
    """Tests for generate_id function."""

    def test_generates_id_with_prefix_and_index(self) -> None:
        """Should generate ID from prefix and index."""
        result = generate_id("section", 0)
        assert result == "section.0"

    def test_generates_id_with_different_index(self) -> None:
        """Should generate ID with different index values."""
        result = generate_id("item", 5)
        assert result == "item.5"

    def test_generates_id_with_complex_prefix(self) -> None:
        """Should handle complex prefix strings."""
        result = generate_id("parent.child", 10)
        assert result == "parent.child.10"


class TestProcessYamlFile:
    """Tests for process_yaml_file function."""

    def test_returns_unchanged_for_file_without_patterns(self, tmp_path: Path) -> None:
        """Should return False and empty stats for unchanged file."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("key: value\n")

        changed, stats = process_yaml_file(yaml_file)

        assert changed is False
        assert stats["types_removed"] == 0
        assert stats["items_renamed"] == 0
        assert stats["ids_added"] == 0
        assert stats["text_renamed"] == {}

    def test_removes_type_field_with_text_field(self, tmp_path: Path) -> None:
        """Should remove type: and rename text: to semantic field."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("type: rule\ntext: Follow this rule.\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        assert stats["types_removed"] == 1
        assert stats["text_renamed"] == {"rule": 1}

        content = yaml_file.read_text()
        assert "type:" not in content
        assert "rule: Follow this rule." in content

    def test_removes_type_text_renames_to_note(self, tmp_path: Path) -> None:
        """Should rename type: text with text: to note:."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("type: text\ntext: Some text content.\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        assert stats["types_removed"] == 1
        assert stats["text_renamed"] == {"text": 1}

        content = yaml_file.read_text()
        assert "type:" not in content
        assert "note: Some text content." in content

    def test_removes_type_field_various_types(self, tmp_path: Path) -> None:
        """Should handle various type values (step, note, example, code, definition, anti_pattern, pattern)."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("type: step\ntext: Step 1\n---\ntype: note\ntext: Note content\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        assert "step" in stats["text_renamed"]

    def test_removes_type_without_text_field(self, tmp_path: Path) -> None:
        """Should remove type: field even without text: field."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("type: rule\nother: value\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        assert stats["types_removed"] == 1

    def test_renames_items_to_rules_based_on_context(self, tmp_path: Path) -> None:
        """Should rename items: to rules: when context contains 'rule'."""
        yaml_file = tmp_path / "test.yml"
        # Need extra line before title so range includes line 0
        yaml_file.write_text("section: test\ntitle: Coding Rules\nitems:\n  - item1\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        assert stats["items_renamed"] == 1

        content = yaml_file.read_text()
        assert "rules:" in content
        assert "items:" not in content

    def test_renames_items_to_anti_patterns_based_on_context(self, tmp_path: Path) -> None:
        """Should rename items: to anti_patterns: when context contains 'anti'."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("section: test\ncategory: Anti-patterns\nitems:\n  - bad practice\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        assert stats["items_renamed"] == 1

        content = yaml_file.read_text()
        assert "anti_patterns:" in content

    def test_renames_items_to_notes_based_on_context(self, tmp_path: Path) -> None:
        """Should rename items: to notes: when context contains 'note'."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("section: test\ntitle: Important Notes\nitems:\n  - note1\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        content = yaml_file.read_text()
        assert "notes:" in content

    def test_renames_items_to_steps_based_on_context(self, tmp_path: Path) -> None:
        """Should rename items: to steps: when context contains 'step'."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("section: test\ntitle: Setup Steps\nitems:\n  - step1\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        content = yaml_file.read_text()
        assert "steps:" in content

    def test_renames_items_to_examples_based_on_context(self, tmp_path: Path) -> None:
        """Should rename items: to examples: when context contains 'example'."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("section: test\ntitle: Usage Examples\nitems:\n  - example1\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        content = yaml_file.read_text()
        assert "examples:" in content

    def test_renames_items_with_category_context(self, tmp_path: Path) -> None:
        """Should use category field for context detection."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("section: test\ncategory: Standard Rules\nitems:\n  - rule1\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        content = yaml_file.read_text()
        assert "rules:" in content

    def test_keeps_items_without_context(self, tmp_path: Path) -> None:
        """Should keep items: when no context for semantic name."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("items:\n  - item1\n")

        _changed, stats = process_yaml_file(yaml_file)

        # No context found, items: stays unchanged
        assert stats["items_renamed"] == 0

    def test_adds_id_to_item_without_id(self, tmp_path: Path) -> None:
        """Should add ID to items without id field."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("- name: Item 1\n  value: test\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        assert stats["ids_added"] == 1

        content = yaml_file.read_text()
        assert "id:" in content

    def test_does_not_add_id_when_already_present(self, tmp_path: Path) -> None:
        """Should not add ID when item already has id field."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("- name: Item 1\n  id: existing-id\n")

        _changed, stats = process_yaml_file(yaml_file)

        # ID already present, nothing to add
        assert stats["ids_added"] == 0

    def test_uses_parent_id_for_new_id(self, tmp_path: Path) -> None:
        """Should use parent section ID as prefix for new ID."""
        yaml_file = tmp_path / "test.yml"
        # Need extra lines so the parent id is within the lookup range
        yaml_file.write_text(
            "dummy: value\nid: parent-section\nchildren:\n  - name: Child 1\n    value: test\n"
        )

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        content = yaml_file.read_text()
        # New ID should start with parent-section
        assert "parent-section." in content

    def test_handles_warning_context_for_anti_patterns(self, tmp_path: Path) -> None:
        """Should rename items: to anti_patterns: when context contains 'warning'."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("section: test\ntitle: Warnings and Pitfalls\nitems:\n  - pitfall1\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        content = yaml_file.read_text()
        assert "anti_patterns:" in content

    def test_handles_none_lines_in_processing(self, tmp_path: Path) -> None:
        """Should properly handle None lines during processing."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("type: rule\ntext: Rule content\ntype: note\ntext: Note content\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        assert stats["types_removed"] == 2

    def test_type_with_indented_text_field(self, tmp_path: Path) -> None:
        """Should handle type and text at same indent level."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("  type: definition\n  text: Definition content\n")

        changed, _stats = process_yaml_file(yaml_file)

        assert changed is True
        assert "definition" in stats["text_renamed"]


class TestMain:
    """Tests for main entry point function."""

    def test_returns_error_with_no_arguments(self) -> None:
        """Should return 1 when no file arguments provided."""
        with mock.patch("sys.argv", ["naturalize_yaml.py"]), mock.patch(
            "sys.stdout", new_callable=StringIO
        ) as mock_stdout:
            result = main()

        assert result == 1
        assert "Usage:" in mock_stdout.getvalue()

    def test_handles_nonexistent_file(self) -> None:
        """Should print error for nonexistent file and continue."""
        with mock.patch("sys.argv", ["prog", "/nonexistent/file.yml"]), mock.patch(
            "sys.stderr", new_callable=StringIO
        ) as mock_stderr, mock.patch("sys.stdout", new_callable=StringIO):
            result = main()

        assert result == 0
        assert "Error: File not found" in mock_stderr.getvalue()

    def test_processes_single_file(self, tmp_path: Path) -> None:
        """Should process a single file successfully."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("key: value\n")

        with mock.patch("sys.argv", ["prog", str(yaml_file)]), mock.patch(
            "sys.stdout", new_callable=StringIO
        ) as mock_stdout:
            result = main()

        assert result == 0
        output = mock_stdout.getvalue()
        assert "Total Summary" in output

    def test_processes_multiple_files(self, tmp_path: Path) -> None:
        """Should process multiple files."""
        file1 = tmp_path / "test1.yml"
        file2 = tmp_path / "test2.yml"
        file1.write_text("type: rule\ntext: Rule 1\n")
        file2.write_text("type: note\ntext: Note 1\n")

        with mock.patch("sys.argv", ["prog", str(file1), str(file2)]), mock.patch(
            "sys.stdout", new_callable=StringIO
        ) as mock_stdout:
            result = main()

        assert result == 0
        output = mock_stdout.getvalue()
        assert "Files changed:" in output

    def test_reports_changed_file_stats(self, tmp_path: Path) -> None:
        """Should report statistics for changed files."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("type: rule\ntext: Rule content\n")

        with mock.patch("sys.argv", ["prog", str(yaml_file)]), mock.patch(
            "sys.stdout", new_callable=StringIO
        ) as mock_stdout:
            result = main()

        assert result == 0
        output = mock_stdout.getvalue()
        assert "File:" in output
        assert "Removed" in output

    def test_reports_text_renames(self, tmp_path: Path) -> None:
        """Should report text->semantic renames."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("type: rule\ntext: Rule content\n")

        with mock.patch("sys.argv", ["prog", str(yaml_file)]), mock.patch(
            "sys.stdout", new_callable=StringIO
        ) as mock_stdout:
            main()

        output = mock_stdout.getvalue()
        assert "text" in output.lower() or "semantic" in output.lower()

    def test_reports_items_renames(self, tmp_path: Path) -> None:
        """Should report items->collection renames."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("title: Rules\nitems:\n  - item1\n")

        with mock.patch("sys.argv", ["prog", str(yaml_file)]), mock.patch(
            "sys.stdout", new_callable=StringIO
        ) as mock_stdout:
            main()

        output = mock_stdout.getvalue()
        assert "collection" in output.lower() or "items" in output.lower()

    def test_reports_ids_added(self, tmp_path: Path) -> None:
        """Should report IDs added."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("- name: Item 1\n  value: test\n")

        with mock.patch("sys.argv", ["prog", str(yaml_file)]), mock.patch(
            "sys.stdout", new_callable=StringIO
        ) as mock_stdout:
            main()

        output = mock_stdout.getvalue()
        assert "IDs added" in output

    def test_handles_processing_exception(self, tmp_path: Path) -> None:
        """Should handle exceptions during file processing."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("key: value\n")

        with mock.patch("sys.argv", ["prog", str(yaml_file)]), mock.patch(
            "scripts.naturalize_yaml.process_yaml_file", side_effect=ValueError("Test error")
        ), mock.patch("sys.stderr", new_callable=StringIO) as mock_stderr, mock.patch(
            "sys.stdout", new_callable=StringIO
        ):
            result = main()

        assert result == 0  # Continues despite errors
        assert "Error processing" in mock_stderr.getvalue()

    def test_accumulates_text_renamed_across_files(self, tmp_path: Path) -> None:
        """Should accumulate text_renamed stats across multiple files."""
        file1 = tmp_path / "test1.yml"
        file2 = tmp_path / "test2.yml"
        file1.write_text("type: rule\ntext: Rule 1\n")
        file2.write_text("type: rule\ntext: Rule 2\n")

        with mock.patch("sys.argv", ["prog", str(file1), str(file2)]), mock.patch(
            "sys.stdout", new_callable=StringIO
        ) as mock_stdout:
            result = main()

        assert result == 0
        output = mock_stdout.getvalue()
        # Should show total stats
        assert "Total" in output

    def test_reports_total_summary(self, tmp_path: Path) -> None:
        """Should print total summary at the end."""
        yaml_file = tmp_path / "test.yml"
        yaml_file.write_text("key: value\n")

        with mock.patch("sys.argv", ["prog", str(yaml_file)]), mock.patch(
            "sys.stdout", new_callable=StringIO
        ) as mock_stdout:
            main()

        output = mock_stdout.getvalue()
        assert "Total Summary" in output
        assert "Files changed:" in output
        assert "Total type fields removed:" in output
        assert "Total text" in output
        assert "Total items" in output
        assert "Total IDs added:" in output
