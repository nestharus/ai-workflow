"""Language-agnostic source code analysis and signal inference via LLM.

This module provides:
- ``analyze_source()`` for stable structural analysis (functions/comments).
- ``infer_code_signals()`` for on-demand semantic facets (edges/signals).

Both paths use content-aware caching to avoid repeated LLM calls.
"""

from __future__ import annotations

import contextlib
import copy
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
    facets: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Cache: content-hash → SourceAnalysis
# ---------------------------------------------------------------------------

_analysis_cache: dict[str, SourceAnalysis] = {}
_signal_cache: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}


def clear_cache() -> None:
    """Clear the analysis cache (useful in tests)."""
    _analysis_cache.clear()
    _signal_cache.clear()


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------

# Default analyzer is set at module level to allow test injection
_default_analyzer: Callable[[str, str, Path | None], SourceAnalysis] | None = None
_default_signal_inferer: (
    Callable[[str, str, list[dict[str, Any]], set[str], Path | None], dict[str, Any]] | None
) = None


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


def _call_llm_signal_inferer(
    file_path: str,
    source_text: str,
    spans: list[dict[str, Any]],
    requested: set[str],
    workspace: Path | None,
) -> dict[str, Any]:
    """Call the code analyzer agent for request-driven signal facets."""
    from spec_manager.core.agent_utils import run_agent

    ws = workspace or Path.cwd()
    requested_list = sorted(requested)
    spans_json = json.dumps(spans, ensure_ascii=True)
    requested_json = json.dumps(requested_list, ensure_ascii=True)

    prompt_lines = [
        "Infer code signals for the requested facets and return JSON only.",
        "The response must be a JSON object keyed by requested facet names.",
        "",
        f"File: {file_path}",
        f"Requested facets: {requested_json}",
        f"Spans (optional): {spans_json}",
        "",
        "Source:",
        "```",
        source_text,
        "```",
    ]
    prompt = "\n".join(prompt_lines)

    raw_output = run_agent(
        agent_name="pdd-code-analyzer",
        prompt=prompt,
        workspace=ws,
    )

    return _parse_signals_response(raw_output)


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


def _parse_signals_response(raw_output: str) -> dict[str, Any]:
    """Parse signal-facet JSON from agent output."""
    cleaned = _strip_code_fences(raw_output)

    data: dict[str, Any] | None = None
    try:
        loaded = json.loads(cleaned)
        if isinstance(loaded, dict):
            data = loaded
    except (json.JSONDecodeError, ValueError):
        extracted = _extract_json_payload(cleaned)
        if extracted:
            with contextlib.suppress(json.JSONDecodeError, ValueError):
                loaded = json.loads(extracted)
                if isinstance(loaded, dict):
                    data = loaded

    if data is None:
        logger.error("Failed to parse code signal response: %s", raw_output[:200])
        return {}

    return data


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

    raw_facets = data.get("facets")
    facets = raw_facets if isinstance(raw_facets, dict) else {}
    return SourceAnalysis(functions=functions, comments=comments, facets=facets)


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


def infer_code_signals(
    *,
    file_path: str,
    source_text: str,
    spans: list[dict[str, Any]] | None = None,
    requested: set[str],
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Infer request-driven code signal facets for a source file.

    Cache key is ``(file_hash, requested_facets)`` so different facet requests
    for the same file are cached independently.
    """
    if not requested:
        return {}

    requested_key = tuple(sorted(requested))
    file_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    cache_key = (file_hash, requested_key)

    cached = _signal_cache.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)

    inferer = _default_signal_inferer or _call_llm_signal_inferer
    result = inferer(file_path, source_text, spans or [], requested, workspace)
    if not isinstance(result, dict):
        result = {}

    _signal_cache[cache_key] = copy.deepcopy(result)
    return result


def infer_adjacency_signals(
    *,
    file_path: str,
    source_text: str,
    spans: list[dict[str, Any]] | None = None,
    requested: set[str],
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Infer adjacency-style graph evidence for requested signal types.

    This is a thin contract over ``infer_code_signals()`` that normalizes the
    response into an ``edges`` list with ``signal_type/src_id/dst_id`` fields.
    """
    requested_upper = {item.strip().upper() for item in requested if item and item.strip()}
    if not requested_upper:
        return {"edges": [], "requested": []}

    raw = infer_code_signals(
        file_path=file_path,
        source_text=source_text,
        spans=spans,
        requested=requested_upper,
        workspace=workspace,
    )
    edges: list[dict[str, Any]] = []

    # Accept either per-signal payloads or a flat "edges" payload.
    for signal_type in requested_upper:
        payload = raw.get(signal_type) or raw.get(signal_type.lower())
        if isinstance(payload, dict):
            payload_edges = payload.get("edges")
            if isinstance(payload_edges, list):
                for entry in payload_edges:
                    if isinstance(entry, dict):
                        edges.append(dict(entry))
        elif isinstance(payload, list):
            for entry in payload:
                if isinstance(entry, dict):
                    edges.append(dict(entry))

    raw_edges = raw.get("edges")
    if isinstance(raw_edges, list):
        for entry in raw_edges:
            if isinstance(entry, dict):
                edges.append(dict(entry))

    normalized: list[dict[str, Any]] = []
    for edge in edges:
        signal_type = str(
            edge.get("signal_type")
            or edge.get("type")
            or edge.get("facet")
            or edge.get("kind")
            or ""
        ).strip()
        signal_type = signal_type.upper() if signal_type else ""
        if not signal_type:
            # If source payload was keyed by signal, preserve it when absent.
            signal_type = next(
                (
                    candidate
                    for candidate in requested_upper
                    if candidate in raw or candidate.lower() in raw
                ),
                "",
            )
        if signal_type and signal_type not in requested_upper:
            continue

        src_id = edge.get("src_id") or edge.get("caller") or edge.get("from")
        dst_id = edge.get("dst_id") or edge.get("callee") or edge.get("to")
        if not src_id or not dst_id:
            continue

        normalized.append(
            {
                "signal_type": signal_type,
                "src_id": str(src_id),
                "dst_id": str(dst_id),
                "confidence": float(edge.get("confidence", 1.0) or 0.0),
                "rationale_span": edge.get("rationale_span"),
                "evidence": edge.get("evidence", {}),
            }
        )

    return {
        "edges": normalized,
        "requested": sorted(requested_upper),
        "raw": raw,
    }
