"""Tests for scripts.dev.agent_runner module - abstract base class and factory."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.dev.agent_runner import AgentRunner


# Minimal concrete implementation for testing abstract base class
class ConcreteTestRunner(AgentRunner):
    """Concrete AgentRunner for testing purposes."""

    def run(self, prompt: str) -> str:
        """Execute the agent."""
        return f"Executed: {prompt}"


class TestAgentRunnerInit:
    """Tests for AgentRunner.__init__ method."""

    def test_init_with_valid_config(self) -> None:
        """Should initialize with all required fields present."""
        config = {
            "model": "test-model",
            "provider": "claude",
            "_system_prompt": "Test system prompt",
        }
        runner = ConcreteTestRunner(config)
        assert runner.agent_config == config

    def test_init_missing_model_raises_key_error(self) -> None:
        """Should raise KeyError when model is missing."""
        config = {
            "provider": "claude",
            "_system_prompt": "Test system prompt",
        }
        with pytest.raises(KeyError, match="model"):
            ConcreteTestRunner(config)

    def test_init_missing_provider_raises_key_error(self) -> None:
        """Should raise KeyError when provider is missing."""
        config = {
            "model": "test-model",
            "_system_prompt": "Test system prompt",
        }
        with pytest.raises(KeyError, match="provider"):
            ConcreteTestRunner(config)

    def test_init_missing_system_prompt_raises_key_error(self) -> None:
        """Should raise KeyError when _system_prompt is missing."""
        config = {
            "model": "test-model",
            "provider": "claude",
        }
        with pytest.raises(KeyError, match="_system_prompt"):
            ConcreteTestRunner(config)


class TestAgentRunnerSystemPrompt:
    """Tests for AgentRunner.system_prompt property."""

    def test_system_prompt_returns_stored_value(self) -> None:
        """Should return the system prompt from agent_config."""
        config = {
            "model": "test-model",
            "provider": "claude",
            "_system_prompt": "You are a helpful assistant.",
        }
        runner = ConcreteTestRunner(config)
        assert runner.system_prompt == "You are a helpful assistant."


class TestSelectFromRoutingThresholds:
    """Tests for AgentRunner.select_from_routing_thresholds static method."""

    def test_selects_first_matching_threshold(self) -> None:
        """Should return model/provider for first threshold where prompt_chars <= max_chars."""
        thresholds = [
            {"max_chars": 3500, "model": "gpt-medium", "provider": "opencode"},
            {"max_chars": 7500, "model": "gpt-high", "provider": "opencode"},
            {"max_chars": None, "model": "opus", "provider": "claude"},
        ]
        result = AgentRunner.select_from_routing_thresholds(thresholds, 2000)
        assert result == ("gpt-medium", "opencode")

    def test_selects_second_threshold_when_exceeds_first(self) -> None:
        """Should skip first threshold when prompt_chars exceeds its max_chars."""
        thresholds = [
            {"max_chars": 3500, "model": "gpt-medium", "provider": "opencode"},
            {"max_chars": 7500, "model": "gpt-high", "provider": "opencode"},
            {"max_chars": None, "model": "opus", "provider": "claude"},
        ]
        result = AgentRunner.select_from_routing_thresholds(thresholds, 5000)
        assert result == ("gpt-high", "opencode")

    def test_selects_catch_all_threshold(self) -> None:
        """Should select threshold with None max_chars as catch-all."""
        thresholds = [
            {"max_chars": 3500, "model": "gpt-medium", "provider": "opencode"},
            {"max_chars": 7500, "model": "gpt-high", "provider": "opencode"},
            {"max_chars": None, "model": "opus", "provider": "claude"},
        ]
        result = AgentRunner.select_from_routing_thresholds(thresholds, 10000)
        assert result == ("opus", "claude")

    def test_returns_none_when_no_thresholds_match(self) -> None:
        """Should return None when no thresholds match (e.g., empty list)."""
        result = AgentRunner.select_from_routing_thresholds([], 5000)
        assert result is None

    def test_exact_boundary_match(self) -> None:
        """Should include prompt_chars equal to max_chars."""
        thresholds = [
            {"max_chars": 3500, "model": "gpt-medium", "provider": "opencode"},
            {"max_chars": 7500, "model": "gpt-high", "provider": "opencode"},
        ]
        result = AgentRunner.select_from_routing_thresholds(thresholds, 3500)
        assert result == ("gpt-medium", "opencode")


class TestLoadFrontmatter:
    """Tests for AgentRunner.load_frontmatter static method."""

    def test_loads_valid_frontmatter_with_model_provider(self, tmp_path: Path) -> None:
        """Should parse frontmatter with model and provider fields."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
model: haiku
provider: claude
---

