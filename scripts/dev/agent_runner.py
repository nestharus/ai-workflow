"""Abstract base class for unified agent runner interface in the .tasks system.

This module provides the abstract base class and factory method for running agents
from different providers (Claude, OpenCode, HuggingFace) through a unified API.
Concrete implementations live in provider-specific runner modules:
- scripts.dev.claude_agent_runner.ClaudeRunner
- scripts.dev.opencode_agent_runner.OpencodeRunner
- scripts.dev.huggingface_agent_runner.HuggingfaceRunner

Each agent can define `routing_thresholds` in its frontmatter to specify which
runner/model combination to use for different prompt character counts. When
`prompt_chars` is provided to `from_agent_name()`, the agent's routing_thresholds
are consulted to automatically select the appropriate model/provider.

Example usage:
    from pathlib import Path
    from scripts.dev.agent_runner import AgentRunner

    config_path = Path(".tasks.yaml")

    # Without routing (uses frontmatter defaults)
    runner = AgentRunner.from_agent_name('implementor', config_path)
    result = runner.run("Implement feature X")

    # With routing (selects model/provider based on prompt character count)
    runner = AgentRunner.from_agent_name('implementor', config_path, prompt_chars=5000)
    result = runner.run("Implement feature X")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

# Key used to store system prompt inside agent_config dict
_SYSTEM_PROMPT_KEY = "_system_prompt"


class AgentRunner(ABC):
    """Abstract base class for agent runners.

    Provides unified interface for running agents from different providers.
    Subclasses must implement the `run` method for provider-specific execution.

    The agent configuration dict (agent_config) contains all frontmatter fields
    plus the system prompt stored under the '_system_prompt' key.

    Attributes:
        agent_config: Parsed frontmatter configuration dict, including system prompt
            under the '_system_prompt' key.
    """

    def __init__(self, agent_config: dict[str, Any]) -> None:
        """Initialize the agent runner.

        Args:
            agent_config: Parsed frontmatter configuration containing at minimum
                'model', 'provider', and '_system_prompt' fields. The '_system_prompt'
                key is automatically added by load_frontmatter().

        Raises:
            KeyError: If required fields 'model', 'provider', or '_system_prompt'
                are missing from config.
        """
        for key in ("model", "provider", _SYSTEM_PROMPT_KEY):
            if key not in agent_config:
                raise KeyError(f"Missing required field: {key}")

        self.agent_config = agent_config

    @property
    def system_prompt(self) -> str:
        """Return the system prompt from agent config."""
        return self.agent_config[_SYSTEM_PROMPT_KEY]

    @abstractmethod
    def run(self, prompt: str) -> str:
        """Execute the agent with the given prompt.

        Args:
            prompt: User prompt to send to the agent.

        Returns:
            Output string from the agent execution. For CLI-based providers
            (Claude, OpenCode), this is the captured stdout. For library-based
            providers (HuggingFace), this is the generated text.

        Raises:
            RuntimeError: If agent execution fails.
        """

    @staticmethod
    def select_from_routing_thresholds(
        routing_thresholds: list[dict[str, Any]], prompt_chars: int
    ) -> tuple[str, str] | None:
        """Select model and provider based on prompt character count and routing thresholds.

        Iterates through thresholds in order (expected to be sorted from smallest to
        largest max_chars). Returns the model and provider for the first threshold where
        prompt_chars <= max_chars, or where max_chars is None (catch-all).

        Args:
            routing_thresholds: List of threshold dicts with 'max_chars', 'model',
                and 'provider' keys. The list should be ordered from smallest to
                largest max_chars, with a null max_chars as the final catch-all.
            prompt_chars: Number of characters in the prompt.

        Returns:
            Tuple of (model, provider) strings for the matched threshold, or None
            if no threshold matches. When None is returned, the caller should fall
            back to the agent's default model/provider from frontmatter.

        Example:
            >>> thresholds = [
            ...     {"max_chars": 3500, "model": "gpt-medium", "provider": "opencode"},
            ...     {"max_chars": 7500, "model": "gpt-high", "provider": "opencode"},
            ...     {"max_chars": None, "model": "opus", "provider": "claude"},
            ... ]
            >>> AgentRunner.select_from_routing_thresholds(thresholds, 2000)
            ('gpt-medium', 'opencode')
            >>> AgentRunner.select_from_routing_thresholds(thresholds, 5000)
            ('gpt-high', 'opencode')
            >>> AgentRunner.select_from_routing_thresholds(thresholds, 10000)
            ('opus', 'claude')
        """
        for threshold in routing_thresholds:
            max_chars = threshold.get("max_chars")
            if max_chars is None or prompt_chars <= max_chars:
                return threshold["model"], threshold["provider"]

        return None

    @staticmethod
    def load_frontmatter(agent_path: Path) -> dict[str, Any]:
        """Load and parse frontmatter from an agent markdown file.

        Reads the agent file, splits on '---' delimiter to extract YAML frontmatter,
        validates required fields, and returns the configuration dict with system
        prompt included under the '_system_prompt' key.

        Args:
            agent_path: Path to the agent markdown file.

        Returns:
            Dict containing parsed YAML configuration with system prompt stored
            under the '_system_prompt' key.

        Raises:
            FileNotFoundError: If the agent file does not exist.
            ValueError: If the file has invalid frontmatter format, invalid YAML,
                or the parsed frontmatter is not a dict.
            KeyError: If required fields 'model' or 'provider' are missing.
        """
        try:
            content = agent_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Agent file not found: {agent_path}") from exc

        parts = content.split("---", 2)
        if len(parts) < 3:
            raise ValueError("Invalid frontmatter in agent file")

        try:
            frontmatter = yaml.safe_load(parts[1])
        except yaml.YAMLError as exc:
            raise ValueError("Invalid YAML frontmatter") from exc

        if not isinstance(frontmatter, dict):
            raise ValueError("Invalid frontmatter in agent file")

        # Validate required fields
        for key in ("model", "provider"):
            if key not in frontmatter:
                raise KeyError(f"Missing required frontmatter field: {key}")

        # Store system prompt inside the config dict
        frontmatter[_SYSTEM_PROMPT_KEY] = parts[2].strip()

        return frontmatter

    @staticmethod
    def from_agent_name(
        agent_name: str,
        config_path: Path,
        *,
        model: str | None = None,
        provider: str | None = None,
        prompt_chars: int | None = None,
    ) -> AgentRunner:
        """Create an AgentRunner instance from an agent name and config file.

        Factory method that loads the .tasks.yaml configuration, locates the agent
        markdown file in the configured agents_dir (resolved relative to the config
        file location), parses frontmatter to determine the provider, and returns
        the appropriate runner subclass.

        Optional model and provider overrides can be specified to override the values
        from the agent's frontmatter. When provider is overridden, the runner class
        is selected based on the override value, not the frontmatter.

        When prompt_chars is provided and the agent has routing_thresholds defined
        in its frontmatter, the routing logic is applied to select the appropriate
        model and provider. Explicit model/provider overrides take precedence over
        routing.

        Routing precedence (highest to lowest):
        1. Explicit model/provider parameters
        2. Routing based on prompt_chars and routing_thresholds
        3. Agent frontmatter defaults

        Args:
            agent_name: Name of the agent (without .md extension).
            config_path: Path to the .tasks.yaml configuration file.
            model: Optional model override. If provided, replaces the frontmatter model.
            provider: Optional provider override. If provided, replaces the frontmatter
                provider and determines which runner class to instantiate.
            prompt_chars: Optional prompt character count for routing. When provided
                and agent has routing_thresholds, selects model/provider based on
                character count.

        Returns:
            An instance of the appropriate AgentRunner subclass based on the
            provider (override, routed, or frontmatter).

        Raises:
            FileNotFoundError: If config file or agent file does not exist.
            ValueError: If config is invalid, missing agents_dir, or unknown provider.
            KeyError: If agent frontmatter is missing required fields.
        """
        try:
            config_content = config_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"Config file not found: {config_path}") from exc

        try:
            config = yaml.safe_load(config_content)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML in config file: {config_path}") from exc

        if not isinstance(config, dict):
            raise ValueError(f"Config file must contain a dict: {config_path}")

        if "agents_dir" not in config:
            raise ValueError(f"Config file missing 'agents_dir' field: {config_path}")

        # Resolve agents_dir relative to config file location
        base_dir = config_path.parent
        agents_dir_path = Path(config["agents_dir"])
        if agents_dir_path.is_absolute():
            agents_dir = agents_dir_path
        else:
            agents_dir = base_dir / agents_dir_path

        agent_path = agents_dir / f"{agent_name}.md"
        agent_config = AgentRunner.load_frontmatter(agent_path)

        # Apply routing if prompt_chars is provided and no explicit overrides
        if (
            prompt_chars is not None
            and model is None
            and provider is None
            and "routing_thresholds" in agent_config
        ):
            routing_result = AgentRunner.select_from_routing_thresholds(
                agent_config["routing_thresholds"], prompt_chars
            )
            if routing_result is not None:
                model, provider = routing_result

        # Apply overrides if provided (explicit or from routing)
        if model is not None:
            agent_config["model"] = model
        if provider is not None:
            agent_config["provider"] = provider

        # Select runner class based on effective provider
        effective_provider = agent_config["provider"]

        if effective_provider == "claude":
            from scripts.dev.claude_agent_runner import ClaudeRunner

            return ClaudeRunner(agent_config)

        if effective_provider == "opencode":
            from scripts.dev.opencode_agent_runner import OpencodeRunner

            # Store agent_name for OpenCode runner to use
            agent_config.setdefault("name", agent_name)
            return OpencodeRunner(agent_config)

        if effective_provider == "huggingface":
            from scripts.dev.huggingface_agent_runner import HuggingfaceRunner

            return HuggingfaceRunner(agent_config)

        raise ValueError(f"Unknown provider: {effective_provider}")
