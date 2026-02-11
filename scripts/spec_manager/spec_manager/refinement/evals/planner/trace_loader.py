"""Load planner traces from disk for evaluation.

Reads the ``analysis/planner_traces/`` directory tree produced by the
planner instrumentation layer.  Provides dataclasses for the index and
full trace, plus filtering and aggregation helpers.

Directory layout::

    workspace_root/analysis/planner_traces/
        index.jsonl
        {trace_id}/
            request.json
            decision.json
            calls/
                model_calls.jsonl
                tool_calls.jsonl
            artifacts/
                *.json
            replay.json
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Dataclasses
# ------------------------------------------------------------------


@dataclass
class TraceEntry:
    """One row from ``index.jsonl``.

    Attributes:
        trace_id: Unique identifier for the trace.
        timestamp: ISO-8601 timestamp of the trace.
        run_id: Pipeline run identifier.
        model_id: Model used for the decision.
        slice_id: Slice (library/component/file) identifier.
        layer: Layer tag (``l1``, ``l2``, ``l3``).
        capability: Planner capability name (e.g. ``PLAN``).
        decision_key: Composite key for the decision.
        status: Decision status (``OK``, ``ERROR``, etc.).
        overridden: Whether the decision was overridden.
        model_calls_count: Number of LLM calls made.
        tool_calls_count: Number of tool calls made.
    """

    trace_id: str = ""
    timestamp: str = ""
    run_id: str = ""
    model_id: str = ""
    slice_id: str = ""
    layer: str = ""
    capability: str = ""
    decision_key: str = ""
    status: str = ""
    overridden: bool = False
    model_calls_count: int = 0
    tool_calls_count: int = 0


@dataclass
class LoadedTrace:
    """Full trace loaded from disk.

    Attributes:
        trace_id: Unique identifier for the trace.
        decision_key: Composite key for the decision.
        request: Deserialized ``request.json`` content.
        decision: Deserialized ``decision.json`` content.
        model_calls: List of model call records from ``model_calls.jsonl``.
        tool_calls: List of tool call records from ``tool_calls.jsonl``.
        artifacts: Mapping of artifact name to deserialized content.
        status: Decision status string.
        overridden: Whether the decision was overridden.
    """

    trace_id: str = ""
    decision_key: str = ""
    request: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    status: str = ""
    overridden: bool = False


# ------------------------------------------------------------------
# Path helpers
# ------------------------------------------------------------------


def _traces_dir(workspace_root: Path) -> Path:
    """Return the planner traces directory."""
    return workspace_root / "analysis" / "planner_traces"


# ------------------------------------------------------------------
# JSONL helpers
# ------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file, skipping malformed lines.

    Returns an empty list when the file does not exist.
    """
    if not path.exists():
        return []

    results: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        return []

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                results.append(obj)
            else:
                logger.debug(
                    "Skipping non-dict line %d in %s", lineno, path
                )
        except json.JSONDecodeError:
            logger.debug(
                "Skipping malformed JSON at line %d in %s", lineno, path
            )
    return results


