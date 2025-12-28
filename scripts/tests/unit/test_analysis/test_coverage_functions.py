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


class TestMain:
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
