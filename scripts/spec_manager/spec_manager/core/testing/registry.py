"""Test runner registry: picks the right runner for a given project root.

Inspects the project root for configuration files (pytest.ini, package.json,
Cargo.toml, etc.) to select the appropriate test runner.
"""

from __future__ import annotations

import logging
from pathlib import Path

from spec_manager.core.testing.runner import PytestRunner, TestRunner

logger = logging.getLogger(__name__)


class RunnerSelectionError(RuntimeError):
    """Raised when runner selection is unknown or ambiguous."""


def _pyproject_declares_pytest(pyproject_path: Path) -> bool:
    if not pyproject_path.exists():
        return False
    try:
        content = pyproject_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "[tool.pytest" in content


def _setup_cfg_declares_pytest(setup_cfg_path: Path) -> bool:
    if not setup_cfg_path.exists():
        return False
    try:
        content = setup_cfg_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "[tool:pytest]" in content or "[pytest]" in content


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

        Raises:
            RunnerSelectionError: when no runner can be determined or selection is ambiguous.
        """
        candidates: set[str] = set()
        if (
            (root / "pytest.ini").exists()
            or (root / "conftest.py").exists()
            or _pyproject_declares_pytest(root / "pyproject.toml")
            or _setup_cfg_declares_pytest(root / "setup.cfg")
        ):
            candidates.add("pytest")

        available_candidates = sorted(
            runner_id for runner_id in candidates if runner_id in self._runners
        )

        if len(available_candidates) == 1:
            runner_id = available_candidates[0]
            runner_cls = self._runners[runner_id]
            logger.debug("Picked %s runner for %s", runner_id, root)
            if runner_id == "pytest":
                return runner_cls(timeout_seconds=timeout_seconds)
            return runner_cls()

        if len(available_candidates) > 1:
            raise RunnerSelectionError(
                f"Ambiguous test runner selection for {root}: {available_candidates}"
            )

        raise RunnerSelectionError(
            f"No test runner detected for {root}. "
            "Add runner configuration (for example pytest.ini or [tool.pytest] in pyproject.toml)."
        )

    def list_runners(self) -> list[str]:
        """List all registered runner IDs."""
        return list(self._runners.keys())
