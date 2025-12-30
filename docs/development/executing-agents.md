# How To Execute Agents Correctly

Agents are executed via `uv run python -m scripts.agents`.

## Usage

```bash
# Execute agent with routing
uv run python -m scripts.agents <agent_name> "<prompt>"

# Execute model directly (no agent routing)
uv run python -m scripts.agents --model <model_name> "<prompt>"

# Execute with prompt from file
uv run python -m scripts.agents <agent_name> --file <prompt_file>

# Execute with prompt from stdin
echo "<prompt>" | uv run python -m scripts.agents <agent_name>
```

## Examples

```bash
# Execute agent with automatic model routing
uv run python -m scripts.agents implementor task_001.md

# Execute model directly for general tasks
uv run python -m scripts.agents --model claude-sonnet "Write a haiku"
uv run python -m scripts.agents -m opencode-glm "Explain this code"

# Pipe prompt from file
cat prompt.txt | uv run python -m scripts.agents my-agent
```

## CLI Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `agent` | No* | Agent name (filename without `.md` extension) |
| `prompt` | No** | Prompt to send |
| `--model`, `-m` | No* | Execute model directly instead of agent |
| `--file`, `-f` | No** | Read prompt from file instead of argument |
| `--project`, `-p` | No | Project root directory (default: cwd) |

*Either `agent` or `--model` is required.
**Prompt must be provided via argument, `--file`, or stdin.

## Listing Available Models

```bash
ls .agents/models/
```
