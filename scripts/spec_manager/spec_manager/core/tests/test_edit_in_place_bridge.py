"""Tests for the edit-in-place bridge to existing refinement workflow.

Covers Plan 5: Integration Bridge.
"""

from __future__ import annotations

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
    analyze_file,
    analyze_project,
)
from spec_manager.core.edit_in_place_bridge import (
    file_state_to_gap_queue,
    function_info_to_tracked_unit,
    project_state_to_gap_queue,
    spec_comment_to_gap,
)
from spec_manager.core.gaps import Severity
from spec_manager.core.provenance import UnitStatus, UnitType
from spec_manager.refinement.core.gap import GapType
from spec_manager.refinement.workspace.state import Phase


class TestSpecCommentToGap:
    def test_spec_comment_conversion(self) -> None:
        comment = SpecComment(
            file="module.py",
            line=23,
            col_offset=4,
            text="validate payment against fraud rules",
            raw="# validate payment against fraud rules",
            kind=CommentKind.SPEC,
            enclosing_function="process_order",
        )
        gap = spec_comment_to_gap(comment)

        assert gap.gap_type == GapType.missing_detail
        assert gap.severity == Severity.ERROR
        assert gap.status == "open"
        assert "module.py:23" in gap.source
        assert gap.description == "validate payment against fraud rules"
        assert gap.derived_artifact_target == "process_order"
        assert len(gap.evidence) == 1
        assert gap.evidence[0].invariant_family == "edit_in_place"

    def test_todo_comment_maps_to_ambiguity(self) -> None:
        comment = SpecComment(
            file="module.py",
            line=10,
            col_offset=0,
            text="TODO: implement retry logic",
            raw="# TODO: implement retry logic",
            kind=CommentKind.TODO,
            enclosing_function=None,
        )
        gap = spec_comment_to_gap(comment)

        assert gap.gap_type == GapType.ambiguity
        assert gap.derived_artifact_target == "module-level"

    def test_gap_has_valid_id(self) -> None:
        comment = SpecComment(
            file="test.py",
            line=5,
            col_offset=0,
            text="spec",
            raw="# spec",
            kind=CommentKind.SPEC,
            enclosing_function=None,
        )
        gap = spec_comment_to_gap(comment)
        assert gap.id.startswith("EIP-")

    def test_gap_serializable(self) -> None:
        """Gap should be serializable via to_dict."""
        comment = SpecComment(
            file="test.py",
            line=1,
            col_offset=0,
            text="gap",
            raw="# gap",
            kind=CommentKind.SPEC,
            enclosing_function=None,
        )
        gap = spec_comment_to_gap(comment)
        d = gap.to_dict()
        assert isinstance(d, dict)
        assert d["gap_type"] == "missing_detail"
        assert d["severity"] == "error"


