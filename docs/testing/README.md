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
| **Component** | Line/branch per function | Service layer (`app/services/`) only |
| **Integration** | Use-case | User scenarios from YAML |
| **Scripts** | Line/branch per function | Scripts and tools |

Coverage thresholds are configured in project settings.

### --no-validate Behavior

The `--no-validate` flag skips coverage threshold validation, but its effect differs between tier types:

| Tier Type | --no-validate Effect |
|-----------|---------------------|
| **Line/Branch** (unit, component, scripts) | Coverage thresholds skipped; test failures still cause `tier_pass=0` |
| **Usecase** (integration) | All gating disabled; `tier_pass` is always `1` |

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

### Automated Test Workflow

**File:** `testing-workflow.md` (section: Automated Test Workflow)

The `test-workflow` CLI provides an automated test generation workflow that orchestrates strategy
creation, planning, writing, debugging, and coverage validation. The state machine and contracts
are defined by `scripts/tasks/workflows/test_automation.py` (orchestrator) and the agent prompts
in `.tasks/agents/test-strategy.md`, `.tasks/agents/test-planner.md`, `.tasks/agents/test-writer-nodebug.md`,
and `.tasks/agents/test-debugger.md`.

```bash
uv run test-workflow app/services/user_service.py app/api/endpoints/users.py
```

The workflow operates as a loop: **strategy → plan → strategy-review → writer → debugger →
plan-review → coverage**. It continues iterating until coverage thresholds are met or maximum
iterations are exceeded.

**Apply when:**

* Generating tests for new or modified source files
* Automating the test creation process for implementation plans
* Ensuring coverage thresholds are met through iterative feedback
* Orchestrating multiple testing agents in a structured workflow