You are a test agent."""
        )
        result = AgentRunner.load_frontmatter(agent_file)
        assert result["model"] == "haiku"
        assert result["provider"] == "claude"
        assert result["_system_prompt"] == "You are a test agent."

    def test_loads_frontmatter_with_routing_thresholds(self, tmp_path: Path) -> None:
        """Should accept frontmatter with routing_thresholds instead of model/provider."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
routing_thresholds:
  - max_chars: 5000
    model: gpt-medium
    provider: opencode
  - max_chars: null
    model: opus
    provider: claude
---

System prompt with routing."""
        )
        result = AgentRunner.load_frontmatter(agent_file)
        assert "routing_thresholds" in result
        assert len(result["routing_thresholds"]) == 2
        assert result["_system_prompt"] == "System prompt with routing."

    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError for non-existent file."""
        agent_file = tmp_path / "nonexistent.md"
        with pytest.raises(FileNotFoundError, match="Agent file not found"):
            AgentRunner.load_frontmatter(agent_file)

    def test_raises_value_error_for_missing_frontmatter_delimiters(self, tmp_path: Path) -> None:
        """Should raise ValueError for file without proper frontmatter."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text("No frontmatter here, just content")
        with pytest.raises(ValueError, match="Invalid frontmatter"):
            AgentRunner.load_frontmatter(agent_file)

    def test_raises_value_error_for_invalid_yaml(self, tmp_path: Path) -> None:
        """Should raise ValueError for invalid YAML in frontmatter."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
