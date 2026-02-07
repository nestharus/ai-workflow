"""Tests for file-based SignalExchange."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from spec_manager.refinement.interactive.input_signal import InputSignal, WorkContext
from spec_manager.refinement.interactive.signal_exchange import SignalExchange
from spec_manager.refinement.interactive.spec_patcher import SteeringResponse


def _make_signal(signal_id: str = "SIG-001") -> InputSignal:
    ctx = WorkContext(
        current_phase="test",
        current_library=None,
        current_task="test",
        iteration=1,
    )
    return InputSignal(
        signal_id=signal_id,
        signal_type="ambiguity",
        encountered_text="test text",
        encountered_location="spec::test",
        work_context=ctx,
        goal="test",
        question="test?",
    )


def test_post_signals_creates_pending_json(tmp_path: Path) -> None:
    exchange = SignalExchange(tmp_path)
    exchange.post_signals([_make_signal()])

    pending = tmp_path / "pending.json"
    assert pending.exists()

    data = json.loads(pending.read_text(encoding="utf-8"))
    assert len(data["signals"]) == 1
    assert data["signals"][0]["signal_id"] == "SIG-001"


def test_post_signals_multiple(tmp_path: Path) -> None:
    exchange = SignalExchange(tmp_path)
    signals = [_make_signal(f"SIG-{i:03d}") for i in range(1, 4)]
    exchange.post_signals(signals)

    data = json.loads((tmp_path / "pending.json").read_text(encoding="utf-8"))
    assert len(data["signals"]) == 3
    ids = [s["signal_id"] for s in data["signals"]]
    assert ids == ["SIG-001", "SIG-002", "SIG-003"]


def test_post_signals_has_generated_at(tmp_path: Path) -> None:
    exchange = SignalExchange(tmp_path)
    exchange.post_signals([_make_signal()])

    data = json.loads((tmp_path / "pending.json").read_text(encoding="utf-8"))
    assert "generated_at" in data
    # Verify it parses as ISO format without raising
    datetime.fromisoformat(data["generated_at"])


def test_check_responses_no_file(tmp_path: Path) -> None:
    exchange = SignalExchange(tmp_path)
    assert exchange.check_responses() == []


def test_check_responses_reads_file(tmp_path: Path) -> None:
    exchange = SignalExchange(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)

    responses_path = tmp_path / "responses.json"
    responses_path.write_text(
        json.dumps([{"signal_id": "SIG-001", "response_text": "answer", "source": "human"}]),
        encoding="utf-8",
    )

    results = exchange.check_responses()
    assert len(results) == 1
    assert isinstance(results[0], SteeringResponse)
    assert results[0].ambiguity_id == "SIG-001"
    assert results[0].response_text == "answer"
    assert results[0].source == "human"


def test_check_responses_invalid_json(tmp_path: Path) -> None:
    exchange = SignalExchange(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)

    responses_path = tmp_path / "responses.json"
    responses_path.write_text("not valid json {{{", encoding="utf-8")

    results = exchange.check_responses()
    assert results == []


def test_check_responses_skips_malformed(tmp_path: Path) -> None:
    exchange = SignalExchange(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)

    payload = [
        {"signal_id": "SIG-001", "response_text": "good"},
        {"missing_keys": True},
        "not a dict",
        {"signal_id": "SIG-003", "response_text": "also good", "source": "human"},
    ]
    responses_path = tmp_path / "responses.json"
    responses_path.write_text(json.dumps(payload), encoding="utf-8")

    results = exchange.check_responses()
    assert len(results) == 2
    assert results[0].ambiguity_id == "SIG-001"
    assert results[1].ambiguity_id == "SIG-003"


def test_wait_for_responses_returns_immediately(tmp_path: Path) -> None:
    exchange = SignalExchange(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)

    responses_path = tmp_path / "responses.json"
    responses_path.write_text(
        json.dumps([{"signal_id": "SIG-001", "response_text": "fast"}]),
        encoding="utf-8",
    )

    results = exchange.wait_for_responses(timeout_seconds=1)
    assert len(results) == 1
    assert results[0].response_text == "fast"


def test_wait_for_responses_timeout(tmp_path: Path) -> None:
    exchange = SignalExchange(tmp_path)

    try:
        exchange.wait_for_responses(timeout_seconds=0.1, poll_interval=0.05)
        raise AssertionError("Expected TimeoutError")  # noqa: TRY301
    except TimeoutError:
        pass


def test_clear_removes_files(tmp_path: Path) -> None:
    exchange = SignalExchange(tmp_path)
    exchange.post_signals([_make_signal()])

    responses_path = tmp_path / "responses.json"
    responses_path.write_text(
        json.dumps([{"signal_id": "SIG-001", "response_text": "done"}]),
        encoding="utf-8",
    )

    assert (tmp_path / "pending.json").exists()
    assert responses_path.exists()

    exchange.clear()

    assert not (tmp_path / "pending.json").exists()
    assert not responses_path.exists()


def test_clear_no_files(tmp_path: Path) -> None:
    exchange = SignalExchange(tmp_path)
    # Should not raise
    exchange.clear()


def test_round_trip(tmp_path: Path) -> None:
    exchange = SignalExchange(tmp_path)

    signal = _make_signal("SIG-042")
    exchange.post_signals([signal])

    # Simulate human writing responses.json that matches the posted signal
    responses_path = tmp_path / "responses.json"
    responses_path.write_text(
        json.dumps([{"signal_id": "SIG-042", "response_text": "clarified", "source": "human"}]),
        encoding="utf-8",
    )

    results = exchange.check_responses()
    assert len(results) == 1
    assert results[0].ambiguity_id == signal.signal_id
    assert results[0].response_text == "clarified"
