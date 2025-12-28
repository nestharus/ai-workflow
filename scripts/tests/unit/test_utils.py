from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.utils import (
    StdoutCaptureError,
    build_concat_parser,
    iter_directory_files,
    parse_concat_args,
    run_command_with_tee,
    utc_timestamp,
    write_concatenated_files,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestRunCommandWithTee:
    def test_successful_command(self, fs: FakeFilesystem) -> None:
        """Should capture output and return exit code 0."""
        # pyfakefs doesn't intercept subprocess, so we need to mock it
        output_path = Path("/fake/output.txt")
        fs.create_dir("/fake")

        mock_stdout = MagicMock()
        mock_stdout.__iter__ = MagicMock(return_value=iter(["line1\n", "line2\n"]))

        mock_process = MagicMock()
        mock_process.stdout = mock_stdout
        mock_process.wait.return_value = 0

        with patch("subprocess.Popen", return_value=mock_process), patch("sys.stdout.write"):
            result = run_command_with_tee(["echo", "test"], output_path)

        assert result == 0

    def test_failed_command(self, fs: FakeFilesystem) -> None:
        """Should return non-zero exit code on failure."""
        output_path = Path("/fake/output.txt")
        fs.create_dir("/fake")

        mock_stdout = MagicMock()
        mock_stdout.__iter__ = MagicMock(return_value=iter([]))

        mock_process = MagicMock()
        mock_process.stdout = mock_stdout
        mock_process.wait.return_value = 1

        with patch("subprocess.Popen", return_value=mock_process):
            result = run_command_with_tee(["false"], output_path)

        assert result == 1

    def test_stdout_capture_error(self, fs: FakeFilesystem) -> None:
        """Should raise StdoutCaptureError when stdout is None."""
        output_path = Path("/fake/output.txt")
        fs.create_dir("/fake")

        mock_process = MagicMock()
        mock_process.stdout = None

        with (
            patch("subprocess.Popen", return_value=mock_process),
            pytest.raises(StdoutCaptureError),
        ):
            run_command_with_tee(["echo", "test"], output_path)

        mock_process.kill.assert_called_once()
