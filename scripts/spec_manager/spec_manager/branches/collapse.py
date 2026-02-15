"""Brownfield ingestion router for Layer 1 routing artifacts.

This module ingests existing source code as span-routing decisions:
- candidate spans that can be pinned,
- initial PinFunction candidates and projection hints,
- adjacency edges with confidence,
- ambiguity questions for unresolved routing choices.
"""

from __future__ import annotations

import hashlib
import json
import logging
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spec_manager.core.code_analysis import (
    RawFunctionInfo,
    SourceAnalysis,
    analyze_source,
    build_candidate_spans,
    infer_adjacency_signals,
)
from spec_manager.core.json_extraction import _extract_json_payload
from spec_manager.refinement.formats import _strip_code_fences

from .layout import BranchLayout
from .types import AtomDescriptor, AtomKind

logger = logging.getLogger(__name__)

_ROUTING_SIGNAL_TYPES = frozenset({"CALL", "STORE_TOUCH", "EVENT_PUBLISH", "EVENT_SUBSCRIBE"})

_ROUTING_PROMPT_TEMPLATE = """\
You are routing brownfield code spans into a PDD graph.

Do not classify by AST categories. Route spans to graph decisions.

Return JSON only with this shape:
{{
  "pin_spans": [
    {{
      "span_id": "string",
      "pin_name": "string",
      "projection_hint": "string",
      "confidence": 0.0,
      "rationale": "string"
    }}
  ],
  "slice_entrypoints": [
    {{
      "span_id": "string",
      "slice_id": "string",
      "confidence": 0.0,
      "rationale": "string"
    }}
  ],
  "store_touches": [
    {{
      "span_id": "string",
      "store_id": "string",
      "operation": "read|write|read_write|unknown",
      "confidence": 0.0,
      "rationale": "string"
    }}
  ],
  "event_routes": [
    {{
      "span_id": "string",
      "event_name": "string",
      "mode": "publish|subscribe",
      "confidence": 0.0,
      "rationale": "string"
    }}
  ],
  "architecture_promotions": [
    {{
      "span_id": "string",
      "target_layer": "architecture|algorithmic",
      "confidence": 0.0,
      "rationale": "string"
    }}
  ],
  "adjacency_edges": [
    {{
      "signal_type": "CALL|STORE_TOUCH|EVENT_PUBLISH|EVENT_SUBSCRIBE",
      "src_id": "string",
      "dst_id": "string",
      "confidence": 0.0,
      "rationale_span": "string"
    }}
  ],
  "atom_candidates": [
    {{
      "span_id": "string",
      "kind": "algorithm|store|shape",
      "confidence": 0.0,
      "rationale": "string"
    }}
  ],
  "ambiguities": [
    {{
      "span_id": "string|null",
      "question": "string",
      "reason": "string"
    }}
  ]
}}

Rules:
- Use only provided span_ids.
- Prefer preserving source spans and routing metadata over summaries.
- If uncertain, add an ambiguity item instead of guessing.

File: {file_path}

Candidate spans:
{spans_json}

Inferred adjacency evidence:
{adjacency_json}

Source:
```
{source}
```
"""

_KIND_MAP: dict[str, AtomKind] = {
    "algorithm": AtomKind.ALGORITHM,
    "store": AtomKind.STORE,
    "shape": AtomKind.SHAPE,
}


@dataclass
class CollapseResult:
    """Result of routing brownfield code spans."""

    atom_candidates: list[AtomDescriptor]
    pin_spans: list[dict[str, Any]]
    slice_entrypoints: list[dict[str, Any]]
    store_touches: list[dict[str, Any]]
    event_routes: list[dict[str, Any]]
    architecture_promotions: list[dict[str, Any]]
    adjacency_edges: list[dict[str, Any]]
    ambiguities: list[dict[str, Any]]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "atom_candidates": [a.to_dict() for a in self.atom_candidates],
            "pin_spans": self.pin_spans,
            "slice_entrypoints": self.slice_entrypoints,
            "store_touches": self.store_touches,
            "event_routes": self.event_routes,
            "architecture_promotions": self.architecture_promotions,
            "adjacency_edges": self.adjacency_edges,
            "ambiguities": self.ambiguities,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CollapseResult:
        """Deserialize from dictionary."""
        atom_payload = data.get("atom_candidates", [])
        return cls(
            atom_candidates=[
                AtomDescriptor.from_dict(a) for a in atom_payload if isinstance(a, dict)
            ],
            pin_spans=_coerce_dict_list(data.get("pin_spans", [])),
            slice_entrypoints=_coerce_dict_list(data.get("slice_entrypoints", [])),
            store_touches=_coerce_dict_list(data.get("store_touches", [])),
            event_routes=_coerce_dict_list(data.get("event_routes", [])),
            architecture_promotions=_coerce_dict_list(data.get("architecture_promotions", [])),
            adjacency_edges=_coerce_dict_list(data.get("adjacency_edges", [])),
            ambiguities=_coerce_dict_list(data.get("ambiguities", [])),
            warnings=[str(item) for item in data.get("warnings", [])],
        )