invalid: yaml: content: [
---

System prompt"""
        )
        with pytest.raises(ValueError, match="Invalid YAML"):
            AgentRunner.load_frontmatter(agent_file)

    def test_raises_type_error_for_non_dict_frontmatter(self, tmp_path: Path) -> None:
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
            AgentRunner.load_frontmatter(agent_file)

    def test_raises_key_error_for_missing_required_fields(self, tmp_path: Path) -> None:
        """Should raise KeyError when neither routing_thresholds nor model/provider exist."""
        agent_file = tmp_path / "test-agent.md"
        agent_file.write_text(
            """---
name: just-a-name
---

System prompt"""
        )
        with pytest.raises(KeyError, match="routing_thresholds"):
            AgentRunner.load_frontmatter(agent_file)


class TestFromAgentName:
    """Tests for AgentRunner.from_agent_name factory method."""

    def test_creates_claude_runner(self, tmp_path: Path) -> None:
        """Should create ClaudeRunner for claude provider."""
        # Set up config file
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("agents_dir: agents")

        # Set up agent file
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text(
            """---
model: haiku
provider: claude
tools: Read
---

Test claude agent."""
        )

        runner = AgentRunner.from_agent_name("test-agent", config_file)
        assert runner.__class__.__name__ == "ClaudeRunner"
        assert runner.agent_config["model"] == "haiku"
        assert runner.agent_config["provider"] == "claude"

    def test_creates_opencode_runner(self, tmp_path: Path) -> None:
        """Should create OpencodeRunner for opencode provider."""
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("agents_dir: agents")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text(
            """---
model: gpt-4
provider: opencode
---

Test opencode agent."""
        )

        runner = AgentRunner.from_agent_name("test-agent", config_file)
        assert runner.__class__.__name__ == "OpencodeRunner"
        assert runner.agent_config["name"] == "test-agent"

    def test_creates_huggingface_runner(self, tmp_path: Path) -> None:
        """Should create HuggingfaceRunner for huggingface provider."""
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("agents_dir: agents")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text(
            """---
model: qwen
provider: huggingface
---

Test huggingface agent."""
        )

        runner = AgentRunner.from_agent_name("test-agent", config_file)
        assert runner.__class__.__name__ == "HuggingfaceRunner"

    def test_raises_for_missing_config_file(self, tmp_path: Path) -> None:
        """Should raise FileNotFoundError for missing config file."""
        config_file = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            AgentRunner.from_agent_name("test-agent", config_file)

    def test_raises_for_invalid_yaml_config(self, tmp_path: Path) -> None:
        """Should raise ValueError for invalid YAML config."""
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("invalid: yaml: [")
        with pytest.raises(ValueError, match="Invalid YAML"):
            AgentRunner.from_agent_name("test-agent", config_file)

    def test_raises_for_non_dict_config(self, tmp_path: Path) -> None:
        """Should raise TypeError when config is not a dict."""
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("- just\n- a\n- list")
        with pytest.raises(TypeError, match="must contain a dict"):
            AgentRunner.from_agent_name("test-agent", config_file)

    def test_raises_for_missing_agents_dir(self, tmp_path: Path) -> None:
        """Should raise ValueError when agents_dir is missing."""
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("other_key: value")
        with pytest.raises(ValueError, match="agents_dir"):
            AgentRunner.from_agent_name("test-agent", config_file)

    def test_raises_for_unknown_provider(self, tmp_path: Path) -> None:
        """Should raise ValueError for unknown provider."""
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("agents_dir: agents")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text(
            """---
model: custom
provider: unknown_provider
---

Test agent."""
        )

        with pytest.raises(ValueError, match="Unknown provider"):
            AgentRunner.from_agent_name("test-agent", config_file)

    def test_applies_model_override(self, tmp_path: Path) -> None:
        """Should apply model override to agent config."""
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("agents_dir: agents")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text(
            """---
model: haiku
provider: claude
---

Test agent."""
        )

        runner = AgentRunner.from_agent_name("test-agent", config_file, model="opus")
        assert runner.agent_config["model"] == "opus"

    def test_applies_provider_override(self, tmp_path: Path) -> None:
        """Should apply provider override and select runner accordingly."""
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("agents_dir: agents")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text(
            """---
model: gpt-4
provider: opencode
---

Test agent."""
        )

        runner = AgentRunner.from_agent_name("test-agent", config_file, provider="claude")
        assert runner.__class__.__name__ == "ClaudeRunner"
        assert runner.agent_config["provider"] == "claude"

    def test_routing_with_prompt_chars(self, tmp_path: Path) -> None:
        """Should use routing_thresholds when prompt_chars is provided."""
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("agents_dir: agents")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text(
            """---
routing_thresholds:
  - max_chars: 5000
    model: gpt-medium
    provider: opencode
  - max_chars: null
    model: opus
    provider: claude
---

Agent with routing."""
        )

        # Small prompt should select first threshold
        runner = AgentRunner.from_agent_name("test-agent", config_file, prompt_chars=3000)
        assert runner.__class__.__name__ == "OpencodeRunner"
        assert runner.agent_config["model"] == "gpt-medium"

    def test_routing_selects_catch_all(self, tmp_path: Path) -> None:
        """Should select catch-all threshold for large prompt_chars."""
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("agents_dir: agents")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text(
            """---
routing_thresholds:
  - max_chars: 5000
    model: gpt-medium
    provider: opencode
  - max_chars: null
    model: opus
    provider: claude
---

Agent with routing."""
        )

        # Large prompt should select catch-all
        runner = AgentRunner.from_agent_name("test-agent", config_file, prompt_chars=10000)
        assert runner.__class__.__name__ == "ClaudeRunner"
        assert runner.agent_config["model"] == "opus"

    def test_routing_without_prompt_chars_selects_catch_all(self, tmp_path: Path) -> None:
        """Should default to catch-all when prompt_chars not provided."""
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("agents_dir: agents")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text(
            """---
routing_thresholds:
  - max_chars: 5000
    model: gpt-medium
    provider: opencode
  - max_chars: null
    model: opus
    provider: claude
---

Agent with routing."""
        )

        # Without prompt_chars, should use large value (2**31) and select catch-all
        runner = AgentRunner.from_agent_name("test-agent", config_file)
        assert runner.__class__.__name__ == "ClaudeRunner"
        assert runner.agent_config["model"] == "opus"

    def test_explicit_override_takes_precedence_over_routing(self, tmp_path: Path) -> None:
        """Should prefer explicit model/provider override over routing."""
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("agents_dir: agents")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text(
            """---
routing_thresholds:
  - max_chars: 5000
    model: gpt-medium
    provider: opencode
  - max_chars: null
    model: opus
    provider: claude
---

Agent with routing."""
        )

        # With explicit override, routing should be skipped
        runner = AgentRunner.from_agent_name(
            "test-agent", config_file, model="haiku", provider="claude", prompt_chars=1000
        )
        assert runner.__class__.__name__ == "ClaudeRunner"
        assert runner.agent_config["model"] == "haiku"

    def test_resolves_absolute_agents_dir(self, tmp_path: Path) -> None:
        """Should handle absolute agents_dir path."""
        agents_dir = tmp_path / "absolute_agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "test-agent.md"
        agent_file.write_text(
            """---
model: haiku
provider: claude
---

Test agent."""
        )

        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text(f"agents_dir: {agents_dir}")

        runner = AgentRunner.from_agent_name("test-agent", config_file)
        assert runner.__class__.__name__ == "ClaudeRunner"

    def test_raises_value_error_when_no_provider_after_routing(self, tmp_path: Path) -> None:
        """Should raise ValueError when routing fails and no provider is available."""
        config_file = tmp_path / ".tasks.yaml"
        config_file.write_text("agents_dir: agents")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "test-agent.md"
        # Agent with routing_thresholds but empty list (no match possible)
        agent_file.write_text(
            """---
routing_thresholds: []
---

Agent with empty routing."""
        )

        with pytest.raises(ValueError, match="No provider selected"):
            AgentRunner.from_agent_name("test-agent", config_file)
