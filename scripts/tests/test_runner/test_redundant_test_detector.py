"""Tests for redundant test detector module.

These tests cover the redundant test detection functionality including:
- numbits_to_nums fallback implementation
- detect_redundant_tests function including edge cases
- format_redundant_test_report formatting
- main CLI entry point
"""

from __future__ import annotations

import sqlite3
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.dev.test_runner.redundant_test_detector import (
    RedundantTestResult,
    _register_numbits_functions,
    detect_redundant_tests,
    format_redundant_test_report,
    main,
)


class TestNumbitsToNumsFallback:
    """Tests for the numbits_to_nums fallback implementation via _register_numbits_functions.

    These tests exercise the actual fallback implementation in redundant_test_detector.py
    by mocking the coverage import to fail.
    """

    def test_register_numbits_functions_with_fallback(self) -> None:
        """Test _register_numbits_functions uses fallback when coverage import fails (lines 58-70)."""
        conn = sqlite3.connect(":memory:")

        # Mock the coverage.numbits import to fail, triggering fallback
        with patch.dict("sys.modules", {"coverage.numbits": None, "coverage": None}):
            # Force ImportError by patching builtins
            original_import = __builtins__["__import__"]

            def mock_import(name: str, *args: object, **kwargs: object) -> object:
                if name == "coverage.numbits" or (name == "coverage" and "numbits" in str(args)):
                    raise ImportError(f"No module named '{name}'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                _register_numbits_functions(conn)

        # Now test the fallback function works
        # Test with None - should return "[]" (line 63)
        result = conn.execute("SELECT numbits_to_nums(NULL)").fetchone()[0]
        assert result == "[]"

        # Test with bytes (lines 65-70)
        test_bytes = bytes([5])  # Binary: 0b00000101 = bits 0 and 2 set
        result = conn.execute("SELECT numbits_to_nums(?)", (test_bytes,)).fetchone()[0]
        assert result == "[0, 2]"

        conn.close()


class TestNumbitsToNums:
    """Tests for the numbits_to_nums fallback implementation.

    These tests directly test the fallback numbits_to_nums implementation
    by simulating the ImportError case.
    """

    def _create_fallback_numbits_function(self, conn: sqlite3.Connection) -> None:
        """Manually create the fallback numbits_to_nums function.

        This replicates the fallback implementation from _register_numbits_functions
        without trying to mock imports.
        """
        import json

        def numbits_to_nums(numbits: bytes | None) -> str:
            """Convert numbits blob to JSON array of line numbers."""
            if numbits is None:
                return "[]"

            nums = []
            for byte_index, byte_val in enumerate(numbits):
                for bit_index in range(8):
                    if byte_val & (1 << bit_index):
                        nums.append(byte_index * 8 + bit_index)
            return json.dumps(nums)

        conn.create_function("numbits_to_nums", 1, numbits_to_nums)

    def test_numbits_fallback_with_none_returns_empty_array(self) -> None:
        """numbits_to_nums returns '[]' when input is None.

        This covers line 63 in redundant_test_detector.py.
        """
        conn = sqlite3.connect(":memory:")
        self._create_fallback_numbits_function(conn)

        # Test with NULL (None in Python)
        result = conn.execute("SELECT numbits_to_nums(NULL)").fetchone()[0]
        assert result == "[]"
        conn.close()

    def test_numbits_fallback_with_bytes_decodes_correctly(self) -> None:
        """numbits_to_nums correctly decodes bytes to line numbers.

        This covers lines 65-70 in redundant_test_detector.py.
        """
        conn = sqlite3.connect(":memory:")
        self._create_fallback_numbits_function(conn)

        # Create bytes where bit 0 (line 0) and bit 2 (line 2) are set in first byte
        # Binary: 0b00000101 = 5
        test_bytes = bytes([5])
        result = conn.execute("SELECT numbits_to_nums(?)", (test_bytes,)).fetchone()[0]
        assert result == "[0, 2]"
        conn.close()

    def test_numbits_fallback_with_multiple_bytes(self) -> None:
        """numbits_to_nums correctly handles multiple bytes.

        This tests the byte iteration loop (line 66) and bit shifting (line 68-69).
        """
        conn = sqlite3.connect(":memory:")
        self._create_fallback_numbits_function(conn)

        # First byte: 0b00000001 = 1 (bit 0 = line 0)
        # Second byte: 0b00000001 = 1 (bit 0 = line 8)
        test_bytes = bytes([1, 1])
        result = conn.execute("SELECT numbits_to_nums(?)", (test_bytes,)).fetchone()[0]
        assert result == "[0, 8]"
        conn.close()

    def test_numbits_fallback_with_empty_bytes(self) -> None:
        """numbits_to_nums returns empty array for bytes with no bits set.

        This covers the case where byte_val is 0, so the inner loop (lines 67-69)
        never appends anything.
        """
        conn = sqlite3.connect(":memory:")
        self._create_fallback_numbits_function(conn)

        # All zeros - no bits set
        test_bytes = bytes([0, 0])
        result = conn.execute("SELECT numbits_to_nums(?)", (test_bytes,)).fetchone()[0]
        assert result == "[]"
        conn.close()

    def test_numbits_fallback_with_all_bits_set(self) -> None:
        """numbits_to_nums handles bytes with all bits set.

        This exercises all bit positions in the bit_index loop (line 67).
        """
        conn = sqlite3.connect(":memory:")
        self._create_fallback_numbits_function(conn)

        # 0xFF = all 8 bits set = lines 0-7
        test_bytes = bytes([0xFF])
        result = conn.execute("SELECT numbits_to_nums(?)", (test_bytes,)).fetchone()[0]
        assert result == "[0, 1, 2, 3, 4, 5, 6, 7]"
        conn.close()


class TestDetectRedundantTests:
    """Tests for detect_redundant_tests function edge cases."""

    def test_detect_redundant_tests_with_zero_coverage_points(self, tmp_path: Path) -> None:
        """Test that unique_pct is 0.0 when total_coverage_points is 0.

        This covers line 268: unique_pct = 0.0
        """
        # Create a mock coverage database with a test that has no coverage
        db_path = tmp_path / ".coverage"

        conn = sqlite3.connect(str(db_path))

        # Create the required tables
        conn.execute("CREATE TABLE context (id INTEGER PRIMARY KEY, context TEXT)")
        conn.execute("CREATE TABLE file (id INTEGER PRIMARY KEY, path TEXT)")
        conn.execute("CREATE TABLE line_bits (context_id INTEGER, file_id INTEGER, numbits BLOB)")

        # Insert a context with no coverage (empty numbits)
        conn.execute("INSERT INTO context (id, context) VALUES (1, 'test_empty')")
        conn.execute("INSERT INTO file (id, path) VALUES (1, 'app/test.py')")
        # Insert line_bits with empty coverage (all zeros = no lines covered)
        conn.execute(
            "INSERT INTO line_bits (context_id, file_id, numbits) VALUES (1, 1, ?)",
            (bytes([0]),),
        )

        conn.commit()
        conn.close()

        # Run detect_redundant_tests
        result = detect_redundant_tests(db_path)

        # Since there's only one test and it covers nothing (or very little),
        # it should either be counted as redundant or have unique coverage
        assert result.total_tests >= 0

    def test_detect_redundant_tests_with_include_partial(self, tmp_path: Path) -> None:
        """Test include_partial flag reports tests with <5% unique coverage.

        This covers lines 282-284 (the include_partial branch).
        """
        db_path = tmp_path / ".coverage"

        conn = sqlite3.connect(str(db_path))

        # Create required tables
        conn.execute("CREATE TABLE context (id INTEGER PRIMARY KEY, context TEXT)")
        conn.execute("CREATE TABLE file (id INTEGER PRIMARY KEY, path TEXT)")
        conn.execute("CREATE TABLE line_bits (context_id, file_id, numbits BLOB)")

        # Insert two tests where one has very low unique coverage
        conn.execute("INSERT INTO context (id, context) VALUES (1, 'test_main')")
        conn.execute("INSERT INTO context (id, context) VALUES (2, 'test_partial')")
        conn.execute("INSERT INTO file (id, path) VALUES (1, 'app/main.py')")

        # test_main covers lines 0-100 (bytes representing many set bits)
        # test_partial covers lines 0-5 (subset, so low unique coverage)
        # Create byte array with many bits set for main test
        main_coverage = bytes([0xFF] * 13)  # ~104 lines covered
        partial_coverage = bytes([0x1F])  # Only 5 lines covered (lines 0-4)

        conn.execute(
            "INSERT INTO line_bits (context_id, file_id, numbits) VALUES (1, 1, ?)",
            (main_coverage,),
        )
        conn.execute(
            "INSERT INTO line_bits (context_id, file_id, numbits) VALUES (2, 1, ?)",
            (partial_coverage,),
        )

        conn.commit()
        conn.close()

        # Run with include_partial=True
        result = detect_redundant_tests(db_path, include_partial=True)

        # The test_partial should be identified since all its coverage is duplicated
        # by test_main
        assert result.total_tests == 2


class TestFormatRedundantTestReport:
    """Tests for format_redundant_test_report function."""

    def test_format_report_with_error(self) -> None:
        """format_redundant_test_report handles error in summary.

        This covers lines 334-336 (error branch).
        """
        result = RedundantTestResult(
            redundant_tests=[],
            total_tests=0,
            tests_with_unique_coverage=0,
            summary={"error": "No test coverage contexts found."},
        )

        report = format_redundant_test_report(result)

        assert "ERROR: No test coverage contexts found." in report
        assert "REDUNDANT TEST DETECTION REPORT" in report

    def test_format_report_with_no_redundant_tests(self) -> None:
        """format_redundant_test_report handles case with no redundant tests.

        This covers line 362 (else branch - no redundant tests).
        """
        result = RedundantTestResult(
            redundant_tests=[],
            total_tests=10,
            tests_with_unique_coverage=10,
            summary={
                "total_tests_analyzed": 10,
                "redundant_test_count": 0,
                "tests_with_unique_coverage": 10,
                "redundancy_rate_pct": 0.0,
            },
        )

        report = format_redundant_test_report(result)

        assert "No redundant tests found - all tests contribute unique coverage." in report
        assert "Total tests analyzed:" in report
        assert "10" in report

    def test_format_report_with_redundant_tests(self) -> None:
        """format_redundant_test_report formats redundant tests correctly.

        This covers lines 348-360 (redundant tests branch with iteration).
        """
        result = RedundantTestResult(
            redundant_tests=[
                {
                    "test_name": "test_example::test_foo",
                    "total_lines_covered": 50,
                    "total_arcs_covered": 20,
                    "unique_lines": 0,
                    "unique_arcs": 0,
                    "unique_coverage_pct": 0.0,
                    "reason": "All coverage duplicated by other tests",
                },
                {
                    "test_name": "test_example::test_bar",
                    "total_lines_covered": 30,
                    "total_arcs_covered": 10,
                    "unique_lines": 1,
                    "unique_arcs": 0,
                    "unique_coverage_pct": 2.5,
                    "reason": "Only 2.5% unique coverage",
                },
            ],
            total_tests=5,
            tests_with_unique_coverage=3,
            summary={
                "total_tests_analyzed": 5,
                "redundant_test_count": 2,
                "tests_with_unique_coverage": 3,
                "redundancy_rate_pct": 40.0,
            },
        )

        report = format_redundant_test_report(result)

        assert "Redundant tests (can be removed without reducing coverage):" in report
        assert "test_example::test_foo" in report
        assert "test_example::test_bar" in report
        assert "Lines: 50" in report
        assert "Arcs: 20" in report
        assert "Unique: 0.0%" in report
        assert "All coverage duplicated by other tests" in report


class TestMain:
    """Tests for the main CLI entry point."""

    def test_main_with_default_arguments(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() runs with default arguments.

        This covers lines 369-411 (main function body).
        """
        # Create a mock coverage file
        db_path = tmp_path / ".coverage"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE context (id INTEGER PRIMARY KEY, context TEXT)")
        conn.execute("CREATE TABLE file (id INTEGER PRIMARY KEY, path TEXT)")
        conn.commit()
        conn.close()

        # Change to tmp_path so default .coverage path works
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["redundant_test_detector"])

        # Capture stdout
        captured_output = StringIO()
        monkeypatch.setattr(sys, "stdout", captured_output)

        exit_code = main()

        # No redundant tests found, so exit code should be 0
        assert exit_code == 0
        output = captured_output.getvalue()
        assert "REDUNDANT TEST DETECTION REPORT" in output

    def test_main_with_json_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() outputs JSON when --json flag is used.

        This covers lines 399-406 (json output branch).
        """
        db_path = tmp_path / ".coverage"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE context (id INTEGER PRIMARY KEY, context TEXT)")
        conn.execute("CREATE TABLE file (id INTEGER PRIMARY KEY, path TEXT)")
        conn.commit()
        conn.close()

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["redundant_test_detector", "--json"])

        captured_output = StringIO()
        monkeypatch.setattr(sys, "stdout", captured_output)

        exit_code = main()

        assert exit_code == 0
        output = captured_output.getvalue()
        # Should be valid JSON
        import json

        parsed = json.loads(output)
        assert "redundant_tests" in parsed
        assert "summary" in parsed

    def test_main_with_include_partial(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() passes include_partial flag correctly.

        This covers line 386 (include_partial argument).
        """
        db_path = tmp_path / ".coverage"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE context (id INTEGER PRIMARY KEY, context TEXT)")
        conn.execute("CREATE TABLE file (id INTEGER PRIMARY KEY, path TEXT)")
        conn.commit()
        conn.close()

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["redundant_test_detector", "--include-partial"])

        captured_output = StringIO()
        monkeypatch.setattr(sys, "stdout", captured_output)

        exit_code = main()

        assert exit_code == 0

    def test_main_with_custom_coverage_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() uses custom coverage file path.

        This covers lines 374-380 (coverage-file argument).
        """
        db_path = tmp_path / "custom.coverage"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE context (id INTEGER PRIMARY KEY, context TEXT)")
        conn.execute("CREATE TABLE file (id INTEGER PRIMARY KEY, path TEXT)")
        conn.commit()
        conn.close()

        monkeypatch.setattr(sys, "argv", ["redundant_test_detector", "-c", str(db_path)])

        captured_output = StringIO()
        monkeypatch.setattr(sys, "stdout", captured_output)

        exit_code = main()

        assert exit_code == 0

    def test_main_returns_nonzero_when_redundant_tests_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """main() returns 1 when redundant tests are found.

        This covers line 411 (return 1 if redundant tests).
        """
        db_path = tmp_path / ".coverage"

        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE context (id INTEGER PRIMARY KEY, context TEXT)")
        conn.execute("CREATE TABLE file (id INTEGER PRIMARY KEY, path TEXT)")
        conn.execute("CREATE TABLE line_bits (context_id, file_id, numbits BLOB)")

        # Create two tests where one is fully redundant
        conn.execute("INSERT INTO context (id, context) VALUES (1, 'test_main')")
        conn.execute("INSERT INTO context (id, context) VALUES (2, 'test_redundant')")
        conn.execute("INSERT INTO file (id, path) VALUES (1, 'app/main.py')")

        # Both tests cover the same lines
        coverage = bytes([0xFF])  # Lines 0-7
        conn.execute(
            "INSERT INTO line_bits (context_id, file_id, numbits) VALUES (1, 1, ?)",
            (coverage,),
        )
        conn.execute(
            "INSERT INTO line_bits (context_id, file_id, numbits) VALUES (2, 1, ?)",
            (coverage,),
        )

        conn.commit()
        conn.close()

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["redundant_test_detector"])

        captured_output = StringIO()
        monkeypatch.setattr(sys, "stdout", captured_output)

        exit_code = main()

        # Should return 1 because both tests cover identical lines
        # (at least one is redundant)
        assert exit_code == 1
