"""Agent configuration loading utilities."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ModelConfig:
    """Configuration for a model from .agents/models/*.toml."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    prompt_mode: str = "stdin"  # "stdin" or "arg"


@dataclass
class AgentConfig:
    """Configuration for an agent from .agents/agents/*.md."""

    name: str
    description: str
    model: str
    output_format: str = ""
    instructions: str = ""


def load_models(models_dir: Path) -> dict[str, ModelConfig]:
    """Load model configurations from .agents/models/ directory."""
    models: dict[str, ModelConfig] = {}

    if not models_dir.exists():
        return models

    for toml_file in models_dir.glob("*.toml"):
        model_name = toml_file.stem
        config = tomllib.loads(toml_file.read_text())

        models[model_name] = ModelConfig(
            name=model_name,
            command=config.get("command", ""),
            args=config.get("args", []),
            prompt_mode=config.get("prompt_mode", "stdin"),
        )

    return models


def load_agents(agents_dir: Path) -> dict[str, AgentConfig]:
    """Load agent configurations from .agents/agents/ directory."""
    agents: dict[str, AgentConfig] = {}

    if not agents_dir.exists():
        return agents

    for md_file in agents_dir.glob("*.md"):
        agent_name = md_file.stem
        content = md_file.read_text()

        frontmatter_match = re.match(r"^---\n(.*?)\n---\n?(.*)", content, re.DOTALL)
        if not frontmatter_match:
            continue

        frontmatter_str = frontmatter_match.group(1)
        instructions = frontmatter_match.group(2).strip()

        frontmatter = yaml.safe_load(frontmatter_str) or {}

        model = frontmatter.get("model", "")
        repair_model = os.getenv("REPAIR_MODEL")
        if repair_model and agent_name.startswith("repair-"):
            model = repair_model

        agents[agent_name] = AgentConfig(
            name=agent_name,
            description=frontmatter.get("description", ""),
            model=model,
            output_format=frontmatter.get("output_format", ""),
            instructions=instructions,
        )

    return agents
