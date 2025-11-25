# Repository Layer Patterns

This document defines the repository (data-access) layer patterns for the
AI Workflow system. Repositories provide a storage-agnostic abstraction over
SurrealDB, Elasticsearch, and any future data stores, and they are consumed by
services rather than routers. The guidance here complements the broader
FastAPI backend conventions captured in `fastapi-best-practices.md` and
`fastapi-best-practices-2.md`.

Repositories sit between the service layer and infrastructure modules such as
`app/infrastructure/db_connections.py`, which manage concrete connection pools
like `SurrealDBPool` and `ElasticsearchWrapper`. Services in
`app/services/` orchestrate repositories and translate domain outcomes into
errors that the HTTP layer can map to responses (see `service-patterns.md`).

## Scope for this document

This guide covers the repository/data-access layer only:

* Defining what a repository is and how it isolates data access from services.
* Repository interface design (often via `typing.Protocol`) per entity or
  aggregate.
* How repositories interact with SurrealDB and Elasticsearch connection pools.
* Query patterns: parameterized queries, pagination, filtering, and mapping to
  domain models.
* Repository-level error handling and when to raise domain exceptions.
* Repository testing strategies, including how they participate in the broader
  testing setup described in `tests/conftest.py`.

## Out of scope for this document

The following topics are documented elsewhere and are intentionally not
covered in detail here:

* Service responsibilities, orchestration, and transaction boundaries
  (see `service-patterns.md`).
* Router concerns such as path operations, status codes, and response
  documentation (see `router-patterns.md` and `api-patterns.md`).
* Low-level connection pool initialization and lifecycle; those details live in
  `connection-pooling-patterns.md` and the concrete helpers in
  `app/infrastructure/db_connections.py`.

## 1. Repository Responsibilities

Repositories encapsulate all direct interaction with databases and search
indices for a given domain aggregate or entity.

* **Persistence abstraction:** Repositories hide SurrealDB SQL, Elasticsearch
  queries, or future storage details behind a stable Python interface.
* **Service-facing contracts:** Services depend on repository interfaces, not
  on infrastructure classes like `SurrealDBPool` or `ElasticsearchWrapper`.
* **Domain model mapping:** Repositories return domain models or DTOs (for
  example, Pydantic models in `app/contracts/`), not raw database rows or
  driver-specific response structures.
* **Testability and substitution:** Repositories make it straightforward to
  substitute real implementations with fakes or mocks in services and tests,
  enabling fast, isolated testing of business logic.
* **Read/write behavior:** Repositories implement CRUD and query operations
  such as `get_by_id`, `list`, `create`, `update`, and `delete`, along with
  aggregate-specific queries.
* **HTTP agnostic:** Repositories are unaware of HTTP; they never import
  FastAPI or raise HTTP-specific exceptions.

Modern FastAPI architectures pair repositories with a dedicated service layer:
services compose multiple repositories and own business rules, while
repositories focus strictly on data access and mapping.

## 2. Repository Interface Design

Each significant aggregate or entity should have a clearly defined repository
interface. In Python, `typing.Protocol` is the recommended way to express these
interfaces without forcing inheritance.

* **Per-entity interfaces:** Prefer one repository interface per aggregate
  (for example, `UserRepositoryProtocol`, `TicketRepositoryProtocol`) instead
  of a single catch-all repository.
* **Typed CRUD operations:** All methods must have explicit type hints for
  parameters and return values.
* **Asynchronous interfaces:** Use `async def` for all I/O-bound operations so
  repositories compose naturally with async services and FastAPI routes.
* **Optional implementation of protocols:** Protocols describe the contract;
  concrete classes implement them in `app/repositories/` or the appropriate
  domain-specific module.
* **Standard surface:** A typical repository interface exposes
  `get_by_id`, `get_by_field`, `list`, `create`, `update`, and `delete`, plus
  additional domain-specific query methods where needed.

Example repository protocol:

