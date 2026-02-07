"""Tests for the edit-in-place engine.

Covers Plans 1-4: data structures, comment classifier, function analyzer,
and file-level orchestrator.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from spec_manager.core.edit_in_place import (
    CommentKind,
    FileTranslationState,
    FunctionInfo,
    ProjectTranslationState,
    SpecComment,
    TranslationState,
    _determine_translation_state,
    _get_docstring,
    _is_stub_body,
    analyze_file,
    analyze_functions,
    analyze_project,
    classify_comment,
    find_gaps,
    format_gap_report,
    scan_comments,
)


# =============================================================================
# Plan 1: Data Structure Tests
# =============================================================================


class TestTranslationState:
    def test_enum_values(self) -> None:
        assert TranslationState.UNRESOLVED.value == "unresolved"
        assert TranslationState.STUB.value == "stub"
        assert TranslationState.PARTIAL.value == "partial"
        assert TranslationState.IMPLEMENTED.value == "implemented"
        assert TranslationState.VERIFIED.value == "verified"


class TestCommentKind:
    def test_enum_values(self) -> None:
        assert CommentKind.SPEC.value == "spec"
        assert CommentKind.TODO.value == "todo"
        assert CommentKind.INFRASTRUCTURE.value == "infra"
        assert CommentKind.SECTION_MARKER.value == "section"


class TestSpecComment:
    def test_frozen_construction(self) -> None:
        sc = SpecComment(
            file="test.py",
            line=10,
            col_offset=0,
            text="validate payment",
            raw="# validate payment",
            kind=CommentKind.SPEC,
            enclosing_function=None,
        )
        assert sc.file == "test.py"
        assert sc.line == 10
        assert sc.kind == CommentKind.SPEC
        assert sc.enclosing_function is None

    def test_frozen_immutable(self) -> None:
        sc = SpecComment(
            file="test.py",
            line=10,
            col_offset=0,
            text="x",
            raw="# x",
            kind=CommentKind.SPEC,
            enclosing_function=None,
        )
        with pytest.raises(AttributeError):
            sc.line = 20  # type: ignore[misc]


class TestFunctionInfo:
    def test_construction(self) -> None:
        fi = FunctionInfo(
            name="foo",
            qualified_name="MyClass.foo",
            file="test.py",
            line_start=5,
            line_end=15,
            col_offset=4,
            is_async=False,
            decorators=["staticmethod"],
            args=["self", "x"],
            return_annotation="int",
            docstring="Do something.",
            body_line_count=10,
            translation_state=TranslationState.IMPLEMENTED,
            spec_comments=[],
            stub_reason=None,
        )
        assert fi.name == "foo"
        assert fi.qualified_name == "MyClass.foo"
        assert fi.translation_state == TranslationState.IMPLEMENTED


class TestFileTranslationState:
    def _make_comment(self, kind: CommentKind) -> SpecComment:
        return SpecComment(
            file="test.py",
            line=1,
            col_offset=0,
            text="x",
            raw="# x",
            kind=kind,
            enclosing_function=None,
        )

    def test_is_complete_true_when_no_gaps_no_stubs(self) -> None:
        state = FileTranslationState(
            file="test.py",
            content_hash="abc",
            functions=[],
            module_comments=[],
            all_comments=[self._make_comment(CommentKind.INFRASTRUCTURE)],
            total_spec_comments=0,
            total_functions=0,
            stub_count=0,
            partial_count=0,
            implemented_count=0,
            unresolved_count=0,
        )
        assert state.is_complete is True

    def test_is_complete_false_with_spec_comments(self) -> None:
        state = FileTranslationState(
            file="test.py",
            content_hash="abc",
            functions=[],
            module_comments=[],
            all_comments=[self._make_comment(CommentKind.SPEC)],
            total_spec_comments=1,
            total_functions=0,
            stub_count=0,
            partial_count=0,
            implemented_count=0,
            unresolved_count=0,
        )
        assert state.is_complete is False

    def test_is_complete_false_with_stubs(self) -> None:
        state = FileTranslationState(
            file="test.py",
            content_hash="abc",
            functions=[],
            module_comments=[],
            all_comments=[],
            total_spec_comments=0,
            total_functions=1,
            stub_count=1,
            partial_count=0,
            implemented_count=0,
            unresolved_count=0,
        )
        assert state.is_complete is False

    def test_completion_ratio_no_functions(self) -> None:
        state = FileTranslationState(
            file="test.py",
            content_hash="abc",
            functions=[],
            module_comments=[],
            all_comments=[],
            total_spec_comments=0,
            total_functions=0,
            stub_count=0,
            partial_count=0,
            implemented_count=0,
            unresolved_count=0,
        )
        assert state.completion_ratio == 1.0

    def test_completion_ratio_calculated(self) -> None:
        state = FileTranslationState(
            file="test.py",
            content_hash="abc",
            functions=[],
            module_comments=[],
            all_comments=[],
            total_spec_comments=0,
            total_functions=4,
            stub_count=1,
            partial_count=1,
            implemented_count=2,
            unresolved_count=0,
        )
        assert state.completion_ratio == 0.5

    def test_gaps_filtering(self) -> None:
        spec = self._make_comment(CommentKind.SPEC)
        todo = self._make_comment(CommentKind.TODO)
        infra = self._make_comment(CommentKind.INFRASTRUCTURE)
        section = self._make_comment(CommentKind.SECTION_MARKER)
        state = FileTranslationState(
            file="test.py",
            content_hash="abc",
            functions=[],
            module_comments=[],
            all_comments=[spec, todo, infra, section],
            total_spec_comments=2,
            total_functions=0,
            stub_count=0,
            partial_count=0,
            implemented_count=0,
            unresolved_count=0,
        )
        gaps = state.gaps
        assert len(gaps) == 2
        assert all(g.kind in (CommentKind.SPEC, CommentKind.TODO) for g in gaps)


class TestProjectTranslationState:
    def test_aggregation(self) -> None:
        f1 = FileTranslationState(
            file="a.py",
            content_hash="h1",
            functions=[],
            module_comments=[],
            all_comments=[],
            total_spec_comments=3,
            total_functions=5,
            stub_count=1,
            partial_count=0,
            implemented_count=4,
            unresolved_count=0,
        )
        f2 = FileTranslationState(
            file="b.py",
            content_hash="h2",
            functions=[],
            module_comments=[],
            all_comments=[],
            total_spec_comments=0,
            total_functions=2,
            stub_count=0,
            partial_count=0,
            implemented_count=2,
            unresolved_count=0,
        )
        proj = ProjectTranslationState(files={"a.py": f1, "b.py": f2})
        assert proj.total_gaps == 3
        assert proj.total_functions == 7
        assert proj.is_complete is False

    def test_is_complete_all_done(self) -> None:
        f = FileTranslationState(
            file="done.py",
            content_hash="h",
            functions=[],
            module_comments=[],
            all_comments=[],
            total_spec_comments=0,
            total_functions=1,
            stub_count=0,
            partial_count=0,
            implemented_count=1,
            unresolved_count=0,
        )
        proj = ProjectTranslationState(files={"done.py": f})
        assert proj.is_complete is True


# =============================================================================
# Plan 2: Comment Classifier Tests
# =============================================================================


class TestClassifyComment:
    def test_spec_comment(self) -> None:
        assert classify_comment("# validate payment against fraud rules") == CommentKind.SPEC

    def test_type_ignore(self) -> None:
        assert classify_comment("# type: ignore[attr-defined]") == CommentKind.INFRASTRUCTURE

    def test_noqa(self) -> None:
        assert classify_comment("# noqa: E501") == CommentKind.INFRASTRUCTURE

    def test_pragma_no_cover(self) -> None:
        assert classify_comment("# pragma: no cover") == CommentKind.INFRASTRUCTURE

    def test_shebang(self) -> None:
        assert classify_comment("#!/usr/bin/env python") == CommentKind.INFRASTRUCTURE

    def test_encoding_declaration(self) -> None:
        assert classify_comment("# -*- coding: utf-8 -*-") == CommentKind.INFRASTRUCTURE

    def test_pylint_disable(self) -> None:
        assert classify_comment("# pylint: disable=C0301") == CommentKind.INFRASTRUCTURE

    def test_fmt_off(self) -> None:
        assert classify_comment("# fmt: off") == CommentKind.INFRASTRUCTURE

    def test_isort_skip(self) -> None:
        assert classify_comment("# isort: skip") == CommentKind.INFRASTRUCTURE

    def test_mypy_directive(self) -> None:
        assert classify_comment("# mypy: ignore-errors") == CommentKind.INFRASTRUCTURE

    def test_ruff_directive(self) -> None:
        assert classify_comment("# ruff: noqa") == CommentKind.INFRASTRUCTURE

    def test_section_marker_dashes(self) -> None:
        assert classify_comment("# ---- atoms ----") == CommentKind.SECTION_MARKER

    def test_section_marker_equals(self) -> None:
        assert classify_comment("# ==== Section ====") == CommentKind.SECTION_MARKER

    def test_todo(self) -> None:
        assert classify_comment("# TODO: implement this") == CommentKind.TODO

    def test_fixme(self) -> None:
        assert classify_comment("# FIXME: broken logic") == CommentKind.TODO

    def test_hack(self) -> None:
        assert classify_comment("# HACK: temporary workaround") == CommentKind.TODO

    def test_xxx(self) -> None:
        assert classify_comment("# XXX: needs attention") == CommentKind.TODO

    def test_workaround(self) -> None:
        assert classify_comment("# WORKAROUND: issue #123") == CommentKind.TODO

    def test_todo_case_insensitive(self) -> None:
        assert classify_comment("# todo: do this") == CommentKind.TODO


class TestScanComments:
    def test_simple_file(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            # validate payment
            # type: ignore
            # ---- section ----
            # TODO: fix this
            x = 1
        """)
        fpath = tmp_path / "simple.py"
        fpath.write_text(source)

        comments = scan_comments(str(fpath))
        assert len(comments) == 4

        kinds = [c.kind for c in comments]
        assert kinds == [
            CommentKind.SPEC,
            CommentKind.INFRASTRUCTURE,
            CommentKind.SECTION_MARKER,
            CommentKind.TODO,
        ]

    def test_enclosing_function(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            # module level comment
            def foo():
                # inside foo
                pass

            def bar():
                # inside bar
                x = 1
        """)
        fpath = tmp_path / "enclosed.py"
        fpath.write_text(source)

        comments = scan_comments(str(fpath))
        assert len(comments) == 3
        assert comments[0].enclosing_function is None
        assert comments[1].enclosing_function == "foo"
        assert comments[2].enclosing_function == "bar"

    def test_nested_class_method(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            class Outer:
                class Inner:
                    def method(self):
                        # inside nested method
                        pass
        """)
        fpath = tmp_path / "nested.py"
        fpath.write_text(source)

        comments = scan_comments(str(fpath))
        assert len(comments) == 1
        assert comments[0].enclosing_function == "Outer.Inner.method"

    def test_empty_file(self, tmp_path: Path) -> None:
        fpath = tmp_path / "empty.py"
        fpath.write_text("")

        comments = scan_comments(str(fpath))
        assert comments == []


