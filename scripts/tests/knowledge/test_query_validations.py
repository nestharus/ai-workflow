"""Integration tests for query_validations CLI script."""

from pathlib import Path

import pytest
from pyfakefs.fake_filesystem import FakeFilesystem

from scripts.knowledge.artifact_validator import ValidationResult, write_validation_result
from scripts.knowledge.query_validations import (
    _compute_stats,
    _filter_validations,
    _format_csv,
    _format_json,
    _format_stats,
    _format_table,
    _format_yaml,
    main,
    parse_args,
)


@pytest.fixture
def sample_validations() -> list[ValidationResult]:
    """Create sample validation results for testing."""
    return [
        ValidationResult(
            validation_id="val-1",
            artifact_id="artifact-1",
            source_file="docs/test1.yml",
            source_element_id="elem-1",
            field_path="description",
            render_plan_id="prose.paragraph.v1",
            projection_version="fieldfacts.v2",
            source_hash="hash1",
            rendered_hash="hash1",
            similarity_score=1.0,
            passed=True,
            mismatch_summary="",
            validated_at="2024-01-01T00:00:00Z",
        ),
        ValidationResult(
            validation_id="val-2",
            artifact_id="artifact-2",
            source_file="docs/test2.yml",
            source_element_id="elem-2",
            field_path="content",
            render_plan_id="table.discriminator-grouped.v1",
            projection_version="fieldfacts.v2",
            source_hash="hash2",
            rendered_hash="hash2-diff",
            similarity_score=0.7,
            passed=False,
            mismatch_summary="Row mismatch",
            validated_at="2024-01-02T00:00:00Z",
        ),
        ValidationResult(
            validation_id="val-3",
            artifact_id="artifact-3",
            source_file="docs/test1.yml",
            source_element_id="elem-3",
            field_path="code",
            render_plan_id="prose.paragraph.v1",
            projection_version="fieldfacts.v2",
            source_hash="hash3",
            rendered_hash="hash3",
            similarity_score=0.95,
            passed=True,
            mismatch_summary="",
            validated_at="2024-01-03T00:00:00Z",
        ),
    ]


@pytest.fixture
def validations_csv(fs: FakeFilesystem, sample_validations: list[ValidationResult]) -> Path:
    """Create a fake validations CSV with sample data."""
    csv_path = Path("/fake/.knowledge/artifacts/validations.csv")
    fs.create_dir(csv_path.parent)

    for validation in sample_validations:
        write_validation_result(validation, csv_path)

    return csv_path


class TestParseArgs:
    """Tests for parse_args function."""

    def test_defaults(self) -> None:
        """Verify default argument values."""
        args = parse_args([])

        assert args.output_format == "table"
        assert args.stats is False
        assert args.artifact_id is None
        assert args.passed is None
        assert args.min_similarity is None

    def test_filter_flags(self) -> None:
        """Verify filter flags are parsed."""
        args = parse_args(
            [
                "--artifact-id",
                "abc123",
                "--passed",
                "true",
                "--min-similarity",
                "0.9",
            ]
        )

        assert args.artifact_id == "abc123"
        assert args.passed == "true"
        assert args.min_similarity == 0.9

    def test_output_format(self) -> None:
        """Verify output format flag is parsed."""
        args = parse_args(["--output-format", "json"])
        assert args.output_format == "json"

    def test_stats_flag(self) -> None:
        """Verify --stats flag is parsed."""
        args = parse_args(["--stats"])
        assert args.stats is True


class TestFilterValidations:
    """Tests for _filter_validations function."""

    def test_no_filters_returns_all(self, sample_validations: list[ValidationResult]) -> None:
        """Verify no filters returns all validations."""
        result = _filter_validations(sample_validations)
        assert len(result) == 3

    def test_filter_by_artifact_id(self, sample_validations: list[ValidationResult]) -> None:
        """Verify filtering by artifact_id prefix."""
        result = _filter_validations(sample_validations, artifact_id="artifact-1")
        assert len(result) == 1
        assert result[0].artifact_id == "artifact-1"

    def test_filter_by_source_file(self, sample_validations: list[ValidationResult]) -> None:
        """Verify filtering by source_file."""
        result = _filter_validations(sample_validations, source_file="docs/test1.yml")
        assert len(result) == 2

    def test_filter_by_passed_true(self, sample_validations: list[ValidationResult]) -> None:
        """Verify filtering by passed=True."""
        result = _filter_validations(sample_validations, passed=True)
        assert len(result) == 2
        assert all(v.passed for v in result)

    def test_filter_by_passed_false(self, sample_validations: list[ValidationResult]) -> None:
        """Verify filtering by passed=False."""
        result = _filter_validations(sample_validations, passed=False)
        assert len(result) == 1
        assert result[0].passed is False

    def test_filter_by_min_similarity(self, sample_validations: list[ValidationResult]) -> None:
        """Verify filtering by minimum similarity."""
        result = _filter_validations(sample_validations, min_similarity=0.9)
        assert len(result) == 2
        assert all(v.similarity_score >= 0.9 for v in result)

    def test_multiple_filters(self, sample_validations: list[ValidationResult]) -> None:
        """Verify multiple filters are combined."""
        result = _filter_validations(
            sample_validations,
            source_file="docs/test1.yml",
            passed=True,
        )
        assert len(result) == 2


class TestFormatTable:
    """Tests for _format_table function."""

    def test_formats_validations_as_table(self, sample_validations: list[ValidationResult]) -> None:
        """Verify validations are formatted as table."""
        result = _format_table(sample_validations)

        assert "Validation ID" in result
        assert "Artifact ID" in result
        assert "Passed" in result
        assert "val-1" in result
        assert "artifact-1" in result

    def test_empty_list_message(self) -> None:
        """Verify empty list shows message."""
        result = _format_table([])
        assert "No validation results found" in result


