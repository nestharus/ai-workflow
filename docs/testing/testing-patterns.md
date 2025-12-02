# Use-Case-Based Test Coverage

This document defines the approach for tracking test coverage at the use-case level, ensuring that
tests validate user-facing scenarios and system requirements rather than just exercising code paths.

## 1. Introduction

Traditional code coverage metrics (line coverage, branch coverage) measure which code is executed
during tests but do not indicate whether user scenarios are actually validated. Use-case coverage
addresses this gap by tracking which user-facing scenarios have corresponding tests.

**Key distinctions:**

* **Code coverage**: Measures what percentage of source lines or branches are executed during tests.
* **Use-case coverage**: Measures how many defined user scenarios have tests that validate them.

A codebase can have 100% line coverage but still miss critical user scenarios if tests only exercise
code paths without asserting on expected behaviors. Conversely, well-designed use-case tests often
achieve high code coverage as a side effect of validating real functionality.

This approach aligns testing with user needs and system requirements, making test gaps visible and
actionable.

## 2. Use-Case Registry

The canonical use-case registry lives at `tests/docs/use_cases.yaml`. This file catalogs all testable
scenarios for the API, organized by feature area.

### 2.1 Registry Structure

```yaml
features:
  health:
    name: Health Checks
    description: Liveness and readiness probes for monitoring
    use_cases:
      - id: UC-HEALTH-001
        endpoint: /health
        method: GET
        description: Root liveness check returns 200 OK
        expected_behavior: |
          Returns HTTP 200 with JSON body {"status": "ok"}.
        test_tier: e2e
```

### 2.2 Field Definitions

| Field | Description |
|-------|-------------|
| `id` | Unique identifier following `UC-{FEATURE}-{NUMBER}` pattern |
| `endpoint` | Full API path (e.g., `/api/v1/health`) |
| `method` | HTTP method (GET, POST, PUT, DELETE, PATCH) |
| `description` | Human-readable scenario description |
| `expected_behavior` | Detailed expected outcome including status codes and response characteristics |
| `test_tier` | Where the test should live: `integration` or `e2e` |

**Note:** Coverage status is calculated dynamically from `@pytest.mark.usecase` markers in tests,
not stored in the registry. Uncovered use cases will appear in coverage reports.

### 2.3 Naming Convention

Use-case IDs follow the pattern `UC-{FEATURE}-{NUMBER}`:

* `UC-HEALTH-001`: First health-related use-case
* `UC-EXAMPLE-007`: Seventh example-feature use-case
* `UC-AUTH-003`: Third authentication use-case

Numbers are zero-padded to three digits for consistent sorting. When adding new use-cases, use the
next available number in the sequence.

### 2.4 When to Add Use-Cases

Add new use-cases when:

* Adding a new API endpoint
* Discovering new scenarios during testing or code review
* Identifying edge cases that should be explicitly tested
* Documenting validation rules that need test coverage
* Breaking down complex behaviors into atomic testable scenarios

Each use-case should represent an **atomic, testable scenario** with a single clear expected outcome.

## 3. Tagging Tests with Use-Case Markers

Tests are linked to use-cases using the `@pytest.mark.usecase` marker.

### 3.1 Basic Usage

```python
import pytest

@pytest.mark.usecase("UC-HEALTH-001")
async def test_root_health_check_returns_ok(api_client):
    """Verify root liveness probe returns healthy status."""
    response = await api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

### 3.2 Multiple Use-Cases per Test

When a single test validates multiple related scenarios, apply multiple markers:

```python
@pytest.mark.usecase("UC-EXAMPLE-010")
@pytest.mark.usecase("UC-EXAMPLE-011")
async def test_pagination_validation_errors(async_client):
    """Verify pagination parameters are validated."""
    # Test page < 1
    response = await async_client.get("/api/v1/examples/processed-messages?page=0")
    assert response.status_code == 422

    # Test page_size < 1
    response = await async_client.get("/api/v1/examples/processed-messages?page_size=0")
    assert response.status_code == 422
