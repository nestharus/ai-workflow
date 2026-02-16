"""Canonical language-agnostic source facts provider backed by LLM analysis.

This module exposes a unified ``FileFacts`` contract and thin projections:
- ``analyze_file_facts()`` returns canonical per-file facts for downstream stages.
- ``analyze_source()`` projects ``FileFacts`` to structural hints only.
- ``infer_code_signals()`` projects relationship facets from the same run cache.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec_manager.core.json_extraction import _extract_json_payload
from spec_manager.core.language import is_test_path, is_test_symbol
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


@dataclass
class FileFacts:
    """Canonical per-file facts consumed by downstream orchestration and gates."""

    file_path: str
    content_hash: str
    source_analysis: SourceAnalysis
    structure_hints: dict[str, Any] = field(default_factory=dict)
    gap_pins: list[dict[str, Any]] = field(default_factory=list)
    relationship_edges: list[dict[str, Any]] = field(default_factory=list)
    test_identity_hints: list[dict[str, Any]] = field(default_factory=list)
    functions: dict[str, Any] = field(default_factory=dict)
    stub_nodes: list[dict[str, Any]] = field(default_factory=list)
    call_graph_nodes: list[str] = field(default_factory=list)
    call_graph_edges: list[dict[str, Any]] = field(default_factory=list)
    stores: dict[str, Any] = field(default_factory=dict)
    store_owners: dict[str, list[str]] = field(default_factory=dict)


_COMMENT_GAP_EXCLUDED_PREFIXES: tuple[str, ...] = (
    "type: ignore",
    "noqa",
    "pragma",
    "fmt:",
    "pylint:",
    "mypy:",
    "pyright:",
    "ruff:",
    "isort:",
    "!",
    "-*- coding",
)
_RUN_SCOPE_DEFAULT = "__default__"
_CACHE_VERSION = "1"


# ---------------------------------------------------------------------------
# Run-scoped cache: (run_scope, content_hash[, requested_facets]) → payload
# ---------------------------------------------------------------------------

_analysis_cache: dict[tuple[str, str], SourceAnalysis] = {}
_signal_cache: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
_facts_cache: dict[tuple[str, str, tuple[str, ...]], FileFacts] = {}


def _normalize_run_scope(run_id: str | None) -> str:
    scope = str(run_id or "").strip()
    return scope or _RUN_SCOPE_DEFAULT


def _cache_dir(*, workspace: Path | None, run_scope: str) -> Path:
    ws = workspace or Path.cwd()
    if run_scope == _RUN_SCOPE_DEFAULT:
        return ws / ".pdd_cache" / "source_analysis"
    return ws / ".pdd_runs" / run_scope / "source_analysis_cache"


def _analysis_cache_file(cache_root: Path, content_hash: str) -> Path:
    return cache_root / f"{content_hash}.json"


def _facets_fingerprint(requested_key: tuple[str, ...]) -> str:
    joined = "|".join(requested_key)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _signals_cache_file(
    cache_root: Path, content_hash: str, requested_key: tuple[str, ...]
) -> Path:
    return cache_root / f"{content_hash}__signals__{_facets_fingerprint(requested_key)}.json"


def _facts_cache_file(cache_root: Path, content_hash: str, requested_key: tuple[str, ...]) -> Path:
    return cache_root / f"{content_hash}__facts__{_facets_fingerprint(requested_key)}.json"


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None
    return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        logger.debug("Failed writing code-analysis cache file: %s", path, exc_info=True)


def clear_cache(*, run_id: str | None = None, workspace: Path | None = None) -> None:
    """Clear in-memory cache and optional run-scoped on-disk cache."""
    run_scope = _normalize_run_scope(run_id)

    if run_id is None:
        _analysis_cache.clear()
        _signal_cache.clear()
        _facts_cache.clear()
        return

    _analysis_cache_keys = [key for key in _analysis_cache if key[0] == run_scope]
    for key in _analysis_cache_keys:
        del _analysis_cache[key]
    _signal_cache_keys = [key for key in _signal_cache if key[0] == run_scope]
    for key in _signal_cache_keys:
        del _signal_cache[key]
    _facts_cache_keys = [key for key in _facts_cache if key[0] == run_scope]
    for key in _facts_cache_keys:
        del _facts_cache[key]

    if workspace is not None:
        cache_root = _cache_dir(workspace=workspace, run_scope=run_scope)
        if cache_root.exists():
            with contextlib.suppress(OSError):
                shutil.rmtree(cache_root)


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
    run_id: str | None = None,
) -> SourceAnalysis:
    """Analyze source code structure. Language-agnostic.

    Uses run-scoped content-hash caching: if the same content has been analyzed
    in the same run scope, returns the cached result without calling the LLM.

    Args:
        content: Source code as a string.
        filepath: Optional filepath for context (helps LLM infer language).
        workspace: Working directory for agent execution.

    Returns:
        SourceAnalysis with functions and comments.
    """
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    run_scope = _normalize_run_scope(run_id)
    cache_key = (run_scope, content_hash)

    cached = _analysis_cache.get(cache_key)
    if cached is not None:
        return cached

    cache_root = _cache_dir(workspace=workspace, run_scope=run_scope)
    cache_path = _analysis_cache_file(cache_root, content_hash)
    cached_payload = _read_json(cache_path)
    if cached_payload is not None:
        cached_analysis = _dict_to_source_analysis(cached_payload)
        _analysis_cache[cache_key] = cached_analysis
        return cached_analysis

    analyzer = _default_analyzer or _call_llm_analyzer
    result = analyzer(content, filepath, workspace)

    _analysis_cache[cache_key] = result
    cache_payload = _source_analysis_to_dict(result)
    cache_payload["_version"] = _CACHE_VERSION
    cache_payload["_content_hash"] = content_hash
    _write_json(cache_path, cache_payload)
    return result


def build_candidate_spans(
    analysis: SourceAnalysis,
    *,
    file_path: str,
) -> list[dict[str, Any]]:
    """Build routing-oriented span payload from source analysis.

    Function spans are always included. If analysis facets provide
    ``logical_blocks`` entries, they are appended as additional candidate spans.
    """
    spans: list[dict[str, Any]] = []

    for func in analysis.functions:
        qualified_name = (func.qualified_name or func.name).strip()
        if not qualified_name:
            continue
        line_start = _coerce_span_line(func.start_line)
        if line_start <= 0:
            line_start = 1
        line_end = max(_coerce_span_line(func.end_line), line_start)
        spans.append(
            {
                "id": f"{file_path}:{qualified_name}",
                "file_path": file_path,
                "qualified_name": qualified_name,
                "kind": "function",
                "line_start": line_start,
                "line_end": line_end,
                "is_async": bool(func.is_async),
                "args": list(func.args),
                "return_annotation": func.return_annotation,
            }
        )

    raw_blocks = analysis.facets.get("logical_blocks")
    if isinstance(raw_blocks, list):
        for idx, block in enumerate(raw_blocks):
            if not isinstance(block, dict):
                continue

            line_start = _coerce_span_line(
                block.get("line_start") or block.get("start_line") or block.get("start")
            )
            line_end = _coerce_span_line(
                block.get("line_end") or block.get("end_line") or block.get("end")
            )
            if line_start <= 0:
                continue
            if line_end < line_start:
                line_end = line_start

            block_id = str(block.get("id") or block.get("block_id") or f"block_{idx + 1}").strip()
            if not block_id:
                continue

            spans.append(
                {
                    "id": f"{file_path}:{block_id}",
                    "file_path": file_path,
                    "kind": str(block.get("kind") or "logical_block"),
                    "line_start": line_start,
                    "line_end": line_end,
                    "label": block.get("label"),
                }
            )

    return spans


def infer_code_signals(
    *,
    file_path: str,
    source_text: str,
    spans: list[dict[str, Any]] | None = None,
    requested: set[str],
    workspace: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Infer request-driven code signal facets for a source file.

    Cache key is ``(file_hash, requested_facets)`` so different facet requests
    for the same file are cached independently.
    """
    if not requested:
        return {}

    requested_key = tuple(sorted(requested))
    file_hash = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    run_scope = _normalize_run_scope(run_id)
    cache_key = (run_scope, file_hash, requested_key)

    cached = _signal_cache.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)

    cache_root = _cache_dir(workspace=workspace, run_scope=run_scope)
    cache_path = _signals_cache_file(cache_root, file_hash, requested_key)
    cached_payload = _read_json(cache_path)
    if cached_payload is not None:
        cached_data = cached_payload.get("signals")
        if isinstance(cached_data, dict):
            _signal_cache[cache_key] = copy.deepcopy(cached_data)
            return copy.deepcopy(cached_data)

    inferer = _default_signal_inferer or _call_llm_signal_inferer
    result = inferer(file_path, source_text, spans or [], requested, workspace)
    if not isinstance(result, dict):
        result = {}

    _signal_cache[cache_key] = copy.deepcopy(result)
    _write_json(
        cache_path,
        {
            "_version": _CACHE_VERSION,
            "_content_hash": file_hash,
            "_requested": list(requested_key),
            "signals": copy.deepcopy(result),
        },
    )
    return result


