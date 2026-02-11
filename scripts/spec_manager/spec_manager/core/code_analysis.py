"""Language-agnostic source code analysis via LLM.

Replaces Python-specific ast/tokenize parsing with LLM-based structural
analysis. All code structure extraction (function boundaries, comments,
stub detection) goes through this module.

The module calls the ``pdd-code-analyzer`` agent and caches results by
content hash so repeated analysis of the same file is free.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.core.json_extraction import _extract_json_payload
from spec_manager.refinement.formats import _strip_code_fences

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures returned by LLM analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawFunctionInfo:
    """Function/method info extracted by LLM."""

    name: str
    qualified_name: str
    start_line: int
    end_line: int
    is_async: bool
    is_stub: bool
    stub_reason: str | None
    has_docstring: bool
    docstring: str | None
    decorators: tuple[str, ...]
    args: tuple[str, ...]
    return_annotation: str | None
    body_start_line: int
    body_line_count: int


@dataclass(frozen=True)
class RawCommentInfo:
    """Comment info extracted by LLM — text WITHOUT language-specific delimiter."""

    line: int
    col_offset: int
    text: str  # Clean text, no delimiter
    raw: str  # Original with delimiter
    enclosing_function: str | None


@dataclass
class SourceAnalysis:
    """Complete structural analysis of a source file."""

    functions: list[RawFunctionInfo] = field(default_factory=list)
    comments: list[RawCommentInfo] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Cache: content-hash → SourceAnalysis
# ---------------------------------------------------------------------------

_analysis_cache: dict[str, SourceAnalysis] = {}


def clear_cache() -> None:
    """Clear the analysis cache (useful in tests)."""
    _analysis_cache.clear()


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------

# Default analyzer is set at module level to allow test injection
_default_analyzer: Callable[[str, str, Path | None], SourceAnalysis] | None = None


def _call_llm_analyzer(
    content: str,
    filepath: str,
    workspace: Path | None,
) -> SourceAnalysis:
    """Call the pdd-code-analyzer agent and parse the response."""
    from spec_manager.core.agent_utils import run_agent

    ws = workspace or Path.cwd()

    prompt_lines = [
        "Analyze the following source code and return the JSON structure",
        "described in your system prompt.",
        "",
        f"File: {filepath}",
        "",
        "```",
        content,
        "```",
    ]
    prompt = "\n".join(prompt_lines)

    raw_output = run_agent(
        agent_name="pdd-code-analyzer",
        prompt=prompt,
        workspace=ws,
    )

    return _parse_analysis_response(raw_output)


def _parse_analysis_response(raw_output: str) -> SourceAnalysis:
    """Parse the JSON response from the code analyzer agent."""
    cleaned = _strip_code_fences(raw_output)

    # Try direct JSON parse first, then fallback to extraction
    data: dict[str, Any] | None = None
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        extracted = _extract_json_payload(cleaned)
        if extracted:
            with contextlib.suppress(json.JSONDecodeError, ValueError):
                data = json.loads(extracted)

    if data is None:
        logger.error("Failed to parse code analyzer response: %s", raw_output[:200])
        return SourceAnalysis()

    return _dict_to_source_analysis(data)


def _dict_to_source_analysis(data: dict[str, Any]) -> SourceAnalysis:
    """Convert a parsed JSON dict to a SourceAnalysis."""
    functions: list[RawFunctionInfo] = []
    for f in data.get("functions", []):
        functions.append(
            RawFunctionInfo(
                name=f.get("name", ""),
                qualified_name=f.get("qualified_name", f.get("name", "")),
                start_line=f.get("start_line", 0),
                end_line=f.get("end_line", 0),
                is_async=f.get("is_async", False),
                is_stub=f.get("is_stub", False),
                stub_reason=f.get("stub_reason"),
                has_docstring=f.get("has_docstring", False),
                docstring=f.get("docstring"),
                decorators=tuple(f.get("decorators", [])),
                args=tuple(f.get("args", [])),
                return_annotation=f.get("return_annotation"),
                body_start_line=f.get("body_start_line", f.get("start_line", 0)),
                body_line_count=f.get("body_line_count", 0),
            )
        )

    comments: list[RawCommentInfo] = []
    for c in data.get("comments", []):
        comments.append(
            RawCommentInfo(
                line=c.get("line", 0),
                col_offset=c.get("col_offset", 0),
                text=c.get("text", ""),
                raw=c.get("raw", ""),
                enclosing_function=c.get("enclosing_function"),
            )
        )

    return SourceAnalysis(functions=functions, comments=comments)


def analyze_source(
    content: str,
    filepath: str = "",
    *,
    workspace: Path | None = None,
) -> SourceAnalysis:
    """Analyze source code structure. Language-agnostic.

    Uses content-hash caching: if the same content has been analyzed
    before, returns the cached result without calling the LLM.

    Args:
        content: Source code as a string.
        filepath: Optional filepath for context (helps LLM infer language).
        workspace: Working directory for agent execution.

    Returns:
        SourceAnalysis with functions and comments.
    """
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    if content_hash in _analysis_cache:
        return _analysis_cache[content_hash]

    analyzer = _default_analyzer or _call_llm_analyzer
    result = analyzer(content, filepath, workspace)

    _analysis_cache[content_hash] = result
    return result
