"""Tests for coverage files tool."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from scripts.dev.test_analysis.coverage_files import (
    aggregate_files,
    format_file_entry,
    get_files_with_issues,
)
from scripts.dev.test_runner.coverage_db import (
    init_custom_tables,
    write_function_coverage,
    write_missing_lines,
)
from scripts.dev.test_runner.test_coverage import (
    FunctionCoverage,
    MissingLineDetail,
)


@pytest.fixture
def temp_db() -> Generator[Path]:
    """Create a temporary database with test data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    # Initialize database
    init_custom_tables(db_path)

    # Add function coverage
    functions = [
        FunctionCoverage(
            file_path="app/services/service_a.py",
            name="function_a",
            start_line=10,
            end_line=20,
            total_lines=10,
            covered_lines=7,
            line_coverage_pct=70.0,
            total_branches=4,
            covered_branches=2,
            branch_coverage_pct=50.0,
            missing_lines=[12, 15, 18],
            missing_branches=[(11, 12)],
        ),
        FunctionCoverage(
            file_path="app/services/service_b.py",
            name="function_b",
            start_line=30,
            end_line=40,
            total_lines=10,
            covered_lines=6,
            line_coverage_pct=60.0,
            total_branches=2,
            covered_branches=1,
            branch_coverage_pct=50.0,
            missing_lines=[32, 35],
            missing_branches=[],
        ),
    ]
    write_function_coverage(db_path, "unit", functions, 80.0, 80.0)

    # Add missing lines
    missing_lines = [
        MissingLineDetail(
            file="app/services/service_a.py",
            line_number=12,
            content="    return None",
            context_before=[],
            context_after=[],
            missing_branch_exits=[13, 14],
        ),
        MissingLineDetail(
            file="app/services/service_b.py",
            line_number=32,
            content="    pass",
            context_before=[],
            context_after=[],
            missing_branch_exits=[],
        ),
    ]
    write_missing_lines(db_path, missing_lines)

    yield db_path

    # Cleanup
    db_path.unlink()


def test_aggregate_files(temp_db: Path) -> None:
    """Test aggregating coverage issues by file."""
    from scripts.dev.test_analysis.common import (
        get_functions_below_threshold,
        get_missing_lines,
    )

    functions = get_functions_below_threshold(temp_db)
    missing_lines = get_missing_lines(temp_db)

    files = aggregate_files(functions, missing_lines)

    # Check both files are present
    assert "app/services/service_a.py" in files
    assert "app/services/service_b.py" in files

    # Check service_a data
    assert len(files["app/services/service_a.py"]["missing_lines"]) == 1
    assert len(files["app/services/service_a.py"]["missing_branches"]) == 2
    assert len(files["app/services/service_a.py"]["functions_below_threshold"]) == 1

    # Check service_b data
    assert len(files["app/services/service_b.py"]["missing_lines"]) == 1
    assert len(files["app/services/service_b.py"]["missing_branches"]) == 0
    assert len(files["app/services/service_b.py"]["functions_below_threshold"]) == 1


def test_format_file_entry() -> None:
    """Test formatting file entry for output."""
    info = {
        "missing_lines": [1, 2, 3],
        "missing_branches": [4, 5],
        "functions_below_threshold": [{"name": "func1"}, {"name": "func2"}],
    }

    entry = format_file_entry("test/file.py", info)

    assert entry["file"] == "test/file.py"
    assert entry["missing_lines_count"] == 3
    assert entry["missing_branches_count"] == 2
    assert entry["functions_below_threshold"] == 2
    assert entry["total_issues"] == 7


def test_get_files_with_issues(temp_db: Path) -> None:
    """Test getting files with coverage issues."""
    files = get_files_with_issues(temp_db)

    # Should return 2 files
    assert len(files) == 2

    # Check sorting (default is by total_issues)
    assert all("file" in f for f in files)
    assert all("total_issues" in f for f in files)


def test_get_files_with_issues_filter(temp_db: Path) -> None:
    """Test filtering files by path prefix."""
    files = get_files_with_issues(temp_db, path_filter="app/services/service_a")

    # Should return only service_a
    assert len(files) == 1
    assert files[0]["file"] == "app/services/service_a.py"


def test_get_files_with_issues_limit(temp_db: Path) -> None:
    """Test limiting number of results."""
    files = get_files_with_issues(temp_db, limit=1)

    # Should return only 1 file
    assert len(files) == 1


def test_get_files_with_issues_sort_by_file(temp_db: Path) -> None:
    """Test sorting files by filename."""
    files = get_files_with_issues(temp_db, sort_by="file")

    # Should be sorted alphabetically
    assert files[0]["file"] == "app/services/service_a.py"
    assert files[1]["file"] == "app/services/service_b.py"


