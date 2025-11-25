# Middleware Patterns

This document defines the standards for HTTP middleware in the FastAPI application. It covers
ordering semantics, the recommended middleware stack, configuration via `Settings`, and testing
strategies so that cross-cutting concerns like security, performance, and observability are handled
consistently.

Primary runtime references:

* `app/core/factory.py` – FastAPI application construction, middleware registration, and OpenAPI
  customization.
* `app/core/settings.py` – application settings model used to configure middleware behavior.
* `app/core/middleware.py` – custom middleware such as `SecurityHeadersMiddleware` and
  request/response logging.

Middleware patterns in this document intentionally avoid concrete source line references. Use the
high-level patterns when wiring or extending middleware in the application factory.

## 1. Middleware Fundamentals and Ordering

FastAPI is built on Starlette and the ASGI specification, so any ASGI-compatible middleware can be
used. Middleware runs for every request and response, making it the correct place for cross-cutting
concerns (security headers, compression, logging, metrics, request IDs, and rate limiting).

**Execution order:**

* Middleware is applied as a stack. When you use `app.add_middleware(...)`, the **last added
  middleware becomes the outermost**.
* On the **request** path, the outermost middleware runs first; on the **response** path, it runs
  last.
* Conceptually, if `MiddlewareA` is added first and `MiddlewareB` second with
  `app.add_middleware(...)`:
  * Request flow: `MiddlewareB  MiddlewareA  route handler`.
  * Response flow: `route handler  MiddlewareA  MiddlewareB`.

Because of this stacking, the registration order in `create_app` in `app/core/factory.py` is
critical. All HTTP middlewares for this project must be registered via FastAPI's
`app.add_middleware()` API inside `create_app`; do not wrap the ASGI app manually. Place middleware
that must see every request as early as possible in the request-path order by registering inner
middlewares first and outer middlewares last.

## 2. Recommended Middleware Stack

The application factory is responsible for assembling the middleware stack using
`app.add_middleware()` calls. A typical production deployment should follow this **request-path
execution order (outermost to innermost)**:

1. **TrustedHostMiddleware** (if configured) – Validates the `Host` header to prevent HTTP Host
   header attacks.
2. **CORSMiddleware** (if enabled) – Handles CORS and preflight `OPTIONS` requests before other
   application-specific transformations.
3. **SecurityHeadersMiddleware** – Custom middleware from `app/core/middleware.py` that attaches
   standard security headers on every response.
4. **GZipMiddleware** – Compresses responses.
5. **Request/response logging and metrics middleware** – Captures request/response details, request
   IDs, and metrics for observability.

Because FastAPI executes the last-added middleware first on the request path, achieving this order
requires registering middlewares in **reverse order** in `create_app` (for example: logging/metrics
→ `GZipMiddleware` → `SecurityHeadersMiddleware` → `CORSMiddleware` → `TrustedHostMiddleware`).

If the app is deployed behind a reverse proxy or load balancer, consider adding Starlette's
`ProxyHeadersMiddleware` as the final `app.add_middleware` call so it becomes the outermost
middleware (for example, request flow: `ProxyHeadersMiddleware` → `TrustedHostMiddleware` →
`CORSMiddleware` → `SecurityHeadersMiddleware` → `GZipMiddleware` → logging/metrics → route
handler). When additional middleware such as rate limiting or APM-specific components are
introduced, insert them in a way that preserves this canonical request-path ordering.

`TrustedHostMiddleware` and `SecurityHeadersMiddleware` form the core of the security layer, while
`CORSMiddleware`, compression, logging, and rate limiting add cross-cutting behavior on top of that
foundation.

## 3. Security Headers Middleware

`SecurityHeadersMiddleware` is a custom ASGI middleware defined in `app/core/middleware.py`. Its
responsibility is to apply security-related HTTP headers consistently across all responses.

**Required headers:**

* `X-Content-Type-Options: nosniff` – Prevents browsers from MIME-sniffing a response away from the
  declared content type.
* `X-Frame-Options: DENY` – Prevents the site from being embedded in frames, mitigating clickjacking
  attacks.
* `Referrer-Policy: strict-origin-when-cross-origin` – Restricts referrer information sent to other
  origins.
