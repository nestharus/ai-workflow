import json
from pathlib import Path

import pytest
import yaml

from scripts.knowledge.compare_yaml_docs import Artifact
from scripts.knowledge.detect_artifacts import (
    _detect_from_file,
    _expand_source_files,
    _format_output,
    main,
    parse_args,
)


class TestParseArgs:
    def test_requires_source_files(self) -> None:
        """Should require --source-files argument."""
        with pytest.raises(SystemExit):
            parse_args([])

    def test_accepts_source_files(self) -> None:
        """Should accept --source-files argument."""
        args = parse_args(["--source-files", "docs/**/*.yml"])
        assert args.source_files == ["docs/**/*.yml"]

    def test_accepts_multiple_source_files(self) -> None:
        """Should accept multiple source files."""
        args = parse_args(["--source-files", "file1.yml", "file2.yml"])
        assert args.source_files == ["file1.yml", "file2.yml"]

    def test_default_artifacts_dir(self) -> None:
        """Should use default artifacts directory."""
        args = parse_args(["--source-files", "test.yml"])
        assert "artifacts" in str(args.artifacts_dir)

    def test_custom_artifacts_dir(self) -> None:
        """Should accept custom artifacts directory."""
        args = parse_args(["--source-files", "test.yml", "--artifacts-dir", "/custom/path"])
        assert args.artifacts_dir == Path("/custom/path")

    def test_create_manifests_default_true(self) -> None:
        """Should default create_manifests to True."""
        args = parse_args(["--source-files", "test.yml"])
        assert args.create_manifests is True

    def test_no_create_manifests(self) -> None:
        """Should allow disabling manifest creation."""
        args = parse_args(["--source-files", "test.yml", "--no-create-manifests"])
        assert args.create_manifests is False

    def test_v1_only_default_true(self) -> None:
        """Should default v1_only to True."""
        args = parse_args(["--source-files", "test.yml"])
        assert args.v1_only is True

    def test_no_v1_only(self) -> None:
        """Should allow disabling V1 filter."""
        args = parse_args(["--source-files", "test.yml", "--no-v1-only"])
        assert args.v1_only is False

    def test_output_format_choices(self) -> None:
        """Should accept valid output formats."""
        for fmt in ["json", "yaml", "csv", "none"]:
            args = parse_args(["--source-files", "test.yml", "--output-format", fmt])
            assert args.output_format == fmt


class TestFormatOutput:
    @pytest.fixture
    def sample_artifacts(self) -> list[Artifact]:
        """Create sample artifacts for testing."""
        return [
            Artifact(
                artifact_id="abc123",
                artifact_kind="diagram/mermaid.sequence",
                artifact_format="text/x-mermaid",
                source_file="docs/test.yml",
                source_element_id="element-1",
                field_path="text",
                source_locator="inline",
                source_uri=None,
                render_engine="text_llm",
                render_plan_id="diagram.mermaid.sequence.v1",
                projection_version="fieldfacts.v2",
            ),
            Artifact(
                artifact_id="xyz789",
                artifact_kind="prose/code-block",
                artifact_format="text/markdown",
                source_file="docs/test.yml",
                source_element_id="element-2",
                field_path="sample_code",
                source_locator="inline",
                source_uri=None,
                render_engine="text_llm",
                render_plan_id="prose.code-block.v1",
                projection_version="fieldfacts.v2",
            ),
        ]

    def test_json_format(self, sample_artifacts: list[Artifact]) -> None:
        """Should format as valid JSON."""
        output = _format_output(sample_artifacts, "json")
        data = json.loads(output)

        assert len(data) == 2
        assert data[0]["artifact_id"] == "abc123"
        assert data[1]["artifact_kind"] == "prose/code-block"

    def test_yaml_format(self, sample_artifacts: list[Artifact]) -> None:
        """Should format as valid YAML."""
        output = _format_output(sample_artifacts, "yaml")
        data = yaml.safe_load(output)

        assert len(data) == 2
        assert data[0]["artifact_id"] == "abc123"

    def test_csv_format(self, sample_artifacts: list[Artifact]) -> None:
        """Should format as CSV with headers."""
        output = _format_output(sample_artifacts, "csv")

        assert "artifact_id" in output
        assert "artifact_kind" in output
        assert "abc123" in output
        assert "diagram/mermaid.sequence" in output

    def test_empty_list_returns_empty_string(self) -> None:
        """Should return empty string for empty list."""
        output = _format_output([], "json")
        assert output == ""
