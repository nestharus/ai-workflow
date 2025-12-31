"""Agent routing logic for selecting models based on prompt characteristics.

This module implements a routing system that:
1. Loads model configurations from .agents/models/ (TOML files)
2. Loads agent configurations from .agents/agents/ (Markdown with YAML frontmatter)
3. Selects the appropriate model based on routing rules
4. Invokes the router agent for ambiguity classification when needed

Agent Format (.agents/agents/*.md):
    ---
    description: Agent description
    routing:
      - max_chars: 4000
        model: smollm2-135
        ambiguity: true
      - max_chars: 6000
        model: smollm2-360
        ambiguity: false
      - model: opencode-glm  # no max_chars = fallback
        ambiguity: true
    ---
    Agent instructions...

Routing Rules:
- max_chars: Maximum character count for this rule (absence = unlimited/fallback)
- model: Model name (references .agents/models/<model>.toml)
- ambiguity: Whether this model can handle ambiguous prompts (default: True)

Selection Logic:
1. Filter rules by max_chars >= len(prompt)
2. If all eligible rules allow ambiguity, use smallest max_chars rule
3. If any eligible rule doesn't allow ambiguity, invoke router agent
4. Route based on ambiguity classification result
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ModelConfig:
    """Configuration for a model from .agents/models/*.toml.

    Attributes:
        name: Model identifier (filename without .toml)
        command: CLI command to execute
        args: Arguments to pass to the command
        prompt_mode: How to pass the prompt - "stdin" (default) or "arg" (positional)
    """

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    prompt_mode: str = "stdin"  # "stdin" or "arg"


@dataclass
class RoutingRule:
    """A single routing rule within an agent."""

    model: str
    max_chars: int | None = None  # None means unlimited/fallback
    ambiguity: bool = True  # Whether model can handle ambiguous prompts


@dataclass
class AgentConfig:
    """Configuration for an agent from .agents/agents/*.md."""

    name: str
    description: str
    routing: list[RoutingRule] = field(default_factory=list)
    instructions: str = ""


def load_models(models_dir: Path) -> dict[str, ModelConfig]:
    """Load model configurations from .agents/models/ directory.

    Args:
        models_dir: Path to .agents/models/ directory

    Returns:
        Dictionary mapping model names to their configurations
    """
    models: dict[str, ModelConfig] = {}

    if not models_dir.exists():
        return models

    for toml_file in models_dir.glob("*.toml"):
        model_name = toml_file.stem
        content = toml_file.read_text()
        config = tomllib.loads(content)

        models[model_name] = ModelConfig(
            name=model_name,
            command=config.get("command", ""),
            args=config.get("args", []),
            prompt_mode=config.get("prompt_mode", "stdin"),
        )

    return models


def load_agents(agents_dir: Path) -> dict[str, AgentConfig]:
    """Load agent configurations from .agents/agents/ directory.

    Agents are markdown files with YAML frontmatter.

    Args:
        agents_dir: Path to .agents/agents/ directory

    Returns:
        Dictionary mapping agent names to their configurations
    """
    agents: dict[str, AgentConfig] = {}

    if not agents_dir.exists():
        return agents

    for md_file in agents_dir.glob("*.md"):
        agent_name = md_file.stem
        content = md_file.read_text()

        # Parse YAML frontmatter
        frontmatter_match = re.match(r"^---\n(.*?)\n---\n?(.*)", content, re.DOTALL)
        if not frontmatter_match:
            continue

        frontmatter_str = frontmatter_match.group(1)
        instructions = frontmatter_match.group(2).strip()

        frontmatter = yaml.safe_load(frontmatter_str) or {}

        # Parse routing rules
        routing_rules = []
        for rule_data in frontmatter.get("routing", []):
            routing_rules.append(
                RoutingRule(
                    model=rule_data.get("model", ""),
                    max_chars=rule_data.get("max_chars"),
                    ambiguity=rule_data.get("ambiguity", True),
                )
            )

        agents[agent_name] = AgentConfig(
            name=agent_name,
            description=frontmatter.get("description", ""),
            routing=routing_rules,
            instructions=instructions,
        )

    return agents


def select_rule(
    rules: list[RoutingRule],
    prompt_chars: int,
) -> RoutingRule | None:
    """Select the best routing rule for the given prompt size.

    Args:
        rules: List of routing rules
        prompt_chars: Character count of the prompt

    Returns:
        Selected rule, or None if no rule can handle the prompt
    """
    eligible = []

    for rule in rules:
        # None means unlimited
        if rule.max_chars is None or rule.max_chars >= prompt_chars:
            eligible.append(rule)

    if not eligible:
        return None

    # Sort by max_chars ascending (None treated as infinity)
    eligible.sort(key=lambda r: r.max_chars if r.max_chars is not None else float("inf"))

    return eligible[0]


def classify_ambiguity(
    router_agent: AgentConfig,
    models: dict[str, ModelConfig],
    prompt: str,
    cwd: Path | None = None,
) -> bool:
    """Classify whether a prompt is ambiguous using the router agent.

    The router agent is selected based on prompt size (max_chars only).

    Args:
        router_agent: Router agent configuration
        models: Dictionary of model configurations
        prompt: The prompt to classify
        cwd: Working directory for the agent

    Returns:
        True if the prompt is ambiguous, False otherwise
    """
    prompt_chars = len(prompt)

    # Select routing rule based on max_chars only
    rule = select_rule(router_agent.routing, prompt_chars)
    if rule is None:
        # No rule can handle this prompt, assume ambiguous
        return True

    model = models.get(rule.model)
    if model is None:
        # Model not found, assume ambiguous
        return True

    # Build full prompt with instructions
    full_prompt = f"{router_agent.instructions}\n\n{prompt}"

    # Execute the model based on prompt_mode
    if model.prompt_mode == "arg":
        result = subprocess.run(
            [model.command, *model.args, full_prompt],
            capture_output=True,
            text=True,
            cwd=cwd or Path.cwd(),
        )
    else:
        result = subprocess.run(
            [model.command, *model.args],
            input=full_prompt,
            capture_output=True,
            text=True,
            cwd=cwd or Path.cwd(),
        )

    output = result.stdout.strip().lower()

    # Parse the response - expect "true" or "false"
    return output == "true" or "true" in output


def route_prompt(
    agent: AgentConfig,
    router_agent: AgentConfig,
    models: dict[str, ModelConfig],
    prompt: str,
    cwd: Path | None = None,
) -> RoutingRule | None:
    """Route a prompt to the appropriate model based on size and ambiguity.

    Args:
        agent: Agent configuration with routing rules
        router_agent: Router agent for ambiguity classification
        models: Dictionary of model configurations
        prompt: The prompt to route
        cwd: Working directory for agents

    Returns:
        Selected routing rule, or None if no rule can handle the prompt
    """
    prompt_chars = len(prompt)

    # Filter rules by max_chars
    eligible_rules = []
    for rule in agent.routing:
        if rule.max_chars is None or rule.max_chars >= prompt_chars:
            eligible_rules.append(rule)

    if not eligible_rules:
        return None

    # Check if all eligible rules allow ambiguity
    all_allow_ambiguity = all(r.ambiguity for r in eligible_rules)

    if all_allow_ambiguity:
        # No classification needed - return smallest eligible rule
        eligible_rules.sort(key=lambda r: r.max_chars if r.max_chars is not None else float("inf"))
        return eligible_rules[0]

    # Need to classify ambiguity
    is_ambiguous = classify_ambiguity(router_agent, models, prompt, cwd)

    if is_ambiguous:
        # Route to rule that allows ambiguity
        ambiguity_rules = [r for r in eligible_rules if r.ambiguity]
        if ambiguity_rules:
            ambiguity_rules.sort(
                key=lambda r: r.max_chars if r.max_chars is not None else float("inf")
            )
            return ambiguity_rules[0]
        # Fallback to any rule
        return eligible_rules[0]
    else:
        # Non-ambiguous - any rule can handle it
        eligible_rules.sort(key=lambda r: r.max_chars if r.max_chars is not None else float("inf"))
        return eligible_rules[0]
