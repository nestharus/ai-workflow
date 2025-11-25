# Testing

This module covers documentation for writing and running test code.

## Topics

### API Testing Patterns

**File:** `api-testing-patterns.md`

Defines how to test FastAPI endpoints across unit, integration, and E2E test layers. Covers fixture setup, dependency overrides, async client configuration, and test organization for comprehensive API coverage.

**Apply when:**

* Writing unit tests for route handlers
* Setting up integration tests with test clients
* Creating E2E tests against live servers
* Configuring dependency overrides for testing

### Testing Patterns

**File:** `testing-patterns.md`

Tracks planned documentation for repository testing, database reset strategies, and
fixture patterns. This placeholder outlines future coverage for data layer testing
approaches.

**Apply when:**

* Writing repository unit tests
* Setting up database fixtures
* Implementing test data reset strategies

### Testing Workflow

**File:** `testing-workflow.md`

Describes the two-tier testing approach balancing feedback speed and comprehensive
verification. Covers Integration Tests (fast, in-process, `async_client` fixture) and
E2E Tests (slow, live server, `api_client` fixture with Docker). Includes common test
commands and `pytest-check` usage for multiple soft assertions.

**Apply when:**

* Running tests at different levels (unit, integration, E2E)
* Understanding test fixture setup and scope
* Executing test commands for specific test tiers
