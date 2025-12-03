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
    Artifact,
    ArtifactMatch,
    ComparisonEntry,
    ContainmentEdge,
    ElementContext,
    FieldFact,
    RoleAssignment,
    SplitEntry,
    _assign_role,
    _build_ancestors_map,
    _check_content_sniff,
    _check_sibling_constraints,
    _clear_artifact_registry_cache,
    _compute_artifact_id,
    _compute_group_key,
    _determine_value_kind,
    _fact_to_line,
    _flatten_entry_to_rows,
    _get_modality_and_extraction_mode_from_registry,
    _get_render_engine_for_kind,
    _get_render_plan_id_from_registry,
    _index_elements,
    _is_artifact_root,
    _is_element,
    _iter_field_facts,
    _load_artifact_registry,
    _match_root_path,
    _slice_element,
    _strip_timestamp_prefix,
    _validate_yaml_result,
    aggregate_split_objects,
    compare_original_to_splits,
    compute_element_content_hash,
    detect_artifacts_from_field_facts,
    extract_field_facts,
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
    """Tests for extract_ids_and_text function.

    Note: Output format changed from simple key=value to fact-line format:
    [ancestor > element_id] field_path = value

    Per fact_redesign.md lines 1233-1258, this enables:
    - Field names as part of the text (for NLP extraction)
    - Ancestor elements provide structural context
    - Nested entities appear only as $ref tokens
    """

    def test_simple_element_text_projection(self) -> None:
        """Should produce fact-line text projection for simple element."""
        data = {"id": "test", "text": "Hello", "count": 5}
        result = extract_ids_and_text(data)  # type: ignore[arg-type]
        assert "test" in result
        text = result["test"]
        # New format: [element_id] field_path = value
        assert "[test]" in text
        assert "text = Hello" in text
        assert "count = 5" in text

    def test_element_with_ref_produces_ref_format(self) -> None:
        """Should produce $ref:child_id format for references."""
        data = {
            "id": "parent",
            "child": {"id": "child-1", "text": "nested"},
        }
        result = extract_ids_and_text(data)  # type: ignore[arg-type]
        text = result["parent"]
        # New format: [element_id] field_path = $ref:child_id
        assert "child = $ref:child-1" in text

    def test_element_with_lists(self) -> None:
        """Should format list items as individual facts."""
        data = {"id": "test", "items": ["a", "b", "c"]}
        result = extract_ids_and_text(data)  # type: ignore[arg-type]
        text = result["test"]
        # List items become individual fact-lines
        assert "items[0] = a" in text
        assert "items[1] = b" in text
        assert "items[2] = c" in text

    def test_deterministic_ordering(self) -> None:
        """Should produce deterministic output based on sorted field_path."""
        data = {"id": "test", "z_field": "last", "a_field": "first"}
        result = extract_ids_and_text(data)  # type: ignore[arg-type]
        text = result["test"]
        lines = text.split("\n")
        # Lines sorted by field_path: a_field before z_field
        assert "a_field" in lines[0]
        assert "z_field" in lines[1]


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


# ==============================================================================
# FieldFact Extraction Tests
# ==============================================================================


class TestDetermineValueKind:
    """Tests for _determine_value_kind helper function."""

    def test_ref_dict_returns_ref(self) -> None:
        """Should return 'ref' for dict with $ref key."""
        from scripts.knowledge.compare_yaml_docs import _determine_value_kind

        result = _determine_value_kind({"$ref": "child-id"})
        assert result == "ref"

    def test_scalar_string_returns_scalar_str(self) -> None:
        """Should return 'scalar-str' for string values."""
        from scripts.knowledge.compare_yaml_docs import _determine_value_kind

        assert _determine_value_kind("hello") == "scalar-str"
        assert _determine_value_kind("") == "scalar-str"

    def test_scalar_number_returns_scalar_num(self) -> None:
        """Should return 'scalar-num' for numeric values."""
        from scripts.knowledge.compare_yaml_docs import _determine_value_kind

        assert _determine_value_kind(42) == "scalar-num"
        assert _determine_value_kind(3.14) == "scalar-num"
        assert _determine_value_kind(0) == "scalar-num"

    def test_scalar_bool_returns_scalar_bool(self) -> None:
        """Should return 'scalar-bool' for boolean values."""
        from scripts.knowledge.compare_yaml_docs import _determine_value_kind

        assert _determine_value_kind(True) == "scalar-bool"
        assert _determine_value_kind(False) == "scalar-bool"

    def test_scalar_null_returns_scalar_null(self) -> None:
        """Should return 'scalar-null' for None values."""
        from scripts.knowledge.compare_yaml_docs import _determine_value_kind

        assert _determine_value_kind(None) == "scalar-null"

    def test_list_of_scalars_returns_list_scalar(self) -> None:
        """Should return 'list-scalar' for lists of primitives."""
        from scripts.knowledge.compare_yaml_docs import _determine_value_kind

        assert _determine_value_kind(["a", "b", "c"]) == "list-scalar"
        assert _determine_value_kind([1, 2, 3]) == "list-scalar"
        assert _determine_value_kind([]) == "list-scalar"

    def test_list_of_dicts_returns_list_object(self) -> None:
        """Should return 'list-object' for lists containing dicts."""
        from scripts.knowledge.compare_yaml_docs import _determine_value_kind

        assert _determine_value_kind([{"key": "value"}]) == "list-object"
        assert _determine_value_kind([{"a": 1}, {"b": 2}]) == "list-object"

    def test_dict_without_ref_returns_object(self) -> None:
        """Should return 'object' for dicts without $ref."""
        from scripts.knowledge.compare_yaml_docs import _determine_value_kind

        assert _determine_value_kind({"key": "value"}) == "object"
        assert _determine_value_kind({}) == "object"


class TestAssignRole:
    """Tests for _assign_role helper function."""

    def test_ref_value_kind_returns_entity_ref(self) -> None:
        """Should return 'entity_ref' when value_kind is 'ref'."""
        result = _assign_role("child", "ref", "items[0].child", None)
        assert isinstance(result, RoleAssignment)
        assert result.role == "entity_ref"
        assert result.artifact_kind is None

    def test_metadata_keys_return_metadata(self) -> None:
        """Should return 'metadata' for known metadata keys."""
        assert _assign_role("id", "scalar-str", "id", None).role == "metadata"
        assert _assign_role("doc_id", "scalar-str", "doc_id", None).role == "metadata"
        assert _assign_role("version_hint", "scalar-str", "version_hint", None).role == "metadata"
        assert _assign_role("kind", "scalar-str", "kind", None).role == "metadata"
        assert _assign_role("index", "scalar-num", "index", None).role == "metadata"
        assert _assign_role("category", "scalar-str", "category", None).role == "metadata"
        assert _assign_role("domain", "scalar-str", "domain", None).role == "metadata"

    def test_default_returns_constraint(self) -> None:
        """Should return 'constraint' for non-metadata, non-ref keys."""
        assert _assign_role("text", "scalar-str", "text", None).role == "constraint"
        assert _assign_role("status_code", "scalar-num", "raises[0].status_code", None).role == "constraint"
        assert _assign_role("method", "scalar-str", "http_method_defaults[0].method", None).role == "constraint"

    def test_artifact_root_returns_none_without_registry(self) -> None:
        """Should return None when no registry is available."""
        # Clear cache and provide empty registry
        _clear_artifact_registry_cache()
        result = _is_artifact_root(
            "text", "scalar-str", "items[0].text", None, None, registry_cache=[]
        )
        assert result is None