* `Strict-Transport-Security: max-age=31536000; includeSubDomains` – Enforces HTTPS for one year
  across the domain and subdomains when the application is served over HTTPS.

**Configuration via settings:**

`SecurityHeadersMiddleware` should be configurable using fields on the `Settings` model in
`app/core/settings.py`, for example:

* `enforce_https: bool` – When `True`, the middleware (or a companion HTTPS enforcement middleware)
  should assume HTTPS-only operation and include HSTS headers.
* `allowed_hosts: list[str]` – Shares the same host configuration as `TrustedHostMiddleware` so
  security headers can be tailored to the domains actually serving traffic.

**Environment guidance:**

* In **production**, `SecurityHeadersMiddleware` must be enabled, and HSTS should be configured
  with a long `max-age` and `includeSubDomains`.
* In **local** or **test** environments, HSTS may be disabled or set with shorter lifetimes to
  avoid issues with browser caching.

`SecurityHeadersMiddleware` should be registered in `create_app` so it wraps all API routes and
error responses, not only specific routers.

## 4. GZip Compression Middleware

The application uses FastAPI's built-in `GZipMiddleware` (from `fastapi.middleware.gzip`) to
compress responses for clients that support GZip.

**Configuration pattern:**

* `minimum_size` – Do not compress small responses. `GZipMiddleware` defaults to `minimum_size=500`
  bytes; for this project, set `minimum_size=1024` bytes to avoid overhead on tiny payloads.
* `compresslevel` – Used during GZip compression and must be an integer from `1` (fastest, largest
  responses) to `9` (slowest, smallest responses). For this project, configure `compresslevel=5`
  to balance speed and compression, and change it only when you have concrete performance
  measurements that justify a different value.
* Only clients that send `Accept-Encoding: gzip` receive compressed responses.
* These knobs mirror the underlying `GZipMiddleware` configuration interface; this document inlines
  the relevant defaults and ranges so you do not need to consult external framework documentation
  when tuning compression.

**Tuning guidance:**

* Start with `minimum_size=1024` and `compresslevel=5` for all environments; this is the project
  standard and should be treated as the baseline.
* If profiling shows that CPU is the bottleneck and bandwidth is cheap (for example, high-throughput
  internal traffic on a fast network), consider lowering `compresslevel` toward `3` to reduce CPU
  cost at the expense of slightly larger responses.
* If profiling shows that outbound bandwidth is the bottleneck and CPU headroom is available, you
  may experiment with higher `compresslevel` values (for example, `7`), but avoid `9` unless you
  have concrete evidence that the extra CPU cost is acceptable.
* Do not change `minimum_size` or `compresslevel` based on intuition alone; always validate changes
  with realistic load tests and keep the chosen values documented in deployment runbooks.

**Settings integration:**

Configure GZip via the settings model:

* `enable_gzip: bool = True` – Toggles GZip compression globally.

In `create_app`, only add the middleware when `settings.enable_gzip` is true. This allows disabling
compression in environments where it is handled upstream (for example, at the API gateway or
reverse proxy).

## 5. Trusted Host Middleware

`TrustedHostMiddleware` (from `fastapi.middleware.trustedhost`) enforces that all incoming requests
use an allowed `Host` header.

**Configuration via settings:**

* `allowed_hosts: list[str] = ["*"]` – A list of allowed host patterns, including wildcard entries
  like `"*.example.com"`.
* In **development**, a default of `"*"` may be acceptable for convenience.
* In **production**, `allowed_hosts` must be set to specific domains and subdomains for the
  deployment (for example, `"example.com"` and `"*.example.com"`).

When `TrustedHostMiddleware` rejects a request, it should return an appropriate `400` response.
Always configure it in `create_app` so it applies uniformly to all routes.

## 6. CORS Middleware

`CORSMiddleware` (from `fastapi.middleware.cors`) is used to control which browsers and origins can
access the API.

**When to use CORS:**

* Enable CORS only when cross-origin browser clients are expected (for example, a separate frontend
  domain calling the API).
* Prefer a narrow list of allowed origins over `"*"` in production.

**Ordering:**

* On the request path, `CORSMiddleware` should execute immediately after `TrustedHostMiddleware`
  and before `SecurityHeadersMiddleware` and `GZipMiddleware` so it can correctly process preflight
  `OPTIONS` requests and attach CORS headers before other response transformations.
