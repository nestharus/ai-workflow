# Dependency Injection Patterns

This document establishes the standard patterns for dependency injection (DI) within the `ai-workflow` application. We leverage FastAPI's powerful dependency injection system to ensure modularity, testability, and separation of concerns. This guide sits alongside `api-patterns.md`, `router-patterns.md`, `service-patterns.md`, and `factory-patterns.md` and should be read together with the FastAPI best-practices documents such as `fastapi-best-practices.md` and `fastapi-best-practices-2.md`.

## 1. Dependency Injection Fundamentals

Dependency injection is a core feature of FastAPI that allows us to declare the components our path operation functions depend on. The system handles the resolution and injection of these dependencies automatically.

For each incoming request, FastAPI builds a dependency tree starting from the path operation and following every `Depends()` and sub-dependency. Each node in this tree is executed at most once per request thanks to FastAPI's per-request dependency cache; if the same dependency appears multiple times in the tree, its result is reused unless `use_cache=False` is passed to `Depends()`.

**Key Concepts:**
- **Use `Depends()`**: Declare dependencies in function signatures using `Depends()`.
- **Composition**: Dependencies can be functions or classes that can themselves have dependencies.
- **Automatic Resolution**: FastAPI resolves the dependency graph (DAG) automatically.
- **Async Support**: Dependencies can be `async def` or `def`.
- **Per-request caching**: Dependency return values are cached per request and reused when the same dependency is needed multiple times.

**Basic Example:**
```python
from fastapi import Depends, FastAPI

def common_parameters(q: str | None = None, skip: int = 0, limit: int = 100):
    return {"q": q, "skip": skip, "limit": limit}

@app.get("/items/")
async def read_items(commons: dict = Depends(common_parameters)):
    return commons
```

## 2. Annotated Type Aliases (2024 Best Practice)

We adopt the modern pattern of using `Annotated` type aliases for dependencies. This reduces code duplication in route handlers and provides clearer type hints.

**Standard Pattern:**
```python
from typing import Annotated
from fastapi import Depends
from app.contracts.pagination import Pagination

def common_parameters(q: str | None = None, skip: int = 0, limit: int = 100):
    return {"q": q, "skip": skip, "limit": limit}

def common_pagination_params(q: str | None = None, page: int = 1, size: int = 50) -> Pagination:
    """Normalize and validate pagination parameters into a Pagination value object."""
    return Pagination(q=q, page=page, size=size)

# Define reusable type aliases
CommonsDep = Annotated[dict, Depends(common_parameters)]
PageParams = Annotated[Pagination, Depends(common_pagination_params)]

@app.get("/items/")
async def read_items(commons: CommonsDep, page: PageParams):
    # 'commons' and 'page' are fully-typed injected values
    ...
```

**Benefits:**
- **DRY Principle**: Define the dependency logic and type once.
- **Readability**: Function signatures become cleaner.
- **IDE Support**: Better autocompletion and type checking.

Store shared dependency aliases in `app/api/v1/dependencies.py` next to the provider functions so routers and services have a single, versioned import location.

## 3. Centralized Dependency Providers

To maintain organization, reusable dependency providers should be centralized in `app/api/v1/dependencies.py` (or the appropriate versioned module) rather than being defined inline in individual routers.

**Structure:**
- **Configuration**: Re-export settings dependencies.
- **Infrastructure**: Providers for database pools, search clients, etc.
- **Services**: Factory functions that instantiate service classes with their dependencies.

At a lower level, `app/core/dependencies.py` exposes framework-agnostic providers such as `get_settings()`, `app/infrastructure/db_connections.py` exposes connection factories and wrappers such as `create_surrealdb_pool()` and `create_elasticsearch_wrapper()` (built on `SurrealDBPool` and `ElasticsearchWrapper`), and `app/core/factory.py` wires these into `app.state` during application startup. High-level providers in `app/api/v1/dependencies.py` should sit on top of this foundation and be the only DI surface imported by routers.

**Example Structure (`app/api/v1/dependencies.py`):**
```python
from typing import Annotated
from fastapi import Depends, Request
from app.core.settings import Settings
from app.core.dependencies import get_settings
from app.infrastructure.db_connections import SurrealDBPool, ElasticsearchWrapper
from app.services.orchestrator_service import OrchestratorService

# Type Aliases
SettingsDep = Annotated[Settings, Depends(get_settings)]

# Infrastructure Providers
def get_surrealdb_pool(request: Request) -> SurrealDBPool:
    return request.app.state.surrealdb_pool

def get_elasticsearch_client(request: Request) -> ElasticsearchWrapper:
    return request.app.state.elasticsearch_client

# Service Providers
def get_orchestrator_service(
    settings: SettingsDep,
    pool: Annotated[SurrealDBPool, Depends(get_surrealdb_pool)],
    search: Annotated[ElasticsearchWrapper, Depends(get_elasticsearch_client)],
) -> OrchestratorService:
    return OrchestratorService(settings=settings, db_pool=pool, search=search)
```

## 4. Database Session Dependencies

Database connections should never be global variables. Instead, they should be injected as dependencies. Use the `yield` pattern to ensure connections are properly closed or returned to the pool after the request is processed.

**Pattern:**
```python
from typing import AsyncGenerator

async def get_db_session(pool = Depends(get_surrealdb_pool)) -> AsyncGenerator:
    # Acquire connection from pool
    async with pool.acquire() as conn:
        yield conn
        # Connection is automatically released back to pool after yield
```

