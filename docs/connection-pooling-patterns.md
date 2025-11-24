# Connection & Resource Pooling Patterns

This document describes how the application creates, reuses, and cleans up
long-lived, pooled resources such as database connections, search clients, and
HTTP clients. It complements the FastAPI best-practices documents and the
router, service, repository, settings, and exception pattern guides.

In this codebase, the FastAPI application factory in `app/core/factory.py`
initializes shared resources during the application lifespan and stores them on
`app.state`. Infrastructure components in `app/infrastructure/db_connections.py`
encapsulate SurrealDB and Elasticsearch connection management, while
configuration for pool sizes and timeouts lives in `app/core/settings.py`.

## Scope for this document

This guide focuses on connection and resource pooling patterns:

*   Creating connection pools once at application startup and reusing them for
    all requests.
*   Managing SurrealDB pools via `SurrealDBPool` and the
    `create_surrealdb_pool()` factory.
*   Managing Elasticsearch connections via `ElasticsearchWrapper` and
    `create_elasticsearch_wrapper()`.
*   Reusing outbound HTTP client instances (for example,
    `httpx.AsyncClient`) instead of creating new clients per request.
*   Tuning pool sizes and timeouts, handling pool exhaustion, and shutting
    down cleanly.

## Out of scope for this document

The following topics are documented elsewhere and are intentionally not
covered in detail here:

*   Repository APIs built on top of connection pools (see
    `repository-patterns.md`).
*   Domain-level service orchestration and business rules (see
    `service-patterns.md`).
*   Settings modeling beyond pool-related configuration (see
    `settings-patterns.md`).
*   HTTP error schemas and validation behavior (see exception and error
    handling documentation).

## 1. Connection pooling fundamentals

Connection pools and other long-lived resources must be created once during
application startup and reused across all incoming requests.

**Core principles:**

*   **Startup-only creation:** Create pools and clients during the FastAPI
    application lifespan startup, before the app starts serving traffic.
*   **No per-request pools:** Never create database engines, connection pools,
    or HTTP clients inside route handlers or other per-request code paths.
*   **Shared state:** Store shared resources on `app.state` (for example,
    `app.state.surrealdb_pool`, `app.state.elasticsearch_client`, and
    `app.state.http_client`) so they can be accessed via dependencies.
*   **Lifespan-managed cleanup:** Close all long-lived resources in the
    lifespan shutdown callback to avoid leaking sockets or threads.

The application factory in `create_app()` uses a lifespan context manager
defined by `_lifespan()` in `app/core/factory.py`. This function calls
`create_surrealdb_pool()` and `create_elasticsearch_wrapper()` during startup,
attaches them to `app.state`, and guarantees that their `close()` methods are
called during shutdown even if initialization fails.

## 2. SurrealDB connection pool

SurrealDB connections are managed by the `SurrealDBPool` class in
`app/infrastructure/db_connections.py`.

**Key characteristics:**

*   **Async queue-based pool:** `SurrealDBPool` maintains multiple WebSocket
    connections to SurrealDB in an `asyncio.Queue`. Connections are established
    up front with authentication and database selection applied.
*   **Configurable size:** The pool size is controlled via
    `Settings.surrealdb_pool_size`, allowing environments to tune concurrency
    without code changes.
*   **Pre-authenticated connections:** Each connection is created once, signed
    in, and pointed at the configured namespace and database during pool
    initialization rather than per request.
*   **Context-managed acquire:** The `acquire()` method is an async context
    manager that enforces an acquire timeout and returns the connection to the
    pool when the context exits.

Typical usage pattern inside infrastructure or repository code is:

```python
async with surrealdb_pool.acquire() as conn:
    result = await conn.query(sql, params)
```

This pattern ensures that every acquired connection is returned to the pool
even if an exception is raised.

## 3. SurrealDB pool configuration

Pool configuration is driven by the `Settings` model in
`app/core/settings.py`.

**Recommended settings:**

*   **Pool size:** Start with a conservative default (for example,
    `surrealdb_pool_size = 5`). Size should be increased only when metrics
    indicate SurrealDB is the bottleneck and the database can safely sustain
    more concurrent connections.
*   **Acquire timeout:** Use an `acquire_timeout` on the order of several
    seconds. The `SurrealDBPool` constructor accepts this timeout and applies
    it via `asyncio.wait_for()` inside `acquire()`.
*   **Environment-specific tuning:** Treat pool size and acquire timeout as
    environment-specific knobs. For example, local development may use a small
    pool, staging might use slightly larger values, and production should be
    tuned based on real traffic patterns and database limits.

Pool-related settings should focus on how many connections are created and how
long callers wait to acquire them, not on unrelated SurrealDB configuration.

## 4. SurrealDB connection lifecycle

The SurrealDB pool lifecycle is managed by the FastAPI application lifespan.

**Startup:**

*   `create_surrealdb_pool(settings)` builds a `SurrealDBPool` using values
    from `Settings` and calls `pool.init()`.
*   As part of initialization, the pool authenticates each connection and
    selects the configured namespace and database.
*   The pool is attached to `app.state.surrealdb_pool` inside `_lifespan()` so
    dependencies can retrieve it.

