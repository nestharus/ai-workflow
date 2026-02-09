"""Comment insertion engine with context-aware placement logic.

Decomposes high-level intentions into micro-unit pseudocode comments and
inserts them at context-appropriate locations in algorithmic code files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from spec_manager.core.code_analysis import analyze_source
from spec_manager.planning.models import (
    CodeFile,
    FunctionInfo,
    InsertionPlan,
    InsertionPoint,
)

if TYPE_CHECKING:
    from spec_manager.planning.evidence_store import EvidenceStore


def plan_insertions(
    intention: str,
    code_file: CodeFile,
    function_name: str,
    evidence_store: EvidenceStore | None = None,
) -> InsertionPlan:
    """Decompose an intention into micro-unit comments and determine placement.

    Steps:
    1. Parse the intention into micro-units via LLM (one comment per logical step)
    2. Analyze the target function to find valid insertionphone insertion points
    3. Match each micro-unit to the best insertion point based on context
    4. Query evidence store for ambiguity resolution if details are unclear

    Args:
        intention: High-level description of new work.
        code_file: Parsed code file.
        function_name: Target function to insert into.
        evidence_store: Optional hollowed-out spec evidence for ambiguity resolution.

    Returns:
        InsertionPlan with ordered (InsertionPoint, comment_text) pairs.

    Raises:
        ValueError: If function_name is not found in the code file.
    """
    func = next((f for f in code_file.functions if f.name == function_name), None)
    if func is None:
        raise ValueError(f"Function '{function_name}' not found in {code_file.file_path}")

    # Step 1: Decompose intention into micro-units
    micro_units = decompose_intention(intention, func)

    # Step 2: Find valid insertion points
    insertion_points = _find_insertion_points(code_file, function_name)

    # Step 3: Match comments to insertion points
    matched = match_comments_to_insertion_points(micro_units, insertion_points, func)

    # Step 4: Resolve ambiguities via evidence store
    evidence_refs: list[str] = []
    if evidence_store is not None:
        for _, comment_text in matched:
            resolution = evidence_store.resolve_ambiguity(comment_text, func)
            if resolution.resolved:
                evidence_refs.extend(resolution.evidence_refs)

    return InsertionPlan(
        file_path=code_file.file_path,
        insertions=matched,
        source_intention=intention,
        evidence_refs=evidence_refs,
    )


def apply_insertion_plan(plan: InsertionPlan) -> str:
    """Apply an InsertionPlan to produce modified file content.

    Reads the file, inserts comments at specified locations,
    returns the modified content as a string. Does NOT write to disk.

    Insertions are applied bottom-up to preserve line numbers.

    Args:
        plan: The insertion plan to apply.

    Returns:
        Modified file content as string.
    """
    path = Path(plan.file_path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    return apply_insertion_plan_to_lines(plan, lines)


def apply_insertion_plan_to_lines(plan: InsertionPlan, lines: list[str]) -> str:
    """Apply an InsertionPlan to a list of lines.

    Args:
        plan: The insertion plan to apply.
        lines: Source lines (with newlines preserved).

    Returns:
        Modified file content as string.
    """
    # Sort insertions by line number descending (bottom-up)
    sorted_insertions = sorted(plan.insertions, key=lambda x: x[0].line_no, reverse=True)

    for point, comment_text in sorted_insertions:
        indent = " " * point.indent_level
        comment_line = f"{indent}# {comment_text}\n"

        # Insert after the specified line number
        insert_idx = point.line_no  # 0-based index for insertion = line_no (after line_no)
        if insert_idx > len(lines):
            insert_idx = len(lines)
        lines.insert(insert_idx, comment_line)

    return "".join(lines)


def decompose_intention(
    intention: str,
    function_context: FunctionInfo,
    agent_name: str = "opus-plan-decomposer",
) -> list[str]:
    """Decompose a high-level intention into micro-unit comment texts via LLM.

    Each returned string is a single-responsibility pseudocode comment.
    The LLM sees the function context (signature, existing code, existing comments)
    to produce contextually relevant decomposition.

    When the LLM agent is not available, falls back to a heuristic decomposition.

    Args:
        intention: High-level intention string.
        function_context: The target function info for context.
        agent_name: Name of the agent to use for decomposition.

    Returns:
        List of comment text strings (without '# ' prefix).
    """
    try:
        return _decompose_via_agent(intention, function_context, agent_name)
    except Exception:
        return _decompose_heuristic(intention, function_context)


def _decompose_via_agent(
    intention: str,
    function_context: FunctionInfo,
    agent_name: str,
) -> list[str]:
    """Decompose intention using an LLM agent.

    Args:
        intention: The intention text.
        function_context: Function context for the agent.
        agent_name: Agent name to invoke.

    Returns:
        List of micro-unit comment strings.

    Raises:
        RuntimeError: If the agent invocation fails.
    """
    from spec_manager.core.agent_utils import PROJECT_ROOT, run_agent

    # Build prompt with function context
    body = "\n".join(function_context.body_lines)
    existing_comments = "\n".join(f"  # {c.text}" for c in function_context.comments)

    prompt = (
        f"Decompose the following intention into micro-unit pseudocode comments.\n"
        f"Each comment should describe a single logical step.\n"
        f"Return a JSON array of strings.\n\n"
        f"## Intention\n{intention}\n\n"
        f"## Target Function\n"
        f"Name: {function_context.name}\n"
        f"Parameters: {', '.join(function_context.parameters)}\n"
        f"Return: {function_context.return_annotation or 'None'}\n\n"
        f"## Existing Code\n```python\n{body}\n```\n\n"
        f"## Existing Comments\n{existing_comments or 'None'}\n\n"
        f"## Output\nReturn ONLY a JSON array of strings, e.g.:\n"
        f'["validate input parameters", "compute result hash", "store result"]\n'
    )

    result = run_agent(agent_name=agent_name, prompt=prompt, workspace=PROJECT_ROOT)
    return _parse_agent_response(result)


def _parse_agent_response(response: str) -> list[str]:
    """Parse agent response expecting a JSON array of strings.

    Handles markdown code fences and single-quote JSON.

    Args:
        response: Raw agent response.

    Returns:
        List of comment strings.

    Raises:
        TypeError: If the response is not a JSON array.
        ValueError: If the response cannot be parsed.
    """
    # Strip code fences
    cleaned = _strip_code_fences(response)

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try fixing single quotes
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
    # Match ```json ... ``` or ``` ... ```
    pattern = r"```(?:json|python)?\s*\n?(.*?)(?:\n?```|$)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _decompose_heuristic(
    intention: str,
    function_context: FunctionInfo,
) -> list[str]:
    """Heuristic decomposition when LLM agent is not available.

    Splits the intention into logical steps based on conjunctions,
    sentence boundaries, and common patterns.

    Args:
        intention: The intention text.
        function_context: Function context for additional hints.

    Returns:
        List of comment text strings.
    """
    # Split on common delimiters
    parts: list[str] = []

    # Split on sentence boundaries
    sentences = re.split(r"[.;]\s+", intention.strip().rstrip("."))

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # Split on "and then", "then", "after that"
        sub_parts = re.split(r"\s+(?:and then|then|after that|finally|also)\s+", sentence)

        for part in sub_parts:
            part = part.strip()
            if part:
                # Lowercase first char for comment style
                if part[0].isupper():
                    part = part[0].lower() + part[1:]
                parts.append(part)

    if not parts:
        parts = [intention.strip().rstrip(".")]

    return parts


def match_comments_to_insertion_points(
    comments: list[str],
    insertion_points: list[InsertionPoint],
    function: FunctionInfo,
) -> list[tuple[InsertionPoint, str]]:
    """Match decomposed comments to the best insertion points.

    Uses semantic similarity between comment text and surrounding code context
    to determine optimal placement. Falls back to sequential ordering when
    context is ambiguous.

    Args:
        comments: List of comment text strings.
        insertion_points: Available insertion points.
        function: The target function.

    Returns:
        List of (InsertionPoint, comment_text) pairs.
    """
    if not comments:
        return []

    if not insertion_points:
        return []

    # If we have fewer or equal insertion points than comments, distribute evenly
    if len(insertion_points) <= len(comments):
        result: list[tuple[InsertionPoint, str]] = []
        for i, comment in enumerate(comments):
            # Map each comment to the nearest insertion point proportionally
            idx = min(i * len(insertion_points) // len(comments), len(insertion_points) - 1)
            result.append((insertion_points[idx], comment))
        return result

    # More insertion points than comments: find best match for each comment
    result = []
    used_indices: set[int] = set()

    for comment in comments:
        best_idx = _find_best_insertion_point(comment, insertion_points, used_indices)
        used_indices.add(best_idx)
        result.append((insertion_points[best_idx], comment))

    # Sort by line number to maintain order
    result.sort(key=lambda x: x[0].line_no)

    return result


def _find_best_insertion_point(
    comment: str,
    insertion_points: list[InsertionPoint],
    used_indices: set[int],
) -> int:
    """Find the best insertion point for a comment.

    Uses keyword overlap between comment text and surrounding code.

    Args:
        comment: The comment text.
        insertion_points: Available insertion points.
        used_indices: Indices already used by other comments.

    Returns:
        Index of the best insertion point.
    """
    comment_words = set(comment.lower().split())
    best_score = -1
    best_idx = 0

    for i, point in enumerate(insertion_points):
        if i in used_indices:
            continue

        # Score based on keyword overlap with surrounding context
        context_words = set()
        context_words.update(point.preceding_code.lower().split())
        context_words.update(point.following_code.lower().split())

        overlap = len(comment_words & context_words)
        # Prefer earlier unused points when scores are tied
        score = overlap * 1000 - i

        if score > best_score:
            best_score = score
            best_idx = i

    return best_idx


# ---------------------------------------------------------------------------
# Insertion-point discovery (moved from code_parser)
# ---------------------------------------------------------------------------


def _find_insertion_points(code_file: CodeFile, function_name: str) -> list[InsertionPoint]:
    """Find valid insertion points within a function.

    Insertion points are between statements, respecting control flow.
    Each point knows its context (what comes before/after).

    Args:
        code_file: Parsed code file.
        function_name: Name of the target function.

    Returns:
        List of InsertionPoint objects.

    Raises:
        ValueError: If function_name is not found in the code file.
    """
    func = next((f for f in code_file.functions if f.name == function_name), None)
    if func is None:
        raise ValueError(f"Function '{function_name}' not found in {code_file.file_path}")

    source = Path(code_file.file_path).read_text(encoding="utf-8")
    return _find_insertion_points_from_source(source, func, code_file.file_path)


def _find_insertion_points_from_source(
    source: str,
    func: FunctionInfo,
    file_path: str,
) -> list[InsertionPoint]:
    """Find insertion points within a function from source text.

    Uses analyze_source() for function metadata and line-based heuristics
    for statement boundary detection.  Language-agnostic.

    Args:
        source: Full file source.
        func: Function info.
        file_path: File path for attribution.

    Returns:
        List of InsertionPoint objects.
    """
    lines = source.splitlines()
    points: list[InsertionPoint] = []

    # Use analyze_source to locate the function
    analysis = analyze_source(source, file_path)
    raw_func = None
    for rf in analysis.functions:
        if rf.name == func.name:
            raw_func = rf
            break
    if raw_func is None:
        return points

    body_indent = func.indent_level + 4  # Standard Python indentation

    # Determine body start: body_start_line from analysis, accounting for docstring
    body_start = raw_func.body_start_line
    body_end = raw_func.end_line

    if body_start <= 0 or body_end <= 0:
        return points

    # Find top-level statement boundaries within the function body.
    stmt_ranges = _find_statement_ranges(
        lines, body_start, body_end, body_indent, raw_func.has_docstring
    )

    if not stmt_ranges:
        return points

    # --- Start of function body (after docstring or def line) ---
    first_range = stmt_ranges[0]
    insert_after_line = first_range[0] - 1
    if insert_after_line < 1:
        insert_after_line = raw_func.start_line

    preceding = lines[insert_after_line - 1] if insert_after_line <= len(lines) else ""
    following = lines[first_range[0] - 1] if first_range[0] <= len(lines) else ""

    points.append(
        InsertionPoint(
            file_path=file_path,
            line_no=insert_after_line,
            indent_level=body_indent,
            function_name=func.name,
            preceding_code=preceding.strip(),
            following_code=following.strip(),
            rationale="Start of function body",
        )
    )

    # --- Between statements ---
    for i in range(len(stmt_ranges) - 1):
        current_end = stmt_ranges[i][1]
        next_start = stmt_ranges[i + 1][0]

        preceding = lines[current_end - 1] if current_end <= len(lines) else ""
        following = lines[next_start - 1] if next_start <= len(lines) else ""

        points.append(
            InsertionPoint(
                file_path=file_path,
                line_no=current_end,
                indent_level=body_indent,
                function_name=func.name,
                preceding_code=preceding.strip(),
                following_code=following.strip(),
                rationale="Between statements",
            )
        )

    # --- End of function body ---
    last_end = stmt_ranges[-1][1]
    preceding = lines[last_end - 1] if last_end <= len(lines) else ""

    points.append(
        InsertionPoint(
            file_path=file_path,
            line_no=last_end,
            indent_level=body_indent,
            function_name=func.name,
            preceding_code=preceding.strip(),
            following_code="",
            rationale="End of function body",
        )
    )

    return points


def _find_statement_ranges(
    lines: list[str],
    body_start: int,
    body_end: int,
    body_indent: int,
    has_docstring: bool,
) -> list[tuple[int, int]]:
    """Identify top-level statement ranges within a function body.

    A statement starts on a line whose indentation equals *body_indent*
    (the function body indent level).  Continuation lines (deeper indent,
    blank lines, or lines inside multi-line strings) are folded into the
    preceding statement.

    Args:
        lines: All source lines (0-indexed list).
        body_start: 1-based line where the body begins.
        body_end: 1-based last line of the function.
        body_indent: Expected indent level for top-level body statements.
        has_docstring: Whether to skip a leading docstring.

    Returns:
        List of (start_line, end_line) tuples, 1-based inclusive.
    """
    ranges: list[tuple[int, int]] = []
    current_start: int | None = None
    current_end: int | None = None

    # Track whether we're inside a docstring to skip
    skip_until_line = 0
    if has_docstring:
        skip_until_line = _find_docstring_end(lines, body_start)

    for line_no in range(body_start, body_end + 1):
        if line_no <= skip_until_line:
            continue

        idx = line_no - 1
        if idx >= len(lines):
            break

        line = lines[idx]
        stripped = line.rstrip()

        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())

        if indent == body_indent:
            if current_start is not None:
                ranges.append((current_start, current_end or current_start))
            current_start = line_no
            current_end = line_no
        elif current_start is not None:
            current_end = line_no

    if current_start is not None:
        ranges.append((current_start, current_end or current_start))

    return ranges


def _find_docstring_end(lines: list[str], start: int) -> int:
    """Find the last line of a docstring starting at *start* (1-based).

    Handles single-line and multi-line triple-quoted strings.

    Returns:
        1-based line number of the docstring's closing line,
        or *start* if no docstring is found.
    """
    idx = start - 1
    if idx >= len(lines):
        return start

    line = lines[idx].strip()

    for quote in ('"""', "'''"):
        if quote in line:
            if line.count(quote) >= 2:
                return start
            for j in range(start, len(lines)):
                if quote in lines[j].strip() and j > idx:
                    return j + 1
            return start

    return start
