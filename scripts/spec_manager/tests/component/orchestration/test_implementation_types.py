from __future__ import annotations

from spec_manager.orchestration.implementation.types import (
    EdgeProposal,
    EditEntry,
    FunctionTarget,
    ImplementorOutput,
    PinProposal,
    TestArtifact,
    UnderSpecEvent,
)

# ======================================================================
# PinProposal
# ======================================================================


class TestPinProposal:
    def test_defaults(self) -> None:
        p = PinProposal(pin_id="PIN-1", fqn="foo:bar", file="foo.py")
        assert p.pin_id == "PIN-1"
        assert p.fqn == "foo:bar"
        assert p.file == "foo.py"
        assert p.role == "ATOM"
        assert p.span is None
        assert p.atom_id_hint is None
        assert p.evidence_paths == []

    def test_from_dict_minimal(self) -> None:
        p = PinProposal.from_dict({})
        assert p.pin_id == ""
        assert p.fqn == ""
        assert p.file == ""
        assert p.role == "ATOM"

    def test_from_dict_full(self) -> None:
        d = {
            "pin_id": "PIN-99",
            "fqn": "mod:cls.method",
            "file": "src/mod.py",
            "role": "STORE",
            "span": {"start": 10, "end": 20},
            "atom_id_hint": "ATM-5",
            "evidence_paths": ["/ev/1.json"],
        }
        p = PinProposal.from_dict(d)
        assert p.pin_id == "PIN-99"
        assert p.role == "STORE"
        assert p.span == {"start": 10, "end": 20}
        assert p.atom_id_hint == "ATM-5"
        assert p.evidence_paths == ["/ev/1.json"]

    def test_to_dict_round_trip(self) -> None:
        d = {
            "pin_id": "PIN-1",
            "fqn": "foo:bar",
            "file": "foo.py",
            "role": "TEST",
            "span": {"start": 1, "end": 5},
            "atom_id_hint": "ATM-1",
            "evidence_paths": ["a.json", "b.json"],
        }
        p = PinProposal.from_dict(d)
        assert p.to_dict() == d

    def test_evidence_paths_not_shared(self) -> None:
        p1 = PinProposal(pin_id="a", fqn="a", file="a")
        p2 = PinProposal(pin_id="b", fqn="b", file="b")
        p1.evidence_paths.append("x")
        assert p2.evidence_paths == []


# ======================================================================
# EdgeProposal
# ======================================================================


class TestEdgeProposal:
    def test_defaults(self) -> None:
        e = EdgeProposal(src="PIN-1", dst="PIN-2")
        assert e.src == "PIN-1"
        assert e.dst == "PIN-2"
        assert e.signal_type == "CALL"
        assert e.weight == 0.7
        assert e.evidence_paths == []

    def test_from_dict_minimal(self) -> None:
        e = EdgeProposal.from_dict({})
        assert e.src == ""
        assert e.dst == ""
        assert e.signal_type == "CALL"
        assert e.weight == 0.7

    def test_from_dict_full(self) -> None:
        d = {
            "src": "PIN-A",
            "dst": "PIN-B",
            "signal_type": "STORE_TOUCH",
            "weight": 0.9,
            "evidence_paths": ["/ev/edge.json"],
        }
        e = EdgeProposal.from_dict(d)
        assert e.src == "PIN-A"
        assert e.signal_type == "STORE_TOUCH"
        assert e.weight == 0.9
        assert e.evidence_paths == ["/ev/edge.json"]

    def test_to_dict_round_trip(self) -> None:
        d = {
            "src": "PIN-1",
            "dst": "PIN-2",
            "signal_type": "EVENT_EMIT",
            "weight": 0.5,
            "evidence_paths": ["p.json"],
        }
        e = EdgeProposal.from_dict(d)
        assert e.to_dict() == d

    def test_evidence_paths_not_shared(self) -> None:
        e1 = EdgeProposal(src="a", dst="b")
        e2 = EdgeProposal(src="c", dst="d")
        e1.evidence_paths.append("x")
        assert e2.evidence_paths == []


# ======================================================================
# TestArtifact
# ======================================================================


