"""Tests for scripts.sonar_review module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from scripts.sonar_review import (
    SonarScriptNotFoundError,
    main,
    parse_args,
    run_sonar,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestSonarScriptNotFoundError:
    """Tests for SonarScriptNotFoundError exception."""

    def test_includes_script_path(self) -> None:
        """Should include script path in message."""
        error = SonarScriptNotFoundError(Path("/path/to/sonar_scan.sh"))
        assert "/path/to/sonar_scan.sh" in str(error)
        assert "not found" in str(error)


class TestParseArgs:
    """Tests for parse_args function."""

    def test_default_output_dir(self) -> None:
        """Should default to .review output directory."""
        args = parse_args([])
        assert args.output_dir == ".review"

    def test_custom_output_dir(self) -> None:
        """Should accept custom output directory."""
        args = parse_args(["--output-dir", "/custom/path"])
        assert args.output_dir == "/custom/path"

    def test_captures_extra_args(self) -> None:
        """Should capture extra arguments."""
        args = parse_args(["--", "--extra", "arg"])
        assert args.extra_args == ["--", "--extra", "arg"]


class TestRunSonar:
    """Tests for run_sonar function."""

    def test_raises_when_script_not_found(self, fs: FakeFilesystem) -> None:
        """Should raise SonarScriptNotFoundError when script not found."""
        fs.create_dir("/output")

        with pytest.raises(SonarScriptNotFoundError):
            run_sonar([], Path("/output"))

    def test_creates_output_directory(self, fs: FakeFilesystem) -> None:
        """Should create output directory if it doesn't exist."""
        # Create the sonar_scan.sh script in the expected location
        scripts_dir = Path(__file__).resolve().parent.parent
        fs.create_file(str(scripts_dir / "sonar_scan.sh"), contents="#!/bin/bash\necho test")

        with patch("scripts.sonar_review.run_command_with_tee", return_value=0):
            run_sonar([], Path("/new/output"))

        assert Path("/new/output").exists()

    def test_calls_sonar_script(self, fs: FakeFilesystem) -> None:
        """Should call sonar_scan.sh script."""
        scripts_dir = Path(__file__).resolve().parent.parent
        script_path = scripts_dir / "sonar_scan.sh"
        fs.create_file(str(script_path), contents="#!/bin/bash\necho test")
        fs.create_dir("/output")

        with patch("scripts.sonar_review.run_command_with_tee") as mock_tee:
            mock_tee.return_value = 0

            run_sonar([], Path("/output"))

            call_args = mock_tee.call_args[0][0]
            assert "sonar_scan.sh" in call_args[0]

    def test_raises_system_exit_on_failure(self, fs: FakeFilesystem) -> None:
        """Should raise SystemExit on non-zero return code."""
        scripts_dir = Path(__file__).resolve().parent.parent
        fs.create_file(str(scripts_dir / "sonar_scan.sh"), contents="#!/bin/bash")
        fs.create_dir("/output")

        with patch("scripts.sonar_review.run_command_with_tee", return_value=1):
            with pytest.raises(SystemExit) as exc_info:
                run_sonar([], Path("/output"))

            assert exc_info.value.code == 1

    def test_returns_output_path(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should return output path on success."""
        scripts_dir = Path(__file__).resolve().parent.parent
        fs.create_file(str(scripts_dir / "sonar_scan.sh"), contents="#!/bin/bash")
        fs.create_dir("/output")

        with patch("scripts.sonar_review.run_command_with_tee", return_value=0):
            result = run_sonar([], Path("/output"))

        assert result.suffix == ".sonar"
        assert result.parent == Path("/output")


class TestMain:
    """Tests for main function."""

    def test_strips_leading_double_dash_from_extra(self, fs: FakeFilesystem) -> None:
        """Should strip leading -- from extra args."""
        scripts_dir = Path(__file__).resolve().parent.parent
        fs.create_file(str(scripts_dir / "sonar_scan.sh"), contents="#!/bin/bash")
        fs.create_dir(".review")

        with patch("scripts.sonar_review.run_command_with_tee") as mock_tee:
            mock_tee.return_value = 0

            main(["--", "--extra"])

            call_args = mock_tee.call_args[0][0]
            # Should have --extra but not leading --
            assert "--extra" in call_args

    def test_returns_zero_on_success(self, fs: FakeFilesystem) -> None:
        """Should return 0 on success."""
        scripts_dir = Path(__file__).resolve().parent.parent
        fs.create_file(str(scripts_dir / "sonar_scan.sh"), contents="#!/bin/bash")
        fs.create_dir(".review")

        with patch("scripts.sonar_review.run_command_with_tee", return_value=0):
            result = main([])

        assert result == 0
