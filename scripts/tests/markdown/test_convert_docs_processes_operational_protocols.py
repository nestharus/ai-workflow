"""Tests for scripts.dev.markdown.convert_docs_processes_operational_protocols module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestMain:
    """Tests for the main function."""

    def test_main_with_mocked_converter(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main() with mocked MarkdownConverter."""
        mock_doc = MagicMock()
        mock_doc.title = "Operational Protocols"
        mock_doc.sections = [MagicMock(), MagicMock()]

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_processes_operational_protocols.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_processes_operational_protocols import main

            main()

            MockConverter.assert_called_once()
            mock_converter.run.assert_called_once()

            captured = capsys.readouterr()
            assert "Converted:" in captured.out
            assert "Output:" in captured.out
            assert "Title: Operational Protocols" in captured.out
            assert "Sections: 2" in captured.out

    def test_main_creates_correct_paths(self) -> None:
        """Test that main() creates correct source and target paths."""
        mock_doc = MagicMock()
        mock_doc.title = "Test"
        mock_doc.sections = []

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_processes_operational_protocols.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_processes_operational_protocols import main

            main()

            call_args = MockConverter.call_args[0]
            source_path = call_args[0]
            target_path = call_args[1]

            assert "docs" in source_path
            assert "processes" in source_path
            assert "operational-protocols.md" in source_path
            assert "operational-protocols.yml" in target_path

    def test_main_function_is_callable(self) -> None:
        """Test that main function can be imported and is callable."""
        from scripts.dev.markdown.convert_docs_processes_operational_protocols import main

        assert callable(main)

    def test_main_prints_all_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main() prints all conversion info."""
        mock_doc = MagicMock()
        mock_doc.title = "Operational Protocols Doc"
        mock_doc.sections = [MagicMock() for _ in range(6)]

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_processes_operational_protocols.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_processes_operational_protocols import main

            main()

            captured = capsys.readouterr()
            assert "Converted:" in captured.out
            assert "Output:" in captured.out
            assert "Title: Operational Protocols Doc" in captured.out
            assert "Sections: 6" in captured.out

    def test_main_path_resolution(self) -> None:
        """Test that main() resolves paths relative to project root."""
        mock_doc = MagicMock()
        mock_doc.title = "Test"
        mock_doc.sections = []

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_processes_operational_protocols.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_processes_operational_protocols import main

            main()

            call_args = MockConverter.call_args[0]
            source_path = call_args[0]
            target_path = call_args[1]

            assert source_path.endswith("operational-protocols.md")
            assert "processes" in source_path
            assert target_path.endswith("operational-protocols.yml")
            assert "processes" in target_path
