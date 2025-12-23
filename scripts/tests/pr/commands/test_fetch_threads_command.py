"""Tests for fetch_threads_command module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.pr.commands.fetch_threads_command import fetch_threads_command


class TestFetchThreadsCommand:
    """Tests for the fetch_threads_command function."""

    def test_creates_output_directory_if_not_exists(self, tmp_path: Path) -> None:
        """Test that output directory is created if it doesn't exist."""
        output_dir = tmp_path / "new_dir"
        assert not output_dir.exists()

        with patch("scripts.pr.commands.fetch_threads_command.github_dao") as mock_gh:
            mock_gh.fetch_unresolved_threads.return_value = []
            result = fetch_threads_command(123, output_dir)

        assert output_dir.exists()
        assert result == 0

    def test_cleans_existing_thread_files(self, tmp_path: Path) -> None:
        """Test that existing thread files are cleaned before processing."""
        # Create existing thread files
        (tmp_path / "thread_0.json").write_text("{}")
        (tmp_path / "thread_1.json").write_text("{}")
        (tmp_path / "other_file.txt").write_text("keep me")

        with patch("scripts.pr.commands.fetch_threads_command.github_dao") as mock_gh:
            mock_gh.fetch_unresolved_threads.return_value = []
            result = fetch_threads_command(123, tmp_path)

        assert not (tmp_path / "thread_0.json").exists()
        assert not (tmp_path / "thread_1.json").exists()
        assert (tmp_path / "other_file.txt").exists()
        assert result == 0

    def test_fetches_unresolved_threads(self, tmp_path: Path) -> None:
        """Test that unresolved threads are fetched from GitHub."""
        with patch("scripts.pr.commands.fetch_threads_command.github_dao") as mock_gh:
            mock_gh.fetch_unresolved_threads.return_value = []
            result = fetch_threads_command(42, tmp_path)

        mock_gh.fetch_unresolved_threads.assert_called_once_with(42)
        assert result == 0

    def test_filters_threads_without_line_numbers(self, tmp_path: Path) -> None:
        """Test that threads without line numbers are filtered out."""
        threads = [
            {"id": "1", "line": 10, "path": "foo.py", "comments": {"nodes": []}},
            {"id": "2", "path": "bar.py", "comments": {"nodes": []}},  # No line
            {"id": "3", "startLine": 5, "path": "baz.py", "comments": {"nodes": []}},
        ]

        with (
            patch("scripts.pr.commands.fetch_threads_command.github_dao") as mock_gh,
            patch(
                "scripts.pr.commands.fetch_threads_command._thread_has_line_number"
            ) as mock_has_line,
            patch(
                "scripts.pr.commands.fetch_threads_command._has_thumbs_up_from_author"
            ) as mock_thumbs,
            patch(
                "scripts.pr.commands.fetch_threads_command._format_thread_for_agent"
            ) as mock_format,
        ):
            mock_gh.fetch_unresolved_threads.return_value = threads
            mock_has_line.side_effect = [True, False, True]  # Filter out second
            mock_thumbs.return_value = False  # No auto-resolve
            mock_format.side_effect = lambda t, i: {"index": i, "id": t["id"]}

            result = fetch_threads_command(123, tmp_path)

        assert result == 0
        # Two threads should be written (first and third)
        assert (tmp_path / "thread_0.json").exists()
        assert (tmp_path / "thread_1.json").exists()
        assert not (tmp_path / "thread_2.json").exists()

    def test_auto_resolves_threads_with_thumbs_up(self, tmp_path: Path) -> None:
        """Test that threads with thumbs-up reactions are auto-resolved."""
        threads = [
            {"id": "thread_1", "line": 10, "path": "foo.py", "comments": {"nodes": []}},
            {"id": "thread_2", "line": 20, "path": "bar.py", "comments": {"nodes": []}},
        ]

        with (
            patch("scripts.pr.commands.fetch_threads_command.github_dao") as mock_gh,
            patch(
                "scripts.pr.commands.fetch_threads_command._thread_has_line_number"
            ) as mock_has_line,
            patch(
                "scripts.pr.commands.fetch_threads_command._has_thumbs_up_from_author"
            ) as mock_thumbs,
            patch(
                "scripts.pr.commands.fetch_threads_command._format_thread_for_agent"
            ) as mock_format,
        ):
            mock_gh.fetch_unresolved_threads.return_value = threads
            mock_has_line.return_value = True
            mock_thumbs.side_effect = [True, False]  # First has thumbs up
            mock_gh.resolve_thread.return_value = True
            mock_format.side_effect = lambda t, i: {"index": i, "id": t["id"]}

            result = fetch_threads_command(123, tmp_path)

        # First thread should be resolved, second should be written
        mock_gh.resolve_thread.assert_called_once_with("thread_1")
        assert not (tmp_path / "thread_1.json").exists()  # First was resolved, not written
        assert (tmp_path / "thread_0.json").exists()  # Second was written as thread_0
        assert result == 0

    def test_handles_failed_thread_resolution(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that failed thread resolutions are reported but don't stop processing."""
        threads = [
            {"id": "thread_1", "line": 10, "path": "foo.py", "comments": {"nodes": []}},
        ]

        with (
            patch("scripts.pr.commands.fetch_threads_command.github_dao") as mock_gh,
            patch(
                "scripts.pr.commands.fetch_threads_command._thread_has_line_number"
            ) as mock_has_line,
            patch(
                "scripts.pr.commands.fetch_threads_command._has_thumbs_up_from_author"
            ) as mock_thumbs,
        ):
            mock_gh.fetch_unresolved_threads.return_value = threads
            mock_has_line.return_value = True
            mock_thumbs.return_value = True
            mock_gh.resolve_thread.return_value = False  # Resolution fails

            result = fetch_threads_command(123, tmp_path)

        captured = capsys.readouterr()
        assert "failed: foo.py:10" in captured.out
        assert result == 0

    def test_writes_formatted_threads_to_files(self, tmp_path: Path) -> None:
        """Test that formatted threads are written to JSON files."""
        threads = [
            {"id": "t1", "line": 10, "path": "foo.py", "comments": {"nodes": []}},
        ]
        formatted = {
            "index": 0,
            "thread_id": "t1",
            "path": "foo.py",
            "line": 10,
        }

        with (
            patch("scripts.pr.commands.fetch_threads_command.github_dao") as mock_gh,
            patch(
                "scripts.pr.commands.fetch_threads_command._thread_has_line_number"
            ) as mock_has_line,
            patch(
                "scripts.pr.commands.fetch_threads_command._has_thumbs_up_from_author"
            ) as mock_thumbs,
            patch(
                "scripts.pr.commands.fetch_threads_command._format_thread_for_agent"
            ) as mock_format,
        ):
            mock_gh.fetch_unresolved_threads.return_value = threads
            mock_has_line.return_value = True
            mock_thumbs.return_value = False
            mock_format.return_value = formatted

            result = fetch_threads_command(123, tmp_path)

        thread_file = tmp_path / "thread_0.json"
        assert thread_file.exists()
        content = json.loads(thread_file.read_text())
        assert content == formatted
        assert result == 0

    def test_prints_summary(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Test that a summary is printed at the end."""
        threads = [
            {"id": "t1", "line": 10, "path": "foo.py", "comments": {"nodes": []}},
            {"id": "t2", "line": 20, "path": "bar.py", "comments": {"nodes": []}},
            {"id": "t3", "path": "no_line.py", "comments": {"nodes": []}},  # No line
        ]

        with (
            patch("scripts.pr.commands.fetch_threads_command.github_dao") as mock_gh,
            patch(
                "scripts.pr.commands.fetch_threads_command._thread_has_line_number"
            ) as mock_has_line,
            patch(
                "scripts.pr.commands.fetch_threads_command._has_thumbs_up_from_author"
            ) as mock_thumbs,
            patch(
                "scripts.pr.commands.fetch_threads_command._format_thread_for_agent"
            ) as mock_format,
        ):
            mock_gh.fetch_unresolved_threads.return_value = threads
            mock_has_line.side_effect = [True, True, False]  # Third has no line
            mock_thumbs.side_effect = [True, False]  # First has thumbs up
            mock_gh.resolve_thread.return_value = True
            mock_format.side_effect = lambda t, i: {"index": i}

            result = fetch_threads_command(123, tmp_path)

        captured = capsys.readouterr()
        assert "Total unresolved threads: 3" in captured.out
        assert "Threads with line numbers: 2" in captured.out
        assert "Auto-resolved (thumbs-up): 1" in captured.out
        assert "Files created for review: 1" in captured.out
        assert result == 0

    def test_handles_thread_without_id_for_resolution(self, tmp_path: Path) -> None:
        """Test that threads without an id don't crash during resolution attempt."""
        threads = [
            {"line": 10, "path": "foo.py", "comments": {"nodes": []}},  # No id
        ]

        with (
            patch("scripts.pr.commands.fetch_threads_command.github_dao") as mock_gh,
            patch(
                "scripts.pr.commands.fetch_threads_command._thread_has_line_number"
            ) as mock_has_line,
            patch(
                "scripts.pr.commands.fetch_threads_command._has_thumbs_up_from_author"
            ) as mock_thumbs,
        ):
            mock_gh.fetch_unresolved_threads.return_value = threads
            mock_has_line.return_value = True
            mock_thumbs.return_value = True

            result = fetch_threads_command(123, tmp_path)

        # Should not call resolve_thread for thread without id
        mock_gh.resolve_thread.assert_not_called()
        assert result == 0

    def test_returns_zero_on_success(self, tmp_path: Path) -> None:
        """Test that the command returns 0 on success."""
        with patch("scripts.pr.commands.fetch_threads_command.github_dao") as mock_gh:
            mock_gh.fetch_unresolved_threads.return_value = []
            result = fetch_threads_command(123, tmp_path)

        assert result == 0
