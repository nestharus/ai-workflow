"""Call-graph extraction via unified adjacency signal inference.

This module intentionally acts as a thin wrapper over
``core.code_analysis.infer_adjacency_signals()``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spec_manager.core.code_analysis import SourceAnalysis, analyze_source, infer_adjacency_signals

if TYPE_CHECKING:
    from spec_manager.compliance.promotion.evidence_loader import AnalyzedFile


@dataclass
class StrategyRegistry:
    """Compatibility registry for call-graph extraction settings.

    The previous implementation supported many extraction strategies. The
    canonical behavior now is one path (adjacency signal inference), but this
    registry remains injectable so existing callers do not break.
    """

    call_graph_strategies: dict[str, Any] = field(default_factory=dict)
    parser_strategies: dict[str, Any] = field(default_factory=dict)
    strategy_matcher_agent: str = "pdd-code-analyzer"
    research_tool: Any = None
    min_edge_confidence: float = 0.0

    def clear(self) -> None:
        self.call_graph_strategies.clear()
        self.parser_strategies.clear()


@dataclass(frozen=True)
class CallGraphEdge:
    """One extracted call edge with provenance."""

    caller: str
    callee: str
    strategy: str
    surface: str
    confidence: float = 1.0
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class CallGraphBuildResult:
    """Aggregated extraction results from one signal-inference pass."""

    nodes: set[str] = field(default_factory=set)
    edges: list[CallGraphEdge] = field(default_factory=list)
    skipped_files: list[dict[str, Any]] = field(default_factory=list)
    unsupported_calls: list[dict[str, Any]] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)


_DEFAULT_REGISTRY = StrategyRegistry()


def _function_spans(analysis: SourceAnalysis) -> list[dict[str, Any]]:
    """Build span payload for adjacency inference from known functions."""
    spans: list[dict[str, Any]] = []
    for func in analysis.functions:
        spans.append(
            {
                "id": func.qualified_name or func.name,
                "line_start": func.start_line,
                "line_end": func.end_line,
                "kind": "function",
            }
        )
    return spans


def _normalize_call_edge(
    raw: dict[str, Any], *, file_path: Path
) -> tuple[CallGraphEdge | None, str | None]:
    """Normalize one inferred edge into a CallGraphEdge."""
    signal_type = str(raw.get("signal_type", "")).upper()
    if signal_type and signal_type != "CALL":
        return None, "non_call_signal"

    caller = str(raw.get("src_id", "")).strip()
    callee = str(raw.get("dst_id", "")).strip()
    if not caller or not callee:
        return None, "missing_endpoint"

    try:
        confidence = float(raw.get("confidence", 1.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    edge = CallGraphEdge(
        caller=caller,
        callee=callee,
        strategy="adjacency_signals",
        surface="CALL",
        confidence=confidence,
        evidence={
            "source_file": str(file_path),
            "rationale_span": raw.get("rationale_span"),
            "raw_evidence": raw.get("evidence", {}),
        },
    )
    return edge, None


def build_call_graph(
    algorithmic_files: list[Path],
    project_root: Path,
    analyzed: list[AnalyzedFile] | None = None,
    registry: StrategyRegistry | None = None,
) -> CallGraphBuildResult:
    """Build call graph from CALL adjacency signals.

    Edges are inferred from LLM-produced adjacency evidence rather than
    language-specific AST parsing.
    """
    registry = registry or _DEFAULT_REGISTRY
    analyzed_by_path: dict[str, AnalyzedFile] = {}
    if analyzed is not None:
        analyzed_by_path = {Path(item.path).resolve().as_posix(): item for item in analyzed}

    output = CallGraphBuildResult()
    seen_edge_keys: set[tuple[str, str, str, str]] = set()

    for file_path in algorithmic_files:
        resolved = file_path.resolve().as_posix()
        preloaded = analyzed_by_path.get(resolved)

        if preloaded is not None:
            source = preloaded.content
            analysis = preloaded.analysis
        else:
            try:
                source = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                output.skipped_files.append(
                    {
                        "path": str(file_path),
                        "reason": f"read_error:{type(exc).__name__}",
                    }
                )
                continue
            analysis = analyze_source(source, str(file_path))

        for func in analysis.functions:
            qn = (func.qualified_name or func.name).strip()
            if qn:
                output.nodes.add(qn)

        spans = _function_spans(analysis)
        inferred = infer_adjacency_signals(
            file_path=str(file_path),
            source_text=source,
            spans=spans,
            requested={"CALL"},
            workspace=project_root,
        )
        raw_edges = inferred.get("edges") if isinstance(inferred, dict) else []
        if not isinstance(raw_edges, list):
            raw_edges = []

        normalized_count = 0
        for raw_edge in raw_edges:
            if not isinstance(raw_edge, dict):
                output.unsupported_calls.append(
                    {
                        "file": str(file_path),
                        "reason": "non_dict_edge",
                    }
                )
                continue

            edge, error_reason = _normalize_call_edge(raw_edge, file_path=file_path)
            if edge is None:
                output.unsupported_calls.append(
                    {
                        "file": str(file_path),
                        "reason": error_reason or "normalize_failed",
                        "edge": raw_edge,
                    }
                )
                continue

            if edge.caller == edge.callee:
                continue
            if edge.confidence < registry.min_edge_confidence:
                output.unsupported_calls.append(
                    {
                        "file": str(file_path),
                        "reason": "below_min_confidence",
                        "caller": edge.caller,
                        "callee": edge.callee,
                        "confidence": edge.confidence,
                        "threshold": registry.min_edge_confidence,
                    }
                )
                continue

            key = (edge.caller, edge.callee, edge.strategy, edge.surface)
            if key in seen_edge_keys:
                continue
            seen_edge_keys.add(key)

            output.edges.append(edge)
            output.nodes.add(edge.caller)
            output.nodes.add(edge.callee)
            normalized_count += 1

        output.provenance.append(
            {
                "file": str(file_path),
                "strategy": "adjacency_signals",
                "requested": ["CALL"],
                "edge_count": normalized_count,
            }
        )

    return output
