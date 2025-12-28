import pytest

from scripts.dev.review.coderabbit_review import (
    CoderabbitNotFoundError,
    main,
    parse_args,
    run_coderabbit,
)


class TestCoderabbitNotFoundError:
    def test_default_message(self) -> None:
        """Should have default message."""
        error = CoderabbitNotFoundError()
        assert "coderabbit executable not found" in str(error)

    def test_custom_message(self) -> None:
        """Should accept custom message."""
        error = CoderabbitNotFoundError("Custom message")
        assert "Custom message" in str(error)


class TestParseArgs:
    def test_default_base_is_main(self) -> None:
        """Should default to --base main when no target specified."""
        args = parse_args([])
        assert args.base is None
        assert args.type is None
        assert args.base_commit is None

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

    def test_mutually_exclusive_targets(self) -> None:
        """Should reject multiple target arguments."""
        with pytest.raises(SystemExit):
            parse_args(["--base", "main", "--type", "uncommitted"])

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
        args = parse_args(["--base", "main", "--", "--extra", "arg"])
        assert args.extra_args == ["--", "--extra", "arg"]