**Schema initialization:**

*   After creating the pool, `create_surrealdb_pool()` calls
    `pool.initialize_schema()` to define schema tables, relationships, and
    vector indexes.
*   If schema initialization fails, the factory closes the pool and propagates
    the error so the application fails fast at startup rather than running
    with a partially applied schema.

**Shutdown:**

*   During application shutdown, the lifespan context manager calls
    `surrealdb_pool.close()` to close all connections and release resources.
*   Cleanup is wrapped in defensive logging so a failure to close one
    connection does not prevent the process from shutting down.

## 5. Elasticsearch connection pool

Elasticsearch connectivity is managed by `ElasticsearchWrapper` in
`app/infrastructure/db_connections.py`, which adapts the synchronous
`elasticsearch` Python client for use in an async application.

**Key characteristics:**

*   **Client-managed pooling:** The underlying Elasticsearch client maintains a
    pool of HTTP connections per node. The
    `connections_per_node` parameter, configured from `Settings`, controls how
    many concurrent HTTP connections the client will keep open to each node.
*   **Async wrapper:** All potentially blocking operations (`ping`, `search`,
    `index`, `bulk`, `indices.create`) are executed via
    `anyio.to_thread.run_sync()` so that synchronous I/O runs in a worker
    thread instead of blocking the async event loop.
*   **Initialization handshake:** `ElasticsearchWrapper.init()` pings the
    cluster to verify connectivity before marking the client initialized.
*   **Index initialization:** `initialize_indices()` uses the shared client to
    create indices with configured shard and replica counts. It gracefully
    handles the case where indices already exist.

## 6. Elasticsearch configuration

Elasticsearch connection-related options are also defined on `Settings` in
`app/core/settings.py`.

**Recommended configuration:**

*   **Connections per node:** `elasticsearch_connections_per_node` should start
    with a moderate value (for example, 25) that balances concurrency and
    memory usage. Increase only if metrics show Elasticsearch is underutilized
    and connection pool exhaustion is occurring.
*   **Request timeouts:** `elasticsearch_request_timeout` defines how long the
    client waits for a response before timing out. Use values that reflect
    expected query latency and avoid unbounded waits.
*   **Retries on timeout:** Enable or disable `retry_on_timeout` based on
    service requirements. Retrying on timeouts can smooth over transient
    network issues but should not mask systemic performance problems.
*   **Hosts list:** `elasticsearch_url` may point at a load balancer or a
    list of node URLs. The client will maintain a pool of connections across
    the configured nodes.

In most cases, developers should rely on the Elasticsearch client to manage
its own connection pool and avoid manually opening or closing HTTP
connections.

## 7. Pool size tuning

Pool sizes must be tuned based on real usage and backend limits.

**Guidelines:**

*   **Conservative defaults:** Start with small values (for example,
    5–10 connections per pool or per node) instead of guessing large pool
    sizes.
*   **Respect database limits:** Ensure
    `workers × surrealdb_pool_size` stays comfortably below the SurrealDB
    server's maximum connections.
*   **Observe metrics:** Track acquire timeouts, request latencies, and error
    rates. Use these signals to decide whether to adjust pool sizes or
    optimize queries.
*   **Scale thoughtfully:** Increase pool sizes incrementally and monitor
    impact rather than making large jumps.

## 8. Connection timeout handling

Timeouts are a primary signal of pool exhaustion or downstream slowness.

**Patterns:**

*   **Acquire timeouts:** `SurrealDBPool.acquire()` uses
    `asyncio.wait_for()` to enforce an acquire timeout. Timeouts should be
    logged with enough context to diagnose whether they are caused by pool
    exhaustion or backend slowness.
*   **Request timeouts:** `ElasticsearchWrapper` uses the client's
    `request_timeout` setting to bound search and indexing operations.
*   **Logging and alerts:** Repeated timeouts should trigger investigation
    into query patterns, indexing strategies, or pool configuration rather
    than simply increasing pool sizes.
*   **Fail fast:** Where appropriate, surface timeout failures through domain
    exceptions that are converted into HTTP errors by global exception
    handlers, rather than hanging requests indefinitely.

Before increasing pool sizes, always consider whether timeouts can be reduced
by query optimization, caching, or modestly higher timeouts that better match
realistic response times.

## 9. Connection recycling

Long-lived connections are efficient, but they must tolerate network issues
and intermediaries that may silently drop idle connections.

**SurrealDB:**

*   `SurrealDBPool` generally maintains connections for the lifetime of the
    application process.
*   If connections become stale due to network interruptions or server
    restarts, the pool should be prepared to recreate connections or rebuild
    the pool. Future enhancements may add explicit recycling or health checks
    to the pool implementation.

**Elasticsearch and other HTTP backends:**

*   The Elasticsearch client already handles dead node detection and
    connection refreshing via its internal transport.
*   For HTTP-based backends (including Elasticsearch and external APIs), it is
    reasonable to periodically recycle connections (for example, every 30
    minutes) to avoid issues with proxies or load balancers that close idle
    connections.
