# How To Execute Agents Correctly

Agents are executed via `uv run agents`.

## Usage

```bash
# Execute agent with its configured model
uv run agents <agent_name> "<prompt>"

# Execute model directly (no agent frontmatter)
uv run agents --model <model_name> "<prompt>"

# Execute agent from arbitrary file path
uv run agents --agent-file <path/to/agent.md> "<prompt>"

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

# Execute agent from any location (not just .agents/agents/)
uv run agents --agent-file .claude/agents/workflow/exception-handler.md --file prompt.md

# Pipe prompt from file
cat prompt.txt | uv run agents my-agent
```

## CLI Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `agent` | No* | Agent name (filename without `.md` extension) |
| `prompt` | No** | Prompt to send |
| `--model`, `-m` | No* | Execute model directly instead of agent |
| `--agent-file`, `-a` | No* | Path to agent `.md` file (any location) |
| `--file`, `-f` | No** | Read prompt from file instead of argument |
| `--project`, `-p` | No | Project root directory (default: cwd) |

*One of `agent`, `--model`, or `--agent-file` is required.
**Prompt must be provided via argument, `--file`, or stdin.

## Output Visibility

When `uv run agents` is invoked from within a Claude Code session (via the
Bash tool), **stdout from the child process is not visible**. The process
runs and completes, but its output is swallowed by the parent session.

To verify what a child agent did:

* Have the agent write results to a file (e.g., `.tmp/output.md`)
* Check Claude session logs after execution
* Use `--file` to pass a prompt that instructs the agent to write output
  to a known path

This only affects Claude-backed models (`claude -p`). Models using other
CLI tools (codex2, opencode) may behave differently.

## GLM Prompt Structure Validation

The spec refinement agent runner logs prompt structure metrics for GLM agents. If a
GLM prompt does not front-load contract rules, a warning is emitted to help enforce
contract-first prompt structure.

## Listing Available Models

```bash
ls .agents/models/
```
