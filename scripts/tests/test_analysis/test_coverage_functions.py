"""Tests for coverage functions tool."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from scripts.dev.test_analysis.coverage_functions import (
    filter_and_sort_functions,
    get_threshold,
)
from scripts.dev.test_runner.coverage_db import (
    init_custom_tables,
    write_function_coverage,
)
from scripts.dev.test_runner.test_coverage import FunctionCoverage


@pytest.fixture
def temp_db() -> Iterator[Path]:
    """Create a temporary database with test data."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    # Initialize database
    init_custom_tables(db_path)

    # Add function coverage with varying coverage levels
    functions = [
        FunctionCoverage(
            file_path="app/services/service_a.py",
            name="function_low",
            start_line=10,
            end_line=20,
            total_lines=10,
            covered_lines=5,
            line_coverage_pct=50.0,
            total_branches=4,
            covered_branches=1,
            branch_coverage_pct=25.0,
            missing_lines=[12, 15, 17, 18, 19],
            missing_branches=[(11, 12)],
        ),
        FunctionCoverage(
            file_path="app/services/service_a.py",
            name="function_medium",
            start_line=30,
            end_line=40,
            total_lines=10,
            covered_lines=7,
            line_coverage_pct=70.0,
            total_branches=2,
            covered_branches=1,
            branch_coverage_pct=50.0,
            missing_lines=[32, 35, 38],
            missing_branches=[],
        ),
        FunctionCoverage(
            file_path="app/services/service_b.py",
            name="function_high",
            start_line=50,
            end_line=60,
            total_lines=10,
            covered_lines=8,
            line_coverage_pct=75.0,
            total_branches=2,
            covered_branches=1,
            branch_coverage_pct=50.0,
            missing_lines=[52, 55],
            missing_branches=[],
        ),
    ]
    write_function_coverage(db_path, "unit", functions, 80.0, 80.0)

    yield db_path

    # Cleanup
    db_path.unlink()


def test_filter_and_sort_functions_default(temp_db: Path) -> None:
    """Test getting functions with default sorting (by line coverage, worst first)."""
    functions = filter_and_sort_functions(temp_db)

    # Should return all 3 functions
    assert len(functions) == 3

    # Should be sorted by line coverage (lowest first)
    assert functions[0]["line_coverage"] == 50.0
    assert functions[1]["line_coverage"] == 70.0
    assert functions[2]["line_coverage"] == 75.0


def test_filter_and_sort_functions_by_branch(temp_db: Path) -> None:
    """Test sorting by branch coverage."""
    functions = filter_and_sort_functions(temp_db, sort_by="branch_coverage")

    # Should be sorted by branch coverage (lowest first)
    assert functions[0]["branch_coverage"] == 25.0
    assert functions[1]["branch_coverage"] >= functions[0]["branch_coverage"]


def test_filter_and_sort_functions_by_file(temp_db: Path) -> None:
    """Test sorting by file path."""
    functions = filter_and_sort_functions(temp_db, sort_by="file")

    # Should be sorted alphabetically by file path
    assert functions[0]["file"] == "app/services/service_a.py"
    assert functions[2]["file"] == "app/services/service_b.py"


def test_filter_and_sort_functions_with_path_filter(temp_db: Path) -> None:
    """Test filtering by path prefix."""
    functions = filter_and_sort_functions(temp_db, path_filter="app/services/service_a")

    # Should return only functions from service_a
    assert len(functions) == 2
    assert all(f["file"] == "app/services/service_a.py" for f in functions)


def test_filter_and_sort_functions_with_limit(temp_db: Path) -> None:
    """Test limiting number of results."""
    functions = filter_and_sort_functions(temp_db, limit=2)

    # Should return only 2 functions
    assert len(functions) == 2

    # Should be the worst 2 (lowest coverage)
    assert functions[0]["line_coverage"] == 50.0
    assert functions[1]["line_coverage"] == 70.0


def test_filter_and_sort_functions_by_missing_lines(temp_db: Path) -> None:
    """Test sorting by missing lines count."""
    functions = filter_and_sort_functions(temp_db, sort_by="missing_lines_count")

    # Should be sorted by missing lines count (most first)
    assert functions[0]["missing_lines_count"] == 5
    assert functions[1]["missing_lines_count"] == 3
    assert functions[2]["missing_lines_count"] == 2


def test_get_threshold(temp_db: Path) -> None:
    """Test getting coverage threshold."""
    threshold = get_threshold(temp_db)

    # Should return default threshold
    assert threshold == 80.0


