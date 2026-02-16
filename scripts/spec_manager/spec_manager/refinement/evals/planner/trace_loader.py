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
        planner_version: Planner implementation version.
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
    planner_version: str = ""
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
    request_path: str = ""
    decision_path: str = ""
    request_exists: bool = False
    decision_exists: bool = False
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    replay: dict[str, Any] = field(default_factory=dict)
    status: str = ""
    overridden: bool = False
    planner_version: str = ""
    load_issues: list[str] = field(default_factory=list)


@dataclass
class TraceLoadDiagnostics:
    """Aggregated diagnostics collected while loading planner traces."""

    issues: list[str] = field(default_factory=list)

    def record(self, issue: str) -> None:
        self.issues.append(issue)

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_count": len(self.issues),
            "issues": list(self.issues),
        }


# ------------------------------------------------------------------
# Path helpers
# ------------------------------------------------------------------


def _traces_dir(workspace_root: Path) -> Path:
    """Return the planner traces directory."""
    return workspace_root / "analysis" / "planner_traces"


def trace_dir(workspace_root: Path, trace_id: str) -> Path:
    """Return a single trace directory path."""
    return _traces_dir(workspace_root) / trace_id


# ------------------------------------------------------------------
# JSONL helpers
# ------------------------------------------------------------------


def _record_issue(
    issue: str,
    *,
    issues: list[str] | None = None,
    diagnostics: TraceLoadDiagnostics | None = None,
) -> None:
    if issues is not None:
        issues.append(issue)
    if diagnostics is not None:
        diagnostics.record(issue)


def _read_jsonl(
    path: Path,
    *,
    issues: list[str] | None = None,
    diagnostics: TraceLoadDiagnostics | None = None,
) -> list[dict[str, Any]]:
    """Read a JSONL file, recording malformed lines as diagnostics.

    Returns an empty list when the file does not exist.
    """
    if not path.exists():
        return []

    results: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        issue = f"unreadable:{path}:{exc}"
        logger.warning("Cannot read %s: %s", path, exc)
        _record_issue(issue, issues=issues, diagnostics=diagnostics)
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
                issue = f"non_dict_jsonl:{path}:{lineno}"
                logger.warning("Skipping non-dict line %d in %s", lineno, path)
                _record_issue(issue, issues=issues, diagnostics=diagnostics)
        except json.JSONDecodeError as exc:
            issue = f"invalid_jsonl:{path}:{lineno}:{exc}"
            logger.warning("Skipping malformed JSON at line %d in %s", lineno, path)
            _record_issue(issue, issues=issues, diagnostics=diagnostics)
    return results


def _read_json(
    path: Path,
    *,
    issues: list[str] | None = None,
    diagnostics: TraceLoadDiagnostics | None = None,
) -> dict[str, Any]:
    """Read a single JSON file, returning an empty dict on failure."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        issue = f"non_object_json:{path}"
        logger.warning("Cannot use %s: top-level JSON value must be an object", path)
        _record_issue(issue, issues=issues, diagnostics=diagnostics)
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        issue = f"invalid_json:{path}:{exc}"
        logger.warning("Cannot read %s: %s", path, exc)
        _record_issue(issue, issues=issues, diagnostics=diagnostics)
        return {}


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------


def load_index(
    workspace_root: Path,
    *,
    diagnostics: TraceLoadDiagnostics | None = None,
) -> list[TraceEntry]:
    """Read ``index.jsonl`` and return a list of :class:`TraceEntry`.

    Malformed lines are excluded from results and reported via diagnostics.

    Args:
        workspace_root: Root of the PDD workspace.

    Returns:
        List of trace entries, one per valid index line.
    """
    index_path = _traces_dir(workspace_root) / "index.jsonl"
    rows = _read_jsonl(index_path, diagnostics=diagnostics)

    entries: list[TraceEntry] = []
    for row in rows:
        try:
            entries.append(
                TraceEntry(
                    trace_id=row.get("trace_id", ""),
                    timestamp=row.get("timestamp", ""),
                    run_id=row.get("run_id", ""),
                    model_id=row.get("model_id", ""),
                    planner_version=row.get("planner_version", ""),
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
            logger.warning("Skipping malformed index entry in %s: %s", index_path, exc)
            _record_issue(
                f"malformed_index_entry:{index_path}:{exc}",
                diagnostics=diagnostics,
            )

    return entries


def load_trace(
    workspace_root: Path,
    trace_id: str,
    *,
    diagnostics: TraceLoadDiagnostics | None = None,
) -> LoadedTrace:
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
    tdir = trace_dir(workspace_root, trace_id)
    if not tdir.is_dir():
        raise FileNotFoundError(f"Trace directory not found: {tdir}")

    trace_issues: list[str] = []
    request = _read_json(tdir / "request.json", issues=trace_issues, diagnostics=diagnostics)
    decision = _read_json(tdir / "decision.json", issues=trace_issues, diagnostics=diagnostics)
    replay = _read_json(tdir / "replay.json", issues=trace_issues, diagnostics=diagnostics)
    request_path = tdir / "request.json"
    decision_path = tdir / "decision.json"

    # Call logs
    calls_dir = tdir / "calls"
    model_calls = _read_jsonl(
        calls_dir / "model_calls.jsonl", issues=trace_issues, diagnostics=diagnostics
    )
    tool_calls = _read_jsonl(
        calls_dir / "tool_calls.jsonl", issues=trace_issues, diagnostics=diagnostics
    )

    # Artifacts
    artifacts: dict[str, Any] = {}
    artifacts_dir = tdir / "artifacts"
    if artifacts_dir.is_dir():
        for artifact_path in sorted(artifacts_dir.iterdir()):
            if artifact_path.suffix == ".json" and artifact_path.is_file():
                name = artifact_path.stem
                artifacts[name] = _read_json(
                    artifact_path,
                    issues=trace_issues,
                    diagnostics=diagnostics,
                )

    return LoadedTrace(
        trace_id=trace_id,
        decision_key=decision.get("decision_key", ""),
        request=request,
        decision=decision,
        request_path=str(request_path),
        decision_path=str(decision_path),
        request_exists=request_path.exists(),
        decision_exists=decision_path.exists(),
        model_calls=model_calls,
        tool_calls=tool_calls,
        artifacts=artifacts,
        replay=replay,
        status=decision.get("status", ""),
        overridden=bool(decision.get("overridden", False)),
        planner_version=str(request.get("planner_version", "") or ""),
        load_issues=trace_issues,
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
    workspace_root: Path,
    run_id: str,
    *,
    diagnostics: TraceLoadDiagnostics | None = None,
) -> list[LoadedTrace]:
    """Load all traces for a given run.

    Convenience function: reads the index, filters by *run_id*, and
    loads each matching trace. Traces that fail to load are skipped with
    warnings and recorded in diagnostics when provided.

    Args:
        workspace_root: Root of the PDD workspace.
        run_id: Pipeline run identifier to filter on.

    Returns:
        List of loaded traces for the run.
    """
    entries = load_index(workspace_root, diagnostics=diagnostics)
    filtered = filter_traces(entries, run_id=run_id)

    traces: list[LoadedTrace] = []
    for entry in filtered:
        try:
            traces.append(load_trace(workspace_root, entry.trace_id, diagnostics=diagnostics))
        except (FileNotFoundError, OSError) as exc:
            logger.warning("Skipping trace %s: %s", entry.trace_id, exc)
            _record_issue(
                f"trace_load_failed:{entry.trace_id}:{exc}",
                diagnostics=diagnostics,
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
