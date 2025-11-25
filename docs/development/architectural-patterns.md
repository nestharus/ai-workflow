# Architectural Patterns

The application follows a strict layered architecture to ensure separation of concerns
and testability.

## Routers (`app/routes/`)

**Role**: Handle HTTP request/response lifecycle.

**Pattern**: Use `APIRouter` instances registered in `app/core/factory.py`.

**Standards**:

* No business logic in routers
* Use Pydantic models for `response_model`
* Include `summary`, `description`, and `responses` for OpenAPI documentation

**Example**: `app/routes/example_router.py`

## Services (`app/services/`)

**Role**: Encapsulate business logic.

**Pattern**: Class-based services with dependency injection.

**Lifecycle**:

* `__init__`: Initialize dependencies
* `process()`: Core logic methods
* `shutdown()`: Cleanup resources

**Standards**: Pure Python objects, agnostic of the HTTP layer.

**Example**: `app/services/example_service.py`

## Contracts/DTOs (`app/contracts/`)

**Role**: Define data structures and validation rules.

**Pattern**: Pydantic models with strict configuration.

**Standards**:

* `ConfigDict(extra="forbid")` to reject unknown fields
* Use `Annotated` and `Field` for validation constraints
* Define custom validators (`@model_validator`) for complex logic

**Example**: `app/contracts/example_contract.py`
