# API testing patterns

This document defines how to test the FastAPI backend across unit, integration, and end-to-end (E2E) layers.
It standardizes how fixtures are composed, how dependencies are overridden, and how to structure tests so
that they are fast, reliable, and aligned with the application architecture.

## 1. Testing architecture

* **Three layers:**
  * **Unit tests:** Exercise a single function or class in isolation with minimal dependencies.
  * **Integration tests:** Use an in-process ASGI client to exercise the full FastAPI app without a real
    network (`async_client` from `tests/conftest.py`).
  * **E2E tests:** Talk to a live server running in Docker and validate the full stack (`api_client` from
    `tests/conftest.py`).
* **App factory:** All tests that need the HTTP layer should build the app via `create_app` from
  `app/core/factory.py`, passing a `Settings` instance from `app/core/settings.py` or a test-specific
  variant.
* **Contracts first:** When testing HTTP endpoints, treat the Pydantic contracts (including
  `HTTPValidationError` in `app/contracts/errors.py`) as the source of truth for request/response shapes.

## 2. Test fixture composition root

`tests/conftest.py` is the **composition root** for the test suite. It owns how the application, settings,
and HTTP clients are composed for tests.

* **Settings fixture:**
  * `test_settings` provides a `Settings` instance configured for testing.
  * Tests should build on top of this fixture rather than constructing `Settings` directly.
* **App fixture:**
  * `test_app` creates a `FastAPI` instance by calling `create_app(test_settings)`.
  * This is the canonical way to get an in-process app in tests.
* **Sync clients:**
  * `client` yields a `TestClient` for basic synchronous route testing.
  * `client_include_error_body` enables `include_error_body=True` via a copied `Settings` instance and is
    dedicated to validation/error-body tests.
* **Async clients:**
  * `async_client` yields an `httpx.AsyncClient` configured with `httpx.ASGITransport(app=test_app)` and a
    `base_url` of `http://test`. It is the standard fixture for in-process integration tests.
  * `api_client` yields an `httpx.AsyncClient` that points at a live server URL and is used only in E2E
    tests.
* **Live server:**
  * `live_server` is a session-scoped fixture that builds and runs the Docker stack (via `docker compose`)
    using `docker-compose.yml`, waits for the `/health` endpoint to become ready, and tears everything down
    after tests complete.

All new HTTP-level tests should prefer these fixtures instead of creating ad-hoc `FastAPI` apps or clients.

## 3. Dependency overrides pattern

FastAPI’s recommended pattern for test-time dependency injection is `app.dependency_overrides`, not
`monkeypatch`. This keeps test configuration close to the real dependency graph and aligns with the
framework’s own guidelines.

* **Core idea:**
  * For a dependency provider like `get_surrealdb_pool` or `get_search_client`, register a test double in
    `app.dependency_overrides` before creating the client.
* **Lifecycle:**
  * Set overrides **before** constructing `TestClient` or `AsyncClient`.
  * Always clear overrides **after** the test to avoid cross-test leakage.
* **Canonical fixture pattern:**

```python
@pytest.fixture
def client_with_overrides(test_app: FastAPI) -> Iterator[TestClient]:
    test_app.dependency_overrides[get_surrealdb_pool] = get_test_surrealdb_pool
    test_app.dependency_overrides[get_search_client] = get_test_search_client

    with TestClient(test_app) as client:
        yield client

    test_app.dependency_overrides.clear()
```

* **Migration note:** Existing tests (such as those in `tests/unit/test_validation_errors.py`) may rely on
  `monkeypatch` against factories like `create_surrealdb_pool`. New tests and refactors should move toward
  the `dependency_overrides` approach so that dependency wiring is centralized and easier to reason about.

## 4. Mocking external dependencies

External resources (databases, search, queues, third-party APIs) should be mocked at the **dependency
boundary**, not by patching internals.

* **DB pools:**
  * Provide a dependency like `get_surrealdb_pool` that returns a `SurrealDBPool` instance in production.
  * In tests, override `get_surrealdb_pool` with a lightweight fake that implements the minimal methods used
    by the code under test (for example, `query`, `close`).
