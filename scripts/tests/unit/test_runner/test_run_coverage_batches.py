import json
import sqlite3
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import pytest

from scripts.dev.test_runner.run_coverage_batches import (
    generate_agent_prompt,
    main,
    print_summary,
    run_batching,
    run_test_coverage,
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
        CREATE TABLE IF NOT EXISTS cc_tier_summary (
            tier TEXT,
            failing_functions INTEGER,
            total_functions INTEGER,
            tier_pass INTEGER
        )
    """)
    conn.commit()
    conn.close()
    return temp_db


class TestRunTestCoverage:
    def test_runs_test_coverage_command(
        self, initialized_db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run_test_coverage calls subprocess correctly."""
        # Insert test data
        conn = sqlite3.connect(initialized_db)
        conn.execute(
            "INSERT INTO cc_tier_summary VALUES (?, ?, ?, ?)",
            ("unit", 2, 10, 0),
        )
        conn.commit()
        conn.close()

        # Mock the coverage database path
        coverage_dir = tmp_path / ".coverage"
        coverage_dir.mkdir()
        db_file = coverage_dir / "coverage.db"
        # Copy the initialized db to the expected location
        import shutil

        shutil.copy(initialized_db, db_file)

        with mock.patch("scripts.dev.test_runner.run_coverage_batches.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            # Mock sqlite3 via sys.modules
            mock_sqlite3 = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_cursor.fetchall.return_value = [("unit", 2, 10, 0)]
            mock_conn.cursor.return_value = mock_cursor
            mock_sqlite3.connect.return_value = mock_conn

            with mock.patch.dict("sys.modules", {"sqlite3": mock_sqlite3}):
                _result = run_test_coverage()

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "uv" in call_args
        assert "test-coverage" in call_args
        assert "--no-validate" in call_args

    def test_runs_test_coverage_with_tier(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that run_test_coverage includes tier argument."""
        with mock.patch("scripts.dev.test_runner.run_coverage_batches.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            mock_sqlite3 = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_cursor.fetchall.return_value = [("unit", 0, 10, 1)]
            mock_conn.cursor.return_value = mock_cursor
            mock_sqlite3.connect.return_value = mock_conn

            with mock.patch.dict("sys.modules", {"sqlite3": mock_sqlite3}):
                _result = run_test_coverage(tier="unit")

        call_args = mock_run.call_args[0][0]
        assert "--tier" in call_args
        assert "unit" in call_args

    def test_prints_output_on_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that output is printed when command fails."""
        with mock.patch("scripts.dev.test_runner.run_coverage_batches.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                returncode=1, stdout="stdout content", stderr="stderr content"
            )
            mock_sqlite3 = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_conn.cursor.return_value = mock_cursor
            mock_sqlite3.connect.return_value = mock_conn

            with mock.patch.dict("sys.modules", {"sqlite3": mock_sqlite3}):
                run_test_coverage()

        captured = capsys.readouterr()
        assert "stdout content" in captured.out
        assert "stderr content" in captured.out

    def test_returns_summary_from_database(self) -> None:
        """Test that summary is returned from database."""
        with mock.patch("scripts.dev.test_runner.run_coverage_batches.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            mock_sqlite3 = mock.MagicMock()
            mock_conn = mock.MagicMock()
            mock_cursor = mock.MagicMock()
            mock_cursor.fetchall.return_value = [
                ("unit", 2, 10, 0),
                ("scripts", 0, 5, 1),
            ]
            mock_conn.cursor.return_value = mock_cursor
            mock_sqlite3.connect.return_value = mock_conn

            with mock.patch.dict("sys.modules", {"sqlite3": mock_sqlite3}):
                result = run_test_coverage()

        assert "unit" in result
        assert result["unit"]["failing"] == 2
        assert result["unit"]["total"] == 10
        assert result["unit"]["pass"] is False
        assert "scripts" in result
        assert result["scripts"]["pass"] is True


class TestRunBatching:
    def test_runs_batching_command(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that run_batching calls subprocess correctly."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="Output", stderr="")
            with mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.Path.exists"
            ) as mock_exists:
                mock_exists.return_value = False

                _result = run_batching(None)

        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "uv" in call_args
        assert "batch_coverage_gaps.py" in call_args[3]

    def test_runs_batching_with_tier(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that run_batching includes tier argument."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            with mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.Path.exists"
            ) as mock_exists:
                mock_exists.return_value = False

                run_batching("unit")

        call_args = mock_run.call_args[0][0]
        assert "--tier" in call_args
        assert "unit" in call_args

    def test_runs_batching_with_batch_size(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that run_batching includes batch size."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            with mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.Path.exists"
            ) as mock_exists:
                mock_exists.return_value = False

                run_batching(None, batch_size=20)

        call_args = mock_run.call_args[0][0]
        assert "--batch-size" in call_args
        assert "20" in call_args

    def test_returns_none_on_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that None is returned when command fails."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="Error occurred")

            result = run_batching(None)

        assert result is None
        captured = capsys.readouterr()
        assert "Error:" in captured.out

    def test_returns_manifest_on_success(self, tmp_path: Path) -> None:
        """Test that manifest is returned on success."""
        manifest_data = {
            "total_batches": 2,
            "total_functions": 15,
            "batch_files": ["batch_001.json", "batch_002.json"],
        }
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data))

        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            with mock.patch("scripts.dev.test_runner.run_coverage_batches.Path") as mock_path_cls:
                # Create a mock for the Path class
                mock_manifest_path = mock.MagicMock()
                mock_manifest_path.exists.return_value = True
                mock_manifest_path.read_text.return_value = json.dumps(manifest_data)

                # Make Path() return our mock for manifest path
                def path_side_effect(path_str):
                    if "manifest.json" in str(path_str):
                        return mock_manifest_path
                    return Path(path_str)

                mock_path_cls.side_effect = path_side_effect

                result = run_batching(None)

        assert result is not None
        assert result["total_batches"] == 2
        assert result["total_functions"] == 15

    def test_returns_none_when_manifest_missing(self) -> None:
        """Test that None is returned when manifest doesn't exist."""
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
            with mock.patch("scripts.dev.test_runner.run_coverage_batches.Path") as mock_path_cls:
                mock_manifest_path = mock.MagicMock()
                mock_manifest_path.exists.return_value = False

                def path_side_effect(path_str):
                    if "manifest.json" in str(path_str):
                        return mock_manifest_path
                    return Path(path_str)

                mock_path_cls.side_effect = path_side_effect

                result = run_batching(None)

        assert result is None


class TestMain:
    def test_main_parses_arguments(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main parses command line arguments."""
        with (
            mock.patch("sys.argv", ["run_coverage_batches.py", "--dry-run"]),
            mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_test_coverage"
            ) as mock_coverage,
        ):
            mock_coverage.return_value = {"unit": {"failing": 0, "total": 10, "pass": True}}

            main()

        captured = capsys.readouterr()
        assert "Coverage Improvement Orchestrator" in captured.out

    def test_main_exits_when_all_pass(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main exits when all tiers pass."""
        with (
            mock.patch("sys.argv", ["run_coverage_batches.py"]),
            mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_test_coverage"
            ) as mock_coverage,
        ):
            mock_coverage.return_value = {"unit": {"failing": 0, "total": 10, "pass": True}}

            main()

        captured = capsys.readouterr()
        assert "All tiers passing!" in captured.out

    def test_main_exits_when_no_batches(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main exits when no batches to process."""
        with (
            mock.patch("sys.argv", ["run_coverage_batches.py"]),
            mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_test_coverage"
            ) as mock_coverage,
        ):
            mock_coverage.return_value = {"unit": {"failing": 5, "total": 10, "pass": False}}
            with mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_batching"
            ) as mock_batching:
                mock_batching.return_value = None

                main()

        captured = capsys.readouterr()
        assert "No batches to process" in captured.out

    def test_main_exits_when_zero_batches(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main exits when manifest has zero batches."""
        with (
            mock.patch("sys.argv", ["run_coverage_batches.py"]),
            mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_test_coverage"
            ) as mock_coverage,
        ):
            mock_coverage.return_value = {"unit": {"failing": 5, "total": 10, "pass": False}}
            with mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_batching"
            ) as mock_batching:
                mock_batching.return_value = {
                    "total_batches": 0,
                    "total_functions": 0,
                    "batch_files": [],
                }

                main()

        captured = capsys.readouterr()
        assert "No batches to process" in captured.out

    def test_main_dry_run_shows_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main shows commands in dry run mode."""
        with (
            mock.patch("sys.argv", ["run_coverage_batches.py", "--dry-run"]),
            mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_test_coverage"
            ) as mock_coverage,
        ):
            mock_coverage.return_value = {"unit": {"failing": 5, "total": 10, "pass": False}}
            with mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_batching"
            ) as mock_batching:
                mock_batching.return_value = {
                    "total_batches": 2,
                    "total_functions": 10,
                    "batch_files": ["batch_001.json", "batch_002.json"],
                }

                main()

        captured = capsys.readouterr()
        assert "[DRY RUN]" in captured.out
        assert "Would launch agents for batches:" in captured.out

    def test_main_shows_agent_instructions(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main shows agent instructions when not dry run."""
        with (
            mock.patch("sys.argv", ["run_coverage_batches.py"]),
            mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_test_coverage"
            ) as mock_coverage,
        ):
            mock_coverage.return_value = {"unit": {"failing": 5, "total": 10, "pass": False}}
            with mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_batching"
            ) as mock_batching:
                mock_batching.return_value = {
                    "total_batches": 1,
                    "total_functions": 5,
                    "batch_files": ["batch_001.json"],
                }

                main()

        captured = capsys.readouterr()
        assert "To run agents in parallel" in captured.out
        assert "Task(subagent_type='test-debugger'" in captured.out

    def test_main_with_tier_filter(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main with tier filter."""
        with (
            mock.patch("sys.argv", ["run_coverage_batches.py", "--tier", "unit"]),
            mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_test_coverage"
            ) as mock_coverage,
        ):
            mock_coverage.return_value = {"unit": {"failing": 0, "total": 10, "pass": True}}

            main()

        captured = capsys.readouterr()
        assert "Tier: unit" in captured.out

    def test_main_with_parallel_option(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main with parallel agents option."""
        with (
            mock.patch("sys.argv", ["run_coverage_batches.py", "--parallel", "8"]),
            mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_test_coverage"
            ) as mock_coverage,
        ):
            mock_coverage.return_value = {"unit": {"failing": 0, "total": 10, "pass": True}}

            main()

        captured = capsys.readouterr()
        assert "Parallel agents: 8" in captured.out

    def test_main_with_max_iterations(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main with max iterations option."""
        with (
            mock.patch("sys.argv", ["run_coverage_batches.py", "--max-iterations", "3"]),
            mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_test_coverage"
            ) as mock_coverage,
        ):
            mock_coverage.return_value = {"unit": {"failing": 0, "total": 10, "pass": True}}

            main()

        captured = capsys.readouterr()
        assert "Max iterations: 3" in captured.out

    def test_main_with_batch_size(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main with batch size option."""
        with (
            mock.patch("sys.argv", ["run_coverage_batches.py", "--batch-size", "20"]),
            mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_test_coverage"
            ) as mock_coverage,
        ):
            mock_coverage.return_value = {"unit": {"failing": 0, "total": 10, "pass": True}}

            main()

        captured = capsys.readouterr()
        assert "Batch size: 20" in captured.out

    def test_main_limits_agents_to_parallel_count(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main limits agents to parallel count."""
        with (
            mock.patch("sys.argv", ["run_coverage_batches.py", "--parallel", "2"]),
            mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_test_coverage"
            ) as mock_coverage,
            mock.patch(
                "scripts.dev.test_runner.run_coverage_batches.run_batching"
            ) as mock_batching,
        ):
            mock_coverage.return_value = {"unit": {"failing": 5, "total": 10, "pass": False}}
            mock_batching.return_value = {
                "total_batches": 5,
                "total_functions": 25,
                "batch_files": [f"batch_{i:03d}.json" for i in range(1, 6)],
            }

            main()

        captured = capsys.readouterr()
        # Should only show 2 agents (limited by --parallel)
        assert "Launch 2 agents in parallel" in captured.out
