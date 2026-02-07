"""Tests for GapDetector: comment detection, stub detection, and branch scanning."""

from __future__ import annotations

from pathlib import Path

import pytest

from spec_manager.branches.gap_detection import GapDetector, GapItem


@pytest.fixture
def detector() -> GapDetector:
    return GapDetector()


class TestFindUnimplementedComments:
    """Tests for comment detection."""

    def test_finds_comments(self, detector: GapDetector, tmp_path: Path) -> None:
        src = tmp_path / "algo.py"
        src.write_text(
            "def process():\n"
            "    # This is a comment\n"
            "    x = 1\n"
            "    # Another comment\n"
            "    return x\n",
            encoding="utf-8",
        )
        gaps = detector.find_unimplemented_comments(src)
        assert len(gaps) == 2
        assert all(g.gap_type == "unimplemented_comment" for g in gaps)
        assert gaps[0].text == "This is a comment"

    def test_skips_empty_comments(self, detector: GapDetector, tmp_path: Path) -> None:
        src = tmp_path / "algo.py"
        src.write_text(
            "def process():\n"
            "    #\n"
            "    x = 1\n",
            encoding="utf-8",
        )
        gaps = detector.find_unimplemented_comments(src)
        assert len(gaps) == 0

    def test_no_comments(self, detector: GapDetector, tmp_path: Path) -> None:
        src = tmp_path / "algo.py"
        src.write_text("def process():\n    return 1\n", encoding="utf-8")
        gaps = detector.find_unimplemented_comments(src)
        assert len(gaps) == 0

    def test_nonexistent_file(self, detector: GapDetector, tmp_path: Path) -> None:
        gaps = detector.find_unimplemented_comments(tmp_path / "missing.py")
        assert gaps == []


class TestDetectStubs:
    """Tests for stub function detection."""

    def test_detects_pass_stub(self, detector: GapDetector, tmp_path: Path) -> None:
        src = tmp_path / "algo.py"
        src.write_text("def stub_func():\n    pass\n", encoding="utf-8")
        gaps = detector.detect_stubs(src)
        assert len(gaps) == 1
        assert gaps[0].gap_type == "stub_function"
        assert "pass" in gaps[0].text

    def test_detects_ellipsis_stub(self, detector: GapDetector, tmp_path: Path) -> None:
        src = tmp_path / "algo.py"
        src.write_text("def stub_func():\n    ...\n", encoding="utf-8")
        gaps = detector.detect_stubs(src)
        assert len(gaps) == 1
        assert "Ellipsis" in gaps[0].text

    def test_detects_not_implemented_stub(self, detector: GapDetector, tmp_path: Path) -> None:
        src = tmp_path / "algo.py"
        src.write_text(
            'def stub_func():\n    raise NotImplementedError("todo")\n',
            encoding="utf-8",
        )
        gaps = detector.detect_stubs(src)
        assert len(gaps) == 1
        assert "NotImplementedError" in gaps[0].text

    def test_detects_docstring_only_stub(self, detector: GapDetector, tmp_path: Path) -> None:
        src = tmp_path / "algo.py"
        src.write_text(
            'def stub_func():\n    """Docstring only."""\n',
            encoding="utf-8",
        )
        gaps = detector.detect_stubs(src)
        assert len(gaps) == 1
        assert "docstring only" in gaps[0].text

    def test_ignores_implemented_function(self, detector: GapDetector, tmp_path: Path) -> None:
        src = tmp_path / "algo.py"
        src.write_text("def real_func():\n    return 42\n", encoding="utf-8")
        gaps = detector.detect_stubs(src)
        assert len(gaps) == 0

    def test_syntax_error_file(self, detector: GapDetector, tmp_path: Path) -> None:
        src = tmp_path / "bad.py"
        src.write_text("def broken(:\n", encoding="utf-8")
        gaps = detector.detect_stubs(src)
        assert gaps == []


class TestDetectRuntimeErrors:
    """Tests for RuntimeError placeholder detection."""

    def test_detects_runtime_error(self, detector: GapDetector, tmp_path: Path) -> None:
        src = tmp_path / "algo.py"
        src.write_text(
            'def func():\n    raise RuntimeError("not done")\n',
            encoding="utf-8",
        )
        gaps = detector.detect_runtime_errors(src)
        assert len(gaps) == 1
        assert gaps[0].gap_type == "runtime_error"

    def test_ignores_value_error(self, detector: GapDetector, tmp_path: Path) -> None:
        src = tmp_path / "algo.py"
        src.write_text(
            'def func():\n    raise ValueError("bad")\n',
            encoding="utf-8",
        )
        gaps = detector.detect_runtime_errors(src)
        assert len(gaps) == 0


class TestScanBranch:
    """Tests for scanning an entire algorithmic branch."""

    def test_scans_multiple_files(self, detector: GapDetector, tmp_path: Path) -> None:
        # Create algorithmic branch structure
        algo_dir = tmp_path / "algorithmic"
        atoms_dir = algo_dir / "atoms"
        atoms_dir.mkdir(parents=True)

        (atoms_dir / "a1.py").write_text(
            "def a1():\n    # todo: implement\n    pass\n",
            encoding="utf-8",
        )
        (atoms_dir / "a2.py").write_text(
            "def a2():\n    return 42\n",
            encoding="utf-8",
        )

        gaps = detector.scan_branch(algo_dir)
        # a1.py has 1 comment + 1 stub
        assert len(gaps) >= 2

    def test_skips_init_files(self, detector: GapDetector, tmp_path: Path) -> None:
        algo_dir = tmp_path / "algorithmic"
        algo_dir.mkdir()
        (algo_dir / "__init__.py").write_text("# init comment\n", encoding="utf-8")
        gaps = detector.scan_branch(algo_dir)
        assert len(gaps) == 0

    def test_empty_branch(self, detector: GapDetector, tmp_path: Path) -> None:
        gaps = detector.scan_branch(tmp_path / "nonexistent")
        assert gaps == []


class TestGapItemSerialization:
    """Tests for GapItem serialization."""

    def test_roundtrip(self) -> None:
        item = GapItem(
            file="algo.py",
            line=10,
            text="todo: implement",
            gap_type="unimplemented_comment",
        )
        data = item.to_dict()
        restored = GapItem.from_dict(data)
        assert restored.file == item.file
        assert restored.line == item.line
        assert restored.text == item.text
        assert restored.gap_type == item.gap_type
