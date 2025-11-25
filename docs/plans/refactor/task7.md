# Task 7 – Settings and API prefix

**Locations:** `app/core/settings.py`, factory integration

**Goal:** Move hard-coded `/api/v1` to settings and add any new config knobs implied by the plan
(example prefix, middleware toggles).

## Steps

**Step 1: Extend `app/core/settings.py`:** Add fields with sensible defaults including
`api_prefix: str = "/api/v1"`, `example_prefix: str = "[PROCESSED]"`, and middleware-related
toggles like `enable_gzip`, `enforce_https`, `allowed_hosts`, and CORS-related fields.

**Step 2: Update `app/core/factory.py`:** Replace `prefix="/api/v1"` with
`prefix=settings.api_prefix` when including the router.

**Step 3: Wire new settings fields:** Update `ExampleService` to consume `settings.example_prefix`.
Use middleware toggles when wiring middleware in Task 8.

**Step 4: Tests and docs:** Adjust any tests that assert a hard-coded prefix. Update docs to
mention the new settings fields.