class TestFormatJson:
    """Tests for _format_json function."""

    def test_formats_as_valid_json(self, sample_validations: list[ValidationResult]) -> None:
        """Verify output is valid JSON."""
        import json

        result = _format_json(sample_validations)
        data = json.loads(result)

        assert isinstance(data, list)
        assert len(data) == 3
        assert data[0]["artifact_id"] == "artifact-1"


class TestFormatYaml:
    """Tests for _format_yaml function."""

    def test_formats_as_valid_yaml(self, sample_validations: list[ValidationResult]) -> None:
        """Verify output is valid YAML."""
        import yaml

        result = _format_yaml(sample_validations)
        data = yaml.safe_load(result)

        assert isinstance(data, list)
        assert len(data) == 3
        assert data[0]["artifact_id"] == "artifact-1"


class TestFormatCsv:
    """Tests for _format_csv function."""

    def test_formats_as_csv(self, sample_validations: list[ValidationResult]) -> None:
        """Verify output is valid CSV."""
        result = _format_csv(sample_validations)

        assert "validation_id" in result
        assert "artifact_id" in result
        assert "artifact-1" in result

    def test_empty_list_returns_empty(self) -> None:
        """Verify empty list returns empty string."""
        result = _format_csv([])
        assert result == ""


class TestComputeStats:
    """Tests for _compute_stats function."""

    def test_computes_total(self, sample_validations: list[ValidationResult]) -> None:
        """Verify total count is computed."""
        stats = _compute_stats(sample_validations)
        assert stats["total"] == 3

    def test_computes_passed_failed(self, sample_validations: list[ValidationResult]) -> None:
        """Verify passed/failed counts are computed."""
        stats = _compute_stats(sample_validations)
        assert stats["passed"] == 2
        assert stats["failed"] == 1

    def test_computes_avg_similarity(self, sample_validations: list[ValidationResult]) -> None:
        """Verify average similarity is computed."""
        stats = _compute_stats(sample_validations)
        # (1.0 + 0.7 + 0.95) / 3 = 0.883...
        assert 0.88 <= stats["avg_similarity"] <= 0.89

    def test_computes_by_render_plan(self, sample_validations: list[ValidationResult]) -> None:
        """Verify stats by render plan are computed."""
        stats = _compute_stats(sample_validations)

        assert "prose.paragraph.v1" in stats["by_render_plan"]
        assert "table.discriminator-grouped.v1" in stats["by_render_plan"]

        prose_stats = stats["by_render_plan"]["prose.paragraph.v1"]
        assert prose_stats["count"] == 2
        assert prose_stats["passed"] == 2

    def test_computes_by_source_file(self, sample_validations: list[ValidationResult]) -> None:
        """Verify stats by source file are computed."""
        stats = _compute_stats(sample_validations)

        assert "docs/test1.yml" in stats["by_source_file"]
        assert stats["by_source_file"]["docs/test1.yml"]["count"] == 2

    def test_computes_similarity_distribution(
        self, sample_validations: list[ValidationResult]
    ) -> None:
        """Verify similarity distribution is computed."""
        stats = _compute_stats(sample_validations)

        dist = stats["similarity_distribution"]
        assert dist["1.0"] == 1  # 1.0
        assert dist["0.9-1.0"] == 1  # 0.95
        assert dist["0.5-0.8"] == 1  # 0.7

    def test_empty_list(self) -> None:
        """Verify empty list returns zero stats."""
        stats = _compute_stats([])

        assert stats["total"] == 0
        assert stats["passed"] == 0
        assert stats["failed"] == 0


class TestFormatStats:
    """Tests for _format_stats function."""

    def test_formats_stats(self, sample_validations: list[ValidationResult]) -> None:
        """Verify stats are formatted for display."""
        stats = _compute_stats(sample_validations)
        result = _format_stats(stats)

        assert "Total validations: 3" in result
        assert "Passed: 2" in result
        assert "Failed: 1" in result
        assert "Average similarity:" in result


class TestMain:
    """Tests for main function."""

    def test_no_validations_returns_zero(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Verify returns 0 when no validations found."""
        result = main(["--validations-csv", "/nonexistent.csv"])

        assert result == 0
        captured = capsys.readouterr()
        assert "No validation results found" in captured.out

    def test_lists_validations(self, validations_csv: Path, capsys: pytest.CaptureFixture) -> None:
        """Verify validations are listed."""
        result = main(["--validations-csv", str(validations_csv)])

        assert result == 0
        captured = capsys.readouterr()
        assert "val-1" in captured.out
        assert "artifact-1" in captured.out

    def test_filter_by_passed(self, validations_csv: Path, capsys: pytest.CaptureFixture) -> None:
        """Verify filtering by passed status."""
        result = main(
            [
                "--validations-csv",
                str(validations_csv),
                "--passed",
                "false",
            ]
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "artifact-2" in captured.out
        assert "artifact-1" not in captured.out

    def test_stats_output(self, validations_csv: Path, capsys: pytest.CaptureFixture) -> None:
        """Verify stats output."""
        result = main(
            [
                "--validations-csv",
                str(validations_csv),
                "--stats",
            ]
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "Total validations: 3" in captured.out
        assert "Passed: 2" in captured.out

    def test_json_output(self, validations_csv: Path, capsys: pytest.CaptureFixture) -> None:
        """Verify JSON output format."""
        import json

        result = main(
            [
                "--validations-csv",
                str(validations_csv),
                "--output-format",
                "json",
            ]
        )

        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert len(data) == 3
