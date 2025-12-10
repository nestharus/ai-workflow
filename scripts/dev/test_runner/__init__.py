"""Test runner scripts for coverage reports and test execution.

This package provides:
- test_coverage: Main coverage runner with multi-tier support
- test_strategies: Strategy pattern implementations for test execution
- coverage_db: SQLite database operations for coverage data
- junit_parser: JUnit XML parsing utilities
- redundant_test_detector: Analysis for redundant test detection
"""

from scripts.dev.test_runner.test_strategies import (
    IntegrationTestStrategy,
    LineBranchTestStrategy,
    TestStrategy,
    create_strategy,
)

__all__ = [
    "IntegrationTestStrategy",
    "LineBranchTestStrategy",
    "TestStrategy",
    "create_strategy",
]
