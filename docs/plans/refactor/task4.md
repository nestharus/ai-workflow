# Task 4 – Core domain error hierarchy

**Location:** `app/core/errors.py`

**Goal:** Introduce a shared domain exception hierarchy to be used by services and repositories,
independent of HTTP concerns.

## Steps

**Step 1: Create `app/core/errors.py`:** Define `DomainError` as the base class for domain/business
logic errors. Add generic subclasses: `ResourceNotFoundError`, `DomainValidationError`, and
`UnauthorizedError`. Give each a docstring and keep them HTTP-agnostic (no status codes).

**Step 2: Update services (starting with `ExampleService`):** Import and raise these domain errors
instead of returning sentinel values or using `HTTPException`.

**Step 3:** Update any existing code currently using ad hoc domain exceptions to inherit from
`DomainError`.
