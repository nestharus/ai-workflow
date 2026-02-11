"""Factory for generating rules with domain vocabulary.

Rules are named with business domain terms like 'reconcile_ledger_delta',
'cascade_threshold_breach' - not generic RULE-001 names. This is part
of the obfuscation strategy.
"""

from __future__ import annotations

import random
from typing import Any

from spec_manager.labyrinth.core.record import InputRecord
from spec_manager.labyrinth.engine.conditions import (
    Condition,
    ConditionGroup,
    ConditionOperator,
    LogicOperator,
)
from spec_manager.labyrinth.engine.rule import (
    CompositeRule,
    CompositionMode,
    Rule,
)
from spec_manager.labyrinth.generator.level_config import LevelConfig

# Domain vocabulary for obfuscation
RULE_VERBS = [
    "reconcile",
    "cascade",
    "validate",
    "aggregate",
    "transform",
    "dispatch",
    "evaluate",
    "normalize",
    "enrich",
    "classify",
    "route",
    "filter",
    "merge",
    "split",
    "correlate",
    "compute",
    "derive",
    "project",
    "reduce",
    "accumulate",
]

RULE_NOUNS = [
    "ledger_delta",
    "threshold_breach",
    "payment_batch",
    "credit_memo",
    "invoice_line",
    "settlement_window",
    "margin_call",
    "risk_score",
    "compliance_flag",
    "audit_trail",
    "revenue_stream",
    "cost_center",
    "budget_variance",
    "accrual_entry",
    "depreciation_schedule",
    "interest_rate",
    "exchange_differential",
    "tax_obligation",
    "withholding_amount",
    "amortization_table",
    "capital_allocation",
    "liquidity_ratio",
    "solvency_metric",
    "exposure_limit",
    "counterparty_risk",
    "collateral_value",
    "mark_to_market",
    "position_delta",
    "hedge_effectiveness",
    "basis_spread",
    "yield_curve",
    "duration_gap",
]

RULE_GROUPS = [
    "ledger",
    "payments",
    "compliance",
    "risk",
    "reporting",
    "settlement",
    "treasury",
    "credit",
    "trading",
    "operations",
    "reconciliation",
    "valuation",
    "derivatives",
    "fixed_income",
    "equity",
    "fx",
]

FIELD_NAMES = [
    "amount",
    "type",
    "currency",
    "status",
    "priority",
    "category",
    "region",
    "department",
    "account_id",
    "entity_id",
    "counterparty",
    "instrument",
    "maturity_date",
    "rate",
    "volume",
    "notional",
]

FIELD_VALUES: dict[str, list[Any]] = {
    "type": ["INVOICE", "CREDIT_NOTE", "PAYMENT", "ADJUSTMENT", "TRANSFER"],
    "currency": ["USD", "EUR", "GBP", "JPY", "CHF"],
    "status": ["PENDING", "APPROVED", "REJECTED", "SETTLED", "CANCELLED"],
    "priority": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
    "category": ["TRADE", "SETTLEMENT", "CLEARING", "MARGIN", "COLLATERAL"],
    "region": ["NA", "EMEA", "APAC", "LATAM"],
    "department": ["TREASURY", "RISK", "COMPLIANCE", "OPERATIONS", "TRADING"],
}

OUTPUT_FIELDS = [
    "tax_rate",
    "route",
    "risk_level",
    "approval_status",
    "fee_amount",
    "discount_rate",
    "penalty",
    "margin_requirement",
    "reserve_amount",
    "adjusted_amount",
    "net_value",
    "gross_value",
    "accrued_interest",
    "settlement_amount",
    "clearing_fee",
    "commission",
]


