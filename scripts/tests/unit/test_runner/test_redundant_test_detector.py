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


class TestMain:
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
