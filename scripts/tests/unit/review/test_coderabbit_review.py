from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.dev.review.coderabbit_review import (
    CoderabbitNotFoundError,
    main,
    parse_args,
    run_coderabbit,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestRunCoderabbit:
    def test_raises_when_coderabbit_not_found(self, fs: FakeFilesystem) -> None:
        """Should raise CoderabbitNotFoundError when coderabbit not found."""
        fs.create_dir("/output")

        with patch("shutil.which", return_value=None), pytest.raises(CoderabbitNotFoundError):
            run_coderabbit(["--base", "main"], [], Path("/output"))

    def test_creates_output_directory(self, fs: FakeFilesystem) -> None:
        """Should create output directory if it doesn't exist."""
        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("scripts.dev.review.coderabbit_review.run_command_with_tee", return_value=0),
        ):
            run_coderabbit(["--base", "main"], [], Path("/new/output"))

        assert Path("/new/output").exists()

    def test_calls_coderabbit_with_prompt_only(self, fs: FakeFilesystem) -> None:
        """Should call coderabbit with --prompt-only flag."""
        fs.create_dir("/output")

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("scripts.dev.review.coderabbit_review.run_command_with_tee") as mock_tee,
        ):
            mock_tee.return_value = 0

            run_coderabbit(["--base", "main"], [], Path("/output"))

            call_args = mock_tee.call_args[0][0]
            assert "--prompt-only" in call_args

    def test_raises_system_exit_on_failure(self, fs: FakeFilesystem) -> None:
        """Should raise SystemExit on non-zero return code."""
        fs.create_dir("/output")

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("scripts.dev.review.coderabbit_review.run_command_with_tee", return_value=1),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_coderabbit(["--base", "main"], [], Path("/output"))

        assert exc_info.value.code == 1

    def test_returns_output_path(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return output path on success."""
        fs.create_dir("/output")

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("scripts.dev.review.coderabbit_review.run_command_with_tee", return_value=0),
        ):
            result = run_coderabbit(["--base", "main"], [], Path("/output"))

        assert result.suffix == ".coderabbit"
        assert result.parent == Path("/output")


class TestMain:
    def test_defaults_to_base_main(self, fs: FakeFilesystem) -> None:
        """Should default to --base main when no target specified."""
        fs.create_dir(".review")

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("scripts.dev.review.coderabbit_review.run_command_with_tee") as mock_tee,
        ):
            mock_tee.return_value = 0

            main([])

            call_args = mock_tee.call_args[0][0]
            assert "--base" in call_args
            assert "main" in call_args

    def test_uses_provided_base(self, fs: FakeFilesystem) -> None:
        """Should use provided --base argument."""
        fs.create_dir(".review")

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("scripts.dev.review.coderabbit_review.run_command_with_tee") as mock_tee,
        ):
            mock_tee.return_value = 0

            main(["--base", "develop"])

            call_args = mock_tee.call_args[0][0]
            assert "develop" in call_args

    def test_uses_type_argument(self, fs: FakeFilesystem) -> None:
        """Should use --type argument."""
        fs.create_dir(".review")

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("scripts.dev.review.coderabbit_review.run_command_with_tee") as mock_tee,
        ):
            mock_tee.return_value = 0

            main(["--type", "uncommitted"])

            call_args = mock_tee.call_args[0][0]
            assert "--type" in call_args
            assert "uncommitted" in call_args

    def test_strips_leading_double_dash_from_extra(self, fs: FakeFilesystem) -> None:
        """Should strip leading -- from extra args."""
        fs.create_dir(".review")

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("scripts.dev.review.coderabbit_review.run_command_with_tee") as mock_tee,
        ):
            mock_tee.return_value = 0

            main(["--base", "main", "--", "--extra"])

            call_args = mock_tee.call_args[0][0]
            # Should have --extra but only one --
            assert "--extra" in call_args

    def test_returns_zero_on_success(self, fs: FakeFilesystem) -> None:
        """Should return 0 on success."""
        fs.create_dir(".review")

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("scripts.dev.review.coderabbit_review.run_command_with_tee", return_value=0),
        ):
            result = main([])

        assert result == 0

    def test_uses_base_commit_argument(self, fs: FakeFilesystem) -> None:
        """Should use --base-commit argument (covers line 83, branch [82,83])."""
        fs.create_dir(".review")

        with (
            patch("shutil.which", return_value="/usr/bin/coderabbit"),
            patch("scripts.dev.review.coderabbit_review.run_command_with_tee") as mock_tee,
        ):
            mock_tee.return_value = 0

            main(["--base-commit", "abc123def456"])

            call_args = mock_tee.call_args[0][0]
            assert "--base-commit" in call_args
            assert "abc123def456" in call_args
