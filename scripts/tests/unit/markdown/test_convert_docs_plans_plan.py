from unittest.mock import MagicMock, patch

import pytest


class TestMain:
    def test_main_with_mocked_converter(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test main() with mocked MarkdownConverter."""
        # Create a mock document
        mock_doc = MagicMock()
        mock_doc.title = "Test Plan"
        mock_doc.sections = [MagicMock(), MagicMock()]  # 2 sections

        # Create mock converter
        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_plans_plan.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_plans_plan import main

            main()

            # Verify converter was created and run was called
            MockConverter.assert_called_once()
            mock_converter.run.assert_called_once()

            # Check print output
            captured = capsys.readouterr()
            assert "Converted:" in captured.out
            assert "Output:" in captured.out
            assert "Title: Test Plan" in captured.out
            assert "Sections: 2" in captured.out

    def test_main_creates_correct_paths(self) -> None:
        """Test that main() creates correct source and target paths."""
        mock_doc = MagicMock()
        mock_doc.title = "Test"
        mock_doc.sections = []

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_plans_plan.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_plans_plan import main

            main()

            # Check that converter was called with correct path patterns
            call_args = MockConverter.call_args[0]
            source_path = call_args[0]
            target_path = call_args[1]

            assert "docs" in source_path
            assert "plans" in source_path
            assert "plan.md" in source_path
            assert "plan.yml" in target_path

    def test_main_prints_all_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that main() prints all conversion info."""
        mock_doc = MagicMock()
        mock_doc.title = "Plan Title"
        mock_doc.sections = [MagicMock() for _ in range(3)]

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_plans_plan.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_plans_plan import main

            main()

            captured = capsys.readouterr()
            # Verify all print statements are executed
            assert "Converted:" in captured.out
            assert "Output:" in captured.out
            assert "Title: Plan Title" in captured.out
            assert "Sections: 3" in captured.out

    def test_main_path_resolution(self) -> None:
        """Test that main() resolves paths relative to project root."""
        mock_doc = MagicMock()
        mock_doc.title = "Test"
        mock_doc.sections = []

        mock_converter = MagicMock()
        mock_converter.run.return_value = mock_doc

        with patch(
            "scripts.dev.markdown.convert_docs_plans_plan.MarkdownConverter"
        ) as MockConverter:
            MockConverter.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_plans_plan import main

            main()

            # The paths should include the relative doc paths
            call_args = MockConverter.call_args[0]
            source_path = call_args[0]
            target_path = call_args[1]

            # Source should be docs/plans/plan.md
            assert source_path.endswith("plan.md")
            assert "plans" in source_path

            # Target should be docs/plans/plan.yml
            assert target_path.endswith("plan.yml")
            assert "plans" in target_path
