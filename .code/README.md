# Every Code Configuration

This directory contains the configuration for **Every Code** (`@just-every/code`), a unified
orchestration harness for AI agents. Every Code coordinates multiple AI CLIs (Claude, Gemini,
Coder, GLM) as sub-agents with configurable instructions and permissions.

## Directory Structure

```
.code/
├── config.toml              # GENERATED - do not edit directly
├── README.md                # This file
├── agents/                  # Agent instruction markdown files
│   └── <domain>/
│       └── <agent-name>.md
├── commands/                # Command instruction markdown files (orchestrator-level)
│   └── <command-name>.md
└── src/                     # SOURCE FILES - edit these
    ├── settings.toml        # Global settings (model, projects, trust)
    ├── agents.toml          # CLI agent definitions
    └── commands/            # Subagent command definitions
        └── <command-name>.toml
```

## Regenerating config.toml

The `config.toml` file is auto-generated from source files in `.code/src/`. Never edit it
directly.

```bash
# Regenerate after editing source files
uv run code-config

# Check if config is up-to-date (useful for CI)
uv run code-config --check
```

## Writing Settings

Edit `.code/src/settings.toml` for global configuration.

### Available Settings

```toml
# Default model for orchestration
model = "gpt-5.2"
model_reasoning_effort = "high"  # low, medium, high, xhigh

# Project-specific settings (key is the absolute project path)
[projects."/path/to/project"]
trust_level = "trusted"           # trusted, sandboxed
approval_policy = "on-request"    # auto, on-request, always
sandbox_mode = "workspace-write"  # read-only, workspace-write, full
```

### Example settings.toml

```toml
# Every Code Global Settings
model = "gpt-5.2"
model_reasoning_effort = "high"

[projects."/mnt/c/Users/xteam/IdeaProjects/ai-workflow"]
trust_level = "trusted"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
```

## Writing Agents

Edit `.code/src/agents.toml` to define CLI agents that can be used in commands.

### Agent Schema

```toml
[[agents]]
name = "agent-name"           # Unique identifier used in commands
command = "cli-command"       # The CLI executable to invoke
enabled = true                # Whether this agent is available
read_only = false             # Restrict to read-only operations
description = "What this agent does"
args = ["--flag1", "--flag2"] # Default CLI arguments
```

### Example agents.toml

```toml
# Every Code Agent Definitions

[[agents]]
name = "coder"
command = "coder"
enabled = true
read_only = false
description = "OpenAI Coder CLI with write access"
args = ["-s", "workspace-write", "-a", "never"]

[[agents]]
name = "coder-readonly"
command = "coder"
enabled = true
read_only = true
description = "OpenAI Coder CLI in read-only mode"
args = ["-s", "read-only"]

[[agents]]
name = "claude"
command = "claude"
enabled = true
read_only = false
description = "Claude Code CLI with write access"
args = ["--dangerously-skip-permissions"]

[[agents]]
name = "gemini"
command = "gemini"
enabled = true
read_only = false
description = "Google Gemini CLI"
args = ["-y"]

[[agents]]
name = "glm"
command = "glm"
enabled = true
read_only = true
description = "GLM 4.7 for context scribing and history summarization"
args = []
```

## Writing Commands

Commands are slash commands that orchestrate agents. Each command has two parts:

1. **Command definition** (`.code/src/commands/<name>.toml`) - Configuration and file references
2. **Instruction file** (`.code/agents/<domain>/<name>.md`) - Detailed instructions for the agent

### Command Schema

```toml
# .code/src/commands/my-command.toml

name = "my-command"                    # Slash command name (/my-command)
read_only = false                      # Whether command modifies files
agents = ["coder", "claude"]           # Which agents to use

# Reference instruction file (resolved from .code/ directory)
orchestrator_instructions_file = "agents/domain/my-command.md"

# Brief inline agent instructions (optional, appended after file contents)
agent_instructions = """
Brief instructions for sub-agents.
"""
```

### File Reference Resolution

The `orchestrator_instructions_file` and `agent_instructions_file` fields reference markdown
files relative to the `.code/` directory:

```
orchestrator_instructions_file = "agents/prd/chunk-refiner.md"
  → Resolves to: .code/agents/prd/chunk-refiner.md

orchestrator_instructions_file = "commands/update-prd.md"
  → Resolves to: .code/commands/update-prd.md
```

### Example Command

**Command definition** (`.code/src/commands/prd-chunk-refiner.toml`):

```toml
# PRD Chunk Refiner Command
# Splits raw chunks into focused sub-chunks with metadata annotations.

name = "prd-chunk-refiner"
read_only = false
agents = ["coder"]

# Load orchestrator instructions from markdown file
orchestrator_instructions_file = "agents/prd/chunk-refiner.md"

# Brief agent instructions (inline)
agent_instructions = """
Read the chunk file, analyze structure, split at conceptual boundaries.
Write original text to sub-chunk files (no modifications).
Write metadata to sidecar .meta.json files.
Output a manifest of created files.
"""
```

**Instruction file** (`.code/agents/prd/chunk-refiner.md`):

```markdown
# PRD Chunk Refiner Agent

Model: gpt-5.2 (reasoning: medium)

## Purpose

Refine raw chunks by:
1. Splitting into smaller, more focused sub-chunks
2. Adding context metadata (what type of content, likely PRD section)
3. Identifying boundaries between distinct concepts

**CRITICAL**: Never rewrite or modify the original text. Only split and annotate.

## Input Format
...

## Output Format
...
```

### Instruction File Conventions

When writing instruction markdown files:

1. **Start with model recommendation**: `Model: gpt-5.2 (reasoning: medium)`
2. **Define purpose clearly**: What the agent should accomplish
3. **Specify input/output formats**: Exact schemas and examples
4. **List rules and constraints**: What to do and what NOT to do
5. **Include anti-patterns**: Common mistakes to avoid

## Model Selection Guide

| Model | CLI | Best For |
|-------|-----|----------|
| Claude Opus | `claude` | Planning, composition, patterns, organization |
| Claude Sonnet | `claude` | Low-level execution, code generation |
| Gemini 2.5 Pro | `gemini` | Reasoning, logic, algorithm analysis |
| GPT-5.2 Medium | `coder` | Orchestration, coordination |
| Codex | `coder` | Auditing, review, text synthesis |
| GLM 4.7 | `glm` | Context scribing, history summarization |

## Running Python Tools

All Python scripts referenced in commands or documentation **must** use `uv run`. Never
use `python` or `python3` directly.

### In Bash Code Blocks

```bash
# Correct
uv run python -m scripts.prd.chunker "$input_file" --output-dir "$output_dir"

# Wrong - never do this
python -m scripts.prd.chunker "$input_file" --output-dir "$output_dir"
```

### In Inline Comments

```toml
# Edit this file, then run: uv run python -m scripts.everycode.generate_code_config
```

### Why?

* `uv run` manages the virtual environment and dependencies automatically
* Entry points defined in `pyproject.toml` only work via `uv run`
* Ensures consistency across all environments

## Workflow Summary

1. **Edit source files** in `.code/src/`
2. **Write instruction files** in `.code/agents/` or `.code/commands/`
3. **Regenerate config**: `uv run code-config`
4. **Use commands** via Every Code: `/my-command`

## Troubleshooting

### Config not updating
Run `uv run code-config` after any changes to source files.

### Command not found
Ensure the command name in the TOML matches what you're invoking.

### Instruction file not found
Check that `orchestrator_instructions_file` path is relative to `.code/` directory.

### Agent not available
Verify the agent is defined in `agents.toml` with `enabled = true`.