def test_aggregate_files_empty_lists() -> None:
    """Test aggregate_files with empty input lists.

    This covers the branches at lines 53 and 61 where the loops don't execute.
    """
    files = aggregate_files([], [])

    # Empty input should return empty dict
    assert files == {}


def test_aggregate_files_empty_missing_lines() -> None:
    """Test aggregate_files with empty missing_lines list."""
    functions = [
        {
            "file_path": "app/test.py",
            "function_name": "test_func",
            "line_coverage_pct": 50.0,
            "branch_coverage_pct": 50.0,
        }
    ]
    files = aggregate_files(functions, [])

    assert "app/test.py" in files
    assert files["app/test.py"]["missing_lines"] == []
    assert files["app/test.py"]["functions_below_threshold"][0]["name"] == "test_func"


def test_aggregate_files_empty_functions() -> None:
    """Test aggregate_files with empty functions list."""
    missing_lines = [
        {
            "file_path": "app/test.py",
            "line_number": 10,
            "missing_branch_exits": [11],
        }
    ]
    files = aggregate_files([], missing_lines)

    assert "app/test.py" in files
    assert files["app/test.py"]["missing_lines"] == [10]
    assert files["app/test.py"]["missing_branches"] == [11]
    assert files["app/test.py"]["functions_below_threshold"] == []


class TestPrintFiles:
    """Tests for print_files function."""

    def test_print_files_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test print_files with empty list."""
        from scripts.dev.test_analysis.coverage_files import print_files

        print_files([])
        captured = capsys.readouterr()
        assert "No files with coverage issues found" in captured.out

    def test_print_files_with_data(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test print_files with file entries."""
        from scripts.dev.test_analysis.coverage_files import print_files

        entries = [
            {
                "file": "app/services/test.py",
                "missing_lines_count": 5,
                "missing_branches_count": 2,
                "functions_below_threshold": 1,
                "total_issues": 8,
            },
            {
                "file": "app/api/router.py",
                "missing_lines_count": 10,
                "missing_branches_count": 3,
                "functions_below_threshold": 2,
                "total_issues": 15,
            },
        ]
        print_files(entries)
        captured = capsys.readouterr()

        # Check header
        assert "FILE" in captured.out
        assert "LINES" in captured.out
        assert "BRANCH" in captured.out
        assert "FUNCS" in captured.out
        assert "TOTAL" in captured.out

        # Check data
        assert "app/services/test.py" in captured.out
        assert "app/api/router.py" in captured.out

        # Check footer
        assert "Total files: 2" in captured.out


class TestMain:
    """Tests for main function."""

    def test_main_db_not_found(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main when database doesn't exist."""
        from scripts.dev.test_analysis.coverage_files import main

        # Use a non-existent database path
        monkeypatch.setattr(
            "sys.argv",
            ["coverage-files", "--db", "/nonexistent/path/to/coverage.db"],
        )

        result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error: Coverage database not found" in captured.err

    def test_main_with_json_output(
        self,
        temp_db: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main with JSON output flag."""
        from scripts.dev.test_analysis.coverage_files import main

        monkeypatch.setattr(
            "sys.argv",
            ["coverage-files", "--db", str(temp_db), "--json"],
        )

        result = main()

        assert result == 0
        captured = capsys.readouterr()
        # Should be valid JSON
        data = json.loads(captured.out)
        assert isinstance(data, list)

    def test_main_with_filter_and_limit(
        self,
        temp_db: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main with filter and limit options."""
        from scripts.dev.test_analysis.coverage_files import main

        monkeypatch.setattr(
            "sys.argv",
            [
                "coverage-files",
                "--db",
                str(temp_db),
                "--filter",
                "app/services/service_a",
                "--limit",
                "1",
                "--sort",
                "file",
            ],
        )

        result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "app/services/service_a.py" in captured.out

    def test_main_default_text_output(
        self,
        temp_db: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main with default text output."""
        from scripts.dev.test_analysis.coverage_files import main

        monkeypatch.setattr(
            "sys.argv",
            ["coverage-files", "--db", str(temp_db)],
        )

        result = main()

        assert result == 0
        captured = capsys.readouterr()
        # Should have human-readable format
        assert "FILE" in captured.out
        assert "LINES" in captured.out

    def test_main_with_database_error(
        self,
        temp_db: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main handling of database errors."""
        from scripts.dev.test_analysis.coverage_files import main

        # Make get_files_with_issues raise an exception
        def mock_get_files_with_issues(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            msg = "Database corruption"
            raise RuntimeError(msg)

        monkeypatch.setattr(
            "scripts.dev.test_analysis.coverage_files.get_files_with_issues",
            mock_get_files_with_issues,
        )
        monkeypatch.setattr(
            "sys.argv",
            ["coverage-files", "--db", str(temp_db)],
        )

        result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err