def _read_json(path: Path) -> dict[str, Any]:
    """Read a single JSON file, returning an empty dict on failure."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Cannot read %s: %s", path, exc)
        return {}


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def load_index(workspace_root: Path) -> list[TraceEntry]:
    """Read ``index.jsonl`` and return a list of :class:`TraceEntry`.

    Malformed lines are silently skipped (logged at DEBUG level).

    Args:
        workspace_root: Root of the PDD workspace.

    Returns:
        List of trace entries, one per valid index line.
    """
    index_path = _traces_dir(workspace_root) / "index.jsonl"
    rows = _read_jsonl(index_path)

    entries: list[TraceEntry] = []
    for row in rows:
        try:
            entries.append(
                TraceEntry(
                    trace_id=row.get("trace_id", ""),
                    timestamp=row.get("timestamp", ""),
                    run_id=row.get("run_id", ""),
                    model_id=row.get("model_id", ""),
                    slice_id=row.get("slice_id", ""),
                    layer=row.get("layer", ""),
                    capability=row.get("capability", ""),
                    decision_key=row.get("decision_key", ""),
                    status=row.get("status", ""),
                    overridden=bool(row.get("overridden", False)),
                    model_calls_count=int(row.get("model_calls_count", 0)),
                    tool_calls_count=int(row.get("tool_calls_count", 0)),
                )
            )
        except (TypeError, ValueError) as exc:
            logger.debug("Skipping malformed index entry: %s", exc)

    return entries


def load_trace(workspace_root: Path, trace_id: str) -> LoadedTrace:
    """Load a full trace from disk.

    Reads ``request.json``, ``decision.json``, call logs, and all
    artifact files for the given *trace_id*.

    Args:
        workspace_root: Root of the PDD workspace.
        trace_id: The trace identifier (directory name).

    Returns:
        A fully populated :class:`LoadedTrace`.

    Raises:
        FileNotFoundError: If the trace directory does not exist.
    """
    trace_dir = _traces_dir(workspace_root) / trace_id
    if not trace_dir.is_dir():
        raise FileNotFoundError(
            f"Trace directory not found: {trace_dir}"
        )

    request = _read_json(trace_dir / "request.json")
    decision = _read_json(trace_dir / "decision.json")

    # Call logs
    calls_dir = trace_dir / "calls"
    model_calls = _read_jsonl(calls_dir / "model_calls.jsonl")
    tool_calls = _read_jsonl(calls_dir / "tool_calls.jsonl")

    # Artifacts
    artifacts: dict[str, Any] = {}
    artifacts_dir = trace_dir / "artifacts"
    if artifacts_dir.is_dir():
        for artifact_path in sorted(artifacts_dir.iterdir()):
            if artifact_path.suffix == ".json" and artifact_path.is_file():
                name = artifact_path.stem
                artifacts[name] = _read_json(artifact_path)

    return LoadedTrace(
        trace_id=trace_id,
        decision_key=decision.get("decision_key", ""),
        request=request,
        decision=decision,
        model_calls=model_calls,
        tool_calls=tool_calls,
        artifacts=artifacts,
        status=decision.get("status", ""),
        overridden=bool(decision.get("overridden", False)),
    )


def filter_traces(
    entries: list[TraceEntry],
    *,
    run_id: str | None = None,
    slice_id: str | None = None,
    layer: str | None = None,
    capability: str | None = None,
) -> list[TraceEntry]:
    """Filter trace entries by optional criteria.

    All supplied criteria are ANDed together.  ``None`` means "don't
    filter on this field".

    Args:
        entries: Trace entries to filter.
        run_id: If set, keep only entries with this run_id.
        slice_id: If set, keep only entries with this slice_id.
        layer: If set, keep only entries with this layer.
        capability: If set, keep only entries with this capability.

    Returns:
        Filtered list of trace entries.
    """
    result: list[TraceEntry] = []
    for entry in entries:
        if run_id is not None and entry.run_id != run_id:
            continue
        if slice_id is not None and entry.slice_id != slice_id:
            continue
        if layer is not None and entry.layer != layer:
            continue
        if capability is not None and entry.capability != capability:
            continue
        result.append(entry)
    return result


def load_traces_for_run(
    workspace_root: Path, run_id: str
) -> list[LoadedTrace]:
    """Load all traces for a given run.

    Convenience function: reads the index, filters by *run_id*, and
    loads each matching trace.  Traces that fail to load are skipped
    with a warning.

    Args:
        workspace_root: Root of the PDD workspace.
        run_id: Pipeline run identifier to filter on.

    Returns:
        List of loaded traces for the run.
    """
    entries = load_index(workspace_root)
    filtered = filter_traces(entries, run_id=run_id)

    traces: list[LoadedTrace] = []
    for entry in filtered:
        try:
            traces.append(load_trace(workspace_root, entry.trace_id))
        except (FileNotFoundError, OSError) as exc:
            logger.warning(
                "Skipping trace %s: %s", entry.trace_id, exc
            )
    return traces


def trace_stats(traces: list[LoadedTrace]) -> dict[str, Any]:
    """Compute aggregate statistics over a list of loaded traces.

    Returns a dict with keys:

    - ``total_traces``: Total number of traces.
    - ``by_capability``: ``{capability: count}`` from decision_key.
    - ``by_layer``: ``{layer: count}`` from decision_key.
    - ``by_status``: ``{status: count}``.
    - ``model_calls_total``: Sum of all model calls across traces.
    - ``tool_calls_total``: Sum of all tool calls across traces.
    - ``error_count``: Number of traces with non-OK status.
    - ``overridden_count``: Number of overridden traces.
    """
    by_capability: dict[str, int] = {}
    by_layer: dict[str, int] = {}
    by_status: dict[str, int] = {}
    model_calls_total = 0
    tool_calls_total = 0
    error_count = 0
    overridden_count = 0

    for trace in traces:
        # Extract capability and layer from decision_key
        # Format: "layer:capability:slice_id:iteration:hash"
        parts = trace.decision_key.split(":") if trace.decision_key else []
        layer = parts[0] if len(parts) > 0 else "unknown"
        capability = parts[1] if len(parts) > 1 else "unknown"

        by_capability[capability] = by_capability.get(capability, 0) + 1
        by_layer[layer] = by_layer.get(layer, 0) + 1
        by_status[trace.status] = by_status.get(trace.status, 0) + 1

        model_calls_total += len(trace.model_calls)
        tool_calls_total += len(trace.tool_calls)

        if trace.status and trace.status != "OK":
            error_count += 1
        if trace.overridden:
            overridden_count += 1

    return {
        "total_traces": len(traces),
        "by_capability": by_capability,
        "by_layer": by_layer,
        "by_status": by_status,
        "model_calls_total": model_calls_total,
        "tool_calls_total": tool_calls_total,
        "error_count": error_count,
        "overridden_count": overridden_count,
    }
