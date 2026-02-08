"""Tests for labyrinth engine modules."""

from spec_manager.labyrinth.core.record import InputRecord
from spec_manager.labyrinth.engine.conditions import (
    Condition,
    ConditionGroup,
    ConditionOperator,
    LogicOperator,
)
from spec_manager.labyrinth.engine.registry import RuleRegistry
from spec_manager.labyrinth.engine.rule import (
    CompositeRule,
    CompositionMode,
    Rule,
    RuleChain,
)


class TestCondition:
    def test_eq(self):
        cond = Condition("type", ConditionOperator.EQ, "INVOICE")
        record = InputRecord("r1", data={"type": "INVOICE"})
        assert cond.evaluate(record) is True

    def test_neq(self):
        cond = Condition("type", ConditionOperator.NEQ, "INVOICE")
        record = InputRecord("r1", data={"type": "PAYMENT"})
        assert cond.evaluate(record) is True

    def test_gt(self):
        cond = Condition("amount", ConditionOperator.GT, 1000)
        assert cond.evaluate(InputRecord("r1", data={"amount": 1500})) is True
        assert cond.evaluate(InputRecord("r1", data={"amount": 500})) is False

    def test_in_operator(self):
        cond = Condition("currency", ConditionOperator.IN, ["USD", "EUR"])
        assert cond.evaluate(InputRecord("r1", data={"currency": "USD"})) is True
        assert cond.evaluate(InputRecord("r1", data={"currency": "GBP"})) is False

    def test_contains(self):
        cond = Condition("name", ConditionOperator.CONTAINS, "test")
        assert cond.evaluate(InputRecord("r1", data={"name": "a_test_value"})) is True

    def test_missing_field(self):
        cond = Condition("missing", ConditionOperator.EQ, "val")
        assert cond.evaluate(InputRecord("r1", data={})) is False


class TestConditionGroup:
    def test_and_all_true(self):
        group = ConditionGroup(logic=LogicOperator.AND)
        group.add(Condition("amount", ConditionOperator.GT, 100))
        group.add(Condition("type", ConditionOperator.EQ, "INVOICE"))
        record = InputRecord("r1", data={"amount": 500, "type": "INVOICE"})
        assert group.evaluate(record) is True

    def test_and_one_false(self):
        group = ConditionGroup(logic=LogicOperator.AND)
        group.add(Condition("amount", ConditionOperator.GT, 1000))
        group.add(Condition("type", ConditionOperator.EQ, "INVOICE"))
        record = InputRecord("r1", data={"amount": 500, "type": "INVOICE"})
        assert group.evaluate(record) is False

    def test_or_one_true(self):
        group = ConditionGroup(logic=LogicOperator.OR)
        group.add(Condition("amount", ConditionOperator.GT, 1000))
        group.add(Condition("type", ConditionOperator.EQ, "INVOICE"))
        record = InputRecord("r1", data={"amount": 500, "type": "INVOICE"})
        assert group.evaluate(record) is True

    def test_empty_group(self):
        group = ConditionGroup()
        assert group.evaluate(InputRecord("r1")) is True

    def test_nested_groups(self):
        inner = ConditionGroup(logic=LogicOperator.OR)
        inner.add(Condition("type", ConditionOperator.EQ, "INVOICE"))
        inner.add(Condition("type", ConditionOperator.EQ, "PAYMENT"))

        outer = ConditionGroup(logic=LogicOperator.AND)
        outer.add(Condition("amount", ConditionOperator.GT, 100))
        outer.add(inner)

        assert outer.evaluate(InputRecord("r1", data={"amount": 500, "type": "INVOICE"})) is True
        assert outer.evaluate(InputRecord("r1", data={"amount": 500, "type": "OTHER"})) is False
        assert outer.evaluate(InputRecord("r1", data={"amount": 50, "type": "INVOICE"})) is False


class TestRule:
    def test_evaluate_matching(self):
        rule = Rule(
            rule_id="R1",
            name="test_rule",
            conditions=ConditionGroup(),
            transform=lambda r: {"result": "ok"},
        )
        result = rule.evaluate(InputRecord("r1"))
        assert result is not None
        assert result.data["result"] == "ok"
        assert result.source_rule_id == "R1"

    def test_evaluate_no_match(self):
        cond = ConditionGroup()
        cond.add(Condition("amount", ConditionOperator.GT, 99999))
        rule = Rule(rule_id="R1", name="test", conditions=cond, transform=lambda r: {})
        result = rule.evaluate(InputRecord("r1", data={"amount": 100}))
        assert result is None

    def test_evaluate_no_transform(self):
        rule = Rule(rule_id="R1", name="test")
        result = rule.evaluate(InputRecord("r1"))
        assert result is None


class TestCompositeRule:
    def test_sequential(self):
        r1 = Rule("R1", "r1", transform=lambda r: {"step1": True})
        r2 = Rule("R2", "r2", transform=lambda r: {"step2": True})
        comp = CompositeRule("C1", "comp", mode=CompositionMode.SEQUENTIAL, sub_rules=[r1, r2])
        result = comp.evaluate(InputRecord("r1"))
        assert result is not None
        assert "R1" in result.applied_rules
        assert "R2" in result.applied_rules

    def test_parallel(self):
        r1 = Rule("R1", "r1", transform=lambda r: {"a": 1})
        r2 = Rule("R2", "r2", transform=lambda r: {"b": 2})
        comp = CompositeRule("C1", "comp", mode=CompositionMode.PARALLEL, sub_rules=[r1, r2])
        result = comp.evaluate(InputRecord("r1"))
        assert result is not None
        assert result.data["a"] == 1
        assert result.data["b"] == 2

    def test_conditional_first_match(self):
        cond1 = ConditionGroup()
        cond1.add(Condition("type", ConditionOperator.EQ, "INVOICE"))
        r1 = Rule("R1", "r1", conditions=cond1, transform=lambda r: {"matched": "r1"})
        r2 = Rule("R2", "r2", transform=lambda r: {"matched": "r2"})
        comp = CompositeRule("C1", "comp", mode=CompositionMode.CONDITIONAL, sub_rules=[r1, r2])

        result = comp.evaluate(InputRecord("r1", data={"type": "INVOICE"}))
        assert result is not None
        assert result.data["matched"] == "r1"


class TestRuleChain:
    def test_dependency_ordering(self):
        r1 = Rule("R1", "r1")
        r2 = Rule("R2", "r2", dependencies=["R1"])
        r3 = Rule("R3", "r3", dependencies=["R2"])
        chain = RuleChain("chain1", rules=[r3, r1, r2])
        order = chain.get_execution_order()
        ids = [r.rule_id for r in order]
        assert ids.index("R1") < ids.index("R2")
        assert ids.index("R2") < ids.index("R3")


class TestRuleRegistry:
    def test_register_and_get(self):
        reg = RuleRegistry()
        rule = Rule("R1", "test", group="ledger")
        reg.register(rule)
        assert reg.get("R1") is rule
        assert reg.has("R1")
        assert len(reg) == 1

    def test_get_by_group(self):
        reg = RuleRegistry()
        reg.register(Rule("R1", "r1", group="ledger"))
        reg.register(Rule("R2", "r2", group="payments"))
        reg.register(Rule("R3", "r3", group="ledger"))
        assert len(reg.get_by_group("ledger")) == 2

    def test_remove(self):
        reg = RuleRegistry()
        reg.register(Rule("R1", "r1"))
        reg.remove("R1")
        assert not reg.has("R1")
        assert len(reg) == 0
