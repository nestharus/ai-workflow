# Service Layer Patterns

This document establishes the architectural patterns for the service layer in the AI Workflow system. The service layer encapsulates business logic, orchestrates data access, and ensures clean separation between the API (HTTP) layer and the persistence layer.

## 1. Service Layer Responsibilities

The service layer is the heart of the application's business logic. Its primary responsibilities are:

*   **Business Logic Encapsulation:** Implementing core use cases and business rules.
*   **Orchestration:** Coordinating calls to multiple repositories or external clients (e.g., fetching data from DB, processing it, and sending an event).
*   **Transaction Management:** Defining transaction boundaries to ensure data consistency across operations.
*   **Domain Error Handling:** Raising domain-specific exceptions (subclasses of `DomainError`) rather than HTTP exceptions.
*   **HTTP Agnostic:** Services must **never** import `fastapi`, `starlette`, or handle `Request`/`Response` objects directly.

## 2. Service Class Structure

Services are implemented as classes to allow for dependency injection and state management (where appropriate).

### Standard Pattern

```python
from app.contracts.common import ServiceResult
from app.contracts.example_contract import ExampleResponse

class OrderService:
    """
    Service for managing order lifecycle.
    
    Attributes:
        order_repository: Repository for order persistence.
        payment_gateway: Client for payment processing.
    """

    def __init__(self, order_repository: OrderRepository, payment_gateway: PaymentGateway):
        self.order_repository = order_repository
        self.payment_gateway = payment_gateway

    async def process_order(self, order_id: str) -> ServiceResult[ExampleResponse]:
        """
        Process a pending order.

        Args:
            order_id: The unique identifier of the order.

        Returns:
            ServiceResult containing the processed order details.

        Raises:
            OrderNotFoundError: If the order does not exist.
            PaymentFailedError: If the payment capture fails.
        """
        # Business logic implementation
        pass

    async def shutdown(self):
        """Cleanup resources if necessary (e.g., closing specific connections)."""
        pass
```

*   **Constructor (`__init__`)**: Accepts dependencies explicitly.
*   **Methods**: Represent business actions (verbs like `create`, `process`, `calculate`).
*   **Cleanup (`shutdown`)**: Optional method for resource cleanup.
*   **Type Hints**: Mandatory for all arguments and return values.
*   **Docstrings**: Follow the Google style guide as defined in the project's docstring guidelines.

## 3. Dependency Injection Pattern

We use FastAPI's dependency injection system to provide services to routers. Services, in turn, receive their dependencies (repositories, settings) via their constructors.

### Injection in Routers

Do not instantiate services directly in route handlers. Use `Depends`.

**Correct:**
```python
# Example of service injection in a router
from fastapi import APIRouter, Depends
# from app.services.order_service import OrderService
# from app.core.dependencies import get_order_service

router = APIRouter()

@router.post("/{order_id}/process")
async def process_order(
    order_id: str,
    service: OrderService = Depends(get_order_service)
):
    return await service.process_order(order_id)
```

### Dependency Factory

Define factories to wire up the service dependencies.

```python
# Example dependency provider
from fastapi import Depends
# from app.infrastructure.db import get_db_session
# from app.services.order_service import OrderService

def get_order_service(session = Depends(get_db_session)) -> OrderService:
    repo = OrderRepository(session)
    return OrderService(repo)
```

## 4. Transaction Management

Services define the boundaries of a unit of work.

*   **Transactional Methods**: Operations that modify state should run within a transaction.
*   **Async Context Managers**: Use `async with` blocks for acquiring connections or transactions.
*   **Commit/Rollback**: The service decides when to commit (success) or rollback (error).

**Example Pattern:**

```python
async def create_order(self, order_data: CreateOrderSchema):
    # Start transaction boundary
    async with self.repository.transaction() as txn:
        try:
            order = await self.repository.create(order_data)
            await self.audit_log.log_creation(order.id)
            await txn.commit()
            return order
        except Exception:
            await txn.rollback()
            raise
```

## 5. Error Handling in Services

Services must raise **Domain Exceptions**, not HTTP Exceptions. This keeps the service layer decoupled from the transport layer.

### Principles

1.  **Define Custom Exceptions**: Create a hierarchy of exceptions (e.g., `AppError` -> `DomainError` -> `ResourceNotFoundError`).
2.  **Catch Technical Errors**: Catch low-level database errors (e.g., `IntegrityError`) and wrap/re-raise them as domain errors (e.g., `DuplicateRecordError`).
3.  **Global Handling**: Rely on the global exception handler (registered in the application core) to translate `ResourceNotFoundError` to a 404 HTTP response.

**Anti-Pattern (Do NOT do this):**
```python
from fastapi import HTTPException

class BadService:
    async def get_item(self, id: str):
        if not found:
            raise HTTPException(status_code=404, detail="Item not found") # WRONG
```

**Correct Pattern:**
```python
class GoodService:
    async def get_item(self, id: str):
        if not found:
            raise ItemNotFoundError(f"Item {id} not found") # RIGHT
```

## 6. Service Testing Strategy

Services are the easiest layer to test because they don't depend on external frameworks.

*   **Unit Tests**: Test logic in isolation. Mock repositories and external clients.
    *   Use `unittest.mock` or `pytest-mock`.
    *   Verify that repositories are called with expected arguments.
*   **Integration Tests**: specific integration tests can verify service interaction with real database implementations using the `async_client` fixture in test configuration.
*   **Dependency Overrides**: In full application tests, use `app.dependency_overrides` to replace real services with mocks if needed (though E2E tests usually prefer real implementations).

## 7. Service Lifecycle

*   **Request Scoped**: Most services are instantiated per request. This ensures thread safety and proper resource isolation (e.g., database sessions).
*   **Singleton Scoped**: Services that hold stateless logic or shared thread-safe connections (like an HTTP client pool) *may* be singletons, but request-scoped is safer by default.
*   **Lifespan Management**: Hooks in application factory manage the startup and shutdown of global resources (DB pools) that services rely on.

## 8. Anti-Patterns to Avoid

*   **God Services**: Avoid creating a single `MainService` that does everything. Split services by domain (e.g., `UserService`, `OrderService`).
*   **Anemic Services**: Services that just pass data to a repository without any logic. If a service adds no value, consider if it's needed, but generally, keep the layer for future extensibility.
*   **Leaky Abstractions**: Returning ORM objects directly to the API layer. Always map domain entities or ORM models to Pydantic Contracts (DTOs) before returning from the service.
*   **Global State**: Relying on module-level variables or `app.state` inside the service logic. Pass everything via `__init__`.