class CollapseEngine:
    """Routes existing code spans into initial PDD graph artifacts."""

    def __init__(self, layout: BranchLayout) -> None:
        self._layout = layout

    def collapse(self, source_dir: Path) -> CollapseResult:
        """Route an existing codebase into brownfield routing outputs."""
        atom_candidates: list[AtomDescriptor] = []
        pin_spans: list[dict[str, Any]] = []
        slice_entrypoints: list[dict[str, Any]] = []
        store_touches: list[dict[str, Any]] = []
        event_routes: list[dict[str, Any]] = []
        architecture_promotions: list[dict[str, Any]] = []
        adjacency_edges: list[dict[str, Any]] = []
        ambiguities: list[dict[str, Any]] = []
        warnings: list[str] = []

        seen_atom_ids: set[str] = set()
        seen_adjacency: set[tuple[str, str, str]] = set()

        if not source_dir.exists():
            warnings.append(f"Source directory does not exist: {source_dir}")
            return CollapseResult(
                atom_candidates=atom_candidates,
                pin_spans=pin_spans,
                slice_entrypoints=slice_entrypoints,
                store_touches=store_touches,
                event_routes=event_routes,
                architecture_promotions=architecture_promotions,
                adjacency_edges=adjacency_edges,
                ambiguities=ambiguities,
                warnings=warnings,
            )

        from spec_manager.core.language import is_package_marker, source_rglob

        py_files = source_rglob(source_dir)
        if not py_files:
            warnings.append(f"No source files found in: {source_dir}")

        for py_file in py_files:
            if is_package_marker(py_file.name):
                continue

            try:
                source = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"Failed to read {py_file}: {exc}")
                continue

            rel_path = py_file.relative_to(source_dir).as_posix()
            analysis = analyze_source(source, filepath=str(py_file), workspace=source_dir)
            spans = build_candidate_spans(analysis, file_path=rel_path)
            function_by_span = _index_functions_by_span(analysis, rel_path)

            if not spans:
                # No routable spans in this file.
                continue

            inferred = infer_adjacency_signals(
                file_path=str(py_file),
                source_text=source,
                spans=spans,
                requested=set(_ROUTING_SIGNAL_TYPES),
                workspace=source_dir,
            )
            inferred_edges = _normalize_adjacency_edges(inferred.get("edges"))

            try:
                routed = _llm_route_spans(
                    file_path=rel_path,
                    source_text=source,
                    spans=spans,
                    inferred_edges=inferred_edges,
                    workspace=source_dir,
                )
            except Exception as exc:  # pragma: no cover - defensive LLM boundary
                warnings.append(f"Routing failed for {rel_path}: {exc}")
                ambiguities.append(
                    {
                        "span_id": None,
                        "question": f"How should spans in {rel_path} be routed?",
                        "reason": f"routing_error:{type(exc).__name__}",
                    }
                )
                routed = {}

            file_pin_spans = _with_file_context(
                _coerce_dict_list(routed.get("pin_spans", [])), rel_path
            )
            file_slice_entrypoints = _with_file_context(
                _coerce_dict_list(routed.get("slice_entrypoints", [])),
                rel_path,
            )
            file_store_touches = _with_file_context(
                _coerce_dict_list(routed.get("store_touches", [])),
                rel_path,
            )
            file_event_routes = _with_file_context(
                _coerce_dict_list(routed.get("event_routes", [])), rel_path
            )
            file_promotions = _with_file_context(
                _coerce_dict_list(routed.get("architecture_promotions", [])),
                rel_path,
            )
            file_ambiguities = _with_file_context(
                _coerce_dict_list(routed.get("ambiguities", [])), rel_path
            )
            routed_edges = _normalize_adjacency_edges(routed.get("adjacency_edges"))
            combined_edges = inferred_edges + routed_edges

            if not file_store_touches:
                file_store_touches = _derive_store_touches_from_edges(combined_edges, rel_path)
            if not file_event_routes:
                file_event_routes = _derive_event_routes_from_edges(combined_edges, rel_path)

            pin_spans.extend(file_pin_spans)
            slice_entrypoints.extend(file_slice_entrypoints)
            store_touches.extend(file_store_touches)
            event_routes.extend(file_event_routes)
            architecture_promotions.extend(file_promotions)
            ambiguities.extend(file_ambiguities)

            for edge in combined_edges:
                key = (
                    str(edge.get("signal_type", "")),
                    str(edge.get("src_id", "")),
                    str(edge.get("dst_id", "")),
                )
                if key in seen_adjacency:
                    continue
                seen_adjacency.add(key)
                adjacency_edges.append(edge)

            atom_payload = _coerce_dict_list(routed.get("atom_candidates", []))
            if not atom_payload and file_pin_spans:
                # Router omitted atom candidates; derive from pinned spans.
                atom_payload = [
                    {"span_id": item.get("span_id"), "kind": "algorithm"} for item in file_pin_spans
                ]

            for atom_data in atom_payload:
                descriptor = self._to_atom_descriptor(
                    atom_data=atom_data,
                    function_by_span=function_by_span,
                    file_path=rel_path,
                    source_text=source,
                    warnings=warnings,
                    ambiguities=ambiguities,
                )
                if descriptor is None:
                    continue
                if descriptor.atom_id in seen_atom_ids:
                    continue
                seen_atom_ids.add(descriptor.atom_id)
                atom_candidates.append(descriptor)

            if (
                not file_pin_spans
                and not file_slice_entrypoints
                and not file_store_touches
                and not file_event_routes
                and not file_promotions
                and not file_ambiguities
            ):
                ambiguities.append(
                    {
                        "file_path": rel_path,
                        "span_id": None,
                        "question": "Router returned no routing decisions for this file.",
                        "reason": "empty_router_output",
                    }
                )

        return CollapseResult(
            atom_candidates=atom_candidates,
            pin_spans=pin_spans,
            slice_entrypoints=slice_entrypoints,
            store_touches=store_touches,
            event_routes=event_routes,
            architecture_promotions=architecture_promotions,
            adjacency_edges=adjacency_edges,
            ambiguities=ambiguities,
            warnings=warnings,
        )

    def _to_atom_descriptor(
        self,
        *,
        atom_data: dict[str, Any],
        function_by_span: dict[str, RawFunctionInfo],
        file_path: str,
        source_text: str,
        warnings: list[str],
        ambiguities: list[dict[str, Any]],
    ) -> AtomDescriptor | None:
        """Build an atom descriptor for a routed function span."""
        span_id = str(atom_data.get("span_id") or "").strip()
        if not span_id:
            return None

        func_info = function_by_span.get(span_id)
        if func_info is None and ":" not in span_id:
            func_info = function_by_span.get(f"{file_path}:{span_id}")
            if func_info is not None:
                span_id = f"{file_path}:{span_id}"
        if func_info is None:
            ambiguities.append(
                {
                    "file_path": file_path,
                    "span_id": span_id,
                    "question": "Span was routed as atom candidate but is not a function span.",
                    "reason": "non_function_atom_candidate",
                }
            )
            return None

        kind_raw = str(atom_data.get("kind") or "algorithm").strip().lower()
        kind = _KIND_MAP.get(kind_raw)
        if kind is None:
            warnings.append(f"Unknown atom kind '{kind_raw}' for span '{span_id}'; skipping")
            return None

        return AtomDescriptor(
            atom_id=span_id,
            kind=kind,
            file_path=file_path,
            function_name=func_info.qualified_name or func_info.name,
            signature=_reconstruct_signature(func_info),
            content_hash=_compute_body_hash(func_info, source_text),
            introduced_by="collapse-routing",
        )


