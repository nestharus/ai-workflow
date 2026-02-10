from __future__ import annotations

import pytest

from spec_manager.core.testing.runner import (
    PytestRunner,
    TestFailure,
    TestRunResult,
)
from spec_manager.core.testing.registry import TestRunnerRegistry


# ------------------------------------------------------------------
# TestFailure dataclass
# ------------------------------------------------------------------


def test_failure_defaults():
    f = TestFailure()
    assert f.test_id is None
    assert f.file is None
    assert f.message == ""
    assert f.raw_excerpt_path == ""


def test_failure_with_values():
    f = TestFailure(test_id="tests/test_x.py::test_y", file="tests/test_x.py", message="boom")
    assert f.test_id == "tests/test_x.py::test_y"
    assert f.file == "tests/test_x.py"
    assert f.message == "boom"


# ------------------------------------------------------------------
# TestRunResult dataclass
# ------------------------------------------------------------------


def test_run_result_defaults():
    r = TestRunResult()
    assert r.passed is False
    assert r.scope == "SLICE"
    assert r.runner_id == ""
    assert r.command == []
    assert r.failures == []
    assert r.total_tests == 0
    assert r.passed_tests == 0
    assert r.failed_tests == 0
    assert r.duration_ms == 0.0


def test_run_result_with_values():
    r = TestRunResult(
        passed=True,
        scope="FULL",
        runner_id="pytest",
        total_tests=10,
        passed_tests=10,
    )
    assert r.passed is True
    assert r.scope == "FULL"
    assert r.total_tests == 10


# ------------------------------------------------------------------
# PytestRunner._parse_failures
# ------------------------------------------------------------------


def test_parse_failures():
    stdout = (
        "FAILED tests/test_foo.py::test_bar - AssertionError: expected 1 got 2\n"
        "FAILED tests/test_baz.py::test_qux - RuntimeError: oops\n"
        "3 failed, 5 passed in 1.23s"
    )
    failures = PytestRunner._parse_failures(stdout)
    assert len(failures) == 2
    assert failures[0].test_id == "tests/test_foo.py::test_bar"
    assert failures[0].file == "tests/test_foo.py"
    assert "AssertionError" in failures[0].message
    assert failures[1].test_id == "tests/test_baz.py::test_qux"
    assert failures[1].file == "tests/test_baz.py"
    assert "RuntimeError" in failures[1].message


def test_parse_failures_no_message():
    stdout = "FAILED tests/test_x.py::test_y\n1 failed in 0.5s"
    failures = PytestRunner._parse_failures(stdout)
    assert len(failures) == 1
    assert failures[0].test_id == "tests/test_x.py::test_y"
    assert failures[0].message == ""


def test_parse_failures_empty_output():
    failures = PytestRunner._parse_failures("")
    assert failures == []


# ------------------------------------------------------------------
# PytestRunner._parse_counts
# ------------------------------------------------------------------


def test_parse_counts():
    stdout = "5 passed, 2 failed in 1.23s"
    counts = PytestRunner._parse_counts(stdout)
    assert counts["passed"] == 5
    assert counts["failed"] == 2
    assert counts["total"] == 7


def test_parse_counts_only_passed():
    stdout = "10 passed in 0.50s"
    counts = PytestRunner._parse_counts(stdout)
    assert counts["passed"] == 10
    assert counts["failed"] == 0
    assert counts["total"] == 10


def test_parse_counts_only_failed():
    stdout = "3 failed in 2.00s"
    counts = PytestRunner._parse_counts(stdout)
    assert counts["passed"] == 0
    assert counts["failed"] == 3
    assert counts["total"] == 3


def test_parse_counts_no_summary():
    stdout = "collecting ..."
    counts = PytestRunner._parse_counts(stdout)
    assert counts["total"] == 0
    assert counts["passed"] == 0
    assert counts["failed"] == 0


def test_parse_counts_multiline():
    stdout = (
        "tests/test_a.py ..\n"
        "tests/test_b.py F\n"
        "============================\n"
        "12 passed, 1 failed in 3.45s"
    )
    counts = PytestRunner._parse_counts(stdout)
    assert counts["passed"] == 12
    assert counts["failed"] == 1
    assert counts["total"] == 13


# ------------------------------------------------------------------
# PytestRunner attributes
# ------------------------------------------------------------------


def test_pytest_runner_id():
    runner = PytestRunner()
    assert runner.runner_id == "pytest"


def test_pytest_runner_extra_args():
    runner = PytestRunner(extra_args=["--verbose", "-x"])
    assert runner._extra_args == ["--verbose", "-x"]


# ------------------------------------------------------------------
# TestRunnerRegistry
# ------------------------------------------------------------------


def test_registry_default_has_pytest():
    registry = TestRunnerRegistry()
    assert "pytest" in registry.list_runners()


def test_registry_pick_default(tmp_path):
    """No indicator files -> defaults to PytestRunner."""
    registry = TestRunnerRegistry()
    runner = registry.pick(root=tmp_path)
    assert runner.runner_id == "pytest"


def test_registry_pick_with_conftest(tmp_path):
    """conftest.py present -> picks PytestRunner."""
    (tmp_path / "conftest.py").write_text("")
    registry = TestRunnerRegistry()
    runner = registry.pick(root=tmp_path)
    assert runner.runner_id == "pytest"


def test_registry_pick_with_pyproject(tmp_path):
    """pyproject.toml present -> picks PytestRunner."""
    (tmp_path / "pyproject.toml").write_text("[tool.pytest]")
    registry = TestRunnerRegistry()
    runner = registry.pick(root=tmp_path)
    assert runner.runner_id == "pytest"


def test_registry_register_custom(tmp_path):
    class DummyRunner:
        runner_id = "dummy"
        def run(self, *, root, scope="SLICE", targets=None):
            return TestRunResult(passed=True, runner_id="dummy")

    registry = TestRunnerRegistry()
    registry.register("dummy", DummyRunner)
    assert "dummy" in registry.list_runners()


def test_registry_list_runners():
    registry = TestRunnerRegistry()
    runners = registry.list_runners()
    assert isinstance(runners, list)
    assert len(runners) >= 1
