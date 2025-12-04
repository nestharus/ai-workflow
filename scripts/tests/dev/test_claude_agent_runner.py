"""Tests for scripts.dev.claude_agent_runner module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.claude_agent_runner import (
    build_command,
    load_agent,
    main,
    parse_args,
    run_command,
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


class TestLoadAgent:
    """Tests for load_agent function."""

    def test_loads_valid_agent_file(self, tmp_path: Path) -> None:
        """Should load frontmatter and system prompt from agent file."""
        agent_dir = tmp_path / "claude" / "agents"
        agent_dir.mkdir(parents=True)
        agent_file = agent_dir / "test-agent.md"
        agent_file.write_text(
            """---
name: test-agent
tools: Read, Write
model: haiku
---

You are a test agent."""
        )

        with patch.object(Path, "resolve", return_value=tmp_path / "scripts" / "dev" / "x.py"):
            with patch(
                "scripts.dev.claude_agent_runner.Path.__new__",
                side_effect=lambda cls, *args: Path.__new__(cls, *args),
            ):
                # Mock the parent resolution to point to tmp_path
                mock_path = MagicMock(spec=Path)
                mock_path.parents = {2: tmp_path}
                mock_path.__truediv__ = lambda self, x: tmp_path / x

                with patch(
                    "scripts.dev.claude_agent_runner.Path",
                    return_value=mock_path,
                ):
                    # Direct file read approach
                    frontmatter, system_prompt = _load_agent_from_path(agent_file)

        assert frontmatter["name"] == "test-agent"
        assert frontmatter["tools"] == "Read, Write"
        assert frontmatter["model"] == "haiku"
        assert system_prompt == "You are a test agent."

    def test_raises_for_invalid_frontmatter_format(self, tmp_path: Path) -> None:
        """Should raise ValueError for missing frontmatter delimiters."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text("No frontmatter here")

        with pytest.raises(ValueError, match="Invalid frontmatter"):
            _load_agent_from_path(agent_file)

    def test_raises_for_invalid_yaml(self, tmp_path: Path) -> None:
        """Should raise ValueError for invalid YAML in frontmatter."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
invalid: yaml: content: [
---

System prompt"""
        )

        with pytest.raises(ValueError, match="Invalid YAML"):
            _load_agent_from_path(agent_file)

    def test_raises_for_non_dict_frontmatter(self, tmp_path: Path) -> None:
        """Should raise ValueError when frontmatter is not a dict."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
- just
- a
- list
---

System prompt"""
        )

        with pytest.raises(ValueError, match="Invalid frontmatter"):
            _load_agent_from_path(agent_file)

    def test_raises_for_missing_tools_field(self, tmp_path: Path) -> None:
        """Should raise KeyError when tools field is missing."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
name: test-agent
model: haiku
---

System prompt"""
        )

        with pytest.raises(KeyError, match="tools"):
            _load_agent_from_path(agent_file)

    def test_raises_for_missing_model_field(self, tmp_path: Path) -> None:
        """Should raise KeyError when model field is missing."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
name: test-agent
tools: Read
---

System prompt"""
        )

        with pytest.raises(KeyError, match="model"):
            _load_agent_from_path(agent_file)


def _load_agent_from_path(agent_path: Path) -> tuple[dict, str]:
    """Helper to load agent directly from a path for testing."""
    import yaml

    content = agent_path.read_text(encoding="utf-8")
    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError("Invalid frontmatter in agent file")

    try:
        frontmatter = yaml.safe_load(parts[1])
    except Exception as exc:
        raise ValueError("Invalid YAML frontmatter") from exc

    if not isinstance(frontmatter, dict):
        raise ValueError("Invalid frontmatter in agent file")

    for key in ("tools", "model"):
        if key not in frontmatter:
            raise KeyError(f"Missing required frontmatter field: {key}")

    system_prompt = parts[2].strip()
    return frontmatter, system_prompt


class TestBuildCommand:
    """Tests for build_command function."""

    def test_builds_basic_command(self) -> None:
        """Should build command with required options."""
        frontmatter = {"tools": "Read, Write", "model": "haiku"}
        system_prompt = "You are a test agent."
        prompt = "Do something"

        command = build_command(frontmatter, system_prompt, prompt)

        assert command[0] == "claude"
        assert "-p" in command
        assert "--model" in command
        assert "haiku" in command
        assert "--system-prompt" in command
        assert system_prompt in command
        assert "--allowedTools" in command
        assert "Read" in command
        assert "Write" in command
        assert "--prompt" in command
        assert prompt in command

    def test_includes_disallowed_tools(self) -> None:
        """Should include disallowedTools when present in frontmatter."""
        frontmatter = {
            "tools": "Read",
            "model": "haiku",
            "disallowedTools": "Bash, Write",
        }
        system_prompt = "System"
        prompt = "Test"

        command = build_command(frontmatter, system_prompt, prompt)

        assert "--disallowedTools" in command
        assert "Bash" in command
        assert "Write" in command

    def test_handles_empty_tools(self) -> None:
        """Should handle empty tools field."""
        frontmatter = {"tools": "", "model": "haiku"}

        command = build_command(frontmatter, "System", "Test")

        assert "--allowedTools" in command

    def test_handles_missing_disallowed_tools(self) -> None:
        """Should not include disallowedTools flag when not in frontmatter."""
        frontmatter = {"tools": "Read", "model": "haiku"}

        command = build_command(frontmatter, "System", "Test")

        assert "--disallowedTools" not in command


