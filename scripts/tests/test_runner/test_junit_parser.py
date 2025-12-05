"""Tests for junit_parser module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scripts.dev.test_runner.junit_parser import TestResult, TestSummary, parse_junit_xml

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestParseJunitXml:
    """Tests for parse_junit_xml function."""

    def test_parses_passed_test(self, fs: FakeFilesystem) -> None:
        """Should parse a passed test correctly."""
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" errors="0" failures="0" skipped="0" time="0.123">
    <testcase classname="tests.unit.test_main" name="test_success" time="0.123"/>
</testsuite>
"""
        fs.create_file("/junit.xml", contents=xml_content)

        results, summary = parse_junit_xml(Path("/junit.xml"))

        assert len(results) == 1
        assert results[0].test_name == "tests/unit/test_main.py::test_success"
        assert results[0].status == "passed"
        assert results[0].duration == 0.123
        assert results[0].message is None
        assert results[0].traceback is None

        assert summary.total == 1
        assert summary.passed == 1
        assert summary.failed == 0
        assert summary.errors == 0
        assert summary.skipped == 0

    def test_parses_failed_test(self, fs: FakeFilesystem) -> None:
        """Should parse a failed test with failure message and traceback."""
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" errors="0" failures="1" skipped="0" time="0.456">
    <testcase classname="tests.unit.test_main" name="test_failure" time="0.456">
        <failure message="AssertionError: expected True">
Traceback (most recent call last):
  File "test_main.py", line 10, in test_failure
    assert False
AssertionError: expected True
        </failure>
    </testcase>
</testsuite>
"""
        fs.create_file("/junit.xml", contents=xml_content)

        results, summary = parse_junit_xml(Path("/junit.xml"))

        assert len(results) == 1
        assert results[0].test_name == "tests/unit/test_main.py::test_failure"
        assert results[0].status == "failed"
        assert results[0].duration == 0.456
        assert results[0].message == "AssertionError: expected True"
        assert results[0].traceback is not None
        assert "Traceback" in results[0].traceback
        assert "AssertionError: expected True" in results[0].traceback

        assert summary.total == 1
        assert summary.passed == 0
        assert summary.failed == 1
        assert summary.errors == 0
        assert summary.skipped == 0

    def test_parses_error_test(self, fs: FakeFilesystem) -> None:
        """Should parse a test with an error."""
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" errors="1" failures="0" skipped="0" time="0.123">
    <testcase classname="tests.unit.test_main" name="test_error" time="0.123">
        <error message="ImportError: No module named 'missing'">
Traceback (most recent call last):
  File "test_main.py", line 5, in test_error
    import missing
ImportError: No module named 'missing'
        </error>
    </testcase>
</testsuite>
"""
        fs.create_file("/junit.xml", contents=xml_content)

        results, summary = parse_junit_xml(Path("/junit.xml"))

        assert len(results) == 1
        assert results[0].test_name == "tests/unit/test_main.py::test_error"
        assert results[0].status == "error"
        assert results[0].message == "ImportError: No module named 'missing'"
        assert results[0].traceback is not None
        assert "ImportError" in results[0].traceback

        assert summary.total == 1
        assert summary.passed == 0
        assert summary.failed == 0
        assert summary.errors == 1
        assert summary.skipped == 0

    def test_parses_skipped_test(self, fs: FakeFilesystem) -> None:
        """Should parse a skipped test."""
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" errors="0" failures="0" skipped="1" time="0.001">
    <testcase classname="tests.unit.test_main" name="test_skip" time="0.001">
        <skipped message="Skipped: test not ready"/>
    </testcase>
