# Testing Workflow

Testing is divided into two tiers to balance feedback speed and comprehensive verification.

## Integration Tests

* **Location**: `tests/integration/`
* **Speed**: Fast (in-process)
* **Fixture**: `async_client` (uses `httpx.ASGITransport`)
* **Scope**: Tests application logic with mocked external dependencies where appropriate;
  no network overhead
* **Command**: `uv run pytest tests/integration/`

## E2E Tests

* **Location**: `tests/e2e/`
* **Speed**: Slow (requires live server)
* **Fixture**: `api_client` (builds and runs a Docker container on port 8008)
* **Marker**: `@pytest.mark.e2e`
* **Scope**: Validates full stack, startup scripts, health checks, and network handling
* **Command**: `uv run pytest -m e2e`

## Common Test Commands

> **Note**: `pytest-check` is available for multiple soft assertions in a single test.
> Example: `check.equal(result, expected)`.

```bash
# Run all tests (including E2E)
uv run pytest

# Run only fast tests (skip E2E)
uv run pytest -m "not e2e"

# Run only E2E tests
uv run pytest -m e2e

# Run with verbose output
uv run pytest -v
```
