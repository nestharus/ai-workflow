"""Tests for planner.constraints.types — serialization round-trip for all types."""

from __future__ import annotations

import json

import pytest
from spec_manager.planner.constraints.types import (
    ConflictReport,
    ConstraintContext,
    ConstraintFact,
    ConstraintHypothesis,
    ConstraintIndexEntry,
    DecisionRequirement,
    ImpactClassification,
    ProblemFrame,
)

# ===================================================================
# ConstraintFact
# ===================================================================


class TestConstraintFact:
    def test_defaults(self):
        f = ConstraintFact()
        assert f.constraint_id == ""
        assert f.source == "existing"
        assert f.confidence == 1.0
        assert f.validated is True
        assert f.dimension == "software"
        assert f.authority_required == "planner_ok"
        assert f.scope == "intra:LIB"
        assert f.status == "ACTIVE"
        assert f.applies_to_layers == []
        assert f.supersedes == []
        assert f.trace == []

    def test_round_trip(self):
        f = ConstraintFact(
            constraint_id="CON-001",
            question="Which auth protocol?",
            answer="OAuth2",
            source="user",
            confidence=0.9,
            validated=True,
            dimension="software",
            authority_required="human_required",
            decision_type="technology_choice",
            scope="inter:A->B:handle",
            applies_to_layers=["L1", "L2"],
            status="ACTIVE",
            supersedes=["CON-000"],
            trace=["bootstrapped from intake"],
        )
        d = f.to_dict()
        f2 = ConstraintFact.from_dict(d)
        assert f2 == f

    def test_json_round_trip(self):
        f = ConstraintFact(constraint_id="X", question="Q", answer="A")
        s = json.dumps(f.to_dict())
        f2 = ConstraintFact.from_dict(json.loads(s))
        assert f2 == f

    def test_from_dict_defaults(self):
        f = ConstraintFact.from_dict({})
        assert f.constraint_id == ""
        assert f.source == "existing"
        assert f.dimension == "software"
        assert f.status == "ACTIVE"

    def test_list_fields_are_copies(self):
        d = {"applies_to_layers": ["L1"], "supersedes": ["X"], "trace": ["t"]}
        f = ConstraintFact.from_dict(d)
        d["applies_to_layers"].append("L3")
        assert f.applies_to_layers == ["L1"]

    def test_to_dict_list_fields_are_copies(self):
        f = ConstraintFact(applies_to_layers=["L1"])
        d = f.to_dict()
        d["applies_to_layers"].append("L3")
        assert f.applies_to_layers == ["L1"]

    def test_superseded_status(self):
        f = ConstraintFact(status="SUPERSEDED", supersedes=["CON-001"])
        d = f.to_dict()
        assert d["status"] == "SUPERSEDED"
        f2 = ConstraintFact.from_dict(d)
        assert f2.status == "SUPERSEDED"


# ===================================================================
# ConstraintHypothesis
# ===================================================================


class TestConstraintHypothesis:
    def test_defaults(self):
        h = ConstraintHypothesis()
        assert h.hypothesis_id == ""
        assert h.confidence == 0.0
        assert h.dimension == "software"
        assert h.reasoning == ""

    def test_round_trip(self):
        h = ConstraintHypothesis(
            hypothesis_id="HYP-001",
            question="How does retry work?",
            inferred_answer="Exponential backoff",
            source="llm_analysis",
            confidence=0.6,
            dimension="operational",
            reasoning="Inferred from retry patterns in code",
        )
        d = h.to_dict()
        h2 = ConstraintHypothesis.from_dict(d)
        assert h2 == h

    def test_json_round_trip(self):
        h = ConstraintHypothesis(hypothesis_id="H", question="Q")
        s = json.dumps(h.to_dict())
        h2 = ConstraintHypothesis.from_dict(json.loads(s))
        assert h2 == h

    def test_from_dict_defaults(self):
        h = ConstraintHypothesis.from_dict({})
        assert h.hypothesis_id == ""
        assert h.dimension == "software"


# ===================================================================
# DecisionRequirement
# ===================================================================


class TestDecisionRequirement:
    def test_defaults(self):
        d = DecisionRequirement()
        assert d.decision_id == ""
        assert d.dimension == "software"
        assert d.scope == "intra:LIB"
        assert d.options == []
        assert d.needed_for == []

    def test_round_trip(self):
        dr = DecisionRequirement(
            decision_id="DEC-001",
            question="SQL or NoSQL?",
            kind="technology_choice",
            dimension="software",
            scope="system",
            impact="HIGH",
            options=["PostgreSQL", "MongoDB"],
            needed_for=["DataStore", "QueryEngine"],
        )
        d = dr.to_dict()
        dr2 = DecisionRequirement.from_dict(d)
        assert dr2 == dr

    def test_json_round_trip(self):
        dr = DecisionRequirement(decision_id="D", options=["a", "b"])
        s = json.dumps(dr.to_dict())
        dr2 = DecisionRequirement.from_dict(json.loads(s))
        assert dr2 == dr

    def test_from_dict_defaults(self):
        dr = DecisionRequirement.from_dict({})
        assert dr.dimension == "software"
        assert dr.scope == "intra:LIB"

    def test_list_fields_are_copies(self):
        d = {"options": ["a"], "needed_for": ["b"]}
        dr = DecisionRequirement.from_dict(d)
        d["options"].append("c")
        assert dr.options == ["a"]


# ===================================================================
# ImpactClassification
# ===================================================================


