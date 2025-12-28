"""Tests for scripts.dev.markdown.run_all_converters module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import yaml

from scripts.dev.markdown.converter_base import Document


class TestMain:
    """Tests for the main() function."""

    def test_main_converts_files_from_manifest(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main() reads manifest and converts files (covers branches [31,32], [31,57])."""
        manifest_data = {
            "sources": [
                {"path": "docs/test.md", "target_stub": "docs/test.yml"},
            ]
        }

        mock_doc = Document(
            doc_id="test",
            title="Test",
            description="",
            domain=[],
            scope="general",
            sections=[MagicMock()],
        )

        # Mock Path to return a consistent project root
        mock_source_path = MagicMock()
        mock_source_path.exists.return_value = True

        with (
            patch("scripts.dev.markdown.run_all_converters.Path") as mock_path,
            patch("scripts.dev.markdown.run_all_converters.MarkdownConverter") as mock_conv,
        ):
            # Setup Path mock
            mock_project_root = MagicMock()
            mock_path.return_value.parent.parent.parent = mock_project_root

            # mock_project_root / "path" returns mock paths
            mock_manifest_path = MagicMock()
            mock_manifest_path.open.return_value.__enter__.return_value.read.return_value = (
                yaml.safe_dump(manifest_data)
            )
            mock_project_root.__truediv__.side_effect = [
                mock_manifest_path,  # First call: manifest_path
                mock_source_path,  # Second call: source_path
                MagicMock(),  # Third call: target_path
            ]

            # Setup yaml loading
            with patch("scripts.dev.markdown.run_all_converters.yaml.safe_load") as mock_yaml:
                mock_yaml.return_value = manifest_data

                # Setup converter mock
                mock_converter = MagicMock()
                mock_converter.run.return_value = mock_doc
                mock_conv.return_value = mock_converter

                from scripts.dev.markdown import run_all_converters

                run_all_converters.main()

                # Should have called converter
                mock_conv.assert_called_once()
                mock_converter.run.assert_called_once()

                captured = capsys.readouterr()
                # Should print summary
                assert "Total" in captured.out

    def test_main_skips_missing_source(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main() skips missing source files (covers branch [36,37])."""
        manifest_data = {
            "sources": [
                {"path": "docs/missing.md", "target_stub": "docs/missing.yml"},
            ]
        }

        # Mock source path that doesn't exist
        mock_source_path = MagicMock()
        mock_source_path.exists.return_value = False

        with (
            patch("scripts.dev.markdown.run_all_converters.Path") as mock_path,
            patch("scripts.dev.markdown.run_all_converters.MarkdownConverter") as mock_conv,
            patch("scripts.dev.markdown.run_all_converters.yaml.safe_load") as mock_yaml,
        ):
            mock_yaml.return_value = manifest_data

            # Setup Path mock
            mock_project_root = MagicMock()
            mock_path.return_value.parent.parent.parent = mock_project_root

            mock_manifest_path = MagicMock()
            mock_project_root.__truediv__.side_effect = [
                mock_manifest_path,  # First call: manifest_path
                mock_source_path,  # Second call: source_path
                MagicMock(),  # Third call: target_path
            ]

            from scripts.dev.markdown import run_all_converters

            run_all_converters.main()

            # Converter should NOT be called since file doesn't exist
            mock_conv.assert_not_called()

            captured = capsys.readouterr()
            # Should print SKIP warning
            assert "SKIP" in captured.out

    def test_main_handles_conversion_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main() handles conversion errors (covers branch [36,41])."""
        manifest_data = {
            "sources": [
                {"path": "docs/test.md", "target_stub": "docs/test.yml"},
            ]
        }

        # Mock source path that exists
        mock_source_path = MagicMock()
        mock_source_path.exists.return_value = True

        with (
            patch("scripts.dev.markdown.run_all_converters.Path") as mock_path,
            patch("scripts.dev.markdown.run_all_converters.MarkdownConverter") as mock_conv,
            patch("scripts.dev.markdown.run_all_converters.yaml.safe_load") as mock_yaml,
        ):
            mock_yaml.return_value = manifest_data

            # Setup Path mock
            mock_project_root = MagicMock()
            mock_path.return_value.parent.parent.parent = mock_project_root

            mock_manifest_path = MagicMock()
            mock_project_root.__truediv__.side_effect = [
                mock_manifest_path,  # First call: manifest_path
                mock_source_path,  # Second call: source_path
                MagicMock(),  # Third call: target_path
            ]

            # Setup converter to raise exception
            mock_converter = MagicMock()
            mock_converter.run.side_effect = Exception("Conversion failed")
            mock_conv.return_value = mock_converter

            from scripts.dev.markdown import run_all_converters

            run_all_converters.main()

            captured = capsys.readouterr()
            # Should print ERROR message
            assert "ERROR" in captured.out

    def test_main_prints_summary_for_empty_sources(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that main() prints summary even when sources list is empty."""
        manifest_data = {"sources": []}

        with (
            patch("scripts.dev.markdown.run_all_converters.Path") as mock_path,
            patch("scripts.dev.markdown.run_all_converters.yaml.safe_load") as mock_yaml,
        ):
            mock_yaml.return_value = manifest_data

            # Setup Path mock
            mock_project_root = MagicMock()
            mock_path.return_value.parent.parent.parent = mock_project_root
            mock_manifest_path = MagicMock()
            mock_project_root.__truediv__.return_value = mock_manifest_path

            from scripts.dev.markdown import run_all_converters

            run_all_converters.main()

            captured = capsys.readouterr()
            # Should print summary
            assert "Total: 0" in captured.out
            assert "Success: 0" in captured.out
            assert "Errors: 0" in captured.out
