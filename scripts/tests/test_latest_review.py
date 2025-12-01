"""Tests for scripts.latest_review module."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from scripts.latest_review import (
    REVIEW_SUFFIXES,
    ReviewDirectoryNotFoundError,
    ReviewFileNotFoundError,
    find_latest,
    main,
    parse_args,
)

if TYPE_CHECKING:
    from pyfakefs.fake_filesystem import FakeFilesystem


class TestReviewSuffixes:
    """Tests for REVIEW_SUFFIXES constant."""

    def test_contains_coderabbit(self) -> None:
        """Should contain coderabbit suffix."""
        assert "coderabbit" in REVIEW_SUFFIXES
        assert REVIEW_SUFFIXES["coderabbit"] == ".review.coderabbit"

    def test_contains_sonar(self) -> None:
        """Should contain sonar suffix."""
        assert "sonar" in REVIEW_SUFFIXES
        assert REVIEW_SUFFIXES["sonar"] == ".review.sonar"


class TestReviewDirectoryNotFoundError:
    """Tests for ReviewDirectoryNotFoundError exception."""

    def test_message_includes_directory(self) -> None:
        """Should include directory path in message."""
        error = ReviewDirectoryNotFoundError(Path("/some/path"))
        assert "/some/path" in str(error)
        assert "not found" in str(error)


class TestReviewFileNotFoundError:
    """Tests for ReviewFileNotFoundError exception."""

    def test_message_includes_suffix_and_directory(self) -> None:
        """Should include suffix and directory in message."""
        error = ReviewFileNotFoundError(".review.coderabbit", Path("/some/path"))
        assert ".review.coderabbit" in str(error)
        assert "/some/path" in str(error)


class TestFindLatest:
    """Tests for find_latest function."""

    def test_finds_latest_coderabbit(self, fs: FakeFilesystem) -> None:
        """Should find the newest coderabbit review file."""
        fs.create_dir("/review")
        fs.create_file("/review/20240101T120000Z.review.coderabbit", contents="old")
        fs.create_file("/review/20240102T120000Z.review.coderabbit", contents="new")

        result = find_latest("coderabbit", Path("/review"))

        assert result.name == "20240102T120000Z.review.coderabbit"

    def test_finds_latest_sonar(self, fs: FakeFilesystem) -> None:
        """Should find the newest sonar review file."""
        fs.create_dir("/review")
        fs.create_file("/review/20240101T120000Z.review.sonar", contents="old")
        fs.create_file("/review/20240102T120000Z.review.sonar", contents="new")

        result = find_latest("sonar", Path("/review"))

        assert result.name == "20240102T120000Z.review.sonar"

    def test_raises_when_directory_missing(self, fs: FakeFilesystem) -> None:
        """Should raise ReviewDirectoryNotFoundError when directory doesn't exist."""
        with pytest.raises(ReviewDirectoryNotFoundError):
            find_latest("coderabbit", Path("/nonexistent"))

    def test_raises_when_no_files_found(self, fs: FakeFilesystem) -> None:
        """Should raise ReviewFileNotFoundError when no matching files exist."""
        fs.create_dir("/review")

        with pytest.raises(ReviewFileNotFoundError):
            find_latest("coderabbit", Path("/review"))

    def test_ignores_other_file_types(self, fs: FakeFilesystem) -> None:
        """Should ignore files with different suffixes."""
        fs.create_dir("/review")
        fs.create_file("/review/20240101T120000Z.review.sonar", contents="sonar")
        fs.create_file("/review/20240102T120000Z.review.coderabbit", contents="coderabbit")

        result = find_latest("coderabbit", Path("/review"))

        assert result.name == "20240102T120000Z.review.coderabbit"


class TestParseArgs:
    """Tests for parse_args function."""

    def test_requires_type_argument(self) -> None:
        """Should require --type argument."""
        with pytest.raises(SystemExit):
            parse_args([])

    def test_parses_coderabbit_type(self) -> None:
        """Should parse coderabbit type."""
        args = parse_args(["--type", "coderabbit"])
        assert args.type == "coderabbit"

    def test_parses_sonar_type(self) -> None:
        """Should parse sonar type."""
        args = parse_args(["--type", "sonar"])
        assert args.type == "sonar"

    def test_rejects_invalid_type(self) -> None:
        """Should reject invalid type."""
        with pytest.raises(SystemExit):
            parse_args(["--type", "invalid"])

    def test_default_directory(self) -> None:
        """Should default to .review directory."""
        args = parse_args(["--type", "coderabbit"])
        assert args.directory == ".review"

    def test_custom_directory(self) -> None:
        """Should accept custom directory."""
        args = parse_args(["--type", "coderabbit", "--dir", "/custom/path"])
        assert args.directory == "/custom/path"


class TestMain:
    """Tests for main function."""

    def test_returns_zero_on_success(self, fs: FakeFilesystem, capsys: pytest.CaptureFixture) -> None:
        """Should return 0 and print path on success."""
        fs.create_dir(".review")
        fs.create_file(".review/20240101T120000Z.review.coderabbit", contents="content")

        result = main(["--type", "coderabbit"])

        assert result == 0
        captured = capsys.readouterr()
        assert "20240101T120000Z.review.coderabbit" in captured.out

    def test_returns_one_when_directory_missing(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when directory doesn't exist."""
        result = main(["--type", "coderabbit"])

        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.out

    def test_returns_one_when_no_files(
        self, fs: FakeFilesystem, capsys: pytest.CaptureFixture
    ) -> None:
        """Should return 1 when no matching files exist."""
        fs.create_dir(".review")

        result = main(["--type", "coderabbit"])

        assert result == 1
        captured = capsys.readouterr()
        assert "No files" in captured.out
