"""Tests for scripts.dev.claude_agent_runner module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.claude_agent_runner import (
    ClaudeRunner,
    build_command,
    load_agent,
    run_command,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestBuildCommand:
    """Tests for build_command function."""

    def test_basic_command_structure(self) -> None:
        """Should build basic command with model and system prompt."""
        frontmatter = {"model": "opus", "tools": "Read,Write"}
        command = build_command(frontmatter, "Test prompt")

        assert command[0] == "claude"
        assert "-p" in command
        assert "--model" in command
        assert "opus" in command
        assert "--system-prompt" in command
        assert "Test prompt" in command

    def test_tools_as_string(self) -> None:
        """Should parse comma-separated tools string."""
        frontmatter = {"model": "opus", "tools": "Read, Write, Edit"}
        command = build_command(frontmatter, "Test prompt")

        assert "--allowedTools" in command
        idx = command.index("--allowedTools")
        assert "Read" in command[idx + 1]
        assert "Write" in command[idx + 1]
        assert "Edit" in command[idx + 1]

    def test_tools_as_list(self) -> None:
        """Should parse list of tools."""
        frontmatter = {"model": "opus", "tools": ["Read", "Write"]}
        command = build_command(frontmatter, "Test prompt")

        assert "--allowedTools" in command
        idx = command.index("--allowedTools")
        assert command[idx + 1] == "Read,Write"

    def test_tools_as_dict(self) -> None:
        """Should parse dict of tools with enabled flags."""
        frontmatter = {"model": "opus", "tools": {"Read": True, "Write": True, "Bash": False}}
        command = build_command(frontmatter, "Test prompt")

        assert "--allowedTools" in command
        idx = command.index("--allowedTools")
        tools_str = command[idx + 1]
        assert "Read" in tools_str
        assert "Write" in tools_str
        assert "Bash" not in tools_str

    def test_tools_none(self) -> None:
        """Should handle None tools field."""
        frontmatter = {"model": "opus", "tools": None}
        command = build_command(frontmatter, "Test prompt")

        # No --allowedTools should be added when tools is None
        assert "--allowedTools" not in command

    def test_disallowed_tools_as_dict(self) -> None:
        """Should parse dict of disallowed tools with disabled flags."""
        frontmatter = {
            "model": "opus",
            "tools": "Read",
            "disallowedTools": {"Bash": True, "Write": False},
        }
        command = build_command(frontmatter, "Test prompt")

        assert "--disallowedTools" in command
        idx = command.index("--disallowedTools")
        assert "Bash" in command[idx + 1]
        assert "Write" not in command[idx + 1]

    def test_disallowed_tools_none(self) -> None:
        """Should handle None disallowedTools field."""
        frontmatter = {"model": "opus", "tools": "Read", "disallowedTools": None}
        command = build_command(frontmatter, "Test prompt")

        # No --disallowedTools should be added when None
        assert "--disallowedTools" not in command


class TestLoadAgent:
    """Tests for load_agent function."""

    def test_load_valid_agent(self, fs: FakeFilesystem) -> None:
        """Should load and parse valid agent file."""
        # Get the actual project root path (as resolved in the module)
        project_root = Path(__file__).resolve().parents[2]
        agent_path = project_root / "claude" / "agents"
        fs.create_dir(str(agent_path))

        agent_content = """---
tools: Read, Write
model: opus
---
You are a helpful assistant."""
        fs.create_file(str(agent_path / "test_agent.md"), contents=agent_content)

        frontmatter, system_prompt = load_agent("test_agent")

        assert frontmatter["tools"] == "Read, Write"
        assert frontmatter["model"] == "opus"
        assert system_prompt == "You are a helpful assistant."

    def test_load_agent_invalid_frontmatter(self, fs: FakeFilesystem) -> None:
        """Should raise ValueError for missing frontmatter delimiters."""
        project_root = Path(__file__).resolve().parents[2]
        agent_path = project_root / "claude" / "agents"
        fs.create_dir(str(agent_path))

        agent_content = """No frontmatter here"""
        fs.create_file(str(agent_path / "bad_agent.md"), contents=agent_content)

        with pytest.raises(ValueError, match="Invalid frontmatter"):
            load_agent("bad_agent")

    def test_load_agent_invalid_yaml(self, fs: FakeFilesystem) -> None:
        """Should raise ValueError for invalid YAML in frontmatter."""
        project_root = Path(__file__).resolve().parents[2]
        agent_path = project_root / "claude" / "agents"
        fs.create_dir(str(agent_path))

        agent_content = """---
[invalid: yaml: content
---
System prompt"""
        fs.create_file(str(agent_path / "yaml_bad.md"), contents=agent_content)

        with pytest.raises(ValueError, match="Invalid YAML"):
            load_agent("yaml_bad")

    def test_load_agent_non_dict_frontmatter(self, fs: FakeFilesystem) -> None:
        """Should raise TypeError when frontmatter is not a dict."""
        project_root = Path(__file__).resolve().parents[2]
        agent_path = project_root / "claude" / "agents"
        fs.create_dir(str(agent_path))

        agent_content = """---
- list item
- another item
---
System prompt"""
        fs.create_file(str(agent_path / "list_agent.md"), contents=agent_content)

        with pytest.raises(TypeError, match="Invalid frontmatter"):
            load_agent("list_agent")

    def test_load_agent_missing_tools(self, fs: FakeFilesystem) -> None:
        """Should raise KeyError for missing required tools field."""
        project_root = Path(__file__).resolve().parents[2]
        agent_path = project_root / "claude" / "agents"
        fs.create_dir(str(agent_path))

        agent_content = """---
model: opus
---
System prompt"""
        fs.create_file(str(agent_path / "no_tools.md"), contents=agent_content)

        with pytest.raises(KeyError, match="tools"):
            load_agent("no_tools")

    def test_load_agent_missing_model(self, fs: FakeFilesystem) -> None:
        """Should raise KeyError for missing required model field."""
        project_root = Path(__file__).resolve().parents[2]
        agent_path = project_root / "claude" / "agents"
        fs.create_dir(str(agent_path))

        agent_content = """---
tools: Read
---
System prompt"""
        fs.create_file(str(agent_path / "no_model.md"), contents=agent_content)

        with pytest.raises(KeyError, match="model"):
            load_agent("no_model")


class TestRunCommand:
    """Tests for run_command function."""

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
    """Tests for ClaudeRunner class."""

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