class TestTestArtifact:
    def test_defaults(self) -> None:
        t = TestArtifact(path="test_foo.py", purpose="unit test")
        assert t.path == "test_foo.py"
        assert t.purpose == "unit test"
        assert t.scope == "UNIT"
        assert t.runner_hint is None
        assert t.unified_diff == ""

    def test_from_dict_minimal(self) -> None:
        t = TestArtifact.from_dict({})
        assert t.path == ""
        assert t.purpose == ""
        assert t.scope == "UNIT"

    def test_from_dict_full(self) -> None:
        d = {
            "path": "tests/test_auth.py",
            "purpose": "integration test for auth",
            "scope": "INTEGRATION",
            "runner_hint": "pytest -k auth",
            "unified_diff": "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new",
        }
        t = TestArtifact.from_dict(d)
        assert t.path == "tests/test_auth.py"
        assert t.scope == "INTEGRATION"
        assert t.runner_hint == "pytest -k auth"
        assert t.unified_diff.startswith("---")

    def test_to_dict_round_trip(self) -> None:
        d = {
            "path": "test_x.py",
            "purpose": "check x",
            "scope": "SLICE",
            "runner_hint": None,
            "unified_diff": "diff content",
        }
        t = TestArtifact.from_dict(d)
        assert t.to_dict() == d


# ======================================================================
# UnderSpecEvent
# ======================================================================


class TestUnderSpecEvent:
    def test_defaults(self) -> None:
        u = UnderSpecEvent()
        assert u.kind == "MISSING_CONSTRAINT"
        assert u.question == ""
        assert u.options == []
        assert u.needed_for is None
        assert u.evidence_paths == []

    def test_from_dict_minimal(self) -> None:
        u = UnderSpecEvent.from_dict({})
        assert u.kind == "MISSING_CONSTRAINT"
        assert u.question == ""

    def test_from_dict_full(self) -> None:
        d = {
            "kind": "CONFLICTING_CONSTRAINTS",
            "question": "Which API version?",
            "options": ["v1", "v2"],
            "needed_for": "auth.login",
            "evidence_paths": ["/ev/conflict.json"],
        }
        u = UnderSpecEvent.from_dict(d)
        assert u.kind == "CONFLICTING_CONSTRAINTS"
        assert u.question == "Which API version?"
        assert u.options == ["v1", "v2"]
        assert u.needed_for == "auth.login"
        assert u.evidence_paths == ["/ev/conflict.json"]

    def test_to_dict_round_trip(self) -> None:
        d = {
            "kind": "NEEDS_API_DECISION",
            "question": "REST or gRPC?",
            "options": ["REST", "gRPC"],
            "needed_for": "transport_layer",
            "evidence_paths": [],
        }
        u = UnderSpecEvent.from_dict(d)
        assert u.to_dict() == d

    def test_options_not_shared(self) -> None:
        u1 = UnderSpecEvent()
        u2 = UnderSpecEvent()
        u1.options.append("opt")
        assert u2.options == []

    def test_evidence_paths_not_shared(self) -> None:
        u1 = UnderSpecEvent()
        u2 = UnderSpecEvent()
        u1.evidence_paths.append("path")
        assert u2.evidence_paths == []


# ======================================================================
# FunctionTarget
# ======================================================================


class TestFunctionTarget:
    def test_defaults(self) -> None:
        ft = FunctionTarget(file="foo.py", fqn="foo:bar")
        assert ft.file == "foo.py"
        assert ft.fqn == "foo:bar"
        assert ft.signature == ""
        assert ft.span_hint is None

    def test_from_dict_minimal(self) -> None:
        ft = FunctionTarget.from_dict({})
        assert ft.file == ""
        assert ft.fqn == ""
        assert ft.signature == ""
        assert ft.span_hint is None

    def test_from_dict_full(self) -> None:
        d = {
            "file": "src/core.py",
            "fqn": "core:Engine.run",
            "signature": "def run(self) -> None",
            "span_hint": {"start": 42, "end": 80},
        }
        ft = FunctionTarget.from_dict(d)
        assert ft.file == "src/core.py"
        assert ft.fqn == "core:Engine.run"
        assert ft.signature == "def run(self) -> None"
        assert ft.span_hint == {"start": 42, "end": 80}


# ======================================================================
# EditEntry
# ======================================================================


class TestEditEntry:
    def test_defaults(self) -> None:
        e = EditEntry(path="foo.py")
        assert e.path == "foo.py"
        assert e.unified_diff == ""

    def test_from_dict_minimal(self) -> None:
        e = EditEntry.from_dict({})
        assert e.path == ""
        assert e.unified_diff == ""

    def test_from_dict_full(self) -> None:
        d = {"path": "bar.py", "unified_diff": "--- a\n+++ b\n"}
        e = EditEntry.from_dict(d)
        assert e.path == "bar.py"
        assert e.unified_diff == "--- a\n+++ b\n"


