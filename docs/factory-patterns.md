# Factory Patterns

This document defines the patterns used for application construction, lifespan management, and configuration in the FastAPI application. These patterns ensure testability, proper resource management, and consistent application structure.

## 1. Application Factory Pattern

We use the Application Factory pattern to create `FastAPI` instances. This allows us to pass configuration (Settings) at runtime, which is crucial for testing and different deployment environments.

**Rationale:**
- **Testability:** Allows creating app instances with test-specific settings.
- **Isolation:** Each call creates a fresh app instance, preventing state leakage between tests.
- **Configuration:** Centralizes app configuration in one place.

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

**Implementation:**

```python
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    # Add other custom handlers here
```

## 5. Middleware Configuration

Middleware is configured in the factory using `app.add_middleware()`.

**Rationale:**
- **Ordering:** Centralized configuration ensures middleware is applied in the correct order (e.g., Security headers before GZip).
- **Configurability:** Middleware can be enabled/disabled based on `Settings`.

*(Detailed middleware patterns are documented in `docs/middleware-patterns.md`)*

## 6. Router Registration

Routers are registered in the factory, typically with a version prefix.

**Rationale:**
- **Versioning:** Enforces API versioning (e.g., `/api/v1`) at the root level.
- **Modularity:** Keeps the main app file clean by importing routers from modules.

**Implementation:**

```python
    # Mount versioned API router; keeps new endpoints scoped under /api/v1.
    app.include_router(api_router, prefix="/api/v1")
    
    # Internal endpoints (like health) can be separate
    app.add_api_route("/health", health_check, methods=["GET"], include_in_schema=False)
```

## 7. OpenAPI Customization

We customize the OpenAPI schema generation to improve documentation quality and client SDK generation.

**Rationale:**
- **Clarity:** Flattens nested `$defs` which can confuse some OpenAPI code generators.
- **Accuracy:** Ensures error schemas (like `HTTPValidationError`) are correctly exposed.

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

**Implementation:**

```python
    app.state.settings = settings
```

## 9. Testing Factory Usage

Tests utilize the factory pattern to create isolated app instances.

**Rationale:**
- **Isolation:** Every test (or test session) gets a clean app configuration.
- **Mocking:** Allows passing modified settings or overriding dependencies on the specific app instance.

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

## 10. Anti-Patterns to Avoid

1.  **Global App Instance:**
    *   *Avoid:* `app = FastAPI()` at the module level in `main.py`.
    *   *Why:* Hard to test, shared state issues, difficult to configure differently for tests.

2.  **Initialization Outside Lifespan:**
    *   *Avoid:* Initializing DB clients globally or in `__init__` blocks without cleanup.
    *   *Why:* Leads to resource leaks (open connections) and errors during testing (event loop mismatch).

3.  **Hardcoded Configuration:**
    *   *Avoid:* `dsn = "postgres://..."` inside the factory.
    *   *Why:* Violates 12-factor app principles; use `Settings` injection.

4.  **Complex Logic in Factory:**
    *   *Avoid:* Putting business logic or complex setup directly in `create_app`.
    *   *Why:* Hard to read and test. Delegate to helper functions (like `create_surrealdb_pool`).
