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

### 1.4 Configuration layers and precedence (normative)

This system loads configuration from multiple layers.

Config files are TOML:

- **User-global (installation)**: `~/.workflow/config.toml`
- **Repo machine-local (repo binding)**: `~/.workflow/repos/<repo_uid>/config.toml`
- **Repo shared (optional, committed)**: `<repo_root>/.workflow/config.toml`

Precedence (highest wins):
1. CLI flags
2. Repo machine-local (repo binding)
3. Repo shared (project)
4. User-global (installation)
5. Built-in defaults

Note: This precedence differs from workflow and agent precedence (Integration §7.1, Configuration §6.1). See Core Infrastructure §11.2.1 for rationale.

Notes:
- Workflow and agent file precedence are separate (see “Workflow locations and precedence” and “Agent file locations”).
- Model routing override precedence is defined in Core Infrastructure §11.4.2.
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
| Cursor | (IDE-managed; not specified) |
| Windsurf | (IDE-managed; not specified) |

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
| Cursor | (IDE-managed; not specified) | (IDE-managed; not specified) |

Project-level skill can override or extend the user-global one.

### 3.4 Skill file structure (Claude Code example)

`.claude/skills/workflow-manager.md`:

```markdown
---
description: Manage workflows, agents, and configuration for the workflow engine
---

# Workflow Manager

You are an expert at working with the workflow engine (`workflowctl` + WSS + filesystem queues + jj-backed Patch-Stream).
Use **evidence-first** reasoning: prefer WSS documents and Logs Store events over assumptions.

## Quick commands

- `workflowctl doctor` — verify dependencies and repo compatibility
- `workflowctl init` — initialize the repo binding under `~/.workflow/repos/<repo_uid>/`
- `workflowctl run --workflow <workflow_id_or_path>` — run a workflow
- `workflowctl notifications tail` — watch notifications
- `workflowctl recover` — WAJ + queue recovery
- `workflowctl fsck` — integrity checks

## Where state lives (paths)

Default `WORKFLOW_HOME`: `~/.workflow`

Repo binding root:
- `~/.workflow/repos/<repo_uid>/`
  - `config.toml` (machine-local overrides)
  - `repo.json` (repo_uid + repo_root)
  - `workspace/` (**WSS root**; durable JSON/YAML artifacts)
  - `logs/` (append-only JSONL shards; one per writer)
  - `notifications/` and `control_actions/` (maildir-like queues)
  - `sandboxes/` (ephemeral jj workspaces for tool execution)

## Terminology (WSS and sandbox)

- **WSS**: the durable store in `.../workspace/`
- **Sandbox**: an ephemeral environment for tool execution (implemented as a **jj workspace**)
- **jj workspace**: jj’s working copy concept; use this term only when referencing jj CLI commands

## ID conventions

Semantic IDs (human strings):
- `project_id`, `ticket_id`, `task_id`, `step_id`
- `workflow_id` (workflow definition ID, e.g. `task_decompose_v1`)
- `agent_id` (agent definition ID, e.g. `approval_agent_v1`)

Generated IDs (ULID):
- `run_id`, `step_execution_id`, `writer_id`
- `request_id`, `notification_id`, `journal_id`, `op_id`, `bundle_id`

## Configuration layers and precedence

TOML config files:

- User-global: `~/.workflow/config.toml`
- Repo machine-local: `~/.workflow/repos/<repo_uid>/config.toml`
- Repo shared (optional, committed): `<repo_root>/.workflow/config.toml`

Precedence (highest wins):
1) CLI flags
2) Repo machine-local
3) Repo shared
4) User-global
5) Built-in defaults

## Workflow locations and precedence

Workflow search order (highest wins):
1) CLI file override: `--workflow-file <path>`
2) Project-scoped WSS: `workspace/projects/<project_id>/workflows/*.yaml`
3) Repo-shared (committable): `<repo_root>/.workflow/workflows/`
4) Repo machine-local (WSS): `workspace/workflows/*.yaml`
5) Built-ins: packaged with `workflowctl`

Note: Repo-shared (3) takes precedence over machine-local (4) because workflows are collaboration artifacts. Machine-local overrides should use `--workflow-file` (1).

Agent prompt search order (highest wins):
1) CLI flag: `--agent <path>`
2) Project: `<repo>/.workflow/agents/`
3) Repo machine-local: `~/.workflow/repos/<repo_uid>/agents/`
4) Global personal agents: `~/.workflow/agents/`
5) Built-ins: packaged with `workflowctl`

Note: Like workflows, agents favor repo-shared (2) over machine-local (3) for collaboration.

## Workflow runner semantics (v1)

- Steps form a DAG via `depends_on`.
- v1 runner is **single-threaded** and chooses the next ready step by **file order**.
- `on_failure` modes:
  - `stop`, `pause`, `investigate`, `continue` (see Integration §7.2.9).
- Step IO:
  - Step inputs are materialized from `with:` expressions.
  - Step outputs are stored in the step execution doc (`.../steps/<step_execution_id>.json`) as a bounded JSON object.

## Inputs schema subset

Workflows define `inputs` using a small JSON-schema-like subset (Integration §7.2.6).
When inputs are missing, `workflowctl` may prompt. Validation failures return `E_VALIDATION_FAILED`.

## Gateway tool contract (`workflow_engine`)

The workflow engine exposes a single gateway tool (`workflow_engine`) with subcommands like:
- `hydrate`, `sandbox_run`, `apply_patch`, `export_stack`, `queue_*`, `wss_*`

Responses use a standard envelope:
- success: `{ "ok": true, ... }`
- failure: `{ "ok": false, "error": { "error_id": "...", "code": "E_...", ... } }`

Error codes and event types are defined in Core Infrastructure §8.2.

## Troubleshooting playbooks (actionable)

### Journal recovery: `journal_abandoned`
1. Open the notification and note `op_id` and paths.
2. Run `workflowctl recover`.
3. If `expected_rev` mismatch is reported, do not overwrite; request user decision.

### Sparse sandbox missing files
- If the tool fails with missing files:
  - allow sparse expansion (`x_allow_sparse_expand: true`) OR
  - fallback to `sparse_mode: full` for that step
- Evidence: sandbox manifest + tool stderr in the step logs.

### Rebase conflicts
- Inspect the evidence bundle under:
  - `workspace/runs/<run_id>/artifacts/rebase/<bundle_id>/`
- Prefer conflict resolution records stored under:
  - `workspace/tickets/<ticket_id>/rebase/conflicts/`

## Minimal workflow example

~~~yaml
schema_version: 1
workflow_id: task_decompose_v1
description: "Decompose a task into concrete steps."

inputs:
  type: object
  additionalProperties: false
  required: [task_text]
  properties:
    task_text:
      type: string
      description: "The user request to decompose into steps."

steps:
  - step_id: plan
    kind: agent
    agent_id: task_decomposer_v1
    with:
      task_text: ${{ inputs.task_text }}
    on_failure: { mode: investigate }
~~~


## Minimal agent prompt example

~~~markdown
# task_decomposer_v1

Goal: convert `task_text` into a step plan.

Constraints:
- steps must be small, testable, and file-scoped
- produce YAML with `step_id`, `kind`, `depends_on`, and `with` inputs
~~~


### Validation and debugging

Recommended practices:

- Validate workflow YAML before execution (schema + DAG):
  - `workflowctl workflow validate <path>`
- Keep workflows deterministic:
  - avoid hidden environment coupling (prefer explicit inputs)
- Use `gate` steps when user decisions are required (no silent auto-selection).



## 5) Writing Agent Prompts

Agent prompts are Markdown files that define:
- purpose and constraints
- required inputs (typed)
- required outputs (typed)
- tool access (capabilities)

They are referenced from workflows via `entrypoint: agent:<name>` or `file:<repo_relative_path>` (Integration §7.2.3).

**See Also**: `Tech_Plan__Agent_Prompt_Definitions.md` for complete definitions of all built-in agents used by workflow engine v3.

### Prompt file format (v1)

An agent prompt is a Markdown document with optional YAML front matter.

#### YAML front matter (recommended)

```yaml
---
schema_version: 1
agent_id: step_patch_author_v1
display_name: Step patch author
description: Produce a unified diff for a single planned step.
capabilities_required: ["patch_write"]
tools_allowed: ["workflow_engine"]   # optional; default []
input_schema:
  type: object
  additionalProperties: false
  properties:
    context: { type: object }
    hydration: { type: object }
  required: ["context","hydration"]
output_schema:
  type: object
  additionalProperties: false
  properties:
    patch: { type: string, description: "Unified diff" }
    summary: { type: string }
  required: ["patch","summary"]
---
```

Rules:

- `schema_version` MUST be `1` for v1 prompts.
- `agent_id` MUST be unique within its resolution scope.
- `input_schema` and `output_schema` use the same restricted schema subset as workflow inputs (Integration §7.2.6).

#### Markdown body

The body is free-form Markdown and should include:

- What the agent must do
- Hard constraints (scope limits, formatting rules)
- Output format instructions (see below)

### Input passing model

At runtime, the runner invokes an LLM with:

- **system prompt**: the agent prompt Markdown (including front matter)
- **user message**: a JSON object containing the runtime input value

The runner MUST also attach (or inline) any hydrated file slices needed for the task.

The durable input is always stored as:

- `workspace/runs/<run_id>/artifacts/steps/<step_execution_id>/agent_input.json`

### Output capture model

The agent MUST emit a single JSON object in the **first** fenced code block labeled `json`:

```json
{
  "patch": "diff --git ...\n...",
  "summary": "What changed and why"
}
```

Rules:

- The runner parses the first ```json``` block.
- The parsed object MUST validate against `output_schema`.
- If parsing or validation fails, the step fails loudly and follows `on_failure`.

For patch-authoring agents, `patch` MUST be a unified diff.

### Tool access

By default, agents have **no tool access**.

Tool access is granted only when:

- the workflow step declares required capabilities, and
- the agent prompt front matter allows the tool (`tools_allowed`), and
- the repo trust policy allows it (Integration §7.3)



## 6) Agent file locations

### 6.1 Precedence

Agent prompts follow the same precedence as skills:

1. **CLI flag**: `--agent <path>`
2. **Project**: `<repo>/.workflow/agents/<name>.md`
3. **Repo machine-local**: `~/.workflow/repos/<repo_uid>/agents/<name>.md`
4. **Installation**: `~/.workflow/agents/<name>.md`
5. **Built-in**: packaged with `workflowctl`

Note: Agent precedence follows the same collaborative-first pattern as workflows (Integration §7.1): project-level (2) takes precedence over machine-local (3). This differs from config precedence (Core Infrastructure §11.2) because agents, like workflows, are collaboration artifacts.

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