def _source_analysis_to_dict(analysis: SourceAnalysis) -> dict[str, Any]:
    """Serialize SourceAnalysis to JSON-compatible primitives."""
    functions = []
    for f in analysis.functions:
        functions.append(
            {
                "name": f.name,
                "qualified_name": f.qualified_name,
                "start_line": f.start_line,
                "end_line": f.end_line,
                "is_async": f.is_async,
                "is_stub": f.is_stub,
                "stub_reason": f.stub_reason,
                "has_docstring": f.has_docstring,
                "docstring": f.docstring,
                "decorators": list(f.decorators),
                "args": list(f.args),
                "return_annotation": f.return_annotation,
                "body_start_line": f.body_start_line,
                "body_line_count": f.body_line_count,
            }
        )

    comments = []
    for c in analysis.comments:
        comments.append(
            {
                "line": c.line,
                "col_offset": c.col_offset,
                "text": c.text,
                "raw": c.raw,
                "enclosing_function": c.enclosing_function,
            }
        )
    return {
        "functions": functions,
        "comments": comments,
        "facets": copy.deepcopy(analysis.facets),
    }


def _canonical_signal(value: Any) -> str:
    if not isinstance(value, str):
        return "REFERENCE"
    signal = value.strip().upper()
    if signal in {"CALL", "CALLS"}:
        return "CALL"
    if signal in {"STORE_TOUCH", "AGGREGATION"}:
        return "STORE_TOUCH"
    if signal in {"EVENT", "EVENT_EMIT", "EVENT_HANDLE"}:
        return "EVENT"
    return "REFERENCE"


