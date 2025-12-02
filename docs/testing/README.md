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
| **E2E** | Use-case | Full stack scenarios |
| **Scripts** | Line/branch per function | Scripts and tools |

Coverage thresholds are configured in project settings.

## Topics

### API Testing Patterns

**File:** `api-testing-patterns.md`

Defines how to test FastAPI endpoints across unit, integration, and E2E test layers. Covers fixture setup,
dependency overrides, async client configuration, and test organization for comprehensive API coverage.

**Apply when:**

* Writing unit tests for route handlers
* Setting up integration tests with test clients
* Creating E2E tests against live servers
* Configuring dependency overrides for testing

### Testing Patterns

**File:** `testing-patterns.md`

Defines the use-case-based test coverage approach. Explains how to link tests to use-cases using pytest
markers, manage the use-case registry in `tests/use_cases.yaml`, and track coverage at the scenario level.

**Apply when:**

* Writing integration or E2E tests
* Adding new use-cases to the registry
* Linking tests to use-case IDs with `@pytest.mark.usecase`
* Understanding the relationship between code coverage and use-case coverage

### Testing Workflow

**File:** `testing-workflow.md`

Describes the four-tier testing approach: Unit (all functions), Component (service layer), Integration
(use-case based), and E2E (full stack). Covers the `test-coverage` command, coverage rules, and common
test commands.

**Apply when:**

* Running tests at different levels (unit, component, integration, E2E)
* Understanding test fixture setup and scope
* Executing test commands for specific test tiers
* Understanding per-function vs use-case coverage requirements

### LLM Coverage Report

**File:** `testing-workflow.md` (section: LLM Coverage Report)

Describes the `llm-coverage-report` tool that generates an LLM-friendly JSON report combining:

* **Per-function coverage gaps**: Functions below threshold with tier-specific rules
* **Line/branch coverage gaps**: Missing lines with source context
* **Use-case coverage gaps**: Use-cases without tests from the registry

The tool auto-discovers tier-specific coverage files (`coverage_unit.json`, etc.) and applies
appropriate rules per tier (unit validates all functions, component validates service layer only).

**Apply when:**

* Identifying functions below the configured coverage threshold
* Finding uncovered use-cases from the registry
* Preparing coverage data for LLM-assisted test generation
* Analyzing coverage quality before code review
* Integrating coverage analysis into automated workflows