class TestFunctionInfoToTrackedUnit:
    def test_implemented_function(self) -> None:
        func = FunctionInfo(
            name="process",
            qualified_name="Service.process",
            file="service.py",
            line_start=10,
            line_end=25,
            col_offset=4,
            is_async=False,
            decorators=["staticmethod"],
            args=["self", "data"],
            return_annotation="bool",
            docstring="Process the service data.",
            body_line_count=15,
            translation_state=TranslationState.IMPLEMENTED,
            spec_comments=[],
            stub_reason=None,
        )
        unit = function_info_to_tracked_unit(func)

        assert unit.id == "EIP-FUNC-Service.process"
        assert unit.unit_type == UnitType.ALGORITHM
        assert unit.status == UnitStatus.PROCESSED
        assert unit.content == "Process the service data."
        assert unit.source.file == "service.py"
        assert unit.source.line_start == 10
        assert unit.source.line_end == 25

    def test_stub_function_status(self) -> None:
        func = FunctionInfo(
            name="foo",
            qualified_name="foo",
            file="test.py",
            line_start=1,
            line_end=2,
            col_offset=0,
            is_async=False,
            decorators=[],
            args=[],
            return_annotation=None,
            docstring=None,
            body_line_count=1,
            translation_state=TranslationState.STUB,
            spec_comments=[],
            stub_reason="pass",
        )
        unit = function_info_to_tracked_unit(func)
        assert unit.status == UnitStatus.PENDING

    def test_partial_function_status(self) -> None:
        func = FunctionInfo(
            name="bar",
            qualified_name="bar",
            file="test.py",
            line_start=1,
            line_end=5,
            col_offset=0,
            is_async=False,
            decorators=[],
            args=["x"],
            return_annotation=None,
            docstring=None,
            body_line_count=4,
            translation_state=TranslationState.PARTIAL,
            spec_comments=[],
            stub_reason=None,
        )
        unit = function_info_to_tracked_unit(func)
        assert unit.status == UnitStatus.PENDING

    def test_verified_function_status(self) -> None:
        func = FunctionInfo(
            name="verified_func",
            qualified_name="verified_func",
            file="test.py",
            line_start=1,
            line_end=3,
            col_offset=0,
            is_async=False,
            decorators=[],
            args=[],
            return_annotation=None,
            docstring=None,
            body_line_count=2,
            translation_state=TranslationState.VERIFIED,
            spec_comments=[],
            stub_reason=None,
        )
        unit = function_info_to_tracked_unit(func)
        assert unit.status == UnitStatus.MAPPED

    def test_no_docstring_uses_signature(self) -> None:
        func = FunctionInfo(
            name="foo",
            qualified_name="MyClass.foo",
            file="test.py",
            line_start=1,
            line_end=2,
            col_offset=0,
            is_async=False,
            decorators=[],
            args=["self", "x"],
            return_annotation=None,
            docstring=None,
            body_line_count=1,
            translation_state=TranslationState.STUB,
            spec_comments=[],
            stub_reason="pass",
        )
        unit = function_info_to_tracked_unit(func)
        assert "MyClass.foo" in unit.content
        assert "self" in unit.content
        assert "x" in unit.content


class TestFileStateToGapQueue:
    def test_gap_count(self, tmp_path: Path) -> None:
        source = textwrap.dedent("""\
            # gap one
            # TODO: gap two
            def stub_func():
                pass

            def impl():
                return 1
        """)
        fpath = tmp_path / "test.py"
        fpath.write_text(source)

        state = analyze_file(str(fpath))
        queue = file_state_to_gap_queue(state)

        # 2 spec comments + 1 stub function = 3 gaps
        assert len(queue.gaps) == 3
        assert all(g.status == "open" for g in queue.gaps)

    def test_no_gaps_empty_queue(self, tmp_path: Path) -> None:
        source = "def f():\n    return 1\n"
        fpath = tmp_path / "clean.py"
        fpath.write_text(source)

        state = analyze_file(str(fpath))
        queue = file_state_to_gap_queue(state)
        assert len(queue.gaps) == 0

    def test_gap_queue_compatible_with_update(self, tmp_path: Path) -> None:
        """GapQueue.update should work with our gaps."""
        source = "# gap\ndef f(): pass\n"
        fpath = tmp_path / "compat.py"
        fpath.write_text(source)

        state = analyze_file(str(fpath))
        queue = file_state_to_gap_queue(state)

        # Should not raise
        queue.update(queue.gaps)
        metrics = queue.get_coverage_metrics()
        assert metrics["total_gaps"] > 0
        assert metrics["open_gaps"] > 0


class TestProjectStateToGapQueue:
    def test_aggregation_across_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("# gap A\ndef f(): return 1\n")
        (tmp_path / "b.py").write_text("# gap B\ndef g(): pass\n")

        state = analyze_project(str(tmp_path), exclude=[])
        queue = project_state_to_gap_queue(state)

        # a.py: 1 spec comment, b.py: 1 spec comment + 1 stub
        assert len(queue.gaps) == 3


class TestPhaseEnumExtension:
    def test_edit_in_place_phase_exists(self) -> None:
        assert Phase.EDIT_IN_PLACE.value == "edit_in_place"
