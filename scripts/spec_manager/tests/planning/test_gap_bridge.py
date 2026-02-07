"""Tests for planning.gap_bridge module."""

from __future__ import annotations

import textwrap

from spec_manager.core.gaps import Severity
from spec_manager.planning.code_parser import parse_source
from spec_manager.planning.gap_bridge import (
    adjacencies_to_gaps,
    comments_to_gaps,
    scan_for_gaps,
    stubs_to_gaps,
)
from spec_manager.planning.models import (
    AdjacentDetail,
    CommentKind,
    FunctionInfo,
    PseudocodeComment,
)
from spec_manager.refinement.core.gap import GapType


# --- Fixtures ---

SAMPLE_CODE = textwrap.dedent("""\
    def process(data):
        # validate input parameters
        if not data:
            raise ValueError("empty")
        # compute the result
        result = data * 2
        return result

    def stub_function():
        pass

    def another_stub():
        raise NotImplementedError
""")


class TestCommentsToGaps:
    """Tests for comments_to_gaps function."""

    def test_plan_comments_become_gaps(self) -> None:
        comments = [
            PseudocodeComment(
                file_path="/test.py",
                line_no=2,
                text="validate input parameters",
                kind=CommentKind.PLAN,
                indent_level=4,
                function_name="process",
                class_name=None,
            ),
            PseudocodeComment(
                file_path="/test.py",
                line_no=5,
                text="compute the result",
                kind=CommentKind.PLAN,
                indent_level=4,
                function_name="process",
                class_name=None,
            ),
        ]
        gaps = comments_to_gaps(comments)
        assert len(gaps) == 2

    def test_gap_properties(self) -> None:
        comments = [
            PseudocodeComment(
                file_path="/test.py",
                line_no=2,
                text="validate input parameters",
                kind=CommentKind.PLAN,
                indent_level=4,
                function_name="process",
                class_name=None,
            ),
        ]
        gaps = comments_to_gaps(comments)
        gap = gaps[0]
        assert gap.gap_type == GapType.missing_detail
        assert gap.severity == Severity.WARNING
        assert gap.description == "validate input parameters"
        assert "/test.py" in gap.source
        assert gap.status == "open"

    def test_annotation_comments_ignored(self) -> None:
        comments = [
            PseudocodeComment(
                file_path="/test.py",
                line_no=1,
                text="TODO: fix this",
                kind=CommentKind.ANNOTATION,
                indent_level=0,
                function_name=None,
                class_name=None,
            ),
        ]
        gaps = comments_to_gaps(comments)
        assert len(gaps) == 0

    def test_reverse_comments_ignored(self) -> None:
        comments = [
            PseudocodeComment(
                file_path="/test.py",
                line_no=1,
                text="[reverse-translated] validate input",
                kind=CommentKind.REVERSE,
                indent_level=0,
                function_name=None,
                class_name=None,
            ),
        ]
        gaps = comments_to_gaps(comments)
        assert len(gaps) == 0

    def test_gap_id_deterministic(self) -> None:
        comments = [
            PseudocodeComment(
                file_path="/test.py",
                line_no=2,
                text="validate input",
                kind=CommentKind.PLAN,
                indent_level=4,
                function_name="f",
                class_name=None,
            ),
        ]
        gaps1 = comments_to_gaps(comments)
        gaps2 = comments_to_gaps(comments)
        assert gaps1[0].id == gaps2[0].id

    def test_gap_has_evidence(self) -> None:
        comments = [
            PseudocodeComment(
                file_path="/test.py",
                line_no=2,
                text="validate input",
                kind=CommentKind.PLAN,
                indent_level=4,
                function_name="f",
                class_name=None,
            ),
        ]
        gaps = comments_to_gaps(comments)
        assert len(gaps[0].evidence) == 1
        assert gaps[0].evidence[0].detector == "planning.gap_bridge"