def _map_stub_reason(reason: str | None) -> str:
    if reason is None:
        return "pass"
    lower = reason.lower()
    if "ellipsis" in lower or reason == "...":
        return "ellipsis"
    compact = lower.replace(" ", "").replace("_", "")
    if "notimplemented" in compact:
        return "not_implemented"
    return "pass"


def _append_unique(records: list[dict[str, Any]], candidate: dict[str, Any]) -> None:
    fingerprint = json.dumps(candidate, sort_keys=True)
    for existing in records:
        if json.dumps(existing, sort_keys=True) == fingerprint:
            return
    records.append(candidate)


def _comment_is_excluded(comment_text: str) -> bool:
    lowered = comment_text.lower()
    return any(lowered.startswith(prefix.lower()) for prefix in _COMMENT_GAP_EXCLUDED_PREFIXES)


def _extract_relationship_edges_from_facets(facets: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect relationship edges from analyzer facets without re-parsing source."""
    collected: list[dict[str, Any]] = []
    if not isinstance(facets, dict):
        return collected

    direct_edges = facets.get("edges")
    if isinstance(direct_edges, list):
        for edge in direct_edges:
            if isinstance(edge, dict):
                collected.append(dict(edge))

    keyed = {
        "call_edges": "CALL",
        "event_edges": "EVENT",
        "store_edges": "STORE_TOUCH",
        "import_edges": "REFERENCE",
        "relationship_edges": "REFERENCE",
    }
    for key, signal in keyed.items():
        payload = facets.get(key)
        if isinstance(payload, list):
            for edge in payload:
                if isinstance(edge, dict):
                    enriched = dict(edge)
                    enriched.setdefault("signal_type", signal)
                    collected.append(enriched)
        elif isinstance(payload, dict):
            payload_edges = payload.get("edges")
            if isinstance(payload_edges, list):
                for edge in payload_edges:
                    if isinstance(edge, dict):
                        enriched = dict(edge)
                        enriched.setdefault("signal_type", signal)
                        collected.append(enriched)
    return collected


def _normalize_relationship_edges(raw_edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for edge in raw_edges:
        if not isinstance(edge, dict):
            continue
        src_id = edge.get("src_id") or edge.get("src") or edge.get("caller") or edge.get("from")
        dst_id = (
            edge.get("dst_id")
            or edge.get("dst")
            or edge.get("callee")
            or edge.get("to")
            or edge.get("store_id")
        )
        if not src_id or not dst_id:
            continue
        normalized.append(
            {
                "signal_type": _canonical_signal(
                    edge.get("signal_type")
                    or edge.get("type")
                    or edge.get("facet")
                    or edge.get("kind")
                ),
                "src_id": str(src_id).strip(),
                "dst_id": str(dst_id).strip(),
                "confidence": float(edge.get("confidence", 1.0) or 0.0),
                "rationale_span": edge.get("rationale_span"),
                "evidence": edge.get("evidence", {}),
            }
        )

    deduped: list[dict[str, Any]] = []
    for edge in normalized:
        _append_unique(deduped, edge)
    return deduped


def _build_function_facts(*, file_path: str, analysis: SourceAnalysis) -> dict[str, Any]:
    functions: dict[str, Any] = {}
    for fn in analysis.functions:
        qualified_name = (fn.qualified_name or fn.name).strip()
        if not qualified_name:
            continue
        functions[qualified_name] = {
            "signature": {
                "name": fn.name,
                "args": list(fn.args),
                "return_annotation": fn.return_annotation,
                "is_async": bool(fn.is_async),
            },
            "doc": fn.docstring or "",
            "file": file_path,
            "lines": [fn.start_line, fn.end_line],
        }
    return functions


def _build_gap_pins(
    *,
    file_path: str,
    source_text: str,
    analysis: SourceAnalysis,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build canonical gap pins + stub nodes directly from canonical analysis."""
    source_lines = source_text.splitlines()
    gap_pins: list[dict[str, Any]] = []
    stub_nodes: list[dict[str, Any]] = []

    for comment in analysis.comments:
        if comment.raw.startswith("#!") and comment.line <= 2:
            continue
        text = str(comment.text or "").strip()
        if not text or _comment_is_excluded(text):
            continue
        is_inline = False
        if 0 < comment.line <= len(source_lines):
            line_text = source_lines[comment.line - 1]
            before_comment = line_text[: comment.col_offset].strip()
            if before_comment:
                is_inline = True
        span = {
            "start_line": comment.line,
            "end_line": comment.line,
            "start_col": comment.col_offset,
            "end_col": max(comment.col_offset + len(comment.raw or text), comment.col_offset),
        }
        gap_pins.append(
            {
                "pin_id": f"{file_path}:comment:{comment.line}:{comment.col_offset}",
                "kind": "comment_gap",
                "file": file_path,
                "description": text,
                "span": span,
                "location": {"file": file_path, **span},
                "enclosing_function": comment.enclosing_function,
                "is_inline": is_inline,
            }
        )

    for fn in analysis.functions:
        if not fn.is_stub:
            continue
        qualified_name = (fn.qualified_name or fn.name).strip()
        span = {
            "start_line": fn.start_line,
            "end_line": fn.end_line,
            "start_col": 0,
            "end_col": 0,
        }
        stub_type = _map_stub_reason(fn.stub_reason)
        gap_pins.append(
            {
                "pin_id": f"{file_path}:{qualified_name or fn.name}:stub",
                "kind": "stub_gap",
                "file": file_path,
                "description": f"Stub function: {qualified_name or fn.name} ({stub_type})",
                "span": span,
                "location": {"file": file_path, **span},
                "stub_type": stub_type,
            }
        )
        stub_nodes.append(
            {
                "node_id": qualified_name or fn.name,
                "file_path": file_path,
                "line": fn.start_line,
                "stub_type": fn.stub_reason or "analysis_stub",
            }
        )

    return gap_pins, stub_nodes


def _build_test_identity_hints(*, file_path: str, analysis: SourceAnalysis) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    file_looks_like_test = is_test_path(file_path)
    if file_looks_like_test:
        hints.append({"kind": "test_file", "file": file_path})

    for fn in analysis.functions:
        name = (fn.name or "").strip()
        qualified = (fn.qualified_name or fn.name or "").strip()
        if is_test_symbol(name, qualified):
            hints.append(
                {
                    "kind": "test_function",
                    "file": file_path,
                    "qualified_name": qualified,
                    "start_line": fn.start_line,
                    "end_line": fn.end_line,
                }
            )
    return hints


def _build_store_and_graph_facts(
    relationship_edges: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any], dict[str, list[str]]]:
    call_graph_nodes: set[str] = set()
    call_graph_edges: list[dict[str, Any]] = []
    stores: dict[str, Any] = {}
    store_owners: dict[str, list[str]] = {}

    for edge in relationship_edges:
        signal_type = _canonical_signal(edge.get("signal_type"))
        src = str(edge.get("src_id", "")).strip()
        dst = str(edge.get("dst_id", "")).strip()
        if signal_type == "CALL" and src and dst:
            call_graph_nodes.update({src, dst})
            _append_unique(
                call_graph_edges,
                {
                    "src": src,
                    "dst": dst,
                    "signal_type": "CALL",
                    "confidence": edge.get("confidence", 1.0),
                },
            )
        if signal_type != "STORE_TOUCH" or not dst:
            continue
        owners = []
        if src:
            owners.append(src)
        existing = stores.get(dst, {})
        previous = existing.get("owner_atoms", []) if isinstance(existing, dict) else []
        merged_owners = sorted(set(previous + owners))
        stores[dst] = {"owner_atoms": merged_owners, "schema": existing.get("schema", {})}
        current = set(store_owners.get(dst, []))
        current.update(owners)
        store_owners[dst] = sorted(owner for owner in current if owner)

    return sorted(call_graph_nodes), call_graph_edges, stores, store_owners


