# How To Write Agents Correctly

Agents are AI task executors with a single model defined in YAML frontmatter.
Agent files live in `.agents/agents/` and reference model configs in `.agents/models/`.

## Directory Structure

```text
.agents/
├── models/          # Model configurations (TOML - how to invoke AI backends)
│   ├── claude-sonnet.toml
│   ├── opencode-glm.toml
│   ├── gpt-5.2-codex-xhigh.toml
│   └── ...
└── agents/          # Agent configurations (Markdown - model + instructions)
    └── implementor.md
```

## Agent Configuration Format

Agents are Markdown files with YAML frontmatter:

```markdown
---
description: What this agent does
model: opencode-glm
---

Agent instructions go here...
```

### Frontmatter Fields

| Field | Required | Description |
|-------|----------|-------------|
| `description` | No | Short description of the agent's purpose |
| `model` | Yes | Model name (matches `.agents/models/<model>.toml`) |

## Using the Agent System

### Python API

```python
from pathlib import Path
from scripts.agents import load_models, load_agents

project_root = Path("/path/to/project")

# Load configurations
models = load_models(project_root / ".agents/models")
agents = load_agents(project_root / ".agents/agents")

# Get specific agent and model
my_agent = agents["my-agent"]
model = models[my_agent.model]

print(f"Using model: {model.name}")
print(f"Command: {model.command} {' '.join(model.args)}")
```

## Example Agent

```markdown
---
description: Implements code changes based on task files
model: gpt-5.2-codex-xhigh
---

You are an implementor agent. Your job is to...
```

## Model Limits

Keep prompts within the context limits of the chosen model. If a prompt exceeds the
model's context window, choose a larger-capacity model in the agent frontmatter.

## GLM-Specific Prompt Engineering

GLM agents MUST use contract-first prompts. Follow the structure documented in
docs/development/glm-prompt-guidelines.md.