* **Search/Elasticsearch:**
  * Provide a `get_elasticsearch_client` dependency that returns an `ElasticsearchWrapper` in production.
  * In tests, override it with a simple in-memory fake.
* **External services:**
  * For authentication providers, payment gateways, or other external APIs, override the dependency that
    calls them and return deterministic fake responses.

This keeps test doubles small and focused on behavior while allowing the HTTP layer and service layer to run
unchanged.

## 5. Settings override pattern

`Settings` in `app/core/settings.py` defines runtime configuration. Tests should treat `Settings` as the
single source of truth and create **immutable variants** using `model_copy`.

* **Base fixture:** Use the `test_settings` fixture from `tests/conftest.py` as the starting point.
* **Per-test variants:** For scenario-specific tweaks (for example, enabling `include_error_body` or turning
  on debug logs), create copies instead of mutating shared settings:

```python
settings = test_settings.model_copy(update={"include_error_body": True})
app = create_app(settings)
```

* **Validation-sensitive fields:** When constructing `Settings` directly (as in `tests/unit/test_validation_errors.py`),
  always respect validation constraints for credentials and URLs so tests mirror production requirements.

## 6. Integration test patterns (in-process)

Integration tests validate the full request/response cycle without starting a real server.

* **Client fixture:** Use `async_client` from `tests/conftest.py` for async endpoints and in-process tests.
* **No network:** Tests run entirely in-process using `httpx.ASGITransport`, giving full coverage of routing,
  dependency injection, and exception handlers without network overhead.
* **Dependency overrides:** Apply `app.dependency_overrides` to replace DB pools or external clients when
  needed.
* **Scope:** These tests should cover most application behavior, including happy paths, validation, and error
  handling, while remaining fast enough for frequent local execution.

## 7. E2E test patterns (Dockerized live server)

E2E tests validate the full stack: Docker image, startup scripts, network plumbing, and HTTP behavior.

* **Fixtures and markers:**
  * Use the `live_server` and `api_client` fixtures from `tests/conftest.py`.
  * Mark tests with `@pytest.mark.e2e` and, for async tests, `@pytest.mark.asyncio` (as shown in
    `tests/e2e/test_health.py`).
* **Docker stack:**
  * `live_server` runs `docker compose -f docker-compose.yml up -d --build api` and waits for `/health` to
    return status `200` with `{"status": "ok"}`.
  * On failure, it captures `docker compose` logs and raises a `DockerStartupTimeoutError` to aid debugging.
* **Port management:**
  * `_resolve_test_port` allocates an ephemeral port (or uses `TEST_PORT` when set) and stores it in
    `os.environ` so Docker and tests agree on the port.

E2E tests are slower and should be reserved for startup behavior, critical flows, and cross-service
interactions.

## 8. Test database setup

Database-related tests should never share a database with development or production.

* **Dedicated test DB:** Point `Settings.surrealdb_url` / `surrealdb_database` to a dedicated test instance
  or schema.
* **Schema initialization:** Ensure schema and seed data are created once per session (for example, in a
  future `test_surrealdb_pool` fixture) before running DB-dependent tests.
* **Isolation:** Use transactions, truncation, or per-test databases to keep tests independent.

Database fixtures and helpers for this project should live in `tests/conftest.py`, which is the canonical
location for test database setup patterns.

Even when the current suite only uses in-memory fakes, new database tests should follow this pattern so they
remain reliable as the system grows.

## 9. Assertion patterns

Assertions should reflect observable behavior and API contracts.

* **Status-first:** Assert the HTTP status code before inspecting the body.
* **Structured body:** Assert against parsed JSON using explicit keys and values.
* **Soft assertions:** Use `pytest-check` (as in `tests/e2e/test_health.py`) when multiple related assertions
  should be evaluated within a single test.
* **Model-based validation:** When appropriate, deserialize responses into Pydantic models (for example,
  response contracts or `HTTPValidationError`) rather than asserting on raw dictionaries.

Example:

```python
check.equal(response.status_code, 200)
check.equal(response.json().get("status"), "ok")
```

## 10. Testing validation errors and error responses

Validation behavior is a cross-cutting concern and must remain consistent.

