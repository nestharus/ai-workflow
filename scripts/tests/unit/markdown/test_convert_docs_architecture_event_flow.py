"""Tests for scripts.dev.markdown.convert_docs_architecture_event_flow module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestMain:
    """Tests for the main function."""

    @patch("scripts.dev.markdown.convert_docs_architecture_event_flow.MarkdownConverter")
    @patch("scripts.dev.markdown.convert_docs_architecture_event_flow.Path")
    def test_main_runs_conversion(
        self,
        mock_path_class: MagicMock,
        mock_converter_class: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main runs the markdown to YAML conversion (lines 12-25)."""
        from scripts.dev.markdown.convert_docs_architecture_event_flow import main

        # Set up mock path resolution
        mock_project_root = MagicMock()
        mock_file_path = MagicMock()
        mock_file_path.parent.parent.parent = mock_project_root
        mock_path_class.__file__ = mock_file_path

        mock_source = MagicMock()
        mock_target = MagicMock()
        mock_project_root.__truediv__ = lambda self, x: (
            mock_source if "event-flow.md" in x else mock_target
        )

        # Set up mock converter
        mock_doc = MagicMock()
        mock_doc.title = "Event Flow"
        mock_doc.sections = [MagicMock(), MagicMock()]

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc
        mock_converter_class.return_value = mock_converter

        main()

        mock_converter.run.assert_called_once()
        captured = capsys.readouterr()
        assert "Converted:" in captured.out
        assert "Output:" in captured.out
        assert "Title:" in captured.out
        assert "Sections:" in captured.out

    @patch("scripts.dev.markdown.convert_docs_architecture_event_flow.MarkdownConverter")
    def test_main_uses_correct_paths(
        self,
        mock_converter_class: MagicMock,
    ) -> None:
        """Test main uses correct source and target paths (lines 15-17)."""
        from scripts.dev.markdown.convert_docs_architecture_event_flow import main

        mock_doc = MagicMock()
        mock_doc.title = "Test"
        mock_doc.sections = []
        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc
        mock_converter_class.return_value = mock_converter

        main()

        # Verify constructor was called with string paths
        call_args = mock_converter_class.call_args
        source_arg = call_args[0][0]
        target_arg = call_args[0][1]
        assert "event-flow.md" in source_arg
        assert "event-flow.yml" in target_arg

    @patch("scripts.dev.markdown.convert_docs_architecture_event_flow.MarkdownConverter")
    def test_main_prints_conversion_info(
        self,
        mock_converter_class: MagicMock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main prints conversion info (lines 22-25)."""
        from scripts.dev.markdown.convert_docs_architecture_event_flow import main

        mock_doc = MagicMock()
        mock_doc.title = "My Title"
        mock_doc.sections = [MagicMock(), MagicMock(), MagicMock()]
        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc
        mock_converter_class.return_value = mock_converter

        main()

        captured = capsys.readouterr()
        assert "Title: My Title" in captured.out
        assert "Sections: 3" in captured.out
