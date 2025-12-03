"""Integration tests for query_artifacts CLI script."""

import json
from pathlib import Path

import pytest
import yaml
from pyfakefs.fake_filesystem import FakeFilesystem

from scripts.knowledge.artifact_manager import ArtifactManifest
from scripts.knowledge.query_artifacts import (
    _compute_stats,
    _filter_manifests,
    _format_csv,
    _format_json,
    _format_stats,
    _format_table,
    _format_yaml,
    main,
    parse_args,
)


@pytest.fixture
def sample_manifests() -> list[ArtifactManifest]:
    """Create sample manifests for testing."""
    return [
        ArtifactManifest(
            artifact_id="abc123",
            artifact_kind="diagram/mermaid.sequence",
            artifact_format="text/x-mermaid",
            source={
                "source_file": "docs/architecture/event-flow.yml",
                "source_element_id": "element-1",
                "field_path": "text",
                "source_locator": "inline",
                "source_uri": None,
            },
            render_plan_id="diagram.mermaid.sequence.v1",
            projection_version="fieldfacts.v2",
            modality="text",
            extraction_mode="full",
            contributors={"structural": [], "semantic": []},
            entities=[],
            rendered={
                "path": "",
                "validation": {
                    "last_validated_at": "",
                    "similarity": "",
                    "passed": "true",
                    "notes": "",
                },
            },
        ),
        ArtifactManifest(
            artifact_id="xyz789",
            artifact_kind="prose/code-block",
            artifact_format="text/markdown",
            source={
                "source_file": "docs/development/test.yml",
                "source_element_id": "element-2",
                "field_path": "sample_code",
                "source_locator": "inline",
                "source_uri": None,
            },
            render_plan_id="prose.code-block.v1",
            projection_version="fieldfacts.v2",
            modality="text",
            extraction_mode="full",
            contributors={
                "structural": [
                    {"element_id": "element-2", "field_path": "sample_code.code"}
                ],
                "semantic": [],
            },
            entities=[],
            rendered={
                "path": "",
                "validation": {
                    "last_validated_at": "",
                    "similarity": "",
                    "passed": "",
                    "notes": "",
                },
            },
        ),
    ]


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_output_format(self) -> None:
        """Should default to table output format."""
        args = parse_args([])
        assert args.output_format == "table"

    def test_custom_artifacts_dir(self) -> None:
        """Should accept custom artifacts directory."""
        args = parse_args(["--artifacts-dir", "/custom/path"])
        assert args.artifacts_dir == Path("/custom/path")

    def test_artifact_id_filter(self) -> None:
        """Should accept artifact_id filter."""
        args = parse_args(["--artifact-id", "abc123"])
        assert args.artifact_id == "abc123"

    def test_artifact_kind_filter(self) -> None:
        """Should accept artifact_kind filter."""
        args = parse_args(["--artifact-kind", "diagram/*"])
        assert args.artifact_kind == "diagram/*"

    def test_source_file_filter(self) -> None:
        """Should accept source_file filter."""
        args = parse_args(["--source-file", "docs/test.yml"])
        assert args.source_file == "docs/test.yml"

    def test_v1_only_default_false(self) -> None:
        """Should default v1_only to False."""
        args = parse_args([])
        assert args.v1_only is False

    def test_show_contributors(self) -> None:
        """Should accept show-contributors flag."""
        args = parse_args(["--show-contributors"])
        assert args.show_contributors is True

    def test_show_validation(self) -> None:
        """Should accept show-validation flag."""
        args = parse_args(["--show-validation"])
        assert args.show_validation is True

    def test_stats_flag(self) -> None:
        """Should accept stats flag."""
        args = parse_args(["--stats"])
        assert args.stats is True


