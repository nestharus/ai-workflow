"""Tests for scripts.create_breakdown_table module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts import create_breakdown_table
from scripts.create_breakdown_table import (
    IdEntry,
    _determine_element_type,
    _extract_text_content,
    _has_explicit_id,
    classify_id,
    extract_all_ids,
    generate_markdown_table,
    main,
    parse_args,
    truncate_text,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestTruncateText:
    """Tests for truncate_text function."""

    def test_returns_short_text_unchanged(self) -> None:
        """Should return short text unchanged."""
        result = truncate_text("short", max_length=50)
        assert result == "short"

    def test_truncates_long_text(self) -> None:
        """Should truncate long text with ellipsis."""
        long_text = "a" * 100
        result = truncate_text(long_text, max_length=50)

        assert len(result) == 50
        assert result.endswith("...")

    def test_handles_exact_length(self) -> None:
        """Should return text unchanged when exactly at max length."""
        text = "a" * 50
        result = truncate_text(text, max_length=50)
        assert result == text


class TestClassifyId:
    """Tests for classify_id function."""

    def test_classifies_project_keywords(self) -> None:
        """Should classify as PROJECT when text contains project keywords."""
        entry = IdEntry(
            id="item-1",
            text="Use FastAPI response_model for validation",
            section="section-1",
            element_type="item",
        )

        classification, rationale = classify_id(entry)

        assert classification == "PROJECT"
        assert "FastAPI" in rationale or "framework" in rationale.lower()

    def test_classifies_general_protocol(self) -> None:
        """Should classify as GENERAL for pure protocol content."""
        entry = IdEntry(
            id="item-1",
            text="Use HTTP 200 status code for successful GET requests",
            section="section-1",
            element_type="item",
        )

        classification, rationale = classify_id(entry)

        assert classification == "GENERAL"

    def test_classifies_mixed_content(self) -> None:
        """Should classify as MIXED when both protocol and project refs."""
        entry = IdEntry(
            id="item-1",
            text="Use HTTP 200 status code with FastAPI response_model",
            section="section-1",
            element_type="item",
        )

        classification, rationale = classify_id(entry)

        assert classification == "MIXED→split"

    def test_classifies_park_for_code_blocks(self) -> None:
        """Should classify as PARK for code block element types."""
        entry = IdEntry(
            id="item-1",
            text="Some code example",
            section="section-1",
            element_type="block",
        )

        classification, rationale = classify_id(entry)

        assert classification == "PARK"


class TestExtractAllIds:
    """Tests for extract_all_ids function."""

    def test_extracts_from_dict_with_id(self) -> None:
        """Should extract ID from dict with id field."""
        data = {
            "doc_id": "test",
            "sections": [
                {"id": "section-1", "text": "Section text"}
            ]
        }

        entries = extract_all_ids(data)

        ids = [e["id"] for e in entries]
        assert "section-1" in ids

    def test_extracts_from_nested_items(self) -> None:
        """Should extract IDs from nested items."""
        data = {
            "sections": [
                {
                    "id": "section-1",
                    "items": [
                        {"id": "item-1", "text": "Item 1"},
                        {"id": "item-2", "text": "Item 2"},
                    ]
                }
            ]
        }

        entries = extract_all_ids(data)

        ids = [e["id"] for e in entries]
        assert "item-1" in ids
        assert "item-2" in ids

    def test_extracts_from_list(self) -> None:
        """Should extract IDs from list structure."""
        data = [
            {"id": "item-1", "text": "Text 1"},
            {"id": "item-2", "text": "Text 2"},
        ]

        entries = extract_all_ids(data)

        ids = [e["id"] for e in entries]
        assert "item-1" in ids
        assert "item-2" in ids


class TestGenerateMarkdownTable:
    """Tests for generate_markdown_table function."""

    def test_generates_header(self) -> None:
        """Should generate header section."""
        entries = [
            IdEntry(
                id="item-1",
                text="Test text",
                section="section-1",
                element_type="item",
            )
        ]

        markdown = generate_markdown_table(entries, Path("test.yml"), auto_classify=False)

        assert "# ID Breakdown Table" in markdown
        assert "Classification Legend" in markdown

    def test_generates_table_rows(self) -> None:
        """Should generate table rows for entries."""
        entries = [
            IdEntry(
                id="item-1",
                text="Test text",
                section="section-1",
                element_type="item",
            )
        ]

        markdown = generate_markdown_table(entries, Path("test.yml"), auto_classify=False)

        assert "| item-1 |" in markdown

    def test_includes_classifications_when_auto_classify(self) -> None:
        """Should include classifications when auto_classify is True."""
        entries = [
            IdEntry(
                id="item-1",
                text="Use HTTP 200 status code",
                section="section-1",
                element_type="item",
            )
        ]

        markdown = generate_markdown_table(entries, Path("test.yml"), auto_classify=True)

        # Should have classification in the table
        assert "GENERAL" in markdown or "PROJECT" in markdown or "MIXED" in markdown

    def test_includes_summary_counts(self) -> None:
        """Should include summary counts section."""
        entries = [
            IdEntry(
                id="item-1",
                text="Test text",
                section="section-1",
                element_type="item",
            )
        ]

        markdown = generate_markdown_table(entries, Path("test.yml"), auto_classify=True)

        assert "Summary Counts" in markdown
        assert "Total IDs:" in markdown


class TestParseArgs:
    """Tests for parse_args function."""

    def test_requires_original_file(self) -> None:
        """Should require --original-file argument."""
        with pytest.raises(SystemExit):
            parse_args(["--output", "output.md"])

    def test_requires_output(self) -> None:
        """Should require --output argument."""
        with pytest.raises(SystemExit):
            parse_args(["--original-file", "test.yml"])

    def test_parses_all_arguments(self) -> None:
        """Should parse all arguments correctly."""
        args = parse_args([
            "--original-file", "/path/to/original.yml",
            "--output", "/path/to/output.md",
            "--auto-classify",
        ])

        assert args.original_file == Path("/path/to/original.yml")
        assert args.output == Path("/path/to/output.md")
        assert args.auto_classify is True


class TestMain:
    """Tests for main function."""

    def test_returns_one_for_missing_file(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when original file doesn't exist."""
        with patch.object(create_breakdown_table, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            with patch(
                "sys.argv",
                ["script", "--original-file", "missing.yml", "--output", "out.md"],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_one_for_non_dict_yaml(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when YAML root is not a dict."""
        with patch.object(create_breakdown_table, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/test.yml", contents="- item1\n- item2\n")

            with patch(
                "sys.argv",
                ["script", "--original-file", "test.yml", "--output", "out.md"],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "dictionary" in captured.err

    def test_returns_zero_on_success(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 0 and generate output on success."""
        with patch.object(create_breakdown_table, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            yaml_content = """
doc_id: test
sections:
  - id: section-1
    items:
      - id: item-1
        text: Test item
"""
            fs.create_file("/fake/test.yml", contents=yaml_content)

            with patch(
                "sys.argv",
                ["script", "--original-file", "test.yml", "--output", "out.md"],
            ):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Generated breakdown table" in captured.out


class TestExtractTextContent:
    """Tests for _extract_text_content function."""

    def test_extracts_text_from_fields(self) -> None:
        """Should extract text from text fields."""
        element = {"text": "Hello", "description": "World"}
        result = _extract_text_content(element)

        assert "Hello" in result
        assert "World" in result

    def test_handles_non_string_values(self) -> None:
        """Should skip non-string values in text fields."""
        element = {"text": 123, "description": "Valid"}
        result = _extract_text_content(element)

        assert "Valid" in result
        assert "123" not in result


class TestDetermineElementType:
    """Tests for _determine_element_type function."""

    def test_returns_table_for_defaults(self) -> None:
        """Should return 'table' for keys with 'defaults'."""
        result = _determine_element_type("http_method_defaults", {})
        assert result == "table"

    def test_returns_fields_for_fields_key(self) -> None:
        """Should return 'fields' for keys containing 'fields'."""
        result = _determine_element_type("query_fields", {})
        assert result == "fields"

    def test_returns_hints_for_hints_key(self) -> None:
        """Should return 'hints' for keys containing 'hints'."""
        result = _determine_element_type("type_hints", {})
        assert result == "hints"

    def test_returns_block_for_sample_key(self) -> None:
        """Should return 'block' for keys containing 'sample' or 'code'."""
        assert _determine_element_type("sample_code", {}) == "block"
        assert _determine_element_type("code_example", {}) == "block"

    def test_returns_table_for_list_value(self) -> None:
        """Should return 'table' for list values."""
        result = _determine_element_type("items", ["a", "b"])
        assert result == "table"

    def test_returns_item_for_other(self) -> None:
        """Should return 'item' for other keys."""
        result = _determine_element_type("regular_key", {})
        assert result == "item"


class TestHasExplicitId:
    """Tests for _has_explicit_id function."""

    def test_returns_true_for_dict_with_id(self) -> None:
        """Should return True when dict has 'id' field."""
        assert _has_explicit_id({"id": "test"}) is True

    def test_returns_true_for_list_with_id_in_item(self) -> None:
        """Should return True when list has item with 'id'."""
        assert _has_explicit_id([{"id": "test"}, {"other": "val"}]) is True

    def test_returns_false_for_dict_without_id(self) -> None:
        """Should return False when dict has no 'id'."""
        assert _has_explicit_id({"other": "val"}) is False

    def test_returns_false_for_list_without_ids(self) -> None:
        """Should return False when no list items have 'id'."""
        assert _has_explicit_id([{"other": "val"}]) is False

    def test_returns_false_for_other_types(self) -> None:
        """Should return False for non-dict/list types."""
        assert _has_explicit_id("string") is False


class TestExtractAllIdsExtended:
    """Extended tests for extract_all_ids function."""

    def test_creates_synthetic_ids_for_structural_elements(self) -> None:
        """Should create synthetic IDs for anonymous structural elements."""
        data = {
            "doc_id": "test",
            "http_method_defaults": [
                {"method": "GET", "cache": True},
                {"method": "POST", "cache": False},
            ],
        }

        entries = extract_all_ids(data)
        ids = [e["id"] for e in entries]

        # Should have synthetic ID for the table
        assert any("http_method_defaults" in id for id in ids)

    def test_skips_synthetic_for_explicit_ids(self) -> None:
        """Should not create synthetic ID when items have explicit IDs."""
        data = {
            "doc_id": "test",
            "sections": [
                {"id": "section-1", "text": "Text"},
            ],
        }

        entries = extract_all_ids(data)
        ids = [e["id"] for e in entries]

        # Should have explicit ID but no synthetic
        assert "section-1" in ids
        assert "(table) sections" not in ids

    def test_handles_dict_summary_for_synthetic(self) -> None:
        """Should extract dict field count for synthetic ID summary."""
        data = {
            "doc_id": "test",
            "config_fields": {
                "field1": "val1",
                "field2": "val2",
            },
        }

        entries = extract_all_ids(data)

        # Find the synthetic entry
        synthetic = [e for e in entries if "config_fields" in e["id"]]
        assert len(synthetic) > 0
        assert "fields" in synthetic[0]["text"]

    def test_handles_string_summary_for_synthetic(self) -> None:
        """Should extract string preview for synthetic ID summary."""
        data = {
            "doc_id": "test",
            "sample_code": "def hello():\n    print('Hello')\n" * 10,
        }

        entries = extract_all_ids(data)

        synthetic = [e for e in entries if "sample_code" in e["id"]]
        assert len(synthetic) > 0
        # Long text should be truncated
        assert len(synthetic[0]["text"]) <= 53

    def test_recurses_into_nested_dicts(self) -> None:
        """Should recurse into nested dict values."""
        data = {
            "doc_id": "test",
            "config": {
                "nested": {
                    "id": "nested-item",
                    "text": "Nested text",
                }
            }
        }

        entries = extract_all_ids(data)
        ids = [e["id"] for e in entries]

        assert "nested-item" in ids

    def test_handles_non_string_doc_id(self) -> None:
        """Should handle non-string doc_id gracefully."""
        data = {
            "doc_id": 123,  # Non-string
            "sections": [
                {"id": "section-1", "text": "Text"},
            ],
        }

        entries = extract_all_ids(data)
        ids = [e["id"] for e in entries]

        assert "section-1" in ids


class TestClassifyIdExtended:
    """Extended tests for classify_id function."""

    def test_classifies_park_for_hints_type(self) -> None:
        """Should classify as PARK for hints element type."""
        entry = IdEntry(
            id="type-hints",
            text="Type hints content",
            section="section-1",
            element_type="hints",
        )

        classification, _ = classify_id(entry)
        assert classification == "PARK"

    def test_classifies_park_for_park_keywords(self) -> None:
        """Should classify as PARK when ID contains PARK keywords."""
        entry = IdEntry(
            id="sample_code_example",
            text="Some example code",
            section="section-1",
            element_type="item",
        )

        classification, _ = classify_id(entry)
        assert classification == "PARK"

    def test_defaults_to_general(self) -> None:
        """Should default to GENERAL when no indicators found."""
        entry = IdEntry(
            id="generic-item",
            text="Some generic text without keywords",
            section="section-1",
            element_type="item",
        )

        classification, rationale = classify_id(entry)
        assert classification == "GENERAL"
        assert "No framework references" in rationale


class TestGenerateMarkdownTableExtended:
    """Extended tests for generate_markdown_table function."""

    def test_generates_project_target(self) -> None:
        """Should generate PROJECT target for PROJECT classification."""
        entries = [
            IdEntry(
                id="item-1",
                text="Use FastAPI response_model for validation",
                section="section-1",
                element_type="item",
            )
        ]

        markdown = generate_markdown_table(entries, Path("test.yml"), auto_classify=True)

        assert "PROJECT" in markdown

    def test_generates_park_target(self) -> None:
        """Should generate N/A target for PARK classification."""
        entries = [
            IdEntry(
                id="item-1",
                text="Code sample",
                section="section-1",
                element_type="block",
            )
        ]

        markdown = generate_markdown_table(entries, Path("test.yml"), auto_classify=True)

        assert "PARK" in markdown
        assert "N/A" in markdown

    def test_generates_both_target_for_mixed(self) -> None:
        """Should generate Both target for MIXED classification."""
        entries = [
            IdEntry(
                id="item-1",
                text="Use HTTP 200 with FastAPI response_model",
                section="section-1",
                element_type="item",
            )
        ]

        markdown = generate_markdown_table(entries, Path("test.yml"), auto_classify=True)

        assert "MIXED→split" in markdown
        assert "Both" in markdown


class TestMainExtended:
    """Extended tests for main function."""

    def test_handles_absolute_paths(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should handle absolute paths correctly."""
        with patch.object(create_breakdown_table, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/absolute")
            yaml_content = """
doc_id: test
sections:
  - id: section-1
    text: Test
"""
            fs.create_file("/absolute/test.yml", contents=yaml_content)

            with patch(
                "sys.argv",
                ["script", "--original-file", "/absolute/test.yml", "--output", "/absolute/out.md"],
            ):
                result = main()

        assert result == 0

    def test_handles_yaml_parse_error(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 on YAML parse error."""
        with patch.object(create_breakdown_table, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/bad.yml", contents="invalid: yaml: content: [[[")

            with patch(
                "sys.argv",
                ["script", "--original-file", "bad.yml", "--output", "out.md"],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err

    def test_warns_for_no_entries(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should warn when no IDs found."""
        with patch.object(create_breakdown_table, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/empty.yml", contents="simple: value\n")

            with patch(
                "sys.argv",
                ["script", "--original-file", "empty.yml", "--output", "out.md"],
            ):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Warning" in captured.err or "No IDs" in captured.err

    def test_handles_path_outside_repo_root(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should handle paths outside REPO_ROOT gracefully."""
        with patch.object(create_breakdown_table, "REPO_ROOT", Path("/repo")):
            fs.create_dir("/repo")
            fs.create_dir("/outside")
            yaml_content = """
doc_id: test
sections:
  - id: section-1
    text: Test
"""
            fs.create_file("/outside/test.yml", contents=yaml_content)

            with patch(
                "sys.argv",
                ["script", "--original-file", "/outside/test.yml", "--output", "/outside/out.md"],
            ):
                result = main()

        assert result == 0
