"""UserQuestionSignal — file-backed signal store for user-facing questions.

Per response2.md Section 3: Internal agents never talk to the user directly.
They emit UserQuestionSignal events that request user input. The final
user prompt is produced by the Intent Agent and must pass the quality gate.

Storage: .pdd_runs/<run_id>/coordination/user_questions.jsonl (append-only)

Emitters:
    - Planner (AuthorityDecider marks human_required)
    - UnderSpecManager (ambiguity not auto-resolvable)
    - PromotionLoop / PddLifecycle (checkpoint signals)
    - Slice agents (rare, user-domain ambiguity only)
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Authoritative enum per response2.md Section 3.1
VALID_SOURCE_KINDS = frozenset({
    "PLANNER",
    "UNDER_SPEC",
    "PROMOTION_LOOP",
    "PDD_LIFECYCLE",
    "INTENT_AGENT",
    "SLICE_AGENT",
})


@dataclass
class SignalSource:
    """Source of a UserQuestionSignal."""

    kind: str = ""  # PLANNER | UNDER_SPEC | PROMOTION_LOOP | PDD_LIFECYCLE | SLICE_AGENT
    trace_id: str = ""
    slice_id: str = ""
    layer: str = ""
    signal_id: str = ""


@dataclass
class SignalBlocking:
    """Blocking context for the signal."""

    severity: str = "INFO"  # BLOCKING | HIGH_RISK | MEDIUM_RISK | INFO
    blocked_slices: list[str] = field(default_factory=list)


@dataclass
class SpecRefItem:
    """Reference to a spec text location."""

    spec_text: str = ""
    source_file: str = ""
    source_line_hint: int = 0


@dataclass
class CodeRefItem:
    """Reference to a code location."""

    file: str = ""
    symbol: str = ""
    line: int = 0


@dataclass
class SignalQuestion:
    """Internal draft question (may be technical — Intent Agent rewrites)."""

    text: str = ""
    taxonomy_hint: str = "UNKNOWN"  # May include internal-only types
    canonical_key_hint: str = ""
    answer_spec_hint: dict[str, Any] = field(default_factory=dict)


@dataclass
class SignalContext:
    """Context for a UserQuestionSignal."""

    blocking: SignalBlocking = field(default_factory=SignalBlocking)
    spec_refs: list[SpecRefItem] = field(default_factory=list)
    code_refs: list[CodeRefItem] = field(default_factory=list)


@dataclass
class UserQuestionSignal:
    """Signal requesting user input via the Intent Agent queue.

    Per response2.md Section 3.1 JSON schema. Internal agents emit these;
    the Intent Agent ingests, rewrites into user-facing language, and
    enforces the quality gate before presenting to the user.
    """

    uq_version: int = 1
    uq_id: str = ""
    run_id: str = ""
    created_at: str = ""
    source: SignalSource = field(default_factory=SignalSource)
    question: SignalQuestion = field(default_factory=SignalQuestion)
    context: SignalContext = field(default_factory=SignalContext)
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.uq_id:
            self.uq_id = f"uq_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.source.kind and self.source.kind not in VALID_SOURCE_KINDS:
            logger.warning(
                "SignalSource.kind %r not in VALID_SOURCE_KINDS %s",
                self.source.kind,
                sorted(VALID_SOURCE_KINDS),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "uq_version": self.uq_version,
            "uq_id": self.uq_id,
            "run_id": self.run_id,
            "created_at": self.created_at,
            "source": {
                "kind": self.source.kind,
                "trace_id": self.source.trace_id,
                "slice_id": self.source.slice_id,
                "layer": self.source.layer,
                "signal_id": self.source.signal_id,
            },
            "question": {
                "text": self.question.text,
                "taxonomy_hint": self.question.taxonomy_hint,
                "canonical_key_hint": self.question.canonical_key_hint,
                "answer_spec_hint": self.question.answer_spec_hint,
            },
            "context": {
                "blocking": {
                    "severity": self.context.blocking.severity,
                    "blocked_slices": self.context.blocking.blocked_slices,
                },
                "spec_refs": [
                    {
                        "spec_text": r.spec_text,
                        "source_file": r.source_file,
                        "source_line_hint": r.source_line_hint,
                    }
                    for r in self.context.spec_refs
                ],
                "code_refs": [
                    {
                        "file": r.file,
                        "symbol": r.symbol,
                        "line": r.line,
                    }
                    for r in self.context.code_refs
                ],
            },
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UserQuestionSignal:
        src = d.get("source", {})
        source = SignalSource(
            kind=src.get("kind", ""),
            trace_id=src.get("trace_id", ""),
            slice_id=src.get("slice_id", ""),
            layer=src.get("layer", ""),
            signal_id=src.get("signal_id", ""),
        )
        q = d.get("question", {})
        question = SignalQuestion(
            text=q.get("text", ""),
            taxonomy_hint=q.get("taxonomy_hint", "UNKNOWN"),
            canonical_key_hint=q.get("canonical_key_hint", ""),
            answer_spec_hint=q.get("answer_spec_hint", {}),
        )
        ctx = d.get("context", {})
        blk = ctx.get("blocking", {})
        blocking = SignalBlocking(
            severity=blk.get("severity", "INFO"),
            blocked_slices=blk.get("blocked_slices", []),
        )
        spec_refs = [
            SpecRefItem(
                spec_text=r.get("spec_text", ""),
                source_file=r.get("source_file", ""),
                source_line_hint=r.get("source_line_hint", 0),
            )
            for r in ctx.get("spec_refs", [])
        ]
        code_refs = [
            CodeRefItem(
                file=r.get("file", ""),
                symbol=r.get("symbol", ""),
                line=r.get("line", 0),
            )
            for r in ctx.get("code_refs", [])
        ]
        context = SignalContext(
            blocking=blocking,
            spec_refs=spec_refs,
            code_refs=code_refs,
        )
        sig = cls.__new__(cls)
        sig.uq_version = d.get("uq_version", 1)
        sig.uq_id = d.get("uq_id", "")
        sig.run_id = d.get("run_id", "")
        sig.created_at = d.get("created_at", "")
        sig.source = source
        sig.question = question
        sig.context = context
        sig.payload = d.get("payload", {})
        return sig


class UserQuestionSignalStore:
    """Append-only JSONL store for UserQuestionSignal events."""

    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "coordination" / "user_questions.jsonl"

    def write(self, signal: UserQuestionSignal) -> None:
        """Append a signal to the store."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    signal.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )

    def read_since(self, watermark: str) -> list[UserQuestionSignal]:
        """Read signals since the given watermark.

        *watermark* is the ``uq_id`` of the last processed signal.
        All signals appearing **after** that line are returned.
        If *watermark* is empty, all signals are returned.
        """
        all_signals = self.read_all()
        if not watermark:
            return all_signals
        seen_watermark = False
        past_watermark = False
        result: list[UserQuestionSignal] = []
        for sig in all_signals:
            if past_watermark:
                result.append(sig)
            elif sig.uq_id == watermark:
                seen_watermark = True
                past_watermark = True
        if not seen_watermark:
            logger.warning(
                "UserQuestionSignalStore watermark %s was not found; replaying all signals",
                watermark,
            )
            return all_signals
        return result

    def read_all(self) -> list[UserQuestionSignal]:
        """Read all signals from the store."""
        if not self._path.exists():
            return []
        signals: list[UserQuestionSignal] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                signals.append(UserQuestionSignal.from_dict(json.loads(line)))
            except (json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
                logger.warning("Skipping malformed signal line: %s", exc)
        return signals


class PlannerUpdateStore:
    """Append-only JSONL store for Planner constraint/decision update signals."""

    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "coordination" / "planner_updates.jsonl"

    def write(self, event: dict[str, Any]) -> None:
        """Append a planner update event."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")

    def read_since(self, watermark: str) -> list[dict[str, Any]]:
        """Read events since the given watermark.

        *watermark* is the ``created_at`` timestamp of the last processed
        event.  All events whose ``created_at`` is strictly greater than
        *watermark* are returned.  If *watermark* is empty, all events are
        returned.
        """
        if not self._path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except (json.JSONDecodeError, Exception) as exc:  # noqa: BLE001
                logger.warning("Skipping malformed planner event line: %s", exc)
        if not watermark:
            return events
        return [e for e in events if e.get("created_at", "") > watermark]
