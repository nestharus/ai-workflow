# Router Patterns

This document establishes the standards for building API routers in the application. Following
these patterns ensures consistency, testability, and proper OpenAPI documentation.

## 1. APIRouter Organization

* **Granularity:** Create one router per domain or resource (e.g., `users.py`, `items.py`,
  `orders.py`).
* **Instantiation:** Use `APIRouter()` instances, never attach routes directly to the `app` object
  in endpoint files.
* **Grouping:** Group related endpoints within the same router file.
* **Versioned registration:** Register each router with the versioned API router so the application
  factory can apply the `/api/{version}` prefix and any shared dependencies.
* **Trailing slashes:** Use canonical paths without a trailing slash for resource routes; allow
  FastAPI's redirect behavior to handle `.../` variants while documenting only the non-slashed form.

```python
from fastapi import APIRouter

router = APIRouter()

@router.get("")
async def list_items():
    ...
```

## 2. Router Configuration

Configure routers to reduce repetition and ensure consistent API structure.

* **Prefix:** Set the `prefix` argument at the router level (e.g., `prefix="/items"`) when
  including the router or initializing it (prefer registration time) so the resulting paths follow
  the no-trailing-slash convention (for example, `prefix="/items"` with `@router.get("")` yields
  `/items`).
* **Tags:** Use `tags` for grouping endpoints in the OpenAPI UI, and apply them consistently:
  either set tags at router registration time (preferred for a router) or on individual route
  decorators, but do not mix both patterns for the same router.
* **Dependencies:** Apply shared dependencies (such as authentication, authorization, rate
  limiting, and request logging) at the router level when they apply to all endpoints in that
  router.
* **Responses:** When many routes share the same response shapes, define common `responses` at
  router or registration time using the shared error and success contracts from the contracts
  module.

## 3. Route Handler Structure

Keep route handlers ("controllers") thin. Their responsibility is to:

1. Validate input (handled by Pydantic/FastAPI).
2. Call the appropriate Service layer method.
3. Return the response (Pydantic model).

**Standard Pattern:**

```python
@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: int,
    service: Annotated[ItemService, Depends(get_item_service)]
):
    return await service.get_item(item_id)
```

## 4. Dependency Injection in Routers

Use FastAPI's dependency injection system for services, settings, database sessions, and user
context.

* **Annotated:** Use `Annotated` type aliases for cleaner function signatures.
* **Service Injection:** Inject services rather than repositories or DB connections directly into
  routers.
* **Settings Injection:** Inject a configuration or settings object via `Depends(get_settings)`
  instead of reading from environment variables inside route handlers.
* **Shared providers:** Keep `get_*_service`, `get_settings`, and other provider functions in
  dedicated dependency modules so they can be reused by routers, background tasks, and tests (see
  the Dependency Injection Patterns documentation for common definitions).

```python
# Reusable type alias for a service dependency
ItemServiceDep = Annotated[ItemService, Depends(get_item_service)]

# Good: service and settings injection using aliases
async def create_item(
    item: ItemCreate,
    service: ItemServiceDep,
    settings: Annotated[AppSettings, Depends(get_settings)],
): ...

# Avoid: direct DB access from routers
async def create_item(
    item: ItemCreate,
    db: AsyncSession = Depends(get_db),
): ...
```

## 5. Request Validation

* **Pydantic Models:** Use Pydantic models for request bodies (defined in contracts).
* **Path/Query Parameters:** Use `Path`, `Query`, `Header` with strict types.
* **Constraints:** Use `Field` for validation rules (min_length, regex, etc.) in the Pydantic
  models, not in the router logic.

```python
async def list_items(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    user_agent: Annotated[str | None, Header()] = None,
) -> ItemsPage:
    ...
```

## 6. Response Handling

* **Response Models:** Always specify `response_model` in the decorator. This ensures output data
  filtering and validation.
* **Status Codes:** Explicitly set `status_code` for non-200 success cases (e.g., 201 Created).
* **Empty Responses:** For 204 No Content, use `response_model=None` and `status_code=204`.
* **Serializer:** Prefer the global default response class configured in the application factory;
  override it only for routes that truly need a different content type or serialization behavior.

```python
@router.post("/", response_model=ItemResponse, status_code=201)
async def create_item(item: ItemCreate, ...):
    ...

@router.delete("/{id}", response_model=None, status_code=204)
async def delete_item(id: int, ...):
    ...
```

## 7. Error Handling in Routers

* **Domain Exceptions:** Let the Service layer raise specific domain exceptions (e.g.,
  `ItemNotFound`, `DuplicateItem`).
* **Infrastructure Errors:** Let infrastructure components (for example, repository or client
  adapters) raise their own typed errors rather than converting them to HTTP responses.
* **Global Handlers:** Rely on global exception handlers (registered in the application core) to
  translate both domain and infrastructure exceptions into HTTP responses according to the shared
  error-handling conventions.
* **Router-Specific Errors:** Only raise `HTTPException` directly in the router for router-specific
  concerns such as authentication failures, authorization checks, and rate limiting.

## 8. OpenAPI Documentation

Maximize the utility of the auto-generated API docs.

* **Summary:** Every route must define a concise `summary` that describes its primary behavior.
* **Description:** Complex routes must also define a `description` that explains important details,
  side effects, and edge cases (Markdown supported).
* **Responses:** Document all relevant responses (success and error) using the `responses`
  parameter so that status codes, schemas, and examples are explicit.

```python
@router.get(
    "/{item_id}",
    response_model=ItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Get item by ID",
    description="Retrieves full item details including inventory status.",
    responses={
        200: {"description": "Item retrieved successfully"},
        400: VALIDATION_ERROR_RESPONSE,
        403: {"description": "Not authorized to view this item"},
        404: {"description": "Item not found"},
    },
)
async def get_item(
    item_id: int,
    service: Annotated[ItemService, Depends(get_item_service)],
) -> ItemResponse:
    ...
```

## 9. Router Registration

Centralize router registration in the main API router file.

* **Include Router:** Use `api_router.include_router()`.
* **Configuration:** Set the `prefix` and `tags` here to keep endpoint files clean.
* **Version prefix:** Apply the `/api/{version}` prefix in the application factory so routers
  remain version-agnostic.
* **Route ordering:** Register more specific routers before generic or catch-all routers to avoid
  shadowing.

```python
# Example of central router registration
from fastapi import APIRouter
from some_module import items_router

api_v1_router = APIRouter()

api_v1_router.include_router(
    items_router,
    prefix="/items",
    tags=["Items"],
)
```

## 10. Anti-Patterns to Avoid

* ❌ **Business Logic in Routers:** Do not perform calculations, complex conditionals, or raw DB
  queries in the route handler.
* ❌ **Direct DB Access:** Avoid `db.execute(...)` in routers. Use a Service.
* ❌ **Manual JSON Response:** Avoid returning dictionaries or `JSONResponse` manually unless
  absolutely necessary. Let FastAPI serialize Pydantic models.
* ❌ **Missing Response Model:** Always define the return schema.
* ❌ **Inconsistent documentation or error schemas:** Do not omit `summary`, `description`, or
  error `responses`, and do not handcraft unique error shapes per route.
* ❌ **Bypassing global error handling:** Do not raise HTTP errors directly from services or
  infrastructure layers; let global exception handlers convert domain and infrastructure errors
  into HTTP responses.
* ❌ **Blocking Code:** Do not use sync I/O methods in `async def` handlers or mix heavy
  synchronous work into async routes without proper offloading.