class RuleFactory:
    """Factory for generating rules at a given complexity level."""

    def __init__(self, config: LevelConfig, rng: random.Random) -> None:
        self._config = config
        self._rng = rng
        self._used_names: set[str] = set()
        self._rule_counter = 0

    def generate_rules(self) -> list[Rule | CompositeRule]:
        """Generate all rules for the configured level."""
        rules: list[Rule | CompositeRule] = []

        num_composite = int(self._config.num_rules * self._config.composite_rule_ratio)
        num_simple = self._config.num_rules - num_composite

        # Generate simple rules first
        for _ in range(num_simple):
            rules.append(self._generate_simple_rule())

        # Generate composite rules
        for _ in range(num_composite):
            # Composite rules reference some of the simple rules as sub-rules
            available = [r for r in rules if isinstance(r, Rule)]
            rules.append(self._generate_composite_rule(available))

        # Add dependencies between rules
        self._add_dependencies(rules)

        return rules

    def _generate_simple_rule(self) -> Rule:
        """Generate a single simple rule with domain naming."""
        self._rule_counter += 1
        rule_id = f"RULE-L{self._config.level}-{self._rule_counter:04d}"
        name = self._generate_name()
        group = self._rng.choice(RULE_GROUPS[: self._config.num_rule_groups])

        conditions = self._generate_conditions()
        transform = self._generate_transform(rule_id)
        topic = f"topic.{group}.{self._rng.randint(1, self._config.num_bus_topics)}"
        output_topic = f"topic.{group}.output.{self._rule_counter}"

        return Rule(
            rule_id=rule_id,
            name=name,
            group=group,
            conditions=conditions,
            transform=transform,
            topics=[topic],
            output_topic=output_topic,
        )

    def _generate_composite_rule(self, available_rules: list[Rule]) -> CompositeRule:
        """Generate a composite rule referencing existing rules."""
        self._rule_counter += 1
        rule_id = f"RULE-L{self._config.level}-{self._rule_counter:04d}"
        name = self._generate_name()

        mode = self._rng.choice(list(CompositionMode))

        # Pick 2-4 sub-rules
        num_sub = min(self._rng.randint(2, 4), len(available_rules))
        sub_rules = self._rng.sample(available_rules, num_sub) if num_sub > 0 else []

        return CompositeRule(
            rule_id=rule_id,
            name=name,
            mode=mode,
            sub_rules=list(sub_rules),
            conditions=self._generate_conditions(),
        )

    def _generate_name(self) -> str:
        """Generate a unique domain-vocabulary rule name."""
        for _ in range(100):
            verb = self._rng.choice(RULE_VERBS)
            noun = self._rng.choice(RULE_NOUNS)
            name = f"{verb}_{noun}"
            if name not in self._used_names:
                self._used_names.add(name)
                return name
        # Fallback with counter
        name = f"rule_operation_{self._rule_counter}"
        self._used_names.add(name)
        return name

    def _generate_conditions(self) -> ConditionGroup:
        """Generate a condition group with random complexity."""
        num_conditions = self._rng.randint(1, self._config.max_conditions_per_rule)
        group = ConditionGroup(logic=self._rng.choice([LogicOperator.AND, LogicOperator.OR]))

        for _ in range(num_conditions):
            field_name = self._rng.choice(FIELD_NAMES)

            if field_name in FIELD_VALUES:
                # Categorical field
                operator = self._rng.choice([ConditionOperator.EQ, ConditionOperator.NEQ])
                value = self._rng.choice(FIELD_VALUES[field_name])
            else:
                # Numeric field
                operator = self._rng.choice(
                    [
                        ConditionOperator.GT,
                        ConditionOperator.GTE,
                        ConditionOperator.LT,
                        ConditionOperator.LTE,
                        ConditionOperator.EQ,
                    ]
                )
                value = self._rng.randint(100, 100000)

            group.add(Condition(field_name=field_name, operator=operator, value=value))

        return group

    def _generate_transform(self, rule_id: str) -> Any:
        """Generate a transform function for a rule."""
        # Pick random output fields and values
        num_outputs = self._rng.randint(1, 3)
        output_fields = self._rng.sample(OUTPUT_FIELDS, min(num_outputs, len(OUTPUT_FIELDS)))

        # Pre-compute the output values
        outputs: dict[str, Any] = {}
        for f in output_fields:
            if "rate" in f or "ratio" in f:
                outputs[f] = round(self._rng.uniform(0.01, 0.99), 2)
            elif "amount" in f or "value" in f or "fee" in f:
                outputs[f] = round(self._rng.uniform(10, 10000), 2)
            elif "level" in f or "status" in f or "route" in f:
                outputs[f] = self._rng.choice(["LOW", "MEDIUM", "HIGH", "APPROVED", "REJECTED"])
            else:
                outputs[f] = round(self._rng.uniform(0, 100), 2)

        frozen_outputs = dict(outputs)
        frozen_rule_id = rule_id

        def transform(record: InputRecord) -> dict[str, Any]:
            return {**frozen_outputs, "_source_rule": frozen_rule_id}

        return transform

    def _add_dependencies(self, rules: list[Rule | CompositeRule]) -> None:
        """Add dependency relationships between rules."""
        rule_ids = [r.rule_id for r in rules]

        for rule in rules:
            if not isinstance(rule, Rule):
                continue
            num_deps = self._rng.randint(0, self._config.max_rule_dependencies)
            available = [rid for rid in rule_ids if rid != rule.rule_id]
            if available and num_deps > 0:
                deps = self._rng.sample(available, min(num_deps, len(available)))
                rule.dependencies = deps
