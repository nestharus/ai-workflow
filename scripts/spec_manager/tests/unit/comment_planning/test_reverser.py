"""Tests for planning.reverser module."""

from __future__ import annotations

import ast
import textwrap
from unittest.mock import patch

from spec_manager.comment_planning.models import CommentKind, parse_source
from spec_manager.comment_planning.reverser import (
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

_MOCK_COMMENTS = [
    "validate the order",
    "check validation result",
    "compute total and apply discount",
    "save the order and return result",
]


def _patch_llm():
    """Patch the LLM pseudocode generator to return mock comments."""
    return patch(
        "spec_manager.comment_planning.reverser._generate_pseudocode_comments",
        return_value=list(_MOCK_COMMENTS),
    )


class TestReverseTranslateFromSource:
    """Tests for reverse_translate_from_source function."""

    def test_generates_reverse_plan(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        with _patch_llm():
            plan = reverse_translate_from_source(SAMPLE_CODE, "/test/process.py", func)
        assert plan.function_name == "process_order"
        assert plan.file_path == "/test/process.py"
        assert len(plan.generated_comments) >= 1

    def test_comments_have_reverse_marker(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        with _patch_llm():
            plan = reverse_translate_from_source(SAMPLE_CODE, "/test/process.py", func)
        for comment in plan.generated_comments:
            assert "[reverse-translated]" in comment.text

    def test_comments_are_reverse_kind(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        with _patch_llm():
            plan = reverse_translate_from_source(SAMPLE_CODE, "/test/process.py", func)
        for comment in plan.generated_comments:
            assert comment.kind == CommentKind.REVERSE

    def test_original_code_preserved(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        with _patch_llm():
            plan = reverse_translate_from_source(SAMPLE_CODE, "/test/process.py", func)
        assert "validate_order" in plan.original_code

    def test_partial_range(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        with _patch_llm():
            # Reverse only lines 3-5
            plan = reverse_translate_from_source(
                SAMPLE_CODE,
                "/test/process.py",
                func,
                start_line=3,
                end_line=5,
            )
        assert plan.start_line >= 3
        assert plan.end_line <= 5

    def test_llm_failure_returns_empty_comments(self) -> None:
        """When the LLM fails, we get a plan with no comments (no regex fallback)."""
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        with patch(
            "spec_manager.comment_planning.reverser._generate_pseudocode_comments",
            side_effect=RuntimeError("LLM unavailable"),
        ):
            plan = reverse_translate_from_source(SAMPLE_CODE, "/test/process.py", func)
        assert plan.generated_comments == []
        assert plan.original_code != ""


class TestApplyReversePlan:
    """Tests for applying reverse plans."""

    def test_result_contains_comments(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        with _patch_llm():
            plan = reverse_translate_from_source(SAMPLE_CODE, "/test/process.py", func)

        lines = SAMPLE_CODE.splitlines(keepends=True)
        result = apply_reverse_plan_to_lines(plan, lines)

        # Should contain reverse-translated comments
        assert "[reverse-translated]" in result
        # Should contain pass (to keep function valid)
        assert "pass" in result

    def test_result_is_valid_python(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        with _patch_llm():
            plan = reverse_translate_from_source(SAMPLE_CODE, "/test/process.py", func)

        lines = SAMPLE_CODE.splitlines(keepends=True)
        result = apply_reverse_plan_to_lines(plan, lines)

        # Must be parseable Python
        ast.parse(result)

    def test_preserves_function_signature(self) -> None:
        code_file = parse_source(SAMPLE_CODE, "/test/process.py")
        func = code_file.functions[0]

        with _patch_llm():
            plan = reverse_translate_from_source(SAMPLE_CODE, "/test/process.py", func)

        lines = SAMPLE_CODE.splitlines(keepends=True)
        result = apply_reverse_plan_to_lines(plan, lines)

        # Function signature should be preserved
        assert "def process_order(order):" in result
