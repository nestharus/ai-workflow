# Task 10 – OpenAPI enrichment and schema tests

**Locations:** `factory.py`, tests

**Goal:** Ensure `HTTPValidationError`, `AppError`, and `ErrorCode` are all present in OpenAPI and
add tests that assert schema completeness.

## Steps

**Step 1: OpenAPI customization in `app/core/factory.py`:** In the custom `openapi` function,
ensure `components.schemas` is set up and includes entries for `HTTPValidationError`, `AppError`,
and `ErrorCode`.

**Step 2: Schema tests:** Create a new module `tests/unit/test_openapi_schema.py`. Use `Settings()`
and `create_app(settings)` to build an app. Call `app.openapi()` and assert that required schemas
and paths exist.

**Step 3: Update plan docs:** Add a section under testing/API schema noting the custom OpenAPI
registration and the new schema tests.
