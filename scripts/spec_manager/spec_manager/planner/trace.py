"""QA instrumentation for the planner.

Every planning decision is logged for inspection and comparison against
ground truth.  A single trace directory is written per ``trace_id``::

    workspace/analysis/planner_traces/{trace_id}/
        request.json          — PlanningRequest snapshot
        decision.json         — final PlanningResult + confidence + rationale
        calls/model_calls.jsonl   — one line per LLM call
        calls/tool_calls.jsonl    — evidence-store queries, etc.
        artifacts/            — integration graphs, plans, etc.
        replay.json           — enough to re-run planner without repo state

Each trace also appends a line to ``index.jsonl`` for fast lookup::

    workspace/analysis/planner_traces/index.jsonl

Usage::

    trace = PlannerTrace.start("abc-123", {"slice": "foo", "layer": "L1"})
    trace.record_model_call(ModelCallRecord(agent_name="gap_agent", model="opus"))
    trace.set_decision(DecisionRecord(decision_text="promote", confidence=0.95))
    trace.add_artifact("graph", {"nodes": [...], "edges": [...]})
    trace_dir = trace.persist(workspace_root)
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TRACE_REL = Path("analysis") / "planner_traces"


def content_hash(data: str) -> str:
    """Return first 16 hex chars of a SHA-256 digest."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def canonical_json(obj: Any) -> str:
    """Deterministic JSON for hashing (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def compute_decision_key(
    layer: str,
    capability: str,
    slice_id: str,
    iteration: int,
    inputs: dict[str, Any],
    capability_input_fields: dict[str, list[str]] | None = None,
) -> str:
    """Build a deterministic decision key for ground truth matching.

    Format: ``{layer}:{capability}:{slice_id}:{iteration}:{input_hash[:8]}``

    *capability_input_fields* maps capability names to the input dict keys
    that matter for identity.  If not provided, a default mapping is used.
    """
    _default_fields: dict[str, list[str]] = {
        "RESOLVE_SIGNAL": ["signal"],
        "GAP": ["gaps"],
        "PLAN": ["gaps"],
        "UNDER_SPEC": ["events"],
        "INTEGRATION_ANALYSIS": ["topology"],
    }
    field_map = capability_input_fields or _default_fields
    keys = field_map.get(capability, sorted(inputs.keys()))

    subset = {k: inputs.get(k) for k in keys if k in inputs}
    input_hash = hashlib.sha256(canonical_json(subset).encode("utf-8")).hexdigest()[:8]

    return f"{layer}:{capability}:{slice_id}:{iteration}:{input_hash}"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


# ---------------------------------------------------------------------------
# Record types
# ---------------------------------------------------------------------------


@dataclass
class ModelCallRecord:
    """One LLM call made during planning."""

    agent_name: str
    model: str = ""
    prompt_hash: str = ""
    output_hash: str = ""
    duration_ms: float = 0
    tokens_in: int = 0
    tokens_out: int = 0
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


@dataclass
class ToolCallRecord:
    """One tool invocation (evidence-store query, etc.)."""

    tool_name: str
    inputs_hash: str = ""
    output_summary: str = ""
    duration_ms: float = 0
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()


@dataclass
class DecisionRecord:
    """The final planning decision and its justification."""

    decision_text: str = ""
    confidence: float = 0.0
    assumptions: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    alternatives_considered: list[str] = field(default_factory=list)
    discriminative_checks: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------


@dataclass
class PlannerTrace:
    """Accumulates all instrumentation for a single planning invocation.

    Call :meth:`start` to create, record calls/decisions during planning,
    then :meth:`persist` to flush everything to disk.
    """

    trace_id: str
    request_snapshot: dict[str, Any] = field(default_factory=dict)
    decision: DecisionRecord | None = None
    model_calls: list[ModelCallRecord] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    decision_key: str = ""
    run_id: str = ""
    model_id: str = ""
    layer: str = ""
    capability: str = ""
    slice_id: str = ""
    status: str = ""
    overridden: bool = False

    # -- mutation helpers ---------------------------------------------------

    def record_model_call(self, record: ModelCallRecord) -> None:
        """Append an LLM call record."""
        self.model_calls.append(record)

    def record_tool_call(self, record: ToolCallRecord) -> None:
        """Append a tool-call record."""
        self.tool_calls.append(record)

    def set_decision(self, decision: DecisionRecord) -> None:
        """Set (or overwrite) the final decision."""
        self.decision = decision

    def add_artifact(self, name: str, data: Any) -> None:
        """Store a named artifact (graph, plan, etc.)."""
        self.artifacts[name] = data

    # -- serialization ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Full trace as a plain dict (for replay.json)."""
        return {
            "trace_id": self.trace_id,
            "decision_key": self.decision_key,
            "run_id": self.run_id,
            "model_id": self.model_id,
            "layer": self.layer,
            "capability": self.capability,
            "slice_id": self.slice_id,
            "status": self.status,
            "overridden": self.overridden,
            "request_snapshot": self.request_snapshot,
            "decision": asdict(self.decision) if self.decision else None,
            "model_calls": [asdict(m) for m in self.model_calls],
            "tool_calls": [asdict(t) for t in self.tool_calls],
            "artifacts": self.artifacts,
        }

    def _index_entry(self) -> dict[str, Any]:
        """One-line summary for ``index.jsonl``."""
        return {
            "trace_id": self.trace_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "model_id": self.model_id,
            "slice_id": self.slice_id,
            "layer": self.layer,
            "capability": self.capability,
            "decision_key": self.decision_key,
            "status": self.status,
            "overridden": self.overridden,
            "model_calls_count": len(self.model_calls),
            "tool_calls_count": len(self.tool_calls),
        }

    # -- persistence --------------------------------------------------------

    def persist(self, workspace_root: str | Path) -> Path:
        """Write the full trace to disk.

        Returns the trace directory path.
        """
        root = Path(workspace_root)
        trace_dir = root / _TRACE_REL / self.trace_id
        trace_dir.mkdir(parents=True, exist_ok=True)

        # 1. request.json
        _write_json(trace_dir / "request.json", self.request_snapshot)

        # 2. decision.json
        decision_payload = asdict(self.decision) if self.decision else {}
        if self.decision_key:
            decision_payload["decision_key"] = self.decision_key
        if self.status:
            decision_payload["status"] = self.status
        _write_json(trace_dir / "decision.json", decision_payload)

        # 3. calls/model_calls.jsonl
        model_calls_path = trace_dir / "calls" / "model_calls.jsonl"
        model_calls_path.parent.mkdir(parents=True, exist_ok=True)
        # Overwrite (not append) so persist is idempotent
        model_calls_path.write_text("", encoding="utf-8")
        for mc in self.model_calls:
            _append_jsonl(model_calls_path, asdict(mc))

        # 4. calls/tool_calls.jsonl
        tool_calls_path = trace_dir / "calls" / "tool_calls.jsonl"
        tool_calls_path.write_text("", encoding="utf-8")
        for tc in self.tool_calls:
            _append_jsonl(tool_calls_path, asdict(tc))

        # 5. artifacts/
        artifacts_dir = trace_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        for name, data in self.artifacts.items():
            _write_json(artifacts_dir / f"{name}.json", data)

        # 6. replay.json
        _write_json(trace_dir / "replay.json", self.to_dict())

        # 7. Append to index.jsonl
        index_path = root / _TRACE_REL / "index.jsonl"
        _append_jsonl(index_path, self._index_entry())

        logger.info("Planner trace persisted: %s", trace_dir)
        return trace_dir

    # -- factory ------------------------------------------------------------

    @classmethod
    def start(
        cls,
        trace_id: str,
        request_snapshot: dict[str, Any],
        *,
        decision_key: str = "",
        run_id: str = "",
        model_id: str = "",
        layer: str = "",
        capability: str = "",
        slice_id: str = "",
    ) -> PlannerTrace:
        """Create a new trace for a planning invocation."""
        return cls(
            trace_id=trace_id,
            request_snapshot=request_snapshot,
            decision_key=decision_key,
            run_id=run_id,
            model_id=model_id,
            layer=layer,
            capability=capability,
            slice_id=slice_id,
        )
