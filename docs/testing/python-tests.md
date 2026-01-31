# How To Run And Understand Python Tests

Test coverage is enforced separately for each test tier using `uv run test-coverage`.

## Test Tiers

| Tier | Test Path | Coverage Type | Target |
|------|-----------|---------------|--------|
| **unit** | `tests/unit/` | 80% line / 70% branch | All `app/` functions |
| **component** | `tests/component/` | 100% use-case | `app/services/` only |
| **integration** | `tests/integration/` | 100% use-case | `app/api/` endpoints |
| **scripts** | `scripts/tests/` | 80% line / 70% branch | `scripts/` only |

> **Note**: The `scripts/tests/` directory is organized into `unit/`, `component/`, and
> `integration/` subdirectories for consistency with the main test structure.

## Coverage Rules

* **Per-function thresholds**: Line 80%, branch 70% per function (unit/scripts tiers)
* **Overall thresholds**: Line 80%, branch 70% overall (unit/scripts tiers)
* **Class fields excluded**: Pydantic model type annotations are excluded from coverage
* **Service layer**: Component tests only validate functions within `app/services/`
* **Use-case coverage**: Component/integration require 100% use-case coverage
* **Private functions**: Unit tests validate all functions; component/integration/scripts skip private

## Validation Commands

```bash
# Run all test tiers (test credentials auto-configured by pytest)
uv run test-coverage

# Run specific tier
uv run test-coverage --tier unit
uv run test-coverage --tier integration

# Custom thresholds (override defaults)
uv run test-coverage --min-line 90 --min-branch 85

# Report only (no validation)
uv run test-coverage --no-validate

# Legacy pytest-cov commands still work
uv run pytest --cov
uv run pytest --cov --cov-report=html
```

**Output**: Test coverage data is written to `.coverage/coverage.db` SQLite database,
which contains per-function coverage statistics, use-case coverage, test results, and
detailed missing line/branch information. Analysis tools (`coverage-summary`,
`coverage-files`, `coverage-file`, `coverage-functions`) read from this database.

## Spec Refinement Integration Tests

Location: `tests/spec_refinement/test_full_workflow.py`

These tests validate the complete 6-phase workflow end-to-end with:
* Filesystem isolation (pyfakefs)
* Agent mocking (monkeypatch)
* Performance benchmarks (pytest-benchmark)
* Gap convergence tracking
* Repair gate validation

Run with: `uv run pytest tests/spec_refinement/test_full_workflow.py -v`
