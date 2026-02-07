"""Comment insertion engine with context-aware placement logic.

Decomposes high-level intentions into micro-unit pseudocode comments and
inserts them at context-appropriate locations in algorithmic code files.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from spec_manager.planning.code_parser import (
    _find_function,
    find_insertion_points,
    parse_source,
)
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
    2. Analyze the target function to find valid insertion points
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
    func = _find_function(code_file, function_name)
    if func is None:
        raise ValueError(
            f"Function '{function_name}' not found in {code_file.file_path}"
        )

    # Step 1: Decompose intention into micro-units
    micro_units = decompose_intention(intention, func)

    # Step 2: Find valid insertion points
    insertion_points = find_insertion_points(code_file, function_name)

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
    from spec_manager.refinement.agent_utils import run_agent

    # Build prompt with function context
    body = "\n".join(function_context.body_lines)
    existing_comments = "\n".join(
        f"  # {c.text}" for c in function_context.comments
    )

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

    Handles markdown code fences and single-quote JSON.

    Args:
        response: Raw agent response.

    Returns:
        List of comment strings.

    Raises:
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
        best_idx = _find_best_insertion_point(
            comment, insertion_points, used_indices
        )
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