class TestFilterManifests:
    """Tests for _filter_manifests function."""

    def test_filters_by_artifact_id(self, sample_manifests: list[ArtifactManifest]) -> None:
        """Should filter by artifact_id prefix."""
        result = _filter_manifests(sample_manifests, artifact_id="abc")
        assert len(result) == 1
        assert result[0]["artifact_id"] == "abc123"

    def test_filters_by_artifact_kind_exact(
        self, sample_manifests: list[ArtifactManifest]
    ) -> None:
        """Should filter by exact artifact_kind."""
        result = _filter_manifests(
            sample_manifests, artifact_kind="diagram/mermaid.sequence"
        )
        assert len(result) == 1
        assert result[0]["artifact_kind"] == "diagram/mermaid.sequence"

    def test_filters_by_artifact_kind_wildcard(
        self, sample_manifests: list[ArtifactManifest]
    ) -> None:
        """Should filter by artifact_kind wildcard pattern."""
        result = _filter_manifests(sample_manifests, artifact_kind="diagram/*")
        assert len(result) == 1
        assert result[0]["artifact_kind"] == "diagram/mermaid.sequence"

    def test_filters_by_source_file(self, sample_manifests: list[ArtifactManifest]) -> None:
        """Should filter by source_file."""
        result = _filter_manifests(
            sample_manifests, source_file="docs/architecture/event-flow.yml"
        )
        assert len(result) == 1
        assert result[0]["source"]["source_file"] == "docs/architecture/event-flow.yml"

    def test_combines_multiple_filters(
        self, sample_manifests: list[ArtifactManifest]
    ) -> None:
        """Should combine multiple filters."""
        result = _filter_manifests(
            sample_manifests,
            artifact_kind="diagram/*",
            source_file="docs/architecture/event-flow.yml",
        )
        assert len(result) == 1

    def test_returns_all_with_no_filters(
        self, sample_manifests: list[ArtifactManifest]
    ) -> None:
        """Should return all manifests with no filters."""
        result = _filter_manifests(sample_manifests)
        assert len(result) == 2


class TestFormatTable:
    """Tests for _format_table function."""

    def test_formats_as_table(self, sample_manifests: list[ArtifactManifest]) -> None:
        """Should format manifests as table."""
        output = _format_table(sample_manifests)

        assert "ID" in output
        assert "Kind" in output
        assert "Source File" in output
        assert "abc123" in output[:50] or "abc" in output  # Truncated ID

    def test_includes_validation_when_requested(
        self, sample_manifests: list[ArtifactManifest]
    ) -> None:
        """Should include validation column when show_validation=True."""
        output = _format_table(sample_manifests, show_validation=True)

        assert "Passed" in output
        assert "yes" in output  # First manifest has passed=true

    def test_includes_contributors_when_requested(
        self, sample_manifests: list[ArtifactManifest]
    ) -> None:
        """Should include contributor counts when show_contributors=True."""
        output = _format_table(sample_manifests, show_contributors=True)

        assert "Contributors" in output

    def test_handles_empty_list(self) -> None:
        """Should handle empty manifest list."""
        output = _format_table([])
        assert "No artifacts found" in output


class TestFormatJson:
    """Tests for _format_json function."""

    def test_formats_as_valid_json(self, sample_manifests: list[ArtifactManifest]) -> None:
        """Should format as valid JSON."""
        output = _format_json(sample_manifests)
        data = json.loads(output)

        assert len(data) == 2
        assert data[0]["artifact_id"] == "abc123"

    def test_excludes_contributors_by_default(
        self, sample_manifests: list[ArtifactManifest]
    ) -> None:
        """Should exclude contributors by default."""
        output = _format_json(sample_manifests, show_contributors=False)
        data = json.loads(output)

        assert "contributors" not in data[0]

    def test_includes_contributors_when_requested(
        self, sample_manifests: list[ArtifactManifest]
    ) -> None:
        """Should include contributors when requested."""
        output = _format_json(sample_manifests, show_contributors=True)
        data = json.loads(output)

        assert "contributors" in data[0]


class TestFormatYaml:
    """Tests for _format_yaml function."""

    def test_formats_as_valid_yaml(self, sample_manifests: list[ArtifactManifest]) -> None:
        """Should format as valid YAML."""
        output = _format_yaml(sample_manifests)
        data = yaml.safe_load(output)

        assert len(data) == 2
        assert data[0]["artifact_id"] == "abc123"


class TestFormatCsv:
    """Tests for _format_csv function."""

    def test_formats_as_csv(self, sample_manifests: list[ArtifactManifest]) -> None:
        """Should format as CSV with headers."""
        output = _format_csv(sample_manifests)

        assert "artifact_id" in output
        assert "artifact_kind" in output
        assert "abc123" in output

    def test_includes_validation_columns(
        self, sample_manifests: list[ArtifactManifest]
    ) -> None:
        """Should include validation columns when requested."""
        output = _format_csv(sample_manifests, show_validation=True)

        assert "validation_passed" in output
        assert "validation_similarity" in output

    def test_includes_contributor_counts(
        self, sample_manifests: list[ArtifactManifest]
    ) -> None:
        """Should include contributor counts when requested."""
        output = _format_csv(sample_manifests, show_contributors=True)

        assert "structural_count" in output
        assert "semantic_count" in output

    def test_handles_empty_list(self) -> None:
        """Should return empty string for empty list."""
        output = _format_csv([])
        assert output == ""


