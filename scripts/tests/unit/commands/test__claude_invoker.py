"""Tests for scripts.dev.commands._claude_invoker module."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from scripts.dev.commands._claude_invoker import (
    HAIKU_MODEL,
    OPUS_MODEL,
    invoke_claude,
    invoke_haiku,
    invoke_planner,
    parse_comments_with_haiku,
)


class TestInvokeClaude:
    """Tests for invoke_claude function."""

    def test_basic_invocation(self) -> None:
        """Should invoke Claude CLI with basic arguments."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Claude response"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            exit_code, stdout, stderr = invoke_claude(prompt="Test prompt")

        assert exit_code == 0
        assert stdout == "Claude response"
        assert stderr == ""

        call_args = mock_run.call_args[0][0]
        assert "claude" in call_args
        assert "-p" in call_args
        assert "--model" in call_args
        assert OPUS_MODEL in call_args  # Default model

    def test_with_system_prompt(self) -> None:
        """Should include system prompt when provided."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Response"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            invoke_claude(prompt="Test", system_prompt="You are helpful")

        call_args = mock_run.call_args[0][0]
        assert "--system-prompt" in call_args
        idx = call_args.index("--system-prompt")
        assert call_args[idx + 1] == "You are helpful"

    def test_without_system_prompt(self) -> None:
        """Should not include system prompt flag when not provided."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Response"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            invoke_claude(prompt="Test", system_prompt=None)

        call_args = mock_run.call_args[0][0]
        assert "--system-prompt" not in call_args

    def test_with_allowed_tools(self) -> None:
        """Should include allowed tools when provided."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Response"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            invoke_claude(prompt="Test", allowed_tools=["Read", "Write"])

        call_args = mock_run.call_args[0][0]
        assert "--allowedTools" in call_args
        idx = call_args.index("--allowedTools")
        assert call_args[idx + 1] == "Read,Write"

    def test_without_allowed_tools(self) -> None:
        """Should not include allowed tools flag when not provided."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Response"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            invoke_claude(prompt="Test", allowed_tools=None)

        call_args = mock_run.call_args[0][0]
        assert "--allowedTools" not in call_args

    def test_timeout_expired(self) -> None:
        """Should return error when command times out."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=300)
            exit_code, stdout, stderr = invoke_claude(prompt="Test", timeout=300)

        assert exit_code == 1
        assert stdout == ""
        assert "timed out" in stderr

    def test_custom_model(self) -> None:
        """Should use custom model when provided."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Response"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            invoke_claude(prompt="Test", model=HAIKU_MODEL)

        call_args = mock_run.call_args[0][0]
        idx = call_args.index("--model")
        assert call_args[idx + 1] == HAIKU_MODEL


class TestInvokeHaiku:
    """Tests for invoke_haiku function."""

    def test_calls_invoke_claude_with_haiku(self) -> None:
        """Should call invoke_claude with haiku model."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Haiku response"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            exit_code, stdout, _stderr = invoke_haiku("Test prompt")

        assert exit_code == 0
        assert stdout == "Haiku response"

        call_args = mock_run.call_args[0][0]
        idx = call_args.index("--model")
        assert call_args[idx + 1] == HAIKU_MODEL

    def test_passes_system_prompt(self) -> None:
        """Should pass system prompt to invoke_claude."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Response"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            invoke_haiku("Test", system_prompt="Be brief")

        call_args = mock_run.call_args[0][0]
        assert "--system-prompt" in call_args
        idx = call_args.index("--system-prompt")
        assert call_args[idx + 1] == "Be brief"


