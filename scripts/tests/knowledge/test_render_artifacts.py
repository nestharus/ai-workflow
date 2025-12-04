"""Integration tests for render_artifacts CLI script."""

from pathlib import Path

import pytest
import yaml
from pyfakefs.fake_filesystem import FakeFilesystem

from scripts.knowledge.render_artifacts import (
    _filter_manifests,
    _get_source_text,
    _render_manifest,
    main,
    parse_args,
)


@pytest.fixture
def sample_manifest() -> dict:
    """Create a sample artifact manifest for testing."""
    return {
        "artifact_id": "abc123def456789012345678901234567890123456789012345678901234",
        "artifact_kind": "prose/paragraph",
        "artifact_format": "text/markdown",
        "source": {
            "source_file": "docs/test.yml",
            "source_element_id": "test-element-1",
            "field_path": "description",
            "source_locator": "inline",
            "source_uri": None,
        },
        "render_plan_id": "prose.paragraph.v1",
        "projection_version": "fieldfacts.v2",
        "modality": "text",
        "extraction_mode": "full",
        "contributors": {"structural": [], "semantic": []},
        "entities": [],
        "rendered": {"path": "", "validation": {}},
    }


@pytest.fixture
def sample_render_plan() -> dict:
    """Create a sample render plan for testing."""
    return {
        "render_plan_id": "prose.paragraph.v1",
        "render_engine": "text_llm",
        "artifact_kind": "prose/paragraph",
        "inputs": {
            "use_structural_fieldfacts": True,
            "use_semantic_facts": True,
        },
        "determinism": {
            "ordering": ["field_path"],
        },
        "steps": [
            {"id": "gather", "instruction": "Collect contributor facts."},
            {"id": "render", "instruction": "Render paragraph."},
        ],
        "notes": "Test render plan",
    }


@pytest.fixture
def artifacts_dir(fs: FakeFilesystem, sample_manifest: dict) -> Path:
    """Create a fake artifacts directory with manifest."""
    artifacts_path = Path("/fake/.knowledge/artifacts")
    fs.create_dir(artifacts_path)

    # Create manifest file
    manifest_path = artifacts_path / f"{sample_manifest['artifact_id']}.yml"
    fs.create_file(manifest_path, contents=yaml.safe_dump(sample_manifest))

    return artifacts_path


@pytest.fixture
def render_plans_dir(fs: FakeFilesystem, sample_render_plan: dict) -> Path:
    """Create a fake render plans directory with plan."""
    plans_path = Path("/fake/.knowledge/artifacts/render_plans")
    fs.create_dir(plans_path)

    # Create render plan file
    plan_path = plans_path / "prose.paragraph.v1.yml"
    fs.create_file(plan_path, contents=yaml.safe_dump(sample_render_plan))

    return plans_path


@pytest.fixture
def rendered_dir(fs: FakeFilesystem) -> Path:
    """Create a fake rendered directory."""
    rendered_path = Path("/fake/.knowledge/artifacts/rendered")
    fs.create_dir(rendered_path)
    return rendered_path


class TestParseArgs:
    """Tests for parse_args function."""

    def test_defaults(self) -> None:
        """Verify default argument values."""
        args = parse_args([])

        assert args.validate is False
        assert args.v1_only is True
        assert args.artifact_id is None
        assert args.artifact_kind is None
        assert args.source_file is None

    def test_validate_flag(self) -> None:
        """Verify --validate flag is parsed."""
        args = parse_args(["--validate"])
        assert args.validate is True

    def test_filter_flags(self) -> None:
        """Verify filter flags are parsed."""
        args = parse_args(
            [
                "--artifact-id",
                "abc123",
                "--artifact-kind",
                "diagram/*",
                "--source-file",
                "docs/test.yml",
            ]
        )

        assert args.artifact_id == "abc123"
        assert args.artifact_kind == "diagram/*"
        assert args.source_file == "docs/test.yml"

    def test_no_v1_only(self) -> None:
        """Verify --no-v1-only flag is parsed."""
        args = parse_args(["--no-v1-only"])
        assert args.v1_only is False


