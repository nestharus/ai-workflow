# AI Agent Entry Point

<coding_guidelines>

Welcome to the **Developing With AI 2.0** system—an automated, orchestrator-based AI
workflow system where agents act as specialized roles within workflows coordinated by
a central orchestrator service.

## What Is This Project?

This project implements an automated AI workflow system using a 5-role skeleton across
four domains: Product, UX, UI, and Technical. The system uses a FastAPI orchestrator
service to route messages to workflows and a separate webhook receiver service to handle
GitHub integration. The goal is to facilitate high-quality software development through
structured, automated collaboration.

For detailed information, see `docs/architecture/project-overview.md`.

## Documentation Modules

This repository organizes documentation into focused modules. Consult the relevant module
for detailed guidance on specific tasks.

| Module | Path | Description |
|--------|------|-------------|
| **Usage** | `docs/usage/` | Using the application |
| **Development** | `docs/development/` | Writing code, docstrings, FastAPI |
| **Testing** | `docs/testing/` | Writing and running test code |
| **Architecture** | `docs/architecture/` | Folder structure, services, endpoints |
| **Processes** | `docs/processes/` | Git releases, code reviews, protocols |

## Code Coverage

Test coverage is enforced separately for each test tier using `uv run test-coverage`.

### Test Tiers

| Tier | Test Path | Coverage Type | Target |
|------|-----------|---------------|--------|
| **unit** | `tests/unit/` | 80% line/branch per function | All `app/` functions |
| **component** | `tests/unit/` | 80% line/branch per function | `app/services/` only |
| **integration** | `tests/integration/` | 100% use-case | Use cases from YAML |
| **scripts** | `scripts/tests/` | 80% line/branch per function | `scripts/`, `tools/` |

### Coverage Rules

* **Per-function**: Each function must individually meet the 80% threshold (not averaged)
* **Class fields excluded**: Pydantic model type annotations are excluded from coverage
* **Service layer**: Component tests only validate functions within `app/services/`
* **Use-case coverage**: Integration requires 100% coverage of use cases
* **Private functions**: Unit tests validate all functions; component/scripts skip private

### Validation Commands

```bash
# Run all test tiers (test credentials auto-configured by pytest)
uv run test-coverage

# Run specific tier
uv run test-coverage --tier unit
uv run test-coverage --tier integration

# Custom thresholds
uv run test-coverage --min-line 90 --min-branch 85

# Report only (no validation)
uv run test-coverage --no-validate

# Legacy pytest-cov commands still work
uv run pytest --cov
uv run pytest --cov --cov-report=html
```

**Output**: Test coverage data is written to `.coverage/coverage.db` SQLite database,
which contains per-function coverage statistics, use-case coverage, test results, and
detailed missing line/branch information. Analysis tools (`coverage-summary`,
`coverage-files`, `coverage-file`, `coverage-functions`) read from this database.

## Linting

Use the `lint-fixer` sub-agent to fix lint errors.

**For workflows and commands** (update-pr, execute-plan, etc.), use changed-only mode:

```python
Task(subagent_type="lint-fixer", prompt="--changed-only")
```

**For full project linting**, use the `/lint-fix` slash command (does NOT use changed-only mode).

For docstring linter errors, see `docs/development/python/python.docstrings-guide.yml`.

## Code Review

Automated code reviews are performed using CodeRabbit and SonarQube.

### CodeRabbit

Automated CodeRabbit review wrapper (adds `--prompt-only` automatically). Agents must not
run this command; a human must run it, and the agent will fetch the latest artifact
afterward.

* **Human-run command**: `uv run review.coderabbit -- [--base <branch> | --type <mode> |
  --base-commit <sha>] [extra coderabbit args]` (defaults to `--base main` when no target
  flag is provided)
* **Selection rule**: Choose exactly one of `--base`, `--type`, or `--base-commit`;
  do not combine
* **Purpose**: Provides AI-driven feedback on work-in-progress code before it is committed
* **Agent retrieval**: After the human run, the agent will fetch the newest artifact via
  `uv run review.latest --type coderabbit` (prints the newest
  `.review/*.review.coderabbit` path)
* **Timeout guidance**: Allow up to 2 hours for this command; do not stop it early when
  invoked via `uv run`

### SonarQube

Runs SonarQube analysis using a Docker-based wrapper with caching enabled. Agents must
not run this command; a human must run it, and the agent will fetch the latest artifact
afterward.

* **Usage**: `./scripts/sonar_scan.sh [OPTIONS]`
* **Options**:
  * `-t, --token`: Authentication token (overrides `SONAR_TOKEN` env var)
  * `-u, --url`: SonarQube server URL (default: `http://localhost:9000`)
  * `--`: Arguments after this flag are passed directly to `sonar-scanner-cli`
