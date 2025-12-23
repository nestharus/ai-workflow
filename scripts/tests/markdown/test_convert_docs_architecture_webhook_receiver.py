"""Tests for scripts.dev.markdown.convert_docs_architecture_webhook_receiver module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.dev.markdown.converter_base import Document


class TestMain:
    """Tests for the main() function."""

    def test_main_calls_converter_with_correct_paths(self) -> None:
        """Test that main() creates converter with correct source and target paths."""
        mock_doc = Document(
            doc_id="test-doc",
            title="Webhook Receiver",
            description="Test description",
            domain=[],
            scope="project",
            sections=[],
        )

        with patch(
            "scripts.dev.markdown.convert_docs_architecture_webhook_receiver.MarkdownConverter"
        ) as mock_converter_class:
            mock_converter = MagicMock()
            mock_converter.run.return_value = mock_doc
            mock_converter_class.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_architecture_webhook_receiver import (
                main,
            )

            main()

            # Verify MarkdownConverter was called
            mock_converter_class.assert_called_once()
            call_args = mock_converter_class.call_args[0]

            # Check that paths contain expected components
            assert "webhook-receiver.md" in call_args[0]
            assert "webhook-receiver.yml" in call_args[1]

            # Verify run() was called
            mock_converter.run.assert_called_once()

    def test_main_prints_output(self, capsys: object) -> None:
        """Test that main() prints conversion details."""
        mock_doc = Document(
            doc_id="test-doc",
            title="Test Title",
            description="Test description",
            domain=[],
            scope="project",
            sections=[MagicMock(), MagicMock()],  # 2 sections
        )

        with patch(
            "scripts.dev.markdown.convert_docs_architecture_webhook_receiver.MarkdownConverter"
        ) as mock_converter_class:
            mock_converter = MagicMock()
            mock_converter.run.return_value = mock_doc
            mock_converter_class.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_architecture_webhook_receiver import (
                main,
            )

            main()

            captured = capsys.readouterr()  # type: ignore[attr-defined]
            assert "Converted:" in captured.out
            assert "Output:" in captured.out
            assert "Title: Test Title" in captured.out
            assert "Sections: 2" in captured.out

    def test_main_uses_project_root_paths(self) -> None:
        """Test that main() constructs paths relative to project root."""
        mock_doc = Document(
            doc_id="test-doc",
            title="Test",
            description="",
            domain=[],
            scope="project",
            sections=[],
        )

        with patch(
            "scripts.dev.markdown.convert_docs_architecture_webhook_receiver.MarkdownConverter"
        ) as mock_converter_class:
            mock_converter = MagicMock()
            mock_converter.run.return_value = mock_doc
            mock_converter_class.return_value = mock_converter

            from scripts.dev.markdown.convert_docs_architecture_webhook_receiver import (
                main,
            )

            main()

            call_args = mock_converter_class.call_args[0]
            source_path = call_args[0]
            target_path = call_args[1]

            # Paths should contain docs/architecture
            assert "docs" in source_path
            assert "architecture" in source_path
            assert "docs" in target_path
            assert "architecture" in target_path
