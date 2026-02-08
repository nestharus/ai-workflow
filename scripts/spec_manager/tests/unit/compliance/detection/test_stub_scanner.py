"""Tests for stub scanner."""

from __future__ import annotations

import textwrap
from pathlib import Path

from spec_manager.compliance.detection.stub_scanner import (
    StubFunction,
    scan_stubs,
    stubs_to_gap_evidence,
)


class TestScanStubs:
    """Test stub function detection."""

    def test_pass_stub_detected(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def placeholder():
                pass
        """)
        filepath = tmp_path / "stubs.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        assert len(stubs) == 1
        assert stubs[0].name == "placeholder"
        assert stubs[0].stub_type == "pass"
        assert stubs[0].has_docstring is False

    def test_ellipsis_stub_detected(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def placeholder():
                ...
        """)
        filepath = tmp_path / "stubs.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        assert len(stubs) == 1
        assert stubs[0].stub_type == "ellipsis"

    def test_not_implemented_stub_detected(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def placeholder():
                raise NotImplementedError("TODO")
        """)
        filepath = tmp_path / "stubs.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        assert len(stubs) == 1
        assert stubs[0].stub_type == "not_implemented"

    def test_not_implemented_no_args(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def placeholder():
                raise NotImplementedError
        """)
        filepath = tmp_path / "stubs.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        assert len(stubs) == 1
        assert stubs[0].stub_type == "not_implemented"

    def test_stub_with_docstring(self, tmp_path: Path) -> None:
        source = textwrap.dedent('''\
            def placeholder():
                """This function is not yet implemented."""
                pass
        ''')
        filepath = tmp_path / "stubs.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        assert len(stubs) == 1
        assert stubs[0].has_docstring is True
        assert stubs[0].stub_type == "pass"

    def test_real_function_not_flagged(self, tmp_path: Path) -> None:
        source = textwrap.dedent('''\
            def real_function(x, y):
                """Add two numbers."""
                return x + y
        ''')
        filepath = tmp_path / "real.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        assert len(stubs) == 0

    def test_function_with_logic_after_docstring_not_flagged(self, tmp_path: Path) -> None:
        source = textwrap.dedent('''\
            def real_function():
                """Do something."""
                x = 42
                return x
        ''')
        filepath = tmp_path / "real.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        assert len(stubs) == 0

    def test_class_method_qualified_name(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            class Calculator:
                def add(self, a, b):
                    pass

                def multiply(self, a, b):
                    return a * b
        """)
        filepath = tmp_path / "cls.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        assert len(stubs) == 1
        assert stubs[0].name == "Calculator.add"

    def test_args_captured(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def process(self, data: list[int], flag: bool = True) -> int:
                pass
        """)
        filepath = tmp_path / "args.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        assert len(stubs) == 1
        assert "self" in stubs[0].args
        assert "data" in stubs[0].args
        assert "flag" in stubs[0].args

    def test_return_annotation_captured(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def process() -> int:
                pass
        """)
        filepath = tmp_path / "ann.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        assert len(stubs) == 1
        assert stubs[0].return_annotation == "int"

    def test_no_return_annotation(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def process():
                pass
        """)
        filepath = tmp_path / "noann.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        assert len(stubs) == 1
        assert stubs[0].return_annotation is None

    def test_mixed_functions(self, tmp_path: Path) -> None:
        source = textwrap.dedent('''\
            def real():
                return 42

            def stub_pass():
                pass

            def stub_ellipsis():
                ...

            def stub_not_impl():
                raise NotImplementedError("TODO")

            def real_with_doc():
                """Documented."""
                x = 1
                return x
        ''')
        filepath = tmp_path / "mixed.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        names = {s.name for s in stubs}
        assert names == {"stub_pass", "stub_ellipsis", "stub_not_impl"}

    def test_async_function_stub(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            async def fetch_data():
                raise NotImplementedError
        """)
        filepath = tmp_path / "async_stubs.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        assert len(stubs) == 1
        assert stubs[0].name == "fetch_data"
        assert stubs[0].stub_type == "not_implemented"

    def test_nested_class(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            class Outer:
                class Inner:
                    def method(self):
                        pass
        """)
        filepath = tmp_path / "nested.py"
        filepath.write_text(source, encoding="utf-8")

        stubs = scan_stubs(filepath)
        assert len(stubs) == 1
        assert stubs[0].name == "Outer.Inner.method"


class TestStubsToGapEvidence:
    """Test conversion of StubFunction to GapEvidence."""

    def test_basic_conversion(self) -> None:
        stubs = [
            StubFunction(
                file_path="/tmp/test.py",
                line=10,
                end_line=12,
                name="Calculator.add",
                stub_type="pass",
                has_docstring=False,
                args=["self", "a", "b"],
                return_annotation="int",
            ),
        ]

        evidence = stubs_to_gap_evidence(stubs)
        assert len(evidence) == 1

        e = evidence[0]
        assert e.invariant_family == "executable_stub"
        assert e.detector == "stub_scanner"
        assert e.location == "/tmp/test.py:10-12"
        assert "Calculator.add" in e.description
        assert "(pass)" in e.description
        assert e.details["stub_type"] == "pass"
        assert e.details["args"] == ["self", "a", "b"]
        assert e.details["return_annotation"] == "int"
        assert e.confidence == 1.0

    def test_empty_input(self) -> None:
        evidence = stubs_to_gap_evidence([])
        assert evidence == []

    def test_evidence_serializes(self) -> None:
        stubs = [
            StubFunction(
                file_path="/tmp/test.py",
                line=1,
                end_line=2,
                name="foo",
                stub_type="ellipsis",
                has_docstring=True,
                args=[],
                return_annotation=None,
            ),
        ]
        evidence = stubs_to_gap_evidence(stubs)
        d = evidence[0].to_dict()
        assert d["invariant_family"] == "executable_stub"
        assert d["detector"] == "stub_scanner"