class TestComputeGroupKey:
    """Tests for _compute_group_key helper function."""

    def test_default_grouping_returns_scope_path(self) -> None:
        """Should return scope_path when no discriminator pattern matches."""
        from scripts.knowledge.compare_yaml_docs import _compute_group_key

        result = _compute_group_key("items[0]", "items[0].text", None)
        assert result == "items[0]"

    def test_empty_scope_path_returns_root(self) -> None:
        """Should return '<root>' when scope_path is empty."""
        from scripts.knowledge.compare_yaml_docs import _compute_group_key

        result = _compute_group_key("", "text", None)
        assert result == "<root>"

    def test_http_method_defaults_discriminator(self) -> None:
        """Should use method discriminator for http_method_defaults."""
        from scripts.knowledge.compare_yaml_docs import _compute_group_key

        parent_data = {"method": "GET", "success_status": 200}
        result = _compute_group_key("http_method_defaults[0]", "http_method_defaults[0].success_status", parent_data)
        assert result == "http_method_defaults::method=GET"

    def test_sample_code_discriminator(self) -> None:
        """Should use language discriminator for sample_code."""
        from scripts.knowledge.compare_yaml_docs import _compute_group_key

        parent_data = {"language": "python", "code": "print('hello')"}
        result = _compute_group_key("sample_code", "sample_code.code", parent_data)
        assert result == "sample_code::language=python"

    def test_nested_list_index_extraction(self) -> None:
        """Should handle list index patterns correctly."""
        from scripts.knowledge.compare_yaml_docs import _compute_group_key

        # Without discriminator, should strip index for container matching but return full scope_path
        result = _compute_group_key("sections[0].items[1]", "sections[0].items[1].text", None)
        assert result == "sections[0].items[1]"


class TestBuildAncestorsMap:
    """Tests for _build_ancestors_map helper function."""

    def test_empty_edges_returns_empty_map(self) -> None:
        """Should return empty map for no edges."""
        result = _build_ancestors_map([])
        assert result == {}

    def test_single_parent_child(self) -> None:
        """Should build ancestors for single parent-child relationship."""
        edges = [
            ContainmentEdge(
                parent_id="parent",
                child_id="child",
                field_path="items[0]",
                source_file="test.yml",
            )
        ]
        result = _build_ancestors_map(edges)

        assert "child" in result
        assert result["child"] == ["parent"]

    def test_three_level_hierarchy(self) -> None:
        """Should build ancestors for grandparent-parent-child hierarchy."""
        edges = [
            ContainmentEdge(
                parent_id="grandparent",
                child_id="parent",
                field_path="sections[0]",
                source_file="test.yml",
            ),
            ContainmentEdge(
                parent_id="parent",
                child_id="child",
                field_path="items[0]",
                source_file="test.yml",
            ),
        ]
        result = _build_ancestors_map(edges)

        # Parent's ancestors = [grandparent]
        assert result["parent"] == ["grandparent"]
        # Child's ancestors = [grandparent, parent] (outermost first)
        assert result["child"] == ["grandparent", "parent"]

    def test_multiple_children_same_parent(self) -> None:
        """Should handle multiple children with same parent."""
        edges = [
            ContainmentEdge(
                parent_id="parent",
                child_id="child-1",
                field_path="items[0]",
                source_file="test.yml",
            ),
            ContainmentEdge(
                parent_id="parent",
                child_id="child-2",
                field_path="items[1]",
                source_file="test.yml",
            ),
        ]
        result = _build_ancestors_map(edges)

        assert result["child-1"] == ["parent"]
        assert result["child-2"] == ["parent"]


class TestIterFieldFacts:
    """Tests for _iter_field_facts generator function."""

    def test_simple_element_produces_field_facts(self) -> None:
        """Should produce FieldFacts for element with scalar fields."""
        from scripts.knowledge.compare_yaml_docs import _iter_field_facts

        data = {"id": "test-1", "text": "Hello", "count": 5}
        facts = _iter_field_facts("test-1", data, [], "test.yml")

        # Should have facts for text and count (id is skipped at root)
        assert len(facts) == 2
        field_paths = {f.field_path for f in facts}
        assert "text" in field_paths
        assert "count" in field_paths

        text_fact = next(f for f in facts if f.field_path == "text")
        assert text_fact.element_id == "test-1"
        assert text_fact.key == "text"
        assert text_fact.value == "Hello"
        assert text_fact.value_kind == "scalar-str"
        assert text_fact.source_file == "test.yml"

    def test_nested_dict_produces_nested_field_facts(self) -> None:
        """Should produce FieldFacts with nested field_paths for nested dicts."""
        from scripts.knowledge.compare_yaml_docs import _iter_field_facts

        data = {
            "id": "test-1",
            "raises": [{"status_code": 404, "description": "Not found"}],
        }
        facts = _iter_field_facts("test-1", data, [], "test.yml")

        field_paths = {f.field_path for f in facts}
        assert "raises[0].status_code" in field_paths
        assert "raises[0].description" in field_paths

        status_fact = next(f for f in facts if f.field_path == "raises[0].status_code")
        assert status_fact.key == "status_code"
        assert status_fact.scope_path == "raises[0]"
        assert status_fact.value == 404
        assert status_fact.value_kind == "scalar-num"

    def test_list_items_produce_indexed_field_facts(self) -> None:
        """Should produce field_paths with indices for list items."""
        from scripts.knowledge.compare_yaml_docs import _iter_field_facts

        data = {
            "id": "test-1",
            "items": ["a", "b", "c"],
        }
        facts = _iter_field_facts("test-1", data, [], "test.yml")

        field_paths = {f.field_path for f in facts}
        assert "items[0]" in field_paths
        assert "items[1]" in field_paths
        assert "items[2]" in field_paths

        item0 = next(f for f in facts if f.field_path == "items[0]")
        assert item0.key == "0"
        assert item0.scope_path == "items"
        assert item0.value == "a"

    def test_ref_value_produces_entity_ref_role(self) -> None:
        """Should produce role='entity_ref' for $ref values."""
        from scripts.knowledge.compare_yaml_docs import _iter_field_facts

        data = {
            "id": "parent",
            "child": {"$ref": "child-1"},
        }
        facts = _iter_field_facts("parent", data, [], "test.yml")

        child_fact = next(f for f in facts if f.field_path == "child")
        assert child_fact.role == "entity_ref"
        assert child_fact.value_kind == "ref"
        assert child_fact.value == {"$ref": "child-1"}

    def test_metadata_fields_produce_metadata_role(self) -> None:
        """Should produce role='metadata' for metadata fields."""
        from scripts.knowledge.compare_yaml_docs import _iter_field_facts

        data = {
            "id": "test-1",
            "doc_id": "test-doc",
            "version_hint": "2024",
            "category": "standard",
        }
        facts = _iter_field_facts("test-1", data, [], "test.yml")

        doc_id_fact = next(f for f in facts if f.field_path == "doc_id")
        assert doc_id_fact.role == "metadata"

        version_fact = next(f for f in facts if f.field_path == "version_hint")
        assert version_fact.role == "metadata"

        category_fact = next(f for f in facts if f.field_path == "category")
        assert category_fact.role == "metadata"

    def test_skips_root_id_field(self) -> None:
        """Should not emit FieldFact for root 'id' field."""
        from scripts.knowledge.compare_yaml_docs import _iter_field_facts

        data = {"id": "test-1", "text": "Hello"}
        facts = _iter_field_facts("test-1", data, [], "test.yml")

        # Should only have text, not id
        field_paths = {f.field_path for f in facts}
        assert "id" not in field_paths
        assert "text" in field_paths

    def test_group_id_is_sha256_of_group_key(self) -> None:
        """Should verify group_id is SHA-256 hash of group_key."""
        import hashlib

        from scripts.knowledge.compare_yaml_docs import _iter_field_facts

        data = {"id": "test-1", "text": "Hello"}
        facts = _iter_field_facts("test-1", data, [], "test.yml")

        text_fact = next(f for f in facts if f.field_path == "text")
        expected_hash = hashlib.sha256(text_fact.group_key.encode("utf-8")).hexdigest()
        assert text_fact.group_id == expected_hash


