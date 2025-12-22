# Testing Workflow

Testing is divided into four tiers to balance feedback speed, comprehensive verification, and appropriate
coverage metrics for each testing level.

## Test Tiers Overview

| Tier | Test Path | Coverage Type | Target | Speed |
|------|-----------|---------------|--------|-------|
| **Unit** | `tests/unit/` | Line/branch per function | All `app/` functions | Fast |
| **Component** | `tests/unit/` | Line/branch per function | `app/services/` only | Fast |
| **Integration** | `tests/integration/` | Use-case | Use cases from YAML | Fast |
| **Scripts** | `scripts/tests/` | Line/branch per function | `scripts/` | Fast |

> **Configuration**: Tier paths, thresholds, and behavior are configured in `pyproject.toml`.
> See [Tier Configuration](README.md#tier-configuration) for the full configuration reference
> and [Migrating to the New Tier Format](README.md#migrating-to-the-new-tier-format) for
> migration instructions if using the legacy format.

## Unit Tests

* **Location**: `tests/unit/`
* **Coverage**: Line and branch coverage per function (threshold configured in settings)
* **Target**: All functions in `app/` including private functions
* **Fixture**: Uses mocks and fakes for isolation
* **Command**: `uv run test-coverage --tier unit`

Unit tests validate individual functions and methods in isolation. Coverage is measured per-function,
meaning each function must individually meet the configured threshold.

## Component Tests

* **Location**: `tests/unit/` (service-focused tests)
* **Coverage**: Line and branch coverage per function (threshold configured in settings)
* **Target**: Only functions within `app/services/` (service layer)
* **Scope**: Tests service layer public API; private functions are skipped
* **Command**: `uv run test-coverage --tier component`

Component tests target the service layer, treating it as the public API of the application. Private
functions within services are implementation details and are excluded from coverage validation.

## Integration Tests

* **Location**: `tests/integration/`
* **Coverage**: Use-case coverage (threshold configured in settings)
* **Target**: Use cases defined in `tests/docs/use_cases.yaml`
* **Fixture**: `async_client` (uses `httpx.ASGITransport`)
* **Scope**: Tests application logic with mocked external dependencies; no network overhead
* **Command**: `uv run test-coverage --tier integration`

Integration tests validate user-facing scenarios defined in the use-case registry. Each test must be
linked to a use-case with `@pytest.mark.usecase("UC-XXX-NNN")`.

### Custom Tiers

You can define additional test tiers beyond the four built-in tiers. Custom tiers are useful for:
* End-to-end (e2e) tests with different coverage requirements
* Performance or smoke tests with separate threshold settings
* Module-specific test suites

Example custom tier configuration:

```toml
[tool.test_coverage.tiers.e2e]
test_path = "tests/e2e"
source_paths = ["app"]
coverage_type = "usecase"
min_usecase = 100.0
```

Run a specific custom tier with:

```bash
uv run test-coverage --tier e2e
```

See [Tier Configuration](README.md#tier-configuration) for required and optional fields.

## Coverage Rules

* **Per-function**: Each function must individually meet the configured threshold (not averaged across file)
* **Class fields excluded**: Pydantic model type annotations are excluded from coverage
* **Service layer**: Component tests only validate functions within `app/services/`
* **Use-case coverage**: Integration requires coverage of use cases (threshold in settings)
* **Private functions**: Unit tests validate ALL functions; component/scripts skip private

## Common Test Commands

> **Note**: `pytest-check` is available for multiple soft assertions in a single test.
> Example: `check.equal(result, expected)`.

```bash
# Run all test tiers with validation
uv run test-coverage

# Run specific tier
uv run test-coverage --tier unit
uv run test-coverage --tier integration

# Report only (no validation failures)
uv run test-coverage --no-validate

# Generate JSON report
uv run test-coverage --json-report coverage_report.json

# Legacy pytest commands
uv run pytest                       # Run all tests
uv run pytest -v                    # Verbose output
```

## Coverage Database

The `test-coverage` command generates a comprehensive coverage database at `.coverage/coverage.db`
containing all coverage metrics, test results, and analysis data. This SQLite database serves as
the single source of truth for all coverage information.

### Database Schema

The coverage database includes custom tables (prefixed with `cc_`) that store:

* **Run metadata**: Timestamp and repository information
* **Tier configuration**: Coverage thresholds and settings from `pyproject.toml`
* **Function coverage**: Per-function line/branch coverage with pass/fail flags
* **Missing lines**: Uncovered lines with source context and branch information
* **Use-case registry**: Use cases defined in `tests/docs/use_cases.yaml`
* **Use-case coverage**: Which use cases are covered by tests
* **Test results**: Individual test pass/fail status with error details
* **Tier summaries**: Overall metrics and pass/fail status per tier

For detailed schema information, see `docs/plans/coverage_consolidation_plan.md`.

### Analysis Tools

After running `test-coverage`, use these tools to analyze coverage data:

```bash
# View summary of all tiers
uv run coverage-summary

# List all files with coverage metrics
uv run coverage-files

# View detailed coverage for a specific file
uv run coverage-file app/core/factory.py

# List functions below threshold
uv run coverage-functions
```

All analysis tools read directly from `.coverage/coverage.db` and support filtering by tier
and file path. Use `--help` on any tool to see available options.