</testsuite>
"""
        fs.create_file("/junit.xml", contents=xml_content)

        results, summary = parse_junit_xml(Path("/junit.xml"))

        assert len(results) == 1
        assert results[0].test_name == "tests/unit/test_main.py::test_skip"
        assert results[0].status == "skipped"
        assert results[0].message == "Skipped: test not ready"
        assert results[0].traceback is None

        assert summary.total == 1
        assert summary.passed == 0
        assert summary.failed == 0
        assert summary.errors == 0
        assert summary.skipped == 1

    def test_parses_multiple_tests(self, fs: FakeFilesystem) -> None:
        """Should parse multiple tests with mixed results."""
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="4" errors="1" failures="1" skipped="1" time="1.0">
    <testcase classname="tests.unit.test_main" name="test_pass" time="0.1"/>
    <testcase classname="tests.unit.test_main" name="test_fail" time="0.2">
        <failure message="Failed">Traceback...</failure>
    </testcase>
    <testcase classname="tests.unit.test_main" name="test_error" time="0.3">
        <error message="Error">Traceback...</error>
    </testcase>
    <testcase classname="tests.unit.test_main" name="test_skip" time="0.001">
        <skipped message="Skipped"/>
    </testcase>
</testsuite>
"""
        fs.create_file("/junit.xml", contents=xml_content)

        results, summary = parse_junit_xml(Path("/junit.xml"))

        assert len(results) == 4
        assert summary.total == 4
        assert summary.passed == 1
        assert summary.failed == 1
        assert summary.errors == 1
        assert summary.skipped == 1

        # Verify each test
        assert results[0].status == "passed"
        assert results[1].status == "failed"
        assert results[2].status == "error"
        assert results[3].status == "skipped"

    def test_parses_testsuites_root(self, fs: FakeFilesystem) -> None:
        """Should handle <testsuites> root element with multiple suites."""
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuites>
    <testsuite name="unit" tests="2" errors="0" failures="0" skipped="0" time="0.2">
        <testcase classname="tests.unit.test_a" name="test_one" time="0.1"/>
        <testcase classname="tests.unit.test_a" name="test_two" time="0.1"/>
    </testsuite>
    <testsuite name="integration" tests="1" errors="0" failures="0" skipped="0" time="0.3">
        <testcase classname="tests.integration.test_b" name="test_three" time="0.3"/>
    </testsuite>
</testsuites>
"""
        fs.create_file("/junit.xml", contents=xml_content)

        results, summary = parse_junit_xml(Path("/junit.xml"))

        assert len(results) == 3
        assert summary.total == 3
        assert summary.passed == 3

    def test_handles_missing_file(self) -> None:
        """Should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError, match="JUnit XML file not found"):
            parse_junit_xml(Path("/nonexistent.xml"))

    def test_handles_malformed_xml(self, fs: FakeFilesystem) -> None:
        """Should raise ParseError for malformed XML."""
        import xml.etree.ElementTree as ET

        fs.create_file("/bad.xml", contents="<not valid xml")

        with pytest.raises(ET.ParseError):
            parse_junit_xml(Path("/bad.xml"))

    def test_handles_unexpected_root_element(self, fs: FakeFilesystem) -> None:
        """Should raise ValueError for unexpected root element."""
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<unexpected>
    <testcase name="test" time="0.1"/>
</unexpected>
"""
        fs.create_file("/bad.xml", contents=xml_content)

        with pytest.raises(ValueError, match="Unexpected root element"):
            parse_junit_xml(Path("/bad.xml"))

    def test_handles_missing_classname(self, fs: FakeFilesystem) -> None:
        """Should handle testcase without classname attribute."""
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" errors="0" failures="0" skipped="0" time="0.1">
    <testcase name="test_without_class" time="0.1"/>
</testsuite>
"""
        fs.create_file("/junit.xml", contents=xml_content)

        results, _summary = parse_junit_xml(Path("/junit.xml"))

        assert len(results) == 1
        assert results[0].test_name == "test_without_class"
        assert results[0].classname == ""

    def test_handles_invalid_time(self, fs: FakeFilesystem) -> None:
        """Should handle invalid time attribute gracefully."""
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" errors="0" failures="0" skipped="0" time="invalid">
    <testcase classname="tests.test" name="test_one" time="not_a_number"/>
