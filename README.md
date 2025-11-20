# Developing With AI 2.0

**Developing With AI 2.0** is a human-orchestrated AI workflow system currently in the planning phase. It
defines a structured collaboration model between human operators and AI agents, with architecture details
available in `docs/plans/`.

## Architecture

The system uses a 5-role skeleton (R1-R5) across four domains: **Product**, **UX**, **UI**, and **Technical**.

* R1 Strategy R2 Planning R3 Implementation R4 Quality Review R5 QA/Maintenance

The workflow relies on **human orchestration** rather than automated sequencing, using a documentation-first
knowledge graph.

## Technology Stack

* Python 3.14+ FastAPI Uvicorn Pydantic v2 Pydantic Settings orjson uv Hatchling

## Project Setup

1. Install dependencies:

   ```bash
   uv sync
   ```

2. Install pre-commit hooks:

   ```bash
   uv run python scripts/setup.py
   ```

See `.pre-commit-config.yaml` for code quality standards.

## Development

### Running Locally

Use the start script for a robust development server with health checks:

```bash
uv run python scripts/start-server.py
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

Run all code quality checks (Ruff formatting/linting and mypy static analysis) with a single command:

```bash
uv run python scripts/lint.py
```

Any errors will fail the lint job locally and in CI.

## Environment Variables

Configuration is managed via `app/core/settings.py`.

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug mode | `False` |
| `APP_NAME` | Application name | `"AI Workflow API"` |
| `APP_VERSION` | Application version | `"0.1.0"` |
| `INCLUDE_ERROR_BODY` | Include full error bodies in validation responses | `False` |
| `HOST` | Server bind address (start-server.py) | `127.0.0.1` |
| `PORT` | Server port (start-server.py) | `8000` |
| `PYTHONUNBUFFERED` | Set to 1 for unbuffered output | `1` (in Docker) |

## API Endpoints

* **`/health`**: Basic health check (`{"status": "ok"}`)
* **`/api/v1/health`**: Versioned health check (`{"status": "ok"}`)
* **`/docs`**: Interactive Swagger UI documentation
* **`/redoc`**: ReDoc documentation

## Repository Structure

* `app/`: FastAPI application code.
* `.factory/droids/`: Agent definitions (POML) by domain.
* `docs/`: Knowledge graph and planning documents.
* `tools/`: Workflow support tools.
* `scripts/`: Helper scripts.

## Operational Protocols

Agents are invoked manually. Always consult the knowledge graph in `docs/` before starting tasks. See
`AGENTS.md` for detailed protocols.

### Example Invocation

> "As R1 Tech Strategist, analyze phase X from `docs/plans/phase1.md`"

Once the CLI is implemented, agent roles will typically be invoked via commands like:

```bash
uv run python -m agents.cli --role "R1 Tech Strategist" --task "analyze phase X"
```

## Droid Settings

See `.factory/SCHEMA.md` for the schema and defaults for `.factory/settings.json`.

## Next Steps

* Implement agent system based on phase plans. Build CLI tools for invocation. Integrate deep research and
  quality tools.
