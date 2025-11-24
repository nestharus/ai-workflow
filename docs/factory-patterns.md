# Factory Patterns

This document defines the patterns used for application construction, lifespan management, and configuration in the FastAPI application. These patterns ensure testability, proper resource management, and consistent application structure, and they align with the guidance in `fastapi-best-practices.md` and `fastapi-best-practices-2.md`.

Primary runtime references:

* `app/core/factory.py` – FastAPI application construction, lifespan wiring, middleware, router registration, and OpenAPI customization.
* `app/core/settings.py` – application settings model and validation rules used to configure `create_app`.
* `app/core/exceptions.py` – global exception and validation handlers registered from the factory.
* `app/infrastructure/db_connections.py` – SurrealDB and Elasticsearch connection factories used during application startup.
* `tests/conftest.py` – test application factory usage, dependency overrides, and test-specific settings.

## 1. Application Factory Pattern

We use the Application Factory pattern to create `FastAPI` instances. This allows us to pass configuration (Settings) at runtime, which is crucial for testing and different deployment environments.

**Rationale:**
- **Testability:** Allows creating app instances with test-specific settings.
- **Isolation:** Each call creates a fresh app instance, preventing state leakage between tests.
- **Configuration:** Centralizes app configuration in one place.
- **Single wiring point:** All routers, middleware, and exception handlers are registered in `create_app`, so the entire HTTP surface is wired from a single function.

**Implementation:**

```python
def create_app(settings: Settings) -> FastAPI:
    """Construct and configure the FastAPI application instance.

    Args:
        settings: Validated runtime options.

    Returns:
        FastAPI: Application wired with orjson responses.
    """
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=settings.app_description,
        docs_url="/docs",
        redoc_url="/redoc",
        default_response_class=ORJSONResponse,
        lifespan=_lifespan(settings),
    )
    app.state.settings = settings
    
    # ... router registration and configuration ...

    return app
```

## 2. Lifespan Management

We use FastAPI's `lifespan` context manager to handle startup and shutdown events. This is the modern replacement for `on_event("startup")` and `on_event("shutdown")`.

**Rationale:**
- **Resource Safety:** Guarantees cleanup code runs even if errors occur during startup (when structured correctly).
- **Async Support:** Fully supports async initialization of database pools and clients.
- **Context:** Keeps setup and teardown logic together in a single function.

**Implementation:**

```python
def _lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        surreal_pool: SurrealDBPool | None = None
        elasticsearch_client: ElasticsearchWrapper | None = None
        try:
            # Startup Phase
            surreal_pool = await create_surrealdb_pool(settings)
            app.state.surrealdb_pool = surreal_pool
            logger.info("Initialized SurrealDB pool")

            elasticsearch_client = await create_elasticsearch_wrapper(settings)
            app.state.elasticsearch_client = elasticsearch_client
            logger.info("Initialized Elasticsearch client")

            yield
        except Exception:
            logger.exception("Failed to initialize application resources")
            raise
        finally:
            # Shutdown Phase
            if elasticsearch_client is not None:
                try:
                    await elasticsearch_client.close()
                except Exception:
                    logger.exception("Failed to close Elasticsearch client cleanly")
            if surreal_pool is not None:
                try:
                    await surreal_pool.close()
                except Exception:
                    logger.exception("Failed to close SurrealDB pool cleanly")

    return lifespan
```

## 3. Resource Initialization

Resources like database connections are initialized using dedicated factory functions called during the lifespan startup. They are stored in `app.state` for access via dependencies.

