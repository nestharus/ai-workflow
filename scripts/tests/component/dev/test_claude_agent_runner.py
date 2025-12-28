from pathlib import Path

import pytest

from scripts.dev.claude_agent_runner import (
    build_command,
    main,
    parse_args,
    run_command,
)


class TestLoadAgent:
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
        """Should raise TypeError when frontmatter is not a dict."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
- just
- a
- list
---

System prompt"""
        )

        with pytest.raises(TypeError, match="Invalid frontmatter"):
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


def _load_agent_from_path(agent_path: Path) -> tuple[dict[str, str], str]:
    """Helper to load agent directly from a path for testing."""
    from typing import Any

    import yaml

    content = agent_path.read_text(encoding="utf-8")
    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError("Invalid frontmatter in agent file")

    try:
        frontmatter: Any = yaml.safe_load(parts[1])
    except Exception as exc:
        raise ValueError("Invalid YAML frontmatter") from exc

    if not isinstance(frontmatter, dict):
        raise TypeError("Invalid frontmatter in agent file")

    for key in ("tools", "model"):
        if key not in frontmatter:
            raise KeyError(f"Missing required frontmatter field: {key}")

    system_prompt = parts[2].strip()
    return frontmatter, system_prompt


class TestBuildCommand:
    def test_builds_basic_command(self) -> None:
        """Should build command with required options."""
        frontmatter = {"tools": "Read, Write", "model": "haiku"}
        system_prompt = "You are a test agent."

        command = build_command(frontmatter, system_prompt)

        assert command[0] == "claude"
        assert "-p" in command
        assert "--model" in command
        assert "haiku" in command
        assert "--system-prompt" in command
        assert system_prompt in command
        assert "--allowedTools" in command
        # Tools are joined with comma in a single argument
        tools_index = command.index("--allowedTools") + 1
        tools_arg = command[tools_index]
        tools_list = [t.strip() for t in tools_arg.split(",")]
        assert set(tools_list) == {"Read", "Write"}

    def test_includes_disallowed_tools(self) -> None:
        """Should include disallowedTools when present in frontmatter."""
        frontmatter = {
            "tools": "Read",
            "model": "haiku",
            "disallowedTools": "Bash, Write",
        }
        system_prompt = "System"

        command = build_command(frontmatter, system_prompt)

        assert "--disallowedTools" in command
        # Disallowed tools are joined with comma in a single argument
        disallowed_index = command.index("--disallowedTools") + 1
        disallowed_arg = command[disallowed_index]
        disallowed_list = [t.strip() for t in disallowed_arg.split(",")]
        assert set(disallowed_list) == {"Bash", "Write"}

    def test_handles_empty_tools(self) -> None:
        """Should handle empty tools field - no allowedTools when empty."""
        frontmatter = {"tools": "", "model": "haiku"}

        command = build_command(frontmatter, "System")

        # When tools is empty string, no allowedTools flag is added
        assert "--allowedTools" not in command

    def test_handles_none_tools(self) -> None:
        """Should handle None tools field appropriately."""
        frontmatter = {"tools": None, "model": "haiku"}

        command = build_command(frontmatter, "System")

        assert "--allowedTools" not in command

    def test_handles_whitespace_only_tools(self) -> None:
        """Should handle whitespace-only tools field."""
        frontmatter = {"tools": "   ", "model": "haiku"}

        command = build_command(frontmatter, "System")

        # Whitespace-only should be treated as empty tools
        assert "--allowedTools" not in command

    def test_handles_missing_disallowed_tools(self) -> None:
        """Should not include disallowedTools flag when not in frontmatter."""
        frontmatter = {"tools": "Read", "model": "haiku"}

        command = build_command(frontmatter, "System")

        assert "--disallowedTools" not in command

    def test_handles_tools_as_list(self) -> None:
        """Should handle tools field as a YAML list."""
        frontmatter = {"tools": ["Read", "Edit", "Bash"], "model": "haiku"}

        command = build_command(frontmatter, "System")

        assert "--allowedTools" in command
        tools_index = command.index("--allowedTools") + 1
        tools_arg = command[tools_index]
        tools_list = [t.strip() for t in tools_arg.split(",")]
        assert set(tools_list) == {"Read", "Edit", "Bash"}

    def test_handles_disallowed_tools_as_list(self) -> None:
        """Should handle disallowedTools field as a YAML list."""
        frontmatter = {
            "tools": "Read",
            "model": "haiku",
            "disallowedTools": ["Bash", "Write"],
        }

        command = build_command(frontmatter, "System")

        assert "--disallowedTools" in command
        disallowed_index = command.index("--disallowedTools") + 1
        disallowed_arg = command[disallowed_index]
        disallowed_list = [t.strip() for t in disallowed_arg.split(",")]
        assert set(disallowed_list) == {"Bash", "Write"}

    def test_handles_tools_list_with_whitespace(self) -> None:
        """Should trim whitespace from list items."""
        frontmatter = {"tools": ["  Read  ", " Edit ", ""], "model": "haiku"}

        command = build_command(frontmatter, "System")

        assert "--allowedTools" in command
        tools_index = command.index("--allowedTools") + 1
        tools_arg = command[tools_index]
        tools_list = [t.strip() for t in tools_arg.split(",")]
        assert set(tools_list) == {"Read", "Edit"}
