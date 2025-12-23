"""Tests for scripts/knowledge/render_artifacts.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts.knowledge import render_artifacts
from scripts.knowledge.artifact_validator import ValidationResult


def _create_manifest(artifact_id: str = "test-123456789012", **overrides: Any) -> dict[str, Any]:
    """Create a valid artifact manifest dict for testing."""
    manifest: dict[str, Any] = {
        "artifact_id": artifact_id,
        "artifact_kind": "prose/paragraph",
        "artifact_format": "markdown",
        "modality": "text",
        "extraction_mode": "full",
        "render_plan_id": "prose.paragraph.v1",
        "projection_version": "fieldfacts.v2",
        "source": {"source_file": "test.yml", "source_element_id": "test"},
        "contributors": {},
        "entities": [],
        "rendered": {},
    }
    manifest.update(overrides)
    return manifest


class TestMain:
    """Tests for main() function."""

    def test_main_no_manifests(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test main() when no manifests exist."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()

        result = render_artifacts.main(
            [
                "--artifacts-dir",
                str(artifacts_dir),
            ]
        )

        assert result == 0
        captured = capsys.readouterr()
        assert "No artifact manifests found" in captured.out

    def test_main_no_matching_filters(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """Test main() when no manifests match filters."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()

        manifests = [_create_manifest("test-123")]

        with patch.object(render_artifacts, "list_artifact_manifests", return_value=manifests):
            result = render_artifacts.main(
                ["--artifacts-dir", str(artifacts_dir), "--artifact-id", "nonexistent"]
            )

        assert result == 0
        captured = capsys.readouterr()
        assert "No manifests match" in captured.out

    def test_main_legacy_mode_render_success(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() in legacy mode with successful render (lines 460, 469-477)."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        render_plans_dir = artifacts_dir / "render_plans"
        render_plans_dir.mkdir()
        rendered_dir = artifacts_dir / "rendered"
        rendered_dir.mkdir()

        manifests = [_create_manifest()]

        with patch.object(render_artifacts, "list_artifact_manifests", return_value=manifests), patch.object(
            render_artifacts, "_render_manifest"
        ) as mock_render:
            mock_render.return_value = (True, True, None)

            result = render_artifacts.main(
                [
                    "--artifacts-dir",
                    str(artifacts_dir),
                    "--render-plans-dir",
                    str(render_plans_dir),
                    "--rendered-dir",
                    str(rendered_dir),
                    "--legacy-mode",
                ]
            )

        assert result == 0
        captured = capsys.readouterr()
        assert "Rendered successfully: 1" in captured.out

    def test_main_legacy_mode_render_failed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() in legacy mode with failed render (line 477)."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        render_plans_dir = artifacts_dir / "render_plans"
        render_plans_dir.mkdir()
        rendered_dir = artifacts_dir / "rendered"
        rendered_dir.mkdir()

        manifests = [_create_manifest()]

        with patch.object(render_artifacts, "list_artifact_manifests", return_value=manifests), patch.object(
            render_artifacts, "_render_manifest"
        ) as mock_render:
            mock_render.return_value = (False, False, None)

            result = render_artifacts.main(
                [
                    "--artifacts-dir",
                    str(artifacts_dir),
                    "--render-plans-dir",
                    str(render_plans_dir),
                    "--rendered-dir",
                    str(rendered_dir),
                    "--legacy-mode",
                ]
            )

        assert result == 1
        captured = capsys.readouterr()
        assert "Render failed: 1" in captured.out

    def test_main_legacy_mode_validation_failed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() in legacy mode with validation failure (lines 471-475)."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        render_plans_dir = artifacts_dir / "render_plans"
        render_plans_dir.mkdir()
        rendered_dir = artifacts_dir / "rendered"
        rendered_dir.mkdir()
        validations_csv = artifacts_dir / "validations.csv"

        manifests = [_create_manifest()]

        with patch.object(render_artifacts, "list_artifact_manifests", return_value=manifests), patch.object(
            render_artifacts, "_render_manifest"
        ) as mock_render:
            mock_render.return_value = (True, False, None)  # render OK, validation failed

            result = render_artifacts.main(
                [
                    "--artifacts-dir",
                    str(artifacts_dir),
                    "--render-plans-dir",
                    str(render_plans_dir),
                    "--rendered-dir",
                    str(rendered_dir),
                    "--validations-csv",
                    str(validations_csv),
                    "--legacy-mode",
                    "--validate",
                ]
            )

        assert result == 0
        captured = capsys.readouterr()
        assert "Validation failed: 1" in captured.out

    def test_main_lifecycle_mode_success(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() in default lifecycle mode with success (lines 492-495)."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        rendered_dir = artifacts_dir / "rendered"
        rendered_dir.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        validations_csv = artifacts_dir / "validations.csv"

        manifests = [_create_manifest()]

        mock_validation = ValidationResult(
            validation_id="val-001",
            artifact_id="test-123456789012",
            passed=True,
            similarity_score=0.95,
        )

        with patch.object(render_artifacts, "list_artifact_manifests", return_value=manifests), patch.object(
            render_artifacts, "execute_artifact_lifecycle"
        ) as mock_lifecycle:
            mock_lifecycle.return_value = (Path("/rendered/test.txt"), mock_validation)

            result = render_artifacts.main(
                [
                    "--artifacts-dir",
                    str(artifacts_dir),
                    "--rendered-dir",
                    str(rendered_dir),
                    "--validations-csv",
                    str(validations_csv),
                    "--knowledge-path",
                    str(knowledge_path),
                ]
            )

        assert result == 0
        captured = capsys.readouterr()
        assert "Rendered successfully: 1" in captured.out
        assert "Validation passed: 1" in captured.out

    def test_main_lifecycle_mode_validation_failed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() in lifecycle mode with validation failure (lines 492-495)."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        rendered_dir = artifacts_dir / "rendered"
        rendered_dir.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        validations_csv = artifacts_dir / "validations.csv"

        manifests = [_create_manifest()]

        mock_validation = ValidationResult(
            validation_id="val-001",
            artifact_id="test-123456789012",
            passed=False,
            similarity_score=0.50,
        )

        with patch.object(render_artifacts, "list_artifact_manifests", return_value=manifests), patch.object(
            render_artifacts, "execute_artifact_lifecycle"
        ) as mock_lifecycle:
            mock_lifecycle.return_value = (Path("/rendered/test.txt"), mock_validation)

            result = render_artifacts.main(
                [
                    "--artifacts-dir",
                    str(artifacts_dir),
                    "--rendered-dir",
                    str(rendered_dir),
                    "--validations-csv",
                    str(validations_csv),
                    "--knowledge-path",
                    str(knowledge_path),
                ]
            )

        assert result == 0
        captured = capsys.readouterr()
        assert "Validation failed: 1" in captured.out

    def test_main_lifecycle_mode_skipped_non_v1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() skipping non-V1 artifacts (lines 496-504)."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        rendered_dir = artifacts_dir / "rendered"
        rendered_dir.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        validations_csv = artifacts_dir / "validations.csv"

        # Non-V1 manifest
        manifests = [
            _create_manifest(
                artifact_kind="diagram/mermaid", modality="image", extraction_mode="partial"
            )
        ]

        with patch.object(render_artifacts, "list_artifact_manifests", return_value=manifests), patch.object(
            render_artifacts, "execute_artifact_lifecycle"
        ) as mock_lifecycle:
            mock_lifecycle.return_value = (None, None)  # Skipped

            result = render_artifacts.main(
                [
                    "--artifacts-dir",
                    str(artifacts_dir),
                    "--rendered-dir",
                    str(rendered_dir),
                    "--validations-csv",
                    str(validations_csv),
                    "--knowledge-path",
                    str(knowledge_path),
                    "--no-v1-only",  # Include non-V1 artifacts
                ]
            )

        assert result == 0

    def test_main_lifecycle_mode_exception(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """Test main() handling lifecycle exception (lines 505-507)."""
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        rendered_dir = artifacts_dir / "rendered"
        rendered_dir.mkdir()
        knowledge_path = tmp_path / ".knowledge"
        knowledge_path.mkdir()
        validations_csv = artifacts_dir / "validations.csv"

        manifests = [_create_manifest()]

        with patch.object(render_artifacts, "list_artifact_manifests", return_value=manifests), patch.object(
            render_artifacts, "execute_artifact_lifecycle"
        ) as mock_lifecycle:
            mock_lifecycle.side_effect = RuntimeError("Lifecycle failed")

            result = render_artifacts.main(
                [
                    "--artifacts-dir",
                    str(artifacts_dir),
                    "--rendered-dir",
                    str(rendered_dir),
                    "--validations-csv",
                    str(validations_csv),
                    "--knowledge-path",
                    str(knowledge_path),
                ]
            )

        assert result == 1
        captured = capsys.readouterr()
        assert "Render failed: 1" in captured.out
