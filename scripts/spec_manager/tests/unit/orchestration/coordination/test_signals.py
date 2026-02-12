"""Tests for coordination signals."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spec_manager.orchestration.coordination.signals import (
    CoordinationSignal,
    FunctionRef,
    LocalContext,
    SearchHints,
    SignalNeed,
    SignalProgress,
    SpecRef,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_signal(**overrides) -> CoordinationSignal:
    defaults = dict(
        signal_id="abc123",
        run_id="run-1",
        layer="L1",
        slice_id="slice-a",
        iteration=1,
        classification="MISSING_INTERFACE",
        need=SignalNeed(
            summary="Need TransactionValidator interface",
            artifact_type="interface",
            artifact_key="TransactionValidator.validate",
            expected_shape={"params": ["txn"], "return": "bool"},
            confidence=0.9,
        ),
        spec_refs=[
            SpecRef(
                spec_text="TransactionValidator must expose validate()",
                source_file="spec.md",
                source_symbol="TransactionValidator",
                source_line_hint=42,
            )
        ],
        local_context=LocalContext(
            blocked_function=FunctionRef(
                file="settlement.py",
                symbol="process_settlement",
                signature_line=10,
            ),
            attempted_approach="Tried stubbing validate() but spec unclear",
        ),
        progress=SignalProgress(
            functions_implemented=5,
            functions_skipped=1,
            worktree_branch="slice-a-l1",
            latest_commit="deadbeef",
            artifacts={"skeleton": "settlement.py"},
        ),
        search_hints=SearchHints(
            keywords=["TransactionValidator", "validate"],
            possible_owner_slices=["slice-b"],
        ),
        payload={"extra": "data"},
    )
    defaults.update(overrides)
    return CoordinationSignal(**defaults)


# ------------------------------------------------------------------
# Sub-type round-trip tests
# ------------------------------------------------------------------


class TestSpecRef:
    def test_round_trip(self):
        ref = SpecRef(
            spec_text="Must validate",
            source_file="spec.md",
            source_symbol="Validator",
            source_line_hint=10,
        )
        assert SpecRef.from_dict(ref.to_dict()) == ref

    def test_defaults(self):
        ref = SpecRef()
        assert ref.spec_text == ""
        assert ref.source_line_hint == 0


class TestFunctionRef:
    def test_round_trip(self):
        ref = FunctionRef(file="a.py", symbol="foo", signature_line=5)
        assert FunctionRef.from_dict(ref.to_dict()) == ref


class TestSignalNeed:
    def test_round_trip(self):
        need = SignalNeed(
            summary="need X",
            artifact_type="interface",
            artifact_key="X.do",
            expected_shape={"a": 1},
            confidence=0.8,
        )
        assert SignalNeed.from_dict(need.to_dict()) == need


class TestLocalContext:
    def test_round_trip(self):
        ctx = LocalContext(
            blocked_function=FunctionRef(file="b.py", symbol="bar", signature_line=20),
            attempted_approach="tried Y",
        )
        restored = LocalContext.from_dict(ctx.to_dict())
        assert restored.attempted_approach == "tried Y"
        assert restored.blocked_function.file == "b.py"


class TestSignalProgress:
    def test_round_trip(self):
        prog = SignalProgress(
            functions_implemented=3,
            functions_skipped=1,
            worktree_branch="br",
            latest_commit="abc",
            artifacts={"k": "v"},
        )
        assert SignalProgress.from_dict(prog.to_dict()) == prog


class TestSearchHints:
    def test_round_trip(self):
        hints = SearchHints(
            keywords=["a", "b"],
            possible_owner_slices=["s1"],
        )
        assert SearchHints.from_dict(hints.to_dict()) == hints


# ------------------------------------------------------------------
# CoordinationSignal tests
# ------------------------------------------------------------------


class TestCoordinationSignal:
    def test_auto_id(self):
        sig = CoordinationSignal(run_id="r")
        assert len(sig.signal_id) == 16  # 8 bytes hex

    def test_explicit_id(self):
        sig = CoordinationSignal(signal_id="my-id")
        assert sig.signal_id == "my-id"

    def test_round_trip(self):
        sig = _make_signal()
        d = sig.to_dict()
        restored = CoordinationSignal.from_dict(d)
        assert restored.signal_id == sig.signal_id
        assert restored.run_id == sig.run_id
        assert restored.layer == sig.layer
        assert restored.slice_id == sig.slice_id
        assert restored.iteration == sig.iteration
        assert restored.status == "HALT"
        assert restored.classification == "MISSING_INTERFACE"
        assert restored.need.summary == sig.need.summary
        assert restored.need.confidence == 0.9
        assert len(restored.spec_refs) == 1
        assert restored.spec_refs[0].spec_text == "TransactionValidator must expose validate()"
        assert restored.local_context.blocked_function.symbol == "process_settlement"
        assert restored.progress.functions_implemented == 5
        assert restored.search_hints.keywords == ["TransactionValidator", "validate"]
        assert restored.payload == {"extra": "data"}

    def test_round_trip_json_stable(self):
        sig = _make_signal()
        json_str = json.dumps(sig.to_dict(), sort_keys=True)
        restored = CoordinationSignal.from_dict(json.loads(json_str))
        assert json.dumps(restored.to_dict(), sort_keys=True) == json_str

    def test_default_signal(self):
        sig = CoordinationSignal()
        assert sig.signal_version == 1
        assert sig.status == "HALT"
        assert sig.classification == "MISSING_INTERFACE"
        assert sig.spec_refs == []
        assert sig.payload == {}

    def test_all_classifications(self):
        for cls_val in [
            "MISSING_INTERFACE",
            "AMBIGUOUS_SPEC",
            "CONFLICTING_REQUIREMENTS",
            "INTERFACE_MISMATCH",
            "MERGE_CONFLICT",
            "MONITOR_FAILED",
        ]:
            sig = CoordinationSignal(classification=cls_val)
            assert sig.classification == cls_val


# ------------------------------------------------------------------
# File I/O tests
# ------------------------------------------------------------------


class TestSignalFileIO:
    def test_write_and_load(self, tmp_path: Path):
        sig = _make_signal()
        sig.write_to(tmp_path)
        loaded = CoordinationSignal.load_from(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].signal_id == sig.signal_id

    def test_write_multiple_signals(self, tmp_path: Path):
        s1 = _make_signal(signal_id="sig-1")
        s2 = _make_signal(signal_id="sig-2", classification="AMBIGUOUS_SPEC")
        s1.write_to(tmp_path)
        s2.write_to(tmp_path)
        loaded = CoordinationSignal.load_from(tmp_path)
        assert len(loaded) == 2
        assert loaded[0].signal_id == "sig-1"
        assert loaded[1].signal_id == "sig-2"

    def test_load_empty_directory(self, tmp_path: Path):
        assert CoordinationSignal.load_from(tmp_path) == []

    def test_write_creates_directory(self, tmp_path: Path):
        nested = tmp_path / "deep" / "nested"
        sig = _make_signal()
        sig.write_to(nested)
        assert (nested / "signals.json").exists()

    def test_load_preserves_all_fields(self, tmp_path: Path):
        sig = _make_signal()
        sig.write_to(tmp_path)
        loaded = CoordinationSignal.load_from(tmp_path)[0]
        # Compare full dict for completeness
        assert loaded.to_dict() == sig.to_dict()