class TestFilterManifests:
    """Tests for _filter_manifests function."""

    def test_no_filters_returns_all(self, sample_manifest: dict) -> None:
        """Verify no filters returns all manifests."""
        manifests = [sample_manifest]

        result = _filter_manifests(manifests, None, None, None)

        assert len(result) == 1

    def test_filter_by_artifact_id_prefix(self, sample_manifest: dict) -> None:
        """Verify filtering by artifact_id prefix."""
        manifests = [sample_manifest]

        result = _filter_manifests(manifests, "abc123", None, None)
        assert len(result) == 1

        result = _filter_manifests(manifests, "xyz", None, None)
        assert len(result) == 0

    def test_filter_by_artifact_kind_pattern(self, sample_manifest: dict) -> None:
        """Verify filtering by artifact_kind pattern."""
        manifests = [sample_manifest]

        result = _filter_manifests(manifests, None, "prose/*", None)
        assert len(result) == 1

        result = _filter_manifests(manifests, None, "diagram/*", None)
        assert len(result) == 0

    def test_filter_by_source_file(self, sample_manifest: dict) -> None:
        """Verify filtering by source_file."""
        manifests = [sample_manifest]

        result = _filter_manifests(manifests, None, None, "docs/test.yml")
        assert len(result) == 1

        result = _filter_manifests(manifests, None, None, "docs/other.yml")
        assert len(result) == 0

    def test_multiple_filters(self, sample_manifest: dict) -> None:
        """Verify multiple filters are combined."""
        manifests = [sample_manifest]

        result = _filter_manifests(manifests, "abc", "prose/*", "docs/test.yml")
        assert len(result) == 1

        result = _filter_manifests(manifests, "abc", "diagram/*", "docs/test.yml")
        assert len(result) == 0


class TestGetSourceText:
    """Tests for _get_source_text function."""

    def test_returns_source_content(self, fs: FakeFilesystem, sample_manifest: dict) -> None:
        """Verify source content is returned."""
        # Create source file
        source_path = Path("/fake/docs/test.yml")
        fs.create_file(source_path, contents="description: Test content")

        # Make manifest use fake path
        sample_manifest["source"]["source_file"] = "/fake/docs/test.yml"

        result = _get_source_text(sample_manifest)

        # field_path is "description", so the extracted value is "Test content"
        assert "Test content" in result

    def test_returns_empty_for_missing_source(
        self, fs: FakeFilesystem, sample_manifest: dict
    ) -> None:
        """Verify empty string for missing source file."""
        sample_manifest["source"]["source_file"] = "/nonexistent/path.yml"

        result = _get_source_text(sample_manifest)

        assert result == ""

    def test_returns_empty_for_no_source_file(
        self, fs: FakeFilesystem, sample_manifest: dict
    ) -> None:
        """Verify empty string when no source_file."""
        sample_manifest["source"]["source_file"] = ""

        result = _get_source_text(sample_manifest)

        assert result == ""


class TestRenderManifest:
    """Tests for _render_manifest function."""

    def test_renders_manifest_successfully(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        render_plans_dir: Path,
        rendered_dir: Path,
        sample_manifest: dict,
    ) -> None:
        """Verify manifest is rendered successfully."""
        validations_csv = artifacts_dir / "validations.csv"

        success, _, _ = _render_manifest(
            sample_manifest,
            artifacts_dir,
            render_plans_dir,
            rendered_dir,
            do_validate=False,
            validations_csv=validations_csv,
        )

        assert success is True

        # Check rendered file exists
        rendered_files = list(rendered_dir.glob("*.md"))
        assert len(rendered_files) == 1

    def test_returns_false_for_missing_render_plan(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        rendered_dir: Path,
        sample_manifest: dict,
    ) -> None:
        """Verify returns False when render plan missing."""
        # Empty render plans dir
        empty_plans_dir = Path("/fake/empty_plans")
        fs.create_dir(empty_plans_dir)
        validations_csv = artifacts_dir / "validations.csv"

        # Use non-existent render plan
        sample_manifest["render_plan_id"] = "nonexistent.v1"

        success, _, _ = _render_manifest(
            sample_manifest,
            artifacts_dir,
            empty_plans_dir,
            rendered_dir,
            do_validate=False,
            validations_csv=validations_csv,
        )

        assert success is False


class TestMain:
    """Tests for main function."""

    def test_no_manifests_returns_zero(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Verify returns 0 when no manifests found."""
        empty_dir = Path("/fake/empty")
        fs.create_dir(empty_dir)

        result = main(
            [
                "--artifacts-dir",
                str(empty_dir),
            ]
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "No artifact manifests found" in captured.out

    def test_renders_artifacts(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        render_plans_dir: Path,
        rendered_dir: Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Verify artifacts are rendered successfully."""
        result = main(
            [
                "--artifacts-dir",
                str(artifacts_dir),
                "--render-plans-dir",
                str(render_plans_dir),
                "--rendered-dir",
                str(rendered_dir),
            ]
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "Rendered successfully: 1" in captured.out

    def test_filter_by_artifact_kind(
        self,
        fs: FakeFilesystem,
        artifacts_dir: Path,
        render_plans_dir: Path,
        rendered_dir: Path,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """Verify filtering by artifact_kind works."""
        result = main(
            [
                "--artifacts-dir",
                str(artifacts_dir),
                "--render-plans-dir",
                str(render_plans_dir),
                "--rendered-dir",
                str(rendered_dir),
                "--artifact-kind",
                "diagram/*",  # Won't match prose/paragraph
            ]
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "No manifests match" in captured.out