```python
from typing import Protocol

from app.contracts.users import User


class UserRepositoryProtocol(Protocol):
    async def get_by_id(self, user_id: str) -> User | None:
        """Return a user by ID, or None if not found."""

    async def get_by_field(self, field_name: str, value: str) -> list[User]:
        """Return users matching a simple equality filter on a field."""

    async def list(self, offset: int = 0, limit: int = 100) -> list[User]:
        """Return a window of users for pagination."""

    async def create(self, user: User) -> User:
        """Persist a new user and return the stored record."""

    async def update(self, user: User) -> User:
        """Persist an updated user and return the stored record."""

    async def delete(self, user_id: str) -> None:
        """Delete a user by ID; succeed silently if already absent."""
```

Even if such protocols are not yet implemented in the codebase, consider them
the target design: services should program against these interfaces rather than
concrete storage details.

### Current reference implementation

The repository pattern is illustrated in `app/repositories/example_repository.py`,
where `ExampleRepositoryProtocol` is implemented against `SurrealDBPool` for
`save_processed_message`. Services such as `ExampleService` in
`app/services/example_service.py` depend on the protocol instead of the concrete
pool, and API v1 wiring in `app/api/v1/dependencies.py` provides the repository
via `get_example_repository` for service construction.

## 3. Implementing Repository Classes

For each protocol, implement one or more concrete repository classes that
encapsulate a specific storage technology or strategy.

* **One class per aggregate:** For clarity, create separate repositories for
  distinct aggregates rather than a monolithic "repository" that handles
  every table or index.
* **Constructor injection:** Repository constructors accept the minimal
  infrastructure dependencies required to execute queries, such as a
  `SurrealDBPool` instance, an `ElasticsearchWrapper`, or a relational
  `AsyncSession`. They do **not** reach into global application state.
* **Async data access:** All methods that hit external stores must be async and
  rely on async-aware primitives from the underlying client or wrapper.
* **No business logic:** Repositories translate repository calls into query
  operations and map results, but do not implement cross-aggregate rules or
  workflows; that belongs in services.

Example constructor pattern:

```python
from app.infrastructure.db_connections import SurrealDBPool


class SurrealUserRepository(UserRepositoryProtocol):
    def __init__(self, pool: SurrealDBPool) -> None:
        self._pool = pool

    async def get_by_id(self, user_id: str) -> User | None:
        ...  # Use parameterized SurrealDB queries here
```

Similarly, an `ElasticsearchUserSearchRepository` could depend on an
`ElasticsearchWrapper` to provide search capabilities over user indices.

## 4. SurrealDB Repository Pattern

SurrealDB access is coordinated via `SurrealDBPool` in
`app/infrastructure/db_connections.py`. Repositories should treat this pool as
their primary SurrealDB dependency.

* **Connection acquisition:** Use `async with pool.acquire() as conn` to obtain
  a connection; the pool handles timeouts and returning the connection to the
  queue.
* **Parameterized queries:** Call `await conn.query(sql, params)` with
  parameter dictionaries instead of interpolating values into SQL strings to
  avoid injection vulnerabilities.
* **Schema management:** Schema and migration operations are centralized on
  `SurrealDBPool` via helpers such as `initialize_schema()` and
  `execute_schema()`. Repositories should not define or migrate schema.
* **Auto-commit behavior:** In the current architecture, SurrealDB queries are
  auto-committed by the driver. Transaction boundary guidance in this document
  is intended to prepare for future transactional stores (for example, a
  relational database with an ORM).

Example query pattern inside a repository method:

```python
async def get_by_id(self, user_id: str) -> User | None:
    sql = "SELECT * FROM users WHERE id = $id LIMIT 1;"
    params = {"id": user_id}
    async with self._pool.acquire() as conn:
        result = await conn.query(sql, params)
    # Map SurrealDB result into a User model
    ...
```

Repositories should encapsulate the mapping from SurrealDB records to domain
models, shielding services from driver-specific result shapes.

## 5. Elasticsearch Repository Pattern

Search-oriented repositories depend on `ElasticsearchWrapper`, also defined in
`app/infrastructure/db_connections.py`. This wrapper provides async-friendly
methods and index initialization behavior.

* **Wrapper methods:** Use `search`, `index`, `bulk`, and `create_index` on
  `ElasticsearchWrapper` rather than calling the Elasticsearch client
  directly.
* **Async worker threads:** The wrapper executes blocking client calls via
  `anyio.to_thread.run_sync`, allowing repository methods to remain async.
* **Index initialization:** Indices such as `facts_index` and
  `entity_aliases_index` are created and configured during application startup
  via `initialize_indices()`. Repositories may assume these indices exist.
