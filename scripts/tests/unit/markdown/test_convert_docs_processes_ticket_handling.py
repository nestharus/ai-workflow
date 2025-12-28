from unittest.mock import MagicMock, patch

import pytest


class TestMain:
    def test_main_with_mocked_converter(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main() with mocked MarkdownConverter."""
        mock_doc = MagicMock()
        mock_doc.title = "Ticket Handling"
        mock_doc.sections = [MagicMock(), MagicMock()]

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_processes_ticket_handling.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_processes_ticket_handling import main

            main()

            MockConverter.assert_called_once()
            mock_converter.run.assert_called_once()

            captured = capsys.readouterr()
            assert "Converted:" in captured.out
            assert "Output:" in captured.out
            assert "Title: Ticket Handling" in captured.out
            assert "Sections: 2" in captured.out

    def test_main_creates_correct_paths(self) -> None:
        """Test that main() creates correct source and target paths."""
        mock_doc = MagicMock()
        mock_doc.title = "Test"
        mock_doc.sections = []

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_processes_ticket_handling.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_processes_ticket_handling import main

            main()

            call_args = MockConverter.call_args[0]
            source_path = call_args[0]
            target_path = call_args[1]

            assert "docs" in source_path
            assert "processes" in source_path
            assert "ticket-handling.md" in source_path
            assert "ticket-handling.yml" in target_path

    def test_main_prints_all_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main() prints all conversion info."""
        mock_doc = MagicMock()
        mock_doc.title = "Ticket Handling Process"
        mock_doc.sections = [MagicMock() for _ in range(5)]

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_processes_ticket_handling.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_processes_ticket_handling import main

            main()

            captured = capsys.readouterr()
            assert "Converted:" in captured.out
            assert "Output:" in captured.out
            assert "Title: Ticket Handling Process" in captured.out
            assert "Sections: 5" in captured.out

    def test_main_path_resolution(self) -> None:
        """Test that main() resolves paths relative to project root."""
        mock_doc = MagicMock()
        mock_doc.title = "Test"
        mock_doc.sections = []

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_processes_ticket_handling.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_processes_ticket_handling import main

            main()

            call_args = MockConverter.call_args[0]
            source_path = call_args[0]
            target_path = call_args[1]

            assert source_path.endswith("ticket-handling.md")
            assert "processes" in source_path
            assert target_path.endswith("ticket-handling.yml")
            assert "processes" in target_path
