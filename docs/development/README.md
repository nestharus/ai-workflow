# Development Documentation

This directory contains structured YAML documentation for development patterns and conventions.

## Directory Structure

```text
docs/development/
├── general/          # Framework/protocol patterns (no app/* references)
│   ├── rest/         # REST/HTTP protocol patterns
│   ├── fastapi/      # FastAPI framework patterns
│   ├── python/       # Python language patterns
│   ├── surrealdb/    # SurrealDB patterns
│   └── elasticsearch/# Elasticsearch patterns
└── project/          # Project-specific implementation (app/* wiring)
    ├── rest/         # REST contract locations
    ├── fastapi/      # FastAPI implementation wiring
    ├── python/       # Python implementation wiring
    ├── surrealdb/    # SurrealDB implementation wiring
    └── elasticsearch/# Elasticsearch implementation wiring
```

## Naming Convention

* **GENERAL files**: `general.<module>.<pattern>.yml`
* **PROJECT files**: `project.<module>.<pattern>.yml`

Examples:
* `general/rest/general.rest.api-patterns.yml`
* `project/fastapi/project.fastapi.factory-patterns.yml`

## GENERAL vs PROJECT Scope

### GENERAL

Documentation that describes patterns without referencing project-specific files:

* REST/HTTP protocol rules (status codes, methods, headers)
* Framework best practices (FastAPI, Pydantic) described generically
* Language conventions (Python docstrings, type hints)
* Database patterns described without `app/*` paths

**Key rule**: No references to `app/*` paths or project-specific components.

### PROJECT

Documentation that references actual project implementation:

* Concrete `app/*` paths (`app/contracts/`, `app/core/factory.py`)
* Project-specific components (`AppError`, `VALIDATION_ERROR_RESPONSE`, `create_app`)
* Implementation wiring showing where patterns are applied in this codebase

**Key rule**: Must reference concrete `app/*` paths or project-specific code.

## Modules

| Module | Description |
|--------|-------------|
| `rest` | REST/HTTP protocol patterns: URL structure, HTTP methods, status codes, versioning, content negotiation |
| `fastapi` | FastAPI framework patterns: routers, dependencies, middleware, exception handling, factory patterns |
| `python` | Python language patterns: architectural patterns, services, repositories, settings |
| `surrealdb` | SurrealDB database patterns: connection pooling, repository patterns, query patterns |
| `elasticsearch` | Elasticsearch patterns: connection pooling, repository patterns, search patterns |

## Classification Criteria

For detailed classification rules when creating or modifying documentation, see:
* `.claude/agents/knowledge-analyzer.md` - Multi-dimensional classification criteria

## Migration Workflow

For restructuring documentation between GENERAL and PROJECT files, see:
* `docs/processes/information-migration.yml` - Full workflow with CLI commands

## External Tool Dependencies

### dotenv-linter (Optional)

dotenv-linter is an external linting tool for validating `.env` files. It helps catch
common mistakes like duplicate keys, trailing whitespace, and incorrect formatting.

**Installation**:

* **macOS**:

  ```bash
  brew install dotenv-linter
  ```

* **Linux**:

  Download from official releases or install via cargo:

  ```bash
  cargo install dotenv-linter
  ```

* **Official Installation Docs**: [dotenv-linter installation](https://dotenv-linter.github.io/#/installation)

**Usage**:

Once installed, dotenv-linter is automatically integrated into the project lint
pipeline, invoked via `uv run lint dotenvlint`. Configuration is managed via
`.lint.dotenvlint.yaml`.

**Pre-commit vs Lint Driver**: The pre-commit hook in `.pre-commit-config.yaml` runs
`dotenv-linter` directly on files matching the `files: ^\.env.*$` pattern at commit time.
The `uv run lint dotenvlint` command uses `.lint.dotenvlint.yaml` to determine which
`.env` templates to include or exclude. To change pre-commit behavior, edit
`.pre-commit-config.yaml`; to change CI/local lint behavior, edit `.lint.dotenvlint.yaml`.

**Note**: This is an optional tool. If not installed, the lint script will skip
dotenv-linter checks.