class TestExtractFieldFacts:
    """Tests for extract_field_facts public function."""

    def test_returns_dict_of_element_to_field_facts(self) -> None:
        """Should return dict[str, list[FieldFact]]."""
        from scripts.knowledge.compare_yaml_docs import FieldFact, extract_field_facts

        data = {
            "id": "root",
            "text": "Root text",
            "items": [{"id": "item-1", "text": "Item text"}],
        }
        result = extract_field_facts(data, "test.yml")

        assert isinstance(result, dict)
        assert "root" in result
        assert "item-1" in result

        # Check all values are lists of FieldFacts
        for facts in result.values():
            assert isinstance(facts, list)
            for fact in facts:
                assert isinstance(fact, FieldFact)

    def test_http_method_defaults_example(self) -> None:
        """Should produce correct FieldFacts for http_method_defaults.

        Uses structure from general.rest.api-patterns.yml lines 61-94.
        Discriminator-based grouping uses the list item's own data as
        parent_data since that's where the discriminator field ("method") lives.
        """
        from scripts.knowledge.compare_yaml_docs import extract_field_facts

        data = {
            "id": "http-methods-section",
            "http_method_defaults": [
                {"method": "GET", "success_status": 200, "error_statuses": [404]},
                {"method": "POST", "success_status": 201, "error_statuses": [400, 409]},
            ],
        }
        result = extract_field_facts(data, "test.yml")

        facts = result["http-methods-section"]

        # Verify we have facts for the http_method_defaults entries
        method_facts = [f for f in facts if f.field_path.endswith(".method")]
        assert len(method_facts) == 2

        # Verify discriminator grouping for GET method
        get_method_fact = next(
            (f for f in facts if f.field_path == "http_method_defaults[0].method"), None
        )
        assert get_method_fact is not None
        assert get_method_fact.value == "GET"
        # Assert explicit discriminator-based group_key
        assert get_method_fact.group_key == "http_method_defaults::method=GET"

        # Verify success_status under GET also has discriminator-based group_key
        get_success_fact = next(
            (f for f in facts if f.field_path == "http_method_defaults[0].success_status"),
            None,
        )
        assert get_success_fact is not None
        assert get_success_fact.value == 200
        assert get_success_fact.group_key == "http_method_defaults::method=GET"

        # Verify error_statuses under GET - these are scalar list items with their own scope_path
        # The discriminator applies to dict fields, not nested list scalars
        get_error_facts = [
            f for f in facts if f.field_path.startswith("http_method_defaults[0].error_statuses")
        ]
        assert len(get_error_facts) == 1  # [404]
        # List items have their own group_key based on scope_path
        assert get_error_facts[0].group_key == "http_method_defaults[0].error_statuses"

        # Verify POST method has different discriminator-based group_key
        post_method_fact = next(
            (f for f in facts if f.field_path == "http_method_defaults[1].method"), None
        )
        assert post_method_fact is not None
        assert post_method_fact.value == "POST"
        assert post_method_fact.group_key == "http_method_defaults::method=POST"

        # POST success_status should share group_id with POST method
        post_success_fact = next(
            (f for f in facts if f.field_path == "http_method_defaults[1].success_status"),
            None,
        )
        assert post_success_fact is not None
        assert post_success_fact.group_id == post_method_fact.group_id

    def test_sample_code_example(self) -> None:
        """Should handle sample_code structures correctly.

        Uses structure from general.python.docstrings-guide.yml lines 58-71.
        Discriminator-based grouping uses "language" field from sample_code dict.
        """
        from scripts.knowledge.compare_yaml_docs import extract_field_facts

        data = {
            "id": "function-example",
            "sample_code": {
                "description": "Example function with Args",
                "language": "python",
                "code": "def fetch_user(): ...",
            },
        }
        result = extract_field_facts(data, "test.yml")

        facts = result["function-example"]

        # Find sample_code facts
        code_facts = [f for f in facts if "sample_code" in f.field_path]
        assert len(code_facts) == 3  # description, language, code

        # Verify discriminator grouping for sample_code with explicit group_key
        language_fact = next(
            (f for f in facts if f.field_path == "sample_code.language"), None
        )
        assert language_fact is not None
        assert language_fact.value == "python"
        # Assert explicit discriminator-based group_key
        assert language_fact.group_key == "sample_code::language=python"

        # Verify description also has discriminator-based group_key
        description_fact = next(
            (f for f in facts if f.field_path == "sample_code.description"), None
        )
        assert description_fact is not None
        assert description_fact.group_key == "sample_code::language=python"

        # Verify code also has discriminator-based group_key
        code_fact = next(
            (f for f in facts if f.field_path == "sample_code.code"), None
        )
        assert code_fact is not None
        assert code_fact.group_key == "sample_code::language=python"

        # All sample_code fields should share the same group_id
        assert language_fact.group_id == description_fact.group_id
        assert language_fact.group_id == code_fact.group_id

    def test_nested_elements_with_containment(self) -> None:
        """Should handle nested elements with $ref correctly."""
        from scripts.knowledge.compare_yaml_docs import extract_field_facts

        data = {
            "id": "parent",
            "title": "Parent Title",
            "items": [
                {"id": "child-1", "text": "Child 1 text"},
                {"id": "child-2", "text": "Child 2 text"},
            ],
        }
        result = extract_field_facts(data, "test.yml")

        # Parent should exist
        assert "parent" in result
        parent_facts = result["parent"]

        # Parent should have title fact
        title_fact = next((f for f in parent_facts if f.field_path == "title"), None)
        assert title_fact is not None
        assert title_fact.value == "Parent Title"

        # Parent should have $ref facts for children (sliced representation)
        ref_facts = [f for f in parent_facts if f.value_kind == "ref"]
        assert len(ref_facts) == 2  # Two children

        # Verify $ref structure
        for ref_fact in ref_facts:
            assert "$ref" in ref_fact.value
            assert ref_fact.role == "entity_ref"

        # Children should have separate FieldFacts
        assert "child-1" in result
        assert "child-2" in result

        child1_facts = result["child-1"]
        text_fact = next((f for f in child1_facts if f.field_path == "text"), None)
        assert text_fact is not None
        assert text_fact.value == "Child 1 text"

    def test_ancestor_tracking_in_nested_elements(self) -> None:
        """Should populate ancestors field from containment edges."""
        from scripts.knowledge.compare_yaml_docs import extract_field_facts

        data = {
            "id": "grandparent",
            "title": "Grandparent",
            "sections": [
                {
                    "id": "parent",
                    "title": "Parent",
                    "items": [
                        {"id": "child-1", "text": "Child 1"},
                        {"id": "child-2", "text": "Child 2"},
                    ],
                }
            ],
        }
        result = extract_field_facts(data, "test.yml")

        # Grandparent should have no ancestors
        grandparent_facts = result["grandparent"]
        for fact in grandparent_facts:
            assert fact.ancestors == []

        # Parent should have grandparent as ancestor
        parent_facts = result["parent"]
        for fact in parent_facts:
            assert fact.ancestors == ["grandparent"]

        # Child should have grandparent, then parent as ancestors (outermost first)
        child1_facts = result["child-1"]
        for fact in child1_facts:
            assert fact.ancestors == ["grandparent", "parent"]

        child2_facts = result["child-2"]
        for fact in child2_facts:
            assert fact.ancestors == ["grandparent", "parent"]


