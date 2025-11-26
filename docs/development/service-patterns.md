# Service Layer Patterns

This document establishes the architectural patterns for the service layer in
the AI Workflow system. The service layer encapsulates business logic,
orchestrates data access, and ensures clean separation between the API (HTTP)
layer and the persistence layer.

In this codebase, routers in `app/api/v1/endpoints/` handle HTTP concerns,
services in `app/services/` implement business rules and use cases, and
infrastructure modules such as `app/infrastructure/db_connections.py` manage
database and search connections.

## Scope for this document

This guide covers the service layer only:

* Defining what a service is and how it sits between routers and repositories.
* Service responsibilities, boundaries, and HTTP-agnostic design.
* Constructor-based dependency injection for repositories, settings, and clients.
* Transaction management where services coordinate units of work and repositories do not commit.
* Patterns for raising domain exceptions from services and testing services in isolation.

## Out of scope for this document

The following topics are documented elsewhere and are intentionally not
covered in detail here:

* Router decorators, HTTP status codes, and response wiring (see router and exception pattern
  documents).
* HTTP error schemas and OpenAPI documentation details.
* Direct data-access implementation details, including repository design and connection pooling.

## 1. Service Layer Responsibilities

The service layer is the heart of the application's business logic. Its primary responsibilities
are:

* **Business Logic Encapsulation:** Implementing core use cases and business rules.
* **Orchestration:** Coordinating calls to multiple repositories or external clients (e.g.,
  fetching data from DB, processing it, and sending an event).
* **Transaction Management:** Defining transaction boundaries to ensure data consistency across
  operations.
* **Domain Error Handling:** Raising domain-specific exceptions (subclasses of `DomainError`,
  defined in `app/core/errors.py`) rather than HTTP exceptions.
* **HTTP Agnostic:** Services must **never** import `fastapi`, `starlette`, handle
  `Request`/`Response` objects directly, or embed HTTP status codes in their public APIs.

## 2. Service Class Structure

Services are implemented as classes to allow for dependency injection and state management (where
appropriate).

### Standard Pattern

```python
class OrderService:
    """Service for managing order lifecycle.

    Attributes:
        order_repository: Repository for order persistence.
        payment_gateway: Client for payment processing.
    """

    def __init__(self, order_repository: OrderRepository, payment_gateway: PaymentGateway) -> None:
        """Create a service with its collaborators."""
        self.order_repository = order_repository
        self.payment_gateway = payment_gateway

    async def process_order(self, order_id: str) -> Order:
        """Process a pending order and return the updated order.

        Args:
            order_id: The unique identifier of the order.

        Returns:
            Order: The processed order details.

        Raises:
            OrderNotFoundError: If the order does not exist.
            PaymentFailedError: If the payment capture fails.
        """
        # 1. Fetch order from repository
        order = await self.order_repository.get_by_id(order_id)
        if order is None:
            raise OrderNotFoundError(order_id)

        # 2. Capture payment via gateway
        payment_result = await self.payment_gateway.capture(order.payment_intent_id)
        if not payment_result.success:
            raise PaymentFailedError(order_id, payment_result.error)

        # 3. Update order status and persist
        order.status = OrderStatus.PROCESSED
        await self.order_repository.update(order)
        return order

    async def shutdown(self) -> None:
        """Cleanup resources if necessary (e.g., closing specific connections)."""
        pass
```

* **Constructor (`__init__`)**: Accepts dependencies explicitly.
* **Methods**: Represent business actions (verbs like `create`, `process`, `calculate`).
* **Cleanup (`shutdown`)**: Optional method for resource cleanup.
* **Type Hints**: Mandatory for all arguments and return values.
* **Docstrings**: Follow the Google-style guidance in `docs/docstrings-guide.md`.
* **Exception Documentation**: List all domain exceptions a method may raise in a `Raises` section
  so callers know which failures to handle.

## 3. Dependency Injection Pattern

Services receive their dependencies via constructors rather than globals or module-level state.
This makes them easy to instantiate in tests and keeps dependencies explicit.

Constructor-based injection pattern:

```python
class UserService:
    def __init__(self, user_repo: UserRepository, settings: Settings) -> None:
        self._user_repo = user_repo
        self._settings = settings
```

When a service needs multiple collaborators (repositories, clients, and configuration objects),
add them as typed constructor parameters. For composition or testing, it is often useful to define
a small factory function that wires the service together:

```python
def build_user_service(
    user_repo: UserRepository,
    settings: Settings,
) -> UserService:
    return UserService(user_repo=user_repo, settings=settings)
```

Database sessions or pools (for example, an ORM session or a SurrealDB connection pool) should be
created in the request context by outer layers and passed into repositories or services as
constructor arguments. Services must not create global connections or reach into application state
to obtain them.

In this project, runtime configuration is provided by a `Settings` object via the `get_settings()`
dependency in `app/core/dependencies.py`. Router-level dependencies obtain a `Settings` instance
from there and pass it into service constructors, following the constructor-based pattern above.

## 4. Transaction Management

Services define the boundaries of a unit of work.

* **Transactional Methods**: Operations that modify state should run within a transaction.
* **Async Context Managers**: Use `async with` blocks for acquiring connections or transactions.
* **Commit/Rollback**: Services commit on success and roll back when a domain exception signals
  failure.

Repositories must not commit or roll back transactions themselves; they translate domain
operations into database or search calls, while services own the unit-of-work boundary. See the
repository patterns documentation for additional guidance on repository responsibilities.

**Example Pattern:**

```python
async def create_order(self, order_data: CreateOrderSchema) -> Order:
    # Start transaction boundary
    async with self.repository.transaction() as txn:
        try:
            order = await self.repository.create(order_data)
            await self.audit_log.log_creation(order.id)
            await txn.commit()
            return order
        except DomainError:
            await txn.rollback()
            raise
```

## 5. Error Handling in Services

Services must raise **Domain Exceptions**, not HTTP Exceptions. This keeps the service layer
decoupled from the transport layer.

### Principles

1. **Define Custom Exceptions**: Create a hierarchy of exceptions (e.g., `AppError` ->
   `DomainError` -> `ResourceNotFoundError`).
2. **Catch Technical Errors**: Catch low-level database errors (e.g., `IntegrityError`) and
   wrap/re-raise them as domain errors (e.g., `DuplicateRecordError`).
3. **Global Handling**: Rely on transport-layer exception handlers (for example, those registered
   in `app/core/factory.py` for HTTP) to translate domain errors into appropriate
   transport-specific responses.

Service code does not decide which HTTP status codes to use or how errors are serialized for
clients; that mapping lives in the HTTP and exception pattern documents and their corresponding
code.

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

* **Unit Tests**: Test logic in isolation. Mock repositories and external clients.
  * Use `unittest.mock` or `pytest-mock`.
  * Verify that repositories are called with expected arguments.
* **Integration Tests**: specific integration tests can verify service interaction with real
  database implementations and real repositories. The fixtures in `tests/conftest.py` show
  patterns for test isolation and swapping implementations via dependency injection.

## 7. Service Lifecycle

* **Request Scoped**: Most services are instantiated per request. This ensures thread safety and
  proper resource isolation (e.g., database sessions).
* **Singleton Scoped**: Services that hold stateless logic or shared thread-safe connections (like
  an HTTP client pool) *may* be singletons, but request-scoped is safer by default.
* **Lifespan Management**: Hooks in the application factory manage the startup and shutdown of
  global resources (DB pools) that services rely on.
* **Long-Lived Services**: For background or long-lived services that own external resources,
  implement a `shutdown()` method on the service and ensure it is called during application
  shutdown.

## 8. Anti-Patterns to Avoid

* Services that are just thin wrappers around repositories with no business logic.
* Services that import FastAPI or Starlette types such as `Request`, `Response`, or
  `HTTPException`.
* Services that directly access `app.state` or other global variables instead of receiving
  dependencies via constructors.
* Services that mix multiple unrelated business domains into a single class.
* Services that perform I/O without using proper `async`/`await` in async codepaths.
