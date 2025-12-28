"""Tests for get_changed_files_command module."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from scripts.pr.commands.get_changed_files_command import get_changed_files_command


class TestGetChangedFilesCommand:
    """Tests for the get_changed_files_command function."""

    def test_success_returns_zero_and_prints_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test successful retrieval prints JSON and returns 0."""
        files = ["file1.py", "file2.py", "dir/file3.py"]

        with patch("scripts.pr.commands.get_changed_files_command.github_dao") as mock_gh:
            mock_gh.get_pr_changed_files.return_value = files
            result = get_changed_files_command(42)

        mock_gh.get_pr_changed_files.assert_called_once_with(42)
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output == files
        assert result == 0

    def test_graphql_error_returns_one_and_prints_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that GraphQL errors return 1 and print error to stderr."""
        with patch("scripts.pr.commands.get_changed_files_command.github_dao") as mock_gh:
            mock_gh.GraphQLError = Exception  # Set up the exception class
            mock_gh.get_pr_changed_files.side_effect = Exception("API failure")
            result = get_changed_files_command(123)

        captured = capsys.readouterr()
        assert "Error: API failure" in captured.err
        assert result == 1

    def test_empty_file_list(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test handling of PR with no changed files."""
        with patch("scripts.pr.commands.get_changed_files_command.github_dao") as mock_gh:
            mock_gh.get_pr_changed_files.return_value = []
            result = get_changed_files_command(99)

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output == []
        assert result == 0

    def test_uses_correct_pr_number(self) -> None:
        """Test that the correct PR number is passed to the DAO."""
        with patch("scripts.pr.commands.get_changed_files_command.github_dao") as mock_gh:
            mock_gh.get_pr_changed_files.return_value = []
            get_changed_files_command(999)

        mock_gh.get_pr_changed_files.assert_called_once_with(999)