class TestExtractIdsAndTextWithFieldFacts:
    """Tests for extract_ids_and_text using FieldFact-based projection."""

    def test_text_projection_uses_fact_line_format(self) -> None:
        """Should verify extract_ids_and_text uses fact-line format."""
        data = {"id": "test", "text": "Hello", "count": 5}
        result = extract_ids_and_text(data)  # type: ignore[arg-type]

        assert "test" in result
        text = result["test"]
        # Should have fact-line format: [element_id] field_path = value
        assert "[test]" in text
        assert "count = 5" in text
        assert "text = Hello" in text

    def test_field_facts_used_for_structured_access(self) -> None:
        """Should verify FieldFacts can be used for structured access."""
        from scripts.knowledge.compare_yaml_docs import extract_field_facts

        data = {"id": "test", "text": "Hello", "count": 5}

        # extract_ids_and_text produces text
        text_result = extract_ids_and_text(data)  # type: ignore[arg-type]

        # extract_field_facts produces structured FieldFacts
        facts_result = extract_field_facts(data, "test.yml")

        # Both should cover the same elements
        assert set(text_result.keys()) == set(facts_result.keys())

        # Facts should provide structured access to the same data
        facts = facts_result["test"]
        text_fact = next((f for f in facts if f.key == "text"), None)
        assert text_fact is not None
        assert text_fact.value == "Hello"


class TestArtifactRootDetection:
    """Tests for artifact root detection with registry."""

    def setup_method(self) -> None:
        """Clear registry cache before each test."""
        _clear_artifact_registry_cache()

    def test_load_artifact_registry_missing_file(self, fs: FakeFilesystem) -> None:
        """Should return empty list when registry file doesn't exist."""
        fs.create_dir("/fake/.knowledge/artifacts")
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            result = _load_artifact_registry(Path("/fake/.knowledge"))
        assert result == []

    def test_load_artifact_registry_valid_file(self, fs: FakeFilesystem) -> None:
        """Should load valid registry."""
        fs.create_dir("/fake/.knowledge/artifacts")
        registry_content = """
kinds:
  - kind_id: test/kind
    content_form: text
"""
        fs.create_file(
            "/fake/.knowledge/artifacts/kinds.yml",
            contents=registry_content,
        )
        with patch.object(compare_yaml_docs, "REPO_ROOT", Path("/fake")):
            result = _load_artifact_registry(Path("/fake/.knowledge"))
        assert len(result) == 1
        assert result[0]["kind_id"] == "test/kind"

    def test_match_root_path_exact(self) -> None:
        """Should match exact path patterns."""
        assert _match_root_path("sections[0].text", "sections[*].text")
        assert _match_root_path("sections[10].text", "sections[*].text")
        assert not _match_root_path("sections[0].items", "sections[*].text")

    def test_match_root_path_nested(self) -> None:
        """Should match nested path patterns."""
        assert _match_root_path("sections[0].items[1].text", "sections[*].items[*].text")
        assert not _match_root_path("sections[0].text", "sections[*].items[*].text")

    def test_match_root_path_container_level(self) -> None:
        """Should match container-level patterns with prefix matching.

        Container-level roots like sections[*].http_method_defaults should match
        any field within that container, enabling artifact root detection at
        the container level.
        """
        # Container-level match - pattern points to container, field is within
        assert _match_root_path(
            "sections[0].http_method_defaults",
            "sections[*].http_method_defaults",
        )
        assert _match_root_path(
            "sections[0].http_method_defaults[0]",
            "sections[*].http_method_defaults",
        )
        assert _match_root_path(
            "sections[0].http_method_defaults[0].method",
            "sections[*].http_method_defaults",
        )
        # Should not match unrelated paths
        assert not _match_root_path(
            "sections[0].other_field",
            "sections[*].http_method_defaults",
        )
        # Should not match partial key overlaps
        assert not _match_root_path(
            "sections[0].http_method_defaults_extra",
            "sections[*].http_method_defaults",
        )

    def test_check_sibling_constraints_equals(self) -> None:
        """Should check equals constraint."""
        constraints = [{"key": "type", "equals": "code"}]
        parent = {"type": "code", "text": "content"}
        assert _check_sibling_constraints(parent, constraints)
        assert not _check_sibling_constraints({"type": "prose"}, constraints)

    def test_check_sibling_constraints_matches(self) -> None:
        """Should check regex matches constraint."""
        constraints = [{"key": "type", "matches": r"^code.*"}]
        assert _check_sibling_constraints({"type": "code_block"}, constraints)
        assert not _check_sibling_constraints({"type": "prose"}, constraints)

    def test_check_sibling_constraints_starts_with(self) -> None:
        """Should check starts_with constraint."""
        constraints = [{"key": "type", "starts_with": "mermaid"}]
        assert _check_sibling_constraints({"type": "mermaid_diagram"}, constraints)
        assert not _check_sibling_constraints({"type": "code"}, constraints)

    def test_check_content_sniff_starts_with_any(self) -> None:
        """Should check starts_with_any content sniff."""
        sniff = {"starts_with_any": ["sequenceDiagram", "graph "]}
        assert _check_content_sniff("sequenceDiagram\n  A->>B", sniff)
        assert _check_content_sniff("graph LR\n  A-->B", sniff)
        assert not _check_content_sniff("flowchart LR", sniff)

    def test_check_content_sniff_matches(self) -> None:
        """Should check regex matches content sniff."""
        sniff = {"matches": r"^```python"}
        assert _check_content_sniff("```python\nprint('hello')", sniff)
        assert not _check_content_sniff("```javascript", sniff)

    def test_is_artifact_root_with_registry(self) -> None:
        """Should detect artifact root using registry patterns."""
        registry = [
            {
                "kind_id": "diagram/mermaid.sequence",
                "structure_pattern": {
                    "root_path": "sections[*].items[*].text",
                    "sibling_constraints": [{"key": "type", "equals": "code"}],
                    "content_sniff": {"starts_with_any": ["sequenceDiagram"]},
                },
                "rendering_contract": {"output_mime": "text/x-mermaid"},
            }
        ]
        # Should match
        result = _is_artifact_root(
            key="text",
            value_kind="scalar-str",
            field_path="sections[0].items[2].text",
            parent_data={"type": "code", "text": "sequenceDiagram\n  A->>B"},
            value="sequenceDiagram\n  A->>B: Message",
            registry_cache=registry,
        )
        assert result is not None
        assert isinstance(result, ArtifactMatch)
        assert result.kind_id == "diagram/mermaid.sequence"
        assert result.artifact_format == "text/x-mermaid"

    def test_is_artifact_root_no_match(self) -> None:
        """Should return None when no pattern matches."""
        registry = [
            {
                "kind_id": "diagram/mermaid.sequence",
                "structure_pattern": {
                    "root_path": "sections[*].items[*].text",
                    "content_sniff": {"starts_with_any": ["sequenceDiagram"]},
                },
            }
        ]
        # Different content - should not match
        result = _is_artifact_root(
            key="text",
            value_kind="scalar-str",
            field_path="sections[0].items[0].text",
            parent_data=None,
            value="Just regular text",
            registry_cache=registry,
        )
        assert result is None

    def test_assign_role_artifact_root(self) -> None:
        """Should return artifact_root role with metadata."""
        registry = [
            {
                "kind_id": "prose/code-block",
                "structure_pattern": {
                    "root_path": "sample_code.code",
                },
                "rendering_contract": {"output_mime": "text/markdown"},
            }
        ]
        result = _assign_role(
            key="code",
            value_kind="scalar-str",
            field_path="sample_code.code",
            parent_data=None,
            value="def foo(): pass",
            registry_cache=registry,
        )
        assert result.role == "artifact_root"
        assert result.artifact_kind == "prose/code-block"
        assert result.artifact_format == "text/markdown"


