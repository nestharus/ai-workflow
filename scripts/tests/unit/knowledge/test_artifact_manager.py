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


class TestCreateArtifactManifest:
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


class TestExecuteArtifactLifecycle:
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