* **Environment Variables**: `SONAR_TOKEN`, `SONAR_HOST_URL`
* **Human-run wrapper**: `uv run review.sonar -- [sonar_scan args]`
* **Agent retrieval**: After the human run, the agent will fetch the newest artifact via
  `uv run review.latest --type sonar` (prints the newest `.review/*.review.sonar` path)
* **Log output**: Wrapper writes to `.review/<timestamp>.review.sonar` and echoes the path
* **Timeout guidance**: Allow up to 2 hours for this command; do not stop it early when
  invoked via `uv run`

## Generating OpenAPI Schema

Generates the OpenAPI 3.1 schema JSON file from the FastAPI application code.

* **Usage**: `uv run app.api.generate`
* **Output**: Saves to `openapi/openapi.json`
* **Note**: This script must be run before `lint` or security scans to ensure the schema
  is up-to-date
* **Timeout guidance**: Allow up to 2 hours for this command; do not stop it early when
  invoked via `uv run`

## Sub-agents

This project has two distinct agent systems with strict call-boundary rules.

### Call-Boundary Invariant

**IMPORTANT**: The `.tasks` orchestration system (including `apply_plan` and all
scripts under `scripts/tasks/workflows/`) must ONLY dispatch to agents defined in
`.tasks/agents/`. These workflows must NOT invoke `.claude/agents/` agents directly.
This separation ensures that orchestration agents have consistent behavior and can
be tested independently.

### Claude Code Sub-agents (Manual Use Only)

These agents are defined in `.claude/agents/` and can be invoked manually via the
Task tool during interactive Claude Code sessions. They are NOT called
programmatically from `.tasks` orchestration workflows.

**Important**: Most sub-agents contain their own instructions. Pass an empty
string (`""`) for the prompt parameter unless otherwise specified below.

#### lint-fixer

Resolves and fixes lint errors iteratively until all issues pass.

* **Invocation**: `Task(subagent_type="lint-fixer", prompt="<args>")`
* **Arguments**:
  * `--worktree <path>`: Run linting from a specific git worktree directory
  * `--changed-only`: Only lint files that have been changed (uncommitted or last commit)
* **Use cases**:
  * Workflow use (recommended): `Task(subagent_type="lint-fixer", prompt="--changed-only")`
  * With worktree: `Task(subagent_type="lint-fixer", prompt="--worktree .worktrees/NES-123-add-feature --changed-only")`
  * Full lint (via `/lint-fix` command only): `Task(subagent_type="lint-fixer", prompt="")`

#### test-fixer

Runs all tests, debugs failures, and ensures coverage requirements are met.

* **Invocation**: `Task(subagent_type="test-fixer", prompt="")`
* **Prompt**: `""` (empty string required)
* **Use case**: Manual invocation when you need to debug test failures interactively
* **Note**: This agent is for direct manual use only; `.tasks` workflows use the
  separate `test-debugger` agent in `.tasks/agents/` for programmatic test debugging

#### knowledge-analyzer

Analyzes YAML documentation items with chunking and multi-dimensional classification.

* **Invocation**: `Task(subagent_type="knowledge-analyzer", prompt="")`
* **Prompt**: `""` (empty string required)
* **Use case**: Manual invocation for documentation analysis tasks

### Tasks Orchestration Agents

These agents are defined in `.tasks/agents/` and are called programmatically by
the `.tasks` orchestration system. They follow a different frontmatter format and
are managed separately from Claude Code sub-agents.

Key orchestration agents include:

* `implementor` - Implements tasks from plan files
* `test-debugger` - Debugs failing tests reported by implementor
* `task-patcher` - Updates task files when source plan changes
* `implementation-analyzer` - Analyzes implementation failures

See `.tasks/agents/` for the full list. These agents are invoked via
`_run_tasks_agent()` in the orchestration code and should not be called directly
via the Task tool.

### Creating New Sub-agents

Claude Code sub-agents are Markdown files with YAML frontmatter in `.claude/agents/`:

```markdown
---
name: my-agent
description: Short description of what this agent does
model: haiku
tools: Read, Edit, Bash, Grep, Glob
---

System prompt instructions for the agent...
```

Tasks orchestration agents use a different format in `.tasks/agents/` - see existing
agents in that directory for the schema.

## Plan Execution Guidelines

When executing tasks from implementation plans (files in `docs/plans/`), agents must
follow these strict rules to ensure complete and consistent implementation.

### No Deferred Stubs Without Plan Authorization

**CRITICAL**: Do NOT create placeholder stubs, TODO comments, or deferred implementations
unless the plan explicitly indicates the item is planned for a later task.

