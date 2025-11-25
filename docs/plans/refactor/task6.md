# Task 6 – Exception handlers and wiring

**Locations:** `app/core/exceptions.py`, `app/core/factory.py`

**Goal:** Return `AppError` envelopes for all non-validation errors and register handlers globally.

## Steps

**Step 1: Extend `app/core/exceptions.py`:** Import `Request`, `FastAPI`, `ORJSONResponse`,
`status`, `logging`. Import `DomainError` from `app/core/errors.py`. Import `AppError`, `ErrorCode`
from `app/contracts/errors.py`.

**Step 2: Domain error handler:** Implement `domain_exception_handler` that creates `AppError` from
the domain exception and returns `ORJSONResponse`. Log at warning level with request context.

**Step 3: Catch-all handler:** Implement `internal_exception_handler` that logs at error level with
stack trace and returns a generic `AppError.internal_error()` response.

**Step 4: Register handlers in `app/core/factory.py`:** After creating the app, add handlers for
`DomainError` and `Exception`. Ensure `DomainError` is registered before the generic `Exception`
handler.

**Step 5: Inject `AppError` and `ErrorCode` into OpenAPI:** In the custom `openapi` function in
`factory.py`, extend `components.schemas` with `AppError` and `ErrorCode` schemas.

**Step 6: Update routes to document `AppError` responses:** Add `500` entries for internal errors
and appropriate entries for domain errors (e.g., `404` for not-found).