def _file_facts_to_dict(facts: FileFacts) -> dict[str, Any]:
    return {
        "file_path": facts.file_path,
        "content_hash": facts.content_hash,
        "source_analysis": _source_analysis_to_dict(facts.source_analysis),
        "structure_hints": copy.deepcopy(facts.structure_hints),
        "gap_pins": copy.deepcopy(facts.gap_pins),
        "relationship_edges": copy.deepcopy(facts.relationship_edges),
        "test_identity_hints": copy.deepcopy(facts.test_identity_hints),
        "functions": copy.deepcopy(facts.functions),
        "stub_nodes": copy.deepcopy(facts.stub_nodes),
        "call_graph_nodes": copy.deepcopy(facts.call_graph_nodes),
        "call_graph_edges": copy.deepcopy(facts.call_graph_edges),
        "stores": copy.deepcopy(facts.stores),
        "store_owners": copy.deepcopy(facts.store_owners),
    }


def _dict_to_file_facts(data: dict[str, Any]) -> FileFacts:
    source_payload = data.get("source_analysis")
    analysis = (
        _dict_to_source_analysis(source_payload)
        if isinstance(source_payload, dict)
        else _dict_to_source_analysis(data)
    )
    return FileFacts(
        file_path=str(data.get("file_path", "")),
        content_hash=str(data.get("content_hash", "")),
        source_analysis=analysis,
        structure_hints=(
            copy.deepcopy(data.get("structure_hints"))
            if isinstance(data.get("structure_hints"), dict)
            else {}
        ),
        gap_pins=[item for item in data.get("gap_pins", []) if isinstance(item, dict)],
        relationship_edges=[
            item for item in data.get("relationship_edges", []) if isinstance(item, dict)
        ],
        test_identity_hints=[
            item for item in data.get("test_identity_hints", []) if isinstance(item, dict)
        ],
        functions=copy.deepcopy(data.get("functions"))
        if isinstance(data.get("functions"), dict)
        else {},
        stub_nodes=[item for item in data.get("stub_nodes", []) if isinstance(item, dict)],
        call_graph_nodes=[
            str(item).strip() for item in data.get("call_graph_nodes", []) if str(item).strip()
        ],
        call_graph_edges=[
            item for item in data.get("call_graph_edges", []) if isinstance(item, dict)
        ],
        stores=copy.deepcopy(data.get("stores")) if isinstance(data.get("stores"), dict) else {},
        store_owners=(
            {
                str(store_id).strip(): [
                    str(owner).strip()
                    for owner in owners
                    if isinstance(owner, str) and str(owner).strip()
                ]
                for store_id, owners in data.get("store_owners", {}).items()
                if str(store_id).strip() and isinstance(owners, list)
            }
            if isinstance(data.get("store_owners"), dict)
            else {}
        ),
    )