* **Search-only vs. write repositories:** Some repositories might only perform
  searches (for example, read-only reporting), while others support indexing
  and bulk operations.

Example pattern:

```python
from app.infrastructure.db_connections import ElasticsearchWrapper


class FactsSearchRepository:
    def __init__(self, es: ElasticsearchWrapper) -> None:
        self._es = es

    async def search_by_text(self, text: str) -> list[Fact]:
        query = {"match": {"text": text}}
        raw = await self._es.search(index="facts_index", query=query)
        # Map hits to Fact models
        ...
```

Repositories using Elasticsearch should centralize index names and query
shapes so they remain discoverable and consistent.

## 6. Transaction Management

Repositories must not commit or roll back transactions. Instead, they
participate in transactions defined and coordinated at the service layer.

* **Transaction boundaries in services:** Services determine when a logical
  unit of work begins and ends. They may wrap repository calls in an
  `async with` block or explicitly manage a unit-of-work abstraction.
* **Relational databases (future-ready guidance):** If a relational database
  and ORM such as SQLAlchemy are introduced, repositories may accept an
  `AsyncSession` and call `session.flush()` to persist changes while leaving
  `session.commit()` to the service.
* **Current SurrealDB and Elasticsearch usage:** With SurrealDB and
  Elasticsearch, each operation is effectively auto-committed by the driver.
  This document still treats transaction boundaries as a service-level
  concern to keep the architecture consistent.
* **Cross-aggregate operations:** When a use case spans multiple repositories
  (for example, writing to SurrealDB and indexing in Elasticsearch), the
  service layer coordinates all calls and defines the recovery behavior if
  one step fails.

For detailed guidance on transaction orchestration and domain error mapping,
refer to `service-patterns.md`.

## 7. Query Patterns and Pagination

Repositories define the low-level query surface for the domain. They should
support safe filtering, pagination, and sorting while mapping results into
domain models.

* **Parameterized queries:** Always prefer parameterized queries (`$id`,
  `$namespace`, etc.) with separate parameter dictionaries to avoid injection
  and to make queries reusable.
* **Pagination parameters:** Repository methods should typically accept
  `offset` and `limit` integers to express result windows. These parameters map
  to API concepts such as `page` and `page_size` from `api-patterns.md` (for
  example, `offset = (page - 1) * page_size`).
* **Domain-centric results:** Methods return lists of domain models, not raw
  database rows or Elasticsearch hits. Mapping is the repository's
  responsibility.
* **Filtering and sorting:** Expose explicit filter and sort parameters rather
  than accepting raw where clauses or query dicts from callers.
* **Bulk operations:** When the underlying store exposes efficient bulk APIs
  (such as Elasticsearch `bulk`), provide repository-level methods like
  `bulk_index` or `bulk_insert`. When only single-entity operations exist,
  services may loop and call repository methods in batches.

Example list method signature:

```python
async def list(self, offset: int = 0, limit: int = 100) -> list[User]:
    ...
```

API-layer pagination structures (such as a `Paginated[T]` contract) should
build on top of these repository-level primitives.

## 8. Error Handling in Repositories

Repositories must translate only expected conditions into domain-level
exceptions and allow unexpected infrastructure errors to propagate.

* **Expected conditions:** When a domain entity is not found or a known
  constraint is violated, repositories may raise specific exceptions such as
  `ResourceNotFoundError` or `DuplicateRecordError`, typically derived from a
  shared `DomainError` base in `app/core/errors.py`.
* **Unexpected errors:** Do not catch broad exceptions like `Exception` to
  hide database connectivity issues, timeouts, or driver bugs. Let these
  propagate so global error handlers can treat them as internal errors.
* **Logging:** When catching and translating expected errors, log only
  high-level context (entity type, identifier) and avoid including sensitive
  data or raw query text in logs.
* **HTTP mapping in outer layers:** Mapping domain exceptions to HTTP status
  codes and error payloads is the responsibility of the exception-handling
  layer documented in `exception-patterns.md` and the HTTP patterns in
  `api-patterns.md`.

This strategy mirrors common guidance in modern FastAPI architectures: keep
data-access concerns in repositories, domain semantics in services and domain
exceptions, and HTTP translation in dedicated handlers.