class TestInvokePlanner:
    """Tests for invoke_planner function."""

    def test_loads_planner_agent_and_builds_command(self) -> None:
        """Should load planner agent and build proper command."""
        # Mock load_agent and build_command from claude_agent_runner
        mock_frontmatter = {"tools": "Read, Write", "model": "opus"}
        mock_system_prompt = "You are a planner agent."

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Planner output"
        mock_result.stderr = ""

        with (
            patch(
                "scripts.dev.claude_agent_runner.load_agent",
                return_value=(mock_frontmatter, mock_system_prompt),
            ),
            patch(
                "scripts.dev.claude_agent_runner.build_command",
                return_value=["claude", "-p", "--model", "opus"],
            ),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            exit_code, stdout, _stderr = invoke_planner("Plan this task")

        assert exit_code == 0
        assert stdout == "Planner output"

        # Verify dangerous permissions flag is added
        call_args = mock_run.call_args[0][0]
        assert "--dangerously-skip-permissions" in call_args

    def test_timeout_expired(self) -> None:
        """Should return error when planner times out."""
        mock_frontmatter = {"tools": "Read", "model": "opus"}
        mock_system_prompt = "System prompt"

        with (
            patch(
                "scripts.dev.claude_agent_runner.load_agent",
                return_value=(mock_frontmatter, mock_system_prompt),
            ),
            patch(
                "scripts.dev.claude_agent_runner.build_command",
                return_value=["claude", "-p", "--model", "opus"],
            ),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=300)
            exit_code, stdout, stderr = invoke_planner("Test")

        assert exit_code == 1
        assert stdout == ""
        assert "timed out" in stderr.lower()

    def test_dangerous_permissions_not_duplicated(self) -> None:
        """Should not add duplicate dangerous permissions flag."""
        mock_frontmatter = {"tools": "Read", "model": "opus"}
        mock_system_prompt = "System prompt"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output"
        mock_result.stderr = ""

        with (
            patch(
                "scripts.dev.claude_agent_runner.load_agent",
                return_value=(mock_frontmatter, mock_system_prompt),
            ),
            patch(
                "scripts.dev.claude_agent_runner.build_command",
                return_value=["claude", "-p", "--model", "opus"],
            ),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            invoke_planner("Test")

        call_args = mock_run.call_args[0][0]
        # Count occurrences of the flag
        count = call_args.count("--dangerously-skip-permissions")
        assert count == 1

    def test_dangerous_permissions_already_present(self) -> None:
        """Should not add flag if already in command."""
        mock_frontmatter = {"tools": "Read", "model": "opus"}
        mock_system_prompt = "System prompt"

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output"
        mock_result.stderr = ""

        # Simulate build_command returning a command that already has the flag
        with (
            patch(
                "scripts.dev.claude_agent_runner.load_agent",
                return_value=(mock_frontmatter, mock_system_prompt),
            ),
            patch(
                "scripts.dev.claude_agent_runner.build_command",
                return_value=["claude", "--dangerously-skip-permissions", "-p", "--model", "opus"],
            ),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            invoke_planner("Test")

        call_args = mock_run.call_args[0][0]
        # Count occurrences of the flag - should still be 1
        count = call_args.count("--dangerously-skip-permissions")
        assert count == 1


class TestParseCommentsWithHaiku:
    """Tests for parse_comments_with_haiku function."""

    def test_successful_parse(self) -> None:
        """Should parse comments when haiku returns valid response."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Comment 1\n---\nComment 2\n---\nComment 3"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            comments = parse_comments_with_haiku('{"comments": []}')

        assert comments == ["Comment 1", "Comment 2", "Comment 3"]

    def test_fallback_on_haiku_failure(self) -> None:
        """Should use fallback parser when haiku fails."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error"

        comments_json = '{"comments": [{"body": "First comment"}, {"body": "Second comment"}]}'

        with patch("subprocess.run", return_value=mock_result):
            comments = parse_comments_with_haiku(comments_json)

        assert comments == ["First comment", "Second comment"]

    def test_fallback_on_empty_response(self) -> None:
        """Should use fallback parser when haiku returns empty response."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""  # Empty stdout
        mock_result.stderr = ""

        comments_json = '{"comments": [{"body": "Fallback comment"}]}'

        with patch("subprocess.run", return_value=mock_result):
            comments = parse_comments_with_haiku(comments_json)

        assert comments == ["Fallback comment"]

    def test_single_comment_no_separator(self) -> None:
        """Should handle single comment without separator."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Just one comment"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            comments = parse_comments_with_haiku('{"comments": []}')

        assert comments == ["Just one comment"]

    def test_filters_empty_comments(self) -> None:
        """Should filter out empty comment entries."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Comment 1\n---\n\n---\nComment 2"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            comments = parse_comments_with_haiku('{"comments": []}')

        assert comments == ["Comment 1", "Comment 2"]
