from pathlib import Path
from typing import TYPE_CHECKING

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
    def _get_agent_path(self, fs: FakeFilesystem) -> Path:
        """Get the agent path as seen by load_agent (relative to claude_agent_runner.py)."""
        # load_agent resolves the path from claude_agent_runner.py's location
        # which is scripts/dev/claude_agent_runner.py -> parents[2] = project root
        from scripts.dev import claude_agent_runner

        module_path = Path(claude_agent_runner.__file__).resolve()
        project_root = module_path.parents[2]
        agent_path = project_root / "claude" / "agents"
        fs.create_dir(str(agent_path))
        return agent_path

    def test_load_valid_agent(self, fs: FakeFilesystem) -> None:
        """Should load and parse valid agent file."""
        agent_path = self._get_agent_path(fs)

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
        agent_path = self._get_agent_path(fs)

        agent_content = """No frontmatter here"""
        fs.create_file(str(agent_path / "bad_agent.md"), contents=agent_content)

        with pytest.raises(ValueError, match="Invalid frontmatter"):
            load_agent("bad_agent")

    def test_load_agent_invalid_yaml(self, fs: FakeFilesystem) -> None:
        """Should raise ValueError for invalid YAML in frontmatter."""
        agent_path = self._get_agent_path(fs)

        agent_content = """---
[invalid: yaml: content
---
System prompt"""
        fs.create_file(str(agent_path / "yaml_bad.md"), contents=agent_content)

        with pytest.raises(ValueError, match="Invalid YAML"):
            load_agent("yaml_bad")

    def test_load_agent_non_dict_frontmatter(self, fs: FakeFilesystem) -> None:
        """Should raise TypeError when frontmatter is not a dict."""
        agent_path = self._get_agent_path(fs)

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
        agent_path = self._get_agent_path(fs)

        agent_content = """---
model: opus
---
System prompt"""
        fs.create_file(str(agent_path / "no_tools.md"), contents=agent_content)

        with pytest.raises(KeyError, match="tools"):
            load_agent("no_tools")

    def test_load_agent_missing_model(self, fs: FakeFilesystem) -> None:
        """Should raise KeyError for missing required model field."""
        agent_path = self._get_agent_path(fs)

        agent_content = """---
tools: Read
---
System prompt"""
        fs.create_file(str(agent_path / "no_model.md"), contents=agent_content)

        with pytest.raises(KeyError, match="model"):
            load_agent("no_model")