* Because the last-added middleware runs first on requests, achieve this by following the
  recommended stack in this document and registering middlewares in reverse order (for example,
  logging/metrics → `GZipMiddleware` → `SecurityHeadersMiddleware` → `CORSMiddleware` →
  `TrustedHostMiddleware`, plus optional `ProxyHeadersMiddleware` added last to run outermost).

**Configuration via settings:**

Add fields to `Settings` for CORS configuration, such as:

* `cors_enabled: bool = False`
* `cors_allow_origins: list[str] = []`
* `cors_allow_methods: list[str] = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]`
* `cors_allow_headers: list[str] = ["Authorization", "Content-Type"]`

The application factory should read these settings and register `CORSMiddleware` only when
`cors_enabled` is true.

## 7. Proxy and HTTPS Enforcement Middleware

When the application runs behind a reverse proxy or load balancer, additional middleware is
required for accurate request metadata and secure redirects.

**ProxyHeadersMiddleware:**

* Use Starlette's `ProxyHeadersMiddleware` to respect `X-Forwarded-For` and `X-Forwarded-Proto`
  headers.
* Add this middleware as the outermost wrapper on the request path so downstream logic (including
  host validation and HTTPS redirects) sees the correct scheme and client IP.
* The application factory should enable this only for environments that are known to be behind a
  trusted proxy and register it as the final `app.add_middleware` call in `create_app`.

**HTTPSRedirectMiddleware:**

* Use FastAPI's `HTTPSRedirectMiddleware` when `Settings.enforce_https` is true.
* On the request path, `HTTPSRedirectMiddleware` should execute immediately after
  `TrustedHostMiddleware` and before `CORSMiddleware` so that host headers are validated before
  computing redirect targets and CORS processing happens only on the canonical HTTPS origin.
* To achieve this, when HTTPS enforcement is enabled, register middlewares in `create_app` in this
  order (from first added to last added): logging/metrics → `GZipMiddleware` →
  `SecurityHeadersMiddleware` → `CORSMiddleware` → `HTTPSRedirectMiddleware` →
  `TrustedHostMiddleware` → `ProxyHeadersMiddleware`.
* Redirects HTTP requests to HTTPS (or `ws` to `wss`) to enforce secure transport at the
  application layer, and should be combined with HSTS headers in `SecurityHeadersMiddleware` to
  provide a strong HTTPS posture.

## 8. Observability, Request IDs, and Rate Limiting

Beyond built-in middleware, the project should rely on custom middleware classes in
`app/core/middleware.py` and well-maintained third-party middleware for observability and traffic
control.

**Request/response logging:**

* Implement middleware that logs request method, path, status code, and duration.
* Use structured logging (for example, key-value pairs) so logs can be queried by attributes
  (status code, route, request ID).
* Avoid logging entire request or response bodies by default to prevent leaking sensitive data.
* Standardize on a dedicated `RequestLoggingMiddleware` class in `app/core/middleware.py` instead
  of ad hoc logging in routers or services.

**Request IDs:**

* Generate a unique request ID per incoming request and attach it to:
  * The logging context for that request.
  * A response header such as `X-Request-ID`.
* When upstream systems already provide a correlation ID header, prefer propagating that value
  instead of generating a new one.
* Use a dedicated `RequestIDMiddleware` class in `app/core/middleware.py` to own request ID
  generation and propagation.

**Metrics and APM:**

* Use middleware-integrated metrics (for example, Prometheus or OpenTelemetry) to record request
  duration, status codes, and error rates per route.
* Ensure metrics capture middleware-induced failures (for example, host rejections or rate limits)
  as distinct categories.
* Implement metrics collection in a standardized `MetricsMiddleware` class in
  `app/core/middleware.py`, or use a well-defined provider-specific middleware wrapper.

**Rate limiting:**

* Apply rate limiting via dedicated middleware or a specialized library, not in routers or services.
* Configure limits via settings (for example, per-IP or per-API key quotas) and keep the
  enforcement logic at the middleware layer to avoid scattering it across endpoints.
* Centralize rate limiting behavior in a `RateLimitingMiddleware` class in `app/core/middleware.py`
  so it can be configured and tested consistently.

