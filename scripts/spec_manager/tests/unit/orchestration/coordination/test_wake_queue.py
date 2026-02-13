"""Tests for wake queue."""

from __future__ import annotations

from pathlib import Path

import pytest
from spec_manager.orchestration.coordination.wake_queue import (
    WakeEvent,
    WakeQueue,
)

# ------------------------------------------------------------------
# WakeEvent tests
# ------------------------------------------------------------------


class TestWakeEvent:
    def test_auto_fields(self):
        evt = WakeEvent(monitor_id="m1", signal_id="s1", slice_id="sl")
        assert len(evt.event_id) == 16
        assert "T" in evt.timestamp  # ISO format

    def test_explicit_fields(self):
        evt = WakeEvent(
            event_id="my-id",
            timestamp="2026-01-01T00:00:00Z",
            monitor_id="m1",
            signal_id="s1",
            slice_id="sl",
            layer="L1",
            reason="interface available",
            artifact_key="Validator.validate",
            wake_payload={"k": "v"},
        )
        assert evt.event_id == "my-id"
        assert evt.timestamp == "2026-01-01T00:00:00Z"

    def test_round_trip(self):
        evt = WakeEvent(
            event_id="e1",
            timestamp="2026-01-01T00:00:00Z",
            monitor_id="m1",
            signal_id="s1",
            slice_id="slice-a",
            layer="L1",
            reason="done",
            artifact_key="key",
            wake_payload={"x": 1},
        )
        restored = WakeEvent.from_dict(evt.to_dict())
        assert restored.event_id == evt.event_id
        assert restored.timestamp == evt.timestamp
        assert restored.monitor_id == evt.monitor_id
        assert restored.signal_id == evt.signal_id
        assert restored.slice_id == evt.slice_id
        assert restored.layer == evt.layer
        assert restored.reason == evt.reason
        assert restored.artifact_key == evt.artifact_key
        assert restored.wake_payload == evt.wake_payload

    def test_defaults(self):
        evt = WakeEvent()
        assert evt.monitor_id == ""
        assert evt.artifact_key == ""
        assert evt.wake_payload == {}


# ------------------------------------------------------------------
# WakeQueue tests
# ------------------------------------------------------------------


class TestWakeQueue:
    def test_enqueue_and_peek(self, tmp_path: Path):
        q = WakeQueue(tmp_path / "coord")
        evt = WakeEvent(
            event_id="e1",
            timestamp="2026-01-01T00-00-00",
            monitor_id="m1",
            signal_id="s1",
            slice_id="slice-a",
            layer="L1",
            reason="ready",
        )
        q.enqueue(evt)
        peeked = q.peek(slice_id="slice-a")
        assert len(peeked) == 1
        assert peeked[0].event_id == "e1"

    def test_peek_all(self, tmp_path: Path):
        q = WakeQueue(tmp_path / "coord")
        e1 = WakeEvent(
            event_id="e1",
            timestamp="2026-01-01T00-00-00",
            slice_id="slice-a",
            monitor_id="m1",
            signal_id="s1",
            reason="r",
        )
        e2 = WakeEvent(
            event_id="e2",
            timestamp="2026-01-01T00-00-01",
            slice_id="slice-b",
            monitor_id="m2",
            signal_id="s2",
            reason="r",
        )
        q.enqueue(e1)
        q.enqueue(e2)
        all_events = q.peek()
        assert len(all_events) == 2

    def test_dequeue_consumes(self, tmp_path: Path):
        q = WakeQueue(tmp_path / "coord")
        evt = WakeEvent(
            event_id="e1",
            timestamp="2026-01-01T00-00-00",
            monitor_id="m1",
            signal_id="s1",
            slice_id="slice-a",
            reason="ready",
        )
        q.enqueue(evt)
        consumed = q.dequeue("slice-a")
        assert len(consumed) == 1
        assert consumed[0].event_id == "e1"
        # Now empty
        assert q.peek(slice_id="slice-a") == []

    def test_dequeue_only_target_slice(self, tmp_path: Path):
        q = WakeQueue(tmp_path / "coord")
        e1 = WakeEvent(
            event_id="e1",
            timestamp="2026-01-01T00-00-00",
            slice_id="slice-a",
            monitor_id="m1",
            signal_id="s1",
            reason="r",
        )
        e2 = WakeEvent(
            event_id="e2",
            timestamp="2026-01-01T00-00-01",
            slice_id="slice-b",
            monitor_id="m2",
            signal_id="s2",
            reason="r",
        )
        q.enqueue(e1)
        q.enqueue(e2)
        consumed = q.dequeue("slice-a")
        assert len(consumed) == 1
        # slice-b still there
        remaining = q.peek(slice_id="slice-b")
        assert len(remaining) == 1

    def test_clear(self, tmp_path: Path):
        q = WakeQueue(tmp_path / "coord")
        e1 = WakeEvent(
            event_id="e1",
            timestamp="2026-01-01T00-00-00",
            slice_id="slice-a",
            monitor_id="m1",
            signal_id="s1",
            reason="r",
        )
        e2 = WakeEvent(
            event_id="e2",
            timestamp="2026-01-01T00-00-01",
            slice_id="slice-a",
            monitor_id="m2",
            signal_id="s2",
            reason="r",
        )
        q.enqueue(e1)
        q.enqueue(e2)
        q.clear("slice-a")
        assert q.peek(slice_id="slice-a") == []

    def test_dequeue_empty(self, tmp_path: Path):
        q = WakeQueue(tmp_path / "coord")
        assert q.dequeue("nonexistent") == []

    def test_peek_empty(self, tmp_path: Path):
        q = WakeQueue(tmp_path / "coord")
        assert q.peek() == []
        assert q.peek(slice_id="x") == []

    def test_multiple_enqueue_same_slice(self, tmp_path: Path):
        q = WakeQueue(tmp_path / "coord")
        for i in range(3):
            q.enqueue(
                WakeEvent(
                    event_id=f"e{i}",
                    timestamp=f"2026-01-01T00-00-0{i}",
                    slice_id="slice-a",
                    monitor_id=f"m{i}",
                    signal_id=f"s{i}",
                    reason="r",
                )
            )
        assert len(q.peek(slice_id="slice-a")) == 3
        consumed = q.dequeue("slice-a")
        assert len(consumed) == 3
        assert q.peek(slice_id="slice-a") == []
