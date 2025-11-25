# Task 9 – Repository module and ExampleService dependency

**Locations:** `app/repositories/`, `ExampleService`

**Goal:** Introduce a repository package and have services depend on repository protocols instead
of concrete DB clients.

## Steps

**Step 1:** Create `app/repositories/__init__.py` (empty or with basic exports).

**Step 2: Create `app/repositories/example_repository.py`:** Import `Protocol` from `typing`,
`SurrealDBPool` from `app/infrastructure/db_connections.py`, and any needed contracts. Define
`ExampleRepositoryProtocol` with a `save_processed_message` method. Implement `ExampleRepository`
using `SurrealDBPool.acquire()` and parameterized queries.

**Step 3: Update `ExampleService`:** Type-hint dependency as `ExampleRepositoryProtocol`. Use
`settings.example_prefix` in processing logic. Call the repository to demonstrate usage. Ensure
no direct DB or HTTP client imports in the service.

**Step 4: Update `app/api/v1/dependencies.py`:** Ensure `get_example_repository` returns
`ExampleRepository` typed as `ExampleRepositoryProtocol`. Ensure `get_example_service` passes both
repository and settings into `ExampleService`.

**Step 5: Update plan docs:** Describe the new `app/repositories/` package and how it illustrates
the repository architecture.

## Implementation Notes

* Added `app/repositories/example_repository.py` defining
  `ExampleRepositoryProtocol.save_processed_message` and a SurrealDB-backed implementation using
  parameterized queries.
* `ExampleService` now depends on the repository protocol, uses `settings.example_prefix`, and
  persists processed messages via the repository.
* API v1 dependencies wire the repository provider and inject settings into `ExampleService`.
