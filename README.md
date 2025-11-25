# Developing With AI 2.0

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
uv run start-server
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

Run all code quality checks (Ruff formatting/linting, mypy, Checkov, pymarkdown) with a single command:

```bash
uv run lint
```

Any errors will fail the lint job locally and in CI.

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
| `tests/` | Test suites (`unit/`, `integration/`, `e2e/`) |
| `tools/` | Workflow support tools and concatenation utilities |
| `.factory/` | Factory configuration (`settings.json`, `SCHEMA.md`) |
| `openapi/` | Generated OpenAPI schema |

## Utility Scripts

Available via `uv run <script>`:

| Script | Description |
|--------|-------------|
| `setup` | Install pre-commit hooks |
| `lint` | Run comprehensive linting (Ruff, mypy, Checkov, pymarkdown) |
| `start-server` | Start development server with health checks |
| `gen_openapi` | Generate OpenAPI schema JSON to `openapi/openapi.json` |
| `coderabbit-review` | Run CodeRabbit AI code review (human-initiated) |
| `sonar-review` | Run SonarQube analysis (human-initiated) |
| `latest-review` | Fetch latest review artifact path |

Additional concatenation tools (`concat_app`, `concat_docs`, `concat_scripts`, `concat_tests`, `concat_tools`)
are available for codebase analysis. See `AGENTS.md` for detailed usage of review tools.

## Documentation Modules

Documentation is organized into focused modules under `docs/`:

| Module | Path | Description |
|--------|------|-------------|
| **Usage** | [`docs/usage/`](docs/usage/README.md) | Using the application |
| **Development** | [`docs/development/`](docs/development/README.md) | Writing code, docstrings, FastAPI practices |
| **Testing** | [`docs/testing/`](docs/testing/README.md) | Writing and running test code |
| **Architecture** | [`docs/architecture/`](docs/architecture/README.md) | Folder structure, services, endpoints, integrations |
| **Processes** | [`docs/processes/`](docs/processes/README.md) | Development processes, git releases, code reviews |

Each module README contains topic summaries and applicability guidance. See `AGENTS.md` as the primary entry
point for AI agents.

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