def analyze_file_facts(
    content: str,
    filepath: str = "",
    *,
    requested_relationship_facets: set[str] | None = None,
    workspace: Path | None = None,
    run_id: str | None = None,
) -> FileFacts:
    """Return the canonical FileFacts projection for one source file."""
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    run_scope = _normalize_run_scope(run_id)
    requested_key = tuple(
        sorted(
            str(item).strip().upper()
            for item in (requested_relationship_facets or set())
            if str(item).strip()
        )
    )
    cache_key = (run_scope, content_hash, requested_key)

    cached = _facts_cache.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)

    cache_root = _cache_dir(workspace=workspace, run_scope=run_scope)
    cache_path = _facts_cache_file(cache_root, content_hash, requested_key)
    cached_payload = _read_json(cache_path)
    if cached_payload is not None:
        file_facts_payload = cached_payload.get("file_facts")
        if isinstance(file_facts_payload, dict):
            cached_facts = _dict_to_file_facts(file_facts_payload)
            _facts_cache[cache_key] = cached_facts
            return copy.deepcopy(cached_facts)

    analysis = analyze_source(content, filepath, workspace=workspace, run_id=run_id)
    spans = build_candidate_spans(analysis, file_path=filepath)
    raw_edges = _extract_relationship_edges_from_facets(analysis.facets)
    if requested_key:
        inferred = infer_adjacency_signals(
            file_path=filepath,
            source_text=content,
            spans=spans,
            requested=set(requested_key),
            workspace=workspace,
            run_id=run_id,
        )
        for edge in inferred.get("edges", []):
            if isinstance(edge, dict):
                raw_edges.append(edge)
    relationship_edges = _normalize_relationship_edges(raw_edges)

    gap_pins, stub_nodes = _build_gap_pins(
        file_path=filepath, source_text=content, analysis=analysis
    )
    functions = _build_function_facts(file_path=filepath, analysis=analysis)
    call_graph_nodes, call_graph_edges, stores, store_owners = _build_store_and_graph_facts(
        relationship_edges
    )
    test_identity_hints = _build_test_identity_hints(file_path=filepath, analysis=analysis)

    logical_blocks = analysis.facets.get("logical_blocks")
    structure_hints = {
        "function_count": len(analysis.functions),
        "comment_count": len(analysis.comments),
        "spans": spans,
        "logical_blocks": logical_blocks if isinstance(logical_blocks, list) else [],
    }

    file_facts = FileFacts(
        file_path=filepath,
        content_hash=content_hash,
        source_analysis=analysis,
        structure_hints=structure_hints,
        gap_pins=gap_pins,
        relationship_edges=relationship_edges,
        test_identity_hints=test_identity_hints,
        functions=functions,
        stub_nodes=stub_nodes,
        call_graph_nodes=call_graph_nodes,
        call_graph_edges=call_graph_edges,
        stores=stores,
        store_owners=store_owners,
    )
    _facts_cache[cache_key] = copy.deepcopy(file_facts)
    _write_json(
        cache_path,
        {
            "_version": _CACHE_VERSION,
            "_content_hash": content_hash,
            "_requested_relationship_facets": list(requested_key),
            "file_facts": _file_facts_to_dict(file_facts),
        },
    )
    return file_facts


def _coerce_span_line(value: Any) -> int:
    """Best-effort integer conversion for span lines."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def infer_adjacency_signals(
    *,
    file_path: str,
    source_text: str,
    spans: list[dict[str, Any]] | None = None,
    requested: set[str],
    workspace: Path | None = None,
    run_id: str | None = None,
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
        run_id=run_id,
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
