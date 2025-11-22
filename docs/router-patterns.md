# Router Patterns

This document establishes the standards for building API routers in the application. Following these patterns ensures consistency, testability, and proper OpenAPI documentation.

## 1. APIRouter Organization

*   **Granularity:** Create one router per domain or resource (e.g., `users.py`, `items.py`, `orders.py`).
*   **Instantiation:** Use `APIRouter()` instances, never attach routes directly to the `app` object in endpoint files.
*   **Grouping:** Group related endpoints within the same router file.

```python
# app/api/v1/endpoints/items.py
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def get_items():
    ...
```

## 2. Router Configuration

Configure routers to reduce repetition and ensure consistent API structure.

*   **Prefix:** Set the `prefix` argument at the router level (e.g., `prefix="/items"`) when including the router or initializing it (prefer registration time).
*   **Tags:** Use `tags` for grouping endpoints in the OpenAPI UI.
*   **Dependencies:** Apply shared dependencies (like auth) at the router level if they apply to all endpoints in that router.

## 3. Route Handler Structure

Keep route handlers ("controllers") thin. Their responsibility is to:
1.  Validate input (handled by Pydantic/FastAPI).
2.  Call the appropriate Service layer method.
3.  Return the response (Pydantic model).

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

Use FastAPI's dependency injection system for services, database sessions, and user context.

*   **Annotated:** Use `Annotated` type aliases for cleaner function signatures.
*   **Service Injection:** Inject services rather than repositories or DB connections directly into routers.

```python
# Good
async def create_item(
    item: ItemCreate,
    service: Annotated[ItemService, Depends(get_item_service)]
): ...

# Avoid
async def create_item(
    item: ItemCreate,
    db: AsyncSession = Depends(get_db) 
): ...
```

## 5. Request Validation

*   **Pydantic Models:** Use Pydantic models for request bodies (defined in contracts).
*   **Path/Query Parameters:** Use `Path`, `Query`, `Header` with strict types.
*   **Constraints:** Use `Field` for validation rules (min_length, regex, etc.) in the Pydantic models, not in the router logic.

## 6. Response Handling

*   **Response Models:** Always specify `response_model` in the decorator. This ensures output data filtering and validation.
*   **Status Codes:** Explicitly set `status_code` for non-200 success cases (e.g., 201 Created).
*   **Empty Responses:** For 204 No Content, use `response_model=None` and `status_code=204`.

```python
@router.post("/", response_model=ItemResponse, status_code=201)
async def create_item(item: ItemCreate, ...):
    ...

@router.delete("/{id}", response_model=None, status_code=204)
async def delete_item(id: int, ...):
    ...
```

## 7. Error Handling in Routers

*   **Domain Exceptions:** Let the Service layer raise specific domain exceptions (e.g., `ItemNotFound`, `DuplicateItem`).
*   **Global Handlers:** Rely on global exception handlers (registered in the application core) to translate domain exceptions into HTTP responses.
*   **Router-Specific Errors:** Only raise `HTTPException` directly in the router for request-layer issues (e.g., malformed headers that Pydantic misses).

## 8. OpenAPI Documentation

Maximize the utility of the auto-generated API docs.

*   **Summary:** Provide a concise summary for the sidebar.
*   **Description:** Use the `description` parameter for details (Markdown supported).
*   **Responses:** Document error states using the `responses` parameter.

```python
@router.get(
    "/{id}",
    summary="Get item by ID",
    description="Retrieves full item details including inventory status.",
    responses={
        404: {"description": "Item not found"},
        403: {"description": "Not authorized to view this item"}
    }
)
```

## 9. Router Registration

Centralize router registration in the main API router file.

*   **Include Router:** Use `api_router.include_router()`.
*   **Configuration:** Set the `prefix` and `tags` here to keep endpoint files clean.

```python
# Example of central router registration
from fastapi import APIRouter
from app.api.v1.endpoints import items

api_router = APIRouter()
api_router.include_router(items.router, prefix="/items", tags=["Items"])
```

## 10. Anti-Patterns to Avoid

*   ❌ **Business Logic in Routers:** Do not perform calculations, complex conditionals, or raw DB queries in the route handler.
*   ❌ **Direct DB Access:** Avoid `db.execute(...)` in routers. Use a Service.
*   ❌ **Manual JSON Response:** Avoid returning dictionaries or `JSONResponse` manually unless absolutely necessary. Let FastAPI serialize Pydantic models.
*   ❌ **Missing Response Model:** Always define the return schema.
*   ❌ **Blocking Code:** Do not use sync I/O methods in `async def` handlers.
