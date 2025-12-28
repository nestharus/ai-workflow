from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.claude_agent_runner import (
    ClaudeRunner,
    build_command,
    load_agent,
    run_command,
)


class TestRunCommand:
    def test_successful_command(self) -> None:
        """Should return exit code 0 and captured output on success."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Output text"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            exit_code, output = run_command(["echo", "test"], stream_output=False)

        assert exit_code == 0
        assert output == "Output text"

    def test_failed_command_with_stderr(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return error code and write stderr on failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error message"

        with patch("subprocess.run", return_value=mock_result):
            exit_code, _output = run_command(["false"], stream_output=False)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error message" in captured.err

    def test_stream_output_true(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should write stdout when stream_output is True."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Streamed output"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            exit_code, _output = run_command(["echo", "test"], stream_output=True)

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Streamed output" in captured.out

    def test_stdin_input_passed(self) -> None:
        """Should pass stdin_input to subprocess."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "result"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            run_command(["cat"], stdin_input="hello world")

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["input"] == "hello world"

    def test_failed_command_without_stderr(self) -> None:
        """Should handle failure with empty stderr (branch coverage)."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "some output"
        mock_result.stderr = ""  # Empty stderr

        with patch("subprocess.run", return_value=mock_result):
            exit_code, output = run_command(["false"], stream_output=False)

        assert exit_code == 1
        assert output == "some output"


class TestClaudeRunner:
    def test_run_success(self) -> None:
        """Should execute command and return output on success."""
        agent_config = {
            "model": "opus",
            "provider": "claude",
            "_system_prompt": "Test system prompt",
            "tools": "Read",
        }

        runner = ClaudeRunner(agent_config)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Claude output"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = runner.run("Test prompt")

        assert result == "Claude output"

    def test_run_failure_raises_runtime_error(self) -> None:
        """Should raise RuntimeError on non-zero exit code."""
        agent_config = {
            "model": "opus",
            "provider": "claude",
            "_system_prompt": "Test system prompt",
            "tools": "Read",
        }

        runner = ClaudeRunner(agent_config)

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error"

        with (
            patch("subprocess.run", return_value=mock_result),
            pytest.raises(RuntimeError, match="exit code 1"),
        ):
            runner.run("Test prompt")

    def test_run_passes_prompt_via_stdin(self) -> None:
        """Should pass user prompt via stdin to command."""
        agent_config = {
            "model": "opus",
            "provider": "claude",
            "_system_prompt": "Test system prompt",
            "tools": "Read",
        }

        runner = ClaudeRunner(agent_config)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            runner.run("My user prompt")

        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["input"] == "My user prompt"
