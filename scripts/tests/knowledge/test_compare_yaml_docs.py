"""Tests for scripts.knowledge.compare_yaml_docs module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
import yaml

from scripts.knowledge import compare_yaml_docs
from scripts.knowledge.compare_yaml_docs import (
    CONTAINMENT_EDGE_COLUMNS,
    CSV_COLUMNS,
    ComparisonEntry,
    ContainmentEdge,
    SplitEntry,
    _flatten_entry_to_rows,
    _is_element,
    _slice_element,
    _strip_timestamp_prefix,
    _validate_yaml_result,
    aggregate_split_objects,
    compare_original_to_splits,
    extract_ids_and_objects,
    extract_ids_and_text,
    find_all_yml,
    find_mapped_splits,
    find_originals,
    get_ids_objects,
    main,
    parse_args,
    parse_yaml_file,
    pattern_from_path,
    write_compare_files,
    write_containment_edges,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_path(self) -> None:
        """Should use default development directory."""
        args = parse_args([])
        assert "development" in str(args.path)

    def test_custom_path(self) -> None:
        """Should accept custom path."""
        args = parse_args(["--path", "/custom/path"])
        assert args.path == Path("/custom/path")

    def test_original_files(self) -> None:
        """Should accept original-files argument."""
        args = parse_args(["--original-files", "/file1.yml", "/file2.yml"])
        assert len(args.original_files) == 2


class TestValidateYamlResult:
    """Tests for _validate_yaml_result function."""

    def test_accepts_dict(self) -> None:
        """Should accept dictionary result."""
        result = _validate_yaml_result({"key": "value"}, Path("/test.yml"))
        assert result == {"key": "value"}

    def test_accepts_list(self) -> None:
        """Should accept list result."""
        result = _validate_yaml_result([1, 2, 3], Path("/test.yml"))
        assert result == [1, 2, 3]

    def test_raises_for_string(self, fs: FakeFilesystem) -> None:
        """Should raise TypeError for string result."""
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            with pytest.raises(TypeError) as exc_info:
                _validate_yaml_result("string", Path("/fake/test.yml"))
            assert "expected dict or list" in str(exc_info.value)

    def test_raises_for_none(self, fs: FakeFilesystem) -> None:
        """Should raise TypeError for None result."""
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            with pytest.raises(TypeError):
                _validate_yaml_result(None, Path("/fake/test.yml"))


class TestParseYamlFile:
    """Tests for parse_yaml_file function."""

    def test_parses_valid_yaml(self, fs: FakeFilesystem) -> None:
        """Should parse valid YAML file."""
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/test.yml", contents="key: value\n")

            result = parse_yaml_file(Path("/fake/test.yml"))

            assert result == {"key": "value"}

    def test_raises_for_invalid_yaml(self, fs: FakeFilesystem) -> None:
        """Should raise YAMLError for invalid YAML."""
        fs.create_file("/test.yml", contents="invalid: yaml: content:")

        with pytest.raises(yaml.YAMLError):
            parse_yaml_file(Path("/test.yml"))

    def test_raises_for_missing_file(self) -> None:
        """Should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            parse_yaml_file(Path("/nonexistent.yml"))


class TestContainmentEdge:
    """Tests for ContainmentEdge dataclass."""

    def test_instantiation(self) -> None:
        """Should instantiate with all required fields."""
        edge = ContainmentEdge(
            parent_id="parent-1",
            child_id="child-1",
            field_path="items[0]",
            source_file="test.yml",
        )
        assert edge.parent_id == "parent-1"
        assert edge.child_id == "child-1"
        assert edge.field_path == "items[0]"
        assert edge.source_file == "test.yml"

    def test_field_access(self) -> None:
        """Should access all fields correctly."""
        edge = ContainmentEdge(
            parent_id="p",
            child_id="c",
            field_path="path",
            source_file="file.yml",
        )
        assert edge.parent_id == "p"
        assert edge.child_id == "c"
        assert edge.field_path == "path"
        assert edge.source_file == "file.yml"


