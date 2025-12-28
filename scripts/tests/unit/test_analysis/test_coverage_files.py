import json
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

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


class TestMain:
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
