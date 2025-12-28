import subprocess
from unittest.mock import patch

import pytest

from scripts.dev.setup import (
    UvNotFoundError,
    main,
    run_pre_commit_install,
)


class TestRunPreCommitInstall:
    def test_raises_when_uv_not_found(self) -> None:
        """Should raise UvNotFoundError when uv is not available."""
        with patch("shutil.which", return_value=None), pytest.raises(UvNotFoundError):
            run_pre_commit_install()

    def test_calls_uv_run_pre_commit(self) -> None:
        """Should call uv run pre-commit install."""
        with (
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.check_call") as mock_check_call,
        ):
            run_pre_commit_install()

        mock_check_call.assert_called_once_with(
            ["/usr/bin/uv", "run", "--group", "dev", "pre-commit", "install"]
        )

    def test_propagates_subprocess_error(self) -> None:
        """Should propagate CalledProcessError from subprocess."""
        with (
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.check_call") as mock_check_call,
            pytest.raises(subprocess.CalledProcessError),
        ):
            mock_check_call.side_effect = subprocess.CalledProcessError(1, ["uv"])
            run_pre_commit_install()


class TestMain:
    def test_returns_zero_on_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 0 on successful installation."""
        with patch("shutil.which", return_value="/usr/bin/uv"), patch("subprocess.check_call"):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Pre-commit hooks installed" in captured.out

    def test_returns_one_when_uv_not_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 when uv is not found."""
        with patch("shutil.which", return_value=None):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Failed to install" in captured.out

    def test_returns_returncode_on_subprocess_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return subprocess returncode on failure."""
        with (
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.check_call") as mock_check_call,
        ):
            error = subprocess.CalledProcessError(42, ["uv"])
            mock_check_call.side_effect = error
            result = main()

        assert result == 42
        captured = capsys.readouterr()
        assert "Failed to install" in captured.out

    def test_returns_one_on_generic_runtime_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 on generic RuntimeError without returncode."""
        with (
            patch("shutil.which", return_value="/usr/bin/uv"),
            patch("subprocess.check_call") as mock_check_call,
        ):
            mock_check_call.side_effect = RuntimeError("Generic error")
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "Failed to install" in captured.out