class TestIsElement:
    """Tests for _is_element helper function."""

    def test_dict_with_string_id_is_element(self) -> None:
        """Should return True for dict with string id field."""
        assert _is_element({"id": "test", "text": "value"}) is True

    def test_dict_without_id_is_not_element(self) -> None:
        """Should return False for dict without id field."""
        assert _is_element({"text": "value"}) is False

    def test_dict_with_non_string_id_is_not_element(self) -> None:
        """Should return False for dict with non-string id."""
        assert _is_element({"id": 123}) is False

    def test_non_dict_is_not_element(self) -> None:
        """Should return False for non-dict values."""
        assert _is_element("string") is False
        assert _is_element(123) is False
        assert _is_element([{"id": "test"}]) is False
        assert _is_element(None) is False


class TestSliceElement:
    """Tests for _slice_element helper function."""

    def test_slices_simple_element_no_nested_ids(self) -> None:
        """Should return original data when no nested ID-bearing dicts."""
        data = {"id": "parent", "text": "content", "count": 5}
        edges: list[ContainmentEdge] = []
        result = _slice_element(data, "parent", "", "test.yml", edges)
        assert result == {"id": "parent", "text": "content", "count": 5}
        assert len(edges) == 0

    def test_slices_element_with_one_nested_id(self) -> None:
        """Should replace nested ID-bearing dict with $ref and emit edge."""
        data = {
            "id": "parent",
            "child": {"id": "child-1", "text": "child content"},
        }
        edges: list[ContainmentEdge] = []
        result = _slice_element(data, "parent", "", "test.yml", edges)

        assert result["id"] == "parent"
        assert result["child"] == {"$ref": "child-1"}
        assert len(edges) == 1
        assert edges[0].parent_id == "parent"
        assert edges[0].child_id == "child-1"
        assert edges[0].field_path == "child"
        assert edges[0].source_file == "test.yml"

    def test_slices_element_with_deeply_nested_ids(self) -> None:
        """Should handle multiple levels of nested ID-bearing dicts."""
        data = {
            "id": "root",
            "level1": {
                "id": "level1-id",
                "level2": {"id": "level2-id", "text": "deep"},
            },
        }
        edges: list[ContainmentEdge] = []
        result = _slice_element(data, "root", "", "test.yml", edges)

        # Only the first level should be replaced; nested processing stops
        assert result["level1"] == {"$ref": "level1-id"}
        assert len(edges) == 1
        assert edges[0].child_id == "level1-id"

    def test_slices_list_containing_id_bearing_dicts(self) -> None:
        """Should replace ID-bearing dicts in lists with $refs."""
        data = {
            "id": "parent",
            "items": [
                {"id": "item-1", "text": "Item 1"},
                {"text": "No ID"},
                {"id": "item-2", "text": "Item 2"},
            ],
        }
        edges: list[ContainmentEdge] = []
        result = _slice_element(data, "parent", "", "test.yml", edges)

        assert result["items"][0] == {"$ref": "item-1"}
        assert result["items"][1] == {"text": "No ID"}
        assert result["items"][2] == {"$ref": "item-2"}
        assert len(edges) == 2
        assert edges[0].field_path == "items[0]"
        assert edges[1].field_path == "items[2]"


class TestExtractIdsAndObjects:
    """Tests for extract_ids_and_objects function."""

    def test_extracts_from_dict(self) -> None:
        """Should extract IDs and sliced objects from dictionary structure."""
        data = {
            "id": "item-1",
            "text": "Item text",
            "category": "test",
        }
        result, edges = extract_ids_and_objects(data)  # type: ignore[arg-type]
        assert "item-1" in result
        assert result["item-1"] == {"id": "item-1", "text": "Item text", "category": "test"}
        assert len(edges) == 0

    def test_extracts_from_nested_dict(self) -> None:
        """Should extract IDs from nested dictionaries with slicing."""
        data = {
            "sections": {
                "id": "section-1",
                "text": "Section text",
            }
        }
        result, edges = extract_ids_and_objects(data)  # type: ignore[arg-type]
        assert "section-1" in result
        assert result["section-1"]["text"] == "Section text"

    def test_extracts_from_list(self) -> None:
        """Should extract IDs from list items."""
        data = [
            {"id": "item-1", "text": "Text 1"},
            {"id": "item-2", "text": "Text 2"},
        ]
        result, edges = extract_ids_and_objects(data)  # type: ignore[arg-type]
        assert "item-1" in result
        assert "item-2" in result

    def test_ignores_non_string_ids(self) -> None:
        """Should ignore non-string ID values."""
        data = {"id": 123, "text": "Text"}
        result, edges = extract_ids_and_objects(data)  # type: ignore[arg-type]
        assert len(result) == 0

    def test_nested_id_bearing_dict_emits_containment_edge(self) -> None:
        """Should emit ContainmentEdge for nested ID-bearing dicts."""
        data = {
            "id": "parent",
            "items": [{"id": "child-1", "text": "Child text"}],
        }
        result, edges = extract_ids_and_objects(
            data, source_file="test.yml"  # type: ignore[arg-type]
        )

        # Parent should have sliced representation
        assert "parent" in result
        assert result["parent"]["items"] == [{"$ref": "child-1"}]

        # Child should also be extracted
        assert "child-1" in result

        # Should have containment edge from parent to child
        parent_edges = [e for e in edges if e.parent_id == "parent"]
        assert len(parent_edges) == 1
        assert parent_edges[0].child_id == "child-1"