**Rationale:**
- **Separation of Concerns:** Connection logic is separated from the app factory.
- **Dependency Injection:** Storing in `app.state` allows dependencies to retrieve these resources without global variables.
- **Centralized infrastructure wiring:** Factories such as `create_surrealdb_pool()` and `create_elasticsearch_wrapper()` live in `app/infrastructure/db_connections.py` and are invoked from the lifespan function so that all long-lived connections are initialized and cleaned up in one place.
- **Caches as first-class resources:** Caches (for example Redis clients or in-memory caches) should also be created in the lifespan startup block, stored on `app.state` (for example `app.state.cache`), and closed or flushed in the shutdown phase alongside database and search clients.
- **Schema and index setup:** Startup logic should ensure both SurrealDB schemas and Elasticsearch indices exist (for example via `initialize_schema()` on the SurrealDB pool and an index-initialization helper on the Elasticsearch wrapper) so that requests do not have to perform ad-hoc schema or index creation.

**Implementation:**

```python
async def create_surrealdb_pool(settings: Settings) -> SurrealDBPool:
    """Factory that builds and initializes a SurrealDB pool from settings."""
    pool = SurrealDBPool(
        dsn=settings.surrealdb_url,
        # ... other args ...
    )
    await pool.init()
    try:
        await pool.initialize_schema()
    except Exception:
        await pool.close()
        raise
    return pool
```

## 4. Exception Handler Registration

Custom exception handlers are registered in the factory to provide consistent error responses across the application.

**Rationale:**
- **Consistency:** Ensures all errors follow a standard JSON format.
- **Security:** Prevents leaking internal stack traces in production.
- **Separation of concerns:** Handlers are implemented in `app/core/exceptions.py` and use contracts from `app/contracts/errors.py` (for example `HTTPValidationError` and the `AppError` envelope) so that the factory only wires them to the app.
 - **Predictable ordering:** Specific exception handlers (such as `RequestValidationError` or `DomainError`) must be registered before generic fallbacks (for example a catch-all `Exception` handler) so that the most specific handler is invoked first.

**Implementation:**

```python
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(DomainError, domain_exception_handler)
    # Add generic fallback handlers (for example Exception) after specific ones
```

## 5. Middleware Configuration

Middleware is configured in the factory using `app.add_middleware()`.

**Rationale:**
- **Ordering:** Centralized configuration ensures middleware is applied in a deliberate order (for example `TrustedHostMiddleware` → security headers → `GZipMiddleware`) so behavior is predictable.
- **Configurability:** Middleware can be enabled or disabled based on `Settings` values (such as allowed hosts, CORS origins, or compression settings) instead of hard-coded constants.
- **Proxy awareness:** When running behind a reverse proxy, configure `ProxyHeadersMiddleware` or Uvicorn proxy header options in the factory so that client IPs and schemes are preserved correctly.

*(Detailed middleware patterns are documented in `docs/middleware-patterns.md`)*

## 6. Router Registration

Routers are registered in the factory, typically with a version prefix.

**Rationale:**
- **Versioning:** Enforces API versioning (e.g., `/api/v1`) at the root level.
- **Modularity:** Keeps the main app file clean by importing routers from modules.
 - **Configurability:** The API prefix should be derived from settings (for example `settings.api_prefix`) so that environments can opt into different versions or prefixes without code changes.

**Implementation:**

```python
    # Mount versioned API router; keeps new endpoints scoped under a versioned API prefix.
    app.include_router(api_router, prefix=settings.api_prefix)

    # Internal endpoints (like health) can be separate
    app.add_api_route("/health", health_check, methods=["GET"], include_in_schema=False)
```

## 7. OpenAPI Customization

We customize the OpenAPI schema generation to improve documentation quality and client SDK generation.

**Rationale:**
- **Clarity:** Flattens nested `$defs` which can confuse some OpenAPI code generators.
- **Accuracy:** Ensures error schemas (like `HTTPValidationError`) are correctly exposed.
- **Shared contracts:** Registers shared error and metadata schemas (for example `HTTPValidationError` and `AppError` from `app/contracts/errors.py`) under `components.schemas` so that routes can reference them consistently.
- **Validation shape stability:** Normalizes validation error schemas to match the global error-handling strategy described in `api-patterns.md`, making it easier for clients and tools to depend on a stable error format.

