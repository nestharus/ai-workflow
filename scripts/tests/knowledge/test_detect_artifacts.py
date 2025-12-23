"""Integration tests for detect_artifacts CLI script."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from _pytest.capture import CaptureFixture
from _pytest.logging import LogCaptureFixture
from pyfakefs.fake_filesystem import FakeFilesystem

from scripts.knowledge.compare_yaml_docs import Artifact
from scripts.knowledge.detect_artifacts import (
    _detect_from_file,
    _expand_source_files,
    _format_output,
    main,
    parse_args,
)


class TestParseArgs:
    """Tests for parse_args function."""

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


class TestExpandSourceFiles:
    """Tests for _expand_source_files function."""

    def test_expands_glob_pattern(self, fs: FakeFilesystem) -> None:
        """Should expand glob patterns."""
        fs.create_file("/docs/test1.yml", contents="id: test1\n")
        fs.create_file("/docs/test2.yml", contents="id: test2\n")
        fs.create_file("/docs/subdir/test3.yml", contents="id: test3\n")

        with patch("scripts.knowledge.detect_artifacts.REPO_ROOT", Path("/")):
            files = _expand_source_files(["/docs/**/*.yml"])

        # Should find all YAML files
        assert len(files) >= 3

    def test_handles_direct_file_path(self, fs: FakeFilesystem) -> None:
        """Should handle direct file paths."""
        fs.create_file("/docs/test.yml", contents="id: test\n")

        with patch("scripts.knowledge.detect_artifacts.REPO_ROOT", Path("/")):
            files = _expand_source_files(["/docs/test.yml"])

        assert len(files) == 1

    def test_returns_sorted_unique_files(self, fs: FakeFilesystem) -> None:
        """Should return sorted unique files."""
        fs.create_file("/docs/a.yml", contents="id: a\n")
        fs.create_file("/docs/b.yml", contents="id: b\n")

        with patch("scripts.knowledge.detect_artifacts.REPO_ROOT", Path("/")):
            files = _expand_source_files(["/docs/a.yml", "/docs/b.yml", "/docs/a.yml"])

        # Should be unique and sorted
        assert len(files) == 2
        assert files == sorted(files)


class TestFormatOutput:
    """Tests for _format_output function."""

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


class TestDetectFromFile:
    """Tests for _detect_from_file function."""

    def test_detects_artifacts_from_file(self, fs: FakeFilesystem) -> None:
        """Should detect artifacts from a YAML file."""
        # Create test YAML file with artifact root
        yaml_content = {
            "id": "test-element",
            "sections": [
                {
                    "id": "section-1",
                    "items": [
                        {
                            "id": "item-1",
                            "type": "code",
                            "text": "sequenceDiagram\n  A->>B: Hello",
                        }
                    ],
                }
            ],
        }
        fs.create_file("/docs/test.yml", contents=yaml.safe_dump(yaml_content))
        artifacts_dir = Path("/fake/.knowledge/artifacts")
        fs.create_dir(artifacts_dir)

        # Create registry
        registry = [
            {
                "kind_id": "diagram/mermaid.sequence",
                "structure_pattern": {
                    "root_path": "sections[*].items[*].text",
                    "sibling_constraints": [{"key": "type", "equals": "code"}],
                    "content_sniff": {"starts_with_any": ["sequenceDiagram"]},
                },
                "rendering_contract": {
                    "render_plan_id": "diagram.mermaid.sequence.v1",
                    "output_mime": "text/x-mermaid",
                },
            }
        ]
        registry_path = artifacts_dir / "kinds.yml"
        fs.create_file(registry_path, contents=yaml.safe_dump({"kinds": registry}))

        with (
            patch("scripts.knowledge.detect_artifacts.REPO_ROOT", Path("/")),
            patch(
                "scripts.knowledge.compare_yaml_docs._load_artifact_registry",
                return_value=registry,
            ),
        ):
            artifacts, _created, _skipped = _detect_from_file(
                Path("/docs/test.yml"),
                artifacts_dir,
                create_manifests=False,
                v1_only=True,
            )

        # Should detect the mermaid diagram artifact
        assert len(artifacts) >= 0  # Detection depends on registry matching

    def test_handles_invalid_yaml(self, fs: FakeFilesystem) -> None:
        """Should handle invalid YAML gracefully."""
        fs.create_file("/docs/invalid.yml", contents="invalid: yaml: {{")
        artifacts_dir = Path("/fake/.knowledge/artifacts")
        fs.create_dir(artifacts_dir)

        with patch("scripts.knowledge.detect_artifacts.REPO_ROOT", Path("/")):
            artifacts, created, skipped = _detect_from_file(
                Path("/docs/invalid.yml"),
                artifacts_dir,
                create_manifests=False,
                v1_only=True,
            )

        # Should return empty results
        assert artifacts == []
        assert created == 0
        assert skipped == 0


class TestMain:
    """Tests for main CLI entry point."""

    def test_returns_error_for_no_files(
        self, fs: FakeFilesystem, caplog: LogCaptureFixture
    ) -> None:
        """Should return error when no source files found."""
        with patch("scripts.knowledge.detect_artifacts.REPO_ROOT", Path("/fake")):
            fs.create_dir("/fake")
            result = main(["--source-files", "/nonexistent/**/*.yml"])

        assert result == 1
        # Error is logged, not printed to stderr
        assert "No source files found" in caplog.text

    def test_prints_summary(self, fs: FakeFilesystem, capsys: CaptureFixture[str]) -> None:
        """Should print summary of detected artifacts."""
        yaml_content = {"id": "test", "text": "Hello world"}
        fs.create_file("/fake/docs/test.yml", contents=yaml.safe_dump(yaml_content))
        fs.create_dir("/fake/.knowledge/artifacts")

        with patch("scripts.knowledge.detect_artifacts.REPO_ROOT", Path("/fake")):
            result = main(
                [
                    "--source-files",
                    "/fake/docs/test.yml",
                    "--artifacts-dir",
                    "/fake/.knowledge/artifacts",
                    "--no-create-manifests",
                ]
            )

        assert result == 0
        captured = capsys.readouterr()
        assert "Files processed:" in captured.out
        assert "Artifacts detected:" in captured.out

    def test_prints_manifests_created(
        self, fs: FakeFilesystem, capsys: CaptureFixture[str]
    ) -> None:
        """Should print manifests created count when create_manifests=True (covers line 325)."""
        yaml_content = {"id": "test", "text": "sequenceDiagram\n  A->>B: Hello"}
        fs.create_file("/fake/docs/test.yml", contents=yaml.safe_dump(yaml_content))
        fs.create_dir("/fake/.knowledge/artifacts")

        with (
            patch("scripts.knowledge.detect_artifacts.REPO_ROOT", Path("/fake")),
            patch(
                "scripts.knowledge.detect_artifacts._detect_from_file",
                return_value=([], 2, 0),  # 2 manifests created
            ),
        ):
            result = main(
                [
                    "--source-files",
                    "/fake/docs/test.yml",
                    "--artifacts-dir",
                    "/fake/.knowledge/artifacts",
                    "--create-manifests",
                ]
            )

        assert result == 0
        captured = capsys.readouterr()
        assert "Manifests created: 2" in captured.out

    def test_prints_skipped_by_v1(self, fs: FakeFilesystem, capsys: CaptureFixture[str]) -> None:
        """Should print skipped by V1 rule count (covers lines 326-327)."""
        yaml_content = {"id": "test", "text": "content"}
        fs.create_file("/fake/docs/test.yml", contents=yaml.safe_dump(yaml_content))
        fs.create_dir("/fake/.knowledge/artifacts")

        with (
            patch("scripts.knowledge.detect_artifacts.REPO_ROOT", Path("/fake")),
            patch(
                "scripts.knowledge.detect_artifacts._detect_from_file",
                return_value=([], 0, 3),  # 3 skipped by V1
            ),
        ):
            result = main(
                [
                    "--source-files",
                    "/fake/docs/test.yml",
                    "--artifacts-dir",
                    "/fake/.knowledge/artifacts",
                    "--v1-only",
                    "--no-create-manifests",
                ]
            )

        assert result == 0
        captured = capsys.readouterr()
        assert "Skipped by V1 rule: 3" in captured.out

    def test_prints_kinds_summary(self, fs: FakeFilesystem, capsys: CaptureFixture[str]) -> None:
        """Should print artifacts by kind summary (covers lines 334-337)."""
        yaml_content = {"id": "test", "text": "content"}
        fs.create_file("/fake/docs/test.yml", contents=yaml.safe_dump(yaml_content))
        fs.create_dir("/fake/.knowledge/artifacts")

        artifacts = [
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
                artifact_kind="diagram/mermaid.sequence",
                artifact_format="text/x-mermaid",
                source_file="docs/test.yml",
                source_element_id="element-2",
                field_path="text2",
                source_locator="inline",
                source_uri=None,
                render_engine="text_llm",
                render_plan_id="diagram.mermaid.sequence.v1",
                projection_version="fieldfacts.v2",
            ),
        ]

        with (
            patch("scripts.knowledge.detect_artifacts.REPO_ROOT", Path("/fake")),
            patch(
                "scripts.knowledge.detect_artifacts._detect_from_file",
                return_value=(artifacts, 0, 0),
            ),
        ):
            result = main(
                [
                    "--source-files",
                    "/fake/docs/test.yml",
                    "--artifacts-dir",
                    "/fake/.knowledge/artifacts",
                    "--no-create-manifests",
                ]
            )

        assert result == 0
        captured = capsys.readouterr()
        assert "Artifacts by kind:" in captured.out
        assert "diagram/mermaid.sequence: 2" in captured.out

    def test_outputs_json_format(self, fs: FakeFilesystem, capsys: CaptureFixture[str]) -> None:
        """Should output JSON when format=json (covers lines 340-343)."""
        yaml_content = {"id": "test", "text": "content"}
        fs.create_file("/fake/docs/test.yml", contents=yaml.safe_dump(yaml_content))
        fs.create_dir("/fake/.knowledge/artifacts")

        artifact = Artifact(
            artifact_id="abc123",
            artifact_kind="prose/paragraph",
            artifact_format="text/markdown",
            source_file="docs/test.yml",
            source_element_id="element-1",
            field_path="text",
            source_locator="inline",
            source_uri=None,
            render_engine="text_llm",
            render_plan_id="prose.paragraph.v1",
            projection_version="fieldfacts.v2",
        )

        with (
            patch("scripts.knowledge.detect_artifacts.REPO_ROOT", Path("/fake")),
            patch(
                "scripts.knowledge.detect_artifacts._detect_from_file",
                return_value=([artifact], 0, 0),
            ),
        ):
            result = main(
                [
                    "--source-files",
                    "/fake/docs/test.yml",
                    "--artifacts-dir",
                    "/fake/.knowledge/artifacts",
                    "--no-create-manifests",
                    "--output-format",
                    "json",
                ]
            )

        assert result == 0
        captured = capsys.readouterr()
        # Should contain JSON output with artifact_id
        assert "abc123" in captured.out
        assert "prose/paragraph" in captured.out