class TestComputeArtifactId:
    """Tests for _compute_artifact_id function."""

    def test_produces_sha256_hash(self) -> None:
        """Should produce a 64-character SHA-256 hash."""
        result = _compute_artifact_id(
            source_file="docs/test.yml",
            element_id="test-element",
            field_path="text",
            artifact_kind="diagram/mermaid.sequence",
        )
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_stable_for_same_inputs(self) -> None:
        """Should produce same hash for same inputs."""
        inputs = {
            "source_file": "docs/test.yml",
            "element_id": "test-element",
            "field_path": "text",
            "artifact_kind": "diagram/mermaid.sequence",
        }
        result1 = _compute_artifact_id(**inputs)
        result2 = _compute_artifact_id(**inputs)
        assert result1 == result2

    def test_different_for_different_inputs(self) -> None:
        """Should produce different hash for different inputs."""
        result1 = _compute_artifact_id(
            source_file="docs/test.yml",
            element_id="element-1",
            field_path="text",
            artifact_kind="diagram/mermaid.sequence",
        )
        result2 = _compute_artifact_id(
            source_file="docs/test.yml",
            element_id="element-2",
            field_path="text",
            artifact_kind="diagram/mermaid.sequence",
        )
        assert result1 != result2


class TestGetRenderEngineForKind:
    """Tests for _get_render_engine_for_kind function."""

    def test_text_llm_for_prose(self) -> None:
        """Should return text_llm for prose kinds."""
        assert _get_render_engine_for_kind("prose/paragraph") == "text_llm"
        assert _get_render_engine_for_kind("prose/code-block") == "text_llm"

    def test_text_llm_for_diagram(self) -> None:
        """Should return text_llm for diagram kinds."""
        assert _get_render_engine_for_kind("diagram/mermaid.sequence") == "text_llm"
        assert _get_render_engine_for_kind("diagram/mermaid.flowchart") == "text_llm"

    def test_text_llm_for_table(self) -> None:
        """Should return text_llm for table kinds."""
        assert _get_render_engine_for_kind("table/discriminator-grouped") == "text_llm"

    def test_none_for_schema(self) -> None:
        """Should return none for schema kinds."""
        assert _get_render_engine_for_kind("schema/nested-hierarchy") == "none"
        assert _get_render_engine_for_kind("schema/json_schema") == "none"

    def test_none_for_data(self) -> None:
        """Should return none for data kinds."""
        assert _get_render_engine_for_kind("data/config") == "none"


class TestGetRenderPlanIdFromRegistry:
    """Tests for _get_render_plan_id_from_registry function."""

    def test_returns_render_plan_from_registry(self) -> None:
        """Should return render_plan_id from matching registry entry."""
        registry = [
            {
                "kind_id": "diagram/mermaid.sequence",
                "rendering_contract": {
                    "render_plan_id": "diagram.mermaid.sequence.v1",
                },
            }
        ]
        result = _get_render_plan_id_from_registry(
            "diagram/mermaid.sequence",
            registry_cache=registry,
        )
        assert result == "diagram.mermaid.sequence.v1"

    def test_returns_default_for_missing_kind(self) -> None:
        """Should return default render_plan_id for unknown kind."""
        registry = []
        result = _get_render_plan_id_from_registry(
            "unknown/kind",
            registry_cache=registry,
        )
        assert result == "unknown.kind.v1"

    def test_converts_kind_format_in_default(self) -> None:
        """Should convert kind_id format for default render_plan_id."""
        registry = []
        result = _get_render_plan_id_from_registry(
            "diagram/mermaid-sequence",
            registry_cache=registry,
        )
        # / -> . and - -> _
        assert result == "diagram.mermaid_sequence.v1"


class TestGetModalityAndExtractionModeFromRegistry:
    """Tests for _get_modality_and_extraction_mode_from_registry function."""

    def test_returns_values_from_registry(self) -> None:
        """Should return modality and extraction_mode from registry."""
        registry = [
            {
                "kind_id": "image/png",
                "modality": "image",
                "extraction_mode": "query_only",
            }
        ]
        modality, extraction_mode = _get_modality_and_extraction_mode_from_registry(
            "image/png",
            registry_cache=registry,
        )
        assert modality == "image"
        assert extraction_mode == "query_only"

    def test_returns_defaults_for_missing_kind(self) -> None:
        """Should return defaults when kind not found."""
        registry = []
        modality, extraction_mode = _get_modality_and_extraction_mode_from_registry(
            "unknown/kind",
            registry_cache=registry,
        )
        assert modality == "text"
        assert extraction_mode == "full"

    def test_returns_defaults_for_missing_fields(self) -> None:
        """Should return defaults when registry entry lacks modality/extraction_mode."""
        registry = [
            {
                "kind_id": "prose/paragraph",
                # modality and extraction_mode not specified
            }
        ]
        modality, extraction_mode = _get_modality_and_extraction_mode_from_registry(
            "prose/paragraph",
            registry_cache=registry,
        )
        assert modality == "text"
        assert extraction_mode == "full"

    def test_handles_invalid_modality_value(self) -> None:
        """Should default to text for invalid modality value."""
        registry = [
            {
                "kind_id": "test/kind",
                "modality": "invalid_value",
            }
        ]
        modality, extraction_mode = _get_modality_and_extraction_mode_from_registry(
            "test/kind",
            registry_cache=registry,
        )
        assert modality == "text"

    def test_handles_invalid_extraction_mode_value(self) -> None:
        """Should default to full for invalid extraction_mode value."""
        registry = [
            {
                "kind_id": "test/kind",
                "extraction_mode": "invalid_value",
            }
        ]
        modality, extraction_mode = _get_modality_and_extraction_mode_from_registry(
            "test/kind",
            registry_cache=registry,
        )
        assert extraction_mode == "full"


