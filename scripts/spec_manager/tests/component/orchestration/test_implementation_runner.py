from __future__ import annotations

import json
from pathlib import Path

from spec_manager.orchestration.coordination.signals import CoordinationSignal
from spec_manager.orchestration.implementation.runner import (
    ImplementationRunner,
    ImplementationRunResult,
    _classify_under_spec,
)
from spec_manager.orchestration.implementation.types import (
    EdgeProposal,
    PinProposal,
    TestArtifact,
    UnderSpecEvent,
)

# ======================================================================
# ImplementationRunResult
# ======================================================================


class TestImplementationRunResult:
    def test_defaults(self) -> None:
        r = ImplementationRunResult()
        assert r.patch_path == ""
        assert r.applied_edits == []
        assert r.pin_proposals == []
        assert r.edge_proposals == []
        assert r.under_spec_events == []
        assert r.signals == []
        assert r.tests_added == []
        assert r.notes_path == ""
        assert r.functions_implemented == 0
        assert r.functions_skipped == 0
        assert r.errors == []

    def test_signals_field_exists(self) -> None:
        r = ImplementationRunResult()
        assert isinstance(r.signals, list)
        assert r.signals == []

    def test_list_fields_not_shared(self) -> None:
        r1 = ImplementationRunResult()
        r2 = ImplementationRunResult()
        r1.applied_edits.append({"f": "x"})
        r1.pin_proposals.append({"pin": "p"})
        r1.edge_proposals.append({"edge": "e"})
        r1.under_spec_events.append({"kind": "k"})
        r1.signals.append({"signal_id": "s"})
        r1.tests_added.append("t.py")
        r1.errors.append({"error": "e"})
        assert r2.applied_edits == []
        assert r2.pin_proposals == []
        assert r2.edge_proposals == []
        assert r2.under_spec_events == []
        assert r2.signals == []
        assert r2.tests_added == []
        assert r2.errors == []

    def test_mutable_fields(self) -> None:
        r = ImplementationRunResult()
        r.functions_implemented = 5
        r.functions_skipped = 2
        r.patch_path = "/tmp/patch.diff"
        r.notes_path = "/tmp/notes.md"
        assert r.functions_implemented == 5
        assert r.functions_skipped == 2
        assert r.patch_path == "/tmp/patch.diff"
        assert r.notes_path == "/tmp/notes.md"


# ======================================================================
# _classify_under_spec
# ======================================================================


class TestClassifyUnderSpec:
    def test_missing_constraint_maps_to_ambiguous_spec(self) -> None:
        event = UnderSpecEvent(kind="MISSING_CONSTRAINT", question="Q")
        assert _classify_under_spec(event) == "AMBIGUOUS_SPEC"

    def test_conflicting_constraints_maps_to_conflicting_requirements(self) -> None:
        event = UnderSpecEvent(kind="CONFLICTING_CONSTRAINTS", question="Q")
        assert _classify_under_spec(event) == "CONFLICTING_REQUIREMENTS"

    def test_external_dep_unknown_maps_to_missing_interface(self) -> None:
        event = UnderSpecEvent(kind="EXTERNAL_DEP_UNKNOWN", question="Q")
        assert _classify_under_spec(event) == "MISSING_INTERFACE"

    def test_needs_product_decision_maps_to_ambiguous_spec(self) -> None:
        event = UnderSpecEvent(kind="NEEDS_PRODUCT_DECISION", question="Q")
        assert _classify_under_spec(event) == "AMBIGUOUS_SPEC"

    def test_needs_api_decision_maps_to_missing_interface(self) -> None:
        event = UnderSpecEvent(kind="NEEDS_API_DECISION", question="Q")
        assert _classify_under_spec(event) == "MISSING_INTERFACE"

    def test_unknown_kind_defaults_to_ambiguous_spec(self) -> None:
        event = UnderSpecEvent(kind="MISSING_CONSTRAINT", question="Q")
        event.kind = "TOTALLY_UNKNOWN"  # type: ignore[assignment]
        assert _classify_under_spec(event) == "AMBIGUOUS_SPEC"


# ======================================================================
# _write_artifacts
# ======================================================================