*   When designing HTTP client wrappers, consider exposing hooks or
    maintenance tasks that can refresh clients or clear connection pools
    without disrupting in-flight requests.

## 10. Schema initialization

Schema initialization is tightly coupled to connection pooling because it
occurs as part of pool creation.

**Patterns in this codebase:**

*   `SurrealDBPool.initialize_schema()` defines Knowledge Graph tables,
    relationships, and vector indexes, and manages schema versioning via a
    `schema_versions` table.
*   `create_surrealdb_pool()` calls `initialize_schema()` immediately after
    pool creation. If this step fails, it closes the pool and re-raises the
    error.
*   The application therefore either starts with the expected schema in place
    or fails fast during startup.

**Guidance:**

*   Use explicit migrations and versioning to evolve schemas safely; avoid
    ad-hoc schema changes at runtime.
*   Treat failures during schema initialization as fatal for startup rather
    than allowing the app to run with partial state.

## 11. Error handling

Robust error handling is essential for diagnosing connection issues and
maintaining predictable behavior.

**Startup errors:**

*   If `create_surrealdb_pool()` or `create_elasticsearch_wrapper()` fails, the
    lifespan context in `app/core/factory.py` logs the error and raises it so
    the application does not accept requests.
*   Factories are responsible for cleaning up partially initialized pools or
    clients before propagating errors.

**Runtime errors:**

*   Connection acquire errors and timeouts should be logged with enough
    metadata (for example, operation type and pool name) to support
    troubleshooting.
*   Infrastructure layers should raise well-typed exceptions that services can
    catch and translate into domain errors; global exception handlers then map
    domain errors into HTTP responses.

**Shutdown errors:**

*   During shutdown, failures to close pools or clients should be logged but
    should not prevent process termination. The goal is to release as many
    resources as possible while still allowing a graceful exit.

## 12. Testing with connection pools

Tests should verify behavior without requiring real SurrealDB or Elasticsearch
instances unless explicitly performing integration or end-to-end testing.

**Unit tests:**

*   Use test doubles for pools and clients. For example, unit tests that care
    about validation behavior can monkeypatch `create_surrealdb_pool()` and
    `create_elasticsearch_wrapper()` to return dummy resources, as shown in
    `tests/unit/test_validation_errors.py`.
*   Avoid hitting real databases or search clusters in unit tests.

**Integration tests:**

*   For in-process integration tests, use the fixtures in `tests/conftest.py`
    (for example, `async_client`) and, when needed, dependency overrides that
    retrieve pools from `app.state`.
*   Consider using disposable databases or isolated indices when running
    integration tests against real backends.

**End-to-end tests:**

*   E2E tests use the `live_server` and `api_client` fixtures in
    `tests/conftest.py` to exercise the full Dockerized stack, including real
    SurrealDB and Elasticsearch services.
*   These tests should validate startup behavior, health checks, and that
    connection pooling works correctly under realistic workloads.

## 13. Anti-patterns to avoid

Avoid the following patterns when working with connection pools and long-lived
clients:

*   **Creating pools per request:** Constructing new pools or clients in route
    handlers is expensive and defeats the purpose of pooling.
*   **Bypassing pooling entirely:** Opening new database or HTTP connections
    for every operation leads to connection thrashing and resource exhaustion.
*   **Oversized pools:** Setting very large pool sizes without regard for
    backend limits can starve other services and make failures harder to
    diagnose.
*   **No timeouts:** Failing to configure acquire or request timeouts causes
    requests to hang when backends are slow or unreachable.
*   **No cleanup:** Neglecting to close pools and clients during shutdown can
    leak sockets, file descriptors, or threads.

## 14. HTTP client pooling

Outbound HTTP traffic (for example, calls to external APIs) should follow the
same pooling principles as database and search clients.

**Recommended pattern:**

*   Create a single shared `httpx.AsyncClient` instance during the FastAPI
    lifespan startup and attach it to `app.state.http_client`.
*   Configure connection limits and timeouts via `httpx.Limits` and
    `httpx.Timeout` so the client maintains a bounded pool of keep-alive
    connections and enforces sensible request timeouts.
*   Inject the shared client into services via dependencies rather than
    creating new clients per request.
*   Close the shared client during lifespan shutdown to release all
    connections cleanly.

This pattern aligns with HTTPX guidance to use a long-lived client for
applications that make many requests, enabling connection reuse and efficient
connection pooling.

## 15. Monitoring and security considerations

Connection pools and long-lived clients must be observable and safe.

**Monitoring:**

*   Emit structured logs for pool initialization, timeouts, and acquire
    failures.
*   Where available, record metrics such as pool utilization, queue wait time,
    and backend response latency.
*   Use these signals to tune pool sizes, timeouts, and retry policies over
    time.

**Security:**

*   Avoid logging raw connection strings, credentials, or other sensitive
    details. The `Settings` model already marks SurrealDB credentials as
    non-repr fields; follow the same pattern for any future secrets.
*   Store credentials and hostnames exclusively in configuration (for example,
    environment variables consumed by `Settings`) and never hard-code them in
    code or tests.
*   Ensure that any additional monitoring or debugging tools respect these
    constraints and do not expose secrets in logs or traces.
