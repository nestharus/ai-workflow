"""Test runner registry: picks the right runner for a given project root.

Inspects the project root for configuration files (pytest.ini, package.json,
Cargo.toml, etc.) to select the appropriate test runner.
"""

from __future__ import annotations

import logging
from pathlib import Path

from spec_manager.core.testing.runner import PytestRunner, TestRunner

logger = logging.getLogger(__name__)

# Well-known test configuration files mapped to runner IDs
_RUNNER_INDICATORS: list[tuple[list[str], str]] = [
    (["pytest.ini", "pyproject.toml", "setup.cfg", "conftest.py"], "pytest"),
]


class TestRunnerRegistry:
    """Registry that picks the right test runner for a project.

    Inspects the project root for configuration files to determine
    which test framework is in use.
    """

    def __init__(self) -> None:
        self._runners: dict[str, type] = {
            "pytest": PytestRunner,
        }

    def register(self, runner_id: str, runner_cls: type) -> None:
        """Register a new runner class."""
        self._runners[runner_id] = runner_cls

    def pick(self, *, root: Path, timeout_seconds: int = 300) -> TestRunner:
        """Pick the best test runner for the given project root.

        Returns PytestRunner by default (Python-first, extend later).
        """
        for indicators, runner_id in _RUNNER_INDICATORS:
            for indicator in indicators:
                if (root / indicator).exists():
                    runner_cls = self._runners.get(runner_id)
                    if runner_cls:
                        logger.debug(
                            "Picked %s runner for %s (found %s)",
                            runner_id,
                            root,
                            indicator,
                        )
                        if runner_id == "pytest":
                            return runner_cls(timeout_seconds=timeout_seconds)
                        return runner_cls()

        # Default to pytest
        logger.debug("No runner indicator found, defaulting to pytest for %s", root)
        return PytestRunner(timeout_seconds=timeout_seconds)

    def list_runners(self) -> list[str]:
        """List all registered runner IDs."""
        return list(self._runners.keys())