# =============================================================================
# Plan 3: Function Analyzer Tests
# =============================================================================


class TestIsStubBody:
    def test_pass(self) -> None:
        import ast as _ast

        tree = _ast.parse("def f(): pass")
        func = tree.body[0]
        assert isinstance(func, _ast.FunctionDef)
        is_stub, reason = _is_stub_body(func.body)
        assert is_stub is True
        assert reason == "pass"

    def test_ellipsis(self) -> None:
        import ast as _ast

        tree = _ast.parse("def f(): ...")
        func = tree.body[0]
        assert isinstance(func, _ast.FunctionDef)
        is_stub, reason = _is_stub_body(func.body)
        assert is_stub is True
        assert reason == "ellipsis"

    def test_not_implemented(self) -> None:
        import ast as _ast

        tree = _ast.parse("def f(): raise NotImplementedError()")
        func = tree.body[0]
        assert isinstance(func, _ast.FunctionDef)
        is_stub, reason = _is_stub_body(func.body)
        assert is_stub is True
        assert reason == "not_implemented"

    def test_not_implemented_bare(self) -> None:
        import ast as _ast

        tree = _ast.parse("def f(): raise NotImplementedError")
        func = tree.body[0]
        assert isinstance(func, _ast.FunctionDef)
        is_stub, reason = _is_stub_body(func.body)
        assert is_stub is True
        assert reason == "not_implemented"

    def test_docstring_plus_pass(self) -> None:
        import ast as _ast

        src = textwrap.dedent('''\
            def f():
                """Docstring."""
                pass
        ''')
        tree = _ast.parse(src)
        func = tree.body[0]
        assert isinstance(func, _ast.FunctionDef)
        is_stub, reason = _is_stub_body(func.body)
        assert is_stub is True
        assert reason == "pass"

    def test_real_code(self) -> None:
        import ast as _ast

        src = textwrap.dedent("""\
            def f():
                x = 1
                return x + 1
        """)
        tree = _ast.parse(src)
        func = tree.body[0]
        assert isinstance(func, _ast.FunctionDef)
        is_stub, reason = _is_stub_body(func.body)
        assert is_stub is False
        assert reason is None


