# Task 3 – Health router tags and readiness docs

**Goal:** Align health endpoint with tag casing and readiness semantics while preserving existing
contracts.

## Steps

**Step 1: Update `app/api/v1/router.py` include for health:** Use no extra prefix on the health
router so that exactly one `/health` segment is applied. Use `tags=["Health"]`.

**Step 2: Update `app/api/v1/endpoints/health.py`:** Keep or add `response_model=HealthResponse`.
Add `summary="Readiness health check"` and optional `description` explaining it checks overall
service readiness, distinct from the unversioned `/health` liveness check.

**Step 3: Check OpenAPI grouping:** Verify that the health endpoint appears under the `"Health"`
tag in generated docs.

**Step 4: Plan doc update:** In `docs/plans/plan.md`, mention changing tags to `"Health"` and
keeping `/health` vs `/api/v1/health` semantics consistent (liveness vs readiness).
