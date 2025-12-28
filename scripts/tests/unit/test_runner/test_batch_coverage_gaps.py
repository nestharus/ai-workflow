import json
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

from scripts.dev.test_runner.batch_coverage_gaps import (
    FailingFunction,
    create_batches,
    get_test_file_path,
    group_by_test_file,
    main,
    query_failing_functions,
    write_batch_file,
)


@pytest.fixture
def temp_db() -> Iterator[Path]:
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    try:
        yield db_path
    finally:
        if db_path.exists():
            db_path.unlink()


@pytest.fixture
def initialized_db(temp_db: Path) -> Path:
    """Create and initialize a temporary database with required schema."""
    conn = sqlite3.connect(temp_db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cc_function_coverage (
            file_path TEXT,
            function_name TEXT,
            tier TEXT,
            line_coverage_pct REAL,
            branch_coverage_pct REAL,
            threshold_line REAL,
            threshold_branch REAL,
            missing_lines TEXT,
            missing_branches TEXT,
            line_pass INTEGER,
            branch_pass INTEGER
        )
    """)
    conn.commit()
    conn.close()
    return temp_db


class TestMain:
    def test_main_with_no_failing_functions(
        self, initialized_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main when there are no failing functions."""
        output_dir = tmp_path / "batches"

        with mock.patch(
            "sys.argv",
            [
                "batch_coverage_gaps.py",
                "--db-path",
                str(initialized_db),
                "--output-dir",
                str(output_dir),
            ],
        ):
            main()

        captured = capsys.readouterr()
        assert "No failing functions found!" in captured.out

    def test_main_creates_batch_files(
        self, initialized_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that main creates batch files."""
        # Insert some failing functions
        conn = sqlite3.connect(initialized_db)
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "app/main.py",
                "func1",
                "unit",
                50.0,
                50.0,
                80.0,
                70.0,
                "[1, 2]",
                "[]",
                0,
                0,
            ),
        )
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "app/other.py",
                "func2",
                "unit",
                60.0,
                60.0,
                80.0,
                70.0,
                "[3, 4]",
                "[]",
                0,
                0,
            ),
        )
        conn.commit()
        conn.close()

        output_dir = tmp_path / "batches"

        with mock.patch(
            "sys.argv",
            [
                "batch_coverage_gaps.py",
                "--db-path",
                str(initialized_db),
                "--output-dir",
                str(output_dir),
            ],
        ):
            main()

        captured = capsys.readouterr()
        assert "Found 2 failing functions" in captured.out
        assert output_dir.exists()
        assert (output_dir / "manifest.json").exists()

    def test_main_with_tier_filter(
        self, initialized_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main with tier filter."""
        # Insert failing functions in different tiers
        conn = sqlite3.connect(initialized_db)
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "app/main.py",
                "func1",
                "unit",
                50.0,
                50.0,
                80.0,
                70.0,
                "[]",
                "[]",
                0,
                0,
            ),
        )
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "scripts/test.py",
                "func2",
                "scripts",
                50.0,
                50.0,
                80.0,
                70.0,
                "[]",
                "[]",
                0,
                0,
            ),
        )
        conn.commit()
        conn.close()

        output_dir = tmp_path / "batches"

        with mock.patch(
            "sys.argv",
            [
                "batch_coverage_gaps.py",
                "--tier",
                "unit",
                "--db-path",
                str(initialized_db),
                "--output-dir",
                str(output_dir),
            ],
        ):
            main()

        captured = capsys.readouterr()
        assert "Found 1 failing functions" in captured.out

    def test_main_cleans_old_batch_files(self, initialized_db: Path, tmp_path: Path) -> None:
        """Test that main cleans old batch files before creating new ones."""
        output_dir = tmp_path / "batches"
        output_dir.mkdir(parents=True)

        # Create old batch file
        old_batch = output_dir / "batch_999.json"
        old_batch.write_text("{}")

        with mock.patch(
            "sys.argv",
            [
                "batch_coverage_gaps.py",
                "--db-path",
                str(initialized_db),
                "--output-dir",
                str(output_dir),
            ],
        ):
            main()

        assert not old_batch.exists()

    def test_main_writes_manifest(self, initialized_db: Path, tmp_path: Path) -> None:
        """Test that main writes manifest with correct data."""
        # Insert a failing function
        conn = sqlite3.connect(initialized_db)
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "app/main.py",
                "func1",
                "unit",
                50.0,
                50.0,
                80.0,
                70.0,
                "[]",
                "[]",
                0,
                0,
            ),
        )
        conn.commit()
        conn.close()

        output_dir = tmp_path / "batches"

        with mock.patch(
            "sys.argv",
            [
                "batch_coverage_gaps.py",
                "--db-path",
                str(initialized_db),
                "--output-dir",
                str(output_dir),
                "--batch-size",
                "5",
            ],
        ):
            main()

        manifest_path = output_dir / "manifest.json"
        assert manifest_path.exists()

        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["total_functions"] == 1
        assert manifest["batch_size"] == 5
        assert "batch_files" in manifest

    def test_main_prints_batch_summary(
        self, initialized_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that main prints batch summary with test file counts."""
        # Insert multiple failing functions across different test files
        conn = sqlite3.connect(initialized_db)
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "app/main.py",
                "func1",
                "unit",
                50.0,
                50.0,
                80.0,
                70.0,
                "[1]",
                "[]",
                0,
                0,
            ),
        )
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "app/main.py",
                "func2",
                "unit",
                50.0,
                50.0,
                80.0,
                70.0,
                "[2]",
                "[]",
                0,
                0,
            ),
        )
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "app/other.py",
                "func3",
                "unit",
                50.0,
                50.0,
                80.0,
                70.0,
                "[3]",
                "[]",
                0,
                0,
            ),
        )
        conn.commit()
        conn.close()

        output_dir = tmp_path / "batches"

        with mock.patch(
            "sys.argv",
            [
                "batch_coverage_gaps.py",
                "--db-path",
                str(initialized_db),
                "--output-dir",
                str(output_dir),
            ],
        ):
            main()

        captured = capsys.readouterr()
        assert "Found 3 failing functions" in captured.out
        assert "Grouped into 2 test files" in captured.out
        assert "Created 1 batches" in captured.out
        assert "Batch 1:" in captured.out
        assert "3 functions across 2 test files" in captured.out
        assert "Manifest written to" in captured.out

    def test_main_handles_multiple_batches(
        self, initialized_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main with multiple batches."""
        # Insert many failing functions
        conn = sqlite3.connect(initialized_db)
        for i in range(15):
            conn.execute(
                """
                INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"app/file{i}.py",
                    "func1",
                    "unit",
                    50.0,
                    50.0,
                    80.0,
                    70.0,
                    "[]",
                    "[]",
                    0,
                    0,
                ),
            )
        conn.commit()
        conn.close()

        output_dir = tmp_path / "batches"

        with mock.patch(
            "sys.argv",
            [
                "batch_coverage_gaps.py",
                "--db-path",
                str(initialized_db),
                "--output-dir",
                str(output_dir),
                "--batch-size",
                "5",
            ],
        ):
            main()

        captured = capsys.readouterr()
        assert "Found 15 failing functions" in captured.out
        assert "Created" in captured.out
        # Should create multiple batch files
        batch_files = list(output_dir.glob("batch_*.json"))
        assert len(batch_files) >= 2

    def test_main_manifest_contains_tier_filter(self, initialized_db: Path, tmp_path: Path) -> None:
        """Test that manifest includes tier filter when specified."""
        # Insert a failing function
        conn = sqlite3.connect(initialized_db)
        conn.execute(
            """
            INSERT INTO cc_function_coverage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "app/main.py",
                "func1",
                "unit",
                50.0,
                50.0,
                80.0,
                70.0,
                "[]",
                "[]",
                0,
                0,
            ),
        )
        conn.commit()
        conn.close()

        output_dir = tmp_path / "batches"

        with mock.patch(
            "sys.argv",
            [
                "batch_coverage_gaps.py",
                "--tier",
                "unit",
                "--db-path",
                str(initialized_db),
                "--output-dir",
                str(output_dir),
            ],
        ):
            main()

        manifest_path = output_dir / "manifest.json"
        with open(manifest_path) as f:
            manifest = json.load(f)

        assert manifest["tier_filter"] == "unit"