def _index_functions_by_span(
    analysis: SourceAnalysis, file_path: str
) -> dict[str, RawFunctionInfo]:
    """Index function spans by the span identifier emitted by build_candidate_spans."""
    indexed: dict[str, RawFunctionInfo] = {}
    for func in analysis.functions:
        span_name = (func.qualified_name or func.name).strip()
        if not span_name:
            continue
        span_id = f"{file_path}:{span_name}"
        indexed[span_id] = func
    return indexed


def _reconstruct_signature(func_info: RawFunctionInfo) -> str:
    """Reconstruct a function signature from RawFunctionInfo."""
    sig = f"({', '.join(func_info.args)})"
    if func_info.return_annotation:
        sig += f" -> {func_info.return_annotation}"
    return sig


def _compute_body_hash(func_info: RawFunctionInfo, source: str) -> str:
    """Compute SHA-256 hash of the function body source."""
    lines = source.splitlines()
    body_start = max(0, func_info.start_line - 1)
    body_end = min(len(lines), max(func_info.end_line, func_info.start_line))
    body_text = "\n".join(lines[body_start:body_end])
    body_text = textwrap.dedent(body_text).strip()
    return hashlib.sha256(body_text.encode("utf-8")).hexdigest()


def _llm_route_spans(
    *,
    file_path: str,
    source_text: str,
    spans: list[dict[str, Any]],
    inferred_edges: list[dict[str, Any]],
    workspace: Path,
) -> dict[str, Any]:
    """Route spans for one file via an LLM pass."""
    from spec_manager.core.agent_utils import run_agent

    prompt = _ROUTING_PROMPT_TEMPLATE.format(
        file_path=file_path,
        spans_json=json.dumps(spans, ensure_ascii=True),
        adjacency_json=json.dumps(inferred_edges, ensure_ascii=True),
        source=source_text,
    )
    raw_output = run_agent(
        agent_name="pdd-code-analyzer",
        prompt=prompt,
        workspace=workspace,
    )
    return _parse_json_dict(raw_output)