def test_get_threshold_empty_db() -> None:
    """Test getting threshold from empty database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)

    try:
        init_custom_tables(db_path)
        threshold = get_threshold(db_path)

        # Should return default
        assert threshold == 80.0
    finally:
        db_path.unlink()


def test_filter_and_sort_functions_combined_filters(temp_db: Path) -> None:
    """Test combining path filter, limit, and sorting."""
    functions = filter_and_sort_functions(
        temp_db,
        path_filter="app/services/service_a",
        limit=1,
        sort_by="line_coverage",
    )

    # Should return only 1 function from service_a with lowest coverage
    assert len(functions) == 1
    assert functions[0]["file"] == "app/services/service_a.py"
    assert functions[0]["line_coverage"] == 50.0


def test_filter_and_sort_functions_by_function(temp_db: Path) -> None:
    """Test sorting by function name."""
    functions = filter_and_sort_functions(temp_db, sort_by="function")

    # Should be sorted alphabetically by function name
    function_names = [f["function"] for f in functions]
    assert function_names == sorted(function_names)


class TestPrintFunctions:
    """Tests for print_functions function."""

    def test_print_functions_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test print_functions with empty list."""
        from scripts.dev.test_analysis.coverage_functions import print_functions

        print_functions([], threshold=80.0)
        captured = capsys.readouterr()
        assert "No functions below threshold" in captured.out

    def test_print_functions_with_data(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test print_functions with function entries."""
        from scripts.dev.test_analysis.coverage_functions import print_functions

        functions = [
            {
                "file": "app/services/test.py",
                "function": "test_func",
                "line_coverage": 50.0,
                "branch_coverage": 40.0,
                "missing_lines": [10, 12, 15],
                "missing_lines_count": 3,
            },
            {
                "file": "app/api/router.py",
                "function": "get_data",
                "line_coverage": 60.0,
                "branch_coverage": 55.0,
                "missing_lines": [20, 25],
                "missing_lines_count": 2,
            },
        ]
        print_functions(functions, threshold=80.0)
        captured = capsys.readouterr()

        # Check header
        assert "FILE" in captured.out
        assert "FUNCTION" in captured.out
        assert "LINE" in captured.out
        assert "BRANCH" in captured.out
        assert "MISS" in captured.out

        # Check data
        assert "app/services/test.py" in captured.out or "test.py" in captured.out
        assert "test_func" in captured.out

        # Check footer
        assert "Total functions below threshold: 2" in captured.out

    def test_print_functions_truncates_long_paths(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test print_functions truncates long file paths."""
        from scripts.dev.test_analysis.coverage_functions import print_functions

        functions = [
            {
                "file": "app/some/very/long/path/to/deeply/nested/file/service.py",
                "function": "very_long_function_name_that_needs_truncation",
                "line_coverage": 50.0,
                "branch_coverage": 40.0,
                "missing_lines": [10],
                "missing_lines_count": 1,
            },
        ]
        print_functions(functions, threshold=80.0)
        captured = capsys.readouterr()

        # Should contain truncation markers
        assert "..." in captured.out
        assert "Total functions below threshold: 1" in captured.out


class TestMain:
    """Tests for main function."""

    def test_main_db_not_found(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main when database doesn't exist."""
        from scripts.dev.test_analysis.coverage_functions import main

        # Use a non-existent database path
        monkeypatch.setattr(
            "sys.argv",
            ["coverage-functions", "--db", "/nonexistent/path/to/coverage.db"],
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
        import json

        from scripts.dev.test_analysis.coverage_functions import main

        monkeypatch.setattr(
            "sys.argv",
            ["coverage-functions", "--db", str(temp_db), "--json"],
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
        from scripts.dev.test_analysis.coverage_functions import main

        monkeypatch.setattr(
            "sys.argv",
            [
                "coverage-functions",
                "--db",
                str(temp_db),
                "--filter",
                "app/services/service_a",
                "--limit",
                "1",
                "--sort",
                "line_coverage",
            ],
        )

        result = main()

        assert result == 0
        captured = capsys.readouterr()
        # Should show function from service_a
        assert "service_a" in captured.out

    def test_main_default_text_output(
        self,
        temp_db: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main with default text output."""
        from scripts.dev.test_analysis.coverage_functions import main

        monkeypatch.setattr(
            "sys.argv",
            ["coverage-functions", "--db", str(temp_db)],
        )

        result = main()

        assert result == 0
        captured = capsys.readouterr()
        # Should have human-readable format with threshold info
        assert "FILE" in captured.out or "below" in captured.out

    def test_main_with_database_error(
        self,
        temp_db: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main handling of database errors."""
        from typing import Any

        from scripts.dev.test_analysis.coverage_functions import main

        # Make filter_and_sort_functions raise an exception
        def mock_filter(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
            msg = "Database corruption"
            raise RuntimeError(msg)

        monkeypatch.setattr(
            "scripts.dev.test_analysis.coverage_functions.filter_and_sort_functions",
            mock_filter,
        )
        monkeypatch.setattr(
            "sys.argv",
            ["coverage-functions", "--db", str(temp_db)],
        )

        result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_main_with_all_sort_options(
        self,
        temp_db: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main with various sort options."""
        from scripts.dev.test_analysis.coverage_functions import main

        for sort_option in [
            "line_coverage",
            "branch_coverage",
            "file",
            "function",
            "missing_lines_count",
        ]:
            monkeypatch.setattr(
                "sys.argv",
                [
                    "coverage-functions",
                    "--db",
                    str(temp_db),
                    "--sort",
                    sort_option,
                ],
            )

            result = main()
            assert result == 0
