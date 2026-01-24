# Tech Plan: Configuration & Onboarding

- **Doc**: Tech_Plan__Configuration_&_Onboarding.md
- **Updated**: 2026-01-24
- **Component**: Configuration agent + CLI integration + Skills system
- **Primary responsibility**: Help users configure the workflow engine, manage models, and integrate with their preferred AI coding tools—without polluting the project.

## 0) Scope and cross-references

This document owns:
- **Onboarding flow** (`workflowctl init` behavior)
- **Skill deployment** (deploying skills into user's AI coding CLI)
- **Command shim installation** (how commands get into user's AI coding tool)
- **Model provider configuration** (API keys, routing)

This document defers to:
- **Core Infrastructure §2**: Runtime root layout (`~/.workflow/` structure)
- **Core Infrastructure §11**: Config format (TOML), precedence rules, schema
- **Core Infrastructure §12**: Secrets storage (OS keychain)
- **Integration §3**: Distribution modes (binary, bootstrap script, Python package)

**Important distinction**: Skills are a feature of AI coding CLIs (Claude Code, OpenCode, etc.), not a system we create. We deploy skills INTO those CLIs.

## 1) Design philosophy

### 1.1 Installation vs Project separation

| Layer | Location | Purpose | Committed |
|-------|----------|---------|-----------|
| **Installation** | `~/.workflow/` | User's machine-local config, skills, agents, workflows | No |
| **Repo binding** | `~/.workflow/repos/<repo_uid>/` | Per-repo machine-local state | No |
| **Project** | `<repo>/.workflow/` | Project-specific overrides (optional, team-shared) | Yes (optional) |

**Key principle**: Installation provides defaults. Project overrides when needed. Zero project pollution by default.

### 1.2 Zero project pollution by default

`workflowctl init` writes NOTHING to the repo by default:
- All state goes to `~/.workflow/repos/<repo_uid>/`
- Project-level files (`<repo>/.workflow/`) require explicit `--project` flag
- Users can commit project config for team sharing, but it's opt-in

### 1.3 One skill to teach the agent

Skills are a feature of AI coding CLIs (Claude Code, OpenCode, etc.). We deploy ONE skill (`workflow-manager`) that teaches the **agent** how to work with the workflow engine:
- When users ask "write me a workflow" or "configure this", the agent knows how
- Single skill file deployed to the CLI's skill location (e.g., `.claude/skills/workflow-manager.md`)
- Small footprint, comprehensive knowledge
- Agent can write workflows, agents, configure models, run commands—all from one skill

## 2) Onboarding flow

### 2.1 Entry point

```bash
workflowctl init [--project]
```

### 2.2 Self-bootstrapping flow

`workflowctl init` is self-bootstrapping: it asks the user which CLI they use, then launches that CLI with a prompt that installs the skill first—so the agent immediately knows how to do everything else.

**Flow:**
```
┌─────────────────────────────────────────────────────────────┐
│  workflowctl init                                           │
├─────────────────────────────────────────────────────────────┤
│  1. Check/create ~/.workflow/ and ~/.workflow/repos/<uid>/  │
│                                                             │
│  2. Ask user: "Which CLI do you use?"                       │
│     [1] Claude Code                                         │
│     [2] OpenCode                                            │
│     [3] Cursor                                              │
│     [4] Windsurf                                            │
│     [5] Other                                               │
│                                                             │
│  3. User selects (e.g., "1" for Claude Code)                │
│                                                             │
│  4. init executes the CLI with bootstrap prompt:            │
│     claude "First run: workflowctl install --cli claude-code│
│     to install the workflow-manager skill. Then use that    │
│     skill to configure the workflow engine for this repo."  │
│                                                             │
│  5. Agent installs skill, now knows how to:                 │
│     - Configure model providers                             │
│     - Set up default workflows                              │
│     - Everything else the skill teaches                     │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 What `workflowctl init` does

1. **Check/create installation state**
   - Create `~/.workflow/` if missing
   - Create `~/.workflow/repos/<repo_uid>/` and `repo.json`

2. **Ask which CLI**
   - Interactive prompt: "Which CLI do you use?"
   - Store selection in config: `[cli] default = "claude-code"`

3. **Launch CLI with bootstrap prompt**
   - Execute the selected CLI (e.g., `claude`, `opencode`)
   - Pass a prompt that tells the agent to install the skill first
   - Agent self-bootstraps: installs skill, then uses it

4. **With `--project` flag**
   - Also create `<repo>/.workflow/` structure for team sharing

### 2.4 Bootstrap prompt (passed to CLI)

```text
First, run: workflowctl install --cli <cli-name>

This installs the workflow-manager skill. Once installed, use that skill
to help the user configure the workflow engine for this repository.
```

The agent:
1. Runs `workflowctl install --cli <name>`
2. Now has the `/workflow-manager` skill
3. Uses that skill's knowledge to configure everything else

### 2.5 CLI execution commands

| CLI | Command to launch |
|-----|-------------------|
| Claude Code | `claude "<prompt>"` |
| OpenCode | `opencode "<prompt>"` |
| Cursor | TBD |
| Windsurf | TBD |

## 3) Skill deployment

Skills are a feature of AI coding CLIs (Claude Code, OpenCode, etc.), not a system we build. We deploy ONE skill file into the user's CLI that teaches the **agent** how to work with the workflow engine.

### 3.1 Purpose of skills

Skills guide **agents**, not users. When a user says:
- "Write me a workflow that validates code"
- "Configure the workflow engine"
- "Create an agent for code review"

The agent knows how to do it because the skill taught it.

### 3.2 The workflow-manager skill

We deploy a single skill: **workflow-manager**

This skill contains all the knowledge an agent needs to:
- Configure the workflow engine
- Write workflows
- Write agent prompts
- Manage model providers
- Run workflows and agents

One skill, small footprint, comprehensive coverage.

### 3.3 Skill deployment locations (per CLI)

| CLI | User-global location | Project location |
|-----|---------------------|------------------|
| Claude Code | `~/.claude/skills/workflow-manager.md` | `<repo>/.claude/skills/workflow-manager.md` |
| OpenCode | `~/.opencode/skills/workflow-manager.md` | `<repo>/.opencode/skills/workflow-manager.md` |
| Cursor | TBD | TBD |

Project-level skill can override or extend the user-global one.

### 3.4 Skill file structure (Claude Code example)

`.claude/skills/workflow-manager.md`:

```markdown
---
description: Manage workflows, agents, and configuration for the workflow engine
---

# Workflow Manager

You are an expert at working with the workflow engine. When users ask you to write workflows, configure the system, or create agents, use this knowledge.

## Configuration

To configure the workflow engine:
- `workflowctl config show` - view current config
- `workflowctl config set <key> <value>` - set a value
- `workflowctl providers add <name>` - add a model provider (API key stored in OS keychain)

## Writing Workflows

Workflows are YAML files with this structure:
[... workflow schema and examples ...]

## Writing Agent Prompts

Agent prompts are markdown files:
[... agent format and examples ...]

## Running Workflows

- `workflowctl run --workflow <name>` - run a workflow
- `workflowctl agents run <name>` - run an agent

## Model Routing

[... model routing config ...]
```

### 3.5 Skill vs Command distinction

| Type | Example | Purpose |
|------|---------|---------|
| **Command** | `/project-manager`, `/ticket-manager` | Execute `workflowctl run <workflow>` |
| **Skill** | `/workflow-manager` | Teaches the agent how to work with the workflow engine |

Commands invoke specific workflows; the skill gives the agent comprehensive knowledge.

## 4) CLI integration

### 4.1 Supported CLIs

The configuration agent asks users which CLI they use. Supported options:
- Claude Code
- OpenCode
- Cursor
- Windsurf
- Generic (MCP-based)

### 4.2 Installation command

```bash
workflowctl install --cli <name> [--project]
```

Without `--project`: installs to user-global CLI location (e.g., `~/.claude/`)
With `--project`: installs to project CLI location (e.g., `<repo>/.claude/`)

This installs commands and the workflow-manager skill into the CLI's expected locations.

### 4.3 What gets installed

**Commands** (in CLI's commands directory):
- `/project-manager` → `workflowctl run project-manager`
- `/ticket-manager` → `workflowctl run ticket-manager`

**Skill** (in CLI's skills directory):
- `/workflow-manager` → teaches the agent how to configure, write workflows, write agents, manage models

### 4.4 CLI-specific locations

| CLI | Commands | Skills |
|-----|----------|--------|
| Claude Code | `~/.claude/commands/` | `~/.claude/skills/` |
| OpenCode | `~/.opencode/commands/` | `~/.opencode/skills/` |
| Cursor | TBD | TBD |
| Windsurf | TBD | TBD |

Project-level: same structure under `<repo>/` instead of `~/`.

### 4.5 Command format (Claude Code example)

`~/.claude/commands/project-manager.md`:
```markdown
---
description: Manage projects and tickets
---
Run: workflowctl run project-manager $ARGUMENTS
```

### 4.6 MCP server (generic integration)

For CLIs that support MCP but not native commands/skills:
```bash
workflowctl mcp-server start
# Exposes commands as MCP tools
```

## 5) Model provider configuration

### 5.1 Provider setup

Model providers are configured via the configuration agent or CLI:

```bash
# Add a provider (prompts for API key, stores in OS keychain)
workflowctl providers add anthropic
workflowctl providers add openai
workflowctl providers add google

# List configured providers
workflowctl providers list

# Test a provider
workflowctl providers test anthropic

# Remove a provider
workflowctl providers remove anthropic
```

### 5.2 API key storage

All API keys are stored in the OS keychain via Python `keyring` (see Core Infrastructure §12.1):

```
Service: workflow
Username: provider/<provider_name>
Password: <api_key>
```

### 5.3 Model routing

Default routing is configured in `~/.workflow/config.toml` (see Core Infrastructure §11.4):

```toml
[models]
default = "claude-sonnet"

[models.routing]
planning = "claude-opus"
implementation = "claude-sonnet"
validation = "chatgpt-5"
multimodal = "gemini-3"
```

Routing can be overridden per-workflow and per-step.

## 6) Agent file locations

### 6.1 Precedence

Agent prompts follow the same precedence as skills:

1. **CLI flag**: `--agent <path>`
2. **Project**: `<repo>/.workflow/agents/<name>.md`
3. **Repo machine-local**: `~/.workflow/repos/<repo_uid>/agents/<name>.md`
4. **Installation**: `~/.workflow/agents/<name>.md`
5. **Built-in**: packaged with `workflowctl`

### 6.2 Installation agents (not in project)

User-defined agent prompts live in the installation by default:
```
~/.workflow/agents/
  code-reviewer.md
  test-writer.md
  refactorer.md
```

### 6.3 Project agents (optional, committed)

When teams need shared agents, they use the `--project` flag:
```
<repo>/.workflow/agents/
  domain-expert.md
  api-designer.md
```

## 7) Commands summary

```bash
# Onboarding
workflowctl init [--interactive] [--project]
workflowctl doctor
workflowctl bootstrap

# Configuration
workflowctl config show [--explain]
workflowctl config set <key> <value>

# Providers (model API keys)
workflowctl providers list
workflowctl providers add <name>
workflowctl providers remove <name>
workflowctl providers test <name>

# CLI integration (installs commands + workflow-manager skill)
workflowctl install --cli <name> [--project]
workflowctl uninstall --cli <name> [--project]

# Agents (workflow engine agent prompts)
workflowctl agents list
workflowctl agents show <name>
workflowctl agents run <name> [--input <file>]
```

## 8) Integration with other tech plans

### 8.1 Additions to Runtime Root Layout (Core Infrastructure §2)

The following directories are added to the runtime root:

```text
~/.workflow/
  agents/                 # User-global agent prompts (for workflow engine)

  repos/<repo_uid>/
    agents/               # Repo machine-local agent prompts
```

Note: Skills are NOT in `~/.workflow/`. Skills are deployed into CLI-specific locations (e.g., `~/.claude/skills/`).

### 8.2 Additions to Config Schema (Core Infrastructure §11.4)

```toml
[cli]
default = ""              # Set by configuration agent: "claude-code"|"opencode"|"cursor"|"windsurf"|""
```

### 8.3 Updates to Repo Init (Integration §3.4)

`workflowctl init` is now self-bootstrapping:
- **Always**: Create `~/.workflow/repos/<repo_uid>/` and `repo.json`
- **Always**: Ask user which CLI they use
- **Always**: Launch that CLI with bootstrap prompt
- **Always**: Agent installs skill first, then uses it to configure
- **With --project**: Also create `<repo>/.workflow/` structure

## 9) Risk register

| Risk | Severity | Control(s) |
|------|----------|------------|
| Users confused by precedence | Medium | `workflowctl config show --explain` shows effective config with sources |
| CLI format changes | Low | Command/skill generation is templated; easy to update per-CLI |
| API keys not in keychain on headless systems | Medium | Fallback encrypted file store (Core §12.1) |
| Project pollution | Medium | Default is zero project files; `--project` required for any project writes |
| CLI skill location unknown | Low | Configuration agent asks user which CLI; explicit `workflowctl install` |
| Agent precedence conflicts | Low | Clear precedence; `workflowctl agents show --explain` shows which file is used |
