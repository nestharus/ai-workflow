# Developing With AI 2.0

Run this before you start working

uv run dev.ensure-env >> .claude/dev-env.log 2>&1 || true

**Developing With AI 2.0** is an automated, orchestrator-based AI workflow system in active development. It
implements a structured collaboration model between AI agents coordinated by a FastAPI orchestrator service,
with architecture details available in `docs/architecture/`.

## Architecture

The system uses a 5-role skeleton (R1-R5) across four domains: **Product**, **UX**, **UI**, and **Technical**.

* R1 Strategy R2 Planning R3 Implementation R4 Quality Review R5 QA/Maintenance

The workflow relies on **automated orchestration via FastAPI service** that routes messages to workflows and
coordinates agent execution, backed by a documentation-first knowledge graph.

## Technology Stack

| Category | Technologies |
|----------|--------------|
| **Core** | Python 3.14+, FastAPI, Uvicorn |
| **Data** | Pydantic v2, Pydantic Settings, orjson |
| **Infrastructure** | SurrealDB (Knowledge Graph), Elasticsearch (vector search), anyio |
| **Build** | uv, Hatchling |

## Project Setup

1. Install dependencies:

   ```bash
   uv sync
   ```

2. Install pre-commit hooks:

   ```bash
   uv run setup
   ```

See `.pre-commit-config.yaml` for code quality standards.

## Development

### Running Locally

Use the start script for a robust development server with health checks:

```bash
uv run app.start
```

#### Options

* `--host <HOST>`: Server bind address (default: 127.0.0.1).
* `--port <PORT>`: Change server port (default: 8000).
* `--reload`: Enable auto-reload for development.
* `--skip-health-check`: Skip post-start health validation.

#### Alternative (Direct Uvicorn)

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

#### Health Check Endpoints

* `http://localhost:8000/health`
* `http://localhost:8000/api/v1/health`

### Running with Docker

Build and run using Docker Compose:

```bash
docker-compose up --build
```

The service will be available at `http://localhost:8000`. The setup includes hot-reload via volume mounts for
`app/`, `scripts/`, and `tests/`.

#### Manual Build & Run

```bash
docker build -t ai-workflow-api:dev .
docker run --rm -p 8000:8000 ai-workflow-api:dev
```

### Code Quality

Run all code quality checks with a single command:

```bash
uv run lint
```

This runs Python-based linters (ruff, mypy, checkov, pymarkdown, detect-secrets, yamllint) plus additional
CLI-based security and configuration linters (actionlint, trivy, gitleaks, dotenv-linter).

#### External CLI Dependencies

The following tools require manual installation as they are not Python packages:

