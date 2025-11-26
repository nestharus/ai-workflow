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

Test coverage is enforced via `pytest-cov` with configuration in `pyproject.toml`.

* **Threshold**: Minimum 80% coverage required (`fail_under = 80`)
* **Tracked Sources**: `app/`, `scripts/`, `tools/`
* **Omitted Paths**: Tests, caches, site-packages, and virtual environments
* **Excluded Lines**: Standard non-executable patterns plus `if TYPE_CHECKING:`,
  `class .*Protocol\):`, and abstract methods

**Validation Commands**:

```bash
# Set required DB creds for settings validation
export SURREALDB_USER=root SURREALDB_PASS=root

# Check coverage in terminal
uv run pytest --cov

# Generate HTML report
uv run pytest --cov --cov-report=html

# Show missing lines
uv run pytest --cov --cov-report=term-missing
```

## Linting

Runs a comprehensive suite of static analysis and security tools.

* **Usage**: `uv run lint`
* **Operations Performed**:
  1. `ruff format .`: Auto-formats code
  2. `ruff check --fix .`: Fixes linting issues
  3. `mypy`: Type checking
  4. `hadolint`: Lints Dockerfiles
  5. `pymarkdown`: Validates Markdown files
  6. `validate-toon`: Validates all `.toon` files for syntax and structural correctness
     per the TOON specification
  7. `checkov`: Scans the generated `openapi/openapi.json` against policies in
     `.checkov.yaml`
* **Prerequisite**: Run `uv run gen_openapi` first to generate the schema for Checkov
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

For docstring linter errors, see `docs/development/docstrings-guide.md`.

## Code Review

Automated code reviews are performed using CodeRabbit and SonarQube.

### CodeRabbit

Automated CodeRabbit review wrapper (adds `--prompt-only` automatically). Agents must not
run this command; a human must run it, and the agent will fetch the latest artifact
afterward.

* **Human-run command**: `uv run coderabbit-review -- [--base <branch> | --type <mode> |
  --base-commit <sha>] [extra coderabbit args]` (defaults to `--base main` when no target
  flag is provided)
* **Selection rule**: Choose exactly one of `--base`, `--type`, or `--base-commit`;
  do not combine
* **Purpose**: Provides AI-driven feedback on work-in-progress code before it is committed
* **Agent retrieval**: After the human run, the agent will fetch the newest artifact via
  `uv run latest-review --type coderabbit` (prints the newest
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
* **Human-run wrapper**: `uv run sonar-review -- [sonar_scan args]`
* **Agent retrieval**: After the human run, the agent will fetch the newest artifact via
  `uv run latest-review --type sonar` (prints the newest `.review/*.review.sonar` path)
* **Log output**: Wrapper writes to `.review/<timestamp>.review.sonar` and echoes the path
* **Timeout guidance**: Allow up to 2 hours for this command; do not stop it early when
  invoked via `uv run`

## Generating OpenAPI Schema

Generates the OpenAPI 3.1 schema JSON file from the FastAPI application code.

* **Usage**: `uv run gen_openapi`
* **Output**: Saves to `openapi/openapi.json`
* **Note**: This script must be run before `lint` or security scans to ensure the schema
  is up-to-date
* **Timeout guidance**: Allow up to 2 hours for this command; do not stop it early when
  invoked via `uv run`

</coding_guidelines>
