"""Tests for scripts.movement_tracker module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts import movement_tracker
from scripts.movement_tracker import (
    CSV_COLUMNS,
    MovementRecord,
    append_movement,
    ensure_csv_exists,
    main,
    parse_args,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestCsvColumns:
    """Tests for CSV_COLUMNS constant."""

    def test_has_required_columns(self) -> None:
        """Should have all required columns."""
        assert "movement_id" in CSV_COLUMNS
        assert "element_id" in CSV_COLUMNS
        assert "source_file" in CSV_COLUMNS
        assert "target_file" in CSV_COLUMNS
        assert "reason" in CSV_COLUMNS
        assert "coverage_description" in CSV_COLUMNS
        assert "before_sentence" in CSV_COLUMNS
        assert "after_sentence_source" in CSV_COLUMNS
        assert "target_before_sentence" in CSV_COLUMNS
        assert "target_after_sentence" in CSV_COLUMNS
        assert "moved_at" in CSV_COLUMNS


class TestEnsureCsvExists:
    """Tests for ensure_csv_exists function."""

    def test_creates_csv_with_header(self, tmp_path: Path) -> None:
        """Should create CSV file with header row.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "movements" / "movements.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.exists()
        content = csv_path.read_text()
        for col in CSV_COLUMNS:
            assert col in content

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Should create parent directories if needed.

        DuckDB requires real filesystem.
        """
        csv_path = tmp_path / "movements" / "movements.csv"

        ensure_csv_exists(csv_path)

        assert csv_path.parent.exists()

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        """Should not overwrite existing non-empty file.

        DuckDB requires real filesystem.
        """
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "movements.csv"
        csv_path.write_text("existing,content\n")

        ensure_csv_exists(csv_path)

        content = csv_path.read_text()
        assert "existing,content" in content


class TestAppendMovement:
    """Tests for append_movement function."""

    def test_appends_record(self, tmp_path: Path) -> None:
        """Should append movement record to CSV.

        DuckDB requires real filesystem.
        """
        (tmp_path / "movements").mkdir(parents=True)
        csv_path = tmp_path / "movements" / "movements.csv"
        header = ",".join(CSV_COLUMNS)
        csv_path.write_text(f"{header}\n")

        record = MovementRecord(
            movement_id="move-1",
            element_id="item-1",
            source_file="source.yml",
            target_file="target.yml",
            reason="Restructuring",
            coverage_description="Moving item description",
            before_sentence="Original sentence",
            after_sentence_source="New sentence in source",
            target_before_sentence="Target before",
            target_after_sentence="Target after with new content",
            moved_at="20240101T120000Z",
        )

        append_movement(csv_path, record)

        content = csv_path.read_text()
        assert "move-1" in content
        assert "item-1" in content
        assert "Restructuring" in content


class TestParseArgs:
    """Tests for parse_args function."""

    def test_requires_all_arguments(self) -> None:
        """Should require all mandatory arguments."""
        with pytest.raises(SystemExit):
            parse_args([])

    def test_parses_all_arguments(self) -> None:
        """Should parse all arguments correctly."""
        args = parse_args([
            "--id", "item-1",
            "--source-file", "/source.yml",
            "--target-file", "/target.yml",
            "--reason", "Restructuring",
            "--coverage", "Coverage description",
            "--before-text", "Before sentence",
            "--after-text-source", "After sentence",
            "--target-before", "Target before",
            "--target-after", "Target after",
        ])

        assert args.id == "item-1"
        assert args.source_file == Path("/source.yml")
        assert args.target_file == Path("/target.yml")
        assert args.reason == "Restructuring"
        assert args.coverage == "Coverage description"

    def test_default_knowledge_path(self) -> None:
        """Should default to .knowledge directory."""
        args = parse_args([
            "--id", "item-1",
            "--source-file", "/source.yml",
            "--target-file", "/target.yml",
            "--reason", "Reason",
            "--coverage", "Coverage",
            "--before-text", "Before",
            "--after-text-source", "After",
            "--target-before", "Target before",
            "--target-after", "Target after",
        ])

        assert args.knowledge_path == Path(".knowledge")


class TestMain:
    """Tests for main function."""

    def test_returns_one_for_missing_source(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when source file doesn't exist."""
        with patch.object(movement_tracker, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--id", "item-1",
                    "--source-file", "missing.yml",
                    "--target-file", "target.yml",
                    "--reason", "Reason",
                    "--coverage", "Coverage",
                    "--before-text", "Before",
                    "--after-text-source", "After",
                    "--target-before", "Target before",
                    "--target-after", "Target after",
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_one_for_missing_target(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when target file doesn't exist."""
        with patch.object(movement_tracker, "REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            fs.create_file("/fake/source.yml", contents="content")

            with patch(
                "sys.argv",
                [
                    "script",
                    "--id", "item-1",
                    "--source-file", "source.yml",
                    "--target-file", "missing.yml",
                    "--reason", "Reason",
                    "--coverage", "Coverage",
                    "--before-text", "Before",
                    "--after-text-source", "After",
                    "--target-before", "Target before",
                    "--target-after", "Target after",
                ],
            ):
                result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_returns_zero_on_success(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 0 and print success message.

        DuckDB requires real filesystem.
        """
        (tmp_path / "source.yml").write_text("content")
        (tmp_path / "target.yml").write_text("content")

        with patch.object(movement_tracker, "REPO_ROOT", tmp_path):
            with patch(
                "sys.argv",
                [
                    "script",
                    "--id", "item-1",
                    "--source-file", "source.yml",
                    "--target-file", "target.yml",
                    "--reason", "Reason",
                    "--coverage", "Coverage",
                    "--before-text", "Before",
                    "--after-text-source", "After",
                    "--target-before", "Target before",
                    "--target-after", "Target after",
                ],
            ):
                result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Movement recorded" in captured.out
