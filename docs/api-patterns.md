# API Design Patterns

Central standards for REST API design in the `ai-workflow` project. Use this as the source of truth for URL structure, request/response schemas, and OpenAPI documentation. References: `app/api/v1/router.py`, `app/api/v1/endpoints/health.py`, `app/contracts/errors.py`, `app/core/factory.py`.

## 1. URL Structure & Versioning

* **Prefix**: All versioned endpoints must be under `/api/{version}` (e.g., `/api/v1`).
* **Health Checks (two-tier)**:
  * **Liveness**: `GET /health` (unversioned, not surfaced in docs).
  * **Readiness**: `GET /api/{version}/health` (versioned, documented in OpenAPI).
  * Reference: `app/core/factory.py`, `app/api/v1/endpoints/health.py`.
* **Resource Naming**: Plural, kebab-case resources (e.g., `/api/v1/task-assignments`).
* **Path Parameters**: Use specific identifiers, not generic ids (e.g., `/users/{user_id}` not `/users/{id}`).

## 2. HTTP Methods & Status Codes

Standard semantics with a strict validation rule:

| Method | Usage | Success Status | Error Statuses |
| :--- | :--- | :--- | :--- |
| **GET** | Retrieve a resource or list | `200 OK` | `404 Not Found` |
| **POST** | Create a new resource | `201 Created` | `400 Bad Request`, `409 Conflict` |
| **PUT** | Full update of a resource | `200 OK` | `400 Bad Request`, `404 Not Found` |
| **PATCH** | Partial update of a resource | `200 OK` | `400 Bad Request`, `404 Not Found` |
| **DELETE** | Remove a resource | `204 No Content` | `404 Not Found` |

* **Validation Errors**: Always return `400 Bad Request` for validation failures to override FastAPI's default 422. Document the 400 schema from `app/contracts/errors.py` in `responses`.

## 3. Request/Response Patterns

* **Pydantic Models**: Request and response models use `ConfigDict(extra="forbid")`.
* **response_model**: All endpoints must set `response_model` to enforce output shape and filtering.
* **Route Docs**: Include `summary`, `description` (when logic is non-trivial), and `responses` for non-200 codes.

### Generic Example

```python
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from app.contracts.errors import HTTPValidationError

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
        400: {"description": "Validation error", "model": HTTPValidationError},
        409: {"description": "Conflict"},
    },
)
async def create_resource(payload: ResourceCreate) -> ResourceResponse:
    ...
```

## 4. OpenAPI Documentation Standards

Documentation-first: the OpenAPI schema is the contract.

* **summary**: Required for every route.
* **description**: Required for complex behavior or side effects.
* **tags**: Group endpoints logically (e.g., `tags=["Users"]`).
* **Error Responses**: Document non-200 responses via `responses`; use the 400 validation schema from `app/contracts/errors.py` (`HTTPValidationError`).

## 5. Response Envelope Pattern

* **No envelopes**: Return domain models directly; avoid wrappers like `{"data": ..., "status": ...}`.
* **Pagination**: Use a generic `Paginated[T]` structure (`items`, `total`, `page`, `size`).
* **Errors**: Use `HTTPValidationError` from `app/contracts/errors.py` for validation failures.

## 6. Content Negotiation

* **JSON Default**: Default `Content-Type` is `application/json`.
* **Serializer**: Use `ORJSONResponse` as the default response class (see `app/core/factory.py`).
* **Compression**: Support `Accept-Encoding: gzip` via middleware.

## 7. API Versioning Strategy

* **Path Versioning**: `/api/v1`, `/api/v2`, etc.
* **Backward Compatibility**: Within a major version, changes are additive and non-breaking.
* **Deprecation**: Mark deprecated routes with `deprecated=True` and include `Sunset` headers when removal is scheduled; document breaking changes in the API changelog.

## 8. Anti-Patterns to Avoid

* Business logic inside route handlers (use services instead).
* Returning ORM models directly instead of Pydantic contracts.
* Inconsistent error formats or undocumented responses.
* Endpoints without `response_model` or missing OpenAPI metadata.
* Generic `except Exception` handlers that obscure root causes.
