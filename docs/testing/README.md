# Testing

This module covers documentation for writing and running test code.

## Test Coverage Command

The primary command for running tests with coverage validation is:

```bash
uv run test-coverage
```

This validates all test tiers with appropriate coverage requirements.

## Test Tiers

| Tier | Coverage Type | Description |
|------|---------------|-------------|
| **Unit** | Line/branch per function | All functions in `app/` |
| **Component** | Use-case | Service layer use-cases (tests in `tests/component/`) |
| **Integration** | Use-case | User scenarios from YAML |
| **Scripts** | Line/branch per function | Scripts and tools |

Coverage thresholds are configured in project settings.

## Tier Configuration

Test tiers are configured in `pyproject.toml` under `[tool.test_coverage]`. There are two
supported configuration formats: the recommended **tiers subtable format** and the legacy
**flat section format**.

### Tiers Subtable Format (Recommended)

Define complete tier configurations using `[tool.test_coverage.tiers.<tier_name>]` subtables.
This format allows all tier properties to be specified in one place:

```toml
[tool.test_coverage.tiers.unit]
test_path = "tests/unit"
source_paths = ["app"]
coverage_type = "line_branch"
min_line_overall = 80.0
min_branch_overall = 70.0
min_line_per_function = 60.0
min_branch_per_function = 50.0
skip_private_functions = false
exclude_class_fields = true

[tool.test_coverage.tiers.component]
test_path = "tests/component"
source_paths = ["app/services"]
coverage_type = "usecase"
min_usecase = 100.0

[tool.test_coverage.tiers.integration]
test_path = "tests/integration"
source_paths = ["app/api"]
coverage_type = "usecase"
min_usecase = 100.0
exclude_patterns = ["__init__.py", "router.py", "dependencies.py"]
```

**Required fields** (for all tiers in the new format - derived from `TestTierConfig`):

| Field | Type | Description |
|-------|------|-------------|
| `test_path` | `str` | Path to the test directory (e.g., `"tests/unit"`) |
| `source_paths` | `list[str]` | Paths to source directories (e.g., `["app", "lib"]`) |
| `coverage_type` | `str` | Either `"line_branch"` or `"usecase"` |

> **Note**: The `name` field is derived automatically from the TOML key (e.g., `[tool.test_coverage.tiers.unit]` sets `name="unit"`).

**Optional fields** (with defaults from `TestTierConfig`):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `min_line_overall` | `float` | `80.0` | Minimum overall line coverage percentage |
| `min_branch_overall` | `float` | `70.0` | Minimum overall branch coverage percentage |
| `min_line_per_function` | `float` | `60.0` | Minimum line coverage per function percentage |
| `min_branch_per_function` | `float` | `50.0` | Minimum branch coverage per function percentage |
| `min_usecase` | `float` | `100.0` | Minimum use-case coverage percentage (for `usecase` type) |
| `skip_private_functions` | `bool` | `False` | Skip functions starting with `_` (except `__init__`, `__call__`) |
| `exclude_class_fields` | `bool` | `True` | Exclude class field annotations from coverage |
| `exclude_patterns` | `list[str]` | `None` | File patterns to exclude from coverage |

**Tier Ordering**: Tiers execute in the order they appear in the TOML file. TOML preserves
insertion order, so the first `[tool.test_coverage.tiers.<name>]` section runs first. This
is important when tiers depend on each other (e.g., running unit tests before component tests
to establish baseline coverage).

### Legacy Flat Section Format (Deprecated)

The legacy format uses individual `[tool.test_coverage.<tier>]` sections. Built-in tiers
(unit, component, integration, scripts) have path/type defaults in `DEFAULT_TIER_CONFIGS`;
you only specify threshold overrides.

```toml
[tool.test_coverage.unit]
min_line_overall = 80.0
min_branch_overall = 70.0
```

When `get_test_tiers()` detects this legacy format (no `[tool.test_coverage.tiers]` section),
it prints a deprecation warning to stderr recommending migration.