```

### 3.3 Marker Registration

The `usecase` marker must be registered in `pyproject.toml` under `[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
markers = [
    "e2e: marks tests as end-to-end (requires running server)",
    "usecase(id): links test to a use-case ID from tests/docs/use_cases.yaml"
]
```

### 3.4 Best Practice: One Test Per Use-Case

For maximum traceability, strive for a 1:1 mapping between use-cases and tests:

* Each use-case has exactly one test that validates it
* Each test links to exactly one use-case (unless scenarios are closely related)
* Test names reflect the use-case description

This makes it trivial to identify which test validates which scenario and vice versa.

## 4. Use-Case Coverage Reporting

Coverage reporting will be implemented via pytest hooks in `tests/conftest.py`.

### 4.1 Report Format

After test runs, a summary will display:

```text
========== Use-Case Coverage Report ==========
Total use-cases: 20
Covered: 15 (75%)
Uncovered: 5

Uncovered use-cases:
  - UC-HEALTH-003: Readiness check returns "unhealthy" when SurrealDB pool missing
  - UC-HEALTH-004: Readiness check returns "unhealthy" when Elasticsearch client missing
  - UC-EXAMPLE-008: List processed messages supports custom pagination parameters
  - UC-EXAMPLE-009: List processed messages returns page 2 correctly
  - UC-EXAMPLE-015: Get processed message handles different message types
==============================================
```

### 4.2 CI Integration

The coverage report can fail the build if coverage falls below the configured threshold:

```bash
# Fail if use-case coverage is below threshold
pytest --usecase-coverage-fail-under=<threshold>
```

### 4.3 Implementation Status

Use-case coverage is calculated automatically by scanning test files for `@pytest.mark.usecase`
markers. The coverage script (`scripts/dev/test_coverage.py`) detects which use-cases have
corresponding tests and reports coverage accordingly. No manual tracking is required.

## 5. Stub Tests for Uncovered Use-Cases

For use-cases that are known but not yet implemented, create stub tests with skip decorators.

### 5.1 Stub Pattern

```python
import pytest

@pytest.mark.skip(reason="Not implemented yet")
@pytest.mark.usecase("UC-HEALTH-003")
async def test_health_unhealthy_when_surrealdb_missing(async_client):
    """Readiness check returns unhealthy when SurrealDB pool is missing.

    TODO: Implement by:
    1. Override app.state to set surrealdb_pool = None
    2. Call /api/v1/health
    3. Assert status is "unhealthy"
    """
    pass
```

### 5.2 Benefits of Stub Tests

* **Visibility**: Missing coverage is explicit in test reports, not silently absent
* **Documentation**: Stubs describe what needs to be tested and how
* **Planning**: Easy to see total test work remaining
* **CI integration**: Skipped tests appear in reports with clear reasons

### 5.3 TODO Comments

Include implementation guidance in stub docstrings:

* What setup is required
* What actions to perform
* What assertions to make
* Any dependencies or prerequisites

## 6. Best Practices

### 6.1 Registry Maintenance

* Update `tests/docs/use_cases.yaml` when adding new endpoints or discovering new scenarios
* Add `@pytest.mark.usecase("UC-XXX-NNN")` markers to tests for automatic coverage detection
* Review the registry during sprint planning to identify coverage gaps
* Archive deprecated use-cases rather than deleting them (add `deprecated: true` field)

### 6.2 CI Enforcement

* Run use-case coverage reports in CI
* Set a minimum coverage threshold in project settings
* Block merges that reduce coverage without justification
* Review new endpoints to ensure corresponding use-cases are added

### 6.3 Traceability

* Include use-case IDs in test docstrings for documentation
* Reference use-case IDs in pull request descriptions when adding coverage
* Link test failures to use-case IDs in bug reports

### 6.4 Review Unlinked Tests

Periodically audit tests without use-case markers:

```bash
# Find tests without usecase markers (future tooling)
pytest --collect-only -q | grep -v usecase
```

Tests without markers may indicate:

* Missing use-cases in the registry
* Tests that should be removed or consolidated
* Implementation tests that belong at the unit level

### 6.5 Human-Readable Descriptions

Write descriptions and expected behaviors that non-developers can understand:

* Avoid implementation jargon
* Focus on what the user or system observes
* Include concrete examples of inputs and outputs

## 7. Integration with Existing Testing Tiers

This use-case approach integrates with the four-tier testing architecture. Different tiers have different
coverage requirements:

### 7.1 Coverage Types by Tier

| Tier | Coverage Type | Use-Case Markers |
|------|---------------|------------------|
| **Unit** | Line/branch per function | Not used |
| **Component** | Line/branch per function | Not used |
| **Integration** | Use-case coverage | Required |
| **E2E** | Use-case coverage | Required |

Coverage thresholds are configured in project settings.

### 7.2 Tier Assignment

| Tier | Use-Case Applicability |
|------|------------------------|
| **Unit tests** | Do not need use-case markers; test implementation details with per-function coverage |
| **Component tests** | Do not need use-case markers; test service layer with per-function coverage |
| **Integration tests** | Primary tier for use-case validation; most use-cases live here |
| **E2E tests** | For scenarios requiring full stack validation (startup, Docker, network) |

### 7.3 Test Tier Field

The `test_tier` field in the use-case registry indicates where tests should live:

* `integration`: Use `async_client` fixture, in-process testing
* `e2e`: Use `api_client` fixture, requires Docker stack

Reference the test tier when creating new tests to ensure consistent organization.

### 7.4 Fixture Selection

| Tier | Fixture | Transport |
|------|---------|-----------|
| Unit | Mocks/fakes | Direct function calls |
| Component | Mocks/fakes | Direct function calls |
| Integration | `async_client` | `httpx.ASGITransport` (in-process) |
| E2E | `api_client` | HTTP to live server |

### 7.5 Per-Function vs Use-Case Coverage

* **Unit/Component/Scripts tiers**: Each function must individually meet the configured line and branch
  coverage threshold. This is not an average—every single function is validated separately.
* **Integration/E2E tiers**: Use-cases must have corresponding tests with
  `@pytest.mark.usecase` markers (threshold configured in settings).

## 8. Examples

### 8.1 Complete Example: Use-Case to Test

**Use-case definition in `tests/docs/use_cases.yaml`:**

```yaml
- id: UC-EXAMPLE-002
  endpoint: /api/v1/examples/process
  method: POST
  description: Process endpoint succeeds with valid message
  expected_behavior: |
    Given a valid ExampleRequest with message between 1-500 chars,
    returns HTTP 200 with ExampleResponse containing processed result.
  test_tier: integration
```

**Corresponding test in `tests/integration/test_example_process.py`:**

```python
import pytest
from datetime import datetime, UTC

@pytest.mark.usecase("UC-EXAMPLE-002")
async def test_process_valid_message_succeeds(async_client):
    """Process endpoint returns ExampleResponse for valid input.

    Use-case: UC-EXAMPLE-002
    """
    payload = {"message": "Hello World", "type": "info"}

    response = await async_client.post("/api/v1/examples/process", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert "[PROCESSED]" in data["result"]
    assert data["original_length"] == len("Hello World")
    assert "processed_at" in data
```

### 8.2 Stub Test Example

```python
import pytest

@pytest.mark.skip(reason="Not implemented yet")
@pytest.mark.usecase("UC-EXAMPLE-014")
async def test_get_message_returns_404_for_nonexistent_id(async_client):
    """Get processed message returns 404 for non-existent ID.

    Use-case: UC-EXAMPLE-014

    TODO: Implement by:
    1. Request /api/v1/examples/processed-messages/nonexistent-id
    2. Assert HTTP 404
    3. Assert response body contains AppError with appropriate message
    """
    pass
```

### 8.3 Test Covering Multiple Use-Cases

```python
import pytest

@pytest.mark.usecase("UC-EXAMPLE-004")
@pytest.mark.usecase("UC-EXAMPLE-005")
async def test_process_message_length_validation(async_client):
    """Process endpoint validates message length constraints.

    Use-cases:
    - UC-EXAMPLE-004: Message exceeding 500 chars fails
    - UC-EXAMPLE-005: Empty message fails
    """
    # Too long
    long_message = "x" * 501
    response = await async_client.post(
        "/api/v1/examples/process",
        json={"message": long_message}
    )
    assert response.status_code == 422

    # Too short (empty after validation)
    response = await async_client.post(
        "/api/v1/examples/process",
        json={"message": ""}
    )
    assert response.status_code == 422
```

## Related Documentation

* [API Testing Patterns](api-testing-patterns.md) - Fixture composition, dependency overrides,
  assertion patterns
* [Testing Workflow](testing-workflow.md) - Test execution commands and tier descriptions
* [tests/docs/use_cases.yaml](../../tests/docs/use_cases.yaml) - The canonical use-case registry
