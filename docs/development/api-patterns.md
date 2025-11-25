# API Design Patterns

Central standards for REST API design in the `ai-workflow` project. Use this as the source of truth for
URL structure, request/response schemas, error responses, and OpenAPI documentation. It captures stable
2024–2025 FastAPI and Pydantic v2 practices for this backend.

This document focuses on API-wide behavior and contracts. Router composition, service and repository
patterns, and tests are covered separately in `router-patterns.md`, `service-patterns.md`, and
`dependency-patterns.md`.

Primary runtime references:

* `app/core/factory.py` – FastAPI application construction, default response class, and custom OpenAPI
  schema.
* `app/core/exceptions.py` – global request validation handler.
* `app/api/v1/router.py` – versioned API router registration.
* `app/contracts/errors.py` – HTTP validation error contracts.

## 1. URL Structure & Versioning

* **Prefix**: All versioned endpoints must be mounted under `/api/{version}` (e.g., `/api/v1`), as
  configured in `create_app` in `app/core/factory.py`.
* **Health checks (two-tier)**:
  * **Liveness**: `GET /health` – unversioned, excluded from OpenAPI; used by orchestrators to see if
    the process is alive.
  * **Readiness**: `GET /api/{version}/health` – versioned endpoint registered in the versioned API
    router and documented in OpenAPI; used to report overall service readiness.
* **Resource naming**: Use plural, kebab-case resources (e.g., `/api/v1/task-assignments`,
  `/api/v1/user-sessions`).
* **Path parameters**: Use descriptive identifiers, not generic ids (e.g., `/users/{user_id}` not
  `/users/{id}`).
* **Trailing slashes**: Declare canonical paths without a trailing slash (e.g., `/users` and
  `/users/{user_id}`). FastAPI will handle `.../` redirects, but the non-slashed form is the contract
  and must be used in documentation and clients.

## 2. HTTP Methods & Status Codes

Standard semantics with a strict rule for validation failures:

| Method | Usage | Success status | Error statuses |
| :----- | :----- | :------------- | :------------- |
| **GET** | Retrieve a resource or list | `200 OK` | `404 Not Found` |
| **POST** | Create a new resource | `201 Created` | `400 Bad Request`, `409 Conflict` |
| **PUT** | Replace an entire resource | `200 OK` | `400 Bad Request`, `404 Not Found` |
| **PATCH** | Partially update a resource | `200 OK` | `400 Bad Request`, `404 Not Found` |
| **DELETE** | Delete a resource | `204 No Content` | `404 Not Found` |

* Prefer named constants from `fastapi.status` (e.g., `status.HTTP_201_CREATED`) instead of hard-coded
  integers.
* **Validation errors**: All request validation failures must be surfaced as `400 Bad Request`,
  overriding FastAPI's default `422 Unprocessable Entity` for `RequestValidationError`.
  * `create_app` registers `validation_exception_handler` from `app/core/exceptions.py` as the global
    handler for `RequestValidationError`.
  * That handler returns a `400` response with a body shaped by the `HTTPValidationError` model in
    `app/contracts/errors.py`.
  * Route decorators should reuse `VALIDATION_ERROR_RESPONSE` from `app/contracts/errors.py` in the
    `responses` section for `400` entries.

## 3. Request/Response Modeling

* **Pydantic v2 models**: Request and response bodies must use `BaseModel` subclasses with
  `model_config = ConfigDict(extra="forbid")` to reject unknown fields.
* **JSON field naming**: Use `snake_case` field names in models and JSON. For datetimes, use
  timezone-aware UTC values formatted as ISO 8601 strings.
* **response_model**: Every endpoint must set `response_model` to enforce the outbound schema, filter
  extra fields from service outputs, and drive OpenAPI schemas.
* **Side effects**: When a route performs non-trivial side effects (writes, external calls), ensure the
  `description` captures them so API consumers understand the behavior.

### Generic Example

```python
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from app.contracts.errors import HTTPValidationError, VALIDATION_ERROR_RESPONSE

class ResourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(min_length=1)]

class ResourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    name: str
    created_at: datetime

router = APIRouter()

@router.post(
    "/resources",
    response_model=ResourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create resource",
    description="Creates a resource and returns its representation.",
    responses={
        400: VALIDATION_ERROR_RESPONSE,
        409: {"description": "Conflict"},
    },
)
async def create_resource(payload: ResourceCreate) -> ResourceResponse:
    ...
```