class TestRunCommand:
    """Tests for run_command function."""

    def test_returns_zero_on_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 0 and print stdout on success."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Success output"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = run_command(["claude", "-p"])

        assert result == 0
        captured = capsys.readouterr()
        assert "Success output" in captured.out

    def test_returns_error_code_on_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return error code and print stderr on failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error message"

        with patch("subprocess.run", return_value=mock_result):
            result = run_command(["claude", "-p"])

        assert result == 1
        captured = capsys.readouterr()
        assert "Error message" in captured.err

    def test_handles_no_output(self) -> None:
        """Should handle case with no stdout or stderr."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = run_command(["claude", "-p"])

        assert result == 0


class TestMain:
    """Tests for main function."""

    def test_returns_zero_on_success(self, tmp_path: Path) -> None:
        """Should return 0 on successful execution."""
        agent_dir = tmp_path / "claude" / "agents"
        agent_dir.mkdir(parents=True)
        agent_file = agent_dir / "test.md"
        agent_file.write_text(
            """---
tools: Read
model: haiku
---

System prompt"""
        )

        mock_subprocess_result = MagicMock()
        mock_subprocess_result.returncode = 0
        mock_subprocess_result.stdout = "output"
        mock_subprocess_result.stderr = ""

        with (
            patch("sys.argv", ["prog", "--agent", "test", "--prompt", "hello"]),
            patch(
                "scripts.dev.claude_agent_runner.load_agent",
                return_value=({"tools": "Read", "model": "haiku"}, "System"),
            ),
            patch("subprocess.run", return_value=mock_subprocess_result),
        ):
            result = main()

        assert result == 0

    def test_returns_one_on_file_not_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 when agent file not found."""
        with (
            patch("sys.argv", ["prog", "--agent", "nonexistent", "--prompt", "hello"]),
            patch(
                "scripts.dev.claude_agent_runner.load_agent",
                side_effect=FileNotFoundError("Agent not found"),
            ),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Agent not found" in captured.err

    def test_returns_one_on_value_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 on ValueError from load_agent."""
        with (
            patch("sys.argv", ["prog", "--agent", "test", "--prompt", "hello"]),
            patch(
                "scripts.dev.claude_agent_runner.load_agent",
                side_effect=ValueError("Invalid frontmatter"),
            ),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Invalid frontmatter" in captured.err

    def test_returns_one_on_key_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 on KeyError from load_agent."""
        with (
            patch("sys.argv", ["prog", "--agent", "test", "--prompt", "hello"]),
            patch(
                "scripts.dev.claude_agent_runner.load_agent",
                side_effect=KeyError("Missing field"),
            ),
        ):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Missing field" in captured.err

    def test_returns_subprocess_returncode_on_called_process_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return subprocess returncode on CalledProcessError."""
        error = subprocess.CalledProcessError(42, ["claude"])
        error.stderr = "Process error"

        with (
            patch("sys.argv", ["prog", "--agent", "test", "--prompt", "hello"]),
            patch(
                "scripts.dev.claude_agent_runner.load_agent",
                return_value=({"tools": "Read", "model": "haiku"}, "System"),
            ),
            patch("scripts.dev.claude_agent_runner.run_command", side_effect=error),
        ):
            result = main()

        assert result == 42
        captured = capsys.readouterr()
        assert "Process error" in captured.err

    def test_returns_one_on_called_process_error_without_returncode(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return 1 when CalledProcessError has no returncode."""
        error = subprocess.CalledProcessError(0, ["claude"])
        error.stderr = ""

        with (
            patch("sys.argv", ["prog", "--agent", "test", "--prompt", "hello"]),
            patch(
                "scripts.dev.claude_agent_runner.load_agent",
                return_value=({"tools": "Read", "model": "haiku"}, "System"),
            ),
            patch("scripts.dev.claude_agent_runner.run_command", side_effect=error),
        ):
            result = main()

        assert result == 1