class TestArtifactDataclass:
    """Tests for Artifact dataclass."""

    def test_creates_artifact_with_all_fields(self) -> None:
        """Should create Artifact with all required fields."""
        artifact = Artifact(
            artifact_id="abc123",
            artifact_kind="diagram/mermaid.sequence",
            artifact_format="text/x-mermaid",
            source_file="docs/test.yml",
            source_element_id="element-1",
            field_path="text",
            source_locator="inline",
            source_uri=None,
            render_engine="text_llm",
            render_plan_id="diagram.mermaid.sequence.v1",
            projection_version="fieldfacts.v2",
        )
        assert artifact.artifact_id == "abc123"
        assert artifact.artifact_kind == "diagram/mermaid.sequence"
        assert artifact.modality == "text"  # Default
        assert artifact.extraction_mode == "full"  # Default

    def test_default_modality_and_extraction_mode(self) -> None:
        """Should have default values for modality and extraction_mode."""
        artifact = Artifact(
            artifact_id="abc123",
            artifact_kind="prose/paragraph",
            artifact_format="text/markdown",
            source_file="docs/test.yml",
            source_element_id="element-1",
            field_path="text",
            source_locator="inline",
            source_uri=None,
            render_engine="text_llm",
            render_plan_id="prose.paragraph.v1",
            projection_version="fieldfacts.v2",
        )
        assert artifact.modality == "text"
        assert artifact.extraction_mode == "full"


class TestDetectArtifactsFromFieldFacts:
    """Tests for detect_artifacts_from_field_facts function."""

    def test_detects_artifact_root_field_facts(self) -> None:
        """Should detect artifacts from FieldFacts with role=artifact_root."""
        field_facts = {
            "element-1": [
                FieldFact(
                    element_id="element-1",
                    field_path="text",
                    key="text",
                    scope_path="",
                    value="sequenceDiagram\n  A->>B: Hello",
                    value_kind="scalar-str",
                    ancestors=[],
                    source_file="docs/test.yml",
                    role="artifact_root",
                    artifact_kind="diagram/mermaid.sequence",
                    artifact_format="text/x-mermaid",
                    artifact_locator="inline",
                    artifact_uri=None,
                    group_key="<root>",
                    group_id="abc123",
                ),
                FieldFact(
                    element_id="element-1",
                    field_path="type",
                    key="type",
                    scope_path="",
                    value="code",
                    value_kind="scalar-str",
                    role="constraint",  # Not an artifact root
                ),
            ]
        }
        registry = [
            {
                "kind_id": "diagram/mermaid.sequence",
                "rendering_contract": {
                    "render_plan_id": "diagram.mermaid.sequence.v1",
                },
            }
        ]

        artifacts = detect_artifacts_from_field_facts(
            field_facts,
            source_file="docs/test.yml",
            registry_cache=registry,
        )

        assert len(artifacts) == 1
        artifact = artifacts[0]
        assert artifact.artifact_kind == "diagram/mermaid.sequence"
        assert artifact.artifact_format == "text/x-mermaid"
        assert artifact.source_element_id == "element-1"
        assert artifact.field_path == "text"
        assert artifact.render_plan_id == "diagram.mermaid.sequence.v1"

    def test_ignores_non_artifact_root_facts(self) -> None:
        """Should ignore FieldFacts without role=artifact_root."""
        field_facts = {
            "element-1": [
                FieldFact(
                    element_id="element-1",
                    field_path="text",
                    key="text",
                    scope_path="",
                    value="Plain text",
                    value_kind="scalar-str",
                    role="constraint",  # Not artifact root
                ),
                FieldFact(
                    element_id="element-1",
                    field_path="ref",
                    key="ref",
                    scope_path="",
                    value={"$ref": "other"},
                    value_kind="ref",
                    role="entity_ref",  # Not artifact root
                ),
            ]
        }

        artifacts = detect_artifacts_from_field_facts(
            field_facts,
            source_file="docs/test.yml",
        )

        assert len(artifacts) == 0

    def test_skips_artifact_root_without_artifact_kind(self) -> None:
        """Should skip artifact roots missing artifact_kind."""
        field_facts = {
            "element-1": [
                FieldFact(
                    element_id="element-1",
                    field_path="text",
                    key="text",
                    scope_path="",
                    value="Some text",
                    value_kind="scalar-str",
                    role="artifact_root",
                    artifact_kind=None,  # Missing
                ),
            ]
        }

        artifacts = detect_artifacts_from_field_facts(
            field_facts,
            source_file="docs/test.yml",
        )

        assert len(artifacts) == 0

    def test_computes_stable_artifact_id(self) -> None:
        """Should compute stable artifact_id from source info."""
        import hashlib

        field_facts = {
            "element-1": [
                FieldFact(
                    element_id="element-1",
                    field_path="text",
                    key="text",
                    scope_path="",
                    value="Content",
                    value_kind="scalar-str",
                    role="artifact_root",
                    artifact_kind="prose/paragraph",
                    artifact_format="text/markdown",
                    artifact_locator="inline",
                ),
            ]
        }

        artifacts = detect_artifacts_from_field_facts(
            field_facts,
            source_file="docs/test.yml",
        )

        expected_concat = "docs/test.yml:element-1:text:prose/paragraph"
        expected_id = hashlib.sha256(expected_concat.encode("utf-8")).hexdigest()
        assert artifacts[0].artifact_id == expected_id

    def test_v1_only_filtering_includes_v1_artifacts(self) -> None:
        """Should include V1 artifacts when v1_only=True."""
        field_facts = {
            "element-1": [
                FieldFact(
                    element_id="element-1",
                    field_path="text",
                    key="text",
                    scope_path="",
                    value="Content",
                    value_kind="scalar-str",
                    role="artifact_root",
                    artifact_kind="prose/paragraph",
                    artifact_format="text/markdown",
                    artifact_locator="inline",
                ),
            ]
        }
        # Registry with V1 values (text modality, full extraction)
        registry = [
            {
                "kind_id": "prose/paragraph",
                "modality": "text",
                "extraction_mode": "full",
            }
        ]

        artifacts = detect_artifacts_from_field_facts(
            field_facts,
            source_file="docs/test.yml",
            registry_cache=registry,
            v1_only=True,
        )
        assert len(artifacts) == 1

    def test_v1_only_filtering_excludes_non_v1_artifacts(self) -> None:
        """Should exclude non-V1 artifacts when v1_only=True."""
        field_facts = {
            "element-1": [
                FieldFact(
                    element_id="element-1",
                    field_path="image",
                    key="image",
                    scope_path="",
                    value="image_ref",
                    value_kind="scalar-str",
                    role="artifact_root",
                    artifact_kind="image/png",
                    artifact_format="image/png",
                    artifact_locator="reference",
                    artifact_uri="assets/image.png",
                ),
            ]
        }
        # Registry with non-V1 values (image modality)
        registry = [
            {
                "kind_id": "image/png",
                "modality": "image",
                "extraction_mode": "query_only",
            }
        ]

        # With v1_only=True, should filter out non-V1 artifact
        artifacts_v1 = detect_artifacts_from_field_facts(
            field_facts,
            source_file="docs/test.yml",
            registry_cache=registry,
            v1_only=True,
        )
        assert len(artifacts_v1) == 0

        # With v1_only=False, should include non-V1 artifact
        artifacts_all = detect_artifacts_from_field_facts(
            field_facts,
            source_file="docs/test.yml",
            registry_cache=registry,
            v1_only=False,
        )
        assert len(artifacts_all) == 1
        assert artifacts_all[0].modality == "image"
        assert artifacts_all[0].extraction_mode == "query_only"