class TestGetDocstring:
    def test_has_docstring(self) -> None:
        import ast as _ast

        src = textwrap.dedent('''\
            def f():
                """My docstring."""
                pass
        ''')
        tree = _ast.parse(src)
        func = tree.body[0]
        assert isinstance(func, _ast.FunctionDef)
        assert _get_docstring(func.body) == "My docstring."

    def test_no_docstring(self) -> None:
        import ast as _ast

        tree = _ast.parse("def f(): pass")
        func = tree.body[0]
        assert isinstance(func, _ast.FunctionDef)
        assert _get_docstring(func.body) is None


class TestDetermineTranslationState:
    def _make_spec_comment(self) -> SpecComment:
        return SpecComment(
            file="t.py",
            line=1,
            col_offset=0,
            text="spec",
            raw="# spec",
            kind=CommentKind.SPEC,
            enclosing_function=None,
        )

    def _make_infra_comment(self) -> SpecComment:
        return SpecComment(
            file="t.py",
            line=1,
            col_offset=0,
            text="type: ignore",
            raw="# type: ignore",
            kind=CommentKind.INFRASTRUCTURE,
            enclosing_function=None,
        )

    def test_unresolved(self) -> None:
        import ast as _ast

        node = _ast.parse("def f(): pass").body[0]
        assert isinstance(node, _ast.FunctionDef)
        state = _determine_translation_state(node, [self._make_spec_comment()], is_stub=True)
        assert state == TranslationState.UNRESOLVED

    def test_stub(self) -> None:
        import ast as _ast

        node = _ast.parse("def f(): pass").body[0]
        assert isinstance(node, _ast.FunctionDef)
        state = _determine_translation_state(node, [], is_stub=True)
        assert state == TranslationState.STUB

    def test_partial(self) -> None:
        import ast as _ast

        node = _ast.parse("def f(): pass").body[0]
        assert isinstance(node, _ast.FunctionDef)
        state = _determine_translation_state(node, [self._make_spec_comment()], is_stub=False)
        assert state == TranslationState.PARTIAL

    def test_implemented(self) -> None:
        import ast as _ast

        node = _ast.parse("def f(): pass").body[0]
        assert isinstance(node, _ast.FunctionDef)
        state = _determine_translation_state(node, [], is_stub=False)
        assert state == TranslationState.IMPLEMENTED

    def test_infra_comments_dont_count_as_gaps(self) -> None:
        """Infrastructure comments should not make a function PARTIAL or UNRESOLVED."""
        import ast as _ast

        node = _ast.parse("def f(): pass").body[0]
        assert isinstance(node, _ast.FunctionDef)
        state = _determine_translation_state(node, [self._make_infra_comment()], is_stub=False)
        assert state == TranslationState.IMPLEMENTED