**Implementation:**

```python
    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        app.openapi_schema = get_openapi(...)
        
        # ... customization logic ...
        schema_definitions = app.openapi_schema.setdefault("components", {}).setdefault("schemas", {})
        # Flatten definitions logic
        
        return app.openapi_schema

    app.openapi = custom_openapi
```

## 8. Settings Integration

The `Settings` object is stored in `app.state` immediately after creation.

**Rationale:**
- **Access:** Makes settings available to any part of the application that has access to the `Request` or `App` object.
- **Runtime Config:** Allows dependencies to read configuration without importing a global settings object.
- **Environment-driven configuration:** `Settings` (defined in `app/core/settings.py` using Pydantic settings) reads values from environment variables, allowing configuration to differ between development, testing, and production without code changes.
 - **Feature flags:** Settings provide feature flags (for example `enable_experimental_routes`) that can be read in the factory to conditionally include routers, middleware, or behaviors per environment.

For the full structure and validation rules of `Settings`, see `settings-patterns.md`, which documents how configuration fields are modeled and validated.

**Implementation:**

```python
    app.state.settings = settings
```

Settings are typically consumed via dependency injection rather than imported as globals. A common pattern is a dependency that reads from `request.app.state.settings`:

```python
from fastapi import Depends, Request


def get_settings(request: Request) -> Settings:
    return request.app.state.settings
```

Routes and services can then depend on `Settings` directly, for example `def some_route(settings: Settings = Depends(get_settings))`, ensuring all configuration flows through the factory-initialized application state.

## 9. Testing Factory Usage

Tests utilize the factory pattern to create isolated app instances.

**Rationale:**
- **Isolation:** Every test (or test session) gets a clean app configuration.
- **Mocking:** Allows passing modified settings or overriding dependencies on the specific app instance.
- **Environment separation:** Test-specific settings (for example different database URLs or reduced pool sizes) can be injected via the factory without affecting non-test environments.
 - **Preferred override mechanism:** FastAPI's dependency override system should be used instead of relying solely on monkeypatching, keeping test wiring aligned with the production factory.

**Implementation:**

```python
@pytest.fixture
def test_settings() -> Settings:
    return Settings()

@pytest.fixture
def test_app(test_settings: Settings) -> FastAPI:
    """Create a FastAPI application instance for testing."""
    return create_app(test_settings)
```

In the real test suite, these patterns live in `tests/conftest.py`, and tests use FastAPI's dependency override system (see `api-testing-patterns.md`) to replace external integrations with fakes while still exercising the same `create_app` wiring.
Monkeypatching may still be used for low-level edge cases, but it must not be the primary mechanism for swapping dependencies when a standard override can be applied.

## 10. Anti-Patterns to Avoid

1.  **Global App Instance:**
    *   *Avoid:* `app = FastAPI()` at the module level in `main.py`.
    *   *Why:* Hard to test, shared state issues, difficult to configure differently for tests.

2.  **Initialization Outside Lifespan:**
    *   *Avoid:* Initializing DB clients globally or in `__init__` blocks without cleanup.
    *   *Why:* Leads to resource leaks (open connections) and errors during testing (event loop mismatch).

3.  **Missing Shutdown Cleanup:**
    *   *Avoid:* Creating connection pools or clients during startup without closing them in the lifespan shutdown phase.
    *   *Why:* Causes long-lived connections to remain open across deploys or tests, leading to resource exhaustion and flaky behavior.

4.  **Hardcoded Configuration:**
    *   *Avoid:* `dsn = "postgres://..."` inside the factory.
    *   *Why:* Violates 12-factor app principles; use `Settings` injection.

5.  **Complex Logic in Factory:**
    *   *Avoid:* Putting business logic or complex setup directly in `create_app`.
    *   *Why:* Hard to read and test. Delegate to helper functions (like `create_surrealdb_pool`).
