"""Tests for planning.reverser module."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from spec_manager.planning.code_parser import parse_file, parse_source
from spec_manager.planning.models import CommentKind
from spec_manager.planning.reverser import (
    _generate_pseudocode_comments_heuristic,
    _summarize_code_block,
    apply_reverse_plan_to_lines,
    reverse_translate_from_source,
)


# --- Fixtures ---

SAMPLE_CODE = textwrap.dedent("""\
    def process_order(order):
        \"\"\"Process a customer order.\"\"\"
        validated = validate_order(order)
        if not validated:
            raise ValueError("Invalid order")
        total = compute_total(order.items)
        discount = apply_discount(total, order.customer)
        result = save_order(order, total - discount)
        return result
""")


class TestSummarizeCodeBlock:
    """Tests for _summarize_code_block helper."""

    def test_return_statement(self) -> None:
        result = _summarize_code_block(["return result"])
        assert result is not None
        assert "return" in result.lower()

    def test_assignment(self) -> None:
        result = _summarize_code_block(["total = compute_total(items)"])
        assert result is not None
        assert "compute" in result.lower()

    def test_for_loop(self) -> None:
        result = _summarize_code_block(["for item in items:"])
        assert result is not None
        assert "iterate" in result.lower()

    def test_if_statement(self) -> None:
        result = _summarize_code_block(["if not validated:"])
        assert result is not None
        assert "check" in result.lower()

    def test_raise_statement(self) -> None:
        result = _summarize_code_block(['raise ValueError("error")'])
        assert result is not None
        assert "raise" in result.lower() or "error" in result.lower()

    def test_empty_block(self) -> None:
        result = _summarize_code_block([])
        assert result is None

    def test_function_call(self) -> None:
        result = _summarize_code_block(["validate_order(order)"])
        assert result is not None
        assert "validate" in result.lower()


class TestGeneratePseudocodeHeuristic:
    """Tests for heuristic reverse translation."""

    def test_generates_comments(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]
        lines = [
            "    validated = validate_order(order)",
            "    if not validated:",
            '        raise ValueError("Invalid order")',
            "    total = compute_total(order.items)",
        ]
        result = _generate_pseudocode_comments_heuristic(lines, func)
        assert len(result) >= 1

    def test_skips_blank_lines(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]
        lines = [
            "    x = 1",
            "",
            "    y = 2",
        ]
        result = _generate_pseudocode_comments_heuristic(lines, func)
        assert len(result) >= 2

    def test_skips_existing_comments(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]
        lines = [
            "    # existing comment",
            "    x = 1",
        ]
        result = _generate_pseudocode_comments_heuristic(lines, func)
        # Should not include the existing comment
        assert all("existing comment" not in r for r in result)


class TestReverseTranslateFromSource:
    """Tests for reverse_translate_from_source function."""

    def test_generates_reverse_plan(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        plan = reverse_translate_from_source(
            SAMPLE_CODE, "/test/process.py", func
        )
        assert plan.function_name == "process_order"
        assert plan.file_path == "/test/process.py"
        assert len(plan.generated_comments) >= 1

    def test_comments_have_reverse_marker(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        plan = reverse_translate_from_source(
            SAMPLE_CODE, "/test/process.py", func
        )
        for comment in plan.generated_comments:
            assert "[reverse-translated]" in comment.text

    def test_comments_are_reverse_kind(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        plan = reverse_translate_from_source(
            SAMPLE_CODE, "/test/process.py", func
        )
        for comment in plan.generated_comments:
            assert comment.kind == CommentKind.REVERSE

    def test_original_code_preserved(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        plan = reverse_translate_from_source(
            SAMPLE_CODE, "/test/process.py", func
        )
        assert "validate_order" in plan.original_code

    def test_partial_range(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        # Reverse only lines 3-5
        plan = reverse_translate_from_source(
            SAMPLE_CODE, "/test/process.py", func,
            start_line=3, end_line=5,
        )
        assert plan.start_line >= 3
        assert plan.end_line <= 5


class TestApplyReversePlan:
    """Tests for applying reverse plans."""

    def test_result_contains_comments(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        plan = reverse_translate_from_source(
            SAMPLE_CODE, "/test/process.py", func
        )

        lines = SAMPLE_CODE.splitlines(keepends=True)
        result = apply_reverse_plan_to_lines(plan, lines)

        # Should contain reverse-translated comments
        assert "[reverse-translated]" in result
        # Should contain pass (to keep function valid)
        assert "pass" in result

    def test_result_is_valid_python(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        plan = reverse_translate_from_source(
            SAMPLE_CODE, "/test/process.py", func
        )

        lines = SAMPLE_CODE.splitlines(keepends=True)
        result = apply_reverse_plan_to_lines(plan, lines)

        # Must be parseable Python
        ast.parse(result)

    def test_preserves_function_signature(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        plan = reverse_translate_from_source(
            SAMPLE_CODE, "/test/process.py", func
        )

        lines = SAMPLE_CODE.splitlines(keepends=True)
        result = apply_reverse_plan_to_lines(plan, lines)

        # Function signature should be preserved
        assert "def process_order(order):" in result
