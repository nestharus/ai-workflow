# Dependency Injection Patterns

This document establishes the standard patterns for dependency injection (DI) within the `ai-workflow` application. We leverage FastAPI's powerful dependency injection system to ensure modularity, testability, and separation of concerns.

## 1. Dependency Injection Fundamentals

Dependency injection is a core feature of FastAPI that allows us to declare the components our path operation functions depend on. The system handles the resolution and injection of these dependencies automatically.

**Key Concepts:**
- **Use `Depends()`**: Declare dependencies in function signatures using `Depends()`.
- **Composition**: Dependencies can be functions or classes that can themselves have dependencies.
- **Automatic Resolution**: FastAPI resolves the dependency graph (DAG) automatically.
- **Async Support**: Dependencies can be `async def` or `def`.

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

# Define reusable type alias
CommonsDep = Annotated[dict, Depends(common_parameters)]

@app.get("/items/")
async def read_items(commons: CommonsDep):
    # 'commons' is typed as dict and injected automatically
    return commons
```

**Benefits:**
- **DRY Principle**: Define the dependency logic and type once.
- **Readability**: Function signatures become cleaner.
- **IDE Support**: Better autocompletion and type checking.

## 3. Centralized Dependency Providers

To maintain organization, reusable dependency providers should be centralized in `app/api/dependencies.py` (or versioned equivalents like `app/api/v1/dependencies.py`).

**Structure:**
- **Configuration**: Re-export settings dependencies.
- **Infrastructure**: Providers for database pools, search clients, etc.
- **Services**: Factory functions that instantiate service classes with their dependencies.

**Example Structure (`app/api/v1/dependencies.py`):**
```python
from typing import Annotated
from fastapi import Depends, Request
from app.core.config import Settings
from app.core.dependencies import get_settings
from app.services.example_service import ExampleService

# Type Aliases
SettingsDep = Annotated[Settings, Depends(get_settings)]

# Infrastructure Providers
def get_surrealdb_pool(request: Request):
    return request.app.state.surrealdb_pool

def get_elasticsearch_client(request: Request):
    return request.app.state.elasticsearch_client

# Service Providers
def get_example_service(
    settings: SettingsDep,
    pool = Depends(get_surrealdb_pool)
) -> ExampleService:
    return ExampleService(prefix=settings.API_V1_STR, pool=pool)
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

This ensures resource safety even if exceptions occur during request processing.

## 5. Settings Dependency

Application settings are loaded once and cached using `@lru_cache`. They should be injected via dependency to allow for easy overriding during tests.

**Implementation:**
```python
from functools import lru_cache
from app.core.config import Settings

@lru_cache
def get_settings() -> Settings:
    return Settings()

# Usage in routes
@app.get("/info")
async def info(settings: Annotated[Settings, Depends(get_settings)]):
    return {"app_name": settings.PROJECT_NAME}
```

## 6. Service Dependencies

We use the Service Layer pattern. Services should be injected into routers, not instantiated directly inside them. This allows us to inject mock services during testing.

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
  - Examples: `Settings` (cached), Connection Pools (`app.state`), HTTP Clients.
  - Managed via `lifespan` in `app/core/factory.py`.
  
- **Request-Scoped:** Created fresh for each request.
  - Examples: Database Sessions (acquired from pool), Current User context, specific Service instances.
  - Use `Depends` and `yield` to manage lifecycle.

## 8. Dependency Chains

FastAPI supports deep dependency chains. A controller depends on a Service, which depends on a Repository, which depends on a DB Session, which depends on a Connection Pool.

**Best Practices:**
- Keep chains distinct and logical.
- Avoid circular dependencies.
- Limit depth to 2-3 levels for maintainability.
- Let FastAPI handle the resolution; do not manually instantiate dependencies deep in the chain if they can be injected.

## 9. Router-Level Dependencies

For cross-cutting concerns that apply to a group of endpoints (like authentication or rate limiting), apply dependencies at the `APIRouter` level.

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

## 10. Testing with Dependency Overrides

The primary benefit of this architecture is testability. We can override any dependency in the graph during testing without changing application code.

**Testing Pattern:**
```python
from app.main import app
from app.api.dependencies import get_db_session

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

**Note:** Always clear `app.dependency_overrides` after tests to avoid side effects.

## 11. Anti-Patterns to Avoid

- **Creating dependencies inside route handlers:** This defeats FastAPI's dependency caching mechanism and makes testing difficult.
- **Using global variables instead of dependency injection:** Prevents effective mocking and isolation during testing.
- **Not using `yield` for cleanup in dependencies with resources:** Leads to resource leaks (e.g., open database connections).
- **Circular dependencies between modules:** Indicates poor architectural separation; resolve by refactoring shared logic or using type checking imports.
- **Over-nesting dependencies:** Keep dependency chains simple (max 2-3 levels) to maintain readability and debuggability.