class TestImpactClassification:
    def test_defaults(self):
        ic = ImpactClassification()
        assert ic.impact == "LOW"
        assert ic.blast_radius == "LOCAL"
        assert ic.reversibility == "EASY"
        assert ic.triggers == []

    def test_round_trip(self):
        ic = ImpactClassification(
            impact="HIGH",
            blast_radius="SYSTEM",
            reversibility="HARD",
            triggers=["cross_library_contract", "introduces_infra"],
        )
        d = ic.to_dict()
        ic2 = ImpactClassification.from_dict(d)
        assert ic2 == ic

    def test_json_round_trip(self):
        ic = ImpactClassification(impact="MEDIUM", triggers=["test"])
        s = json.dumps(ic.to_dict())
        ic2 = ImpactClassification.from_dict(json.loads(s))
        assert ic2 == ic

    def test_triggers_are_copies(self):
        d = {"triggers": ["a"]}
        ic = ImpactClassification.from_dict(d)
        d["triggers"].append("b")
        assert ic.triggers == ["a"]


# ===================================================================
# ProblemFrame
# ===================================================================


class TestProblemFrame:
    def test_defaults(self):
        pf = ProblemFrame()
        assert pf.goal == ""
        assert pf.domain_markers == []

    def test_round_trip(self):
        pf = ProblemFrame(
            goal="Build a payment processor",
            scope="PaymentLib",
            domain_markers=["PCI-DSS", "stripe"],
            decision_points=["gateway selection"],
            tradeoff_axes=["cost vs latency"],
            unknowns=["volume estimate"],
        )
        d = pf.to_dict()
        pf2 = ProblemFrame.from_dict(d)
        assert pf2 == pf

    def test_json_round_trip(self):
        pf = ProblemFrame(goal="test", unknowns=["x"])
        s = json.dumps(pf.to_dict())
        pf2 = ProblemFrame.from_dict(json.loads(s))
        assert pf2 == pf

    def test_list_fields_are_copies(self):
        d = {"domain_markers": ["a"], "unknowns": ["b"]}
        pf = ProblemFrame.from_dict(d)
        d["domain_markers"].append("c")
        assert pf.domain_markers == ["a"]


# ===================================================================
# ConstraintContext
# ===================================================================


class TestConstraintContext:
    def test_defaults(self):
        ctx = ConstraintContext()
        assert ctx.authoritative == []
        assert ctx.decisions == []
        assert ctx.unverified == []

    def test_round_trip(self):
        ctx = ConstraintContext(
            authoritative=[ConstraintFact(constraint_id="A")],
            decisions=[ConstraintFact(constraint_id="B", source="user")],
            unverified=[ConstraintHypothesis(hypothesis_id="H1")],
        )
        d = ctx.to_dict()
        ctx2 = ConstraintContext.from_dict(d)
        assert ctx2 == ctx

    def test_json_round_trip(self):
        ctx = ConstraintContext(
            authoritative=[ConstraintFact(constraint_id="X")],
        )
        s = json.dumps(ctx.to_dict())
        ctx2 = ConstraintContext.from_dict(json.loads(s))
        assert ctx2 == ctx

    def test_empty_from_dict(self):
        ctx = ConstraintContext.from_dict({})
        assert ctx.authoritative == []
        assert ctx.decisions == []
        assert ctx.unverified == []

    def test_nested_types_are_correct(self):
        ctx = ConstraintContext.from_dict(
            {
                "authoritative": [{"constraint_id": "C1"}],
                "decisions": [{"constraint_id": "C2"}],
                "unverified": [{"hypothesis_id": "H1"}],
            }
        )
        assert isinstance(ctx.authoritative[0], ConstraintFact)
        assert isinstance(ctx.decisions[0], ConstraintFact)
        assert isinstance(ctx.unverified[0], ConstraintHypothesis)


# ===================================================================
# ConflictReport
# ===================================================================


class TestConflictReport:
    def test_defaults(self):
        cr = ConflictReport()
        assert cr.conflicts == []

    def test_round_trip(self):
        cr = ConflictReport(
            conflicts=[
                {"a": "CON-001", "b": "CON-002", "reason": "contradictory answers"},
            ]
        )
        d = cr.to_dict()
        cr2 = ConflictReport.from_dict(d)
        assert cr2 == cr

    def test_json_round_trip(self):
        cr = ConflictReport(conflicts=[{"x": 1}])
        s = json.dumps(cr.to_dict())
        cr2 = ConflictReport.from_dict(json.loads(s))
        assert cr2 == cr

    def test_conflicts_are_copies(self):
        d = {"conflicts": [{"a": 1}]}
        cr = ConflictReport.from_dict(d)
        d["conflicts"].append({"b": 2})
        assert len(cr.conflicts) == 1


# ===================================================================
# ConstraintIndexEntry
# ===================================================================


class TestConstraintIndexEntry:
    def test_defaults(self):
        e = ConstraintIndexEntry()
        assert e.element_id == ""
        assert e.subtype == ""
        assert e.entities == []

    def test_round_trip(self):
        e = ConstraintIndexEntry(
            element_id="CON-LIB-001",
            subtype="performance",
            scope_hint="intra",
            entities=["PaymentEngine", "Stripe"],
            text_preview="Latency must not exceed 200ms",
        )
        d = e.to_dict()
        e2 = ConstraintIndexEntry.from_dict(d)
        assert e2 == e

    def test_json_round_trip(self):
        e = ConstraintIndexEntry(element_id="E", entities=["X"])
        s = json.dumps(e.to_dict())
        e2 = ConstraintIndexEntry.from_dict(json.loads(s))
        assert e2 == e

    def test_entities_are_copies(self):
        d = {"entities": ["a"]}
        e = ConstraintIndexEntry.from_dict(d)
        d["entities"].append("b")
        assert e.entities == ["a"]
