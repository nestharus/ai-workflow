"""Integration tests for linter execution with real linters.

These tests invoke actual linter binaries and require them to be installed
on the system. Tests are skipped if the required binaries are not available.

Test Organization:
- TestRealLinterExecution: Tests that invoke real linter binaries
"""

import shutil

import pytest

from scripts.dev.linter.base import (
    LinterResult,
    execute_phase,
)


def _linter_available(name: str) -> bool:
    """Check if a linter binary is available on the system."""
    # Map linter names to their binary names
    binary_map = {
        "scripts": None,  # scripts linter doesn't need external binary
        "checkov": "checkov",
        "ruff": "ruff",
        "mypy": "mypy",
    }
    binary = binary_map.get(name)
    if binary is None:
        return True  # Linter doesn't need external binary
    return shutil.which(binary) is not None


class TestRealLinterExecution:
    """Integration tests for execute_phase with real linters.

    These tests require actual linter binaries to be installed on the system.
    Tests are skipped if required binaries are not available.
    """

    @pytest.mark.skipif(
        not _linter_available("scripts"),
        reason="scripts linter not available",
    )
    def test_execute_single_real_linter(self) -> None:
        """Test executing a single real linter (ScriptsLinter)."""
        results = execute_phase(["scripts"], None)

        assert len(results) == 1
        assert "scripts" in results
        assert isinstance(results["scripts"], LinterResult)

    @pytest.mark.skipif(
        not (_linter_available("scripts") and _linter_available("checkov")),
        reason="scripts or checkov linter not available",
    )
    def test_execute_multiple_real_linters_in_parallel(self) -> None:
        """Test executing multiple real linters in parallel."""
        results = execute_phase(["scripts", "checkov"], None)

        assert len(results) == 2
        assert "scripts" in results
        assert "checkov" in results
        assert isinstance(results["scripts"], LinterResult)
        assert isinstance(results["checkov"], LinterResult)

    @pytest.mark.skipif(
        not _linter_available("scripts"),
        reason="scripts linter not available",
    )
    def test_mixed_known_unknown_linters(self) -> None:
        """Test parallel execution with mix of known and unknown linters."""
        results = execute_phase(["scripts", "fake-linter-xyz"], None)

        assert len(results) == 2
        assert isinstance(results["scripts"], LinterResult)
        assert results["fake-linter-xyz"].success is False
        assert "Unknown linter" in (results["fake-linter-xyz"].message or "")

    @pytest.mark.skipif(
        not (_linter_available("scripts") and _linter_available("checkov")),
        reason="scripts or checkov linter not available",
    )
    def test_execute_phase_returns_linter_result_type(self) -> None:
        """Test that all results from real linters are LinterResult instances."""
        results = execute_phase(["scripts", "checkov"], None)

        for linter_name, result in results.items():
            assert isinstance(result, LinterResult), (
                f"Result for {linter_name} is not LinterResult: {type(result)}"
            )
            assert isinstance(result.success, bool)
            assert result.message is None or isinstance(result.message, str)
