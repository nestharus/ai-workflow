from unittest.mock import MagicMock, patch

import pytest


class TestMain:
    def test_main_with_mocked_converter(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main() with mocked MarkdownConverter."""
        mock_doc = MagicMock()
        mock_doc.title = "API Testing Patterns"
        mock_doc.sections = [MagicMock(), MagicMock()]

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_testing_api_testing_patterns.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_testing_api_testing_patterns import main

            main()

            MockConverter.assert_called_once()
            mock_converter.run.assert_called_once()

            captured = capsys.readouterr()
            assert "Converted:" in captured.out
            assert "Output:" in captured.out
            assert "Title: API Testing Patterns" in captured.out
            assert "Sections: 2" in captured.out

    def test_main_creates_correct_paths(self) -> None:
        """Test that main() creates correct source and target paths."""
        mock_doc = MagicMock()
        mock_doc.title = "Test"
        mock_doc.sections = []

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_testing_api_testing_patterns.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_testing_api_testing_patterns import main

            main()

            call_args = MockConverter.call_args[0]
            source_path = call_args[0]
            target_path = call_args[1]

            assert "docs" in source_path
            assert "testing" in source_path
            assert "api-testing-patterns.md" in source_path
            assert "api-testing-patterns.yml" in target_path

    def test_main_prints_all_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main() prints all conversion info."""
        mock_doc = MagicMock()
        mock_doc.title = "API Testing Patterns Doc"
        mock_doc.sections = [MagicMock() for _ in range(7)]

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_testing_api_testing_patterns.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_testing_api_testing_patterns import main

            main()

            captured = capsys.readouterr()
            assert "Converted:" in captured.out
            assert "Output:" in captured.out
            assert "Title: API Testing Patterns Doc" in captured.out
            assert "Sections: 7" in captured.out

    def test_main_path_resolution(self) -> None:
        """Test that main() resolves paths relative to project root."""
        mock_doc = MagicMock()
        mock_doc.title = "Test"
        mock_doc.sections = []

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_testing_api_testing_patterns.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_testing_api_testing_patterns import main

            main()

            call_args = MockConverter.call_args[0]
            source_path = call_args[0]
            target_path = call_args[1]

            assert source_path.endswith("api-testing-patterns.md")
            assert "testing" in source_path
            assert target_path.endswith("api-testing-patterns.yml")
            assert "testing" in target_path
