"""Tests for scripts.dev.opencode_agent_runner module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.opencode_agent_runner import (
    main,
    parse_args,
    run_agent,
)


class TestParseArgs:
    """Tests for parse_args function."""

    def test_parses_required_arguments(self) -> None:
        """Should parse --agent and --prompt arguments."""
        with patch("sys.argv", ["prog", "--agent", "test-agent", "--prompt", "test prompt"]):
            args = parse_args()

        assert args.agent == "test-agent"
        assert args.prompt == "test prompt"

    def test_raises_on_missing_agent(self) -> None:
        """Should raise SystemExit when --agent is missing."""
        with (
            patch("sys.argv", ["prog", "--prompt", "test prompt"]),
            pytest.raises(SystemExit),
        ):
            parse_args()

    def test_raises_on_missing_prompt(self) -> None:
        """Should raise SystemExit when --prompt is missing."""
        with (
            patch("sys.argv", ["prog", "--agent", "test-agent"]),
            pytest.raises(SystemExit),
        ):
            parse_args()


class TestRunAgent:
    """Tests for run_agent function."""

    def test_returns_zero_on_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 0 and print stdout on success."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Success output"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            exit_code, _output = run_agent("test-agent", "test prompt")

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Success output" in captured.out

    def test_returns_error_code_on_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return error code and print stderr on failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error message"

        with patch("subprocess.run", return_value=mock_result):
            exit_code, _output = run_agent("test-agent", "test prompt")

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error message" in captured.err

    def test_builds_correct_command(self) -> None:
        """Should build command with correct arguments."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            run_agent("my-agent", "my prompt")

        call_args = mock_run.call_args
        command = call_args[0][0]

        # Check command structure
        assert "opencode" in command[0]
        assert "run" in command
        assert "--agent" in command
        assert "my-agent" in command
        assert "my prompt" in command

    def test_handles_no_output(self) -> None:
        """Should handle case with no stdout or stderr."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            exit_code, _output = run_agent("test-agent", "test prompt")

        assert exit_code == 0

    def test_does_not_print_stderr_on_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should not print stderr when returncode is 0."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output"
        mock_result.stderr = "some stderr"

        with patch("subprocess.run", return_value=mock_result):
            exit_code, _output = run_agent("test-agent", "test prompt")

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "some stderr" not in captured.err


class TestMain:
    """Tests for main function."""

    def test_returns_zero_on_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 0 on successful execution."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output"
        mock_result.stderr = ""

        with (
            patch("sys.argv", ["prog", "--agent", "test", "--prompt", "hello"]),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "output" in captured.out

    def test_returns_agent_returncode(self) -> None:
        """Should return the returncode from run_agent."""
        mock_result = MagicMock()
        mock_result.returncode = 42
        mock_result.stdout = ""
        mock_result.stderr = "error"

        with (
            patch("sys.argv", ["prog", "--agent", "test", "--prompt", "hello"]),
            patch("subprocess.run", return_value=mock_result),
        ):
            result = main()

        assert result == 42

    def test_calls_run_agent_with_parsed_args(self) -> None:
        """Should call run_agent with parsed arguments."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with (
            patch("sys.argv", ["prog", "--agent", "my-agent", "--prompt", "my prompt"]),
            patch("subprocess.run", return_value=mock_result) as mock_run,
        ):
            main()

        call_args = mock_run.call_args
        command = call_args[0][0]
        assert "my-agent" in command
        assert "my prompt" in command
