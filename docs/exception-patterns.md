# Exception Patterns

Central standards for exception design and error handling in the `ai-workflow` FastAPI backend. Use this document as the source of truth for how domain errors are modeled, how they are translated into HTTP responses, and how they are documented in OpenAPI. It builds on the API-wide rules in `api-patterns.md` and aligns with the guidance captured in the FastAPI best-practices documents.

Primary runtime references:

- `app/core/exceptions.py` – request validation handler and sanitization utilities.
- `app/contracts/errors.py` – HTTP validation error models and shared error response definitions.
- `app/core/factory.py` – FastAPI application construction, default response class, and exception handler registration.
- `tests/unit/test_validation_errors.py` – baseline tests for request validation behavior.
- `app/contracts/example_contract.py` – validation constants used to constrain error payloads.

This document standardizes a single error response vocabulary with two core shapes:

- `HTTPValidationError` – field-level validation issues for requests.
- `AppError` – top-level envelope for all domain and infrastructure errors.

## 1. Exception Hierarchy

Domain and business logic errors are modeled with a small, explicit hierarchy that is independent of HTTP concerns:

- `DomainError`: Root base class for all business-level failures. Defined in `app/core/errors.py` and used by services and domain components.
- `ResourceNotFoundError(DomainError)`: Raised when a requested domain entity does not exist (for example, user, ticket, workflow).
- `DomainValidationError(DomainError)`: Raised when domain invariants are violated beyond simple request-shape validation (for example, invalid state transitions, conflicting inputs).
- `UnauthorizedError(DomainError)`: Raised when a user lacks permission to perform a domain operation, separate from transport-level authentication failures.
- Additional domain-specific subclasses (for example, `UserNotFoundError`, `InvalidOrderStateError`) may extend these core types as needed.

Key rules:

- Services and domain logic raise `DomainError` subclasses instead of returning sentinel values such as `None`, `False`, or magic strings.
- Domain exceptions are HTTP-agnostic: they must not embed HTTP status codes, headers, or transport-specific terminology.
- `fastapi.HTTPException` is reserved for HTTP-layer concerns that are not part of domain logic (for example, malformed requests, explicit redirects, low-level authentication or rate-limiting failures).

## 2. AppError Response Model

All non-validation error responses use a single envelope modeled by `AppError` in `app/contracts/errors.py`. This envelope provides a stable JSON contract for the frontend and external consumers.

Conceptual model:

- `ErrorCode`: Enum listing all known error identifiers (for example, `USER_NOT_FOUND`, `VALIDATION_ERROR`, `UNAUTHORIZED`, `INTERNAL_ERROR`).
- `AppError` Pydantic model:
  - `code: ErrorCode` – machine-parseable error identifier from the controlled vocabulary.
  - `message: str` – human-readable description safe to expose to clients.
  - `status_code: int` – HTTP status code; serialized with the JSON alias `statusCode`.
  - `details: dict | list | None` – optional structured context (for example, validation issues, conflicting field names, or correlation identifiers).

JSON examples:

- Domain error example:

  ```json
  {
    "code": "USER_NOT_FOUND",
    "message": "User with ID 123 was not found",
    "statusCode": 404,
    "details": null
  }
  ```

- Infrastructure error example:

  ```json
  {
    "code": "INTERNAL_ERROR",
    "message": "Unexpected error while processing request",
    "statusCode": 500,
    "details": {"requestId": "b8a53f7b-9a5b-4e2b-9c0e-4f2d1c0f25b1"}
  }
  ```

Usage guidelines:

- Routes describing non-validation failures must document `AppError` in their `responses` section, for example: `responses={404: {"model": AppError, "description": "Not found"}}`.
- `AppError.code` values must come from the `ErrorCode` enum; ad-hoc strings are not allowed.
- `details` should contain structured data (objects or lists), not long free-form strings or stack traces.

## 3. Global Exception Handlers

Global exception handlers translate internal exceptions into consistent HTTP responses. They are registered in `create_app` in `app/core/factory.py` using `app.add_exception_handler`.

The application uses three layers of handlers:

- **Request validation handler**: Registered for `RequestValidationError` and implemented as `validation_exception_handler` in `app/core/exceptions.py`. It returns `HTTPValidationError` payloads with status code `400`.
- **Domain error handler**: Registered for `DomainError` and responsible for mapping domain-specific exceptions to appropriate HTTP status codes and `AppError` responses.
- **Catch-all handler** (optional but recommended): Registered for `Exception` as a last resort to log unexpected failures and return a generic `INTERNAL_ERROR` `AppError` with status `500`.

Conceptual example for registering handlers:

```python
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse

from app.contracts.errors import HTTPValidationError
from app.core.errors import DomainError
from app.core.exceptions import validation_exception_handler
from app.contracts.errors import AppError


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(default_response_class=ORJSONResponse, lifespan=_lifespan(settings))

    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> ORJSONResponse:
        error = AppError.from_domain(exc)
        return ORJSONResponse(
            status_code=error.status_code,
            content=error.model_dump(mode="json", by_alias=True, exclude_none=True),
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception) -> ORJSONResponse:
        # Log at error level with full stack trace; see logging section below.
        generic = AppError.internal_error()
        return ORJSONResponse(
            status_code=generic.status_code,
            content=generic.model_dump(mode="json", by_alias=True),
        )

    return app
```

