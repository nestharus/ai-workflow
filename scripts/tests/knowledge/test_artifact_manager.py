"""Unit tests for artifact_manager module."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pyfakefs.fake_filesystem import FakeFilesystem

from scripts.knowledge.artifact_manager import (
    artifact_to_manifest,
    create_artifact_manifest,
    delete_artifact_manifest,
    execute_artifact_lifecycle,
    get_manifests_by_kind,
    get_manifests_by_source_file,
    list_artifact_manifests,
    load_artifact_manifest,
    set_validation_result,
    update_artifact_manifest,
)
from scripts.knowledge.compare_yaml_docs import Artifact


@pytest.fixture
def sample_artifact() -> Artifact:
    """Create a sample Artifact for testing."""
    return Artifact(
        artifact_id="abc123def456789012345678901234567890123456789012345678901234",
        artifact_kind="diagram/mermaid.sequence",
        artifact_format="text/x-mermaid",
        source_file="docs/architecture/event-flow.yml",
        source_element_id="sequence-diagram-code-1",
        field_path="text",
        source_locator="inline",
        source_uri=None,
        render_engine="text_llm",
        render_plan_id="diagram.mermaid.sequence.v1",
        projection_version="fieldfacts.v2",
        modality="text",
        extraction_mode="full",
    )


@pytest.fixture
def artifacts_dir(fs: FakeFilesystem) -> Path:
    """Create a fake artifacts directory."""
    artifacts_path = Path("/fake/.knowledge/artifacts")
    fs.create_dir(artifacts_path)
    return artifacts_path


class TestArtifactToManifest:
    """Tests for artifact_to_manifest function."""

    def test_converts_artifact_to_manifest(self, sample_artifact: Artifact) -> None:
        """Verify artifact is correctly converted to manifest dict."""
        manifest = artifact_to_manifest(sample_artifact)

        assert manifest["artifact_id"] == sample_artifact.artifact_id
        assert manifest["artifact_kind"] == "diagram/mermaid.sequence"
        assert manifest["artifact_format"] == "text/x-mermaid"
        assert manifest["render_plan_id"] == "diagram.mermaid.sequence.v1"
        assert manifest["projection_version"] == "fieldfacts.v2"
        assert manifest["modality"] == "text"
        assert manifest["extraction_mode"] == "full"

    def test_source_info_populated(self, sample_artifact: Artifact) -> None:
        """Verify source info is correctly populated."""
        manifest = artifact_to_manifest(sample_artifact)

        assert manifest["source"]["source_file"] == "docs/architecture/event-flow.yml"
        assert manifest["source"]["source_element_id"] == "sequence-diagram-code-1"
        assert manifest["source"]["field_path"] == "text"
        assert manifest["source"]["source_locator"] == "inline"
        assert manifest["source"]["source_uri"] is None

    def test_contributors_entities_rendered_empty(self, sample_artifact: Artifact) -> None:
        """Verify contributors, entities, and rendered are initialized empty."""
        manifest = artifact_to_manifest(sample_artifact)

        assert manifest["contributors"]["structural"] == []
        assert manifest["contributors"]["semantic"] == []
        assert manifest["entities"] == []
        assert manifest["rendered"]["path"] == ""
        assert manifest["rendered"]["validation"]["last_validated_at"] == ""


class TestCreateArtifactManifest:
    """Tests for create_artifact_manifest function."""

    def test_creates_manifest_file(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify manifest file is created at correct path."""
        result = create_artifact_manifest(sample_artifact, artifacts_dir)

        expected_path = artifacts_dir / f"{sample_artifact.artifact_id}.yml"
        assert result == expected_path
        assert expected_path.exists()

    def test_manifest_content_valid_yaml(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify manifest content is valid YAML."""
        result = create_artifact_manifest(sample_artifact, artifacts_dir)

        content = result.read_text()
        data = yaml.safe_load(content)

        assert data["artifact_id"] == sample_artifact.artifact_id
        assert data["artifact_kind"] == "diagram/mermaid.sequence"

    def test_creates_parent_dirs(self, fs: FakeFilesystem, sample_artifact: Artifact) -> None:
        """Verify parent directories are created if they don't exist."""
        artifacts_dir = Path("/new/path/artifacts")
        # Don't create dir - let function create it

        result = create_artifact_manifest(sample_artifact, artifacts_dir)

        assert result.exists()
        assert artifacts_dir.exists()

    def test_raises_runtime_error_on_yaml_serialization_failure(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify RuntimeError raised when YAML serialization fails."""
        from unittest.mock import patch

        # Mock yaml.safe_dump to raise YAMLError
        with patch("scripts.knowledge.artifact_manager.yaml.safe_dump") as mock_dump:
            mock_dump.side_effect = yaml.YAMLError("Serialization failed")

            with pytest.raises(RuntimeError, match="Failed to serialize artifact manifest"):
                create_artifact_manifest(sample_artifact, artifacts_dir)

    def test_raises_os_error_on_file_write_failure(
        self, fs: FakeFilesystem, sample_artifact: Artifact
    ) -> None:
        """Verify OSError raised when file write fails."""
        import os

        # Create a directory that we'll make read-only
        artifacts_dir = Path("/readonly_artifacts")
        fs.create_dir(artifacts_dir)

        # Make the directory read-only in fake filesystem
        # pyfakefs supports changing permissions
        os.chmod(str(artifacts_dir), 0o444)

        with pytest.raises(OSError):
            create_artifact_manifest(sample_artifact, artifacts_dir)


class TestLoadArtifactManifest:
    """Tests for load_artifact_manifest function."""

    def test_loads_existing_manifest(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify manifest is correctly loaded from file."""
        create_artifact_manifest(sample_artifact, artifacts_dir)

        manifest = load_artifact_manifest(sample_artifact.artifact_id, artifacts_dir)

        assert manifest["artifact_id"] == sample_artifact.artifact_id
        assert manifest["artifact_kind"] == "diagram/mermaid.sequence"

    def test_raises_for_missing_manifest(self, fs: FakeFilesystem, artifacts_dir: Path) -> None:
        """Verify FileNotFoundError raised for missing manifest."""
        with pytest.raises(FileNotFoundError, match="Artifact manifest not found"):
            load_artifact_manifest("nonexistent-id", artifacts_dir)

    def test_raises_for_invalid_yaml(self, fs: FakeFilesystem, artifacts_dir: Path) -> None:
        """Verify ValueError raised for invalid YAML."""
        manifest_path = artifacts_dir / "bad-manifest.yml"
        fs.create_file(manifest_path, contents="invalid: yaml: syntax: {{")

        with pytest.raises(ValueError, match="Invalid YAML"):
            load_artifact_manifest("bad-manifest", artifacts_dir)

    def test_raises_for_missing_required_fields(
        self, fs: FakeFilesystem, artifacts_dir: Path
    ) -> None:
        """Verify ValueError raised for missing required fields."""
        manifest_path = artifacts_dir / "incomplete.yml"
        fs.create_file(manifest_path, contents="artifact_id: incomplete\n")

        with pytest.raises(ValueError, match="missing required fields"):
            load_artifact_manifest("incomplete", artifacts_dir)

    def test_adds_defaults_for_optional_fields(
        self, fs: FakeFilesystem, artifacts_dir: Path
    ) -> None:
        """Verify defaults added for optional fields."""
        minimal_manifest = {
            "artifact_id": "minimal-id",
            "artifact_kind": "prose/paragraph",
            "artifact_format": "text/markdown",
            "source": {
                "source_file": "test.yml",
                "source_element_id": "test-id",
                "field_path": "text",
                "source_locator": "inline",
                "source_uri": None,
            },
            "render_plan_id": "prose.paragraph.v1",
            "projection_version": "fieldfacts.v2",
        }
        manifest_path = artifacts_dir / "minimal-id.yml"
        fs.create_file(manifest_path, contents=yaml.safe_dump(minimal_manifest))

        manifest = load_artifact_manifest("minimal-id", artifacts_dir)

        assert manifest["modality"] == "text"
        assert manifest["extraction_mode"] == "full"
        assert manifest["contributors"]["structural"] == []
        assert manifest["entities"] == []

    def test_raises_type_error_when_manifest_is_not_dict(
        self, fs: FakeFilesystem, artifacts_dir: Path
    ) -> None:
        """Verify TypeError raised when manifest content is not a dict."""
        # Create a manifest file that contains a list instead of a dict
        manifest_path = artifacts_dir / "list-manifest.yml"
        fs.create_file(manifest_path, contents="- item1\n- item2\n")

        with pytest.raises(TypeError, match="Artifact manifest must be a dict"):
            load_artifact_manifest("list-manifest", artifacts_dir)


class TestUpdateArtifactManifest:
    """Tests for update_artifact_manifest function."""

    def test_updates_simple_fields(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify simple field updates work."""
        create_artifact_manifest(sample_artifact, artifacts_dir)

        update_artifact_manifest(
            sample_artifact.artifact_id,
            {"render_plan_id": "new.render.plan.v2"},
            artifacts_dir,
        )

        manifest = load_artifact_manifest(sample_artifact.artifact_id, artifacts_dir)
        assert manifest["render_plan_id"] == "new.render.plan.v2"

    def test_deep_merge_nested_fields(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify nested fields are deep merged."""
        create_artifact_manifest(sample_artifact, artifacts_dir)

        update_artifact_manifest(
            sample_artifact.artifact_id,
            {"contributors": {"structural": [{"element_id": "test", "field_path": "text"}]}},
            artifacts_dir,
        )

        manifest = load_artifact_manifest(sample_artifact.artifact_id, artifacts_dir)
        assert len(manifest["contributors"]["structural"]) == 1
        assert manifest["contributors"]["structural"][0]["element_id"] == "test"

    def test_raises_for_missing_manifest(self, fs: FakeFilesystem, artifacts_dir: Path) -> None:
        """Verify FileNotFoundError raised for missing manifest."""
        with pytest.raises(FileNotFoundError):
            update_artifact_manifest("nonexistent", {"key": "value"}, artifacts_dir)


class TestListArtifactManifests:
    """Tests for list_artifact_manifests function."""

    def test_lists_all_manifests(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify all manifests are listed."""
        # Create multiple manifests
        create_artifact_manifest(sample_artifact, artifacts_dir)

        artifact2 = Artifact(
            artifact_id="xyz789",
            artifact_kind="prose/code-block",
            artifact_format="text/markdown",
            source_file="docs/test.yml",
            source_element_id="code-1",
            field_path="sample_code",
            source_locator="inline",
            source_uri=None,
            render_engine="text_llm",
            render_plan_id="prose.code-block.v1",
            projection_version="fieldfacts.v2",
        )
        create_artifact_manifest(artifact2, artifacts_dir)

        manifests = list_artifact_manifests(artifacts_dir, filter_v1_only=False)

        assert len(manifests) == 2

    def test_filters_by_v1_rule(self, fs: FakeFilesystem, artifacts_dir: Path) -> None:
        """Verify V1 filtering works (modality=text AND extraction_mode=full)."""
        # Create V1-compliant manifest
        v1_artifact = Artifact(
            artifact_id="v1-artifact",
            artifact_kind="diagram/mermaid.sequence",
            artifact_format="text/x-mermaid",
            source_file="docs/test.yml",
            source_element_id="test-id",
            field_path="text",
            source_locator="inline",
            source_uri=None,
            render_engine="text_llm",
            render_plan_id="diagram.mermaid.sequence.v1",
            projection_version="fieldfacts.v2",
            modality="text",
            extraction_mode="full",
        )
        create_artifact_manifest(v1_artifact, artifacts_dir)

        # Create non-V1 manifest (manually modify the file)
        non_v1_manifest = {
            "artifact_id": "non-v1-artifact",
            "artifact_kind": "image/png",
            "artifact_format": "image/png",
            "source": {
                "source_file": "docs/test.yml",
                "source_element_id": "test-id",
                "field_path": "image",
                "source_locator": "reference",
                "source_uri": "assets/image.png",
            },
            "render_plan_id": "none",
            "projection_version": "fieldfacts.v2",
            "modality": "image",  # Non-V1
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
        non_v1_path = artifacts_dir / "non-v1-artifact.yml"
        fs.create_file(non_v1_path, contents=yaml.safe_dump(non_v1_manifest))

        # V1 filter should only return V1 artifact
        v1_manifests = list_artifact_manifests(artifacts_dir, filter_v1_only=True)
        assert len(v1_manifests) == 1
        assert v1_manifests[0]["artifact_id"] == "v1-artifact"

        # Without filter, both should be returned
        all_manifests = list_artifact_manifests(artifacts_dir, filter_v1_only=False)
        assert len(all_manifests) == 2

    def test_returns_empty_for_nonexistent_dir(self, fs: FakeFilesystem) -> None:
        """Verify empty list returned for nonexistent directory."""
        manifests = list_artifact_manifests(Path("/nonexistent"))
        assert manifests == []

    def test_skips_kinds_yml(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify kinds.yml registry file is skipped."""
        create_artifact_manifest(sample_artifact, artifacts_dir)

        # Create kinds.yml registry file
        kinds_path = artifacts_dir / "kinds.yml"
        fs.create_file(kinds_path, contents="kinds: []\n")

        manifests = list_artifact_manifests(artifacts_dir, filter_v1_only=False)

        # Should only find the artifact manifest, not kinds.yml
        assert len(manifests) == 1


class TestDeleteArtifactManifest:
    """Tests for delete_artifact_manifest function."""

    def test_deletes_existing_manifest(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify manifest file is deleted."""
        path = create_artifact_manifest(sample_artifact, artifacts_dir)
        assert path.exists()

        delete_artifact_manifest(sample_artifact.artifact_id, artifacts_dir)

        assert not path.exists()

    def test_raises_for_missing_manifest(self, fs: FakeFilesystem, artifacts_dir: Path) -> None:
        """Verify FileNotFoundError raised for missing manifest."""
        with pytest.raises(FileNotFoundError, match="Artifact manifest not found"):
            delete_artifact_manifest("nonexistent", artifacts_dir)


class TestGetManifestsBySourceFile:
    """Tests for get_manifests_by_source_file function."""

    def test_filters_by_source_file(self, fs: FakeFilesystem, artifacts_dir: Path) -> None:
        """Verify filtering by source file works."""
        artifact1 = Artifact(
            artifact_id="artifact-1",
            artifact_kind="diagram/mermaid.sequence",
            artifact_format="text/x-mermaid",
            source_file="docs/architecture/event-flow.yml",
            source_element_id="test-1",
            field_path="text",
            source_locator="inline",
            source_uri=None,
            render_engine="text_llm",
            render_plan_id="diagram.mermaid.sequence.v1",
            projection_version="fieldfacts.v2",
        )
        artifact2 = Artifact(
            artifact_id="artifact-2",
            artifact_kind="prose/code-block",
            artifact_format="text/markdown",
            source_file="docs/development/test.yml",
            source_element_id="test-2",
            field_path="sample_code",
            source_locator="inline",
            source_uri=None,
            render_engine="text_llm",
            render_plan_id="prose.code-block.v1",
            projection_version="fieldfacts.v2",
        )
        create_artifact_manifest(artifact1, artifacts_dir)
        create_artifact_manifest(artifact2, artifacts_dir)

        results = get_manifests_by_source_file(
            "docs/architecture/event-flow.yml",
            artifacts_dir,
            filter_v1_only=False,
        )

        assert len(results) == 1
        assert results[0]["artifact_id"] == "artifact-1"


class TestGetManifestsByKind:
    """Tests for get_manifests_by_kind function."""

    def test_filters_by_exact_kind(self, fs: FakeFilesystem, artifacts_dir: Path) -> None:
        """Verify exact artifact_kind filtering."""
        artifact1 = Artifact(
            artifact_id="artifact-1",
            artifact_kind="diagram/mermaid.sequence",
            artifact_format="text/x-mermaid",
            source_file="docs/test.yml",
            source_element_id="test-1",
            field_path="text",
            source_locator="inline",
            source_uri=None,
            render_engine="text_llm",
            render_plan_id="diagram.mermaid.sequence.v1",
            projection_version="fieldfacts.v2",
        )
        artifact2 = Artifact(
            artifact_id="artifact-2",
            artifact_kind="prose/code-block",
            artifact_format="text/markdown",
            source_file="docs/test.yml",
            source_element_id="test-2",
            field_path="sample_code",
            source_locator="inline",
            source_uri=None,
            render_engine="text_llm",
            render_plan_id="prose.code-block.v1",
            projection_version="fieldfacts.v2",
        )
        create_artifact_manifest(artifact1, artifacts_dir)
        create_artifact_manifest(artifact2, artifacts_dir)

        results = get_manifests_by_kind(
            "diagram/mermaid.sequence",
            artifacts_dir,
            filter_v1_only=False,
        )

        assert len(results) == 1
        assert results[0]["artifact_kind"] == "diagram/mermaid.sequence"

    def test_filters_by_wildcard_pattern(self, fs: FakeFilesystem, artifacts_dir: Path) -> None:
        """Verify wildcard pattern filtering works."""
        artifact1 = Artifact(
            artifact_id="artifact-1",
            artifact_kind="diagram/mermaid.sequence",
            artifact_format="text/x-mermaid",
            source_file="docs/test.yml",
            source_element_id="test-1",
            field_path="text",
            source_locator="inline",
            source_uri=None,
            render_engine="text_llm",
            render_plan_id="diagram.mermaid.sequence.v1",
            projection_version="fieldfacts.v2",
        )
        artifact2 = Artifact(
            artifact_id="artifact-2",
            artifact_kind="diagram/mermaid.flowchart",
            artifact_format="text/x-mermaid",
            source_file="docs/test.yml",
            source_element_id="test-2",
            field_path="text",
            source_locator="inline",
            source_uri=None,
            render_engine="text_llm",
            render_plan_id="diagram.mermaid.flowchart.v1",
            projection_version="fieldfacts.v2",
        )
        artifact3 = Artifact(
            artifact_id="artifact-3",
            artifact_kind="prose/code-block",
            artifact_format="text/markdown",
            source_file="docs/test.yml",
            source_element_id="test-3",
            field_path="sample_code",
            source_locator="inline",
            source_uri=None,
            render_engine="text_llm",
            render_plan_id="prose.code-block.v1",
            projection_version="fieldfacts.v2",
        )
        create_artifact_manifest(artifact1, artifacts_dir)
        create_artifact_manifest(artifact2, artifacts_dir)
        create_artifact_manifest(artifact3, artifacts_dir)

        results = get_manifests_by_kind(
            "diagram/*",
            artifacts_dir,
            filter_v1_only=False,
        )

        assert len(results) == 2
        kinds = {m["artifact_kind"] for m in results}
        assert kinds == {"diagram/mermaid.sequence", "diagram/mermaid.flowchart"}


class TestSetValidationResult:
    """Tests for set_validation_result function."""

    def test_sets_validation_fields(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify validation fields are set correctly."""
        create_artifact_manifest(sample_artifact, artifacts_dir)

        set_validation_result(
            sample_artifact.artifact_id,
            artifacts_dir,
            similarity="0.95",
            passed=True,
            notes="Validation successful",
        )

        manifest = load_artifact_manifest(sample_artifact.artifact_id, artifacts_dir)
        validation = manifest["rendered"]["validation"]

        assert validation["similarity"] == "0.95"
        assert validation["passed"] == "true"
        assert validation["notes"] == "Validation successful"
        assert validation["last_validated_at"] != ""  # Timestamp set

    def test_sets_failed_validation(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify failed validation is recorded."""
        create_artifact_manifest(sample_artifact, artifacts_dir)

        set_validation_result(
            sample_artifact.artifact_id,
            artifacts_dir,
            similarity="0.5",
            passed=False,
            notes="Content mismatch detected",
        )

        manifest = load_artifact_manifest(sample_artifact.artifact_id, artifacts_dir)
        validation = manifest["rendered"]["validation"]

        assert validation["passed"] == "false"
        assert validation["notes"] == "Content mismatch detected"


class TestExecuteArtifactLifecycle:
    """Tests for execute_artifact_lifecycle function."""

    def test_skips_non_v1_artifacts(self, fs: FakeFilesystem, artifacts_dir: Path) -> None:
        """Verify non-V1 artifacts are skipped."""
        # Create non-V1 manifest (image modality)
        non_v1_manifest = {
            "artifact_id": "non-v1-artifact",
            "artifact_kind": "image/png",
            "artifact_format": "image/png",
            "source": {
                "source_file": "docs/test.yml",
                "source_element_id": "test-id",
                "field_path": "image",
                "source_locator": "reference",
                "source_uri": "assets/image.png",
            },
            "render_plan_id": "none",
            "projection_version": "fieldfacts.v2",
            "modality": "image",  # Non-V1
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
        manifest_path = artifacts_dir / "non-v1-artifact.yml"
        fs.create_file(manifest_path, contents=yaml.safe_dump(non_v1_manifest))

        rendered_dir = artifacts_dir / "rendered"
        fs.create_dir(rendered_dir)
        validations_csv = artifacts_dir / "validations.csv"
        knowledge_path = artifacts_dir.parent

        rendered_path, result = execute_artifact_lifecycle(
            "non-v1-artifact",
            artifacts_dir,
            rendered_dir,
            validations_csv,
            knowledge_path,
        )

        assert rendered_path is None
        assert result is None

    def test_orchestration_with_mocks(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify lifecycle orchestration calls rendering and validation."""
        from dataclasses import dataclass
        from unittest.mock import patch

        # Create manifest
        create_artifact_manifest(sample_artifact, artifacts_dir)

        # Setup directories
        rendered_dir = artifacts_dir / "rendered"
        fs.create_dir(rendered_dir)
        render_plans_dir = artifacts_dir.parent / "render_plans"
        fs.create_dir(render_plans_dir)
        validations_csv = artifacts_dir / "validations.csv"
        knowledge_path = artifacts_dir.parent

        # Create a render plan matching load_render_plan schema expectations
        render_plan_content = {
            "render_plan_id": "diagram.mermaid.sequence.v1",
            "render_engine": "text_llm",
            "artifact_kind": "diagram/mermaid.sequence",
            "inputs": {
                "use_structural_fieldfacts": True,
                "use_semantic_facts": True,
            },
            "determinism": {
                "ordering": ["field_path"],
            },
            "steps": [{"id": "render", "instruction": "Render the artifact"}],
            "notes": "Test render plan for mermaid sequence diagrams",
        }
        render_plan_path = render_plans_dir / "diagram.mermaid.sequence.v1.yml"
        fs.create_file(render_plan_path, contents=yaml.safe_dump(render_plan_content))

        # Create source file
        source_content = {
            "items": [
                {
                    "id": "sequence-diagram-code-1",
                    "text": "sequenceDiagram\n    A->>B: Hello",
                }
            ]
        }
        source_path = artifacts_dir.parent.parent / "docs" / "architecture" / "event-flow.yml"
        fs.create_file(source_path, contents=yaml.safe_dump(source_content))

        # Create mock rendered file
        rendered_file = rendered_dir / f"{sample_artifact.artifact_id}.mmd"

        @dataclass
        class MockValidationResult:
            passed: bool = True
            similarity_score: float = 0.95
            mismatch_summary: str = ""

        mock_validation = MockValidationResult()

        with (
            patch(
                "scripts.knowledge.artifact_renderer.render_artifact", return_value=rendered_file
            ) as mock_render,
            patch(
                "scripts.knowledge.artifact_validator.validate_artifact",
                return_value=mock_validation,
            ) as mock_validate,
            patch("scripts.knowledge.artifact_validator.write_validation_result"),
        ):
            # Create the rendered file that validation expects
            fs.create_file(rendered_file, contents="sequenceDiagram\n    A->>B: Hello")

            _result_path, _result = execute_artifact_lifecycle(
                sample_artifact.artifact_id,
                artifacts_dir,
                rendered_dir,
                validations_csv,
                knowledge_path,
            )

            # Verify render was called
            assert mock_render.called

            # Verify validation was called
            assert mock_validate.called

    def test_handles_missing_render_plan(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify graceful handling when render plan is not found."""
        # Create manifest
        create_artifact_manifest(sample_artifact, artifacts_dir)

        # Setup directories but no render plans
        rendered_dir = artifacts_dir / "rendered"
        fs.create_dir(rendered_dir)
        validations_csv = artifacts_dir / "validations.csv"
        knowledge_path = artifacts_dir.parent

        rendered_path, result = execute_artifact_lifecycle(
            sample_artifact.artifact_id,
            artifacts_dir,
            rendered_dir,
            validations_csv,
            knowledge_path,
        )

        # Should return None when render plan not found
        assert rendered_path is None
        assert result is None

    def test_raises_for_missing_manifest(self, fs: FakeFilesystem, artifacts_dir: Path) -> None:
        """Verify FileNotFoundError raised for missing manifest."""
        rendered_dir = artifacts_dir / "rendered"
        fs.create_dir(rendered_dir)
        validations_csv = artifacts_dir / "validations.csv"
        knowledge_path = artifacts_dir.parent

        with pytest.raises(FileNotFoundError, match="Artifact manifest not found"):
            execute_artifact_lifecycle(
                "nonexistent-id",
                artifacts_dir,
                rendered_dir,
                validations_csv,
                knowledge_path,
            )

    def test_handles_empty_render_plan_id(self, fs: FakeFilesystem, artifacts_dir: Path) -> None:
        """Verify graceful handling when render_plan_id is empty."""
        # Create manifest with empty render_plan_id
        manifest = {
            "artifact_id": "empty-render-plan",
            "artifact_kind": "prose/paragraph",
            "artifact_format": "text/markdown",
            "source": {
                "source_file": "docs/test.yml",
                "source_element_id": "test-id",
                "field_path": "text",
                "source_locator": "inline",
                "source_uri": None,
            },
            "render_plan_id": "",  # Empty render plan
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
        manifest_path = artifacts_dir / "empty-render-plan.yml"
        fs.create_file(manifest_path, contents=yaml.safe_dump(manifest))

        rendered_dir = artifacts_dir / "rendered"
        fs.create_dir(rendered_dir)
        validations_csv = artifacts_dir / "validations.csv"
        knowledge_path = artifacts_dir.parent

        rendered_path, result = execute_artifact_lifecycle(
            "empty-render-plan",
            artifacts_dir,
            rendered_dir,
            validations_csv,
            knowledge_path,
        )

        # Should return None when render_plan_id is empty
        assert rendered_path is None
        assert result is None

    def test_handles_rendering_exception(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify graceful handling when rendering raises an exception."""
        from unittest.mock import patch

        # Create manifest
        create_artifact_manifest(sample_artifact, artifacts_dir)

        # Setup directories
        rendered_dir = artifacts_dir / "rendered"
        fs.create_dir(rendered_dir)
        render_plans_dir = artifacts_dir.parent / "render_plans"
        fs.create_dir(render_plans_dir)
        validations_csv = artifacts_dir / "validations.csv"
        knowledge_path = artifacts_dir.parent

        # Create render plan
        render_plan_content = {
            "render_plan_id": "diagram.mermaid.sequence.v1",
            "render_engine": "text_llm",
            "artifact_kind": "diagram/mermaid.sequence",
            "inputs": {"use_structural_fieldfacts": True, "use_semantic_facts": True},
            "determinism": {"ordering": ["field_path"]},
            "steps": [{"id": "render", "instruction": "Render the artifact"}],
            "notes": "Test render plan",
        }
        render_plan_path = render_plans_dir / "diagram.mermaid.sequence.v1.yml"
        fs.create_file(render_plan_path, contents=yaml.safe_dump(render_plan_content))

        # Mock renderer to raise exception
        with patch(
            "scripts.knowledge.artifact_renderer.render_artifact",
            side_effect=Exception("Rendering failed"),
        ):
            rendered_path, result = execute_artifact_lifecycle(
                sample_artifact.artifact_id,
                artifacts_dir,
                rendered_dir,
                validations_csv,
                knowledge_path,
            )

        # Should return None when rendering fails
        assert rendered_path is None
        assert result is None

    def test_handles_missing_source_file_in_manifest(
        self, fs: FakeFilesystem, artifacts_dir: Path
    ) -> None:
        """Verify graceful handling when source.source_file is empty."""
        from unittest.mock import patch

        # Create manifest with empty source_file
        manifest = {
            "artifact_id": "no-source-file",
            "artifact_kind": "prose/paragraph",
            "artifact_format": "text/markdown",
            "source": {
                "source_file": "",  # Empty source file
                "source_element_id": "test-id",
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
        manifest_path = artifacts_dir / "no-source-file.yml"
        fs.create_file(manifest_path, contents=yaml.safe_dump(manifest))

        # Setup directories
        rendered_dir = artifacts_dir / "rendered"
        fs.create_dir(rendered_dir)
        render_plans_dir = artifacts_dir.parent / "render_plans"
        fs.create_dir(render_plans_dir)
        validations_csv = artifacts_dir / "validations.csv"
        knowledge_path = artifacts_dir.parent

        # Create render plan
        render_plan_content = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": {"use_structural_fieldfacts": True, "use_semantic_facts": True},
            "determinism": {"ordering": ["field_path"]},
            "steps": [{"id": "render", "instruction": "Render the artifact"}],
            "notes": "Test render plan",
        }
        render_plan_path = render_plans_dir / "prose.paragraph.v1.yml"
        fs.create_file(render_plan_path, contents=yaml.safe_dump(render_plan_content))

        # Create mock rendered file
        rendered_file = rendered_dir / "no-source-file.md"
        fs.create_file(rendered_file, contents="Test content")

        with patch(
            "scripts.knowledge.artifact_renderer.render_artifact", return_value=rendered_file
        ):
            rendered_path, result = execute_artifact_lifecycle(
                "no-source-file",
                artifacts_dir,
                rendered_dir,
                validations_csv,
                knowledge_path,
            )

        # Should return rendered_path but None result due to no source_file
        assert rendered_path == rendered_file
        assert result is None

    def test_handles_source_file_not_found(self, fs: FakeFilesystem, artifacts_dir: Path) -> None:
        """Verify graceful handling when source file does not exist."""
        from unittest.mock import patch

        # Create manifest with a source_file path that doesn't exist
        manifest = {
            "artifact_id": "missing-source-test",
            "artifact_kind": "prose/paragraph",
            "artifact_format": "text/markdown",
            "source": {
                "source_file": "docs/nonexistent.yml",  # File won't exist
                "source_element_id": "test-id",
                "field_path": "",
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
        manifest_path = artifacts_dir / "missing-source-test.yml"
        fs.create_file(manifest_path, contents=yaml.safe_dump(manifest))

        # Setup directories
        rendered_dir = artifacts_dir / "rendered"
        fs.create_dir(rendered_dir)
        render_plans_dir = artifacts_dir.parent / "render_plans"
        fs.create_dir(render_plans_dir)
        validations_csv = artifacts_dir / "validations.csv"
        knowledge_path = artifacts_dir.parent

        # Create render plan
        render_plan_content = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": {"use_structural_fieldfacts": True, "use_semantic_facts": True},
            "determinism": {"ordering": ["field_path"]},
            "steps": [{"id": "render", "instruction": "Render the artifact"}],
            "notes": "Test render plan",
        }
        render_plan_path = render_plans_dir / "prose.paragraph.v1.yml"
        fs.create_file(render_plan_path, contents=yaml.safe_dump(render_plan_content))

        # Do NOT create source file - it should not exist

        # Create mock rendered file
        rendered_file = rendered_dir / "missing-source-test.md"
        fs.create_file(rendered_file, contents="Test content")

        with patch(
            "scripts.knowledge.artifact_renderer.render_artifact", return_value=rendered_file
        ):
            rendered_path, result = execute_artifact_lifecycle(
                "missing-source-test",
                artifacts_dir,
                rendered_dir,
                validations_csv,
                knowledge_path,
            )

        # Should return rendered_path but None result due to missing source file
        assert rendered_path == rendered_file
        assert result is None

    def test_handles_validation_exception(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify graceful handling when validation raises an exception."""
        from unittest.mock import patch

        # Create manifest
        create_artifact_manifest(sample_artifact, artifacts_dir)

        # Setup directories
        rendered_dir = artifacts_dir / "rendered"
        fs.create_dir(rendered_dir)
        render_plans_dir = artifacts_dir.parent / "render_plans"
        fs.create_dir(render_plans_dir)
        validations_csv = artifacts_dir / "validations.csv"
        knowledge_path = artifacts_dir.parent

        # Create render plan
        render_plan_content = {
            "render_plan_id": "diagram.mermaid.sequence.v1",
            "render_engine": "text_llm",
            "artifact_kind": "diagram/mermaid.sequence",
            "inputs": {"use_structural_fieldfacts": True, "use_semantic_facts": True},
            "determinism": {"ordering": ["field_path"]},
            "steps": [{"id": "render", "instruction": "Render the artifact"}],
            "notes": "Test render plan",
        }
        render_plan_path = render_plans_dir / "diagram.mermaid.sequence.v1.yml"
        fs.create_file(render_plan_path, contents=yaml.safe_dump(render_plan_content))

        # Create source file
        source_content = {
            "items": [
                {
                    "id": "sequence-diagram-code-1",
                    "text": "sequenceDiagram\n    A->>B: Hello",
                }
            ]
        }
        source_path = artifacts_dir.parent.parent / "docs" / "architecture" / "event-flow.yml"
        fs.create_file(source_path, contents=yaml.safe_dump(source_content))

        # Create mock rendered file
        rendered_file = rendered_dir / f"{sample_artifact.artifact_id}.mmd"
        fs.create_file(rendered_file, contents="sequenceDiagram\n    A->>B: Hello")

        # Mock renderer and validator
        with (
            patch(
                "scripts.knowledge.artifact_renderer.render_artifact", return_value=rendered_file
            ),
            patch(
                "scripts.knowledge.artifact_validator.validate_artifact",
                side_effect=Exception("Validation failed"),
            ),
        ):
            rendered_path, result = execute_artifact_lifecycle(
                sample_artifact.artifact_id,
                artifacts_dir,
                rendered_dir,
                validations_csv,
                knowledge_path,
            )

        # Should return rendered_path but None result due to validation exception
        assert rendered_path == rendered_file
        assert result is None

    def test_handles_manifest_update_exception(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify graceful handling when manifest update fails."""
        from dataclasses import dataclass
        from unittest.mock import patch

        # Create manifest
        create_artifact_manifest(sample_artifact, artifacts_dir)

        # Setup directories
        rendered_dir = artifacts_dir / "rendered"
        fs.create_dir(rendered_dir)
        render_plans_dir = artifacts_dir.parent / "render_plans"
        fs.create_dir(render_plans_dir)
        validations_csv = artifacts_dir / "validations.csv"
        knowledge_path = artifacts_dir.parent

        # Create render plan
        render_plan_content = {
            "render_plan_id": "diagram.mermaid.sequence.v1",
            "render_engine": "text_llm",
            "artifact_kind": "diagram/mermaid.sequence",
            "inputs": {"use_structural_fieldfacts": True, "use_semantic_facts": True},
            "determinism": {"ordering": ["field_path"]},
            "steps": [{"id": "render", "instruction": "Render the artifact"}],
            "notes": "Test render plan",
        }
        render_plan_path = render_plans_dir / "diagram.mermaid.sequence.v1.yml"
        fs.create_file(render_plan_path, contents=yaml.safe_dump(render_plan_content))

        # Create source file
        source_content = {
            "items": [
                {
                    "id": "sequence-diagram-code-1",
                    "text": "sequenceDiagram\n    A->>B: Hello",
                }
            ]
        }
        source_path = artifacts_dir.parent.parent / "docs" / "architecture" / "event-flow.yml"
        fs.create_file(source_path, contents=yaml.safe_dump(source_content))

        # Create mock rendered file
        rendered_file = rendered_dir / f"{sample_artifact.artifact_id}.mmd"
        fs.create_file(rendered_file, contents="sequenceDiagram\n    A->>B: Hello")

        @dataclass
        class MockValidationResult:
            passed: bool = True
            similarity_score: float = 0.95
            mismatch_summary: str = ""

        mock_validation = MockValidationResult()

        # Mock renderer, validator, and set_validation_result
        with (
            patch(
                "scripts.knowledge.artifact_renderer.render_artifact", return_value=rendered_file
            ),
            patch(
                "scripts.knowledge.artifact_validator.validate_artifact",
                return_value=mock_validation,
            ),
            patch("scripts.knowledge.artifact_validator.write_validation_result"),
            patch(
                "scripts.knowledge.artifact_manager.set_validation_result",
                side_effect=Exception("Manifest update failed"),
            ),
        ):
            # Should not raise, just log a warning
            rendered_path, result = execute_artifact_lifecycle(
                sample_artifact.artifact_id,
                artifacts_dir,
                rendered_dir,
                validations_csv,
                knowledge_path,
            )

        # Should still return results even if manifest update fails
        assert rendered_path == rendered_file
        assert result == mock_validation

    def test_extracts_field_path_from_yaml_source(
        self, fs: FakeFilesystem, artifacts_dir: Path
    ) -> None:
        """Verify field_path extraction from YAML source file."""
        from dataclasses import dataclass
        from unittest.mock import patch

        # Create manifest with field_path specified
        manifest = {
            "artifact_id": "field-path-test",
            "artifact_kind": "prose/paragraph",
            "artifact_format": "text/markdown",
            "source": {
                "source_file": "docs/test.yml",
                "source_element_id": "test-id",
                "field_path": "nested.description",  # Field path to extract
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
        manifest_path = artifacts_dir / "field-path-test.yml"
        fs.create_file(manifest_path, contents=yaml.safe_dump(manifest))

        # Setup directories
        rendered_dir = artifacts_dir / "rendered"
        fs.create_dir(rendered_dir)
        render_plans_dir = artifacts_dir.parent / "render_plans"
        fs.create_dir(render_plans_dir)
        validations_csv = artifacts_dir / "validations.csv"
        knowledge_path = artifacts_dir.parent

        # Create render plan
        render_plan_content = {
            "render_plan_id": "prose.paragraph.v1",
            "render_engine": "text_llm",
            "artifact_kind": "prose/paragraph",
            "inputs": {"use_structural_fieldfacts": True, "use_semantic_facts": True},
            "determinism": {"ordering": ["field_path"]},
            "steps": [{"id": "render", "instruction": "Render the artifact"}],
            "notes": "Test render plan",
        }
        render_plan_path = render_plans_dir / "prose.paragraph.v1.yml"
        fs.create_file(render_plan_path, contents=yaml.safe_dump(render_plan_content))

        # Create source file with nested structure
        source_content = {"nested": {"description": "This is the extracted text from field_path"}}
        source_path = artifacts_dir.parent.parent / "docs" / "test.yml"
        fs.create_file(source_path, contents=yaml.safe_dump(source_content))

        # Create mock rendered file
        rendered_file = rendered_dir / "field-path-test.md"
        fs.create_file(rendered_file, contents="This is the extracted text from field_path")

        @dataclass
        class MockValidationResult:
            passed: bool = True
            similarity_score: float = 1.0
            mismatch_summary: str = ""

        mock_validation = MockValidationResult()

        with (
            patch(
                "scripts.knowledge.artifact_renderer.render_artifact", return_value=rendered_file
            ),
            patch(
                "scripts.knowledge.artifact_validator.validate_artifact",
                return_value=mock_validation,
            ) as mock_validate,
            patch("scripts.knowledge.artifact_validator.write_validation_result"),
        ):
            rendered_path, result = execute_artifact_lifecycle(
                "field-path-test",
                artifacts_dir,
                rendered_dir,
                validations_csv,
                knowledge_path,
            )

        assert rendered_path == rendered_file
        assert result == mock_validation
        # Verify that validate_artifact was called with the extracted field content
        assert mock_validate.called

    def test_handles_successful_fact_extraction(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify successful fact extraction is logged."""
        from dataclasses import dataclass
        from unittest.mock import patch

        # Create manifest
        create_artifact_manifest(sample_artifact, artifacts_dir)

        # Setup directories
        rendered_dir = artifacts_dir / "rendered"
        fs.create_dir(rendered_dir)
        render_plans_dir = artifacts_dir.parent / "render_plans"
        fs.create_dir(render_plans_dir)
        validations_csv = artifacts_dir / "validations.csv"
        knowledge_path = artifacts_dir.parent

        # Create render plan
        render_plan_content = {
            "render_plan_id": "diagram.mermaid.sequence.v1",
            "render_engine": "text_llm",
            "artifact_kind": "diagram/mermaid.sequence",
            "inputs": {"use_structural_fieldfacts": True, "use_semantic_facts": True},
            "determinism": {"ordering": ["field_path"]},
            "steps": [{"id": "render", "instruction": "Render"}],
            "notes": "Test",
        }
        render_plan_path = render_plans_dir / "diagram.mermaid.sequence.v1.yml"
        fs.create_file(render_plan_path, contents=yaml.safe_dump(render_plan_content))

        # Create source file
        source_content = {"items": [{"id": "sequence-diagram-code-1", "text": "diagram"}]}
        source_path = artifacts_dir.parent.parent / "docs" / "architecture" / "event-flow.yml"
        fs.create_file(source_path, contents=yaml.safe_dump(source_content))

        rendered_file = rendered_dir / f"{sample_artifact.artifact_id}.mmd"
        fs.create_file(rendered_file, contents="diagram")

        @dataclass
        class MockValidationResult:
            passed: bool = True
            similarity_score: float = 1.0
            mismatch_summary: str = ""

        # Mock with successful fact extraction
        with (
            patch(
                "scripts.knowledge.artifact_fact_extractor.extract_artifact_facts"
            ) as mock_extract_facts,
            patch(
                "scripts.knowledge.artifact_renderer.render_artifact", return_value=rendered_file
            ),
            patch(
                "scripts.knowledge.artifact_validator.validate_artifact",
                return_value=MockValidationResult(),
            ),
            patch("scripts.knowledge.artifact_validator.write_validation_result"),
        ):
            mock_extract_facts.return_value = None  # Successful extraction

            rendered_path, _result = execute_artifact_lifecycle(
                sample_artifact.artifact_id,
                artifacts_dir,
                rendered_dir,
                validations_csv,
                knowledge_path,
            )

        assert mock_extract_facts.called
        assert rendered_path is not None

    def test_handles_import_error_for_fact_extractor(
        self, fs: FakeFilesystem, sample_artifact: Artifact, artifacts_dir: Path
    ) -> None:
        """Verify ImportError is handled gracefully when artifact_fact_extractor not available."""
        from dataclasses import dataclass
        from unittest.mock import patch

        # Create manifest
        create_artifact_manifest(sample_artifact, artifacts_dir)

        # Setup directories
        rendered_dir = artifacts_dir / "rendered"
        fs.create_dir(rendered_dir)
        render_plans_dir = artifacts_dir.parent / "render_plans"
        fs.create_dir(render_plans_dir)
        validations_csv = artifacts_dir / "validations.csv"
        knowledge_path = artifacts_dir.parent

        # Create render plan
        render_plan_content = {
            "render_plan_id": "diagram.mermaid.sequence.v1",
            "render_engine": "text_llm",
            "artifact_kind": "diagram/mermaid.sequence",
            "inputs": {"use_structural_fieldfacts": True, "use_semantic_facts": True},
            "determinism": {"ordering": ["field_path"]},
            "steps": [{"id": "render", "instruction": "Render"}],
            "notes": "Test",
        }
        render_plan_path = render_plans_dir / "diagram.mermaid.sequence.v1.yml"
        fs.create_file(render_plan_path, contents=yaml.safe_dump(render_plan_content))

        # Create source file
        source_content = {"items": [{"id": "sequence-diagram-code-1", "text": "diagram"}]}
        source_path = artifacts_dir.parent.parent / "docs" / "architecture" / "event-flow.yml"
        fs.create_file(source_path, contents=yaml.safe_dump(source_content))

        rendered_file = rendered_dir / f"{sample_artifact.artifact_id}.mmd"
        fs.create_file(rendered_file, contents="diagram")

        @dataclass
        class MockValidationResult:
            passed: bool = True
            similarity_score: float = 1.0
            mismatch_summary: str = ""

        # We need to simulate ImportError for the lazy import inside execute_artifact_lifecycle
        # The function does: from scripts.knowledge.artifact_fact_extractor import ...
        # We'll mock __import__ to raise ImportError for that specific module
        original_import = (
            __builtins__["__import__"]
            if isinstance(__builtins__, dict)
            else __builtins__.__import__
        )

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "artifact_fact_extractor" in name:
                raise ImportError("Module not available")
            return original_import(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=mock_import),
            patch(
                "scripts.knowledge.artifact_renderer.render_artifact", return_value=rendered_file
            ),
            patch(
                "scripts.knowledge.artifact_validator.validate_artifact",
                return_value=MockValidationResult(),
            ),
            patch("scripts.knowledge.artifact_validator.write_validation_result"),
        ):
            # Should not raise - ImportError is caught and logged
            rendered_path, _result = execute_artifact_lifecycle(
                sample_artifact.artifact_id,
                artifacts_dir,
                rendered_dir,
                validations_csv,
                knowledge_path,
            )

        # Lifecycle should continue even without fact extraction
        assert rendered_path is not None
