# How To Add Models Correctly

Models are AI backend configurations stored in `.agents/models/` as TOML files. Each model
defines how to invoke an AI backend (Claude, GPT, Ollama, etc.) via command line.

## Directory Structure

```text
.agents/
├── models/          # Model configurations (TOML - how to invoke AI backends)
│   ├── claude-sonnet.toml
│   ├── claude-opus.toml
│   ├── opencode-glm.toml
│   ├── smollm2-135.toml
│   └── ...
└── agents/          # Agent configurations (Markdown - routing rules + instructions)
    └── router.md
```

## Model Configuration Format

Each model is a TOML file:

```toml
# Required: Command to execute the model
command = "claude"

# Optional: Arguments to pass to the command
args = ["-p", "--model", "sonnet", "--dangerously-skip-permissions"]

# Optional: How to pass the prompt - "stdin" (default) or "arg" (positional argument)
prompt_mode = "stdin"
```

## Adding a New Model

### Step 1: Identify the Command

Determine how to invoke your model from the command line:

| Backend | Command Example |
|---------|-----------------|
| Claude Code | `claude -p --model sonnet` |
| GLM via Z.AI | `glm -p` (uses `~/.claude-glm` config) |
| Ollama | `ollama run smollm2:135m` |
| OpenCode | `opencode -p -m factory:gpt-5.2-high` |

### Step 2: Create the TOML File

Create a new file in `.agents/models/`:

```bash
touch .agents/models/my-model.toml
```

### Step 3: Configure the Model

```toml
# .agents/models/my-model.toml
command = "ollama"
args = ["run", "my-model:latest"]
```

### Step 4: Test the Model

```bash
echo "Hello, world!" | ollama run my-model:latest
```

## Model Examples

### Claude via Claude Code

```toml
# .agents/models/claude-sonnet.toml
command = "claude"
args = ["-p", "--model", "sonnet", "--dangerously-skip-permissions"]
```

### GLM via Z.AI

```toml
# .agents/models/opencode-glm.toml
command = "glm"
args = ["-p", "--dangerously-skip-permissions"]
```

The `glm` command is a bash alias that runs Claude Code with a custom config directory
pointing to Z.AI's API endpoint with GLM models.

### SmolLM2 via Ollama

```toml
# .agents/models/smollm2-135.toml
command = "ollama-smollm2-135"
args = []
```

### GPT via OpenCode

```toml
# .agents/models/gpt-5.2-high.toml
command = "opencode"
args = ["-p", "-m", "factory:gpt-5.2-high", "--dangerously-skip-permissions"]
```

## Model Context Limits

When using models in agent routing rules, use these approximate character limits:

| Model | Context (tokens) | Recommended max_chars |
|-------|------------------|----------------------|
| SmolLM2-135M | 2,048 | 4,000 |
| SmolLM2-360M | 2,048 | 6,000 |
| GLM-4.7 | 32,768-128,768 | (no limit - fallback) |
| Claude Sonnet | 200,000 | 600,000 |
| GPT-5.x | 272,000 | 800,000 |

The `max_chars` value should be conservative (roughly 3-4 characters per token) to leave
room for model output. Omit `max_chars` for fallback models that should handle any size.

## Using Models in Agents

Models are referenced by name (filename without `.toml`) in agent routing rules:

```markdown
---
routing:
  - max_chars: 4000
    model: smollm2-135      # References .agents/models/smollm2-135.toml
  - model: opencode-glm     # References .agents/models/opencode-glm.toml
---
```

See [`docs/development/writing-agents.md`](writing-agents.md) for agent configuration details.
