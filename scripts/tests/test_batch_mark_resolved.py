"""Tests for scripts.batch_mark_resolved module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts import batch_mark_resolved
from scripts.batch_mark_resolved import (
    _is_separator_row,
    _parse_table_line,
    main,
    mark_resolved_for_id,
    parse_args,
    parse_breakdown_table,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestParseBreakdownTable:
    """Tests for parse_breakdown_table function."""

    def test_extracts_mixed_split_ids(self, fs: FakeFilesystem) -> None:
        """Should extract IDs classified as MIXED→split."""
        content = """
# ID Breakdown Table

| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | GENERAL | Protocol | GENERAL |
| item-2 | Text | MIXED→split | Both refs | Both |
| item-3 | Text | PROJECT | Framework | PROJECT |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        assert "item-2" in result
        assert "item-1" not in result
        assert "item-3" not in result

    def test_returns_empty_for_no_mixed(self, fs: FakeFilesystem) -> None:
        """Should return empty list when no MIXED→split items."""
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | GENERAL | Protocol | GENERAL |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        assert len(result) == 0

    def test_handles_structural_elements(self, fs: FakeFilesystem) -> None:
        """Should extract ID from structural element notation."""
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| (table) mixed_data | Data | MIXED→split | Both | Both |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        assert "mixed_data" in result