## 4. OpenAPI Documentation Standards

The generated OpenAPI schema is the external contract; routes must be documented accordingly.

* **summary**: Short, action-oriented sentence for every route.
* **description**: Provide details for complex behavior, side effects, or edge cases; Markdown is
  allowed.
* **tags**: Group endpoints by domain (e.g., `tags=["Users"]`, `tags=["Health"]`).
* **Error responses**:
  * Document non-success responses using the `responses` parameter.
  * For request validation, use `VALIDATION_ERROR_RESPONSE` so schemas align with
    `HTTPValidationError`.
  * `create_app` customizes OpenAPI generation to register the `HTTPValidationError` schema and its
    nested types; do not duplicate these definitions by hand.
* **Consistency**: Router-specific documentation details (e.g., shared `responses`) belong in
  router-level patterns; this document defines only the API-wide expectations they should satisfy.

## 5. Response Shape and Pagination

* **No generic envelopes**: Do not wrap successful responses in generic structures like
  `{"status": "ok", "data": ...}`. Return domain models directly as dictated by the `response_model`.
* **Pagination pattern**: For collections that require pagination, use a consistent structure
  conceptually equivalent to:
  * `items: list[T]`
  * `total: int`
  * `page: int`
  * `page_size: int`
  until a concrete generic `Paginated[T]` model is introduced under `app/contracts/`. New paginated
  endpoints should follow these field names to ease future migration.
* **Error responses**:
  * All error responses should share a common top-level envelope, conceptually an `AppError` schema
    with `code`, `message`, `status_code`, and optional `details` fields.
  * Validation failures continue to use `HTTPValidationError` to describe field-level issues (with
    `detail` and optional `body`), but where feasible they should be exposed through the same top-level
    `AppError` structure (for example, by placing the `HTTPValidationError` payload inside the
    `details` field).
  * Non-validation errors (for example, domain or infrastructure failures) must also use the `AppError`
    envelope with domain-specific `code` values and contextual `details`.
  * TODO: Introduce a concrete `AppError` Pydantic model under `app/contracts/errors.py` and align
    global exception handling (including the existing validation handler in `app/core/exceptions.py`)
    so that all non-validation errors, and where feasible validation errors, are exposed through this
    envelope and documented consistently.
  * TODO: Once a generic `Paginated[T]` model exists under `app/contracts/`, update routers and this
    document to reference that model as the canonical pagination schema instead of treating
    `Paginated[T]` as purely conceptual.

## 6. Content Negotiation

* **JSON default**: Default `Content-Type` is `application/json` unless a route explicitly declares
  otherwise.
* **Serializer**: `create_app` sets `ORJSONResponse` as the `default_response_class`, so responses
  inherit high-performance JSON serialization by default. Avoid per-route overrides unless required
  for special content types.
* **Compression**: The API must support `Accept-Encoding: gzip` via middleware; responses must remain
  valid JSON regardless of transport-level compression.

## 7. Versioning and Deprecation

* **Path-based versioning**: All public endpoints are versioned in the path (`/api/v1`, `/api/v2`,
  etc.). Breaking changes require a new major version.
* **Compatibility within a version**:
  * Additive changes (new optional fields, new endpoints) are allowed.
  * Breaking changes (removing fields, changing semantics) are not.
* **Marking deprecated endpoints**:
  * Set `deprecated=True` in the route decorator so OpenAPI and interactive docs highlight deprecation.
  * Add a `Deprecation` response header when an endpoint is deprecated (e.g., `Deprecation: true` or a
    deprecation date string).
  * When a removal date is known, include a `Sunset` header with an RFC 1123 timestamp (e.g.,
    `Sunset: Wed, 30 Jun 2025 23:59:59 GMT`).
* **Changelog**: Any breaking or deprecating change must be documented in the API changelog, including
  migration guidance to replacement endpoints or versions.

## 8. Anti-Patterns to Avoid

* Implementing business logic directly in route handlers instead of delegating to services.
* Returning ORM or database models directly instead of Pydantic contracts.
* Inconsistent error response shapes across endpoints or undocumented error responses.
* Omitting `response_model` or leaving success and error status codes implicit.
* Using broad `except Exception` handlers that hide the root cause or bypass global exception handling.
* Missing OpenAPI documentation (for example, absent `summary`, `description`, `tags`, or documented
  error responses).
