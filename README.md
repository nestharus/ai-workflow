# Developing With AI 2.0

**Developing With AI 2.0** is an automated, orchestrator-based AI workflow
system in active development. It implements a structured collaboration
model between AI agents coordinated by a FastAPI orchestrator service,
with architecture details available in `docs/architecture/`.

## Quick Start

```bash
# 1. Install uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone and setup
git clone <repo-url> && cd ai-workflow
cp .env.example .env  # Edit with your API keys

# 3. Install dependencies and hooks
uv sync && uv run setup

# 4. Start development services
uv run dev.ensure-env

# 5. Run the server
uv run app.start
```

Run this before each working session to ensure services are running:

```bash
uv run dev.ensure-env >> .claude/dev-env.log 2>&1 || true
```

## Architecture

The system uses a 5-role skeleton (R1-R5) across four domains: **Product**,
**UX**, **UI**, and **Technical**.

* R1 Strategy R2 Planning R3 Implementation R4 Quality Review R5 QA/Maintenance

The workflow relies on **automated orchestration via FastAPI service**
that routes messages to workflows and coordinates agent execution, backed
by a documentation-first knowledge graph.

## Technology Stack

| Category | Technologies |
|----------|--------------|
| **Core** | Python 3.14+, FastAPI, Uvicorn |
| **Data** | Pydantic v2, Pydantic Settings, orjson |
| **Infrastructure** | SurrealDB (Knowledge Graph), Elasticsearch
  (vector search), anyio |
| **Build** | uv, Hatchling |
| **AI Backends** | Claude Code, OpenCode, Gemini CLI, Ollama |

## Prerequisites

Before setting up the project, ensure you have these system-level
dependencies installed.

### Required System Tools

| Tool | Purpose | Installation |
|------|---------|--------------|
| **uv** | Python package manager | `curl -LsSf https://astral.sh/uv/install.sh`
  `\| sh` |