This ensures resource safety even if exceptions occur during request processing. For SurrealDB, this pattern should be implemented using the `SurrealDBPool.acquire()` async context manager exposed by `app/infrastructure/db_connections.py` so that individual `Surreal` connections remain request-scoped while the underlying pool is shared.

Keep the session dependency itself thin: `get_db_session` is responsible only for acquiring and releasing a connection, while repositories and services encapsulate all query logic, transactions, and domain workflows on top of that session.

## 5. Settings Dependency

Application settings are loaded once and cached using `@lru_cache`. They should be injected via dependency to allow for easy overriding during tests.

**Implementation (see `app/core/dependencies.py`):**
```python
from functools import lru_cache
from app.core.settings import Settings

@lru_cache
def get_settings() -> Settings:
    return Settings()

# Usage in routes
@app.get("/info")
async def info(settings: Annotated[Settings, Depends(get_settings)]):
    return {"app_name": settings.PROJECT_NAME}
```

In tests, `get_settings` should be overridden via `app.dependency_overrides` to inject test-specific configuration, for example:

```python
from app.core.dependencies import get_settings

app.dependency_overrides[get_settings] = lambda: Settings(environment="test")
...
app.dependency_overrides.clear()
```

## 6. Service Dependencies

We use the Service Layer pattern. Services should be injected into routers, not instantiated directly inside them. This allows us to inject mock services during testing and keeps HTTP concerns separate from domain logic.

Services encapsulate domain workflows and are expected to raise domain-specific exceptions (for example `TicketNotFoundError` or `InvalidTransitionError`) rather than HTTP or framework-level exceptions; routers and shared exception handlers (such as those in `app/core/exceptions.py`) are responsible for translating these into appropriate HTTP responses.

**Factory Pattern:**
Create factory functions that assemble the service with its required dependencies (repositories, other services, settings).

```python
def get_user_service(
    db_session = Depends(get_db_session),
    settings: Settings = Depends(get_settings)
) -> UserService:
    return UserService(session=db_session, config=settings)

# In Router
@router.post("/users/")
async def create_user(
    user_in: UserCreate,
    service: Annotated[UserService, Depends(get_user_service)]
):
    return await service.create(user_in)
```

## 7. Request-Scoped vs Singleton Dependencies

Understand the lifecycle of your dependencies:

- **Singleton (Application Scope):** Created once per application lifecycle.
  - Examples: `Settings` (cached via `get_settings()`), connection pools such as `SurrealDBPool` and `ElasticsearchWrapper` stored on `app.state`, and shared HTTP clients.
  - Managed via the application `lifespan` in `app/core/factory.py`.
  
- **Request-Scoped:** Created fresh for each request.
  - Examples: Database sessions or connections acquired from `SurrealDBPool`, the current user context, and service instances that depend on request-scoped resources.
  - Use `Depends` and `yield` to manage lifecycle.

## 8. Dependency Chains

FastAPI supports deep dependency chains. A controller depends on a Service, which depends on a Repository, which depends on a DB Session, which depends on a Connection Pool.

**Best Practices:**
- Keep chains distinct and logical.
- Avoid circular dependencies.
- Limit depth to 2-3 levels for maintainability.
- Let FastAPI handle the resolution; do not manually instantiate dependencies deep in the chain if they can be injected.

## 9. Router-Level Dependencies

For cross-cutting concerns that apply to a group of endpoints (like authentication, rate limiting, or request logging), apply dependencies at the `APIRouter` level.

**Usage:**
```python
router = APIRouter(
    dependencies=[Depends(verify_token), Depends(check_rate_limit)]
)

@router.get("/secure-data")
async def secure_endpoint():
    # verify_token and check_rate_limit run before this
    pass
```

When declaring security schemes that need scopes (for example OAuth2), use `Security()` instead of `Depends()` in the dependency definition, but still attach those dependencies to routers in the same way. API key–based schemes (for example an `APIKeyHeader` or `APIKeyQuery` dependency) should also be wired at the router level when they guard an entire group of endpoints.

## 10. Testing with Dependency Overrides

The primary benefit of this architecture is testability. We can override any dependency in the graph during testing without changing application code.

**Testing Pattern:**
```python
from app.main import app
from app.api.v1.dependencies import get_db_session

async def override_get_db_session():
    async with test_db_pool.acquire() as conn:
        yield conn

def test_create_item():
    # Override the dependency
    app.dependency_overrides[get_db_session] = override_get_db_session
    
    # Run test
    client.post("/items/", json={...})
    
    # Clean up
    app.dependency_overrides = {}
```

The test suite's composition root in `tests/conftest.py` centralizes fixture patterns: integration tests use `test_settings`, `test_app`, and `async_client` fixtures to exercise the in-process app and can rely on `app.dependency_overrides` to swap dependencies such as `get_settings`, `get_surrealdb_pool`, or service factories, while E2E tests use the `live_server` and `api_client` fixtures to hit a dockerized stack without overrides so the full dependency graph is exercised end-to-end.

**Note:** Always clear `app.dependency_overrides` after tests to avoid side effects.

## 11. Anti-Patterns to Avoid

- **Creating dependencies inside route handlers:** This defeats FastAPI's dependency caching mechanism and makes testing difficult.
- **Using global variables instead of dependency injection:** Prevents effective mocking and isolation during testing.
- **Not using `yield` for cleanup in dependencies with resources:** Leads to resource leaks (e.g., open database connections).
- **Circular dependencies between modules:** Indicates poor architectural separation; resolve by refactoring shared logic or using type checking imports.
- **Over-nesting dependencies:** Keep dependency chains simple (max 2-3 levels) to maintain readability and debuggability.
