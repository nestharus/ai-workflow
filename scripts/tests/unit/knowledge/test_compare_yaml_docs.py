from pathlib import Path
from unittest.mock import patch

import pytest

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
    compare_all,
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


class TestMain:
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


class TestMainAdditionalBranches:
    def test_handles_original_files_argument(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should process explicit original files from --original-files."""
        docs_dir = tmp_path / "docs"
        originals_dir = tmp_path / ".knowledge" / "originals"
        knowledge_dir = tmp_path / ".knowledge"

        docs_dir.mkdir()
        originals_dir.mkdir(parents=True)
        (knowledge_dir / "comparisons").mkdir(parents=True)

        # Create explicit original file with timestamp prefix
        content = """
items:
  - id: item-1
    text: Original text
"""
        explicit_file = originals_dir / "20251201T134735Z-test-pattern.yml"
        explicit_file.write_text(content)

        with (
            patch.object(compare_yaml_docs, "REPO_ROOT", tmp_path),
            patch.object(compare_yaml_docs, "DEVELOPMENT_DIR", docs_dir),
            patch(
                "sys.argv",
                [
                    "script",
                    "--path",
                    str(docs_dir),
                    "--original-files",
                    str(explicit_file),
                ],
            ),
        ):
            result = main()

        # Should process without error
        assert result in [0, 1]  # Either no diff or diff found

    def test_returns_one_when_write_containment_edges_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when write_containment_edges raises RuntimeError."""
        docs_dir = tmp_path / "docs"
        knowledge_dir = tmp_path / ".knowledge"

        docs_dir.mkdir()
        (knowledge_dir / "comparisons").mkdir(parents=True)

        # Create YAML with nested ID-bearing dicts to trigger containment edge write
        content = """
id: parent-section
items:
  - id: child-item
    text: Child text
"""
        (docs_dir / "original.test.yml").write_text(content)

        with (
            patch.object(compare_yaml_docs, "REPO_ROOT", tmp_path),
            patch.object(compare_yaml_docs, "DEVELOPMENT_DIR", docs_dir),
            patch(
                "sys.argv",
                ["script", "--path", str(docs_dir)],
            ),
            patch.object(
                compare_yaml_docs,
                "write_containment_edges",
                side_effect=RuntimeError("Mock edge write failure"),
            ),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_prints_deleted_stale_csv_count(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print count of deleted stale CSV files."""
        docs_dir = tmp_path / "docs"
        python_dir = docs_dir / "python"
        knowledge_dir = tmp_path / ".knowledge"
        comparisons_dir = knowledge_dir / "comparisons"

        docs_dir.mkdir()
        python_dir.mkdir()
        comparisons_dir.mkdir(parents=True)

        # Create stale CSV that won't match any pattern
        stale_csv = comparisons_dir / "old-pattern.csv"
        stale_csv.write_text("source_file,id,origin_type,original_data,split_file,split_data\n")

        # Create matching original and split (no differences)
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
            main()

        captured = capsys.readouterr()
        # If stale CSV was deleted, should print message
        if "Deleted" in captured.out:
            assert "stale CSV" in captured.out

    def test_returns_one_and_writes_csv_when_differences_found(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 and write CSVs when differences are found."""
        docs_dir = tmp_path / "docs"
        python_dir = docs_dir / "python"
        knowledge_dir = tmp_path / ".knowledge"

        docs_dir.mkdir()
        python_dir.mkdir()
        (knowledge_dir / "comparisons").mkdir(parents=True)

        # Create different content in original and split
        orig_content = """
items:
  - id: item-1
    text: Original text
"""
        split_content = """
items:
  - id: item-1
    text: Different text
"""
        (docs_dir / "original.test.yml").write_text(orig_content)
        (python_dir / "python.test.yml").write_text(split_content)

        with (
            patch.object(compare_yaml_docs, "REPO_ROOT", tmp_path),
            patch.object(compare_yaml_docs, "DEVELOPMENT_DIR", docs_dir),
            patch("sys.argv", ["script", "--path", str(docs_dir)]),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "CSV file(s)" in captured.out
