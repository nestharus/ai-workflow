"""Unit tests for signal emission in ImplementationRunner."""
from __future__ import annotations

import json
from pathlib import Path

from spec_manager.orchestration.coordination.signals import CoordinationSignal
from spec_manager.orchestration.implementation.runner import (
    ImplementationRunResult,
    ImplementationRunner,
    _classify_under_spec,
)
from spec_manager.orchestration.implementation.types import UnderSpecEvent


# ======================================================================
# ImplementationRunResult.signals field
# ======================================================================


class TestRunResultSignals:
    def test_signals_default_empty(self) -> None:
        r = ImplementationRunResult()
        assert r.signals == []

    def test_signals_field_is_independent(self) -> None:
        r1 = ImplementationRunResult()
        r2 = ImplementationRunResult()
        r1.signals.append({"signal_id": "abc"})
        assert r2.signals == []


# ======================================================================
# _classify_under_spec
# ======================================================================


class TestClassifyUnderSpec:
    def test_all_known_mappings(self) -> None:
        cases = {
            "MISSING_CONSTRAINT": "AMBIGUOUS_SPEC",
            "CONFLICTING_CONSTRAINTS": "CONFLICTING_REQUIREMENTS",
            "EXTERNAL_DEP_UNKNOWN": "MISSING_INTERFACE",
            "NEEDS_PRODUCT_DECISION": "AMBIGUOUS_SPEC",
            "NEEDS_API_DECISION": "MISSING_INTERFACE",
        }
        for kind, expected in cases.items():
            event = UnderSpecEvent(kind=kind, question="test")  # type: ignore[arg-type]
            assert _classify_under_spec(event) == expected, f"Failed for kind={kind}"

    def test_unknown_kind_defaults(self) -> None:
        event = UnderSpecEvent(question="test")
        event.kind = "SOME_FUTURE_KIND"  # type: ignore[assignment]
        assert _classify_under_spec(event) == "AMBIGUOUS_SPEC"


# ======================================================================
# _write_artifacts writes signals.json
# ======================================================================


class TestWriteSignals:
    def test_signals_written_to_disk(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        sig = CoordinationSignal(
            run_id="run-42",
            layer="l1",
            classification="MISSING_INTERFACE",
        )

        ImplementationRunner._write_artifacts(
            tmp_path, result, [], [], [], [], [], signals=[sig]
        )

        path = tmp_path / "signals.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["run_id"] == "run-42"
        assert data[0]["classification"] == "MISSING_INTERFACE"

    def test_multiple_signals_written(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        sig1 = CoordinationSignal(run_id="r", layer="l1", classification="AMBIGUOUS_SPEC")
        sig2 = CoordinationSignal(run_id="r", layer="l1", classification="MISSING_INTERFACE")

        ImplementationRunner._write_artifacts(
            tmp_path, result, [], [], [], [], [], signals=[sig1, sig2]
        )

        data = json.loads((tmp_path / "signals.json").read_text(encoding="utf-8"))
        assert len(data) == 2
        classifications = {d["classification"] for d in data}
        assert classifications == {"AMBIGUOUS_SPEC", "MISSING_INTERFACE"}

    def test_no_signals_file_when_empty(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()

        ImplementationRunner._write_artifacts(
            tmp_path, result, [], [], [], [], [], signals=[]
        )

        assert not (tmp_path / "signals.json").exists()

    def test_no_signals_file_when_none(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()

        ImplementationRunner._write_artifacts(tmp_path, result, [], [], [], [], [])

        assert not (tmp_path / "signals.json").exists()


# ======================================================================
# Legacy format removal
# ======================================================================


class TestLegacyRemoved:
    def test_no_apply_function_body_method(self) -> None:
        assert not hasattr(ImplementationRunner, "_apply_function_body")
