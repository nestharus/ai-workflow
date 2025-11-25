# Task 5 – Error contracts: ErrorCode and AppError

**Location:** `app/contracts/errors.py`

**Goal:** Provide a consistent error envelope for all non-validation errors, per
`exception-patterns.md`.

## Steps

**Step 1: Extend `app/contracts/errors.py`:** Import `Enum`, `ConfigDict` from Pydantic/typing.

**Step 2: Define `ErrorCode` enum:** Include values like `VALIDATION_ERROR`, `RESOURCE_NOT_FOUND`,
`UNAUTHORIZED`, `DOMAIN_VALIDATION_ERROR`, `INTERNAL_ERROR`, and optionally `EXAMPLE_INVALID`.

**Step 3: Define `AppError` Pydantic model:** Include fields `code: ErrorCode`, `message: str`,
`status_code: int` (alias `statusCode`), and `details: dict | list | None`. Set
`model_config = ConfigDict(extra="forbid")`.

**Step 4: Add helper constructors:** Create `from_domain(exc: DomainError)` class method that maps
domain errors to appropriate error codes and status codes. Create `internal_error()` class method
returning a standardized 500 error.

**Step 5: Keep existing validation models:** Ensure `HTTPValidationError` and related models remain
intact; they continue to be used for request validation responses (400).
