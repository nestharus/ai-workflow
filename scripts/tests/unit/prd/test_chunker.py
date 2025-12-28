import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.prd.chunker import _get_line_number_at_offset, chunk_file, main

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestMainExceptionHandling:
    def test_unexpected_exception_emits_structured_error(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should emit structured JSON error to stderr on unexpected exceptions."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content")

        # Mock chunk_file to raise an unexpected exception
        with (
            patch(
                "scripts.prd.chunker.chunk_file",
                side_effect=RuntimeError("Simulated unexpected error"),
            ),
            patch(
                "sys.argv",
                ["chunker", str(input_file), "--output-dir", str(output_dir), "--mode", "headers"],
            ),
        ):
            exit_code = main()

        assert exit_code == 1

        # Check stderr for structured error output
        captured = capsys.readouterr()
        stderr_lines = captured.err.strip().split("\n")

        # The last line should be a JSON object with type and message
        last_line = stderr_lines[-1]
        error_info = json.loads(last_line)

        assert error_info["type"] == "RuntimeError"
        assert error_info["message"] == "Simulated unexpected error"

    def test_structured_error_contains_exception_type_and_message(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should include both exception type name and message in structured error."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content")

        # Mock chunk_file to raise a custom exception type
        class CustomChunkerError(Exception):
            pass

        with (
            patch(
                "scripts.prd.chunker.chunk_file",
                side_effect=CustomChunkerError("Custom error message"),
            ),
            patch(
                "sys.argv",
                ["chunker", str(input_file), "--output-dir", str(output_dir), "--mode", "headers"],
            ),
        ):
            exit_code = main()

        assert exit_code == 1

        captured = capsys.readouterr()
        stderr_lines = captured.err.strip().split("\n")
        last_line = stderr_lines[-1]
        error_info = json.loads(last_line)

        assert error_info["type"] == "CustomChunkerError"
        assert error_info["message"] == "Custom error message"

    def test_traceback_not_printed_by_default(
        self,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should NOT print traceback by default for unexpected exceptions."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content")

        # Ensure no debug environment variable is set
        monkeypatch.delenv("CHUNKER_DEBUG", raising=False)

        with (
            patch(
                "scripts.prd.chunker.chunk_file",
                side_effect=RuntimeError("Simulated unexpected error"),
            ),
            patch(
                "sys.argv",
                ["chunker", str(input_file), "--output-dir", str(output_dir), "--mode", "headers"],
            ),
        ):
            exit_code = main()

        assert exit_code == 1

        captured = capsys.readouterr()
        # Should have JSON error but NO traceback
        assert "Traceback" not in captured.err
        assert '"type": "RuntimeError"' in captured.err
        assert '"message": "Simulated unexpected error"' in captured.err

    def test_traceback_printed_with_verbose_flag(
        self,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should print traceback when --verbose flag is provided."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content")

        # Ensure no debug environment variable is set
        monkeypatch.delenv("CHUNKER_DEBUG", raising=False)

        with (
            patch(
                "scripts.prd.chunker.chunk_file",
                side_effect=RuntimeError("Simulated unexpected error"),
            ),
            patch(
                "sys.argv",
                [
                    "chunker",
                    str(input_file),
                    "--output-dir",
                    str(output_dir),
                    "--mode",
                    "headers",
                    "--verbose",
                ],
            ),
        ):
            exit_code = main()

        assert exit_code == 1

        captured = capsys.readouterr()
        # Should have BOTH JSON error AND traceback
        assert "Traceback" in captured.err
        assert '"type": "RuntimeError"' in captured.err
        assert '"message": "Simulated unexpected error"' in captured.err

    @pytest.mark.parametrize("debug_value", ["1", "true", "yes", "TRUE", "Yes"])
    def test_traceback_printed_with_chunker_debug_env_var(
        self,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        debug_value: str,
    ) -> None:
        """Should print traceback when CHUNKER_DEBUG environment variable is set."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content")

        # Set the debug environment variable
        monkeypatch.setenv("CHUNKER_DEBUG", debug_value)

        with (
            patch(
                "scripts.prd.chunker.chunk_file",
                side_effect=RuntimeError("Simulated unexpected error"),
            ),
            patch(
                "sys.argv",
                ["chunker", str(input_file), "--output-dir", str(output_dir), "--mode", "headers"],
            ),
        ):
            exit_code = main()

        assert exit_code == 1

        captured = capsys.readouterr()
        # Should have BOTH JSON error AND traceback
        assert "Traceback" in captured.err
        assert '"type": "RuntimeError"' in captured.err

    def test_traceback_not_printed_with_invalid_debug_env_value(
        self,
        fs: FakeFilesystem,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Should NOT print traceback when CHUNKER_DEBUG has invalid value."""
        input_file = Path("/test/input.md")
        output_dir = Path("/test/output")
        fs.create_file(str(input_file), contents="# Test content")

        # Set the debug environment variable to an invalid value
        monkeypatch.setenv("CHUNKER_DEBUG", "false")

        with (
            patch(
                "scripts.prd.chunker.chunk_file",
                side_effect=RuntimeError("Simulated unexpected error"),
            ),
            patch(
                "sys.argv",
                ["chunker", str(input_file), "--output-dir", str(output_dir), "--mode", "headers"],
            ),
        ):
            exit_code = main()

        assert exit_code == 1

        captured = capsys.readouterr()
        # Should have JSON error but NO traceback
        assert "Traceback" not in captured.err
        assert '"type": "RuntimeError"' in captured.err