class TestWriteArtifacts:
    def test_writes_pin_proposals(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        pins = [PinProposal(pin_id="PIN-1", fqn="foo:bar", file="foo.py")]

        ImplementationRunner._write_artifacts(tmp_path, result, pins, [], [], [], [])

        path = tmp_path / "pin_proposals.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["pin_id"] == "PIN-1"

    def test_writes_edge_proposals(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        edges = [EdgeProposal(src="PIN-1", dst="PIN-2")]

        ImplementationRunner._write_artifacts(tmp_path, result, [], edges, [], [], [])

        path = tmp_path / "edge_proposals.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["src"] == "PIN-1"
        assert data[0]["dst"] == "PIN-2"

    def test_writes_under_spec_events(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        events = [UnderSpecEvent(kind="MISSING_CONSTRAINT", question="Why?")]

        ImplementationRunner._write_artifacts(tmp_path, result, [], [], events, [], [])

        path = tmp_path / "under_spec_events.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["kind"] == "MISSING_CONSTRAINT"
        assert data[0]["question"] == "Why?"

    def test_writes_signals_json(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        signal = CoordinationSignal(
            run_id="run-1",
            layer="l1",
            classification="AMBIGUOUS_SPEC",
        )

        ImplementationRunner._write_artifacts(
            tmp_path, result, [], [], [], [], [], signals=[signal]
        )

        path = tmp_path / "signals.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["run_id"] == "run-1"
        assert data[0]["layer"] == "l1"
        assert data[0]["classification"] == "AMBIGUOUS_SPEC"
        assert data[0]["signal_id"]  # auto-generated

    def test_skips_signals_when_empty(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()

        ImplementationRunner._write_artifacts(tmp_path, result, [], [], [], [], [])

        assert not (tmp_path / "signals.json").exists()

    def test_writes_tests_added(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        tests = [TestArtifact(path="test_foo.py", purpose="unit test")]

        ImplementationRunner._write_artifacts(tmp_path, result, [], [], [], tests, [])

        path = tmp_path / "tests_added.json"
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["path"] == "test_foo.py"

    def test_writes_notes(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        notes = ["First note", "Second note"]

        ImplementationRunner._write_artifacts(tmp_path, result, [], [], [], [], notes)

        path = tmp_path / "notes.md"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert "First note" in content
        assert "Second note" in content
        assert "\n\n---\n\n" in content
        assert result.notes_path == str(path)

    def test_skips_empty_collections(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()

        ImplementationRunner._write_artifacts(tmp_path, result, [], [], [], [], [])

        assert not (tmp_path / "pin_proposals.json").exists()
        assert not (tmp_path / "edge_proposals.json").exists()
        assert not (tmp_path / "under_spec_events.json").exists()
        assert not (tmp_path / "signals.json").exists()
        assert not (tmp_path / "tests_added.json").exists()
        assert not (tmp_path / "notes.md").exists()

    def test_sets_patch_path_when_pins_present(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        pins = [PinProposal(pin_id="PIN-1", fqn="f", file="f.py")]

        ImplementationRunner._write_artifacts(tmp_path, result, pins, [], [], [], [])

        assert result.patch_path == str(tmp_path / "patch.diff")

    def test_writes_all_artifacts_together(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        pins = [PinProposal(pin_id="PIN-1", fqn="f", file="f.py")]
        edges = [EdgeProposal(src="PIN-1", dst="PIN-2")]
        events = [UnderSpecEvent(question="Q")]
        tests = [TestArtifact(path="t.py", purpose="p")]
        notes = ["note"]
        signal = CoordinationSignal(run_id="run-1", layer="l1")

        ImplementationRunner._write_artifacts(
            tmp_path, result, pins, edges, events, tests, notes, signals=[signal]
        )

        assert (tmp_path / "pin_proposals.json").exists()
        assert (tmp_path / "edge_proposals.json").exists()
        assert (tmp_path / "under_spec_events.json").exists()
        assert (tmp_path / "signals.json").exists()
        assert (tmp_path / "tests_added.json").exists()
        assert (tmp_path / "notes.md").exists()

    def test_artifact_json_is_formatted(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        pins = [PinProposal(pin_id="PIN-1", fqn="f", file="f.py")]

        ImplementationRunner._write_artifacts(tmp_path, result, pins, [], [], [], [])

        content = (tmp_path / "pin_proposals.json").read_text(encoding="utf-8")
        assert "\n" in content
        assert "  " in content

    def test_signals_json_is_formatted(self, tmp_path: Path) -> None:
        result = ImplementationRunResult()
        signal = CoordinationSignal(run_id="run-1", layer="l1")

        ImplementationRunner._write_artifacts(
            tmp_path, result, [], [], [], [], [], signals=[signal]
        )

        content = (tmp_path / "signals.json").read_text(encoding="utf-8")
        assert "\n" in content
        assert "  " in content
