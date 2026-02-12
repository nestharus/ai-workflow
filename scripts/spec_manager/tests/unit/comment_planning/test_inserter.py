"""Tests for planning.inserter module."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from spec_manager.comment_planning.inserter import (
    _decompose_heuristic,
    _strip_code_fences,
    apply_insertion_plan_to_lines,
    match_comments_to_insertion_points,
)
from spec_manager.comment_planning.models import (
    FunctionInfo,
    InsertionPlan,
    InsertionPoint,
)


class TestStripCodeFences:
    """Tests for code fence stripping utility."""

    def test_strip_json_fences(self) -> None:
        text = '```json\n["a", "b"]\n```'
        result = _strip_code_fences(text)
        assert result == '["a", "b"]'

    def test_strip_python_fences(self) -> None:
        text = '```python\nprint("hello")\n```'
        result = _strip_code_fences(text)
        assert result == 'print("hello")'

    def test_strip_bare_fences(self) -> None:
        text = "```\nsome content\n```"
        result = _strip_code_fences(text)
        assert result == "some content"

    def test_no_fences(self) -> None:
        text = '["a", "b"]'
        result = _strip_code_fences(text)
        assert result == '["a", "b"]'

    def test_unclosed_fence(self) -> None:
        text = '```json\n["a", "b"]'
        result = _strip_code_fences(text)
        assert result == '["a", "b"]'


class TestDecomposeHeuristic:
    """Tests for heuristic intention decomposition."""

    def test_single_sentence(self) -> None:
        func = _make_func_info("process")
        result = _decompose_heuristic("validate input data", func)
        assert len(result) >= 1
        assert any("validate" in r.lower() for r in result)

    def test_multiple_sentences(self) -> None:
        func = _make_func_info("process")
        result = _decompose_heuristic(
            "Validate input data. Transform the results. Store in cache.",
            func,
        )
        assert len(result) >= 3

    def test_conjunction_splitting(self) -> None:
        func = _make_func_info("process")
        result = _decompose_heuristic(
            "validate input and then transform data and then store results",
            func,
        )
        assert len(result) >= 3

    def test_empty_intention(self) -> None:
        func = _make_func_info("process")
        result = _decompose_heuristic("", func)
        assert len(result) >= 1

    def test_lowercases_first_char(self) -> None:
        func = _make_func_info("process")
        result = _decompose_heuristic("Validate the input", func)
        # First char should be lowercased
        assert result[0][0].islower()


class TestApplyInsertionPlan:
    """Tests for applying insertion plans."""

    def test_basic_insertion(self) -> None:
        lines = [
            "def process(data):\n",
            "    x = validate(data)\n",
            "    return x\n",
        ]

        point = InsertionPoint(
            file_path="/test.py",
            line_no=1,
            indent_level=4,
            function_name="process",
            preceding_code="def process(data):",
            following_code="x = validate(data)",
            rationale="After function def",
        )

        plan = InsertionPlan(
            file_path="/test.py",
            insertions=[(point, "check input parameters")],
            source_intention="add validation",
            evidence_refs=[],
        )

        result = apply_insertion_plan_to_lines(plan, lines)
        assert "# check input parameters" in result

    def test_insertion_preserves_indent(self) -> None:
        lines = [
            "def process(data):\n",
            "    x = 1\n",
            "    return x\n",
        ]

        point = InsertionPoint(
            file_path="/test.py",
            line_no=1,
            indent_level=4,
            function_name="process",
            preceding_code="def process(data):",
            following_code="x = 1",
            rationale="test",
        )

        plan = InsertionPlan(
            file_path="/test.py",
            insertions=[(point, "validate input")],
            source_intention="test",
            evidence_refs=[],
        )

        result = apply_insertion_plan_to_lines(plan, lines)
        result_lines = result.splitlines()
        comment_line = next(l for l in result_lines if "# validate input" in l)
        # Should have 4 spaces indent
        assert comment_line.startswith("    #")

    def test_multiple_insertions_bottom_up(self) -> None:
        lines = [
            "def process(data):\n",
            "    x = 1\n",
            "    y = 2\n",
            "    return x + y\n",
        ]

        point1 = InsertionPoint(
            file_path="/test.py",
            line_no=1,
            indent_level=4,
            function_name="process",
            preceding_code="def process(data):",
            following_code="x = 1",
            rationale="first",
        )
        point2 = InsertionPoint(
            file_path="/test.py",
            line_no=2,
            indent_level=4,
            function_name="process",
            preceding_code="x = 1",
            following_code="y = 2",
            rationale="second",
        )

        plan = InsertionPlan(
            file_path="/test.py",
            insertions=[
                (point1, "initialize first value"),
                (point2, "initialize second value"),
            ],
            source_intention="test",
            evidence_refs=[],
        )

        result = apply_insertion_plan_to_lines(plan, lines)
        # Both comments should be present
        assert "# initialize first value" in result
        assert "# initialize second value" in result
        # Result should be valid Python
        ast.parse(result)

    def test_result_is_valid_python(self, tmp_path: Path) -> None:
        """Applying insertion plan produces syntactically valid Python."""
        code = textwrap.dedent("""\
            def process(data):
                x = validate(data)
                y = transform(x)
                return y
        """)
        lines = code.splitlines(keepends=True)

        point = InsertionPoint(
            file_path="/test.py",
            line_no=1,
            indent_level=4,
            function_name="process",
            preceding_code="def process(data):",
            following_code="x = validate(data)",
            rationale="test",
        )

        plan = InsertionPlan(
            file_path="/test.py",
            insertions=[(point, "check data validity")],
            source_intention="test",
            evidence_refs=[],
        )

        result = apply_insertion_plan_to_lines(plan, lines)
        # Must be parseable Python
        ast.parse(result)


class TestMatchCommentsToInsertionPoints:
    """Tests for comment-to-insertion-point matching."""

    def test_empty_comments(self) -> None:
        func = _make_func_info("f")
        result = match_comments_to_insertion_points([], [], func)
        assert result == []

    def test_empty_points(self) -> None:
        func = _make_func_info("f")
        result = match_comments_to_insertion_points(["validate"], [], func)
        assert result == []

    def test_single_comment_single_point(self) -> None:
        func = _make_func_info("f")
        point = InsertionPoint(
            file_path="/test.py",
            line_no=1,
            indent_level=4,
            function_name="f",
            preceding_code="def f():",
            following_code="return",
            rationale="test",
        )
        result = match_comments_to_insertion_points(["validate"], [point], func)
        assert len(result) == 1
        assert result[0][1] == "validate"

    def test_more_points_than_comments(self) -> None:
        func = _make_func_info("f")
        points = [
            InsertionPoint(
                file_path="/test.py",
                line_no=i,
                indent_level=4,
                function_name="f",
                preceding_code=f"line {i}",
                following_code=f"line {i + 1}",
                rationale=f"point {i}",
            )
            for i in range(1, 6)
        ]
        comments = ["validate", "transform"]
        result = match_comments_to_insertion_points(comments, points, func)
        assert len(result) == 2

    def test_result_sorted_by_line(self) -> None:
        func = _make_func_info("f")
        points = [
            InsertionPoint(
                file_path="/test.py",
                line_no=i,
                indent_level=4,
                function_name="f",
                preceding_code=f"line {i}",
                following_code=f"line {i + 1}",
                rationale=f"point {i}",
            )
            for i in range(1, 6)
        ]
        comments = ["validate", "transform", "store"]
        result = match_comments_to_insertion_points(comments, points, func)
        line_nos = [r[0].line_no for r in result]
        assert line_nos == sorted(line_nos)


def _make_func_info(name: str) -> FunctionInfo:
    """Create a minimal FunctionInfo for testing."""
    return FunctionInfo(
        name=name,
        file_path="/test.py",
        start_line=1,
        end_line=5,
        indent_level=0,
        parameters=[],
        return_annotation=None,
        docstring=None,
        body_lines=["def f():", "    pass"],
        calls=[],
        comments=[],
        class_name=None,
        decorators=[],
    )
