"""Tests for scripts/knowledge/query_validations.py."""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.knowledge import query_validations


class TestMain:
    """Tests for main() function."""

    def test_main_no_validations_file(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test main() when validations CSV doesn't exist."""
        non_existent = tmp_path / "validations.csv"
        result = query_validations.main(["--validations-csv", str(non_existent)])

        assert result == 0
        captured = capsys.readouterr()
        assert "No validation results found" in captured.out

    def test_main_empty_validations(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test main() when validations CSV exists but has no data (only header)."""
        validations_csv = tmp_path / "validations.csv"
        # Create empty CSV with header
        with validations_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "validation_id",
                    "artifact_id",
                    "source_file",
                    "source_element_id",
                    "field_path",
                    "render_plan_id",
                    "projection_version",
                    "source_hash",
                    "rendered_hash",
                    "similarity_score",
                    "passed",
                    "mismatch_summary",
                    "validated_at",
                ],
            )
            writer.writeheader()

        result = query_validations.main(["--validations-csv", str(validations_csv)])

        assert result == 0
        captured = capsys.readouterr()
        assert "No validation results found" in captured.out

    def test_main_load_exception(
        self, tmp_path: Path, capsys: pytest.CaptureFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test main() when loading validations raises an exception (lines 478-484)."""
        validations_csv = tmp_path / "validations.csv"
        # Create a valid CSV with a header so file exists
        validations_csv.write_text("validation_id,artifact_id\n")

        with patch.object(query_validations, "load_validation_results") as mock_load:
            mock_load.side_effect = ValueError("Invalid CSV format")
            result = query_validations.main(["--validations-csv", str(validations_csv)])

        assert result == 1
        assert "Failed to load validations" in caplog.text

    def test_main_yaml_output(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test main() with YAML output format (lines 510-511)."""
        validations_csv = tmp_path / "validations.csv"

        # Create CSV with one validation result
        with validations_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "validation_id",
                    "artifact_id",
                    "source_file",
                    "source_element_id",
                    "field_path",
                    "render_plan_id",
                    "projection_version",
                    "source_hash",
                    "rendered_hash",
                    "similarity_score",
                    "passed",
                    "mismatch_summary",
                    "validated_at",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "validation_id": "val-001",
                    "artifact_id": "art-001",
                    "source_file": "docs/test.yml",
                    "source_element_id": "test-element",
                    "field_path": "path.to.field",
                    "render_plan_id": "prose.paragraph.v1",
                    "projection_version": "v1",
                    "source_hash": "abc123",
                    "rendered_hash": "def456",
                    "similarity_score": "0.9500",
                    "passed": "true",
                    "mismatch_summary": "",
                    "validated_at": "2024-01-01T00:00:00Z",
                }
            )

        result = query_validations.main(
            ["--validations-csv", str(validations_csv), "--output-format", "yaml"]
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "validation_id: val-001" in captured.out
        assert "artifact_id: art-001" in captured.out

    def test_main_csv_output(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test main() with CSV output format (lines 512-513)."""
        validations_csv = tmp_path / "validations.csv"

        # Create CSV with one validation result
        with validations_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "validation_id",
                    "artifact_id",
                    "source_file",
                    "source_element_id",
                    "field_path",
                    "render_plan_id",
                    "projection_version",
                    "source_hash",
                    "rendered_hash",
                    "similarity_score",
                    "passed",
                    "mismatch_summary",
                    "validated_at",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "validation_id": "val-002",
                    "artifact_id": "art-002",
                    "source_file": "docs/test2.yml",
                    "source_element_id": "test-element-2",
                    "field_path": "path.to.field2",
                    "render_plan_id": "prose.paragraph.v1",
                    "projection_version": "v1",
                    "source_hash": "abc456",
                    "rendered_hash": "def789",
                    "similarity_score": "0.8500",
                    "passed": "false",
                    "mismatch_summary": "Some mismatch",
                    "validated_at": "2024-01-02T00:00:00Z",
                }
            )

        result = query_validations.main(
            ["--validations-csv", str(validations_csv), "--output-format", "csv"]
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "val-002" in captured.out
        assert "art-002" in captured.out

    def test_main_json_output(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test main() with JSON output format."""
        validations_csv = tmp_path / "validations.csv"

        # Create CSV with one validation result
        with validations_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "validation_id",
                    "artifact_id",
                    "source_file",
                    "source_element_id",
                    "field_path",
                    "render_plan_id",
                    "projection_version",
                    "source_hash",
                    "rendered_hash",
                    "similarity_score",
                    "passed",
                    "mismatch_summary",
                    "validated_at",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "validation_id": "val-003",
                    "artifact_id": "art-003",
                    "source_file": "docs/test3.yml",
                    "source_element_id": "test-element-3",
                    "field_path": "",
                    "render_plan_id": "",
                    "projection_version": "",
                    "source_hash": "",
                    "rendered_hash": "",
                    "similarity_score": "1.0000",
                    "passed": "true",
                    "mismatch_summary": "",
                    "validated_at": "2024-01-03T00:00:00Z",
                }
            )

        result = query_validations.main(
            ["--validations-csv", str(validations_csv), "--output-format", "json"]
        )

        assert result == 0
        captured = capsys.readouterr()
        assert '"validation_id": "val-003"' in captured.out

    def test_main_with_stats_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test main() with --stats flag."""
        validations_csv = tmp_path / "validations.csv"

        # Create CSV with validation results
        with validations_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "validation_id",
                    "artifact_id",
                    "source_file",
                    "source_element_id",
                    "field_path",
                    "render_plan_id",
                    "projection_version",
                    "source_hash",
                    "rendered_hash",
                    "similarity_score",
                    "passed",
                    "mismatch_summary",
                    "validated_at",
                ],
            )
            writer.writeheader()
            writer.writerow(
                {
                    "validation_id": "val-004",
                    "artifact_id": "art-004",
                    "source_file": "docs/test4.yml",
                    "source_element_id": "",
                    "field_path": "",
                    "render_plan_id": "plan1",
                    "projection_version": "",
                    "source_hash": "",
                    "rendered_hash": "",
                    "similarity_score": "0.9000",
                    "passed": "true",
                    "mismatch_summary": "",
                    "validated_at": "",
                }
            )

        result = query_validations.main(["--validations-csv", str(validations_csv), "--stats"])

        assert result == 0
        captured = capsys.readouterr()
        assert "Total validations:" in captured.out
        assert "Passed:" in captured.out

    def test_main_with_verbose(self, tmp_path: Path) -> None:
        """Test main() with verbose logging."""
        non_existent = tmp_path / "validations.csv"
        result = query_validations.main(["--validations-csv", str(non_existent), "-v"])
        assert result == 0
