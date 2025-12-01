"""Tests for scripts.rebuild_from_breakdown module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts import rebuild_from_breakdown
from scripts.rebuild_from_breakdown import (
    ClassificationEntry,
    load_variants_file,
    main,
    merge_variants,
    parse_args,
    parse_breakdown_table,
    rebuild_file,
    strip_project_refs,
    write_yaml_file,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestStripProjectRefs:
    """Tests for strip_project_refs function."""

    def test_strips_app_paths(self) -> None:
        """Should strip app/* path references."""
        text = "Use the endpoint in app/api/routes.py for handling"
        result = strip_project_refs(text)

        assert "app/api/routes.py" not in result

    def test_strips_fastapi_refs(self) -> None:
        """Should strip FastAPI references."""
        text = "Use FastAPI dependency injection"
        result = strip_project_refs(text)

        assert "FastAPI" not in result

    def test_strips_pydantic_refs(self) -> None:
        """Should strip Pydantic references."""
        text = "Use Pydantic BaseModel for validation"
        result = strip_project_refs(text)

        assert "Pydantic" not in result

    def test_cleans_extra_whitespace(self) -> None:
        """Should clean up extra whitespace after stripping."""
        text = "Use   FastAPI   for routing"
        result = strip_project_refs(text)

        assert "  " not in result


class TestParseBreakdownTable:
    """Tests for parse_breakdown_table function."""

    def test_extracts_classifications(self, fs: FakeFilesystem) -> None:
        """Should extract classifications from markdown table."""
        content = """
# ID Breakdown Table

| ID | Original Text Summary | Classification | Rationale | Target |
|----|----------------------|----------------|-----------|--------|
| item-1 | Some text | GENERAL | Protocol rule | GENERAL |
| item-2 | Other text | PROJECT | Framework specific | PROJECT |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        assert result["item-1"]["classification"] == "GENERAL"
        assert result["item-2"]["classification"] == "PROJECT"

    def test_handles_mixed_split(self, fs: FakeFilesystem) -> None:
        """Should handle MIXED→split classification."""
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | MIXED→split | Both refs | Both |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        assert result["item-1"]["classification"] == "MIXED→split"

    def test_handles_structural_elements(self, fs: FakeFilesystem) -> None:
        """Should extract ID from structural element notation."""
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| (table) http_defaults | Data | PARK | Structural | N/A |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        assert "http_defaults" in result

    def test_warns_on_malformed_rows(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should warn on rows with too few columns."""
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | col2 | col3 |
| item-2 | Text | GENERAL | Protocol | GENERAL |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        captured = capsys.readouterr()
        assert "Warning: Line" in captured.err
        assert result["item-2"]["classification"] == "GENERAL"

    def test_skips_invalid_classifications(self, fs: FakeFilesystem) -> None:
        """Should skip rows with invalid classifications."""
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | INVALID | Bad | None |
| item-2 | Text | GENERAL | Good | GENERAL |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        assert "item-1" not in result
        assert result["item-2"]["classification"] == "GENERAL"

    def test_extracts_extended_format(self, fs: FakeFilesystem) -> None:
        """Should extract text variants from extended format."""
        content = """
| ID | Summary | Classification | Rationale | Target | GENERAL TEXT | PROJECT TEXT |
|----|---------|----------------|-----------|--------|--------------|--------------|
| item-1 | Text | MIXED→split | Both | Both | General text | Project text |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        assert result["item-1"]["general_text"] == "General text"
        assert result["item-1"]["project_text"] == "Project text"

    def test_skips_empty_element_id(self, fs: FakeFilesystem) -> None:
        """Should skip rows with empty element ID."""
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
|  | Text | GENERAL | Protocol | GENERAL |
| item-2 | Text | GENERAL | Protocol | GENERAL |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        assert len(result) == 1
        assert "item-2" in result


class TestLoadVariantsFile:
    """Tests for load_variants_file function."""

    def test_returns_empty_for_missing_file(self, fs: FakeFilesystem) -> None:
        """Should return empty dict when file doesn't exist."""
        result = load_variants_file(Path("/nonexistent.yml"))
        assert result == {}

    def test_loads_variants(self, fs: FakeFilesystem) -> None:
        """Should load variants from YAML file."""
        content = """
item-1:
  general_text: "General version"
  project_text: "Project version"
"""
        fs.create_file("/variants.yml", contents=content)

        result = load_variants_file(Path("/variants.yml"))

        assert "item-1" in result
        assert result["item-1"]["general_text"] == "General version"
        assert result["item-1"]["project_text"] == "Project version"

    def test_returns_empty_for_invalid_yaml(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return empty dict on invalid YAML."""
        fs.create_file("/variants.yml", contents="invalid: yaml: content:")

        result = load_variants_file(Path("/variants.yml"))

        assert result == {}
        captured = capsys.readouterr()
        assert "Warning" in captured.err

    def test_returns_empty_for_non_dict_yaml(self, fs: FakeFilesystem) -> None:
        """Should return empty dict when YAML is not a dict."""
        fs.create_file("/variants.yml", contents="- item1\n- item2")

        result = load_variants_file(Path("/variants.yml"))

        assert result == {}

    def test_skips_invalid_entries(self, fs: FakeFilesystem) -> None:
        """Should skip entries with invalid structure."""
        content = """
item-1:
  general_text: "Valid"
123:
  general_text: "Invalid key type"
item-3: "Invalid value type"
"""
        fs.create_file("/variants.yml", contents=content)

        result = load_variants_file(Path("/variants.yml"))

        assert "item-1" in result


class TestMergeVariants:
    """Tests for merge_variants function."""

    def test_merges_variants(self) -> None:
        """Should merge variants into classifications."""
        classifications = {
            "item-1": {"classification": "MIXED→split", "general_text": None, "project_text": None}
        }
        variants = {
            "item-1": {
                "classification": "MIXED→split",
                "general_text": "Gen",
                "project_text": "Proj",
            }
        }

        result = merge_variants(classifications, variants)  # type: ignore[arg-type]

        assert result["item-1"]["general_text"] == "Gen"
        assert result["item-1"]["project_text"] == "Proj"


class TestRebuildFile:
    """Tests for rebuild_file function."""

    def test_sets_general_doc_id(self) -> None:
        """Should set general doc_id for GENERAL target."""
        data = {"doc_id": "project.api-patterns", "sections": []}
        classifications: dict[str, ClassificationEntry] = {}

        result = rebuild_file(data, classifications, "GENERAL", Path("general.yml"))  # type: ignore[arg-type]

        assert "general" in result["doc_id"]  # type: ignore[operator]

    def test_sets_project_doc_id(self) -> None:
        """Should set project doc_id for PROJECT target."""
        data = {"doc_id": "general.api-patterns", "sections": []}
        classifications: dict[str, ClassificationEntry] = {}

        result = rebuild_file(data, classifications, "PROJECT", Path("project.yml"))  # type: ignore[arg-type]

        assert "project" in result["doc_id"]  # type: ignore[operator]

    def test_excludes_parked_items(self) -> None:
        """Should exclude items classified as PARK."""
        data = {
            "doc_id": "test",
            "sections": [
                {
                    "id": "section-1",
                    "items": [
                        {"id": "item-1", "text": "Keep this"},
                        {"id": "item-2", "text": "Park this"},
                    ],
                }
            ],
        }
        # Classifications use ClassificationEntry dict structure
        classifications = {
            "item-2": {"classification": "PARK", "general_text": None, "project_text": None}
        }

        result = rebuild_file(data, classifications, "GENERAL", Path("general.yml"))  # type: ignore[arg-type]

        # The structure should not include item-2
        if "sections" in result:
            for section in result["sections"]:  # type: ignore[union-attr]
                if "items" in section:  # type: ignore[operator]
                    ids = [item["id"] for item in section["items"]]  # type: ignore[union-attr,index,call-overload]
                    assert "item-2" not in ids


class TestWriteYamlFile:
    """Tests for write_yaml_file function."""

    def test_creates_yaml_file(self, fs: FakeFilesystem) -> None:
        """Should create YAML file with data."""
        data = {"key": "value", "list": [1, 2, 3]}
        output_path = Path("/output/test.yml")

        write_yaml_file(data, output_path)  # type: ignore[arg-type]

        assert output_path.exists()
        content = output_path.read_text()
        assert "key: value" in content

    def test_creates_parent_directories(self, fs: FakeFilesystem) -> None:
        """Should create parent directories if needed."""
        data = {"key": "value"}
        output_path = Path("/nested/deep/path/test.yml")

        write_yaml_file(data, output_path)  # type: ignore[arg-type]

        assert output_path.parent.exists()


class TestParseArgs:
    """Tests for parse_args function."""

    def test_requires_all_arguments(self) -> None:
        """Should require all mandatory arguments."""
        with pytest.raises(SystemExit):
            parse_args([])

    def test_parses_all_arguments(self) -> None:
        """Should parse all arguments correctly."""
        args = parse_args(
            [
                "--breakdown-table",
                "/table.md",
                "--original-file",
                "/original.yml",
                "--general-output",
                "/general.yml",
                "--project-output",
                "/project.yml",
            ]
        )

        assert args.breakdown_table == Path("/table.md")
        assert args.original_file == Path("/original.yml")
        assert args.general_output == Path("/general.yml")
        assert args.project_output == Path("/project.yml")


class TestMain:
    """Tests for main function."""

    def test_returns_one_for_missing_breakdown(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when breakdown table doesn't exist."""
        with patch.object(rebuild_from_breakdown, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table",
                    "missing.md",
                    "--original-file",
                    "original.yml",
                    "--general-output",
                    "general.yml",
                    "--project-output",
                    "project.yml",
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_one_for_missing_original(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when original file doesn't exist."""
        with patch.object(rebuild_from_breakdown, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file(
                "/fake/table.md", contents="| ID | Summary | Classification | Rationale | Target |"
            )

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table",
                    "table.md",
                    "--original-file",
                    "missing.yml",
                    "--general-output",
                    "general.yml",
                    "--project-output",
                    "project.yml",
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_zero_on_success(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 and generate files on success."""
        with patch.object(rebuild_from_breakdown, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            table_content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | GENERAL | Protocol | GENERAL |
"""
            fs.create_file("/fake/table.md", contents=table_content)

            yaml_content = """
doc_id: test
sections:
  - id: section-1
    items:
      - id: item-1
        text: Test item
"""
            fs.create_file("/fake/original.yml", contents=yaml_content)

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table",
                    "table.md",
                    "--original-file",
                    "original.yml",
                    "--general-output",
                    "general.yml",
                    "--project-output",
                    "project.yml",
                ],
            ):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Wrote GENERAL file" in captured.out
        assert "Wrote PROJECT file" in captured.out

    def test_handles_absolute_paths(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should handle absolute paths for all arguments."""
        with patch.object(rebuild_from_breakdown, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_dir("/abs_path")

            table_content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | GENERAL | Protocol | GENERAL |
"""
            fs.create_file("/abs_path/table.md", contents=table_content)

            yaml_content = """
doc_id: test
sections: []
"""
            fs.create_file("/abs_path/original.yml", contents=yaml_content)

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table",
                    "/abs_path/table.md",
                    "--original-file",
                    "/abs_path/original.yml",
                    "--general-output",
                    "/abs_path/general.yml",
                    "--project-output",
                    "/abs_path/project.yml",
                ],
            ):
                result = main()

        assert result == 0

    def test_warns_on_empty_classifications(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should warn when no classifications found."""
        with patch.object(rebuild_from_breakdown, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            # Empty table with just header
            table_content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
"""
            fs.create_file("/fake/table.md", contents=table_content)

            yaml_content = """
doc_id: test
sections: []
"""
            fs.create_file("/fake/original.yml", contents=yaml_content)

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table",
                    "table.md",
                    "--original-file",
                    "original.yml",
                    "--general-output",
                    "general.yml",
                    "--project-output",
                    "project.yml",
                ],
            ):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "No classifications found" in captured.err

    def test_loads_variants_file(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should load and merge variants file."""
        with patch.object(rebuild_from_breakdown, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            table_content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | MIXED→split | Both | Both |
"""
            fs.create_file("/fake/table.md", contents=table_content)

            yaml_content = """
doc_id: test
sections:
  - id: section-1
    items:
      - id: item-1
        text: Original text
"""
            fs.create_file("/fake/original.yml", contents=yaml_content)

            variants_content = """
item-1:
  general_text: "General version"
  project_text: "Project version"
"""
            fs.create_file("/fake/variants.yml", contents=variants_content)

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table",
                    "table.md",
                    "--original-file",
                    "original.yml",
                    "--general-output",
                    "general.yml",
                    "--project-output",
                    "project.yml",
                    "--variants-file",
                    "variants.yml",
                ],
            ):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Merged" in captured.out
        assert "explicit text variant" in captured.out

    def test_returns_one_for_yaml_error(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when YAML parsing fails."""
        with patch.object(rebuild_from_breakdown, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            table_content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | GENERAL | Protocol | GENERAL |
"""
            fs.create_file("/fake/table.md", contents=table_content)
            fs.create_file("/fake/original.yml", contents="invalid: yaml: content:")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table",
                    "table.md",
                    "--original-file",
                    "original.yml",
                    "--general-output",
                    "general.yml",
                    "--project-output",
                    "project.yml",
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error parsing YAML" in captured.err

    def test_returns_one_for_non_dict_yaml(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when YAML is not a dictionary."""
        with patch.object(rebuild_from_breakdown, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            table_content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | GENERAL | Protocol | GENERAL |
"""
            fs.create_file("/fake/table.md", contents=table_content)
            fs.create_file("/fake/original.yml", contents="- item1\n- item2")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table",
                    "table.md",
                    "--original-file",
                    "original.yml",
                    "--general-output",
                    "general.yml",
                    "--project-output",
                    "project.yml",
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "dictionary" in captured.err
