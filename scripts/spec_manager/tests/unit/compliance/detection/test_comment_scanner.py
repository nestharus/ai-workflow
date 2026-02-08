"""Tests for comment scanner."""

from __future__ import annotations

import textwrap
from pathlib import Path

from spec_manager.compliance.detection.comment_scanner import (
    CommentGap,
    comments_to_gap_evidence,
    scan_comments,
)


class TestScanComments:
    """Test comment scanning with various comment types."""

    def test_spec_comments_detected(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def calculate_tax(amount):
                # Apply progressive tax brackets
                # Handle edge case for zero amount
                return amount * 0.2
        """)
        filepath = tmp_path / "tax.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 2
        assert gaps[0].text == "Apply progressive tax brackets"
        assert gaps[0].line == 2
        assert gaps[0].enclosing_function == "calculate_tax"
        assert not gaps[0].is_inline
        assert gaps[1].text == "Handle edge case for zero amount"

    def test_type_ignore_excluded(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            x: int = "hello"  # type: ignore
            y = foo()  # type: ignore[assignment]
        """)
        filepath = tmp_path / "types.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 0

    def test_noqa_excluded(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            import os  # noqa: F401
            import sys  # noqa
        """)
        filepath = tmp_path / "imports.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 0

    def test_pragma_excluded(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            if TYPE_CHECKING:  # pragma: no cover
                pass
        """)
        filepath = tmp_path / "pragma.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 0

    def test_fmt_excluded(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            # fmt: off
            x = 1
            # fmt: on
        """)
        filepath = tmp_path / "fmt.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 0

    def test_pylint_excluded(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            x = None  # pylint: disable=invalid-name
        """)
        filepath = tmp_path / "pylint.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 0

    def test_ruff_mypy_pyright_excluded(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            x = 1  # ruff: noqa
            y = 2  # mypy: ignore
            z = 3  # pyright: ignore
        """)
        filepath = tmp_path / "tools.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 0

    def test_shebang_excluded(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            #!/usr/bin/env python3
            # -*- coding: utf-8 -*-
            def main():
                pass
        """)
        filepath = tmp_path / "script.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 0

    def test_docstrings_not_comments(self, tmp_path: Path) -> None:
        source = textwrap.dedent('''\
            def foo():
                """This is a docstring, not a comment."""
                return 42
        ''')
        filepath = tmp_path / "docs.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 0

    def test_inline_comment_detected(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def foo():
                x = 42  # magic number for alignment
                return x
        """)
        filepath = tmp_path / "inline.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 1
        assert gaps[0].is_inline is True
        assert gaps[0].text == "magic number for alignment"

    def test_enclosing_function_for_nested(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def outer():
                # outer comment
                def inner():
                    # inner comment
                    pass
                return inner
        """)
        filepath = tmp_path / "nested.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 2
        assert gaps[0].enclosing_function == "outer"
        assert gaps[1].enclosing_function == "outer.inner"

    def test_module_level_comment(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            # Module-level initialization logic
            X = 42
        """)
        filepath = tmp_path / "module.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 1
        assert gaps[0].enclosing_function is None

    def test_class_method_enclosing(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            class Calculator:
                def add(self, a, b):
                    # Validate inputs
                    return a + b
        """)
        filepath = tmp_path / "cls.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 1
        assert gaps[0].enclosing_function == "Calculator.add"

    def test_empty_comments_excluded(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            #
            #
            def foo():
                # real comment
                pass
        """)
        filepath = tmp_path / "empty.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        assert len(gaps) == 1
        assert gaps[0].text == "real comment"

    def test_mixed_file(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            #!/usr/bin/env python3
            # -*- coding: utf-8 -*-

            # Initialize the tax engine

            def calculate(amount):
                \"\"\"Calculate the tax.\"\"\"
                # Apply bracket logic
                x = amount  # type: ignore
                return x  # noqa: E501

            class Processor:
                def process(self):
                    # Run the pipeline
                    pass  # pragma: no cover
        """)
        filepath = tmp_path / "mixed.py"
        filepath.write_text(source, encoding="utf-8")

        gaps = scan_comments(filepath)
        texts = [g.text for g in gaps]
        assert "Initialize the tax engine" in texts
        assert "Apply bracket logic" in texts
        assert "Run the pipeline" in texts
        assert len(gaps) == 3


class TestCommentsToGapEvidence:
    """Test conversion of CommentGap to GapEvidence."""

    def test_basic_conversion(self) -> None:
        comments = [
            CommentGap(
                file_path="/tmp/test.py",
                line=10,
                col_int=4,
                text="Apply tax brackets",
                enclosing_function="calculate_tax",
                is_inline=False,
            ),
        ]

        evidence = comments_to_gap_evidence(comments)
        assert len(evidence) == 1

        e = evidence[0]
        assert e.invariant_family == "executable_comment"
        assert e.detector == "comment_scanner"
        assert e.location == "/tmp/test.py:10"
        assert e.description == "Apply tax brackets"
        assert e.details["enclosing_function"] == "calculate_tax"
        assert e.details["is_inline"] is False
        assert e.confidence == 1.0

    def test_inline_comment_evidence(self) -> None:
        comments = [
            CommentGap(
                file_path="/tmp/test.py",
                line=5,
                col_int=20,
                text="magic number",
                enclosing_function="foo",
                is_inline=True,
            ),
        ]

        evidence = comments_to_gap_evidence(comments)
        assert evidence[0].details["is_inline"] is True

    def test_empty_input(self) -> None:
        evidence = comments_to_gap_evidence([])
        assert evidence == []

    def test_evidence_serializes(self) -> None:
        comments = [
            CommentGap(
                file_path="/tmp/test.py",
                line=10,
                col_int=4,
                text="test",
                enclosing_function=None,
                is_inline=False,
            ),
        ]
        evidence = comments_to_gap_evidence(comments)
        d = evidence[0].to_dict()
        assert d["invariant_family"] == "executable_comment"
        assert d["detector"] == "comment_scanner"