## 9. Repository Testing Strategies

Repositories are testable at multiple levels, from unit tests that mock
connections to integration tests that exercise real databases or indices.

* **Unit tests with fakes or mocks:** Replace `SurrealDBPool` or
  `ElasticsearchWrapper` with fakes or mocks that capture executed queries
  without performing real I/O. Assert on the SQL strings, parameter dictionaries,
  or search bodies.
* **Integration tests with real stores:** Use test databases or indices to
  verify that repository methods interact correctly with the actual storage
  engines.
* **Test fixtures:** The fixtures in `tests/conftest.py` demonstrate how the
  application is constructed for integration and E2E tests (for example,
  via `create_app` and Docker-based stacks). Repository tests can reuse this
  composition root, or a subset of it, to acquire pools and clients.
* **State isolation:** Ensure test data is reset between runs by truncating
  collections, deleting indices, or using transactional rollbacks where
  supported. Repositories should provide helper methods where necessary to
  make reset logic straightforward and safe. See
  [testing-patterns.md](plans/todo/testing-patterns.md) for concrete reset
  strategies and fixtures.

When choosing between unit and integration tests, prioritize fast unit tests
for most logic and add targeted integration coverage for critical queries and
index mappings.

## 10. Repository Factory and Dependency Injection

To integrate repositories with FastAPI and the service layer, construct them
via small factory functions that are compatible with FastAPI's dependency
injection system and the application factory in `app/core/factory.py`.

* **Factory functions:** Define simple functions like
  `def get_user_repository(pool: SurrealDBPool) -> UserRepositoryProtocol` that
  build concrete repositories.
* **App state wiring:** `create_app` stores initialized `SurrealDBPool` and
  `ElasticsearchWrapper` instances on `app.state`. Dependency functions can
  retrieve these objects from the current `FastAPI` application and pass them
  into repository factories.
* **FastAPI dependencies:** In routers, use `Depends` with repository factory
  functions to inject repositories into services or route handlers. FastAPI's
  per-request dependency cache ensures that each repository is constructed at
  most once per request.
* **Service composition:** Services receive repositories via constructors (see
  `service-patterns.md`), keeping dependencies explicit and testable.

Example factory-style dependency:

```python
from fastapi import Depends


def get_user_repository() -> UserRepositoryProtocol:
    pool = ...  # Retrieve SurrealDBPool from app state or another dependency
    return SurrealUserRepository(pool)


async def get_user_service(
    user_repo: UserRepositoryProtocol = Depends(get_user_repository),
) -> UserService:
    return UserService(user_repo=user_repo)
```

Routers then depend on `get_user_service`, while repositories remain hidden
behind the dependency graph.

## 11. Generic Repositories (Optional)

In some cases, a generic base repository can reduce duplication across
multiple concrete repositories.

* **Shared CRUD logic:** If many entities share identical CRUD semantics,
  consider extracting a base class such as `GenericRepository[T]` that
  implements `get_by_id`, `list`, `create`, and `delete`.
* **Explicit overrides:** Concrete repositories may still override specific
  methods to optimize queries, enforce additional constraints, or integrate
  search backends.
* **Avoid over-generalization:** Overly generic repositories can obscure
  behavior and make debugging difficult. Favor explicit, per-entity
  repositories when in doubt.
* **2024 guidance:** Industry best practices recommend explicit repositories
  per aggregate as the default, with generic abstractions used sparingly.

## 12. Anti-Patterns to Avoid

The following patterns undermine the goals of the repository layer and should
be avoided:

* Repositories that commit or roll back transactions instead of delegating
  transaction control to services.
* Repositories that implement business rules, workflows, or cross-aggregate
  orchestration.
* Repositories that return ORM models or raw driver responses (SurrealDB
  records, Elasticsearch hit structures) instead of domain models or DTOs.
* Global or module-level repository instances that bypass dependency
  injection and make testing difficult.
* Single "god" repositories that handle unrelated aggregates instead of
  focused, per-entity repositories.
* Over-generic repositories whose type parameters and behavior are difficult
  to understand at call sites.

By following these patterns, the repository layer remains a well-defined,
storage-agnostic abstraction that supports the service and API layers while
staying aligned with modern FastAPI and backend architecture best practices.
