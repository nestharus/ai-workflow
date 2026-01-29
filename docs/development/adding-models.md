# How To Add Models Correctly

Models are AI backend configurations stored in `.agents/models/` as TOML files. Each model
defines how to invoke an AI backend (Claude, GPT, OpenCode, etc.) via command line.

## Directory Structure

```text
.agents/
├── models/          # Model configurations (TOML - how to invoke AI backends)
│   ├── claude-sonnet.toml
│   ├── claude-opus.toml
│   ├── opencode-glm.toml
│   └── ...
└── agents/          # Agent configurations (Markdown - model + instructions)
    └── implementor.md
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
| OpenCode | `opencode -p -m factory:gpt-5.2-high` |

### Step 2: Create the TOML File

Create a new file in `.agents/models/`:

```bash
touch .agents/models/my-model.toml
```

### Step 3: Configure the Model

```toml
# .agents/models/my-model.toml
command = "opencode"
args = ["-p", "-m", "factory:my-model", "--dangerously-skip-permissions"]
```

### Step 4: Test the Model

```bash
echo "Hello, world!" | opencode -p -m factory:my-model
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

### GPT via OpenCode

```toml
# .agents/models/gpt-5.2-high.toml
command = "opencode"
args = ["-p", "-m", "factory:gpt-5.2-high", "--dangerously-skip-permissions"]
```

## Using Models in Agents

Models are referenced by name (filename without `.toml`) in agent frontmatter:

```markdown
---
description: Implements code changes based on task files
model: gpt-5.2-high
---
```

See `docs/development/writing-agents.md` for agent configuration details.