TODO: Introduce the `RequestLoggingMiddleware`, `RequestIDMiddleware`, `MetricsMiddleware`, and
`RateLimitingMiddleware` classes in `app/core/middleware.py` and wire them via `create_app` so new
work can rely on these standardized middleware entry points.

## 9. Middleware Implementation Patterns

In this project, HTTP middleware must be implemented as ASGI classes and registered via FastAPI's
`app.add_middleware()` API inside `create_app`. Do not use the `@app.middleware("http")` decorator.

**ASGI class pattern:**

* `__init__(self, app, **config)` – stores the inner ASGI app and configuration.
* `async def __call__(self, scope, receive, send)` – wraps the request/response lifecycle.
* Use this pattern for `SecurityHeadersMiddleware`, request logging, metrics, rate limiting, and
  any other cross-cutting concerns.

Middleware classes should be defined in `app/core/middleware.py` (or adjacent modules) and added
only from `create_app` so that the stack is centralized and easy to audit.

## 10. Middleware Configuration via Settings and Factory

All middleware should be configured via the `Settings` model and wired in the application factory.

**Settings fields (conceptual):**

* `enable_gzip: bool = True`
* `enforce_https: bool = False` (set to `True` in production)
* `allowed_hosts: list[str] = ["*"]`

**Factory wiring pattern:**

* Retrieve settings via the factory argument (`Settings`) and store them on `app.state.settings`
  for downstream access.
* Use `if` conditions to enable or disable each middleware based on settings, keeping all
  `app.add_middleware()` calls in `create_app`.
* Ensure the order of `add_middleware` calls matches the recommended stack in this document.

This pattern keeps middleware behavior environment-driven, testable, and consistent with the
factory and settings patterns documented elsewhere.

## 11. Error Handling in Middleware

Middleware must cooperate with the application's global exception handling strategy.

**Guidelines:**

* Do not swallow exceptions raised by downstream handlers or services.
* Allow FastAPI's exception handlers (registered in `app/core/factory.py` using functions from
  `app/core/exceptions.py`) to convert errors into HTTP responses.
* Use `try`/`finally` in middleware for cleanup (for example, timing or metrics) while re-raising
  exceptions so they are handled centrally.
* If middleware needs to log errors, log them and then re-raise rather than returning ad hoc
  responses.

Following these rules ensures that domain and infrastructure exceptions remain consistent with the
error contracts defined in `api-patterns.md` and `exception-patterns.md`.

## 12. Testing Middleware

Middleware must be tested via integration tests that exercise the actual FastAPI application
instance constructed by `create_app`.

**Integration testing pattern:**

* Build an app instance using `create_app` with test-specific `Settings`.
* Use FastAPI's `TestClient` or an async HTTP client to send requests through the full stack.
* Assert on:
  * Presence and values of security headers (from `SecurityHeadersMiddleware`).
  * Compression behavior (for example, large responses compressed when `Accept-Encoding: gzip` is
    present, and uncompressed when it is not).
  * Host validation (requests with invalid `Host` headers receive appropriate `400` responses when
    `TrustedHostMiddleware` is enabled).
  * CORS behavior (preflight `OPTIONS` requests and allowed/denied origins).
  * Logging and request ID behavior where observable via headers or test logging sinks.

Existing test fixtures should instantiate the application via the factory and provide clients that
exercise middleware in the same way as production, so middleware tests remain close to real
behavior.

## 13. Anti-Patterns to Avoid

Avoid the following anti-patterns when working with middleware:

* Adding middleware in an arbitrary order, leading to incorrect CORS behavior, missing security
  headers, or confusing logging.
* Hardcoding middleware configuration inside the factory or middleware classes instead of using
  `Settings`.
* Modifying request or response bodies in middleware without carefully preserving streaming behavior
  and content types.
* Performing heavy CPU-bound or blocking I/O work directly inside middleware without offloading to
  background tasks or worker pools.
* Swallowing exceptions in middleware and returning ad hoc error responses that bypass global
  exception handling and error contracts.
* Implementing rate limiting, logging, or metrics directly inside routers or services instead of
  centralized middleware.

By following these patterns, middleware remains a powerful, centralized mechanism for enforcing
security, performance, and observability across the entire API surface.
