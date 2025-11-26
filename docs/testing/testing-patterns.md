# Testing Patterns Documentation

This document tracks the planned testing-patterns documentation that will cover
concrete reset strategies and fixtures for repository testing.

## Status

In progress - this document serves as a tracking placeholder until the full
documentation is complete.

## Planned Sections

1. Reset Strategies
   * Transactional rollback approach
   * Truncation-based cleanup
   * Test database isolation patterns

2. Fixture Types
   * Unit test fixtures (mocked dependencies)
   * Integration test fixtures (real connections)
   * E2E test fixtures (Docker-based stacks)

3. Transaction vs Truncation
   * When to use transactional rollbacks
   * When truncation is more appropriate
   * Performance considerations

4. Examples
   * SurrealDB repository test fixtures
   * Elasticsearch index test fixtures
   * Combined stack testing patterns

5. Migration Checklist
   * Steps for adding new repository tests
   * Checklist for test data management
   * Guidelines for test isolation

## Source Materials

The following documents contain testing guidance to be adapted and integrated:

* `to_adapt/docs/to_integrate/TEST_1.md`
* `to_adapt/docs/to_integrate/e2e-testing-guide.md`
* `to_adapt/docs/to_integrate/e2e_dependencies.md`
* `to_adapt/docs/to_integrate/test_fixtures_soft_and_e2e.py`
* `to_adapt/docs/TEST.md`
* `to_adapt/docs/TESTING_ARCHITECTURE.md`
* `api-testing-patterns.md` (FastAPI testing patterns)

## Related Documentation

* `../development/repository-patterns.toon` - Repository implementation patterns
* `../development/dependency-patterns.md` - Dependency injection for testing
* `../../tests/conftest.py` - Current fixture implementations
