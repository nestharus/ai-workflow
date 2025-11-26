# Development

This module covers documentation for writing application code. This includes docstrings, code style, FastAPI
practices, etc.

## Topics

### Settings Patterns

**File:** `settings-patterns.md`

Defines how to model, validate, and consume runtime configuration using Pydantic settings. Covers environment
variable binding, validation rules, and settings composition for different deployment environments.

**Apply when:**

* Defining application configuration models
* Adding new environment variables
* Validating configuration at startup

### Factory Patterns

**File:** `factory-patterns.md`

Covers application construction, lifespan management, and configuration patterns for building FastAPI
applications. Establishes how to wire together routers, middleware, and services during application startup.

**Apply when:**

* Setting up application entry points
* Configuring application lifespan events
* Wiring routers and middleware

### Dependency Patterns

**File:** `dependency-patterns.md`

Establishes FastAPI dependency injection patterns using Annotated type aliases. Defines how to wire services,
repositories, and other dependencies into route handlers for testability and separation of concerns.

**Apply when:**

* Creating injectable services and repositories
* Defining reusable dependency type aliases
* Wiring database connections into handlers

### Router Patterns

**File:** `router-patterns.md`

Defines FastAPI router organization, route handler structure, and OpenAPI documentation standards. Covers how to
structure endpoints, handle request/response models, and document APIs for clarity.

**Apply when:**

* Creating new API endpoints
* Organizing routes by domain
* Adding OpenAPI documentation to handlers

### Service Patterns

**File:** `service-patterns.md`

Establishes service layer architecture for encapsulating business logic and transaction management. Defines how
services coordinate between routers and repositories while maintaining separation of concerns.

**Apply when:**

* Writing business logic for domain operations
* Coordinating multiple repository calls
* Managing transactions and rollbacks

### Repository Patterns

**File:** `repository-patterns.md`

Defines data access layer patterns, repository interfaces, and query patterns for persistence code. Covers how
to abstract database operations behind clean interfaces for testability.

**Apply when:**

* Writing database query code
* Defining repository interfaces
* Implementing CRUD operations

### Middleware Patterns

**File:** `middleware-patterns.md`

Covers HTTP middleware implementation, ordering, and configuration for cross-cutting concerns. Defines how to
add request/response processing for logging, security headers, and error handling.

**Apply when:**

* Adding cross-cutting HTTP behavior
* Configuring security headers
* Implementing request/response logging

### Exception Patterns

**File:** `exception-patterns.md`

Defines how to design domain exceptions, error handling, and HTTP error mapping. Establishes a consistent
approach to raising, catching, and translating exceptions into appropriate API responses.

**Apply when:**

* Defining domain-specific exceptions
* Mapping exceptions to HTTP status codes
* Implementing error handling in services

### Connection Pooling Patterns

**File:** `connection-pooling-patterns.md`

Describes how to create, configure, and manage database and search client pools. Covers pool sizing, connection
lifecycle, and health checking for infrastructure resources.

**Apply when:**

* Configuring database connection pools
* Setting up search client connections
* Managing pool lifecycle and cleanup

### API Patterns

**File:** `api-patterns.md`

Establishes REST API design standards including URL structure, request/response modeling, and OpenAPI
documentation conventions. Defines consistent patterns for resource naming, pagination, and error responses.

**Apply when:**

* Designing new API endpoints
* Modeling request and response schemas
* Documenting API contracts

### Docstrings Guide

**File:** `docstrings-guide.md`

Defines Google-style docstring conventions and standards for documenting code. Covers
function, class, and module documentation with examples for consistent codebase
documentation.

**Apply when:**

* Writing function and class documentation
* Documenting module-level code
* Adding parameter and return type descriptions

### Architectural Patterns

**File:** `architectural-patterns.md`

Defines the strict layered architecture for separation of concerns and testability.
Covers Routers (HTTP request/response lifecycle), Services (business logic encapsulation
with dependency injection), and Contracts/DTOs (data structures and validation rules
with Pydantic). Includes standards, patterns, and lifecycle details for each layer.

**Apply when:**

* Designing new application components
* Understanding layer responsibilities and boundaries
* Implementing routers, services, or contracts
