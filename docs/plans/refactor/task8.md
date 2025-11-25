# Task 8 – Middleware stack and settings

**Locations:** `app/core/middleware.py`, `factory.py` wiring

**Goal:** Implement the core middleware stack per middleware-patterns and configure it via settings.

## Steps

**Step 1: Create `app/core/middleware.py`:** Implement at least `SecurityHeadersMiddleware` as an
ASGI class that adds security headers and optional HSTS. Optionally add `RequestIDMiddleware` and
`RequestLoggingMiddleware`.

**Step 2: Update `app/core/settings.py`:** Ensure fields exist for `enable_gzip`, `enforce_https`,
`allowed_hosts`, and CORS toggles.

**Step 3: Wire middleware in `app/core/factory.py`:** Import and register middlewares using
`app.add_middleware()` in the documented order (last added runs first on request path).

**Step 4: Tests:** Add or update tests to verify security headers are present and GZip is applied
when appropriate.

**Step 5: Update plan docs:** Add a middleware section listing the new module, settings fields, and
wiring order.

## Implementation Notes

* Added `app/core/middleware.py` with `SecurityHeadersMiddleware` (includes HSTS when
  `Settings.enforce_https` is true) and registered it via the factory.
* Introduced `Settings.cors_enabled` and defaulted `allowed_hosts` to `['*']` alongside existing
  CORS and compression flags.
* Middleware order in `create_app`: GZip (optional) → Security headers → CORS (optional) → HTTPS
  redirect (optional) → Trusted hosts.
* Added `tests/unit/test_middleware.py` to verify security headers, HSTS, and gzip behavior.
