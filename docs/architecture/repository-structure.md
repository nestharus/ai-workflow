# Repository Structure

This document provides a comprehensive directory and file reference for the codebase.

## Application Code

* **`app/routes/`**: API endpoint routers, including `orchestrator_router.py`
* **`app/services/`**: Business logic layer, including `orchestrator_service.py` and
  `agent_invoker.py`
* **`app/contracts/`**: Pydantic models, including `orchestrator_contracts.py`
* **`app/core/`**: Core application setup including `factory.py` for app construction

## Agent Definitions

* **`.factory/droids/`**: Agent definitions (POML) organized by domain

## Documentation

* **`docs/`**: The Coarse Knowledge Graph (source of truth) with subdirectories for each
  domain:
  * `docs/usage/`: Documentation for using the application
  * `docs/development/`: Writing application code, docstrings, code style
  * `docs/testing/`: Writing and running test code
  * `docs/architecture/`: Folder structure, services, endpoints, integrations
  * `docs/processes/`: Development processes like git releases, code reviews

## Infrastructure

* **`webhook_receiver/`**: Standalone service for handling GitHub webhooks
* **`openapi/`**: Generated OpenAPI schema JSON

## Testing

* **`tests/`**: Test organization:
  * `tests/unit/`: Unit tests
  * `tests/integration/`: Integration tests (in-process)
  * `tests/e2e/`: End-to-end tests (live server)

## Tooling

* **`scripts/`**: Runtime and development scripts
* **`scripts/dev/`**: Development tools (linting, testing, code review)
* **`scripts/knowledge/`**: Knowledge management system scripts