# ==============================================================================
# Text Projection Helper Tests (per fact_redesign.md lines 1068-1258)
# ==============================================================================


class TestElementContext:
    """Tests for ElementContext dataclass."""

    def test_instantiation(self) -> None:
        """Should instantiate with all required fields."""
        ctx = ElementContext(
            id="element-1",
            obj={"id": "element-1", "text": "content"},
            path="sections[0]",
            ancestors=["root", "parent"],
        )
        assert ctx.id == "element-1"
        assert ctx.obj == {"id": "element-1", "text": "content"}
        assert ctx.path == "sections[0]"
        assert ctx.ancestors == ["root", "parent"]

    def test_empty_ancestors(self) -> None:
        """Should allow empty ancestors list."""
        ctx = ElementContext(
            id="root",
            obj={"id": "root"},
            path="$",
            ancestors=[],
        )
        assert ctx.ancestors == []


class TestIndexElements:
    """Tests for _index_elements helper function."""

    def test_indexes_single_element(self) -> None:
        """Should index a single element with id."""
        data = {"id": "test-1", "text": "content"}
        result = _index_elements(data)

        assert "test-1" in result
        ctx = result["test-1"]
        assert ctx.id == "test-1"
        assert ctx.obj == data
        assert ctx.path == "$"  # Root element
        assert ctx.ancestors == []

    def test_indexes_nested_elements(self) -> None:
        """Should index nested elements with correct paths."""
        data = {
            "id": "parent",
            "items": [
                {"id": "child-1", "text": "Child 1"},
                {"id": "child-2", "text": "Child 2"},
            ],
        }
        result = _index_elements(data)

        assert "parent" in result
        assert "child-1" in result
        assert "child-2" in result

        # Check paths
        assert result["child-1"].path == "items[0]"
        assert result["child-2"].path == "items[1]"

    def test_tracks_ancestors(self) -> None:
        """Should track ancestor element IDs."""
        data = {
            "id": "grandparent",
            "sections": [
                {
                    "id": "parent",
                    "items": [
                        {"id": "child", "text": "content"},
                    ],
                }
            ],
        }
        result = _index_elements(data)

        # Grandparent has no ancestors
        assert result["grandparent"].ancestors == []

        # Parent has grandparent as ancestor
        assert result["parent"].ancestors == ["grandparent"]

        # Child has grandparent, parent as ancestors (outermost first)
        assert result["child"].ancestors == ["grandparent", "parent"]

    def test_handles_non_element_dicts(self) -> None:
        """Should skip dicts without string id field."""
        data = {
            "id": "root",
            "metadata": {"key": "value"},  # No id - not an element
            "items": [
                {"id": 123},  # Non-string id - not an element
            ],
        }
        result = _index_elements(data)

        assert "root" in result
        assert len(result) == 1

    def test_handles_empty_data(self) -> None:
        """Should return empty dict for primitive data."""
        assert _index_elements(None) == {}
        assert _index_elements("string") == {}
        assert _index_elements(123) == {}

    def test_deep_nesting_path(self) -> None:
        """Should build correct paths for deeply nested structures.

        Uses structure similar to MODULE-DEFINITIONS.yml lines 101-104.
        """
        data = {
            "id": "root",
            "sections": [
                {
                    "id": "section-1",
                    "items": [
                        {
                            "id": "item-1",
                            "subitems": [{"id": "subitem-1", "text": "deep"}],
                        }
                    ],
                }
            ],
        }
        result = _index_elements(data)

        assert result["subitem-1"].path == "sections[0].items[0].subitems[0]"
        assert result["subitem-1"].ancestors == ["root", "section-1", "item-1"]


class TestFactToLine:
    """Tests for _fact_to_line helper function."""

    def test_formats_simple_fact(self) -> None:
        """Should format fact with no ancestors."""
        fact = FieldFact(
            element_id="test-1",
            field_path="text",
            key="text",
            scope_path="",
            value="Hello World",
            value_kind="scalar-str",
            ancestors=[],
            source_file="test.yml",
            role="constraint",
        )
        line = _fact_to_line(fact)

        assert line == "[test-1] text = Hello World"

    def test_formats_fact_with_ancestors(self) -> None:
        """Should format fact with ancestor chain."""
        fact = FieldFact(
            element_id="child",
            field_path="text",
            key="text",
            scope_path="",
            value="Content",
            value_kind="scalar-str",
            ancestors=["grandparent", "parent"],
            source_file="test.yml",
            role="constraint",
        )
        line = _fact_to_line(fact)

        assert line == "[grandparent > parent > child] text = Content"

    def test_formats_ref_value(self) -> None:
        """Should format $ref values with $ref:child_id syntax."""
        fact = FieldFact(
            element_id="parent",
            field_path="child",
            key="child",
            scope_path="",
            value={"$ref": "child-1"},
            value_kind="ref",
            ancestors=[],
            source_file="test.yml",
            role="entity_ref",
        )
        line = _fact_to_line(fact)

        assert line == "[parent] child = $ref:child-1"

    def test_formats_numeric_value(self) -> None:
        """Should format numeric values as strings."""
        fact = FieldFact(
            element_id="test",
            field_path="count",
            key="count",
            scope_path="",
            value=42,
            value_kind="scalar-num",
            ancestors=[],
            source_file="test.yml",
            role="constraint",
        )
        line = _fact_to_line(fact)

        assert line == "[test] count = 42"

    def test_formats_boolean_value(self) -> None:
        """Should format boolean values as lowercase."""
        fact_true = FieldFact(
            element_id="test",
            field_path="enabled",
            key="enabled",
            scope_path="",
            value=True,
            value_kind="scalar-bool",
            ancestors=[],
            source_file="test.yml",
            role="constraint",
        )
        fact_false = FieldFact(
            element_id="test",
            field_path="disabled",
            key="disabled",
            scope_path="",
            value=False,
            value_kind="scalar-bool",
            ancestors=[],
            source_file="test.yml",
            role="constraint",
        )

        assert _fact_to_line(fact_true) == "[test] enabled = true"
        assert _fact_to_line(fact_false) == "[test] disabled = false"

    def test_formats_null_value(self) -> None:
        """Should format None as 'null'."""
        fact = FieldFact(
            element_id="test",
            field_path="optional",
            key="optional",
            scope_path="",
            value=None,
            value_kind="scalar-null",
            ancestors=[],
            source_file="test.yml",
            role="constraint",
        )
        line = _fact_to_line(fact)

        assert line == "[test] optional = null"

    def test_formats_list_value(self) -> None:
        """Should format list values with bracket notation."""
        fact = FieldFact(
            element_id="test",
            field_path="items",
            key="items",
            scope_path="",
            value=["a", "b", "c"],
            value_kind="list-scalar",
            ancestors=[],
            source_file="test.yml",
            role="constraint",
        )
        line = _fact_to_line(fact)

        assert line == "[test] items = [a, b, c]"


