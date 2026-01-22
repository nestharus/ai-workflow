from unittest.mock import MagicMock, patch

import pytest

from scripts.dev.review.coderabbit_review import (
    CoderabbitNotFoundError,
    main,
    parse_args,
    run_coderabbit,
)


class TestRunCoderabbit:
    def test_raises_when_coderabbit_not_found(self) -> None:
        """Should raise CoderabbitNotFoundError when coderabbit not found."""
        with patch("shutil.which", return_value=None), pytest.raises(CoderabbitNotFoundError):
            run_coderabbit(["--base", "main"], [])

    def test_calls_coderabbit_with_prompt_only(self) -> None:
        """Should call coderabbit with --prompt-only flag."""
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = 0

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("subprocess.Popen", return_value=mock_process) as mock_popen,
        ):
            run_coderabbit(["--base", "main"], [])

            call_args = mock_popen.call_args[0][0]
            assert "--prompt-only" in call_args

    def test_returns_exit_code_from_process(self) -> None:
        """Should return exit code from coderabbit process."""
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = 0

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("subprocess.Popen", return_value=mock_process),
        ):
            result = run_coderabbit(["--base", "main"], [])

        assert result == 0

    def test_returns_nonzero_on_failure(self) -> None:
        """Should return non-zero exit code on failure."""
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = 1

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("subprocess.Popen", return_value=mock_process),
        ):
            result = run_coderabbit(["--base", "main"], [])

        assert result == 1

    def test_streams_output_to_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should stream process output to stdout."""
        mock_process = MagicMock()
        mock_process.stdout = iter(["line 1\n", "line 2\n"])
        mock_process.wait.return_value = 0

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("subprocess.Popen", return_value=mock_process),
        ):
            run_coderabbit(["--base", "main"], [])

        captured = capsys.readouterr()
        assert "line 1" in captured.out
        assert "line 2" in captured.out

    def test_returns_error_when_stdout_is_none(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Should return 1 and print error when stdout is None."""
        mock_process = MagicMock()
        mock_process.stdout = None

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("subprocess.Popen", return_value=mock_process),
        ):
            result = run_coderabbit(["--base", "main"], [])

        assert result == 1
        mock_process.kill.assert_called_once()
        captured = capsys.readouterr()
        assert "ERROR" in captured.err


class TestParseArgs:
    def test_parses_base_argument(self) -> None:
        """Should parse --base argument."""
        args = parse_args(["--base", "develop"])
        assert args.base == "develop"

    def test_parses_type_argument(self) -> None:
        """Should parse --type argument."""
        args = parse_args(["--type", "uncommitted"])
        assert args.type == "uncommitted"

    def test_parses_base_commit_argument(self) -> None:
        """Should parse --base-commit argument."""
        args = parse_args(["--base-commit", "abc123"])
        assert args.base_commit == "abc123"

    def test_captures_extra_args(self) -> None:
        """Should capture extra arguments."""
        args = parse_args(["--base", "main", "--", "--extra", "arg"])
        assert args.extra_args == ["--", "--extra", "arg"]


class TestMain:
    def test_defaults_to_base_main(self) -> None:
        """Should default to --base main when no target specified."""
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = 0

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("subprocess.Popen", return_value=mock_process) as mock_popen,
        ):
            main([])

            call_args = mock_popen.call_args[0][0]
            assert "--base" in call_args
            assert "main" in call_args

    def test_uses_provided_base(self) -> None:
        """Should use provided --base argument."""
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = 0

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("subprocess.Popen", return_value=mock_process) as mock_popen,
        ):
            main(["--base", "develop"])

            call_args = mock_popen.call_args[0][0]
            assert "develop" in call_args

    def test_uses_type_argument(self) -> None:
        """Should use --type argument."""
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = 0

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("subprocess.Popen", return_value=mock_process) as mock_popen,
        ):
            main(["--type", "uncommitted"])

            call_args = mock_popen.call_args[0][0]
            assert "--type" in call_args
            assert "uncommitted" in call_args

    def test_strips_leading_double_dash_from_extra(self) -> None:
        """Should strip leading -- from extra args."""
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = 0

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("subprocess.Popen", return_value=mock_process) as mock_popen,
        ):
            main(["--base", "main", "--", "--extra"])

            call_args = mock_popen.call_args[0][0]
            assert "--extra" in call_args

    def test_returns_zero_on_success(self) -> None:
        """Should return 0 on success."""
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = 0

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("subprocess.Popen", return_value=mock_process),
        ):
            result = main([])

        assert result == 0

    def test_uses_base_commit_argument(self) -> None:
        """Should use --base-commit argument."""
        mock_process = MagicMock()
        mock_process.stdout = iter([])
        mock_process.wait.return_value = 0

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("subprocess.Popen", return_value=mock_process) as mock_popen,
        ):
            main(["--base-commit", "abc123def456"])

            call_args = mock_popen.call_args[0][0]
            assert "--base-commit" in call_args
            assert "abc123def456" in call_args