* **Validation contracts:** `HTTPValidationError` in `app/contracts/errors.py` defines the shape of
  validation error responses exposed by the API.
* **Settings-driven behavior:** The `include_error_body` flag in `Settings` controls whether the request body
  is echoed back in error responses. The `client_include_error_body` fixture and tests in
  `tests/unit/test_validation_errors.py` demonstrate testing both enabled and disabled cases.
* **Detail structure:** Tests should assert that `detail` contains structured error items (such as `loc`,
  `msg`, and `type`), not just free-form messages.
* **OpenAPI alignment:** Validation error responses should remain compatible with the OpenAPI schema produced
  by `create_app`, which registers `HTTPValidationError` in the components section.

## 11. Docker-based E2E execution details

E2E tests rely on `docker-compose.yml` and the `live_server` fixture to orchestrate external services.

* **Readiness checks:** Only begin assertions after the `/health` endpoint reports ready; the fixture already
  polls with a bounded timeout.
* **Failure visibility:** On startup failure, E2E fixtures log `docker compose` output; tests should treat
  these errors as indications of environment or configuration problems, not application-level failures.
* **Teardown:** E2E fixtures always call `docker compose down --remove-orphans --volumes` to clean up
  containers, networks, and volumes.

## 12. Test organization and execution

Tests are organized by scope and speed.

* **Directories:**
  * `tests/unit/`: Classic unit tests and lightweight in-process API tests.
  * `tests/integration/`: In-depth integration tests that may involve multiple components or a test database.
  * `tests/e2e/`: Full-stack Dockerized tests using `api_client`.
* **Markers:**
  * Use `@pytest.mark.e2e` for all E2E tests.
  * Use `@pytest.mark.asyncio` for async tests that await `AsyncClient` methods.
* **Typical commands:**
  * Fast local iteration: `pytest -m "not e2e"`.
  * Run all tests in CI: `pytest`.

## 13. Parallel execution considerations

Currently the test suite is designed and expected to run **sequentially**; CI does not assume parallel
execution (for example, via `pytest-xdist`). This section documents how to evolve toward safe parallel
execution and highlights patterns that rely on sequential runs.

* **Sequential-only patterns:**
  * A single shared `TEST_PORT` and `live_server` container are used for all E2E tests in a session.
  * Any future real test database instances would be shared across tests unless isolated per worker.
* **Preparing for parallelism:**
  * Avoid introducing new shared mutable global state, ports, or databases without coordination.
  * `_resolve_test_port` already guards against conflicts for the main API port; additional services
    introduced in future tests must follow similar patterns.
  * If tests begin to run in parallel, consider per-worker schemas (for example,
    `knowledge_test_1`, `knowledge_test_2`, …) and isolate `Settings` per worker.

## 14. API schema and documentation tests

Schema generation is part of the application contract and can be tested as needed.

* **OpenAPI smoke tests:** Add tests that call `app.openapi()` on a `FastAPI` instance created via
  `create_app` to ensure schema generation does not raise.
* **Key endpoint presence:** Optionally assert that critical endpoints and models (including
  `HTTPValidationError`) appear in the generated schema.
* **Scope:** Keep schema tests focused and fast; they should complement, not replace, request/response tests.

## 15. Test data setup patterns

Test data should be predictable, minimal, and expressed through public APIs whenever possible.

* **Factories and seeds:** Centralize test data creation in fixtures or future factory utilities rather than
  inlining complex objects across many tests.
* **API-first for integration/E2E:** Prefer creating data via API calls in integration and E2E tests so
  behavior matches real client interactions.
* **Direct DB seeding:** Reserve direct database writes for fixtures that clearly document their purpose and
  clean up after themselves.

## 16. Anti-patterns to avoid

* Using `monkeypatch` for dependency injection when a `dependency_overrides` hook exists.
* Forgetting to clear `app.dependency_overrides` between tests.
* Creating ad-hoc `FastAPI` apps instead of using `create_app` and the shared fixtures.
* Mixing integration and E2E tests in the same module or directory.
* Bypassing fixtures for settings, clients, or databases when shared fixtures would be clearer.
* Testing implementation details (internal function calls, log messages) instead of observable behavior and
  contracts.