| **Docker** | Container runtime for dev services | [Install Docker]
  (https://docs.docker.com/get-docker/) |
| **Node.js** | Required for npm-based CLI tools | [Install Node.js]
  (https://nodejs.org/) (v18+) |

### AI CLI Tools

These CLI tools are required to run AI agents in the project:

| Tool | Purpose | Installation |
|------|---------|--------------|
| **claude** | Claude Code CLI (Anthropic) | `npm install -g`
  `@anthropic-ai/claude-code` |
| **opencode** | OpenCode CLI (OpenAI) | `npm install -g opencode` |
| **gemini** | Gemini CLI (Google) | `npm install -g @anthropic-ai/gemini-cli`
  or via Google's CLI |
| **coderabbit** | AI code review | `npm install -g coderabbit` then
  `coderabbit login` |

### Code Quality Tools (External CLI)

| Tool | Purpose | Installation |
|------|---------|--------------|
| **actionlint** | GitHub Actions linting | `brew install actionlint` or
  `go install github.com/rhysd/actionlint/cmd/actionlint@latest` |
| **trivy** | Security vulnerability scanning | `brew install trivy` or
  [releases](https://github.com/aquasecurity/trivy/releases) |
| **gitleaks** | Secret detection | `brew install gitleaks` or
  `go install github.com/gitleaks/gitleaks/v8@v8.24.2` |
| **dotenv-linter** | .env file linting | `brew install dotenv-linter`
  or `cargo install dotenv-linter` |

## Environment Variables

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

The `.env.example` file contains all required environment variables with
comments explaining where to obtain API keys. Key categories:

| Category | Variables | Purpose |
|----------|-----------|---------|
| **AI Providers** | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
  `GEMINI_API_KEY`, `Z_AI_API_KEY`, `MINIMAX_API_KEY` | AI model backends |
| **Integrations** | `LINEAR_API_KEY`, `GITHUB_MCP_PAT`,
  `FIRECRAWL_API_KEY` | External service integrations |
| **Code Review** | `SONAR_HOST_URL`, `SONAR_TOKEN` | SonarQube analysis |
| **Runtime** | `UV_MANAGED_PYTHON`,
  `OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` | Tool configuration |

Load environment variables:

```bash
# Using dotenv
source .env

# Or export in your shell config (~/.bashrc or ~/.zshrc)
set -a && source .env && set +a
```

## Home Directory Configuration

Several tools require configuration in your home directory.

### GLM via Z.AI (~/.bashrc)

Add to your `~/.bashrc` or `~/.zshrc`:

```bash
# GLM alias pointing to Claude Code with Z.AI config
alias glm='claude --config ~/.claude-glm'

# Z.AI environment (if not already exported)
export Z_AI_API_KEY="<your-z-ai-key>"
export Z_AI_BASE_URL="https://api.z.ai/v1"
```

Then create `~/.claude-glm/config.json`:

```json
{
  "apiKey": "${Z_AI_API_KEY}",
  "baseUrl": "${Z_AI_BASE_URL}",
  "model": "glm-4.7"
}
```

### Minimax via Claude Code

Create `~/.claude-minimax/config.json`:

```json
{
  "apiKey": "${MINIMAX_API_KEY}",
  "baseUrl": "https://api.minimax.chat/v1",
  "model": "abab6.5s-chat"
}
```

Then add alias to `~/.bashrc`:

```bash
alias claude-minimax='claude --config ~/.claude-minimax'
```

### Gemini CLI (~/.gemini/settings.json)

Configure Gemini CLI with your API key:

```json
{
  "apiKey": "${GEMINI_API_KEY}",
  "defaultModel": "gemini-3-flash-high"
}
```

### SSH Key for Git Operations (~/.ssh/github)

The sandbox server requires an SSH key for git operations:

```bash
# Generate if not exists
ssh-keygen -t ed25519 -f ~/.ssh/github -N ""

# Add to GitHub at https://github.com/settings/keys
cat ~/.ssh/github.pub
```

## Project Setup

1. Install Python dependencies:

   ```bash
   uv sync
   ```

2. Install pre-commit hooks:

   ```bash
   uv run setup
   ```

3. Start development services (MCP Bridge, Sandbox Server, Ollama):

   ```bash
   uv run dev.ensure-env
   ```

   This starts Docker containers for:
   * **MCP Bridge** (`ai-workflow-mcp-bridge-dev`) - REST-to-MCP bridge on
     Unix socket
   * **Sandbox Server** (`ai-workflow-sandbox-server-dev`) - Git operations
     sandbox
   * **Ollama** (`ai-workflow-ollama-dev`) - Local Ministral 3B model on
     port 11434

4. Verify services are running:

   ```bash
   docker ps | grep ai-workflow
   ```

See `.pre-commit-config.yaml` for code quality standards.

## AI Models Configuration

The project uses multiple AI backends configured in `.agents/models/`. Each
model is a TOML file specifying how to invoke the AI backend.

### Available Model Providers

| Provider | Models | Environment Variable | Get API Key |
|----------|--------|---------------------|-------------|
| **Anthropic** | claude-haiku, claude-sonnet,
  claude-opus | `ANTHROPIC_API_KEY` |
  [console.anthropic.com](https://console.anthropic.com/) |
| **OpenAI** | gpt-5.2-*, gpt-5.1-* | `OPENAI_API_KEY` |
  [platform.openai.com](https://platform.openai.com/api-keys) |
| **Google** | gemini-3-flash-*, gemini-3-pro-* | `GEMINI_API_KEY` |
  [aistudio.google.com](https://aistudio.google.com/apikey) |
| **Z.AI** | glm (GLM-4.7) | `Z_AI_API_KEY` | [z.ai](https://z.ai/) |
| **Minimax** | minimax | `MINIMAX_API_KEY` |
  [minimax.chat](https://www.minimax.chat/) |
| **Ollama** | ministral-3b, smollm2-* | None (local) | Bundled via Docker |

### Model Context Limits

| Model | Context (tokens) | Recommended max_chars |
|-------|------------------|----------------------|
| SmolLM2-135M | 2,048 | 4,000 |
| SmolLM2-360M | 2,048 | 6,000 |
| Ministral-3B | 4,096 | 8,000 |
| GLM-4.7 | 32,768-128,768 | (no limit - fallback) |
| Claude Sonnet | 200,000 | 600,000 |
| GPT-5.x | 272,000 | 800,000 |
| Gemini 3 | 1,000,000+ | 1,500,000+ |

### Running Agents

```bash
# Run an agent with default routing
uv run agent.claude "Your prompt here"

# Run with a specific model
uv run agent.claude --model claude-sonnet "Your prompt here"

# Run via OpenCode
uv run agent.opencode --model gpt-5.2-high "Your prompt here"
```

See `docs/development/adding-models.md` for adding new models and
`docs/development/writing-agents.md` for creating agents.

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

The service will be available at `http://localhost:8000`. The setup includes
hot-reload via volume mounts for `app/`, `scripts/`, and `tests/`.

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

This runs Python-based linters (ruff, mypy, checkov, pymarkdown,
detect-secrets, yamllint) plus additional CLI-based security and
configuration linters (actionlint, trivy, gitleaks, dotenv-linter).

See [Code Quality Tools (External CLI)](#code-quality-tools-external-cli)
in Prerequisites for installation. If these tools are not installed,
`uv run lint` will fail with clear error messages.

## Code Review

Automated code reviews are performed using CodeRabbit and SonarQube.

### CodeRabbit

Automated CodeRabbit review wrapper (adds `--prompt-only` automatically).
Agents must not run this command; a human must run it, and the agent will
fetch the latest artifact afterward.

* **Human-run command**: `uv run review.coderabbit -- [--base <branch> |
  --type <mode> | --base-commit <sha>] [extra coderabbit args]` (defaults
  to `--base main` when no target flag is provided)
* **Selection rule**: Choose exactly one of `--base`, `--type`, or
  `--base-commit`; do not combine
* **Purpose**: Provides AI-driven feedback on work-in-progress code before
  it is committed
* **Agent retrieval**: After the human run, the agent will fetch the newest
  artifact via `uv run review.latest --type coderabbit` (prints the newest
  `.review/*.review.coderabbit` path)
* **Timeout guidance**: Allow up to 2 hours for this command; do not stop
  it early when invoked via `uv run`

#### Quick Commands

```bash
# Review uncommitted changes (staged + unstaged)
uv run review.coderabbit -- --type uncommitted

# Review against main branch
uv run review.coderabbit -- --base main
```

### SonarQube

Runs SonarQube analysis using a Docker-based wrapper with caching enabled.
Agents must not run this command; a human must run it, and the agent will
fetch the latest artifact afterward.

* **Usage**: `./scripts/sonar_scan.sh [OPTIONS]`
* **Options**:
  * `-t, --token`: Authentication token (overrides `SONAR_TOKEN` env var)
  * `-u, --url`: SonarQube server URL (default: `http://localhost:9000`)
  * `--`: Arguments after this flag are passed directly to
    `sonar-scanner-cli`
* **Environment Variables**: `SONAR_TOKEN`, `SONAR_HOST_URL`
* **Human-run wrapper**: `uv run review.sonar -- [sonar_scan args]`
* **Agent retrieval**: After the human run, the agent will fetch the newest
  artifact via `uv run review.latest --type sonar` (prints the newest
  `.review/*.review.sonar` path)
* **Log output**: Wrapper writes to `.review/<timestamp>.review.sonar` and
  echoes the path
* **Timeout guidance**: Allow up to 2 hours for this command; do not stop
  it early when invoked via `uv run`

## Application Environment Variables

These variables configure the FastAPI application. For AI API keys, see
[Environment Variables](#environment-variables) above. Configuration is
managed via `app/core/settings.py`.

### Application Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Enable debug mode | `False` |
| `APP_NAME` | Application name | `"AI Workflow API"` |
| `APP_VERSION` | Application version | `"0.1.0"` |
| `INCLUDE_ERROR_BODY` | Include full error bodies in validation
  responses | `False` |
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
| `SURREALDB_URL` | SurrealDB connection URL
  (ws/wss/http/https) | `"ws://localhost:8000/rpc"` |
| `SURREALDB_NAMESPACE` | SurrealDB namespace | `"knowledge"` |
| `SURREALDB_DATABASE` | SurrealDB database name | `"facts"` |
| `SURREALDB_USER` | SurrealDB username (min 12 chars,
  complexity required) | **Required** |
| `SURREALDB_PASS` | SurrealDB password (min 12 chars,
  complexity required) | **Required** |
| `SURREALDB_POOL_SIZE` | Connection pool size | `5` |

### Vector Search (Elasticsearch)

| Variable | Description | Default |
|----------|-------------|---------|
| `ELASTICSEARCH_URL` | Elasticsearch URL | `http://localhost:9200` |
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
| `app/` | FastAPI application (`api/v1/`, `contracts/`,
  `core/`, `infrastructure/`, `repositories/`, `services/`) |
| `docs/` | Modular documentation (`usage/`, `development/`,
  `testing/`, `architecture/`, `processes/`) |
| `scripts/` | Utility scripts for setup, linting, reviews,
  OpenAPI generation |
| `tests/` | Test suites (`unit/`, `integration/`) |
| `tools/` | Workflow support tools and concatenation utilities |
| `.factory/` | Factory configuration (`settings.json`, `SCHEMA.md`) |
| `openapi/` | Generated OpenAPI schema |

## Utility Scripts

Available via `uv run <script>`:

| Script | Description |
|--------|-------------|
| `setup` | Install pre-commit hooks |
| `lint` | Run comprehensive linting (Ruff, mypy, Checkov,
  pymarkdown) |
| `app.start` | Start development server with health checks |
| `gen_openapi` | Generate OpenAPI schema JSON to
  `openapi/openapi.json` |
| `zip-changes` | Create zip of changed files (no args =
  uncommitted, or pass SHA) |
| `coderabbit-review` | Run CodeRabbit AI code review (human-initiated) |
| `sonar-review` | Run SonarQube analysis (human-initiated) |
| `latest-review` | Fetch latest review artifact path |

Additional concatenation tools (`concat_app`, `concat_docs`, `concat_scripts`,
`concat_tests`, `concat_tools`) are available for codebase analysis. See
`AGENTS.md` for detailed usage of review tools.

### MCP Bridge

Detailed deployment and configuration information for the MCP bridge is
documented in
[`docs/architecture/mcp-bridge-architecture.yml`](docs/architecture/mcp-bridge-architecture.yml).

## Keyword Extraction Pipeline Tests

The keyword extraction pipeline has comprehensive test coverage organized in
the tiered structure under `scripts/tests/`:

* **Unit tests**: `scripts/tests/unit/knowledge/` - Isolated function tests
* **Component tests**: `scripts/tests/component/knowledge/` - Integration
  tests for module interactions
* **Integration tests**: `scripts/tests/integration/knowledge/` - End-to-end
  pipeline tests

| Test File | Description |
|-----------|-------------|
| `test_candidate_extraction.py` | Unit tests for Stage 1 candidate
  extraction |
| `test_query_keyword_candidates.py` | Tests for querying candidates from
  CSV |
| `test_classify_keyword.py` | Tests for Stage 2 classification CLI |
| `test_qwen_scoring.py` | Tests for Qwen model scoring |
| `test_keyword_store.py` | Tests for keyword storage and application |
| `test_variant_resolver.py` | Tests for variant tracking and
  resolution |
| `test_extraction_pipeline.py` | Integration tests for full pipeline |

### Running Tests

```bash
# Run all knowledge tests (all tiers)
uv run pytest scripts/tests/unit/knowledge/ \
  scripts/tests/component/knowledge/ \
  scripts/tests/integration/knowledge/

# Run unit tests only
uv run pytest scripts/tests/unit/knowledge/

# Run specific test file
uv run pytest scripts/tests/unit/knowledge/test_extraction_pipeline.py

# Run golden keyword validation
uv run pytest \
  scripts/tests/unit/knowledge/test_extraction_pipeline.py::TestPipelineIntegration
```

### Golden Keywords

The test fixture
`scripts/tests/unit/knowledge/fixtures/golden_keywords_test.yml` contains a
curated set of technical terms that must be extracted. The integration
test validates that all golden keywords are captured, ensuring the
pipeline maintains high recall (zero false negatives).

## Documentation Modules

Documentation is organized into focused modules under `docs/`:

| Module | Path | Description |
|--------|------|-------------|
| **Usage** | [`docs/usage/`](docs/usage/README.md) | Using the
  application |
| **Development** | [`docs/development/`](docs/development/README.md) | Writing
  code, docstrings, FastAPI practices |
| **Testing** | [`docs/testing/`](docs/testing/README.md) | Writing and running
  test code |
| **Architecture** | [`docs/architecture/`](docs/architecture/README.md) |
  Structure, services, endpoints |
| **Processes** | [`docs/processes/`](docs/processes/README.md) | Development
  processes, git releases, code reviews |

Each module README contains topic summaries and applicability guidance. See
`AGENTS.md` as the primary entry point for AI agents.

## Operational Protocols

Always consult the knowledge graph in `docs/` before starting tasks. For
detailed operational protocols, agent guidelines, and workflow patterns,
see `AGENTS.md` and `docs/processes/`.

## Droid Settings

See `.factory/SCHEMA.md` for the schema and defaults for
`.factory/settings.json`. This configures Factory integration settings for
the project.

## Next Steps

* Continue development of orchestrator service and agent workflows.
* Enhance existing tooling and automation.
* Expand Knowledge Graph infrastructure (SurrealDB, Elasticsearch).
* Integrate deep research and quality tools.
