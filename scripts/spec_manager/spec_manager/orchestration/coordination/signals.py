"""Coordination signals emitted by agents when they halt.

A CoordinationSignal is the structured artifact an agent writes to disk
when it cannot proceed.  The planner reads these signals, triages them,
and either resolves the issue or schedules a JIT monitor.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# ------------------------------------------------------------------
# Sub-types carried by every signal
# ------------------------------------------------------------------


@dataclass
class SpecRef:
    """Pointer to a spec passage that is relevant to the signal."""

    spec_text: str = ""
    source_file: str = ""
    source_symbol: str = ""
    source_line_hint: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_text": self.spec_text,
            "source_file": self.source_file,
            "source_symbol": self.source_symbol,
            "source_line_hint": self.source_line_hint,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SpecRef:
        return cls(
            spec_text=d.get("spec_text", ""),
            source_file=d.get("source_file", ""),
            source_symbol=d.get("source_symbol", ""),
            source_line_hint=d.get("source_line_hint", 0),
        )


@dataclass
class FunctionRef:
    """Reference to a specific function in a file."""

    file: str = ""
    symbol: str = ""
    signature_line: str = ""

    def __post_init__(self) -> None:
        self.signature_line = str(self.signature_line)

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "symbol": self.symbol,
            "signature_line": self.signature_line,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FunctionRef:
        return cls(
            file=d.get("file", ""),
            symbol=d.get("symbol", ""),
            signature_line=str(d.get("signature_line", "")),
        )


@dataclass
class SignalNeed:
    """What the halted agent needs to continue."""

    summary: str = ""
    artifact_type: str = ""
    artifact_key: str = ""
    expected_shape: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "artifact_type": self.artifact_type,
            "artifact_key": self.artifact_key,
            "expected_shape": self.expected_shape,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SignalNeed:
        return cls(
            summary=d.get("summary", ""),
            artifact_type=d.get("artifact_type", ""),
            artifact_key=d.get("artifact_key", ""),
            expected_shape=d.get("expected_shape", {}),
            confidence=d.get("confidence", 0.0),
        )


@dataclass
class LocalContext:
    """Agent-local context at the point it halted."""

    blocked_function: FunctionRef = field(default_factory=FunctionRef)
    attempted_approach: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked_function": self.blocked_function.to_dict(),
            "attempted_approach": self.attempted_approach,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LocalContext:
        return cls(
            blocked_function=FunctionRef.from_dict(d.get("blocked_function", {})),
            attempted_approach=d.get("attempted_approach", ""),
        )


@dataclass
class SignalProgress:
    """Progress snapshot when the agent halted."""

    functions_implemented: int = 0
    functions_skipped: int = 0
    worktree_branch: str = ""
    latest_commit: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "functions_implemented": self.functions_implemented,
            "functions_skipped": self.functions_skipped,
            "worktree_branch": self.worktree_branch,
            "latest_commit": self.latest_commit,
            "artifacts": self.artifacts,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SignalProgress:
        return cls(
            functions_implemented=d.get("functions_implemented", 0),
            functions_skipped=d.get("functions_skipped", 0),
            worktree_branch=d.get("worktree_branch", ""),
            latest_commit=d.get("latest_commit", ""),
            artifacts=d.get("artifacts", {}),
        )


@dataclass
class SearchHints:
    """Hints to help the planner resolve the signal."""

    keywords: list[str] = field(default_factory=list)
    possible_owner_slices: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "keywords": list(self.keywords),
            "possible_owner_slices": list(self.possible_owner_slices),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SearchHints:
        return cls(
            keywords=list(d.get("keywords", [])),
            possible_owner_slices=list(d.get("possible_owner_slices", [])),
        )


# ------------------------------------------------------------------
# Main signal type
# ------------------------------------------------------------------

_CLASSIFICATION_VALUES = frozenset(
    {
        "MISSING_INTERFACE",
        "AMBIGUOUS_SPEC",
        "CONFLICTING_REQUIREMENTS",
        "INTERFACE_MISMATCH",
        "MERGE_CONFLICT",
        "MONITOR_FAILED",
    }
)


@dataclass
class CoordinationSignal:
    """Structured halt signal emitted by an agent that cannot proceed."""

    signal_version: int = 1
    signal_id: str = ""
    run_id: str = ""
    layer: str = ""
    slice_id: str = ""
    iteration: int = 0
    status: Literal["HALT"] = "HALT"
    classification: Literal[
        "MISSING_INTERFACE",
        "AMBIGUOUS_SPEC",
        "CONFLICTING_REQUIREMENTS",
        "INTERFACE_MISMATCH",
        "MERGE_CONFLICT",
        "MONITOR_FAILED",
    ] = "MISSING_INTERFACE"
    need: SignalNeed = field(default_factory=SignalNeed)
    spec_refs: list[SpecRef] = field(default_factory=list)
    local_context: LocalContext = field(default_factory=LocalContext)
    progress: SignalProgress = field(default_factory=SignalProgress)
    search_hints: SearchHints = field(default_factory=SearchHints)
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.signal_id:
            self.signal_id = os.urandom(8).hex()

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_version": self.signal_version,
            "signal_id": self.signal_id,
            "run_id": self.run_id,
            "layer": self.layer,
            "slice_id": self.slice_id,
            "iteration": self.iteration,
            "status": self.status,
            "classification": self.classification,
            "need": self.need.to_dict(),
            "spec_refs": [r.to_dict() for r in self.spec_refs],
            "local_context": self.local_context.to_dict(),
            "progress": self.progress.to_dict(),
            "search_hints": self.search_hints.to_dict(),
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CoordinationSignal:
        return cls(
            signal_version=d.get("signal_version", 1),
            signal_id=d.get("signal_id", ""),
            run_id=d.get("run_id", ""),
            layer=d.get("layer", ""),
            slice_id=d.get("slice_id", ""),
            iteration=d.get("iteration", 0),
            status=d.get("status", "HALT"),
            classification=d.get("classification", "MISSING_INTERFACE"),
            need=SignalNeed.from_dict(d.get("need", {})),
            spec_refs=[SpecRef.from_dict(r) for r in d.get("spec_refs", [])],
            local_context=LocalContext.from_dict(d.get("local_context", {})),
            progress=SignalProgress.from_dict(d.get("progress", {})),
            search_hints=SearchHints.from_dict(d.get("search_hints", {})),
            payload=d.get("payload", {}),
        )

    def write_to(self, iteration_dir: Path) -> None:
        """Append this signal to ``signals.json`` in *iteration_dir*.

        The file stores a JSON array so multiple signals can coexist in
        the same iteration directory.
        """
        iteration_dir.mkdir(parents=True, exist_ok=True)
        signals_path = iteration_dir / "signals.json"
        existing: list[dict[str, Any]] = []
        if signals_path.exists():
            existing = json.loads(signals_path.read_text())
        existing.append(self.to_dict())
        signals_path.write_text(json.dumps(existing, indent=2))

    @classmethod
    def load_from(cls, iteration_dir: Path) -> list[CoordinationSignal]:
        """Load all signals from ``signals.json`` in *iteration_dir*."""
        signals_path = iteration_dir / "signals.json"
        if not signals_path.exists():
            return []
        raw = json.loads(signals_path.read_text())
        return [cls.from_dict(d) for d in raw]
