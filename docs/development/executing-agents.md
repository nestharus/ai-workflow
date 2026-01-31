# How To Execute Agents Correctly

Agents are executed via `uv run agents`.

## Usage

```bash
# Execute agent with its configured model
uv run agents <agent_name> "<prompt>"

# Execute model directly (no agent frontmatter)
uv run agents --model <model_name> "<prompt>"

# Execute with prompt from file
uv run agents <agent_name> --file <prompt_file>

# Execute with prompt from stdin
echo "<prompt>" | uv run agents <agent_name>
```

## Examples

```bash
# Execute agent with its configured model
uv run agents implementor task_001.md

# Execute model directly for general tasks
uv run agents --model claude-sonnet "Write a haiku"
uv run agents -m opencode-glm "Explain this code"

# Pipe prompt from file
cat prompt.txt | uv run agents my-agent
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

## GLM Prompt Structure Validation

The spec refinement agent runner logs prompt structure metrics for GLM agents. If a
GLM prompt does not front-load contract rules, a warning is emitted to help enforce
contract-first prompt structure.

## Listing Available Models

```bash
ls .agents/models/
```
