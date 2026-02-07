"""Tests for the edit-in-place CLI integration.

Covers Plan 6: CLI Integration.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from spec_manager.cli import cmd_scan_source


def _make_args(**kwargs: object) -> object:
    """Create a simple namespace to mimic argparse output."""

    class _NS:
        pass

    ns = _NS()
    for k, v in kwargs.items():
        setattr(ns, k, v)
    return ns


class TestCmdScanSourceText:
    def test_single_file_text(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        source = textwrap.dedent("""\
            # validate payment
            def process():
                # apply discount
                return 1

            def stub():
                pass
        """)
        fpath = tmp_path / "module.py"
        fpath.write_text(source)

        args = _make_args(path=str(fpath), exclude=None, format="text", output=None)
        result = cmd_scan_source(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "# Gap Report" in captured.out
        assert "validate payment" in captured.out
        assert "apply discount" in captured.out

    def test_directory_text(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "a.py").write_text("# gap A\ndef f(): return 1\n")
        (tmp_path / "b.py").write_text("def g(): return 2\n")

        args = _make_args(path=str(tmp_path), exclude=None, format="text", output=None)
        result = cmd_scan_source(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "# Gap Report" in captured.out
        assert "Files analyzed:" in captured.out


class TestCmdScanSourceJson:
    def test_single_file_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        source = textwrap.dedent("""\
            def f():
                # compute result
                return 1
        """)
        fpath = tmp_path / "mod.py"
        fpath.write_text(source)

        args = _make_args(path=str(fpath), exclude=None, format="json", output=None)
        result = cmd_scan_source(args)

        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "files" in data
        assert "total_gaps" in data
        assert "total_functions" in data
        assert "is_complete" in data
        assert data["total_gaps"] == 1
        assert data["total_functions"] == 1

    def test_directory_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "a.py").write_text("def f(): return 1\n")
        (tmp_path / "b.py").write_text("# gap\ndef g(): pass\n")

        args = _make_args(path=str(tmp_path), exclude=None, format="json", output=None)
        result = cmd_scan_source(args)

        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["is_complete"] is False


class TestCmdScanSourceOutput:
    def test_output_to_file(self, tmp_path: Path) -> None:
        source = "def f():\n    return 1\n"
        fpath = tmp_path / "mod.py"
        fpath.write_text(source)

        out_path = tmp_path / "report.md"
        args = _make_args(path=str(fpath), exclude=None, format="text", output=str(out_path))
        result = cmd_scan_source(args)

        assert result == 0
        assert out_path.exists()
        content = out_path.read_text()
        assert "# Gap Report" in content


class TestCmdScanSourceErrors:
    def test_nonexistent_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _make_args(
            path="/nonexistent/path.py", exclude=None, format="text", output=None
        )
        result = cmd_scan_source(args)
        assert result == 1
        captured = capsys.readouterr()
        assert "Path not found" in captured.out

    def test_syntax_error_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fpath = tmp_path / "bad.py"
        fpath.write_text("def f(:\n  pass\n")

        args = _make_args(path=str(fpath), exclude=None, format="text", output=None)
        result = cmd_scan_source(args)
        assert result == 1
        captured = capsys.readouterr()
        assert "Syntax error" in captured.out


class TestCmdScanSourceExclude:
    def test_exclude_patterns(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "main.py").write_text("# gap\ndef f(): return 1\n")
        (tmp_path / "test_main.py").write_text("# test gap\ndef test_f(): pass\n")

        args = _make_args(
            path=str(tmp_path), exclude=["**/test_*"], format="json", output=None
        )
        result = cmd_scan_source(args)

        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        file_names = [Path(f).name for f in data["files"]]
        assert "main.py" in file_names
        assert "test_main.py" not in file_names
