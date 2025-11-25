# Task 1 – Introduce versioned DI providers and aliases

**Location:** `app/api/v1/dependencies.py`

**Goal:** Move HTTP-facing dependency wiring into a versioned module and keep
`app/core/dependencies.py` framework-agnostic, per dependency-patterns.

## Steps

**Step 1: Create module** `app/api/v1/dependencies.py`.

**Step 2: Import foundations** including `Annotated`, `Callable` from `typing`; `Depends`, `Request`
from `fastapi`; `Settings` and `get_settings` from `app/core/settings.py` and
`app/core/dependencies.py`; `SurrealDBPool`, `ElasticsearchWrapper` from
`app/infrastructure/db_connections.py`; `ExampleRepositoryProtocol`, `ExampleRepository` from
`app/repositories/example_repository.py`; `ExampleService` from `app/services/example_service.py`.

**Step 3: Infrastructure providers (HTTP-facing):** Define `get_db_pool(request: Request)` returning
`SurrealDBPool` and `get_elasticsearch_client(request: Request)` returning `ElasticsearchWrapper`,
both retrieving from `request.app.state`.

**Step 4: Repository provider:** Define `get_example_repository` that takes a pool via `Depends` and
returns `ExampleRepository(pool=pool)`.

**Step 5: Service provider:** Define `get_example_service` that takes settings and repository via
`Depends` and returns `ExampleService(repository=repo, settings=settings)`.

**Step 6: Annotated aliases:** Create `SettingsDep`, `SurrealDBPoolDep`, `ElasticsearchWrapperDep`,
`ExampleRepositoryDep`, and `ExampleServiceDep` as `Annotated` type aliases with their respective
`Depends` declarations.

**Step 7: Update `app/api/v1/endpoints/example.py`:** Remove inline service definitions and import
`ExampleServiceDep` from `app/api/v1/dependencies.py`.

**Step 8: Update `app/api/v1/router.py`:** Import from `app/api/v1/dependencies.py` as needed.

**Step 9: Simplify `app/core/dependencies.py`:** Keep only framework-agnostic providers like
`get_settings()`. Remove any HTTP/router-specific providers that moved to the versioned module.