class TestStubsToGaps:
    """Tests for stubs_to_gaps function."""

    def test_stub_becomes_gap(self) -> None:
        stub = FunctionInfo(
            name="stub_function",
            file_path="/test.py",
            start_line=10,
            end_line=11,
            indent_level=0,
            parameters=[],
            return_annotation=None,
            docstring=None,
            body_lines=["def stub_function():", "    pass"],
            calls=[],
            comments=[],
            class_name=None,
            decorators=[],
        )
        gaps = stubs_to_gaps([stub])
        assert len(gaps) == 1
        assert gaps[0].severity == Severity.ERROR
        assert "stub_function" in gaps[0].description

    def test_stub_gap_type(self) -> None:
        stub = FunctionInfo(
            name="my_stub",
            file_path="/test.py",
            start_line=1,
            end_line=2,
            indent_level=0,
            parameters=["x", "y"],
            return_annotation="int",
            docstring=None,
            body_lines=["def my_stub(x, y): ...", "    pass"],
            calls=[],
            comments=[],
            class_name=None,
            decorators=[],
        )
        gaps = stubs_to_gaps([stub])
        assert gaps[0].gap_type == GapType.missing_detail

    def test_stub_includes_signature(self) -> None:
        stub = FunctionInfo(
            name="compute",
            file_path="/test.py",
            start_line=1,
            end_line=2,
            indent_level=0,
            parameters=["a", "b"],
            return_annotation="float",
            docstring=None,
            body_lines=["def compute(a, b):", "    pass"],
            calls=[],
            comments=[],
            class_name=None,
            decorators=[],
        )
        gaps = stubs_to_gaps([stub])
        assert "compute(a, b) -> float" in gaps[0].description


class TestAdjacenciesToGaps:
    """Tests for adjacencies_to_gaps function."""

    def test_needs_plan_becomes_gap(self) -> None:
        adj = AdjacentDetail(
            source_function="module.process",
            related_function="module.validate",
            relationship="calls",
            store_or_event=None,
            has_test_coverage=False,
            needs_plan=True,
        )
        gaps = adjacencies_to_gaps([adj])
        assert len(gaps) == 1
        assert gaps[0].severity == Severity.INFO
        assert "module.validate" in gaps[0].description

    def test_no_plan_not_a_gap(self) -> None:
        adj = AdjacentDetail(
            source_function="module.process",
            related_function="module.validate",
            relationship="calls",
            store_or_event=None,
            has_test_coverage=True,
            needs_plan=False,
        )
        gaps = adjacencies_to_gaps([adj])
        assert len(gaps) == 0

    def test_shared_store_info(self) -> None:
        adj = AdjacentDetail(
            source_function="module.writer",
            related_function="module.reader",
            relationship="shared_store",
            store_or_event="database",
            has_test_coverage=False,
            needs_plan=True,
        )
        gaps = adjacencies_to_gaps([adj])
        assert len(gaps) == 1
        assert "database" in gaps[0].description


class TestScanForGaps:
    """Tests for scan_for_gaps function."""

    def test_finds_plan_comments(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        gaps = scan_for_gaps([code_file])

        # Should find at least the plan comments
        plan_gaps = [g for g in gaps if "validate" in g.description or "compute" in g.description]
        assert len(plan_gaps) >= 2

    def test_finds_stubs(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/sample.py")
        gaps = scan_for_gaps([code_file])

        # Should find stub functions
        stub_gaps = [g for g in gaps if "stub" in g.description.lower()]
        assert len(stub_gaps) >= 1

    def test_empty_file_no_gaps(self) -> None:
        code_file = parse_source("", "/test/empty.py")
        gaps = scan_for_gaps([code_file])
        assert len(gaps) == 0

    def test_multiple_files(self) -> None:
        code_a = textwrap.dedent("""\
            def func_a():
                # validate input
                pass
        """)
        code_b = textwrap.dedent("""\
            def func_b():
                # process data
                pass
        """)
        cf_a = parse_source(code_a, "/test/a.py")
        cf_b = parse_source(code_b, "/test/b.py")
        gaps = scan_for_gaps([cf_a, cf_b])
        assert len(gaps) >= 2