</testsuite>
"""
        fs.create_file("/junit.xml", contents=xml_content)

        results, _summary = parse_junit_xml(Path("/junit.xml"))

        assert len(results) == 1
        assert results[0].duration == 0.0  # Default to 0.0 on parse error

    def test_handles_empty_failure_text(self, fs: FakeFilesystem) -> None:
        """Should handle failure element with no text content."""
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" tests="1" errors="0" failures="1" skipped="0" time="0.1">
    <testcase classname="tests.test" name="test_fail" time="0.1">
        <failure message="Test failed"/>
    </testcase>
</testsuite>
"""
        fs.create_file("/junit.xml", contents=xml_content)

        results, _summary = parse_junit_xml(Path("/junit.xml"))

        assert len(results) == 1
        assert results[0].status == "failed"
        assert results[0].message == "Test failed"
        assert results[0].traceback == ""

    def test_real_world_pytest_format(self, fs: FakeFilesystem) -> None:
        """Should parse real pytest-generated junit XML format."""
        xml_content = """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="pytest" errors="0" failures="1" skipped="0" tests="3" time="1.234">
    <testcase classname="tests.unit.test_example" name="test_addition" time="0.001"/>
    <testcase classname="tests.unit.test_example" name="test_subtraction" time="0.002">
        <failure message="assert 2 == 3">def test_subtraction():
&gt;       assert 2 == 3
E       assert 2 == 3

tests/unit/test_example.py:10: AssertionError</failure>
    </testcase>
    <testcase classname="tests.unit.test_example" name="test_multiplication" time="0.001"/>
</testsuite>
"""
        fs.create_file("/junit.xml", contents=xml_content)

        results, summary = parse_junit_xml(Path("/junit.xml"))

        assert len(results) == 3
        assert summary.total == 3
        assert summary.passed == 2
        assert summary.failed == 1

        # Check the failed test
        failed_test = next(r for r in results if r.status == "failed")
        assert failed_test.test_name == "tests/unit/test_example.py::test_subtraction"
        assert failed_test.message is not None
        assert "assert 2 == 3" in failed_test.message
        assert failed_test.traceback is not None
        assert "AssertionError" in failed_test.traceback


class TestTestResult:
    """Tests for TestResult dataclass."""

    def test_creates_test_result(self) -> None:
        """Should create test result with all fields."""
        result = TestResult(
            test_name="tests/unit/test_main.py::test_example",
            status="passed",
            duration=0.123,
            message=None,
            traceback=None,
            classname="tests.unit.test_main",
        )

        assert result.test_name == "tests/unit/test_main.py::test_example"
        assert result.status == "passed"
        assert result.duration == 0.123
        assert result.message is None
        assert result.traceback is None
        assert result.classname == "tests.unit.test_main"

    def test_creates_failed_result(self) -> None:
        """Should create failed test result with message and traceback."""
        result = TestResult(
            test_name="tests/unit/test_main.py::test_fail",
            status="failed",
            duration=0.456,
            message="AssertionError",
            traceback="Traceback...",
            classname="tests.unit.test_main",
        )

        assert result.status == "failed"
        assert result.message == "AssertionError"
        assert result.traceback == "Traceback..."


class TestTestSummary:
    """Tests for TestSummary dataclass."""

    def test_creates_summary(self) -> None:
        """Should create test summary with all fields."""
        summary = TestSummary(
            total=100,
            passed=85,
            failed=10,
            errors=3,
            skipped=2,
        )

        assert summary.total == 100
        assert summary.passed == 85
        assert summary.failed == 10
        assert summary.errors == 3
        assert summary.skipped == 2

    def test_calculates_totals_correctly(self) -> None:
        """Total should equal sum of passed, failed, errors, and skipped."""
        summary = TestSummary(
            total=20,
            passed=15,
            failed=3,
            errors=1,
            skipped=1,
        )

        assert summary.passed + summary.failed + summary.errors + summary.skipped == summary.total