# ======================================================================
# ImplementorOutput
# ======================================================================


class TestImplementorOutput:
    def test_defaults(self) -> None:
        out = ImplementorOutput()
        assert isinstance(out.function_target, FunctionTarget)
        assert out.edits == []
        assert out.pin_proposals == []
        assert out.edge_proposals == []
        assert out.tests == []
        assert out.under_spec_events == []
        assert out.notes_md == ""

    def test_no_legacy_fields(self) -> None:
        out = ImplementorOutput()
        assert not hasattr(out, "body")
        assert not hasattr(out, "imports_needed")
        assert not hasattr(out, "gaps")
        assert not hasattr(out, "is_legacy_format")

    def test_from_dict_new_schema(self) -> None:
        new_data = {
            "function_target": {"file": "foo.py", "fqn": "foo:bar"},
            "edits": [{"path": "foo.py", "unified_diff": "diff"}],
            "pin_proposals": [{"pin_id": "PIN-1", "fqn": "foo:bar", "file": "foo.py"}],
            "edge_proposals": [{"src": "PIN-1", "dst": "PIN-2", "signal_type": "CALL"}],
            "tests": [{"path": "test_foo.py", "purpose": "unit test", "scope": "UNIT"}],
            "under_spec_events": [{"kind": "MISSING_CONSTRAINT", "question": "How?"}],
            "notes_md": "Implementation notes",
        }
        out = ImplementorOutput.from_dict(new_data)
        assert out.function_target.file == "foo.py"
        assert out.function_target.fqn == "foo:bar"
        assert len(out.edits) == 1
        assert out.edits[0].path == "foo.py"
        assert out.edits[0].unified_diff == "diff"
        assert len(out.pin_proposals) == 1
        assert out.pin_proposals[0].pin_id == "PIN-1"
        assert len(out.edge_proposals) == 1
        assert out.edge_proposals[0].src == "PIN-1"
        assert out.edge_proposals[0].dst == "PIN-2"
        assert len(out.tests) == 1
        assert out.tests[0].path == "test_foo.py"
        assert len(out.under_spec_events) == 1
        assert out.under_spec_events[0].kind == "MISSING_CONSTRAINT"
        assert out.notes_md == "Implementation notes"

    def test_from_dict_empty(self) -> None:
        out = ImplementorOutput.from_dict({})
        assert isinstance(out.function_target, FunctionTarget)
        assert out.edits == []

    def test_from_dict_notes_fallback_to_notes_key(self) -> None:
        d = {"notes": "fallback value"}
        out = ImplementorOutput.from_dict(d)
        assert out.notes_md == "fallback value"

    def test_from_dict_notes_md_takes_priority(self) -> None:
        d = {"notes_md": "primary", "notes": "fallback"}
        out = ImplementorOutput.from_dict(d)
        assert out.notes_md == "primary"

    def test_list_fields_not_shared(self) -> None:
        o1 = ImplementorOutput()
        o2 = ImplementorOutput()
        o1.edits.append(EditEntry(path="x.py"))
        o1.pin_proposals.append(PinProposal(pin_id="p", fqn="f", file="f"))
        o1.edge_proposals.append(EdgeProposal(src="a", dst="b"))
        o1.tests.append(TestArtifact(path="t.py", purpose="p"))
        o1.under_spec_events.append(UnderSpecEvent())
        assert o2.edits == []
        assert o2.pin_proposals == []
        assert o2.edge_proposals == []
        assert o2.tests == []
        assert o2.under_spec_events == []

    def test_from_dict_multiple_edits(self) -> None:
        d = {
            "edits": [
                {"path": "a.py", "unified_diff": "diff-a"},
                {"path": "b.py", "unified_diff": "diff-b"},
                {"path": "c.py", "unified_diff": "diff-c"},
            ],
        }
        out = ImplementorOutput.from_dict(d)
        assert len(out.edits) == 3
        assert out.edits[0].path == "a.py"
        assert out.edits[2].unified_diff == "diff-c"

    def test_from_dict_multiple_under_spec_events(self) -> None:
        d = {
            "under_spec_events": [
                {"kind": "MISSING_CONSTRAINT", "question": "Q1"},
                {"kind": "NEEDS_PRODUCT_DECISION", "question": "Q2"},
            ],
        }
        out = ImplementorOutput.from_dict(d)
        assert len(out.under_spec_events) == 2
        assert out.under_spec_events[0].kind == "MISSING_CONSTRAINT"
        assert out.under_spec_events[1].kind == "NEEDS_PRODUCT_DECISION"