def _parse_json_dict(raw_output: str) -> dict[str, Any]:
    """Parse JSON dictionary from LLM output."""
    cleaned = _strip_code_fences(raw_output)
    try:
        loaded = json.loads(cleaned)
        if isinstance(loaded, dict):
            return loaded
    except (json.JSONDecodeError, ValueError):
        pass

    extracted = _extract_json_payload(cleaned)
    if extracted:
        loaded = json.loads(extracted)
        if isinstance(loaded, dict):
            return loaded

    logger.error("Failed to parse collapse routing output: %s", raw_output[:200])
    raise ValueError("invalid_routing_json")


def _coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    """Normalize a value to a list of dictionaries."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _with_file_context(rows: list[dict[str, Any]], file_path: str) -> list[dict[str, Any]]:
    """Attach file_path to rows that do not include it."""
    enriched: list[dict[str, Any]] = []
    for row in rows:
        if "file_path" not in row:
            item = dict(row)
            item["file_path"] = file_path
            enriched.append(item)
            continue
        enriched.append(dict(row))
    return enriched


def _normalize_adjacency_edges(value: Any) -> list[dict[str, Any]]:
    """Normalize adjacency edges to a stable structure."""
    normalized: list[dict[str, Any]] = []
    for edge in _coerce_dict_list(value):
        signal_type = str(edge.get("signal_type") or edge.get("type") or "").strip().upper()
        if not signal_type:
            continue
        if signal_type not in _ROUTING_SIGNAL_TYPES:
            continue

        src_id = str(edge.get("src_id") or edge.get("from") or edge.get("caller") or "").strip()
        dst_id = str(edge.get("dst_id") or edge.get("to") or edge.get("callee") or "").strip()
        if not src_id or not dst_id:
            continue

        try:
            confidence = float(edge.get("confidence", 1.0) or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0

        normalized.append(
            {
                "signal_type": signal_type,
                "src_id": src_id,
                "dst_id": dst_id,
                "confidence": max(0.0, min(1.0, confidence)),
                "rationale_span": edge.get("rationale_span"),
                "evidence": edge.get("evidence", {}),
            }
        )

    return normalized


def _derive_store_touches_from_edges(
    edges: list[dict[str, Any]], file_path: str
) -> list[dict[str, Any]]:
    """Derive store touch routing when router does not emit explicit entries."""
    derived: list[dict[str, Any]] = []
    for edge in edges:
        if str(edge.get("signal_type", "")).upper() != "STORE_TOUCH":
            continue
        derived.append(
            {
                "file_path": file_path,
                "span_id": edge.get("src_id"),
                "store_id": edge.get("dst_id"),
                "operation": "unknown",
                "confidence": edge.get("confidence", 0.0),
                "rationale": "derived_from_adjacency_signal",
            }
        )
    return derived


def _derive_event_routes_from_edges(
    edges: list[dict[str, Any]], file_path: str
) -> list[dict[str, Any]]:
    """Derive event pub/sub routing when router does not emit explicit entries."""
    derived: list[dict[str, Any]] = []
    for edge in edges:
        signal_type = str(edge.get("signal_type", "")).upper()
        if signal_type not in {"EVENT_PUBLISH", "EVENT_SUBSCRIBE"}:
            continue
        mode = "publish" if signal_type == "EVENT_PUBLISH" else "subscribe"
        derived.append(
            {
                "file_path": file_path,
                "span_id": edge.get("src_id"),
                "event_name": edge.get("dst_id"),
                "mode": mode,
                "confidence": edge.get("confidence", 0.0),
                "rationale": "derived_from_adjacency_signal",
            }
        )
    return derived