Router and service code should rely on these handlers instead of blanket-catching exceptions and manually returning `ORJSONResponse` objects.

## 4. Validation Error Handling

Request validation behavior is centralized in `validation_exception_handler` in `app/core/exceptions.py` and the models in `app/contracts/errors.py`.

`HTTPValidationError` and its nested `ValidationErrorDetail` model define the canonical shape of validation failures:

- `ValidationErrorDetail` fields:
  - `loc: list[str | int]` – location of the failing field (for example, `"body"`, `"query"`, nested field names, or indices).
  - `msg: str` – short, user-friendly message.
  - `type: str` – machine-parseable error type.
  - `ctx: dict[str, Any] | None` – optional context (for example, constraints or limits).
- `HTTPValidationError` fields:
  - `detail: list[ValidationErrorDetail]` – list of validation problems.
  - `body: Any | None` – optionally echoes the request body when `include_error_body=True` in settings.

Implementation rules derived from `app/core/exceptions.py` and `app/contracts/example_contract.py`:

- A maximum of `MAX_VALIDATION_ERRORS` entries (from `app/contracts/example_contract.py`) are returned to keep responses small and readable.
- Error locations are limited in depth using `MAX_JSON_DEPTH` to guard against excessively nested structures.
- Validation errors are always returned as `400 Bad Request`, overriding FastAPI's default `422 Unprocessable Entity` for `RequestValidationError`.
- When `Settings.include_error_body` is `True`, the handler attempts to parse and include the body under `HTTPValidationError.body`; otherwise, this field is omitted from the response.
- The handler logs each validation failure at warning level and truncates the serialized error list in logs to avoid flooding storage.

Example response body for a missing field:

```json
{
  "detail": [
    {
      "loc": ["body", "message"],
      "msg": "Field required",
      "type": "missing"
    }
  ]
}
```

## 5. Domain Exception Pattern

Services and domain components should signal failures by raising domain-specific exceptions rather than by returning sentinel values or HTTP-layer primitives.

Pattern for services:

- When a resource is not found, raise `ResourceNotFoundError` (or a subtype such as `UserNotFoundError`) with enough context for logging and error-code mapping.
- When an operation violates a business rule, raise `DomainValidationError` with details describing the violated invariant.
- When the user is not allowed to perform an operation, raise `UnauthorizedError` instead of returning `None` or a boolean.

Pattern for routers:

- Call services directly and allow them to raise `DomainError` subclasses.
- Do not catch domain exceptions just to convert them into `HTTPException`; rely on the global `DomainError` handler to map them into `AppError` responses.
- Continue to use `fastapi.HTTPException` where the error is purely HTTP-specific (for example, missing authentication headers, invalid tokens, or rate limiting) and not a domain concern.

Mapping examples via the domain handler:

- `ResourceNotFoundError` → `404 Not Found` with `AppError.code == ErrorCode.USER_NOT_FOUND` (or another resource-specific code).
- `DomainValidationError` → `400 Bad Request` with `AppError.code == ErrorCode.VALIDATION_ERROR` and `details` hinting at the violated rule.
- `UnauthorizedError` → `401 Unauthorized` or `403 Forbidden` depending on semantics, with appropriate `code` values.

## 6. Custom Exception Handler Implementation

Custom handlers follow the standard FastAPI pattern:

- Decorated with `@app.exception_handler(ExceptionType)`.
- Asynchronous functions with the signature `async def handler(request: Request, exc: ExceptionType) -> Response`.
- Return `ORJSONResponse` instances so responses share the same serialization behavior as the rest of the API.

Implementation guidelines:

- **Logging levels**:
  - Log domain and validation errors at warning level; these are expected user or workflow issues.
  - Log unexpected internal errors at error level with stack traces.
- **Request context**: Log at least the HTTP method, path, and any trace or correlation identifiers attached to the request state.
- **Payload truncation**: When logging error details or request bodies, truncate long values to a safe length (for example, first 1000 characters) to avoid log flooding and leaking excessively large payloads.
- **Reuse models**: All handlers must serialize errors using `AppError` or `HTTPValidationError` from `app/contracts/errors.py`; ad-hoc JSON structures are not allowed.

Example handler shape for a single domain error type:

```python
@app.exception_handler(ResourceNotFoundError)
async def resource_not_found_handler(request: Request, exc: ResourceNotFoundError) -> ORJSONResponse:
    logger.warning("Resource not found on %s %s", request.method, request.url.path)
    error = AppError(
        code=ErrorCode.USER_NOT_FOUND,
        message=str(exc),
        status_code=404,
        details=None,
    )
    return ORJSONResponse(
        status_code=error.status_code,
        content=error.model_dump(mode="json", by_alias=True, exclude_none=True),
    )
```

## 7. Error Response Structure