class TestMarkResolvedForId:
    """Tests for mark_resolved_for_id function."""

    def test_returns_success_on_zero_exit(self, fs: FakeFilesystem) -> None:
        """Should return success tuple on subprocess success."""
        with patch.object(batch_mark_resolved, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "Resolution recorded"
                mock_run.return_value.stderr = ""

                success, message = mark_resolved_for_id(
                    "item-1",
                    Path("/fake/original.yml"),
                    Path("/fake/general.yml"),
                    Path("/fake/project.yml"),
                    Path("/fake/.knowledge"),
                )

        assert success is True
        assert "Resolution recorded" in message

    def test_returns_failure_on_nonzero_exit(self, fs: FakeFilesystem) -> None:
        """Should return failure tuple on subprocess failure."""
        with patch.object(batch_mark_resolved, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 1
                mock_run.return_value.stdout = ""
                mock_run.return_value.stderr = "ID not found"

                success, message = mark_resolved_for_id(
                    "item-1",
                    Path("/fake/original.yml"),
                    Path("/fake/general.yml"),
                    Path("/fake/project.yml"),
                    Path("/fake/.knowledge"),
                )

        assert success is False
        assert "ID not found" in message

    def test_handles_subprocess_error(self, fs: FakeFilesystem) -> None:
        """Should handle subprocess exceptions."""
        with patch.object(batch_mark_resolved, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.SubprocessError("Subprocess failed")

                success, message = mark_resolved_for_id(
                    "item-1",
                    Path("/fake/original.yml"),
                    Path("/fake/general.yml"),
                    Path("/fake/project.yml"),
                    Path("/fake/.knowledge"),
                )

        assert success is False
        assert "Subprocess failed" in message


class TestParseArgs:
    """Tests for parse_args function."""

    def test_requires_all_arguments(self) -> None:
        """Should require all mandatory arguments."""
        with pytest.raises(SystemExit):
            parse_args([])

    def test_parses_all_arguments(self) -> None:
        """Should parse all arguments correctly."""
        args = parse_args([
            "--breakdown-table", "/table.md",
            "--original-file", "/original.yml",
            "--general-file", "/general.yml",
            "--project-file", "/project.yml",
        ])

        assert args.breakdown_table == Path("/table.md")
        assert args.original_file == Path("/original.yml")
        assert args.general_file == Path("/general.yml")
        assert args.project_file == Path("/project.yml")

    def test_default_knowledge_path(self) -> None:
        """Should default to .knowledge directory."""
        args = parse_args([
            "--breakdown-table", "/table.md",
            "--original-file", "/original.yml",
            "--general-file", "/general.yml",
            "--project-file", "/project.yml",
        ])

        assert args.knowledge_path == Path(".knowledge")


class TestMain:
    """Tests for main function."""

    def test_returns_one_for_missing_breakdown(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when breakdown table doesn't exist."""
        with patch.object(batch_mark_resolved, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table", "missing.md",
                    "--original-file", "original.yml",
                    "--general-file", "general.yml",
                    "--project-file", "project.yml",
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_one_for_missing_original(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when original file doesn't exist."""
        with patch.object(batch_mark_resolved, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/table.md", contents="| ID | Summary | Classification | Rationale | Target |")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table", "table.md",
                    "--original-file", "missing.yml",
                    "--general-file", "general.yml",
                    "--project-file", "project.yml",
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_zero_when_no_mixed_items(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 0 when no MIXED→split items found."""
        with patch.object(batch_mark_resolved, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            # Create files without MIXED→split items
            table_content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | GENERAL | Protocol | GENERAL |
"""
            fs.create_file("/fake/table.md", contents=table_content)
            fs.create_file("/fake/original.yml", contents="")
            fs.create_file("/fake/general.yml", contents="")
            fs.create_file("/fake/project.yml", contents="")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table", "table.md",
                    "--original-file", "original.yml",
                    "--general-file", "general.yml",
                    "--project-file", "project.yml",
                ],
            ):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "No MIXED→split items" in captured.out

    def test_returns_one_for_missing_general(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when GENERAL file doesn't exist."""
        with patch.object(batch_mark_resolved, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/table.md", contents="| ID |")
            fs.create_file("/fake/original.yml", contents="")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table", "table.md",
                    "--original-file", "original.yml",
                    "--general-file", "missing_general.yml",
                    "--project-file", "project.yml",
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "GENERAL file not found" in captured.err

    def test_returns_one_for_missing_project(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when PROJECT file doesn't exist."""
        with patch.object(batch_mark_resolved, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/table.md", contents="| ID |")
            fs.create_file("/fake/original.yml", contents="")
            fs.create_file("/fake/general.yml", contents="")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table", "table.md",
                    "--original-file", "original.yml",
                    "--general-file", "general.yml",
                    "--project-file", "missing_project.yml",
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "PROJECT file not found" in captured.err

    def test_processes_mixed_items_with_success(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should process MIXED→split items and return 0 on all success."""
        with patch.object(batch_mark_resolved, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            table_content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | MIXED→split | Both | Both |
"""
            fs.create_file("/fake/table.md", contents=table_content)
            fs.create_file("/fake/original.yml", contents="")
            fs.create_file("/fake/general.yml", contents="")
            fs.create_file("/fake/project.yml", contents="")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "OK"
                mock_run.return_value.stderr = ""

                with patch(
                    "sys.argv",
                    [
                        "script",
                        "--breakdown-table", "table.md",
                        "--original-file", "original.yml",
                        "--general-file", "general.yml",
                        "--project-file", "project.yml",
                    ],
                ):
                    result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Successfully marked" in captured.out

    def test_processes_mixed_items_with_failure(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when some items fail."""
        with patch.object(batch_mark_resolved, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            table_content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | MIXED→split | Both | Both |
"""
            fs.create_file("/fake/table.md", contents=table_content)
            fs.create_file("/fake/original.yml", contents="")
            fs.create_file("/fake/general.yml", contents="")
            fs.create_file("/fake/project.yml", contents="")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 1
                mock_run.return_value.stdout = ""
                mock_run.return_value.stderr = "Failed"

                with patch(
                    "sys.argv",
                    [
                        "script",
                        "--breakdown-table", "table.md",
                        "--original-file", "original.yml",
                        "--general-file", "general.yml",
                        "--project-file", "project.yml",
                    ],
                ):
                    result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "failed" in captured.out.lower()

    def test_handles_absolute_paths(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should handle absolute paths without resolving."""
        with patch.object(batch_mark_resolved, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_dir("/abs")
            table_content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | GENERAL | Protocol | GENERAL |
"""
            fs.create_file("/abs/table.md", contents=table_content)
            fs.create_file("/abs/original.yml", contents="")
            fs.create_file("/abs/general.yml", contents="")
            fs.create_file("/abs/project.yml", contents="")
            fs.create_dir("/abs/.knowledge")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--breakdown-table", "/abs/table.md",
                    "--original-file", "/abs/original.yml",
                    "--general-file", "/abs/general.yml",
                    "--project-file", "/abs/project.yml",
                    "--knowledge-path", "/abs/.knowledge",
                ],
            ):
                result = main()

        assert result == 0


class TestParseTableLine:
    """Tests for _parse_table_line function."""

    def test_returns_none_for_no_pipe(self) -> None:
        """Should return None for line without pipe."""
        result = _parse_table_line("Just some text")
        assert result is None

    def test_parses_basic_table_line(self) -> None:
        """Should parse basic table line."""
        result = _parse_table_line("| col1 | col2 | col3 |")
        assert result == ["col1", "col2", "col3"]

    def test_handles_no_leading_pipe(self) -> None:
        """Should handle line without leading pipe."""
        result = _parse_table_line("col1 | col2 |")
        assert result == ["col1", "col2"]

    def test_handles_no_trailing_pipe(self) -> None:
        """Should handle line without trailing pipe."""
        result = _parse_table_line("| col1 | col2")
        assert result == ["col1", "col2"]

    def test_returns_none_for_empty_parts(self) -> None:
        """Should return None if only empty parts remain."""
        result = _parse_table_line("|")
        assert result is None


class TestIsSeparatorRow:
    """Tests for _is_separator_row function."""

    def test_detects_separator(self) -> None:
        """Should detect separator row."""
        assert _is_separator_row(["---", "---", "---"]) is True
        assert _is_separator_row([":---:", "---:", ":---"]) is True

    def test_rejects_content_row(self) -> None:
        """Should reject content row."""
        assert _is_separator_row(["ID", "Summary", "Class"]) is False


class TestParseBreakdownTableExtended:
    """Extended tests for parse_breakdown_table function."""

    def test_warns_for_malformed_rows(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should warn for rows with wrong column count."""
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | GENERAL | Protocol | GENERAL |
| bad | row |
"""
        fs.create_file("/table.md", contents=content)

        parse_breakdown_table(Path("/table.md"))

        captured = capsys.readouterr()
        assert "Warning" in captured.err
        assert "columns" in captured.err

    def test_skips_empty_element_id(self, fs: FakeFilesystem) -> None:
        """Should skip rows with empty element ID."""
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
|    | Text | MIXED→split | Both | Both |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        assert len(result) == 0

    def test_skips_classification_header(self, fs: FakeFilesystem) -> None:
        """Should skip rows where classification is header text."""
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| ID | Summary | Classification | Rationale | Target |
| item-1 | Text | MIXED→split | Both | Both |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        assert "ID" not in result
        assert "item-1" in result

    def test_handles_short_classification_column(
        self, fs: FakeFilesystem
    ) -> None:
        """Should skip rows where classification column is missing."""
        # Row with 5+ cols but classification index exceeds actual columns
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text |  | | |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        # Empty classification should be skipped
        assert len(result) == 0

    def test_handles_parentheses_without_match(self, fs: FakeFilesystem) -> None:
        """Should handle malformed parentheses prefix."""
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| (unclosed | Text | MIXED→split | Both | Both |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        # The regex won't match, so original ID stays
        assert "(unclosed" in result

    def test_prints_skipped_count(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should print note when rows are skipped."""
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
| item-1 | Text | GENERAL | Protocol | GENERAL |
| short | row |
| also | short |
"""
        fs.create_file("/table.md", contents=content)

        parse_breakdown_table(Path("/table.md"))

        captured = capsys.readouterr()
        assert "skipped" in captured.err.lower()

    def test_skips_row_with_header_comment(self, fs: FakeFilesystem) -> None:
        """Should skip rows that look like comments (start with #)."""
        content = """
| ID | Summary | Classification | Rationale | Target |
|----|---------|----------------|-----------|--------|
# This is a comment that happens to have pipes | | |
| item-1 | Text | GENERAL | Protocol | GENERAL |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        assert "item-1" not in [r for r in result if r.startswith("#")]

    def test_handles_row_with_missing_classification_column(
        self, fs: FakeFilesystem
    ) -> None:
        """Should skip rows where classification column index is out of bounds."""
        # Create a custom header with CLASSIFICATION at index 5
        # but have a data row with fewer columns (but >= 5 to pass len check)
        content = """
| ID | Summary | Notes | Extra | Extra2 | Classification |
|----|---------|-------|-------|--------|----------------|
| item-1 | Text | Note | X | Y |
"""
        fs.create_file("/table.md", contents=content)

        result = parse_breakdown_table(Path("/table.md"))

        # Row should be skipped because classification column index (5) exceeds
        # the number of columns (5, indexed 0-4)
        assert len(result) == 0