| Tool | Purpose | Installation |
|------|---------|--------------|
| **actionlint** | GitHub Actions workflow linting | `brew install actionlint` (macOS) or `go install
| github.com/rhysd/actionlint/cmd/actionlint@latest` |
| **trivy** | Security vulnerability scanning | `brew install trivy` (macOS/Linux) or download from
| [GitHub releases](https://github.com/aquasecurity/trivy/releases) |
| **gitleaks** | Secret detection in code | `brew install gitleaks` (macOS/Linux) or `go install
| github.com/gitleaks/gitleaks/v8@v8.24.2` |
| **dotenv-linter** | .env file linting | `brew install dotenv-linter` (macOS) or `cargo install dotenv-linter` (Linux) |

If these tools are not installed, `uv run lint` will fail with clear error messages. For detailed
documentation on each linter, see the files in `docs/usage/` and `docs/development/project/`.

Any errors will fail the lint job locally and in CI.

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

#### Quick Commands

```bash
# Review uncommitted changes (staged + unstaged)
uv run review.coderabbit -- --type uncommitted

# Review against main branch
uv run review.coderabbit -- --base main
```

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

## Environment Variables

Configuration is managed via `app/core/settings.py`. See that file for complete validation rules.

### Application Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug mode | `False` |
| `APP_NAME` | Application name | `"AI Workflow API"` |
| `APP_VERSION` | Application version | `"0.1.0"` |
| `INCLUDE_ERROR_BODY` | Include full error bodies in validation responses | `False` |
| `HOST` | Server bind address (start-server.py) | `127.0.0.1` |
| `PORT` | Server port (start-server.py) | `8000` |

### API Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `API_PREFIX` | Base path for API routes | `"/api/v1"` |
| `EXAMPLE_PREFIX` | Prefix for processed example responses | `"[PROCESSED]"` |

### Knowledge Graph (SurrealDB)

| Variable | Description | Default |
|----------|-------------|---------|
| `SURREALDB_URL` | SurrealDB connection URL (ws/wss/http/https) | `"ws://localhost:8000/rpc"` |
| `SURREALDB_NAMESPACE` | SurrealDB namespace | `"knowledge"` |
| `SURREALDB_DATABASE` | SurrealDB database name | `"facts"` |
| `SURREALDB_USER` | SurrealDB username (min 12 chars, complexity required) | **Required** |
| `SURREALDB_PASS` | SurrealDB password (min 12 chars, complexity required) | **Required** |
| `SURREALDB_POOL_SIZE` | Connection pool size | `5` |

### Vector Search (Elasticsearch)

| Variable | Description | Default |
|----------|-------------|---------|
| `ELASTICSEARCH_URL` | Elasticsearch URL (http/https) | `"http://localhost:9200"` |
| `ELASTICSEARCH_CONNECTIONS_PER_NODE` | Connections per node | `25` |
| `ELASTICSEARCH_REQUEST_TIMEOUT` | Request timeout in seconds | `10` |
| `ELASTICSEARCH_SHARDS` | Number of index shards | `1` |
| `ELASTICSEARCH_REPLICAS` | Number of index replicas | `0` |
| `EMBEDDING_DIMENSION` | Vector embedding dimension | `768` |

### Middleware Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `ENABLE_GZIP` | Enable GZip compression | `False` |
| `ENFORCE_HTTPS` | Enforce HTTPS redirects | `False` |
| `ALLOWED_HOSTS` | List of allowed host headers | `["*"]` |
| `CORS_ENABLED` | Enable CORS middleware | `False` |
| `CORS_ALLOW_ORIGINS` | Allowed CORS origins | `[]` |
| `CORS_ALLOW_ORIGIN_REGEX` | Regex pattern for allowed origins | `None` |
| `CORS_ALLOW_METHODS` | Allowed HTTP methods | `["*"]` |
| `CORS_ALLOW_HEADERS` | Allowed request headers | `["*"]` |
| `CORS_EXPOSE_HEADERS` | Headers exposed to browser | `[]` |
| `CORS_ALLOW_CREDENTIALS` | Allow credentials in CORS | `False` |
| `CORS_MAX_AGE` | CORS preflight cache duration (seconds) | `600` |

## API Endpoints

* **`/health`**: Basic health check (`{"status": "ok"}`)
* **`/api/v1/health`**: Versioned health check (`{"status": "ok"}`)
* **`/api/v1/examples/sample`**: GET demo endpoint returning sample response
* **`/api/v1/examples/process`**: POST endpoint demonstrating service integration
* **`/docs`**: Interactive Swagger UI documentation
* **`/redoc`**: ReDoc documentation

Note: Example endpoints are non-resource demos for illustration purposes.

## Repository Structure

| Directory | Description |
|-----------|-------------|
| `app/` | FastAPI application (`api/v1/`, `contracts/`, `core/`, `infrastructure/`, `repositories/`, `services/`) |
| `docs/` | Modular documentation (`usage/`, `development/`, `testing/`, `architecture/`, `processes/`) |
| `scripts/` | Utility scripts for setup, linting, reviews, OpenAPI generation |
| `tests/` | Test suites (`unit/`, `integration/`) |
| `tools/` | Workflow support tools and concatenation utilities |
| `.factory/` | Factory configuration (`settings.json`, `SCHEMA.md`) |
| `openapi/` | Generated OpenAPI schema |

## Utility Scripts

Available via `uv run <script>`:

| Script | Description |
|--------|-------------|
| `setup` | Install pre-commit hooks |
| `lint` | Run comprehensive linting (Ruff, mypy, Checkov, pymarkdown) |
| `app.start` | Start development server with health checks |
| `gen_openapi` | Generate OpenAPI schema JSON to `openapi/openapi.json` |
| `zip-changes` | Create zip of changed files (no args = uncommitted, or pass SHA) |
| `coderabbit-review` | Run CodeRabbit AI code review (human-initiated) |
| `sonar-review` | Run SonarQube analysis (human-initiated) |
| `latest-review` | Fetch latest review artifact path |

Additional concatenation tools (`concat_app`, `concat_docs`, `concat_scripts`, `concat_tests`,
`concat_tools`) are available for codebase analysis. See `AGENTS.md` for detailed usage of review
tools.

### MCP Bridge

Detailed deployment and configuration information for the MCP bridge is documented in
[`docs/architecture/mcp-bridge-architecture.yml`](docs/architecture/mcp-bridge-architecture.yml).

## Keyword Extraction Pipeline Tests

The keyword extraction pipeline has comprehensive test coverage organized in the tiered structure
under `scripts/tests/`:

* **Unit tests**: `scripts/tests/unit/knowledge/` - Isolated function tests
* **Component tests**: `scripts/tests/component/knowledge/` - Integration tests for module interactions
* **Integration tests**: `scripts/tests/integration/knowledge/` - End-to-end pipeline tests

| Test File | Description |
|-----------|-------------|
| `test_candidate_extraction.py` | Unit tests for Stage 1 candidate extraction |
| `test_query_keyword_candidates.py` | Tests for querying candidates from CSV |
| `test_classify_keyword.py` | Tests for Stage 2 classification CLI |
| `test_qwen_scoring.py` | Tests for Qwen model scoring |
| `test_keyword_store.py` | Tests for keyword storage and application |
| `test_variant_resolver.py` | Tests for variant tracking and resolution |
| `test_extraction_pipeline.py` | Integration tests for full pipeline |

### Running Tests

```bash
# Run all knowledge tests (all tiers)
uv run pytest scripts/tests/unit/knowledge/ scripts/tests/component/knowledge/ scripts/tests/integration/knowledge/

# Run unit tests only
uv run pytest scripts/tests/unit/knowledge/

# Run specific test file
uv run pytest scripts/tests/unit/knowledge/test_extraction_pipeline.py

# Run golden keyword validation
uv run pytest scripts/tests/unit/knowledge/test_extraction_pipeline.py::TestPipelineIntegration
```

### Golden Keywords

The test fixture `scripts/tests/unit/knowledge/fixtures/golden_keywords_test.yml` contains a curated
set of technical terms that must be extracted. The integration test validates that all golden
keywords are captured, ensuring the pipeline maintains high recall (zero false negatives).

## Documentation Modules

Documentation is organized into focused modules under `docs/`:

| Module | Path | Description |
|--------|------|-------------|
| **Usage** | [`docs/usage/`](docs/usage/README.md) | Using the application |
| **Development** | [`docs/development/`](docs/development/README.md) | Writing code, docstrings, FastAPI practices |
| **Testing** | [`docs/testing/`](docs/testing/README.md) | Writing and running test code |
| **Architecture** | [`docs/architecture/`](docs/architecture/README.md) | Structure, services, endpoints |
| **Processes** | [`docs/processes/`](docs/processes/README.md) | Development processes, git releases, code reviews |

Each module README contains topic summaries and applicability guidance. See `AGENTS.md` as the
primary entry point for AI agents.

## Operational Protocols

Always consult the knowledge graph in `docs/` before starting tasks. For detailed operational protocols, agent
guidelines, and workflow patterns, see `AGENTS.md` and `docs/processes/`.

## Droid Settings

See `.factory/SCHEMA.md` for the schema and defaults for `.factory/settings.json`. This configures Factory
integration settings for the project.

## Next Steps

* Continue development of orchestrator service and agent workflows.
* Enhance existing tooling and automation.
* Expand Knowledge Graph infrastructure (SurrealDB, Elasticsearch).
* Integrate deep research and quality tools.