The backend exposes two complementary error shapes, each with a specific purpose.

- **Validation failures** – request-shape problems:
  - Represented by `HTTPValidationError` in `app/contracts/errors.py`.
  - Returned as `400 Bad Request`.
  - Body shape: `{ "detail": [ValidationErrorDetail, ...], "body": ... }` (with `body` optionally omitted).

- **Domain and infrastructure errors** – business logic and internal failures:
  - Represented by `AppError`.
  - Returned with status codes matching the semantics of the error (`404`, `400`, `401`, `403`, `409`, `500`, etc.).
  - Body shape: `{ "code": "ERROR_CODE", "message": "...", "statusCode": 4xx/5xx, "details": { ... } }`.

Examples:

- Domain error:

  ```json
  {
    "code": "USER_NOT_FOUND",
    "message": "User with ID 123 was not found",
    "statusCode": 404
  }
  ```

- Validation error:

  ```json
  {
    "detail": [
      {
        "loc": ["body", "message"],
        "msg": "Field required",
        "type": "missing"
      }
    ]
  }
  ```

Security and privacy rules:

- Do not expose stack traces, SQL queries, internal IDs, or secrets in `message` or `details`.
- Use generic phrasing for internal errors (for example, "Unexpected error while processing request").
- Rich diagnostics belong in logs and observability tooling, not in client-facing error payloads.

## 8. Error Logging

Exception handlers are responsible for consistent, structured logging of failures.

Guidelines:

- Always log through the module-level logger (for example, `logger = logging.getLogger(__name__)`) to integrate with application logging configuration.
- Include request metadata in log entries (HTTP method, path, query parameters when safe, correlation IDs, and authenticated principal when available).
- Use structured logging (for example, JSON fields) where supported so monitoring systems can filter and aggregate by `code`, `status_code`, and route.
- Truncate large payloads and error messages to a bounded length; when validation errors contain many items, log only a subset or summary.
- For validation errors, log at warning level using the sanitized `ValidationErrorDetail` list produced by `_sanitize_validation_errors` in `app/core/exceptions.py`.
- For unexpected internal errors, log at error level with full stack traces while returning a sanitized `AppError` to the client.

## 9. OpenAPI Error Documentation

Error responses must be documented explicitly in OpenAPI using shared models and response definitions.

Patterns:

- Reuse `VALIDATION_ERROR_RESPONSE` from `app/contracts/errors.py` for `400` validation failures in route decorators, for example:

  ```python
  from app.contracts.errors import VALIDATION_ERROR_RESPONSE

  @router.post(
      "/resources",
      responses={400: VALIDATION_ERROR_RESPONSE},
  )
  async def create_resource(payload: ResourceCreate) -> ResourceResponse:
      ...
  ```

- Use `AppError` as the response model for domain and infrastructure errors, for example:

  ```python
  @router.get(
      "/users/{user_id}",
      responses={
          400: {"model": AppError, "description": "Invalid request"},
          404: {"model": AppError, "description": "User not found"},
      },
  )
  async def get_user(user_id: str) -> UserResponse:
      ...
  ```

- `create_app` in `app/core/factory.py` already ensures that `HTTPValidationError` and its nested types are registered in the OpenAPI components section. `AppError` and `ErrorCode` must be added similarly under `app/contracts/errors.py` so that routes can reference them by model.
- Where helpful, include example error payloads in `responses` definitions to document concrete `code` values and field structures.

## 10. Testing Exception Handlers

Exception handling behavior must be covered by unit tests to avoid regressions.

Validation tests:

- `tests/unit/test_validation_errors.py` verifies that validation failures return `400` with an `HTTPValidationError` body shaped by `ValidationErrorDetail`.
- Extend this suite with additional cases for deeply nested payloads, truncated error lists, and the `include_error_body` toggle.

Domain error tests:

- Add tests that trigger specific `DomainError` subclasses from services and assert that routes produce the expected HTTP status code and `AppError` JSON.
- Verify that `AppError.code` values align with the `ErrorCode` enum and that `details` is present or omitted as expected.

Catch-all tests:

- Add tests that simulate unexpected exceptions (for example, raising a generic `Exception` in a route) and assert that the response is a sanitized `INTERNAL_ERROR` `AppError` with status `500` and no internal details.

Logging tests (where practical):

- Use log-capture fixtures to assert that validation errors are logged at warning level and internal errors at error level, without logging raw request bodies in full.

## 11. Anti-Patterns to Avoid

To keep error handling predictable and secure, avoid the following patterns:

- Raising `fastapi.HTTPException` from services instead of domain-specific exceptions.
- Returning different error shapes from different endpoints (for example, mixing `{ "detail": ... }` with arbitrary custom envelopes instead of `AppError`).
- Swallowing exceptions in routers or services and returning generic `500` responses instead of relying on global handlers.
- Exposing internal error details, stack traces, SQL statements, or secrets in client-facing responses.
- Using broad `except Exception` blocks without re-raising or delegating to global handlers.
- Adding new error models ad hoc instead of extending `AppError`, `ErrorCode`, and the domain exception hierarchy.