class TestExtractIdsAndText:
    """Tests for extract_ids_and_text function."""

    def test_simple_element_text_projection(self) -> None:
        """Should produce text projection for simple element."""
        data = {"id": "test", "text": "Hello", "count": 5}
        result = extract_ids_and_text(data)  # type: ignore[arg-type]
        assert "test" in result
        text = result["test"]
        assert "id=test" in text
        assert "text=Hello" in text
        assert "count=5" in text

    def test_element_with_ref_produces_ref_format(self) -> None:
        """Should produce $ref:child_id format for references."""
        data = {
            "id": "parent",
            "child": {"id": "child-1", "text": "nested"},
        }
        result = extract_ids_and_text(data)  # type: ignore[arg-type]
        text = result["parent"]
        assert "child=$ref:child-1" in text

    def test_element_with_lists(self) -> None:
        """Should format lists correctly in text projection."""
        data = {"id": "test", "items": ["a", "b", "c"]}
        result = extract_ids_and_text(data)  # type: ignore[arg-type]
        text = result["test"]
        assert "items=[a, b, c]" in text

    def test_deterministic_ordering(self) -> None:
        """Should produce deterministic output based on sorted keys."""
        data = {"id": "test", "z_field": "last", "a_field": "first"}
        result = extract_ids_and_text(data)  # type: ignore[arg-type]
        text = result["test"]
        lines = text.split("\n")
        # a_field should come before id which comes before z_field
        assert lines[0].startswith("a_field=")
        assert lines[1].startswith("id=")
        assert lines[2].startswith("z_field=")


class TestStripTimestampPrefix:
    """Tests for _strip_timestamp_prefix function."""

    def test_strips_timestamp(self) -> None:
        """Should strip ISO 8601 timestamp prefix."""
        result = _strip_timestamp_prefix("20251201T134735Z-api-patterns")
        assert result == "api-patterns"

    def test_returns_original_without_timestamp(self) -> None:
        """Should return original if no timestamp prefix."""
        result = _strip_timestamp_prefix("api-patterns")
        assert result == "api-patterns"


class TestPatternFromPath:
    """Tests for pattern_from_path function."""

    def test_extracts_from_original_file(self) -> None:
        """Should extract pattern from original.*.yml file."""
        result = pattern_from_path(Path("/docs/original.api-patterns.yml"))
        assert result == "api-patterns"

    def test_extracts_from_split_file(self) -> None:
        """Should extract pattern from split file."""
        result = pattern_from_path(Path("/docs/python/python.api-patterns.yml"))
        assert result == "api-patterns"

    def test_extracts_from_timestamped_file(self) -> None:
        """Should extract pattern from timestamped file."""
        result = pattern_from_path(Path("/docs/20251201T134735Z-api-patterns.yml"))
        assert result == "api-patterns"


