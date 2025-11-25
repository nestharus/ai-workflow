# Task 2 – Adjust example router prefix, paths, and docs

**Path:** `/api/v1/examples`

**Decision:** Treat `example` endpoints as **demo** endpoints, not a first-class resource.

**Goal:** Use plural resource prefix but keep demo-style suffixes, and document them explicitly.

## Steps

**Step 1: Update `app/api/v1/router.py`:** Change the example router registration to use
`prefix="/examples"` and `tags=["Examples"]`.

**Step 2: Update paths in `app/api/v1/endpoints/example.py`:** Keep the existing suffixes like
`/sample` and `/process`. Ensure `router = APIRouter()` has no prefix of its own.

**Step 3: Document demo nature:** In module-level docstring and/or route `description`, explicitly
state these are non-resource demo endpoints.

**Step 4: Use DI aliases:** Change route signatures to use `ExampleServiceDep` from
`app/api/v1/dependencies.py` (from Task 1).

**Step 5: Adjust tests referencing example paths:** Search under `tests/` for `/api/v1/example/`
and update to `/api/v1/examples/`, including `tests/unit/test_validation_errors.py`.

**Step 6: Ensure router-patterns compliance:** Confirm all example routes use canonical paths
without trailing slashes, have `response_model` defined, and use `status_code` constants from
`fastapi.status` where applicable.
