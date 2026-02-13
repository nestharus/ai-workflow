"""Reverse translation engine: code -> pseudocode comments.

Converts existing implementation code back into pseudocode comments
for replanning sections. This "reopens" a completed section for redesign.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from spec_manager.comment_planning.models import (
    CodeFile,
    CommentKind,
    FunctionInfo,
    PseudocodeComment,
    ReversePlan,
)
from spec_manager.core.code_analysis import analyze_source

logger = logging.getLogger(__name__)

_REVERSE_MARKER = "[reverse-translated]"


def reverse_translate(
    code_file: CodeFile,
    function_name: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> ReversePlan:
    """Reverse-translate code back to pseudocode comments.

    Replaces implementation code with comments describing what it did.
    This "reopens" a completed section for redesign.

    If start_line/end_line are specified, only that range is reversed.
    Otherwise the entire function body is reversed.

    Args:
        code_file: Parsed code file.
        function_name: Function to reverse-translate.
        start_line: Optional start of range (1-based).
        end_line: Optional end of range (1-based).

    Returns:
        ReversePlan with generated comments and original code.

    Raises:
        ValueError: If function_name is not found in the code file.
    """
    func = next((f for f in code_file.functions if f.name == function_name), None)
    if func is None:
        raise ValueError(f"Function '{function_name}' not found in {code_file.file_path}")

    # Determine the range to reverse
    source = Path(code_file.file_path).read_text(encoding="utf-8")
    return reverse_translate_from_source(source, code_file.file_path, func, start_line, end_line)


def reverse_translate_from_source(
    source: str,
    file_path: str,
    func: FunctionInfo,
    start_line: int | None = None,
    end_line: int | None = None,
) -> ReversePlan:
    """Reverse-translate from source code string.

    Args:
        source: Full file source.
        file_path: File path for attribution.
        func: Function info.
        start_line: Optional start of range (1-based).
        end_line: Optional end of range (1-based).

    Returns:
        ReversePlan with generated comments and original code.
    """
    lines = source.splitlines()

    # Determine body range (skip def line and docstring)
    body_start = _get_body_start(source, func)
    body_end = func.end_line

    actual_start = max(start_line, body_start) if start_line is not None else body_start

    actual_end = min(end_line, body_end) if end_line is not None else body_end

    # Extract the code lines to reverse-translate (1-based indexing)
    code_lines = lines[actual_start - 1 : actual_end]
    original_code = "\n".join(code_lines)

    # Generate pseudocode comments via LLM
    try:
        comment_texts = _generate_pseudocode_comments(code_lines, func)
    except Exception:
        # C03: Surface errors — log LLM failure for diagnosis
        logger.warning(
            "LLM reverse-translation failed for %s — returning empty comments",
            func.name,
            exc_info=True,
        )
        comment_texts = []

    from spec_manager.core.language import INDENT_SIZE

    # Build PseudocodeComment objects
    body_indent = func.indent_level + INDENT_SIZE
    generated_comments: list[PseudocodeComment] = []
    for i, text in enumerate(comment_texts):
        generated_comments.append(
            PseudocodeComment(
                file_path=file_path,
                line_no=actual_start + i,
                text=f"{_REVERSE_MARKER} {text}",
                kind=CommentKind.REVERSE,
                indent_level=body_indent,
                function_name=func.name,
                class_name=func.class_name,
            )
        )

    return ReversePlan(
        file_path=file_path,
        function_name=func.name,
        start_line=actual_start,
        end_line=actual_end,
        generated_comments=generated_comments,
        original_code=original_code,
    )


def apply_reverse_plan(plan: ReversePlan) -> str:
    """Apply a ReversePlan to produce modified file content.

    Replaces the specified code range with generated pseudocode comments.
    Preserves function signature, decorators, and docstring.
    Returns modified content as string. Does NOT write to disk.

    Args:
        plan: The reverse plan to apply.

    Returns:
        Modified file content as string.
    """
    path = Path(plan.file_path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    return apply_reverse_plan_to_lines(plan, lines)


def apply_reverse_plan_to_lines(plan: ReversePlan, lines: list[str]) -> str:
    """Apply a ReversePlan to a list of lines.

    Args:
        plan: The reverse plan to apply.
        lines: Source lines (with newlines preserved).

    Returns:
        Modified file content as string.
    """
    from spec_manager.core.language import COMMENT_PREFIX

    # Build replacement lines from generated comments
    replacement_lines: list[str] = []
    for comment in plan.generated_comments:
        indent = " " * comment.indent_level
        replacement_lines.append(f"{indent}{COMMENT_PREFIX}{comment.text}\n")

    # We need at least a pass statement to keep the function valid
    if replacement_lines:
        indent = " " * plan.generated_comments[0].indent_level
        replacement_lines.append(f"{indent}pass\n")

    # Replace the range (1-based to 0-based)
    start_idx = plan.start_line - 1
    end_idx = plan.end_line

    new_lines = lines[:start_idx] + replacement_lines + lines[end_idx:]
    return "".join(new_lines)


def _get_body_start(source: str, func: FunctionInfo) -> int:
    """Get the line number where the function body starts (after docstring).

    Uses ``analyze_source`` to find the ``body_start_line`` from the
    matching ``RawFunctionInfo``.  Falls back to ``func.start_line + 1``
    when the function cannot be located in the analysis.

    Args:
        source: Full file source.
        func: Function info.

    Returns:
        1-based line number of the first body statement after docstring.
    """
    analysis = analyze_source(source, func.file_path)

    for raw_func in analysis.functions:
        if raw_func.name == func.name and raw_func.start_line == func.start_line:
            if raw_func.body_start_line > 0:
                return raw_func.body_start_line
            return func.start_line + 1

    return func.start_line + 1


def _generate_pseudocode_comments(
    code_lines: list[str],
    function_context: FunctionInfo,
    agent_name: str = "opus-reverse-translator",
) -> list[str]:
    """Use LLM to generate pseudocode comments from code.

    The LLM receives:
    - The code lines to reverse-translate
    - The function signature and docstring for context
    - Instructions to produce one comment per logical step

    Args:
        code_lines: Lines of code to reverse-translate.
        function_context: Function context for the agent.
        agent_name: Name of the agent to use.

    Returns:
        List of comment text strings preserving intent, not implementation detail.

    Raises:
        RuntimeError: If agent invocation fails.
    """
    from spec_manager.core.agent_utils import run_agent

    code_text = "\n".join(code_lines)
    prompt = (
        f"Reverse-translate the following code into pseudocode comments.\n"
        f"Each comment should describe INTENT, not implementation details.\n"
        f"Group related lines into single comments where they form one logical step.\n"
        f"Return a JSON array of strings.\n\n"
        f"## Function Context\n"
        f"Name: {function_context.name}\n"
        f"Parameters: {', '.join(function_context.parameters)}\n"
        f"Return: {function_context.return_annotation or 'None'}\n"
        f"Docstring: {function_context.docstring or 'None'}\n\n"
        f"## Code to Reverse-Translate\n```python\n{code_text}\n```\n\n"
        f"## Output\nReturn ONLY a JSON array of strings, e.g.:\n"
        f'["validate input parameters", "compute the result hash"]\n'
    )

    result = run_agent(
        agent_name=agent_name,
        prompt=prompt,
        workspace=Path.cwd(),
    )
    return _parse_agent_response(result)


def _parse_agent_response(response: str) -> list[str]:
    """Parse agent response expecting a JSON array of strings.

    Args:
        response: Raw agent response.

    Returns:
        List of comment strings.

    Raises:
        ValueError: If the response cannot be parsed.
    """
    cleaned = _strip_code_fences(response)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        cleaned = cleaned.replace("'", '"')
        parsed = json.loads(cleaned)

    if not isinstance(parsed, list):
        raise TypeError(f"Expected JSON array, got {type(parsed).__name__}")

    return [str(item) for item in parsed]


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from text.

    Args:
        text: Text potentially wrapped in code fences.

    Returns:
        Text with code fences removed.
    """
    text = text.strip()
    pattern = r"```(?:json|python)?\s*\n?(.*?)(?:\n?```|$)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text