class TestComputeStats:
    """Tests for _compute_stats function."""

    def test_computes_total(self, sample_manifests: list[ArtifactManifest]) -> None:
        """Should compute total count."""
        stats = _compute_stats(sample_manifests)
        assert stats["total"] == 2

    def test_computes_by_kind(self, sample_manifests: list[ArtifactManifest]) -> None:
        """Should compute counts by artifact_kind."""
        stats = _compute_stats(sample_manifests)

        assert stats["by_kind"]["diagram/mermaid.sequence"] == 1
        assert stats["by_kind"]["prose/code-block"] == 1

    def test_computes_by_source_file(
        self, sample_manifests: list[ArtifactManifest]
    ) -> None:
        """Should compute counts by source_file."""
        stats = _compute_stats(sample_manifests)

        assert stats["by_source_file"]["docs/architecture/event-flow.yml"] == 1
        assert stats["by_source_file"]["docs/development/test.yml"] == 1

    def test_computes_validation_status(
        self, sample_manifests: list[ArtifactManifest]
    ) -> None:
        """Should compute validation status counts."""
        stats = _compute_stats(sample_manifests)

        assert stats["validation"]["passed"] == 1
        assert stats["validation"]["not_validated"] == 1


class TestFormatStats:
    """Tests for _format_stats function."""

    def test_formats_stats_output(self, sample_manifests: list[ArtifactManifest]) -> None:
        """Should format stats for display."""
        stats = _compute_stats(sample_manifests)
        output = _format_stats(stats)

        assert "Total artifacts: 2" in output
        assert "By artifact kind:" in output
        assert "By source file:" in output
        assert "Validation status:" in output


class TestMain:
    """Tests for main CLI entry point."""

    def test_returns_error_for_missing_dir(self, fs: FakeFilesystem, capsys) -> None:
        """Should return error when artifacts directory doesn't exist."""
        result = main(["--artifacts-dir", "/nonexistent"])

        assert result == 1
        captured = capsys.readouterr()
        assert "Artifacts directory not found" in captured.err

    def test_lists_empty_artifacts(self, fs: FakeFilesystem, capsys) -> None:
        """Should handle empty artifacts directory."""
        fs.create_dir("/fake/.knowledge/artifacts")

        result = main(["--artifacts-dir", "/fake/.knowledge/artifacts"])

        assert result == 0
        captured = capsys.readouterr()
        assert "No artifacts found" in captured.out

    def test_shows_stats(self, fs: FakeFilesystem, capsys) -> None:
        """Should show stats with --stats flag."""
        artifacts_dir = Path("/fake/.knowledge/artifacts")
        fs.create_dir(artifacts_dir)

        # Create a manifest file
        manifest = {
            "artifact_id": "test-id",
            "artifact_kind": "prose/paragraph",
            "artifact_format": "text/markdown",
            "source": {
                "source_file": "docs/test.yml",
                "source_element_id": "test",
                "field_path": "text",
                "source_locator": "inline",
                "source_uri": None,
            },
            "render_plan_id": "prose.paragraph.v1",
            "projection_version": "fieldfacts.v2",
            "modality": "text",
            "extraction_mode": "full",
            "contributors": {"structural": [], "semantic": []},
            "entities": [],
            "rendered": {
                "path": "",
                "validation": {
                    "last_validated_at": "",
                    "similarity": "",
                    "passed": "",
                    "notes": "",
                },
            },
        }
        manifest_path = artifacts_dir / "test-id.yml"
        fs.create_file(manifest_path, contents=yaml.safe_dump(manifest))

        result = main([
            "--artifacts-dir", str(artifacts_dir),
            "--stats",
            "--no-v1-only",
        ])

        assert result == 0
        captured = capsys.readouterr()
        assert "Total artifacts:" in captured.out
        assert "By artifact kind:" in captured.out