class TestAnalyzeFunctions:
    def test_mixed_file(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def implemented():
                x = 1
                return x + 1

            def stub_func():
                pass

            def partial_func():
                # apply discount logic
                x = 1
                return x

            def unresolved_func():
                # compute tax rate
                pass
        """)
        fpath = tmp_path / "mixed.py"
        fpath.write_text(source)

        comments = scan_comments(str(fpath))
        functions = analyze_functions(str(fpath), comments)

        assert len(functions) == 4

        by_name = {f.name: f for f in functions}
        assert by_name["implemented"].translation_state == TranslationState.IMPLEMENTED
        assert by_name["stub_func"].translation_state == TranslationState.STUB
        assert by_name["stub_func"].stub_reason == "pass"
        assert by_name["partial_func"].translation_state == TranslationState.PARTIAL
        assert by_name["unresolved_func"].translation_state == TranslationState.UNRESOLVED

    def test_class_methods(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            class Service:
                def process(self):
                    return True

                def validate(self):
                    pass
        """)
        fpath = tmp_path / "cls.py"
        fpath.write_text(source)

        comments = scan_comments(str(fpath))
        functions = analyze_functions(str(fpath), comments)

        assert len(functions) == 2
        by_name = {f.name: f for f in functions}
        assert by_name["process"].qualified_name == "Service.process"
        assert by_name["validate"].qualified_name == "Service.validate"
        assert by_name["validate"].translation_state == TranslationState.STUB

    def test_async_functions(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            async def fetch_data():
                return await something()
        """)
        fpath = tmp_path / "async_mod.py"
        fpath.write_text(source)

        comments = scan_comments(str(fpath))
        functions = analyze_functions(str(fpath), comments)

        assert len(functions) == 1
        assert functions[0].is_async is True
        assert functions[0].translation_state == TranslationState.IMPLEMENTED

    def test_nested_functions(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def outer():
                def inner():
                    pass
                return inner()
        """)
        fpath = tmp_path / "nested.py"
        fpath.write_text(source)

        comments = scan_comments(str(fpath))
        functions = analyze_functions(str(fpath), comments)

        names = {f.name for f in functions}
        assert "outer" in names
        assert "inner" in names

        by_name = {f.name: f for f in functions}
        assert by_name["inner"].qualified_name == "outer.inner"
        assert by_name["inner"].translation_state == TranslationState.STUB

    def test_decorators(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            import functools

            @staticmethod
            def foo():
                return 1

            @functools.lru_cache(maxsize=128)
            def bar():
                return 2
        """)
        fpath = tmp_path / "deco.py"
        fpath.write_text(source)

        comments = scan_comments(str(fpath))
        functions = analyze_functions(str(fpath), comments)

        by_name = {f.name: f for f in functions}
        assert "staticmethod" in by_name["foo"].decorators
        assert "functools.lru_cache" in by_name["bar"].decorators


# =============================================================================
# Plan 4: File-Level Orchestrator Tests
# =============================================================================


class TestAnalyzeFile:
    def test_simple_analysis(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            # module level spec comment
            def implemented():
                return 42

            def stub():
                pass
        """)
        fpath = tmp_path / "simple.py"
        fpath.write_text(source)

        state = analyze_file(str(fpath))
        assert state.file == str(fpath)
        assert state.total_functions == 2
        assert state.implemented_count == 1
        assert state.stub_count == 1
        assert state.total_spec_comments == 1
        assert len(state.module_comments) == 1

    def test_all_implemented(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def foo():
                return 1

            def bar():
                return 2
        """)
        fpath = tmp_path / "complete.py"
        fpath.write_text(source)

        state = analyze_file(str(fpath))
        assert state.is_complete is True
        assert state.total_spec_comments == 0
        assert state.stub_count == 0

    def test_all_stubs(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            def a():
                pass

            def b():
                ...

            def c():
                raise NotImplementedError()
        """)
        fpath = tmp_path / "stubs.py"
        fpath.write_text(source)

        state = analyze_file(str(fpath))
        assert state.stub_count == 3
        assert state.is_complete is False

    def test_mixed_states(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            # module gap
            def impl():
                return 1

            def stub_f():
                pass

            def partial_f():
                # finish this logic
                x = compute()
                return x

            def unresolved_f():
                # compute results
                ...
        """)
        fpath = tmp_path / "mixed.py"
        fpath.write_text(source)

        state = analyze_file(str(fpath))
        assert state.implemented_count == 1
        assert state.stub_count == 1
        assert state.partial_count == 1
        assert state.unresolved_count == 1
        assert state.total_spec_comments == 3  # module gap + finish this + compute results

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            analyze_file("/nonexistent/path/to/file.py")

    def test_syntax_error(self, tmp_path: Path) -> None:
        fpath = tmp_path / "bad.py"
        fpath.write_text("def foo(:\n  pass\n")

        with pytest.raises(SyntaxError):
            analyze_file(str(fpath))

    def test_content_hash_deterministic(self, tmp_path: Path) -> None:
        source = "x = 1\n"
        fpath = tmp_path / "det.py"
        fpath.write_text(source)

        state1 = analyze_file(str(fpath))
        state2 = analyze_file(str(fpath))
        assert state1.content_hash == state2.content_hash


class TestAnalyzeProject:
    def test_multi_file(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("def f(): return 1\n")
        (tmp_path / "b.py").write_text("def g(): pass\n")

        state = analyze_project(str(tmp_path))
        assert len(state.files) == 2
        assert state.total_functions == 2

    def test_exclude_patterns(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("def f(): return 1\n")
        (tmp_path / "test_a.py").write_text("def test_f(): pass\n")

        state = analyze_project(str(tmp_path))
        # Default excludes test_* files
        assert len(state.files) == 1
        file_names = [Path(f).name for f in state.files]
        assert "a.py" in file_names
        assert "test_a.py" not in file_names

    def test_exclude_custom(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("def f(): return 1\n")
        (tmp_path / "b.py").write_text("def g(): return 2\n")

        state = analyze_project(str(tmp_path), exclude=["**/b.py"])
        assert len(state.files) == 1

    def test_syntax_error_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "good.py").write_text("def f(): return 1\n")
        (tmp_path / "bad.py").write_text("def f(:\n")

        state = analyze_project(str(tmp_path), exclude=[])
        # bad.py should be skipped due to SyntaxError
        assert len(state.files) == 1


class TestFindGaps:
    def test_file_gaps(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            # spec gap one
            # TODO: gap two
            # type: ignore
            def f():
                return 1
        """)
        fpath = tmp_path / "gaps.py"
        fpath.write_text(source)

        state = analyze_file(str(fpath))
        gaps = find_gaps(state)
        assert len(gaps) == 2
        assert gaps[0].kind in (CommentKind.SPEC, CommentKind.TODO)
        assert gaps[1].kind in (CommentKind.SPEC, CommentKind.TODO)

    def test_project_gaps(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("# gap A\ndef f(): return 1\n")
        (tmp_path / "b.py").write_text("# gap B\ndef g(): return 2\n")

        state = analyze_project(str(tmp_path), exclude=[])
        gaps = find_gaps(state)
        assert len(gaps) == 2


class TestFormatGapReport:
    def test_report_formatting(self, tmp_path: Path) -> None:
        (tmp_path / "mod.py").write_text(
            textwrap.dedent("""\
            # validate payment
            def process():
                # apply discount
                return 1

            def stub():
                pass
        """)
        )

        state = analyze_project(str(tmp_path), exclude=[])
        report = format_gap_report(state)

        assert "# Gap Report" in report
        assert "## Summary" in report
        assert "Files analyzed:" in report
        assert "Total functions:" in report
        assert "Remaining spec comments:" in report
        assert "## Gaps by File" in report

    def test_report_no_gaps(self, tmp_path: Path) -> None:
        (tmp_path / "clean.py").write_text("def f():\n    return 1\n")

        state = analyze_project(str(tmp_path), exclude=[])
        report = format_gap_report(state)

        assert "No Gaps Found" in report
