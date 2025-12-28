from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scripts.dev.review.sonar_review import (
    SonarScriptNotFoundError,
    main,
    parse_args,
    run_sonar,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestSonarScriptNotFoundError:
    def test_includes_script_path(self) -> None:
        """Should include script path in message."""
        error = SonarScriptNotFoundError(Path("/path/to/sonar_scan.sh"))
        assert "/path/to/sonar_scan.sh" in str(error)
        assert "not found" in str(error)


class TestParseArgs:
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
    def test_raises_when_script_not_found(self, fs: FakeFilesystem) -> None:
        """Should raise SonarScriptNotFoundError when script not found."""
        fs.create_dir("/output")

        with pytest.raises(SonarScriptNotFoundError):
            run_sonar([], Path("/output"))
