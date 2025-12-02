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
| **e2e** | `tests/e2e/` | 100% use-case | Use cases from YAML |
| **scripts** | `scripts/tests/` | 80% line/branch per function | `scripts/`, `tools/` |

### Coverage Rules

* **Per-function**: Each function must individually meet the 80% threshold (not averaged)
* **Class fields excluded**: Pydantic model type annotations are excluded from coverage
* **Service layer**: Component tests only validate functions within `app/services/`
* **Use-case coverage**: Integration/e2e require 100% coverage of non-future use cases
* **Private functions**: Unit tests validate all functions; component/scripts skip private

### Validation Commands

```bash
# Set required DB creds for settings validation
export SURREALDB_USER=root SURREALDB_PASS=root

# Run all test tiers
uv run test-coverage

# Run specific tier
uv run test-coverage --tier unit
uv run test-coverage --tier integration

# Custom thresholds
uv run test-coverage --min-line 90 --min-branch 85

# Report only (no validation)
uv run test-coverage --no-validate

# Generate JSON report
uv run test-coverage --json-report coverage_report.json

# Legacy pytest-cov commands still work
uv run pytest --cov
uv run pytest --cov --cov-report=html
```

## LLM Coverage Report

Generates an LLM-friendly JSON report combining code coverage gaps and use-case coverage
gaps for AI-assisted test generation.

* **Usage**: `uv run llm-coverage-report`
* **Prerequisites**:
  * `coverage.json`: Generate with `pytest --cov --cov-report=json`
  * `tests/docs/use_cases.yaml`: The canonical use-case registry
* **Output**: `coverage_llm.json` containing:
  * Code coverage gaps (missing lines/branches with context)
  * Use-case coverage gaps (uncovered use-cases)
  * Prompting notes for LLM consumption
* **Common Options**:
  * `--coverage-json PATH`: Specify coverage JSON path (default: `coverage.json`)
  * `--output PATH`: Specify output path (default: `coverage_llm.json`)
  * `--context-radius N`: Number of surrounding lines (default: 2)
  * `--use-cases PATH`: Path to use-case registry (default: `tests/docs/use_cases.yaml`)
* **Integration**: Used by the test-fixer sub-agent to identify coverage gaps

## Linting

Runs a comprehensive suite of static analysis and security tools.

* **Usage**: `uv run lint [LINTER ...]`
* **Arguments**: Specify one or more linter names to run only those linters. If no
  arguments are provided, all linters run in order.
* **Available Linters** (in execution order):
  1. `scripts`: Validates pyproject.toml script entry point naming conventions
  2. `markdown-restriction`: Enforces that only `./README.md` and `./AGENTS.md` are
     allowed as markdown files in root, app/**, docs/**, scripts/**, and tests/**
     directories. All other documentation must be in YAML format following the schema
     defined in `docs/development/general/general.yaml.schema-guidelines.yml`
  3. `ruff`: Auto-formats code (`ruff format .`) and fixes linting issues
     (`ruff check --fix .`)
  4. `mypy`: Type checking
  5. `hadolint`: Lints Dockerfiles
  6. `pymarkdown`: Validates Markdown files
  7. `yamllint`: Validates all `.yml` and `.yaml` files for syntax and style per the
     configuration in `.yamllint.yaml`
  8. `yamldocs`: Validates YAML documentation files (identified by `doc_id` at root)
     follow the schema defined in `general.yaml.schema-guidelines.yml`
  9. `checkov`: Scans the generated `openapi/openapi.json` against policies in
     `.checkov.yaml`
* **Examples**:
  * `uv run lint` - Run all linters
  * `uv run lint ruff` - Run only ruff (format and check)
  * `uv run lint mypy yamllint` - Run mypy and yamllint
  * `uv run lint markdown-restriction` - Run only markdown restriction linter
* **Prerequisite**: Run `uv run app.api.generate` first to generate the schema for Checkov
* **Timeout guidance**: Allow up to 2 hours for this command; do not stop it early when
  invoked via `uv run`
* **Markdown lint expectation**: The lint job runs `pymarkdown` with the repo config
  `.pymarkdown.json` and excludes listed paths in `scripts/lint.py`. When it flags
  documentation, adjust the doc text (e.g., wrap long lines, align bullet markers) to
  satisfy the reported rules; do not silence rules or change the lint configuration.
  Rerun `uv run lint` until it passes.
* **TCH003 handling**: Reintroduce `TYPE_CHECKING` gates where runtime inspection is not
  needed. For files that feed runtime type introspection (e.g., `app/contracts/**`,
  `app/schemas/**`), keep imports loaded at runtime and rely on the scoped TCH003 ignore
  already configured.

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

This project includes specialized Claude sub-agents for automated task delegation.
Sub-agents are defined in `.claude/agents/` and can be invoked via the Task tool.

**Important**: All sub-agents contain their own instructions. Always pass an empty string
(`""`) for the prompt parameter to avoid overriding their built-in workflows.

### lint-fixer

Resolves and fixes lint errors iteratively until all issues pass.

* **Invocation**: `Task(subagent_type="lint-fixer", prompt="")`
* **Prompt**: `""` (empty string required)

### test-fixer

Runs all tests, debugs failures, and ensures coverage requirements are met.

* **Invocation**: `Task(subagent_type="test-fixer", prompt="")`
* **Prompt**: `""` (empty string required)

### knowledge-analyzer

Analyzes YAML documentation items with chunking and multi-dimensional classification.

* **Invocation**: `Task(subagent_type="knowledge-analyzer", prompt="")`
* **Prompt**: `""` (empty string required)

### Creating New Sub-agents

Sub-agents are Markdown files with YAML frontmatter in `.claude/agents/`:

```markdown
---
name: my-agent
description: Short description of what this agent does
model: haiku
tools: Read, Edit, Bash, Grep, Glob
---

System prompt instructions for the agent...
```

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

</coding_guidelines>
