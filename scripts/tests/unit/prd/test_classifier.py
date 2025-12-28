from pathlib import Path

import pytest

from scripts.prd.classifier import (
    ClassificationResult,
    InputType,
    _count_indexed_ids,
    _count_prose_indicators,
    _count_section_headers,
    classify_by_heuristics,
    classify_input,
    main,
)


class TestMainCLI:
    def test_main_with_valid_prd_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print classification result for a valid PRD file."""
        prd_content = """## Resources

RES-1: Database schema
RES-2: API endpoint
RES-3: User model

## Goals

GOAL-1: Implement feature
GOAL-2: Add tests

## Invariants

INV-1: Data consistency
"""
        prd_file = tmp_path / "test_prd.md"
        prd_file.write_text(prd_content, encoding="utf-8")

        monkeypatch.setattr("sys.argv", ["classifier", str(prd_file)])

        exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "PRD"
        assert captured.err == ""

    def test_main_with_valid_prose_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should print PROSE for a file with prose content."""
        prose_content = "I think we should add a new feature. Can you please implement this?"
        prose_file = tmp_path / "request.txt"
        prose_file.write_text(prose_content, encoding="utf-8")

        monkeypatch.setattr("sys.argv", ["classifier", str(prose_file)])

        exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == "PROSE"
        assert captured.err == ""

    def test_main_with_nonexistent_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should exit non-zero and print error for nonexistent file."""
        nonexistent_path = tmp_path / "nonexistent_file.md"

        monkeypatch.setattr("sys.argv", ["classifier", str(nonexistent_path)])

        exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Error: File not found" in captured.err
        assert "nonexistent_file.md" in captured.err

    def test_main_with_no_arguments(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should exit non-zero and print usage for missing arguments."""
        monkeypatch.setattr("sys.argv", ["classifier"])

        exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Usage:" in captured.err

    def test_main_with_too_many_arguments(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should exit non-zero and print usage for too many arguments."""
        monkeypatch.setattr("sys.argv", ["classifier", "file1.md", "file2.md"])

        exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Usage:" in captured.err

    def test_main_with_unreadable_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Should exit non-zero and print error when file read fails."""
        binary_file = tmp_path / "binary.bin"
        binary_file.write_bytes(b"\x80\x81\x82\x83\xff\xfe")

        monkeypatch.setattr("sys.argv", ["classifier", str(binary_file)])

        exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Error:" in captured.err
