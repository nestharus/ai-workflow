"""Tests for planning.code_parser module."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from spec_manager.planning.code_parser import (
    _classify_comment,
    detect_stubs_from_source,
    extract_function_calls,
    find_insertion_points,
    parse_file,
    parse_source,
)
from spec_manager.planning.models import CommentKind

# --- Fixtures ---

SAMPLE_CODE = textwrap.dedent("""\
    import os
    import sys

    # Top-level annotation
    GLOBAL_VAR = 42


    class MyClass:
        \"\"\"A sample class.\"\"\"

        def method_one(self, x: int) -> int:
            \"\"\"Compute something.\"\"\"
            # validate input range
            if x < 0:
                raise ValueError("negative")
            # compute the result
            result = x * 2
            return result

        @staticmethod
        def static_helper(data: list) -> list:
            # sort and filter data
            filtered = [d for d in data if d > 0]
            return sorted(filtered)


    def top_level_function(a: str, b: str) -> str:
        \"\"\"Concatenate strings.\"\"\"
        # check inputs are not empty
        if not a or not b:
            return ""
        return a + b


    def stub_function():
        pass


    def stub_with_docstring():
        \"\"\"This is a stub.\"\"\"
        raise NotImplementedError


    def stub_with_ellipsis():
        ...
""")


class TestClassifyComment:
    """Tests for comment classification heuristic."""

    def test_plan_verb_first_word(self) -> None:
        assert _classify_comment("validate input parameters") == CommentKind.PLAN

    def test_plan_verb_compute(self) -> None:
        assert _classify_comment("compute the result hash") == CommentKind.PLAN

    def test_plan_verb_check(self) -> None:
        assert _classify_comment("check inputs are not empty") == CommentKind.PLAN

    def test_plan_verb_sort(self) -> None:
        assert _classify_comment("sort and filter data") == CommentKind.PLAN

    def test_reverse_marker(self) -> None:
        assert _classify_comment("[reverse-translated] validate payment") == CommentKind.REVERSE

    def test_reverse_marker_prefix(self) -> None:
        assert _classify_comment("Reverse-translated: handle error") == CommentKind.REVERSE

    def test_annotation_todo(self) -> None:
        assert _classify_comment("TODO: fix this later") == CommentKind.ANNOTATION

    def test_annotation_note(self) -> None:
        assert _classify_comment("NOTE: important consideration") == CommentKind.ANNOTATION

    def test_annotation_simple(self) -> None:
        assert _classify_comment("Top-level annotation") == CommentKind.ANNOTATION


class TestParseSource:
    """Tests for parse_source function."""

    def test_parse_functions(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        func_names = [f.name for f in code_file.functions]
        assert "method_one" in func_names
        assert "static_helper" in func_names
        assert "top_level_function" in func_names
        assert "stub_function" in func_names

    def test_parse_classes(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        assert "MyClass" in code_file.classes

    def test_parse_imports(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        assert "os" in code_file.imports
        assert "sys" in code_file.imports

    def test_function_parameters(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        method = next(f for f in code_file.functions if f.name == "method_one")
        assert "self" in method.parameters
        assert "x" in method.parameters

    def test_function_return_annotation(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        method = next(f for f in code_file.functions if f.name == "method_one")
        assert method.return_annotation == "int"

    def test_function_docstring(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        method = next(f for f in code_file.functions if f.name == "method_one")
        assert method.docstring == "Compute something."

    def test_function_calls_extracted(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        method = next(f for f in code_file.functions if f.name == "method_one")
        assert "ValueError" in method.calls

    def test_function_class_assignment(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        method = next(f for f in code_file.functions if f.name == "method_one")
        assert method.class_name == "MyClass"

    def test_top_level_function_no_class(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        func = next(f for f in code_file.functions if f.name == "top_level_function")
        assert func.class_name is None

    def test_decorators(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        helper = next(f for f in code_file.functions if f.name == "static_helper")
        assert "staticmethod" in helper.decorators

    def test_function_comments(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        method = next(f for f in code_file.functions if f.name == "method_one")
        comment_texts = [c.text for c in method.comments]
        assert "validate input range" in comment_texts
        assert "compute the result" in comment_texts

    def test_top_level_comments(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        top_texts = [c.text for c in code_file.top_level_comments]
        assert "Top-level annotation" in top_texts

    def test_comment_kind_assigned(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        method = next(f for f in code_file.functions if f.name == "method_one")
        plan_comments = [c for c in method.comments if c.kind == CommentKind.PLAN]
        assert len(plan_comments) >= 2

    def test_function_line_range(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        method = next(f for f in code_file.functions if f.name == "method_one")
        assert method.start_line > 0
        assert method.end_line >= method.start_line

    def test_empty_source(self) -> None:
        code_file = parse_source("", "/test/empty.py")
        assert code_file.functions == []
        assert code_file.top_level_comments == []
        assert code_file.imports == []
        assert code_file.classes == []


class TestParseFile:
    """Tests for parse_file function (reads from disk)."""

    def test_parse_real_file(self, tmp_path: Path) -> None:
        code = textwrap.dedent("""\
            def hello(name: str) -> str:
                # greet the user
                return f"Hello, {name}!"
        """)
        py_file = tmp_path / "hello.py"
        py_file.write_text(code, encoding="utf-8")

        code_file = parse_file(str(py_file))
        assert len(code_file.functions) == 1
        assert code_file.functions[0].name == "hello"

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            parse_file("/nonexistent/file.py")


class TestFindInsertionPoints:
    """Tests for find_insertion_points function."""

    def test_finds_insertion_points(self, tmp_path: Path) -> None:
        code = textwrap.dedent("""\
            def process(data):
                \"\"\"Process data.\"\"\"
                x = validate(data)
                y = transform(x)
                return y
        """)
        py_file = tmp_path / "process.py"
        py_file.write_text(code, encoding="utf-8")

        code_file = parse_file(str(py_file))
        points = find_insertion_points(code_file, "process")
        assert len(points) >= 2  # At least between statements

    def test_function_not_found(self, tmp_path: Path) -> None:
        code = "def f(): pass\n"
        py_file = tmp_path / "test.py"
        py_file.write_text(code, encoding="utf-8")

        code_file = parse_file(str(py_file))
        with pytest.raises(ValueError, match="not found"):
            find_insertion_points(code_file, "nonexistent")

    def test_insertion_points_have_context(self, tmp_path: Path) -> None:
        code = textwrap.dedent("""\
            def compute(a, b):
                x = a + b
                y = x * 2
                return y
        """)
        py_file = tmp_path / "compute.py"
        py_file.write_text(code, encoding="utf-8")

        code_file = parse_file(str(py_file))
        points = find_insertion_points(code_file, "compute")
        for point in points:
            assert point.file_path == str(py_file)
            assert point.function_name == "compute"
            assert point.indent_level >= 0
            assert point.rationale != ""


class TestExtractFunctionCalls:
    """Tests for extract_function_calls function."""

    def test_deduplicated(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        helper = next(f for f in code_file.functions if f.name == "static_helper")
        calls = extract_function_calls(helper)
        # Should be deduplicated
        assert len(calls) == len(set(calls))


class TestDetectStubs:
    """Tests for detect_stubs_from_source function."""

    def test_detect_pass_stub(self) -> None:
        stubs = detect_stubs_from_source(SAMPLE_CODE, "/test/sample.py")
        stub_names = [s.name for s in stubs]
        assert "stub_function" in stub_names

    def test_detect_not_implemented_stub(self) -> None:
        stubs = detect_stubs_from_source(SAMPLE_CODE, "/test/sample.py")
        stub_names = [s.name for s in stubs]
        assert "stub_with_docstring" in stub_names

    def test_detect_ellipsis_stub(self) -> None:
        stubs = detect_stubs_from_source(SAMPLE_CODE, "/test/sample.py")
        stub_names = [s.name for s in stubs]
        assert "stub_with_ellipsis" in stub_names

    def test_non_stubs_excluded(self) -> None:
        stubs = detect_stubs_from_source(SAMPLE_CODE, "/test/sample.py")
        stub_names = [s.name for s in stubs]
        assert "method_one" not in stub_names
        assert "top_level_function" not in stub_names
        assert "static_helper" not in stub_names
