# How To Write Agents Correctly

Agents are AI task executors with routing rules. They are stored in `.agents/agents/`
as Markdown files with YAML frontmatter. Each agent defines routing rules that determine
which model handles prompts based on size and ambiguity.

## Directory Structure

```text
.agents/
├── models/          # Model configurations (TOML - how to invoke AI backends)
│   ├── claude-sonnet.toml
│   ├── smollm2-135.toml
│   ├── opencode-glm.toml
│   └── ...
└── agents/          # Agent configurations (Markdown - routing rules + instructions)
    └── router.md    # Single router agent for ambiguity classification
```

## Agent Configuration Format

Agents are Markdown files with YAML frontmatter:

```markdown
---
description: What this agent does
routing:
  - max_chars: 4000
    model: smollm2-135
    ambiguity: true
  - max_chars: 6000
    model: smollm2-360
    ambiguity: false
  - model: opencode-glm
    ambiguity: true
---

Agent instructions go here...
```

### Frontmatter Fields

| Field | Required | Description |
|-------|----------|-------------|
| `description` | No | Short description of the agent's purpose |
| `routing` | Yes | List of routing rules (see below) |

### Routing Rules

Each routing rule specifies when and how to use a particular model:

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `model` | Yes | - | Model name (matches `.agents/models/<model>.toml`) |
| `max_chars` | No | unlimited | Max character count for this rule |
| `ambiguity` | No | `true` | Whether this model can handle ambiguous prompts |

## Routing Logic

The routing system works as follows:

1. **Filter by size**: Only rules with `max_chars >= len(prompt)` are eligible
2. **Check ambiguity**:
   - If ALL eligible rules allow ambiguity → use smallest `max_chars` rule
   - If ANY eligible rule has `ambiguity: false` → classify the prompt first
3. **Classify if needed**: The router agent determines if prompt is ambiguous
4. **Route appropriately**:
   - Ambiguous prompts → rules with `ambiguity: true`
   - Non-ambiguous prompts → any eligible rule (prefer smallest)

## The Router Agent

There is exactly ONE router agent (`.agents/agents/router.md`). It classifies prompts
as ambiguous or not. The router agent:

- Only routes on `max_chars` (cannot use `ambiguity` to avoid recursion)
- Returns `true` (ambiguous) or `false` (not ambiguous)
- Uses smaller/faster models for small prompts, falls back to larger models

```markdown
---
description: Classifies prompts as ambiguous or not ambiguous
routing:
  - max_chars: 4000
    model: smollm2-135
  - max_chars: 6000
    model: smollm2-360
  - model: opencode-glm
---

You are an ambiguity classifier...
```

Note: The router agent's rules do NOT have `ambiguity` field because the router
itself cannot trigger ambiguity classification (that would cause infinite recursion).

## Using the Routing System

### Python API

```python
from pathlib import Path
from scripts.agents import load_models, load_agents, route_prompt

project_root = Path("/path/to/project")

# Load configurations
models = load_models(project_root / ".agents/models")
agents = load_agents(project_root / ".agents/agents")

# Get specific agents
my_agent = agents["my-agent"]
router = agents["router"]

# Route a prompt
prompt = "Help me write a function"
rule = route_prompt(my_agent, router, models, prompt)

if rule:
    model = models[rule.model]
    print(f"Using model: {model.name}")
    print(f"Command: {model.command} {' '.join(model.args)}")
```

## Example Agent with Routing

```markdown
---
description: Implements code changes based on task files
routing:
  - max_chars: 3500
    model: gpt-5.1-codex-medium
    ambiguity: false
  - max_chars: 7500
    model: gpt-5.1-codex-high
    ambiguity: false
  - max_chars: 12500
    model: gpt-5.1-codex-xhigh
    ambiguity: true
  - model: claude-opus
    ambiguity: true
---

You are an implementor agent. Your job is to...
```

In this example:
- Small prompts (≤3500 chars) use `gpt-5.1-codex-medium` but only if NOT ambiguous
- Medium prompts (≤7500 chars) use `gpt-5.1-codex-high` but only if NOT ambiguous
- Larger prompts (≤12500 chars) use `gpt-5.1-codex-xhigh` which handles ambiguity
- Largest prompts use `claude-opus` as fallback (handles any ambiguity)

If a 3000 char prompt comes in:
- Eligible rules: all of them
- Some rules have `ambiguity: false`
- Router classifies the prompt
- If ambiguous → routes to `gpt-5.1-codex-xhigh` (first eligible with ambiguity)
- If not ambiguous → routes to `gpt-5.1-codex-medium` (smallest eligible)

## Model Context Limits Reference

| Model | Context (tokens) | Recommended max_chars |
|-------|------------------|----------------------|
| SmolLM2-135M | 2,048 | 4,000 |
| SmolLM2-360M | 2,048 | 6,000 |
| GLM-4.7 | 32,768-128,768 | (no limit - fallback) |
| Claude Sonnet | 200,000 | 600,000 |
| GPT-5.x Codex | 272,000 | 800,000 |
