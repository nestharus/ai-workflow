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

import copy
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
_DEFAULT_CAPABILITY_INPUT_FIELDS: dict[str, list[str]] = {
    # Empty by default: identity hashes include the full request input payload.
}
_INPUT_IDENTITY_SCHEMA_VERSION = "v2_full_inputs"


def content_hash(data: str) -> str:
    """Return first 16 hex chars of a SHA-256 digest."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:16]


def canonical_json(obj: Any) -> str:
    """Deterministic JSON for hashing (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def identity_inputs_subset(
    capability: str,
    inputs: dict[str, Any],
    capability_input_fields: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Return capability-scoped inputs used for decision identity."""
    field_map = capability_input_fields or _DEFAULT_CAPABILITY_INPUT_FIELDS
    keys = field_map.get(capability)
    if keys is None:
        return {key: inputs.get(key) for key in sorted(inputs.keys())}
    return {key: inputs.get(key) for key in keys if key in inputs}


def compute_input_hash(
    capability: str,
    inputs: dict[str, Any],
    capability_input_fields: dict[str, list[str]] | None = None,
) -> str:
    """Compute normalized full SHA-256 hash for identity input subset."""
    subset = identity_inputs_subset(capability, inputs, capability_input_fields)
    identity_payload = {
        "schema_version": _INPUT_IDENTITY_SCHEMA_VERSION,
        "capability": capability,
        "inputs": subset,
    }
    return hashlib.sha256(canonical_json(identity_payload).encode("utf-8")).hexdigest()


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
    input_hash = compute_input_hash(capability, inputs, capability_input_fields)
    return f"{layer}:{capability}:{slice_id}:{iteration}:{input_hash[:8]}"


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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not path.exists():
        return [], []
    rows: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows, parse_errors
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            parse_errors.append(
                {
                    "line_number": line_number,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "line_preview": line[:240],
                }
            )
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows, parse_errors


def _safe_deepcopy(value: Any) -> Any:
    try:
        return copy.deepcopy(value)
    except Exception:
        return value


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
    model_params: dict[str, Any] = field(default_factory=dict)
    prompt_text: str = ""
    response_text: str = ""
    prompt_ref: str = ""
    response_ref: str = ""
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
    tokens_in: int = 0
    tokens_out: int = 0
    tool_params: dict[str, Any] = field(default_factory=dict)
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


@dataclass
class ReplayBundle:
    """Replay payload for deterministic QA/eval re-execution."""

    trace_id: str
    decision_key: str
    request: dict[str, Any]
    next_actions: list[dict[str, Any]]
    model_route: dict[str, Any]
    planner_state: dict[str, Any]
    final_result: dict[str, Any]
    model_calls: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    snapshot_files: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "trace_id": self.trace_id,
            "decision_key": self.decision_key,
            "request": _safe_deepcopy(self.request),
            "request_snapshot": _safe_deepcopy(self.request),
            "next_actions": [_safe_deepcopy(row) for row in self.next_actions],
            "model_route": _safe_deepcopy(self.model_route),
            "planner_state": _safe_deepcopy(self.planner_state),
            "final_result": _safe_deepcopy(self.final_result),
            "model_calls": [_safe_deepcopy(row) for row in self.model_calls],
            "tool_calls": [_safe_deepcopy(row) for row in self.tool_calls],
            "snapshot_files": _safe_deepcopy(self.snapshot_files),
        }
        if isinstance(self.final_result, dict):
            payload["status"] = str(self.final_result.get("status", "") or "")
            payload["outputs"] = _safe_deepcopy(self.final_result.get("outputs", {}))
            payload["error"] = str(self.final_result.get("error", "") or "")
        return payload


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
    result: dict[str, Any] = field(default_factory=dict)
    model_calls: list[ModelCallRecord] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)
    replay_payload: dict[str, Any] = field(default_factory=dict)
    decision_key: str = ""
    run_id: str = ""
    model_id: str = ""
    planner_version: str = ""
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

    def set_result(self, result: dict[str, Any]) -> None:
        """Set final planning-result payload for decision/replay files."""
        self.result = dict(result) if isinstance(result, dict) else {}

    def add_artifact(self, name: str, data: Any) -> None:
        """Store a named artifact (graph, plan, etc.)."""
        self.artifacts[name] = data

    def set_replay_payload(self, payload: dict[str, Any]) -> None:
        """Set explicit replay payload written to replay.json."""
        self.replay_payload = dict(payload) if isinstance(payload, dict) else {}

    # -- serialization ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Full trace as a plain dict (for replay.json)."""
        return {
            "trace_id": self.trace_id,
            "decision_key": self.decision_key,
            "run_id": self.run_id,
            "model_id": self.model_id,
            "planner_version": self.planner_version,
            "layer": self.layer,
            "capability": self.capability,
            "slice_id": self.slice_id,
            "status": self.status,
            "overridden": self.overridden,
            "request_snapshot": self.request_snapshot,
            "decision": asdict(self.decision) if self.decision else None,
            "result": self.result,
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
            "planner_version": self.planner_version,
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
        request_payload = dict(self.request_snapshot)
        if self.capability:
            request_payload["capability"] = self.capability
        if self.layer:
            request_payload["layer"] = self.layer
        if self.run_id:
            request_payload["run_id"] = self.run_id
        if self.slice_id:
            request_payload["slice_id"] = self.slice_id
        if self.model_id:
            request_payload["model_id"] = self.model_id
        if self.planner_version:
            request_payload["planner_version"] = self.planner_version
        if self.decision_key:
            request_payload["decision_key"] = self.decision_key
        self.request_snapshot = request_payload
        _write_json(trace_dir / "request.json", request_payload)

        # 2. decision.json
        decision_record = asdict(self.decision) if self.decision else {}
        decision_payload = dict(self.result) if isinstance(self.result, dict) else {}
        if decision_record:
            decision_payload.update(decision_record)
            decision_payload["decision_record"] = decision_record
        if "confidence" not in decision_payload:
            decision_payload["confidence"] = float(decision_record.get("confidence", 0.0))
        if "rationale" not in decision_payload:
            decision_payload["rationale"] = str(
                decision_record.get("decision_text", decision_payload.get("status", ""))
            ).strip()
        if self.decision_key:
            decision_payload["decision_key"] = self.decision_key
        if self.status:
            decision_payload["status"] = self.status
        decision_payload["overridden"] = bool(self.overridden)
        _write_json(trace_dir / "decision.json", decision_payload)

        # 3. calls/model_calls.jsonl
        model_calls_path = trace_dir / "calls" / "model_calls.jsonl"
        model_calls_path.parent.mkdir(parents=True, exist_ok=True)
        content_dir = model_calls_path.parent / "content"
        content_dir.mkdir(parents=True, exist_ok=True)
        # Overwrite (not append) so persist is idempotent
        model_calls_path.write_text("", encoding="utf-8")
        for mc in self.model_calls:
            row = asdict(mc)
            prompt_text = str(row.pop("prompt_text", "") or "")
            response_text = str(row.pop("response_text", "") or "")
            if prompt_text:
                prompt_hash = str(row.get("prompt_hash", "") or content_hash(prompt_text))
                row["prompt_hash"] = prompt_hash
                row["prompt_ref"] = f"calls/content/{prompt_hash}.txt"
                prompt_path = content_dir / f"{prompt_hash}.txt"
                if not prompt_path.exists():
                    prompt_path.write_text(prompt_text, encoding="utf-8")
            if response_text:
                response_hash = str(row.get("output_hash", "") or content_hash(response_text))
                row["output_hash"] = response_hash
                row["response_ref"] = f"calls/content/{response_hash}.txt"
                response_path = content_dir / f"{response_hash}.txt"
                if not response_path.exists():
                    response_path.write_text(response_text, encoding="utf-8")
            _append_jsonl(model_calls_path, row)

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
        replay_payload = (
            dict(self.replay_payload)
            if isinstance(self.replay_payload, dict) and self.replay_payload
            else self.to_dict()
        )
        replay_payload.setdefault("trace_id", self.trace_id)
        replay_payload.setdefault("decision_key", self.decision_key)
        replay_payload.setdefault("status", self.status)
        replay_payload.setdefault("request_snapshot", request_payload)
        replay_payload.setdefault("decision", decision_record)
        replay_payload.setdefault("result", decision_payload)
        _write_json(trace_dir / "replay.json", replay_payload)

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
        planner_version: str = "",
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
            planner_version=planner_version,
            layer=layer,
            capability=capability,
            slice_id=slice_id,
        )


class PlannerDebugView:
    """Read-only helper for answering planner QA questions from persisted trace files."""

    def __init__(self, trace_dir: str | Path) -> None:
        self._trace_dir = Path(trace_dir)

    @classmethod
    def from_workspace(cls, workspace_root: str | Path, trace_id: str) -> PlannerDebugView:
        return cls(Path(workspace_root) / _TRACE_REL / trace_id)

    def why_did_you_choose_this(self) -> str:
        decision = _read_json(self._trace_dir / "decision.json")
        rationale = str(decision.get("rationale", "") or "").strip()
        if rationale:
            return rationale
        decision_text = str(decision.get("decision_text", "") or "").strip()
        if decision_text:
            return decision_text
        status = str(decision.get("status", "") or "").strip()
        return status or "No rationale captured."

    def what_evidence_did_you_use(self) -> list[str]:
        decision = _read_json(self._trace_dir / "decision.json")
        refs = decision.get("evidence_refs")
        if isinstance(refs, list):
            return [str(ref).strip() for ref in refs if str(ref).strip()]
        nested = decision.get("decision_record")
        if isinstance(nested, dict) and isinstance(nested.get("evidence_refs"), list):
            return [str(ref).strip() for ref in nested.get("evidence_refs", []) if str(ref).strip()]
        return []

    def which_models_touched_this(self) -> list[str]:
        rows, parse_errors = _read_jsonl(self._trace_dir / "calls" / "model_calls.jsonl")
        touched: list[str] = []
        for row in rows:
            agent = str(row.get("agent_name", "")).strip() or "<unknown-agent>"
            model = str(row.get("model", "")).strip() or "<unknown-model>"
            touched.append(f"{agent}:{model}")
        if parse_errors:
            line_numbers = ",".join(str(item.get("line_number", "?")) for item in parse_errors[:5])
            touched.append(
                f"<trace-corruption:model_calls.jsonl parse_errors={len(parse_errors)} "
                f"lines={line_numbers}>"
            )
        deduped: list[str] = []
        seen: set[str] = set()
        for token in touched:
            if token in seen:
                continue
            seen.add(token)
            deduped.append(token)
        return deduped

    def what_would_have_made_you_block_earlier(self) -> list[str]:
        decision = _read_json(self._trace_dir / "decision.json")
        checks = decision.get("discriminative_checks")
        if isinstance(checks, list):
            return [str(check).strip() for check in checks if str(check).strip()]
        nested = decision.get("decision_record")
        if isinstance(nested, dict) and isinstance(nested.get("discriminative_checks"), list):
            return [
                str(check).strip()
                for check in nested.get("discriminative_checks", [])
                if str(check).strip()
            ]
        return []

    def render(self) -> dict[str, Any]:
        return {
            "why_did_you_choose_this": self.why_did_you_choose_this(),
            "what_evidence_did_you_use": self.what_evidence_did_you_use(),
            "which_models_touched_this": self.which_models_touched_this(),
            "what_would_have_made_you_block_earlier": (
                self.what_would_have_made_you_block_earlier()
            ),
        }