* **Before creating a stub**: Check if the functionality is specified in the current task
* **If specified in current task**: Implement it fully, even if it requires more effort
* **If specified in a later task**: Note that in a comment with the task reference
* **If implementation is blocked**: Document what is blocking and what is needed to proceed

Bad example (unauthorized stub):

```python
def resolve_entity(entity_mention: str) -> str:
    # TODO: Integrate with variant_resolver
    return entity_mention  # Placeholder
```

Good example (plan-authorized deferral):

```python
def resolve_entity(entity_mention: str) -> str:
    # Entity resolution rules are in Task 9 (fact_redesign_plan.md lines 172-189)
    # This task (Task 6) uses pass-through until Task 9 is implemented
    return entity_mention
```

### Task Decomposition for Complex Plans

For plans with many requirements, the primary agent should:

1. **Save the plan to `.tmp/`**: Split the plan into numbered task files
2. **Delegate to sub-agents**: Use the `Task` tool with `subagent_type="general-purpose"`
   to delegate individual tasks
3. **Review each completion**: After each sub-agent returns, verify the task was fully
   implemented before proceeding to the next task
4. **Track incomplete items**: If a sub-agent reports blockers, record them and either
   resolve them before continuing or escalate to the user

Example workflow:

```text
1. Read docs/plans/my_feature_plan.md
2. Write task files:
   - .tmp/my_feature/task_1.md
   - .tmp/my_feature/task_2.md
   - .tmp/my_feature/task_3.md
3. Delegate Task 1 to sub-agent
4. Review sub-agent output for Task 1
5. Delegate Task 2 to sub-agent
6. ...
```

### Reporting Incomplete Implementation

If implementation cannot be completed, you MUST report:

* What was completed
* What could NOT be completed
* WHY it could not be completed (missing dependency, unclear requirement, etc.)
* What is needed to complete it

Do NOT silently skip requirements or create stubs without explicit acknowledgment.

## External Resources

When stuck on implementation details, library usage, or unfamiliar patterns, use the
Firecrawl MCP tools to search the web for documentation and examples:

* **Search**: `mcp__firecrawl__firecrawl_search` - Search for documentation, Stack Overflow
  answers, or best practices
* **Scrape**: `mcp__firecrawl__firecrawl_scrape` - Fetch and read specific documentation pages

Examples of when to use Firecrawl:

* Unfamiliar with pyfakefs test patterns? Search for "pyfakefs modules_to_reload pytest"
* Need FastAPI middleware examples? Search for "FastAPI middleware authentication 2025"
* Library API unclear? Scrape the official documentation page

## Git Commit Signing

All commits are automatically GPG-signed using the configured signing key. This is required
by the repository's branch protection rules.

**Current configuration** (already set globally):

```bash
git config --global user.signingkey 2AAAEEBD97F32BFE
git config --global commit.gpgsign true
```

**Key location**: `~/.gnupg/` (RSA 4096-bit, no passphrase)

**GitHub verification**: The public key must be added to GitHub at
[https://github.com/settings/keys](https://github.com/settings/keys) for signatures to show as "Verified".

To export the public key:

```bash
gpg --armor --export contact@nestharus.com
```

## Git Commit Authorship

When creating git commits, agents must NOT add themselves as authors or co-authors:

* **No Co-Authored-By**: Do not add `Co-Authored-By: Claude <noreply@anthropic.com>` or
  similar lines
* **No Generated-By footers**: Do not add `🤖 Generated with [Claude Code]` or similar
  attribution footers
* **Use configured identity only**: All commits must use only the git username and email
  configured in the repository (from `git config user.name` and `git config user.email`)

The human user is the author of all commits. The agent is a tool assisting the user, not
a co-author.

**Why this matters**: Each unique author in a GitHub repository costs $30/month for a
seat. Adding Claude as a co-author would waste money on a seat for an AI that doesn't
need repository access.

## Git Branch Naming for Linear Integration

When creating branches for Linear tickets, the ticket ID casing must be preserved exactly:

* **Correct**: `NES-47-rest-to-mcp-bridge` (ticket ID `NES-47` keeps uppercase)
* **Wrong**: `nes-47-rest-to-mcp-bridge` (lowercase breaks automatic linking)

Linear automatically links branches and PRs to tickets when the ticket ID appears in the
branch name with correct casing. Using lowercase will break this automatic linking and
require manual attachment.

**Branch format**: `<TICKET-ID>-<description>` where:

* `<TICKET-ID>` preserves exact casing from Linear (e.g., `NES-47`, `PROJ-123`)
* `<description>` is lowercase with hyphens, derived from ticket title
* Total length should not exceed 50 characters

</coding_guidelines>