class TestFindOriginals:
    """Tests for find_originals function."""

    def test_finds_original_files(self, fs: FakeFilesystem) -> None:
        """Should find original.*.yml files."""
        fs.create_dir("/docs")
        fs.create_file("/docs/original.api-patterns.yml", contents="")
        fs.create_file("/docs/original.other-patterns.yml", contents="")

        result = find_originals(Path("/docs"))

        assert len(result) == 2

    def test_uses_provided_original_files(self, fs: FakeFilesystem) -> None:
        """Should use provided original files instead of globbing."""
        fs.create_dir("/docs")
        fs.create_file("/docs/custom.yml", contents="")

        result = find_originals(Path("/docs"), [Path("/docs/custom.yml")])

        assert len(result) == 1
        assert result[0].name == "custom.yml"

    def test_filters_nonexistent_original_files(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should filter out non-existent provided files with warning."""
        fs.create_dir("/docs")
        fs.create_file("/docs/exists.yml", contents="")

        result = find_originals(
            Path("/docs"), [Path("/docs/exists.yml"), Path("/docs/missing.yml")]
        )

        assert len(result) == 1
        captured = capsys.readouterr()
        assert "does not exist" in captured.err


class TestFindAllYml:
    """Tests for find_all_yml function."""

    def test_finds_yml_in_subdirs(self, fs: FakeFilesystem) -> None:
        """Should find .yml files in configured subdirectories."""
        fs.create_dir("/docs/python")
        fs.create_dir("/docs/fastapi")
        fs.create_file("/docs/python/python.api-patterns.yml", contents="")
        fs.create_file("/docs/fastapi/fastapi.api-patterns.yml", contents="")

        result = find_all_yml(Path("/docs"))

        assert len(result) == 2


class TestFindMappedSplits:
    """Tests for find_mapped_splits function."""

    def test_finds_matching_splits(self, fs: FakeFilesystem) -> None:
        """Should find split files matching pattern."""
        fs.create_dir("/docs/python")
        fs.create_file("/docs/python/python.api-patterns.yml", contents="")

        result = find_mapped_splits("api-patterns", Path("/docs"))

        assert "python" in result
        assert result["python"].name == "python.api-patterns.yml"


class TestGetIdsObjects:
    """Tests for get_ids_objects function."""

    def test_extracts_ids_and_objects(self, fs: FakeFilesystem) -> None:
        """Should extract IDs and full objects from YAML file."""
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            content = """
id: root
items:
  - id: item-1
    text: Item 1 text
    category: test
"""
            fs.create_file("/fake/test.yml", contents=content)

            result = get_ids_objects(Path("/fake/test.yml"))

            assert "item-1" in result
            assert result["item-1"]["text"] == "Item 1 text"
            assert result["item-1"]["category"] == "test"


class TestAggregateSplitObjects:
    """Tests for aggregate_split_objects function."""

    def test_aggregates_objects_by_id(self, fs: FakeFilesystem) -> None:
        """Should aggregate object data by ID across files."""
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/python")
            content = """
items:
  - id: item-1
    text: Python item text
    category: python
"""
            fs.create_file("/fake/python/python.test.yml", contents=content)

            split_map = {"python": Path("/fake/python/python.test.yml")}
            result = aggregate_split_objects(split_map)

            assert "item-1" in result
            assert "python/python.test.yml" in result["item-1"]


class TestCompareOriginalToSplits:
    """Tests for compare_original_to_splits function."""

    def test_finds_differences(self, fs: FakeFilesystem) -> None:
        """Should find dict differences between original and splits."""
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake/python")

            orig_content = """
items:
  - id: item-1
    text: Original text
    category: original
"""
            split_content = """
items:
  - id: item-1
    text: Modified text
    category: modified
"""
            fs.create_file("/fake/original.yml", contents=orig_content)
            fs.create_file("/fake/python/python.test.yml", contents=split_content)

            split_map = {"python": Path("/fake/python/python.test.yml")}
            result = compare_original_to_splits(Path("/fake/original.yml"), split_map)

            assert len(result) > 0
            # Verify it's using dict comparison
            assert result[0]["source_data"]["text"] == "Original text"


class TestFlattenEntryToRows:
    """Tests for _flatten_entry_to_rows function."""

    def test_flattens_entry_with_splits(self) -> None:
        """Should create one row per split."""
        entry = ComparisonEntry(
            source_file="source.yml",
            id="item-1",
            source_data={"id": "item-1", "text": "Original"},
            splits=[
                SplitEntry(split_data={"id": "item-1", "text": "Split 1"}, source_file="split1.yml"),
                SplitEntry(split_data={"id": "item-1", "text": "Split 2"}, source_file="split2.yml"),
            ],
            origin_type="original",
        )

        rows = _flatten_entry_to_rows(entry)

        assert len(rows) == 2

    def test_flattens_entry_without_splits(self) -> None:
        """Should create one row with empty split columns."""
        entry = ComparisonEntry(
            source_file="source.yml",
            id="item-1",
            source_data={"id": "item-1", "text": "Original"},
            splits=[],
            origin_type="split_only",
        )

        rows = _flatten_entry_to_rows(entry)

        assert len(rows) == 1
        assert rows[0]["split_file"] == ""
        assert rows[0]["split_data"] == ""


class TestWriteCompareFiles:
    """Tests for write_compare_files function."""

    def test_writes_csv_files(self, tmp_path: Path) -> None:
        """Should write CSV files with comparison results.

        DuckDB requires real filesystem.
        """
        (tmp_path / ".knowledge" / "comparisons").mkdir(parents=True)

        with patch.object(compare_yaml_docs, "REPO_ROOT", tmp_path):
            results = {
                "docs/original.api-patterns.yml": {
                    "original_file": "docs/original.api-patterns.yml",
                    "entries": [
                        ComparisonEntry(
                            source_file="docs/original.api-patterns.yml",
                            id="item-1",
                            source_data={"id": "item-1", "text": "Text"},
                            splits=[],
                            origin_type="original",
                        )
                    ],
                }
            }

            count = write_compare_files(results)  # type: ignore[arg-type]

            assert count == 1


class TestWriteContainmentEdges:
    """Tests for write_containment_edges function."""

    def test_writes_edges_to_csv(self, tmp_path: Path) -> None:
        """Should write containment edges to CSV file.

        DuckDB requires real filesystem.
        """
        knowledge_path = tmp_path / ".knowledge"

        edges = [
            ContainmentEdge(
                parent_id="parent-1",
                child_id="child-1",
                field_path="items[0]",
                source_file="test.yml",
            ),
            ContainmentEdge(
                parent_id="parent-1",
                child_id="child-2",
                field_path="items[1]",
                source_file="test.yml",
            ),
        ]

        count = write_containment_edges(edges, knowledge_path)

        assert count == 2
        csv_path = knowledge_path / "graph" / "containment_edges.csv"
        assert csv_path.exists()

        # Verify CSV content
        content = csv_path.read_text()
        assert "parent_id" in content
        assert "child_id" in content
        assert "field_path" in content
        assert "source_file" in content
        assert "parent-1" in content
        assert "child-1" in content
        assert "child-2" in content

    def test_handles_empty_edge_list(self, tmp_path: Path) -> None:
        """Should create empty CSV with headers for empty edge list."""
        knowledge_path = tmp_path / ".knowledge"

        count = write_containment_edges([], knowledge_path)

        assert count == 0
        csv_path = knowledge_path / "graph" / "containment_edges.csv"
        assert csv_path.exists()
        content = csv_path.read_text()
        assert "parent_id" in content

    def test_deduplicates_edges(self, tmp_path: Path) -> None:
        """Should deduplicate edges by (source_file, parent_id, child_id, field_path)."""
        knowledge_path = tmp_path / ".knowledge"

        # Create duplicate edges
        edges = [
            ContainmentEdge(
                parent_id="p",
                child_id="c",
                field_path="items[0]",
                source_file="test.yml",
            ),
            ContainmentEdge(
                parent_id="p",
                child_id="c",
                field_path="items[0]",
                source_file="test.yml",
            ),
        ]

        count = write_containment_edges(edges, knowledge_path)

        assert count == 1

    def test_raises_runtime_error_on_duckdb_failure(self, tmp_path: Path) -> None:
        """Should raise RuntimeError when DuckDB fails to write."""
        import duckdb as duckdb_module

        knowledge_path = tmp_path / ".knowledge"
        edges = [
            ContainmentEdge(
                parent_id="p",
                child_id="c",
                field_path="items[0]",
                source_file="test.yml",
            ),
        ]

        # Mock duckdb.connect to raise an error
        with patch.object(
            duckdb_module, "connect", side_effect=duckdb_module.Error("Mock DuckDB error")
        ):
            with pytest.raises(RuntimeError) as exc_info:
                write_containment_edges(edges, knowledge_path)

            assert "Failed to write containment edges" in str(exc_info.value)
            assert "Mock DuckDB error" in str(exc_info.value)

    def test_empty_edges_succeeds_even_with_no_data(self, tmp_path: Path) -> None:
        """Should succeed with count 0 when edge list is empty (not a failure)."""
        knowledge_path = tmp_path / ".knowledge"

        # Empty edges should succeed and create CSV with headers
        count = write_containment_edges([], knowledge_path)

        assert count == 0
        csv_path = knowledge_path / "graph" / "containment_edges.csv"
        assert csv_path.exists()


class TestContainmentEdgeColumns:
    """Tests for CONTAINMENT_EDGE_COLUMNS constant."""

    def test_has_required_columns(self) -> None:
        """Should have all required columns."""
        assert "parent_id" in CONTAINMENT_EDGE_COLUMNS
        assert "child_id" in CONTAINMENT_EDGE_COLUMNS
        assert "field_path" in CONTAINMENT_EDGE_COLUMNS
        assert "source_file" in CONTAINMENT_EDGE_COLUMNS


class TestCsvColumns:
    """Tests for CSV_COLUMNS constant."""

    def test_has_required_columns(self) -> None:
        """Should have all required columns."""
        assert "source_file" in CSV_COLUMNS
        assert "id" in CSV_COLUMNS
        assert "origin_type" in CSV_COLUMNS
        assert "original_data" in CSV_COLUMNS
        assert "split_file" in CSV_COLUMNS
        assert "split_data" in CSV_COLUMNS


class TestMain:
    """Tests for main function."""

    def test_returns_one_for_invalid_path(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 for non-existent path."""
        nonexistent = tmp_path / "nonexistent"
        with patch("sys.argv", ["script", "--path", str(nonexistent)]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "does not exist" in captured.err

    def test_returns_zero_when_no_differences(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 0 when no differences found."""
        # Create docs structure
        docs_dir = tmp_path / "docs"
        python_dir = docs_dir / "python"
        knowledge_dir = tmp_path / ".knowledge"

        docs_dir.mkdir()
        python_dir.mkdir()
        (knowledge_dir / "comparisons").mkdir(parents=True)

        # Create matching original and split
        content = """
items:
  - id: item-1
    text: Same text
"""
        (docs_dir / "original.test.yml").write_text(content)
        (python_dir / "python.test.yml").write_text(content)

        with (
            patch.object(compare_yaml_docs, "REPO_ROOT", tmp_path),
            patch.object(compare_yaml_docs, "DEVELOPMENT_DIR", docs_dir),
            patch("sys.argv", ["script", "--path", str(docs_dir)]),
        ):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "No differences found" in captured.out

    def test_writes_containment_edges(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should write containment edges CSV for nested ID-bearing dicts."""
        # Create docs structure
        docs_dir = tmp_path / "docs"
        python_dir = docs_dir / "python"
        knowledge_dir = tmp_path / ".knowledge"

        docs_dir.mkdir()
        python_dir.mkdir()
        (knowledge_dir / "comparisons").mkdir(parents=True)

        # Create YAML with nested ID-bearing dicts
        content = """
id: parent-section
items:
  - id: child-item-1
    text: Child 1 text
  - id: child-item-2
    text: Child 2 text
"""
        (docs_dir / "original.test.yml").write_text(content)
        (python_dir / "python.test.yml").write_text(content)

        with (
            patch.object(compare_yaml_docs, "REPO_ROOT", tmp_path),
            patch.object(compare_yaml_docs, "DEVELOPMENT_DIR", docs_dir),
            patch("sys.argv", ["script", "--path", str(docs_dir)]),
        ):
            result = main()

        # Should succeed (matching content)
        assert result == 0

        # Containment edges CSV should exist
        edges_csv = knowledge_dir / "graph" / "containment_edges.csv"
        assert edges_csv.exists()

        # Verify edges content
        content = edges_csv.read_text()
        assert "parent-section" in content
        assert "child-item-1" in content
        assert "child-item-2" in content

        captured = capsys.readouterr()
        assert "containment edge" in captured.out