See [Migrating to the New Tier Format](#migrating-to-the-new-tier-format) for instructions.

## Migrating to the New Tier Format

If your `pyproject.toml` uses the legacy `[tool.test_coverage.<tier>]` format, you will see
this deprecation warning when running `uv run test-coverage`:

```txt
DEPRECATION WARNING: Using legacy tier configuration format.
Consider migrating to [tool.test_coverage.tiers.<tier_name>] format.
See docs/testing/README.md for migration instructions.
```

### Migration Steps

1. **Create the tiers subtable structure**: For each existing `[tool.test_coverage.<tier>]`
   section, create a corresponding `[tool.test_coverage.tiers.<tier>]` section.

2. **Add required fields**: In the new format, all tiers must specify `test_path`,
   `source_paths`, and `coverage_type`. Copy these from `DEFAULT_TIER_CONFIGS` in
   `scripts/dev/test_runner/test_coverage.py` or use the reference values below.

3. **Copy threshold values**: Move `min_line_overall`, `min_branch_overall`, etc. from the
   legacy section to the new tiers subtable.

4. **Remove legacy sections**: After verifying the new configuration works, remove or
   comment out the old `[tool.test_coverage.<tier>]` sections.

### Reference: Built-in Tier Defaults

Use these values when migrating built-in tiers:

| Tier | test_path | source_paths | coverage_type | skip_private_functions |
|------|-----------|--------------|---------------|------------------------|
| unit | `tests/unit` | `["app"]` | `line_branch` | `false` |
| component | `tests/component` | `["app/services"]` | `usecase` | `true` |
| integration | `tests/integration` | `["app/api"]` | `usecase` | `true` |
| scripts | `scripts/tests` | `["scripts", "tools"]` | `line_branch` | `true` |

> **Note**: The `scripts/tests` directory is internally organized into `unit/`, `component/`, and
> `integration/` subdirectories for consistency with the main test structure, but all tests under
> `scripts/tests/` are part of the single "scripts" tier.

### Example Migration

**Before (legacy format):**

```toml
[tool.test_coverage.unit]
min_line_overall = 80.0
min_branch_overall = 70.0
min_line_per_function = 60.0
min_branch_per_function = 50.0

[tool.test_coverage.integration]
min_usecase = 100.0
```

**After (tiers subtable format):**

```toml
[tool.test_coverage.tiers.unit]
test_path = "tests/unit"
source_paths = ["app"]
coverage_type = "line_branch"
min_line_overall = 80.0
min_branch_overall = 70.0
min_line_per_function = 60.0
min_branch_per_function = 50.0
skip_private_functions = false
exclude_class_fields = true

[tool.test_coverage.tiers.integration]
test_path = "tests/integration"
source_paths = ["app/api"]
coverage_type = "usecase"
min_usecase = 100.0
exclude_patterns = ["__init__.py", "router.py", "dependencies.py"]
```

### Validation

After migration, run `uv run test-coverage` to verify:
* No deprecation warning appears (confirms new format is detected)
* All tiers execute with expected thresholds
* Tier order matches your TOML file order

### --no-validate Behavior

The `--no-validate` flag skips coverage threshold validation, but its effect differs between tier types:

| Tier Type | --no-validate Effect |
|-----------|---------------------|
| **Line/Branch** (unit, scripts) | Coverage thresholds skipped; test failures still cause `tier_pass=0` |
| **Usecase** (component, integration) | All gating disabled; `tier_pass` is always `1` |

**Line/Branch Tiers**: When `--no-validate` is used, functions below the coverage threshold do
not cause validation failure. However, test execution results are always respected - if any test
fails, the tier still fails (`tier_pass=0`).

**Usecase Tiers**: When `--no-validate` is used, the tier is always considered passed
(`tier_pass=1`). This is because usecase tiers only check whether `@pytest.mark.usecase` markers
exist in test files; they do not track individual test pass/fail status.

**Guidance**: Use `--no-validate` for exploratory runs or when you want coverage metrics
without enforcement. Do not use it in CI pipelines that require coverage gates. Teams adding
custom usecase tiers should be aware that `--no-validate` effectively disables all gating for
usecase coverage.

## Topics

### API Testing Patterns

**File:** `api-testing-patterns.md`

Defines how to test FastAPI endpoints across unit and integration test layers. Covers fixture setup,
dependency overrides, async client configuration, and test organization for comprehensive API coverage.

**Apply when:**

* Writing unit tests for route handlers
* Setting up integration tests with test clients
* Configuring dependency overrides for testing

### Testing Patterns

**File:** `testing-patterns.md`

Defines the use-case-based test coverage approach. Explains how to link tests to use-cases using pytest
markers, manage the use-case registry in `tests/docs/use_cases.yaml`, and track coverage at the scenario level.

**Apply when:**

* Writing integration tests
* Adding new use-cases to the registry
* Linking tests to use-case IDs with `@pytest.mark.usecase`
* Understanding the relationship between code coverage and use-case coverage

### Testing Workflow

**File:** `testing-workflow.md`

Describes the four-tier testing approach: Unit (all functions), Component (service layer), Integration
(use-case based), and Scripts. Covers the `test-coverage` command, coverage rules, and common
test commands.

**Apply when:**

* Running tests at different levels (unit, component, integration, scripts)
* Understanding test fixture setup and scope
* Executing test commands for specific test tiers
* Understanding per-function vs use-case coverage requirements

### Coverage Database and Analysis Tools

**File:** `testing-workflow.md` (section: Coverage Database)

The `test-coverage` command generates a comprehensive SQLite database (`.coverage/coverage.db`)
that serves as the single source of truth for all coverage information. The database contains:

* **Per-function coverage**: Line/branch coverage with pass/fail flags and tier-specific rules
* **Missing lines**: Uncovered lines with source context and branch information
* **Use-case coverage**: Coverage status for all use cases from the registry
* **Test results**: Individual test pass/fail status with error details
* **Tier summaries**: Overall metrics and pass/fail status per tier

Analysis tools (`coverage-summary`, `coverage-files`, `coverage-file`, `coverage-functions`)
read directly from this database and support filtering by tier and file path.

**Apply when:**

* Identifying functions below the configured coverage threshold
* Finding uncovered use-cases from the registry
* Analyzing coverage quality before code review
* Reviewing detailed coverage metrics for specific files
* Investigating test failures and coverage gaps
