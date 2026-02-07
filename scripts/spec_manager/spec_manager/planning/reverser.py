"""Reverse translation engine: code -> pseudocode comments.

Converts existing implementation code back into pseudocode comments
for replanning sections. This "reopens" a completed section for redesign.
"""

from __future__ import annotations

import ast
import json
import re
import tempfile
from pathlib import Path

from spec_manager.planning.code_parser import _find_function, parse_source
from spec_manager.planning.models import (
    CodeFile,
    CommentKind,
    FunctionInfo,
    PseudocodeComment,
    ReversePlan,
)

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
    func = _find_function(code_file, function_name)
    if func is None:
        raise ValueError(
            f"Function '{function_name}' not found in {code_file.file_path}"
        )

    # Determine the range to reverse
    source = Path(code_file.file_path).read_text(encoding="utf-8")
    return reverse_translate_from_source(
        source, code_file.file_path, func, start_line, end_line
    )


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

    if start_line is not None:
        actual_start = max(start_line, body_start)
    else:
        actual_start = body_start

    if end_line is not None:
        actual_end = min(end_line, body_end)
    else:
        actual_end = body_end

    # Extract the code lines to reverse-translate (1-based indexing)
    code_lines = lines[actual_start - 1 : actual_end]
    original_code = "\n".join(code_lines)

    # Generate pseudocode comments
    try:
        comment_texts = _generate_pseudocode_comments(code_lines, func)
    except Exception:
        comment_texts = _generate_pseudocode_comments_heuristic(code_lines, func)

    # Build PseudocodeComment objects
    body_indent = func.indent_level + 4
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
    # Build replacement lines from generated comments
    replacement_lines: list[str] = []
    for comment in plan.generated_comments:
        indent = " " * comment.indent_level
        replacement_lines.append(f"{indent}# {comment.text}\n")

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

    Args:
        source: Full file source.
        func: Function info.

    Returns:
        1-based line number of the first body statement after docstring.
    """
    try:
        tree = ast.parse(source, filename=func.file_path)
    except SyntaxError:
        return func.start_line + 1

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func.name:
                body = node.body
                if not body:
                    return func.start_line + 1

                # Skip docstring
                first_idx = 0
                if (
                    isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)
                ):
                    first_idx = 1

                if first_idx < len(body):
                    return body[first_idx].lineno
                else:
                    # Function body is just a docstring
                    end = body[0].end_lineno or body[0].lineno
                    return end + 1

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
    from spec_manager.refinement.agent_utils import run_agent

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

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(prompt)
        prompt_path = f.name

    try:
        result = run_agent(agent_name, prompt_path)
        return _parse_agent_response(result)
    finally:
        Path(prompt_path).unlink(missing_ok=True)


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
        raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")

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


def _generate_pseudocode_comments_heuristic(
    code_lines: list[str],
    function_context: FunctionInfo,
) -> list[str]:
    """Heuristic reverse-translation when LLM is not available.

    Groups code lines into logical blocks and generates comments
    based on AST analysis of each block.

    Args:
        code_lines: Lines of code to reverse.
        function_context: Function context for hints.

    Returns:
        List of comment text strings.
    """
    comments: list[str] = []
    current_block: list[str] = []

    for line in code_lines:
        stripped = line.strip()
        if not stripped:
            # Empty line ends a block
            if current_block:
                comment = _summarize_code_block(current_block)
                if comment:
                    comments.append(comment)
                current_block = []
            continue

        # Skip existing comments
        if stripped.startswith("#"):
            continue

        current_block.append(stripped)

    # Process remaining block
    if current_block:
        comment = _summarize_code_block(current_block)
        if comment:
            comments.append(comment)

    if not comments:
        comments = [f"implement {function_context.name} logic"]

    return comments


def _summarize_code_block(block: list[str]) -> str | None:
    """Summarize a block of code lines into a pseudocode comment.

    Args:
        block: List of stripped code lines.

    Returns:
        Summary comment string, or None if block is trivial.
    """
    if not block:
        return None

    first_line = block[0]

    # Return statement
    if first_line.startswith("return "):
        return_val = first_line[7:].strip()
        if return_val:
            return f"return the {_simplify_expression(return_val)}"
        return "return result"

    # Assignment
    if "=" in first_line and not first_line.startswith("if ") and not first_line.startswith("for "):
        parts = first_line.split("=", 1)
        var_name = parts[0].strip()
        if not any(op in var_name for op in ["<", ">", "!", "+"]):
            return f"compute {_to_readable(var_name)}"

    # For loop
    if first_line.startswith("for "):
        match = re.match(r"for\s+\w+\s+in\s+(.+?):", first_line)
        if match:
            iterable = match.group(1).strip()
            return f"iterate over {_simplify_expression(iterable)}"

    # If statement
    if first_line.startswith("if "):
        condition = first_line[3:].rstrip(":")
        return f"check if {_simplify_expression(condition)}"

    # Function call
    match = re.match(r"(\w+)\s*\(", first_line)
    if match:
        func_name = match.group(1)
        return f"{_to_readable(func_name)}"

    # Method call
    match = re.match(r"\w+\.(\w+)\s*\(", first_line)
    if match:
        method_name = match.group(1)
        return f"{_to_readable(method_name)}"

    # Raise
    if first_line.startswith("raise "):
        return "raise error on invalid state"

    # With statement
    if first_line.startswith("with "):
        return "open resource context"

    # Try
    if first_line.startswith("try:"):
        return "handle potential errors"

    return f"process {block[0][:40]}"


def _simplify_expression(expr: str) -> str:
    """Simplify a Python expression to readable pseudocode.

    Args:
        expr: Python expression string.

    Returns:
        Simplified human-readable string.
    """
    # Remove parentheses around simple expressions
    expr = expr.strip().strip("()")
    # Truncate long expressions
    if len(expr) > 50:
        expr = expr[:47] + "..."
    return expr


def _to_readable(name: str) -> str:
    """Convert a snake_case or camelCase name to readable text.

    Args:
        name: Python identifier.

    Returns:
        Readable text with spaces.
    """
    # Handle snake_case
    result = name.replace("_", " ")
    # Handle camelCase
    result = re.sub(r"([a-z])([A-Z])", r"\1 \2", result)
    return result.lower().strip()