class TestExtractIdsAndTextFieldFactProjection:
    """Tests for extract_ids_and_text with FieldFact-based projection."""

    def test_produces_fact_line_format(self) -> None:
        """Should produce text with [element_id] field_path = value format."""
        data = {"id": "test", "text": "Hello", "count": 5}
        result = extract_ids_and_text(data)  # type: ignore[arg-type]

        text = result["test"]
        # Should contain ancestor chain format
        assert "[test]" in text
        # Should contain field_path = value format
        assert "text = Hello" in text
        assert "count = 5" in text

    def test_deterministic_ordering_by_field_path(self) -> None:
        """Should sort lines by field_path for deterministic output."""
        data = {"id": "test", "z_field": "last", "a_field": "first", "m_field": "mid"}
        result = extract_ids_and_text(data)  # type: ignore[arg-type]

        text = result["test"]
        lines = text.strip().split("\n")

        # Lines should be sorted by field_path (a_field, m_field, z_field)
        assert "a_field" in lines[0]
        assert "m_field" in lines[1]
        assert "z_field" in lines[2]

    def test_nested_element_produces_ref_token(self) -> None:
        """Should produce $ref:child_id for nested elements."""
        data = {
            "id": "parent",
            "child": {"id": "child-1", "text": "child content"},
        }
        result = extract_ids_and_text(data)  # type: ignore[arg-type]

        parent_text = result["parent"]
        assert "$ref:child-1" in parent_text

    def test_ancestor_chain_in_nested_elements(self) -> None:
        """Should include ancestor chain in nested element text."""
        data = {
            "id": "grandparent",
            "sections": [
                {
                    "id": "parent",
                    "items": [
                        {"id": "child", "text": "nested content"},
                    ],
                }
            ],
        }
        result = extract_ids_and_text(data)  # type: ignore[arg-type]

        child_text = result["child"]
        # Should have ancestor chain in format
        assert "[grandparent > parent > child]" in child_text
        assert "text = nested content" in child_text

    def test_real_world_api_patterns_structure(self) -> None:
        """Should handle structure from general.rest.api-patterns.yml."""
        data = {
            "id": "http-methods-section",
            "http_method_defaults": [
                {"method": "GET", "success_status": 200},
                {"method": "POST", "success_status": 201},
            ],
        }
        result = extract_ids_and_text(data)  # type: ignore[arg-type]

        text = result["http-methods-section"]
        # Should have fact-line format
        assert "[http-methods-section]" in text
        # Should include nested dict fields
        assert "http_method_defaults[0].method" in text
        assert "http_method_defaults[0].success_status" in text


class TestComputeElementContentHash:
    """Tests for compute_element_content_hash function."""

    def test_produces_sha256_hash(self) -> None:
        """Should produce a 64-character hex string (SHA-256)."""
        data = {"id": "test", "text": "Hello"}
        result = compute_element_content_hash(data, "test")  # type: ignore[arg-type]

        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_hash_stability(self) -> None:
        """Should produce same hash for equivalent structures."""
        data = {"id": "test", "z_field": "last", "a_field": "first"}
        hash1 = compute_element_content_hash(data, "test")  # type: ignore[arg-type]
        hash2 = compute_element_content_hash(data, "test")  # type: ignore[arg-type]

        assert hash1 == hash2

    def test_hash_changes_with_value_change(self) -> None:
        """Should produce different hash when field values change."""
        data1 = {"id": "test", "text": "Hello"}
        data2 = {"id": "test", "text": "World"}

        hash1 = compute_element_content_hash(data1, "test")  # type: ignore[arg-type]
        hash2 = compute_element_content_hash(data2, "test")  # type: ignore[arg-type]

        assert hash1 != hash2

    def test_hash_changes_with_field_name_change(self) -> None:
        """Should produce different hash when field names change."""
        data1 = {"id": "test", "text": "Hello"}
        data2 = {"id": "test", "content": "Hello"}

        hash1 = compute_element_content_hash(data1, "test")  # type: ignore[arg-type]
        hash2 = compute_element_content_hash(data2, "test")  # type: ignore[arg-type]

        assert hash1 != hash2

    def test_hash_independent_of_nested_element_internals(self) -> None:
        """Should not change when nested element internals change.

        Due to $ref replacement, parent hash is independent of child content.
        """
        data1 = {
            "id": "parent",
            "child": {"id": "child-1", "text": "Version 1"},
        }
        data2 = {
            "id": "parent",
            "child": {"id": "child-1", "text": "Version 2"},
        }

        # Parent hash should be same (child is replaced with $ref)
        parent_hash1 = compute_element_content_hash(data1, "parent")  # type: ignore[arg-type]
        parent_hash2 = compute_element_content_hash(data2, "parent")  # type: ignore[arg-type]

        assert parent_hash1 == parent_hash2

        # Child hashes should differ
        child_hash1 = compute_element_content_hash(data1, "child-1")  # type: ignore[arg-type]
        child_hash2 = compute_element_content_hash(data2, "child-1")  # type: ignore[arg-type]

        assert child_hash1 != child_hash2

    def test_raises_for_missing_element(self) -> None:
        """Should raise KeyError for non-existent element ID."""
        data = {"id": "test", "text": "Hello"}

        with pytest.raises(KeyError) as exc_info:
            compute_element_content_hash(data, "nonexistent")  # type: ignore[arg-type]

        assert "nonexistent" in str(exc_info.value)

    def test_hash_includes_all_fields(self) -> None:
        """Should include all FieldFact fields in hash computation."""
        import hashlib
        import json

        data = {"id": "test", "text": "Hello", "count": 5}
        result = compute_element_content_hash(data, "test")  # type: ignore[arg-type]

        # Manual computation to verify
        from scripts.knowledge.compare_yaml_docs import _iter_field_facts, extract_ids_and_objects

        sliced_objects, edges = extract_ids_and_objects(data)
        facts = _iter_field_facts("test", sliced_objects["test"], [], "")
        payload = [
            {"field_path": f.field_path, "value_kind": f.value_kind, "value": f.value}
            for f in sorted(facts, key=lambda f: f.field_path)
        ]
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(blob.encode("utf-8")).hexdigest()

        assert result == expected
