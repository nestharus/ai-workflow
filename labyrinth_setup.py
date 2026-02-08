from spec_manager.labyrinth.engine.conditions import (
    Condition,
    ConditionGroup,
    ConditionOperator,
    LogicOperator,
)
from spec_manager.labyrinth.engine.rule import CompositeRule, CompositionMode, Rule
from spec_manager.labyrinth.integration.integration_points import IntegrationPoint
from spec_manager.labyrinth.integration.wiring import SideEffectChain


def setup_labyrinth(pipeline):
    # === Simple Rules (RULE-L3-0001 to RULE-L3-0167) ===

    rule_1 = Rule(
        rule_id="RULE-L3-0001",
        name="aggregate_threshold_breach",
        group="trading",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="LOW"),
                Condition(field_name="rate", operator=ConditionOperator.GT, value=4005),
            ],
        ),
        transform=lambda r: {"penalty": 23.27},
        dependencies=["RULE-L3-0138", "RULE-L3-0244", "RULE-L3-0186", "RULE-L3-0032", "RULE-L3-0049", "RULE-L3-0083", "RULE-L3-0216", "RULE-L3-0227"],
        topics=["topic.trading.1"],
        output_topic="topic.trading.output.1",
    )

    rule_2 = Rule(
        rule_id="RULE-L3-0002",
        name="project_budget_variance",
        group="fixed_income",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.GT, value=99558),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="CLEARING"),
            ],
        ),
        transform=lambda r: {"fee_amount": 9572.56, "approval_status": "HIGH"},
        dependencies=["RULE-L3-0188", "RULE-L3-0009"],
        topics=["topic.fixed_income.4"],
        output_topic="topic.fixed_income.output.2",
    )

    rule_3 = Rule(
        rule_id="RULE-L3-0003",
        name="validate_counterparty_risk",
        group="risk",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.GT, value=95747),
                Condition(field_name="volume", operator=ConditionOperator.EQ, value=16461),
                Condition(field_name="maturity_date", operator=ConditionOperator.GT, value=72457),
            ],
        ),
        transform=lambda r: {"gross_value": 1930.96, "adjusted_amount": 704.86},
        dependencies=["RULE-L3-0227", "RULE-L3-0251", "RULE-L3-0107", "RULE-L3-0248", "RULE-L3-0079"],
        topics=["topic.risk.8"],
        output_topic="topic.risk.output.3",
    )

    rule_4 = Rule(
        rule_id="RULE-L3-0004",
        name="classify_settlement_window",
        group="credit",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=83420),
            ],
        ),
        transform=lambda r: {"discount_rate": 0.36, "commission": 67.02},
        dependencies=["RULE-L3-0192", "RULE-L3-0241", "RULE-L3-0212", "RULE-L3-0230", "RULE-L3-0165", "RULE-L3-0240", "RULE-L3-0191"],
        topics=["topic.credit.3"],
        output_topic="topic.credit.output.4",
    )

    rule_5 = Rule(
        rule_id="RULE-L3-0005",
        name="accumulate_revenue_stream",
        group="credit",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.LT, value=83986),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="TREASURY"),
            ],
        ),
        transform=lambda r: {"route": "HIGH"},
        dependencies=["RULE-L3-0040", "RULE-L3-0201", "RULE-L3-0050", "RULE-L3-0029"],
        topics=["topic.credit.13"],
        output_topic="topic.credit.output.5",
    )

    rule_6 = Rule(
        rule_id="RULE-L3-0006",
        name="enrich_invoice_line",
        group="treasury",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="LATAM"),
                Condition(field_name="volume", operator=ConditionOperator.GTE, value=34818),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="HIGH"),
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=52450),
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=18231),
            ],
        ),
        transform=lambda r: {"commission": 4.71, "route": "LOW", "accrued_interest": 15.28},
        dependencies=["RULE-L3-0049", "RULE-L3-0008"],
        topics=["topic.treasury.6"],
        output_topic="topic.treasury.output.6",
    )

    rule_7 = Rule(
        rule_id="RULE-L3-0007",
        name="split_invoice_line",
        group="derivatives",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=1604),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="REJECTED"),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="SETTLED"),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="TRADE"),
            ],
        ),
        transform=lambda r: {"reserve_amount": 1794.73, "commission": 91.26, "accrued_interest": 87.05},
        dependencies=["RULE-L3-0157", "RULE-L3-0147", "RULE-L3-0158", "RULE-L3-0061"],
        topics=["topic.derivatives.10"],
        output_topic="topic.derivatives.output.7",
    )

    rule_8 = Rule(
        rule_id="RULE-L3-0008",
        name="derive_budget_variance",
        group="reporting",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.EQ, value=42587),
                Condition(field_name="notional", operator=ConditionOperator.GT, value=14762),
                Condition(field_name="instrument", operator=ConditionOperator.LT, value=31485),
            ],
        ),
        transform=lambda r: {"margin_requirement": 87.8},
        dependencies=["RULE-L3-0061", "RULE-L3-0177", "RULE-L3-0007"],
        topics=["topic.reporting.3"],
        output_topic="topic.reporting.output.8",
    )

    rule_9 = Rule(
        rule_id="RULE-L3-0009",
        name="validate_duration_gap",
        group="compliance",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="MEDIUM"),
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=79607),
                Condition(field_name="rate", operator=ConditionOperator.GTE, value=70786),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="LATAM"),
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=67939),
            ],
        ),
        transform=lambda r: {"approval_status": "MEDIUM", "commission": 6.4},
        dependencies=["RULE-L3-0022", "RULE-L3-0178", "RULE-L3-0201", "RULE-L3-0124", "RULE-L3-0036"],
        topics=["topic.compliance.1"],
        output_topic="topic.compliance.output.9",
    )

    rule_10 = Rule(
        rule_id="RULE-L3-0010",
        name="reduce_depreciation_schedule",
        group="credit",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.EQ, value="INVOICE"),
            ],
        ),
        transform=lambda r: {"net_value": 717.86},
        dependencies=["RULE-L3-0218", "RULE-L3-0156", "RULE-L3-0122", "RULE-L3-0184", "RULE-L3-0168", "RULE-L3-0097", "RULE-L3-0049", "RULE-L3-0220"],
        topics=["topic.credit.8"],
        output_topic="topic.credit.output.10",
    )

    rule_11 = Rule(
        rule_id="RULE-L3-0011",
        name="enrich_duration_gap",
        group="treasury",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=62093),
                Condition(field_name="rate", operator=ConditionOperator.GTE, value=12463),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="REJECTED"),
                Condition(field_name="rate", operator=ConditionOperator.LTE, value=61313),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="INVOICE"),
            ],
        ),
        transform=lambda r: {"net_value": 8618.11, "accrued_interest": 24.87},
        dependencies=["RULE-L3-0127", "RULE-L3-0123", "RULE-L3-0037", "RULE-L3-0043", "RULE-L3-0051", "RULE-L3-0059"],
        topics=["topic.treasury.7"],
        output_topic="topic.treasury.output.11",
    )

    rule_12 = Rule(
        rule_id="RULE-L3-0012",
        name="project_hedge_effectiveness",
        group="reporting",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=32842),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="CHF"),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="CANCELLED"),
                Condition(field_name="amount", operator=ConditionOperator.GT, value=98871),
            ],
        ),
        transform=lambda r: {"discount_rate": 0.41},
        dependencies=[],
        topics=["topic.reporting.16"],
        output_topic="topic.reporting.output.12",
    )

    rule_13 = Rule(
        rule_id="RULE-L3-0013",
        name="evaluate_collateral_value",
        group="payments",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.LTE, value=34860),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=55544),
            ],
        ),
        transform=lambda r: {"commission": 29.67, "risk_level": "LOW", "approval_status": "REJECTED"},
        dependencies=["RULE-L3-0197", "RULE-L3-0250", "RULE-L3-0004", "RULE-L3-0238", "RULE-L3-0071", "RULE-L3-0245"],
        topics=["topic.payments.2"],
        output_topic="topic.payments.output.13",
    )

    rule_14 = Rule(
        rule_id="RULE-L3-0014",
        name="route_credit_memo",
        group="payments",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.EQ, value="COLLATERAL"),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="USD"),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="JPY"),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="CANCELLED"),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="ADJUSTMENT"),
            ],
        ),
        transform=lambda r: {"net_value": 2050.55, "clearing_fee": 7164.76, "fee_amount": 2394.47},
        dependencies=["RULE-L3-0058", "RULE-L3-0192", "RULE-L3-0173", "RULE-L3-0254", "RULE-L3-0053", "RULE-L3-0195"],
        topics=["topic.payments.13"],
        output_topic="topic.payments.output.14",
    )

    rule_15 = Rule(
        rule_id="RULE-L3-0015",
        name="transform_amortization_table",
        group="equity",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.LTE, value=81516),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="CANCELLED"),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="EMEA"),
            ],
        ),
        transform=lambda r: {"risk_level": "MEDIUM", "clearing_fee": 3701.58},
        dependencies=["RULE-L3-0018", "RULE-L3-0047", "RULE-L3-0239"],
        topics=["topic.equity.6"],
        output_topic="topic.equity.output.15",
    )

    rule_16 = Rule(
        rule_id="RULE-L3-0016",
        name="correlate_amortization_table",
        group="ledger",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.EQ, value="REJECTED"),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="CANCELLED"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="HIGH"),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="EMEA"),
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=64132),
                Condition(field_name="account_id", operator=ConditionOperator.GT, value=12197),
            ],
        ),
        transform=lambda r: {"settlement_amount": 450.43, "commission": 33.36, "fee_amount": 1316.89},
        dependencies=["RULE-L3-0223", "RULE-L3-0159", "RULE-L3-0127", "RULE-L3-0178", "RULE-L3-0085", "RULE-L3-0119", "RULE-L3-0229"],
        topics=["topic.ledger.9"],
        output_topic="topic.ledger.output.16",
    )

    rule_17 = Rule(
        rule_id="RULE-L3-0017",
        name="dispatch_hedge_effectiveness",
        group="fixed_income",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.EQ, value="APPROVED"),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="TRANSFER"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="MEDIUM"),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="PAYMENT"),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="CREDIT_NOTE"),
            ],
        ),
        transform=lambda r: {"margin_requirement": 35.37, "net_value": 5603.24, "route": "APPROVED"},
        dependencies=["RULE-L3-0111", "RULE-L3-0105", "RULE-L3-0200"],
        topics=["topic.fixed_income.5"],
        output_topic="topic.fixed_income.output.17",
    )

    rule_18 = Rule(
        rule_id="RULE-L3-0018",
        name="normalize_revenue_stream",
        group="settlement",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="MARGIN"),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="RISK"),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="PENDING"),
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=26258),
            ],
        ),
        transform=lambda r: {"gross_value": 8207.16, "fee_amount": 8714.52},
        dependencies=[],
        topics=["topic.settlement.8"],
        output_topic="topic.settlement.output.18",
    )

    rule_19 = Rule(
        rule_id="RULE-L3-0019",
        name="reconcile_budget_variance",
        group="derivatives",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="GBP"),
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=43504),
                Condition(field_name="amount", operator=ConditionOperator.GT, value=34337),
            ],
        ),
        transform=lambda r: {"reserve_amount": 392.19},
        dependencies=["RULE-L3-0186", "RULE-L3-0082", "RULE-L3-0102", "RULE-L3-0158", "RULE-L3-0242", "RULE-L3-0192"],
        topics=["topic.derivatives.14"],
        output_topic="topic.derivatives.output.19",
    )

    rule_20 = Rule(
        rule_id="RULE-L3-0020",
        name="filter_capital_allocation",
        group="fixed_income",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=25014),
                Condition(field_name="account_id", operator=ConditionOperator.GT, value=93001),
                Condition(field_name="rate", operator=ConditionOperator.GT, value=68246),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="LATAM"),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="CHF"),
            ],
        ),
        transform=lambda r: {"approval_status": "HIGH", "gross_value": 5076.15},
        dependencies=["RULE-L3-0136", "RULE-L3-0166", "RULE-L3-0226", "RULE-L3-0182", "RULE-L3-0203", "RULE-L3-0010", "RULE-L3-0135", "RULE-L3-0029"],
        topics=["topic.fixed_income.14"],
        output_topic="topic.fixed_income.output.20",
    )

    rule_21 = Rule(
        rule_id="RULE-L3-0021",
        name="route_collateral_value",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="LATAM"),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="MARGIN"),
                Condition(field_name="amount", operator=ConditionOperator.LT, value=37706),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="APAC"),
                Condition(field_name="volume", operator=ConditionOperator.LTE, value=58054),
            ],
        ),
        transform=lambda r: {"penalty": 79.37, "reserve_amount": 9598.72, "margin_requirement": 73.6},
        dependencies=["RULE-L3-0118", "RULE-L3-0213", "RULE-L3-0226", "RULE-L3-0011", "RULE-L3-0256", "RULE-L3-0064", "RULE-L3-0134"],
        topics=["topic.operations.3"],
        output_topic="topic.operations.output.21",
    )

    rule_22 = Rule(
        rule_id="RULE-L3-0022",
        name="classify_liquidity_ratio",
        group="compliance",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.EQ, value="RISK"),
                Condition(field_name="amount", operator=ConditionOperator.GT, value=32192),
            ],
        ),
        transform=lambda r: {"risk_level": "APPROVED", "margin_requirement": 88.61},
        dependencies=["RULE-L3-0103", "RULE-L3-0253", "RULE-L3-0190", "RULE-L3-0011", "RULE-L3-0144", "RULE-L3-0101", "RULE-L3-0134", "RULE-L3-0197"],
        topics=["topic.compliance.7"],
        output_topic="topic.compliance.output.22",
    )

    rule_23 = Rule(
        rule_id="RULE-L3-0023",
        name="merge_duration_gap",
        group="derivatives",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.GT, value=55824),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="TRADING"),
            ],
        ),
        transform=lambda r: {"route": "MEDIUM", "reserve_amount": 9175.53},
        dependencies=[],
        topics=["topic.derivatives.4"],
        output_topic="topic.derivatives.output.23",
    )

    rule_24 = Rule(
        rule_id="RULE-L3-0024",
        name="correlate_compliance_flag",
        group="equity",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.EQ, value=94376),
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=58546),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="MARGIN"),
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=83679),
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=63617),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="OPERATIONS"),
            ],
        ),
        transform=lambda r: {"adjusted_amount": 2352.59},
        dependencies=["RULE-L3-0076", "RULE-L3-0114", "RULE-L3-0103"],
        topics=["topic.equity.11"],
        output_topic="topic.equity.output.24",
    )

    rule_25 = Rule(
        rule_id="RULE-L3-0025",
        name="route_settlement_window",
        group="reporting",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.GTE, value=92691),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="LATAM"),
            ],
        ),
        transform=lambda r: {"net_value": 4664.58, "reserve_amount": 632.03},
        dependencies=["RULE-L3-0200", "RULE-L3-0213", "RULE-L3-0075", "RULE-L3-0120"],
        topics=["topic.reporting.14"],
        output_topic="topic.reporting.output.25",
    )

    rule_26 = Rule(
        rule_id="RULE-L3-0026",
        name="merge_threshold_breach",
        group="derivatives",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.LT, value=98859),
                Condition(field_name="maturity_date", operator=ConditionOperator.LTE, value=70645),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="RISK"),
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=63754),
            ],
        ),
        transform=lambda r: {"accrued_interest": 33.61},
        dependencies=["RULE-L3-0110", "RULE-L3-0077"],
        topics=["topic.derivatives.13"],
        output_topic="topic.derivatives.output.26",
    )

    rule_27 = Rule(
        rule_id="RULE-L3-0027",
        name="dispatch_basis_spread",
        group="reporting",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=74075),
                Condition(field_name="amount", operator=ConditionOperator.GT, value=84346),
                Condition(field_name="rate", operator=ConditionOperator.GTE, value=60615),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="CLEARING"),
                Condition(field_name="maturity_date", operator=ConditionOperator.LT, value=27842),
            ],
        ),
        transform=lambda r: {"net_value": 7614.68, "discount_rate": 0.38},
        dependencies=[],
        topics=["topic.reporting.14"],
        output_topic="topic.reporting.output.27",
    )

    rule_28 = Rule(
        rule_id="RULE-L3-0028",
        name="enrich_settlement_window",
        group="fx",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=85315),
            ],
        ),
        transform=lambda r: {"route": "LOW"},
        dependencies=["RULE-L3-0233", "RULE-L3-0038", "RULE-L3-0120", "RULE-L3-0214", "RULE-L3-0167", "RULE-L3-0117", "RULE-L3-0024", "RULE-L3-0186"],
        topics=["topic.fx.8"],
        output_topic="topic.fx.output.28",
    )

    rule_29 = Rule(
        rule_id="RULE-L3-0029",
        name="evaluate_threshold_breach",
        group="reporting",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.GT, value=74020),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="APAC"),
            ],
        ),
        transform=lambda r: {"discount_rate": 0.61, "adjusted_amount": 7481.78},
        dependencies=["RULE-L3-0030", "RULE-L3-0048", "RULE-L3-0201", "RULE-L3-0151", "RULE-L3-0242", "RULE-L3-0230", "RULE-L3-0180", "RULE-L3-0141"],
        topics=["topic.reporting.4"],
        output_topic="topic.reporting.output.29",
    )

    rule_30 = Rule(
        rule_id="RULE-L3-0030",
        name="dispatch_amortization_table",
        group="risk",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="entity_id", operator=ConditionOperator.EQ, value=88881),
                Condition(field_name="maturity_date", operator=ConditionOperator.LTE, value=93818),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="EMEA"),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="CANCELLED"),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="REJECTED"),
            ],
        ),
        transform=lambda r: {"settlement_amount": 698.88, "net_value": 6478.96, "discount_rate": 0.02},
        dependencies=["RULE-L3-0102", "RULE-L3-0107"],
        topics=["topic.risk.14"],
        output_topic="topic.risk.output.30",
    )

    rule_31 = Rule(
        rule_id="RULE-L3-0031",
        name="compute_margin_call",
        group="fixed_income",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="MEDIUM"),
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=70639),
                Condition(field_name="notional", operator=ConditionOperator.LTE, value=57191),
            ],
        ),
        transform=lambda r: {"reserve_amount": 2462.5, "discount_rate": 0.93, "settlement_amount": 2796.49},
        dependencies=["RULE-L3-0117", "RULE-L3-0007", "RULE-L3-0047", "RULE-L3-0118", "RULE-L3-0153"],
        topics=["topic.fixed_income.15"],
        output_topic="topic.fixed_income.output.31",
    )

    rule_32 = Rule(
        rule_id="RULE-L3-0032",
        name="normalize_basis_spread",
        group="derivatives",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.LT, value=23934),
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=46607),
                Condition(field_name="account_id", operator=ConditionOperator.LT, value=36755),
            ],
        ),
        transform=lambda r: {"reserve_amount": 5171.11, "commission": 19.11, "tax_rate": 0.25},
        dependencies=["RULE-L3-0227", "RULE-L3-0118", "RULE-L3-0024"],
        topics=["topic.derivatives.14"],
        output_topic="topic.derivatives.output.32",
    )

    rule_33 = Rule(
        rule_id="RULE-L3-0033",
        name="compute_interest_rate",
        group="fx",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.GT, value=12296),
                Condition(field_name="entity_id", operator=ConditionOperator.GTE, value=53105),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="TRADING"),
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=72644),
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=97871),
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=92224),
            ],
        ),
        transform=lambda r: {"reserve_amount": 2521.52, "fee_amount": 1215.35},
        dependencies=["RULE-L3-0084", "RULE-L3-0179", "RULE-L3-0168", "RULE-L3-0234"],
        topics=["topic.fx.7"],
        output_topic="topic.fx.output.33",
    )

    rule_34 = Rule(
        rule_id="RULE-L3-0034",
        name="route_risk_score",
        group="settlement",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.LT, value=95072),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=25543),
            ],
        ),
        transform=lambda r: {"margin_requirement": 17.94, "discount_rate": 0.02},
        dependencies=["RULE-L3-0185", "RULE-L3-0189"],
        topics=["topic.settlement.5"],
        output_topic="topic.settlement.output.34",
    )

    rule_35 = Rule(
        rule_id="RULE-L3-0035",
        name="enrich_payment_batch",
        group="payments",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="LOW"),
                Condition(field_name="amount", operator=ConditionOperator.EQ, value=37368),
                Condition(field_name="notional", operator=ConditionOperator.LTE, value=57833),
                Condition(field_name="counterparty", operator=ConditionOperator.GTE, value=6834),
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=15053),
            ],
        ),
        transform=lambda r: {"accrued_interest": 49.17},
        dependencies=["RULE-L3-0024"],
        topics=["topic.payments.2"],
        output_topic="topic.payments.output.35",
    )

    rule_36 = Rule(
        rule_id="RULE-L3-0036",
        name="transform_audit_trail",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="CANCELLED"),
            ],
        ),
        transform=lambda r: {"margin_requirement": 38.04, "accrued_interest": 90.85, "reserve_amount": 2980.56},
        dependencies=["RULE-L3-0182"],
        topics=["topic.operations.14"],
        output_topic="topic.operations.output.36",
    )

    rule_37 = Rule(
        rule_id="RULE-L3-0037",
        name="classify_credit_memo",
        group="risk",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.GT, value=20685),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="TRADING"),
            ],
        ),
        transform=lambda r: {"discount_rate": 0.01},
        dependencies=["RULE-L3-0164", "RULE-L3-0094", "RULE-L3-0022", "RULE-L3-0136", "RULE-L3-0183", "RULE-L3-0100", "RULE-L3-0188"],
        topics=["topic.risk.15"],
        output_topic="topic.risk.output.37",
    )

    rule_38 = Rule(
        rule_id="RULE-L3-0038",
        name="accumulate_yield_curve",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="entity_id", operator=ConditionOperator.LT, value=92241),
            ],
        ),
        transform=lambda r: {"risk_level": "MEDIUM", "net_value": 9239.87},
        dependencies=["RULE-L3-0158", "RULE-L3-0245", "RULE-L3-0042", "RULE-L3-0098", "RULE-L3-0142", "RULE-L3-0099", "RULE-L3-0012", "RULE-L3-0198"],
        topics=["topic.operations.7"],
        output_topic="topic.operations.output.38",
    )

    rule_39 = Rule(
        rule_id="RULE-L3-0039",
        name="split_risk_score",
        group="credit",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=9459),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="PAYMENT"),
                Condition(field_name="entity_id", operator=ConditionOperator.LTE, value=16399),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=91815),
                Condition(field_name="maturity_date", operator=ConditionOperator.LT, value=65697),
                Condition(field_name="notional", operator=ConditionOperator.LTE, value=10643),
            ],
        ),
        transform=lambda r: {"route": "HIGH", "clearing_fee": 6041.1, "penalty": 2.59},
        dependencies=["RULE-L3-0235", "RULE-L3-0087"],
        topics=["topic.credit.8"],
        output_topic="topic.credit.output.39",
    )

    rule_40 = Rule(
        rule_id="RULE-L3-0040",
        name="reduce_threshold_breach",
        group="trading",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="COLLATERAL"),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=23888),
                Condition(field_name="rate", operator=ConditionOperator.LTE, value=12059),
                Condition(field_name="notional", operator=ConditionOperator.LT, value=53623),
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=87935),
            ],
        ),
        transform=lambda r: {"discount_rate": 0.33},
        dependencies=["RULE-L3-0043", "RULE-L3-0224"],
        topics=["topic.trading.16"],
        output_topic="topic.trading.output.40",
    )

    rule_41 = Rule(
        rule_id="RULE-L3-0041",
        name="classify_collateral_value",
        group="payments",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=42472),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="CANCELLED"),
                Condition(field_name="amount", operator=ConditionOperator.EQ, value=60652),
                Condition(field_name="rate", operator=ConditionOperator.GT, value=24686),
            ],
        ),
        transform=lambda r: {"gross_value": 4989.95, "adjusted_amount": 4425.99, "accrued_interest": 5.16},
        dependencies=["RULE-L3-0047", "RULE-L3-0198"],
        topics=["topic.payments.9"],
        output_topic="topic.payments.output.41",
    )

    rule_42 = Rule(
        rule_id="RULE-L3-0042",
        name="project_compliance_flag",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.EQ, value="CANCELLED"),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="COMPLIANCE"),
                Condition(field_name="amount", operator=ConditionOperator.EQ, value=53576),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="USD"),
            ],
        ),
        transform=lambda r: {"approval_status": "MEDIUM", "net_value": 4988.77},
        dependencies=[],
        topics=["topic.operations.10"],
        output_topic="topic.operations.output.42",
    )

    rule_43 = Rule(
        rule_id="RULE-L3-0043",
        name="derive_tax_obligation",
        group="fixed_income",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="TRADING"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="MEDIUM"),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="HIGH"),
                Condition(field_name="rate", operator=ConditionOperator.LT, value=66650),
            ],
        ),
        transform=lambda r: {"tax_rate": 0.72, "fee_amount": 8376.38},
        dependencies=["RULE-L3-0080", "RULE-L3-0081", "RULE-L3-0188", "RULE-L3-0198", "RULE-L3-0248", "RULE-L3-0116"],
        topics=["topic.fixed_income.16"],
        output_topic="topic.fixed_income.output.43",
    )

    rule_44 = Rule(
        rule_id="RULE-L3-0044",
        name="transform_hedge_effectiveness",
        group="fx",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.LTE, value=42276),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="LATAM"),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="TREASURY"),
            ],
        ),
        transform=lambda r: {"commission": 91.34, "gross_value": 3818.5},
        dependencies=["RULE-L3-0162", "RULE-L3-0048", "RULE-L3-0031", "RULE-L3-0232"],
        topics=["topic.fx.5"],
        output_topic="topic.fx.output.44",
    )

    rule_45 = Rule(
        rule_id="RULE-L3-0045",
        name="compute_payment_batch",
        group="reporting",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="PENDING"),
                Condition(field_name="volume", operator=ConditionOperator.GT, value=94792),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="MEDIUM"),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="GBP"),
                Condition(field_name="counterparty", operator=ConditionOperator.EQ, value=90894),
            ],
        ),
        transform=lambda r: {"risk_level": "HIGH", "settlement_amount": 8524.89},
        dependencies=["RULE-L3-0247", "RULE-L3-0053"],
        topics=["topic.reporting.13"],
        output_topic="topic.reporting.output.45",
    )

    rule_46 = Rule(
        rule_id="RULE-L3-0046",
        name="route_duration_gap",
        group="payments",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="RISK"),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="USD"),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="APPROVED"),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=6128),
                Condition(field_name="counterparty", operator=ConditionOperator.GT, value=38552),
            ],
        ),
        transform=lambda r: {"gross_value": 1464.24, "penalty": 53.12},
        dependencies=[],
        topics=["topic.payments.6"],
        output_topic="topic.payments.output.46",
    )

    rule_47 = Rule(
        rule_id="RULE-L3-0047",
        name="dispatch_cost_center",
        group="compliance",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="TRADING"),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="CRITICAL"),
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=33566),
                Condition(field_name="amount", operator=ConditionOperator.LTE, value=37800),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="MARGIN"),
            ],
        ),
        transform=lambda r: {"adjusted_amount": 9620.67, "net_value": 6906.23},
        dependencies=["RULE-L3-0004", "RULE-L3-0119", "RULE-L3-0129", "RULE-L3-0220"],
        topics=["topic.compliance.15"],
        output_topic="topic.compliance.output.47",
    )

    rule_48 = Rule(
        rule_id="RULE-L3-0048",
        name="classify_budget_variance",
        group="derivatives",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="TRADING"),
                Condition(field_name="instrument", operator=ConditionOperator.EQ, value=38880),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=86375),
                Condition(field_name="maturity_date", operator=ConditionOperator.LT, value=1161),
            ],
        ),
        transform=lambda r: {"route": "APPROVED", "clearing_fee": 8330.06, "adjusted_amount": 9030.32},
        dependencies=["RULE-L3-0141", "RULE-L3-0208", "RULE-L3-0002", "RULE-L3-0157", "RULE-L3-0227", "RULE-L3-0128", "RULE-L3-0062"],
        topics=["topic.derivatives.8"],
        output_topic="topic.derivatives.output.48",
    )

    rule_49 = Rule(
        rule_id="RULE-L3-0049",
        name="accumulate_solvency_metric",
        group="credit",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=82445),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="REJECTED"),
                Condition(field_name="volume", operator=ConditionOperator.GT, value=76065),
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=11913),
                Condition(field_name="entity_id", operator=ConditionOperator.LT, value=98073),
                Condition(field_name="rate", operator=ConditionOperator.GTE, value=26418),
            ],
        ),
        transform=lambda r: {"gross_value": 5313.22},
        dependencies=["RULE-L3-0152", "RULE-L3-0170", "RULE-L3-0123"],
        topics=["topic.credit.9"],
        output_topic="topic.credit.output.49",
    )

    rule_50 = Rule(
        rule_id="RULE-L3-0050",
        name="dispatch_exchange_differential",
        group="fx",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="PENDING"),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="CRITICAL"),
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=51817),
            ],
        ),
        transform=lambda r: {"reserve_amount": 5370.36},
        dependencies=["RULE-L3-0106", "RULE-L3-0115", "RULE-L3-0021", "RULE-L3-0155", "RULE-L3-0002", "RULE-L3-0064", "RULE-L3-0227"],
        topics=["topic.fx.15"],
        output_topic="topic.fx.output.50",
    )

    rule_51 = Rule(
        rule_id="RULE-L3-0051",
        name="filter_exchange_differential",
        group="derivatives",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.EQ, value="SETTLED"),
                Condition(field_name="amount", operator=ConditionOperator.EQ, value=73684),
                Condition(field_name="counterparty", operator=ConditionOperator.EQ, value=29115),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="GBP"),
                Condition(field_name="rate", operator=ConditionOperator.GT, value=18420),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="PAYMENT"),
            ],
        ),
        transform=lambda r: {"approval_status": "MEDIUM", "route": "REJECTED"},
        dependencies=["RULE-L3-0073", "RULE-L3-0160", "RULE-L3-0162", "RULE-L3-0144", "RULE-L3-0211", "RULE-L3-0213", "RULE-L3-0055", "RULE-L3-0013"],
        topics=["topic.derivatives.5"],
        output_topic="topic.derivatives.output.51",
    )

    rule_52 = Rule(
        rule_id="RULE-L3-0052",
        name="merge_basis_spread",
        group="valuation",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="LOW"),
                Condition(field_name="notional", operator=ConditionOperator.EQ, value=53592),
                Condition(field_name="account_id", operator=ConditionOperator.GT, value=90576),
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=58215),
                Condition(field_name="volume", operator=ConditionOperator.GTE, value=47637),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="CANCELLED"),
            ],
        ),
        transform=lambda r: {"gross_value": 2766.06, "tax_rate": 0.96, "penalty": 94.9},
        dependencies=["RULE-L3-0038", "RULE-L3-0015"],
        topics=["topic.valuation.15"],
        output_topic="topic.valuation.output.52",
    )

    rule_53 = Rule(
        rule_id="RULE-L3-0053",
        name="validate_accrual_entry",
        group="ledger",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.EQ, value="TRADING"),
            ],
        ),
        transform=lambda r: {"risk_level": "REJECTED"},
        dependencies=["RULE-L3-0010", "RULE-L3-0038", "RULE-L3-0220", "RULE-L3-0009", "RULE-L3-0172"],
        topics=["topic.ledger.7"],
        output_topic="topic.ledger.output.53",
    )

    rule_54 = Rule(
        rule_id="RULE-L3-0054",
        name="reduce_accrual_entry",
        group="credit",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.LT, value=19064),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="MEDIUM"),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="APPROVED"),
            ],
        ),
        transform=lambda r: {"gross_value": 7901.95},
        dependencies=["RULE-L3-0086", "RULE-L3-0237", "RULE-L3-0023", "RULE-L3-0013"],
        topics=["topic.credit.8"],
        output_topic="topic.credit.output.54",
    )

    rule_55 = Rule(
        rule_id="RULE-L3-0055",
        name="reduce_capital_allocation",
        group="ledger",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.EQ, value="ADJUSTMENT"),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="SETTLED"),
            ],
        ),
        transform=lambda r: {"gross_value": 5940.72, "reserve_amount": 4525.53},
        dependencies=["RULE-L3-0108"],
        topics=["topic.ledger.8"],
        output_topic="topic.ledger.output.55",
    )

    rule_56 = Rule(
        rule_id="RULE-L3-0056",
        name="accumulate_payment_batch",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="ADJUSTMENT"),
                Condition(field_name="rate", operator=ConditionOperator.GT, value=64360),
                Condition(field_name="volume", operator=ConditionOperator.GT, value=10689),
                Condition(field_name="counterparty", operator=ConditionOperator.EQ, value=19542),
            ],
        ),
        transform=lambda r: {"fee_amount": 2757.41},
        dependencies=["RULE-L3-0042", "RULE-L3-0174"],
        topics=["topic.operations.11"],
        output_topic="topic.operations.output.56",
    )

    rule_57 = Rule(
        rule_id="RULE-L3-0057",
        name="merge_withholding_amount",
        group="equity",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.EQ, value="CANCELLED"),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="LATAM"),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="COMPLIANCE"),
                Condition(field_name="volume", operator=ConditionOperator.LTE, value=54624),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="SETTLED"),
            ],
        ),
        transform=lambda r: {"reserve_amount": 9536.39, "discount_rate": 0.68},
        dependencies=["RULE-L3-0158", "RULE-L3-0171", "RULE-L3-0179", "RULE-L3-0181"],
        topics=["topic.equity.16"],
        output_topic="topic.equity.output.57",
    )

    rule_58 = Rule(
        rule_id="RULE-L3-0058",
        name="validate_settlement_window",
        group="compliance",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="APPROVED"),
            ],
        ),
        transform=lambda r: {"route": "REJECTED", "adjusted_amount": 3303.16, "reserve_amount": 1231.09},
        dependencies=["RULE-L3-0046", "RULE-L3-0249", "RULE-L3-0118", "RULE-L3-0193", "RULE-L3-0150", "RULE-L3-0094", "RULE-L3-0240", "RULE-L3-0010"],
        topics=["topic.compliance.12"],
        output_topic="topic.compliance.output.58",
    )

    rule_59 = Rule(
        rule_id="RULE-L3-0059",
        name="split_credit_memo",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=75848),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="LATAM"),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="COMPLIANCE"),
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=36612),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="TRADING"),
            ],
        ),
        transform=lambda r: {"tax_rate": 0.82, "adjusted_amount": 2681.8, "net_value": 1812.36},
        dependencies=["RULE-L3-0198"],
        topics=["topic.operations.10"],
        output_topic="topic.operations.output.59",
    )

    rule_60 = Rule(
        rule_id="RULE-L3-0060",
        name="route_solvency_metric",
        group="ledger",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.GT, value=18695),
                Condition(field_name="amount", operator=ConditionOperator.GT, value=97894),
            ],
        ),
        transform=lambda r: {"penalty": 45.36, "commission": 15.74, "clearing_fee": 3123.26},
        dependencies=["RULE-L3-0084", "RULE-L3-0096", "RULE-L3-0231", "RULE-L3-0099"],
        topics=["topic.ledger.11"],
        output_topic="topic.ledger.output.60",
    )

    rule_61 = Rule(
        rule_id="RULE-L3-0061",
        name="reduce_settlement_window",
        group="payments",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.EQ, value="PAYMENT"),
                Condition(field_name="volume", operator=ConditionOperator.LTE, value=63756),
            ],
        ),
        transform=lambda r: {"clearing_fee": 2163.53, "penalty": 51.23, "fee_amount": 3458.28},
        dependencies=["RULE-L3-0196"],
        topics=["topic.payments.4"],
        output_topic="topic.payments.output.61",
    )

    rule_62 = Rule(
        rule_id="RULE-L3-0062",
        name="classify_duration_gap",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=7280),
            ],
        ),
        transform=lambda r: {"penalty": 30.14},
        dependencies=["RULE-L3-0217", "RULE-L3-0142", "RULE-L3-0017", "RULE-L3-0076", "RULE-L3-0122", "RULE-L3-0035"],
        topics=["topic.operations.7"],
        output_topic="topic.operations.output.62",
    )

    rule_63 = Rule(
        rule_id="RULE-L3-0063",
        name="transform_exchange_differential",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.LTE, value=98012),
                Condition(field_name="rate", operator=ConditionOperator.GTE, value=17032),
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=92331),
            ],
        ),
        transform=lambda r: {"gross_value": 730.03},
        dependencies=["RULE-L3-0179"],
        topics=["topic.operations.2"],
        output_topic="topic.operations.output.63",
    )

    rule_64 = Rule(
        rule_id="RULE-L3-0064",
        name="split_threshold_breach",
        group="equity",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=53108),
            ],
        ),
        transform=lambda r: {"settlement_amount": 4056.27, "fee_amount": 9662.33, "route": "MEDIUM"},
        dependencies=["RULE-L3-0086", "RULE-L3-0136", "RULE-L3-0107", "RULE-L3-0054"],
        topics=["topic.equity.15"],
        output_topic="topic.equity.output.64",
    )

    rule_65 = Rule(
        rule_id="RULE-L3-0065",
        name="filter_settlement_window",
        group="fixed_income",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=52587),
            ],
        ),
        transform=lambda r: {"risk_level": "HIGH", "penalty": 74.58, "settlement_amount": 2223.5},
        dependencies=["RULE-L3-0158", "RULE-L3-0015", "RULE-L3-0028"],
        topics=["topic.fixed_income.6"],
        output_topic="topic.fixed_income.output.65",
    )

    rule_66 = Rule(
        rule_id="RULE-L3-0066",
        name="validate_risk_score",
        group="treasury",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="LOW"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="MEDIUM"),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="TRADE"),
            ],
        ),
        transform=lambda r: {"commission": 46.4},
        dependencies=["RULE-L3-0254", "RULE-L3-0023", "RULE-L3-0125", "RULE-L3-0187", "RULE-L3-0178", "RULE-L3-0156", "RULE-L3-0241", "RULE-L3-0203"],
        topics=["topic.treasury.15"],
        output_topic="topic.treasury.output.66",
    )

    rule_67 = Rule(
        rule_id="RULE-L3-0067",
        name="route_audit_trail",
        group="equity",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.LT, value=36102),
            ],
        ),
        transform=lambda r: {"route": "LOW", "discount_rate": 0.31, "reserve_amount": 4524.62},
        dependencies=["RULE-L3-0111", "RULE-L3-0157", "RULE-L3-0219", "RULE-L3-0083"],
        topics=["topic.equity.2"],
        output_topic="topic.equity.output.67",
    )

    rule_68 = Rule(
        rule_id="RULE-L3-0068",
        name="filter_withholding_amount",
        group="compliance",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.LTE, value=76164),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="TRANSFER"),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="LATAM"),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="CRITICAL"),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="PENDING"),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="SETTLEMENT"),
            ],
        ),
        transform=lambda r: {"clearing_fee": 5232.25, "margin_requirement": 15.87, "reserve_amount": 3734.79},
        dependencies=["RULE-L3-0136", "RULE-L3-0149", "RULE-L3-0256", "RULE-L3-0161"],
        topics=["topic.compliance.10"],
        output_topic="topic.compliance.output.68",
    )

    rule_69 = Rule(
        rule_id="RULE-L3-0069",
        name="merge_mark_to_market",
        group="reconciliation",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="counterparty", operator=ConditionOperator.GT, value=43313),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="REJECTED"),
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=19809),
                Condition(field_name="counterparty", operator=ConditionOperator.GT, value=76480),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="HIGH"),
                Condition(field_name="maturity_date", operator=ConditionOperator.GTE, value=78093),
            ],
        ),
        transform=lambda r: {"risk_level": "APPROVED", "fee_amount": 6438.5, "reserve_amount": 3291.48},
        dependencies=["RULE-L3-0239", "RULE-L3-0034", "RULE-L3-0159", "RULE-L3-0146", "RULE-L3-0129"],
        topics=["topic.reconciliation.5"],
        output_topic="topic.reconciliation.output.69",
    )

    rule_70 = Rule(
        rule_id="RULE-L3-0070",
        name="derive_settlement_window",
        group="fixed_income",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.LT, value=40583),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="CLEARING"),
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=29793),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="LOW"),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=66643),
            ],
        ),
        transform=lambda r: {"route": "REJECTED", "net_value": 1319.18, "discount_rate": 0.38},
        dependencies=["RULE-L3-0188", "RULE-L3-0163", "RULE-L3-0129", "RULE-L3-0128", "RULE-L3-0208", "RULE-L3-0047", "RULE-L3-0228", "RULE-L3-0158"],
        topics=["topic.fixed_income.6"],
        output_topic="topic.fixed_income.output.70",
    )

    rule_71 = Rule(
        rule_id="RULE-L3-0071",
        name="dispatch_revenue_stream",
        group="equity",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=58322),
            ],
        ),
        transform=lambda r: {"adjusted_amount": 7840.17, "accrued_interest": 23.4, "gross_value": 2399.29},
        dependencies=["RULE-L3-0183", "RULE-L3-0076", "RULE-L3-0252"],
        topics=["topic.equity.16"],
        output_topic="topic.equity.output.71",
    )

    rule_72 = Rule(
        rule_id="RULE-L3-0072",
        name="evaluate_exposure_limit",
        group="equity",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=69235),
                Condition(field_name="rate", operator=ConditionOperator.GTE, value=26274),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="LOW"),
                Condition(field_name="notional", operator=ConditionOperator.LT, value=72784),
            ],
        ),
        transform=lambda r: {"approval_status": "HIGH"},
        dependencies=["RULE-L3-0001", "RULE-L3-0031", "RULE-L3-0007"],
        topics=["topic.equity.3"],
        output_topic="topic.equity.output.72",
    )

    rule_73 = Rule(
        rule_id="RULE-L3-0073",
        name="dispatch_tax_obligation",
        group="equity",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="rate", operator=ConditionOperator.GT, value=29202),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=3595),
                Condition(field_name="rate", operator=ConditionOperator.GT, value=52064),
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=50715),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="EUR"),
            ],
        ),
        transform=lambda r: {"net_value": 9308.95},
        dependencies=["RULE-L3-0162", "RULE-L3-0205", "RULE-L3-0031", "RULE-L3-0190", "RULE-L3-0219", "RULE-L3-0054", "RULE-L3-0206"],
        topics=["topic.equity.11"],
        output_topic="topic.equity.output.73",
    )

    rule_74 = Rule(
        rule_id="RULE-L3-0074",
        name="transform_compliance_flag",
        group="payments",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="CRITICAL"),
                Condition(field_name="amount", operator=ConditionOperator.GT, value=2590),
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=19697),
            ],
        ),
        transform=lambda r: {"settlement_amount": 2888.13, "route": "HIGH", "accrued_interest": 12.18},
        dependencies=["RULE-L3-0107", "RULE-L3-0012", "RULE-L3-0087", "RULE-L3-0091", "RULE-L3-0145", "RULE-L3-0208"],
        topics=["topic.payments.8"],
        output_topic="topic.payments.output.74",
    )

    rule_75 = Rule(
        rule_id="RULE-L3-0075",
        name="split_basis_spread",
        group="compliance",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.EQ, value=75472),
            ],
        ),
        transform=lambda r: {"fee_amount": 2919.81},
        dependencies=["RULE-L3-0003", "RULE-L3-0165", "RULE-L3-0052"],
        topics=["topic.compliance.1"],
        output_topic="topic.compliance.output.75",
    )

    rule_76 = Rule(
        rule_id="RULE-L3-0076",
        name="normalize_mark_to_market",
        group="settlement",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=69051),
                Condition(field_name="amount", operator=ConditionOperator.LTE, value=61721),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="PAYMENT"),
                Condition(field_name="account_id", operator=ConditionOperator.GT, value=46905),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="EUR"),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="APPROVED"),
            ],
        ),
        transform=lambda r: {"gross_value": 5464.68},
        dependencies=["RULE-L3-0066", "RULE-L3-0204", "RULE-L3-0018", "RULE-L3-0080"],
        topics=["topic.settlement.6"],
        output_topic="topic.settlement.output.76",
    )

    rule_77 = Rule(
        rule_id="RULE-L3-0077",
        name="correlate_yield_curve",
        group="settlement",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.GT, value=38562),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="EMEA"),
            ],
        ),
        transform=lambda r: {"net_value": 9334.38},
        dependencies=["RULE-L3-0131", "RULE-L3-0142", "RULE-L3-0084", "RULE-L3-0198"],
        topics=["topic.settlement.13"],
        output_topic="topic.settlement.output.77",
    )

    rule_78 = Rule(
        rule_id="RULE-L3-0078",
        name="project_yield_curve",
        group="trading",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="entity_id", operator=ConditionOperator.LT, value=6365),
            ],
        ),
        transform=lambda r: {"net_value": 7995.43, "fee_amount": 4375.14, "route": "APPROVED"},
        dependencies=[],
        topics=["topic.trading.15"],
        output_topic="topic.trading.output.78",
    )

    rule_79 = Rule(
        rule_id="RULE-L3-0079",
        name="merge_liquidity_ratio",
        group="settlement",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.EQ, value=35059),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="USD"),
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=23752),
                Condition(field_name="entity_id", operator=ConditionOperator.LT, value=13547),
            ],
        ),
        transform=lambda r: {"net_value": 6612.58},
        dependencies=["RULE-L3-0177"],
        topics=["topic.settlement.10"],
        output_topic="topic.settlement.output.79",
    )

    rule_80 = Rule(
        rule_id="RULE-L3-0080",
        name="correlate_position_delta",
        group="settlement",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=5651),
                Condition(field_name="instrument", operator=ConditionOperator.EQ, value=57108),
                Condition(field_name="account_id", operator=ConditionOperator.GT, value=9935),
                Condition(field_name="maturity_date", operator=ConditionOperator.LT, value=67351),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="SETTLEMENT"),
                Condition(field_name="volume", operator=ConditionOperator.GT, value=16645),
            ],
        ),
        transform=lambda r: {"margin_requirement": 77.85},
        dependencies=["RULE-L3-0089", "RULE-L3-0103", "RULE-L3-0187", "RULE-L3-0147", "RULE-L3-0159"],
        topics=["topic.settlement.12"],
        output_topic="topic.settlement.output.80",
    )

    rule_81 = Rule(
        rule_id="RULE-L3-0081",
        name="filter_counterparty_risk",
        group="payments",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.LT, value=48860),
                Condition(field_name="volume", operator=ConditionOperator.GT, value=75325),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="CRITICAL"),
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=32817),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="APPROVED"),
            ],
        ),
        transform=lambda r: {"accrued_interest": 56.17, "clearing_fee": 2625.15},
        dependencies=[],
        topics=["topic.payments.9"],
        output_topic="topic.payments.output.81",
    )

    rule_82 = Rule(
        rule_id="RULE-L3-0082",
        name="correlate_accrual_entry",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="region", operator=ConditionOperator.EQ, value="EMEA"),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="EUR"),
                Condition(field_name="volume", operator=ConditionOperator.GT, value=89481),
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=93100),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="GBP"),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="CLEARING"),
            ],
        ),
        transform=lambda r: {"margin_requirement": 79.21, "route": "MEDIUM", "approval_status": "APPROVED"},
        dependencies=["RULE-L3-0050", "RULE-L3-0086"],
        topics=["topic.operations.1"],
        output_topic="topic.operations.output.82",
    )

    rule_83 = Rule(
        rule_id="RULE-L3-0083",
        name="filter_exposure_limit",
        group="equity",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="GBP"),
                Condition(field_name="maturity_date", operator=ConditionOperator.LTE, value=69003),
                Condition(field_name="rate", operator=ConditionOperator.LTE, value=75453),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="GBP"),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="JPY"),
            ],
        ),
        transform=lambda r: {"gross_value": 7804.83, "risk_level": "REJECTED", "settlement_amount": 1827.81},
        dependencies=["RULE-L3-0238", "RULE-L3-0174", "RULE-L3-0124", "RULE-L3-0236", "RULE-L3-0123"],
        topics=["topic.equity.5"],
        output_topic="topic.equity.output.83",
    )

    rule_84 = Rule(
        rule_id="RULE-L3-0084",
        name="aggregate_audit_trail",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="counterparty", operator=ConditionOperator.GTE, value=45453),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=32947),
            ],
        ),
        transform=lambda r: {"reserve_amount": 1260.45},
        dependencies=[],
        topics=["topic.operations.10"],
        output_topic="topic.operations.output.84",
    )

    rule_85 = Rule(
        rule_id="RULE-L3-0085",
        name="accumulate_settlement_window",
        group="settlement",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="COLLATERAL"),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="INVOICE"),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="CREDIT_NOTE"),
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=83853),
                Condition(field_name="amount", operator=ConditionOperator.LTE, value=82303),
            ],
        ),
        transform=lambda r: {"adjusted_amount": 4834.62, "net_value": 8048.83, "fee_amount": 6853.06},
        dependencies=["RULE-L3-0125", "RULE-L3-0040"],
        topics=["topic.settlement.10"],
        output_topic="topic.settlement.output.85",
    )

    rule_86 = Rule(
        rule_id="RULE-L3-0086",
        name="correlate_invoice_line",
        group="payments",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="rate", operator=ConditionOperator.LTE, value=60975),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="EMEA"),
            ],
        ),
        transform=lambda r: {"net_value": 9880.35, "gross_value": 3460.25},
        dependencies=["RULE-L3-0230", "RULE-L3-0223", "RULE-L3-0139", "RULE-L3-0231", "RULE-L3-0087", "RULE-L3-0120", "RULE-L3-0202"],
        topics=["topic.payments.13"],
        output_topic="topic.payments.output.86",
    )

    rule_87 = Rule(
        rule_id="RULE-L3-0087",
        name="transform_exposure_limit",
        group="risk",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.GT, value=35158),
                Condition(field_name="volume", operator=ConditionOperator.GTE, value=18565),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="REJECTED"),
            ],
        ),
        transform=lambda r: {"settlement_amount": 9627.23, "approval_status": "MEDIUM"},
        dependencies=["RULE-L3-0239", "RULE-L3-0192", "RULE-L3-0015", "RULE-L3-0215", "RULE-L3-0135", "RULE-L3-0077"],
        topics=["topic.risk.11"],
        output_topic="topic.risk.output.87",
    )

    rule_88 = Rule(
        rule_id="RULE-L3-0088",
        name="evaluate_revenue_stream",
        group="fx",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.LT, value=65291),
                Condition(field_name="amount", operator=ConditionOperator.GT, value=51643),
                Condition(field_name="volume", operator=ConditionOperator.GTE, value=28299),
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=6724),
                Condition(field_name="entity_id", operator=ConditionOperator.LTE, value=78417),
            ],
        ),
        transform=lambda r: {"commission": 0.82, "fee_amount": 1083.9, "reserve_amount": 1348.01},
        dependencies=["RULE-L3-0144", "RULE-L3-0139", "RULE-L3-0005", "RULE-L3-0054", "RULE-L3-0149"],
        topics=["topic.fx.9"],
        output_topic="topic.fx.output.88",
    )

    rule_89 = Rule(
        rule_id="RULE-L3-0089",
        name="filter_collateral_value",
        group="valuation",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.EQ, value="PAYMENT"),
            ],
        ),
        transform=lambda r: {"adjusted_amount": 5047.51, "route": "REJECTED", "penalty": 27.97},
        dependencies=["RULE-L3-0206", "RULE-L3-0236", "RULE-L3-0229", "RULE-L3-0205", "RULE-L3-0092"],
        topics=["topic.valuation.4"],
        output_topic="topic.valuation.output.89",
    )

    rule_90 = Rule(
        rule_id="RULE-L3-0090",
        name="transform_margin_call",
        group="derivatives",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=26190),
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=5376),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="CREDIT_NOTE"),
            ],
        ),
        transform=lambda r: {"net_value": 5198.13, "accrued_interest": 14.89, "margin_requirement": 89.31},
        dependencies=["RULE-L3-0250"],
        topics=["topic.derivatives.5"],
        output_topic="topic.derivatives.output.90",
    )

    rule_91 = Rule(
        rule_id="RULE-L3-0091",
        name="route_capital_allocation",
        group="settlement",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="counterparty", operator=ConditionOperator.EQ, value=66909),
                Condition(field_name="notional", operator=ConditionOperator.EQ, value=39394),
                Condition(field_name="notional", operator=ConditionOperator.GT, value=48381),
                Condition(field_name="counterparty", operator=ConditionOperator.GT, value=54696),
            ],
        ),
        transform=lambda r: {"adjusted_amount": 8722.27, "accrued_interest": 62.93, "gross_value": 5973.13},
        dependencies=["RULE-L3-0072", "RULE-L3-0217"],
        topics=["topic.settlement.9"],
        output_topic="topic.settlement.output.91",
    )

    rule_92 = Rule(
        rule_id="RULE-L3-0092",
        name="cascade_yield_curve",
        group="settlement",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="LOW"),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="PENDING"),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=54990),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="MEDIUM"),
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=80247),
            ],
        ),
        transform=lambda r: {"route": "MEDIUM", "gross_value": 5191.65},
        dependencies=[],
        topics=["topic.settlement.11"],
        output_topic="topic.settlement.output.92",
    )

    rule_93 = Rule(
        rule_id="RULE-L3-0093",
        name="compute_counterparty_risk",
        group="reconciliation",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="counterparty", operator=ConditionOperator.EQ, value=46537),
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=63562),
            ],
        ),
        transform=lambda r: {"margin_requirement": 27.9},
        dependencies=["RULE-L3-0253", "RULE-L3-0098", "RULE-L3-0162", "RULE-L3-0138", "RULE-L3-0217"],
        topics=["topic.reconciliation.10"],
        output_topic="topic.reconciliation.output.93",
    )

    rule_94 = Rule(
        rule_id="RULE-L3-0094",
        name="normalize_amortization_table",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.LT, value=62988),
                Condition(field_name="instrument", operator=ConditionOperator.EQ, value=94689),
                Condition(field_name="account_id", operator=ConditionOperator.LT, value=16074),
                Condition(field_name="maturity_date", operator=ConditionOperator.LTE, value=45337),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="LOW"),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=45498),
            ],
        ),
        transform=lambda r: {"reserve_amount": 4796.0, "gross_value": 2028.66},
        dependencies=["RULE-L3-0148", "RULE-L3-0157"],
        topics=["topic.operations.9"],
        output_topic="topic.operations.output.94",
    )

    rule_95 = Rule(
        rule_id="RULE-L3-0095",
        name="project_tax_obligation",
        group="reporting",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.EQ, value="TRADING"),
            ],
        ),
        transform=lambda r: {"margin_requirement": 5.25},
        dependencies=["RULE-L3-0048", "RULE-L3-0154", "RULE-L3-0030", "RULE-L3-0223", "RULE-L3-0202", "RULE-L3-0194"],
        topics=["topic.reporting.14"],
        output_topic="topic.reporting.output.95",
    )

    rule_96 = Rule(
        rule_id="RULE-L3-0096",
        name="route_yield_curve",
        group="risk",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.EQ, value=20801),
                Condition(field_name="rate", operator=ConditionOperator.LTE, value=62680),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="APAC"),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=11825),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="RISK"),
                Condition(field_name="rate", operator=ConditionOperator.GTE, value=4863),
            ],
        ),
        transform=lambda r: {"commission": 93.66, "risk_level": "HIGH"},
        dependencies=["RULE-L3-0182", "RULE-L3-0221", "RULE-L3-0081", "RULE-L3-0183"],
        topics=["topic.risk.2"],
        output_topic="topic.risk.output.96",
    )

    rule_97 = Rule(
        rule_id="RULE-L3-0097",
        name="reconcile_amortization_table",
        group="risk",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.EQ, value=68823),
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=66188),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=25372),
            ],
        ),
        transform=lambda r: {"net_value": 1633.32},
        dependencies=[],
        topics=["topic.risk.15"],
        output_topic="topic.risk.output.97",
    )

    rule_98 = Rule(
        rule_id="RULE-L3-0098",
        name="enrich_cost_center",
        group="ledger",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="entity_id", operator=ConditionOperator.EQ, value=88495),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="LATAM"),
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=43082),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="USD"),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="MARGIN"),
                Condition(field_name="counterparty", operator=ConditionOperator.GTE, value=995),
            ],
        ),
        transform=lambda r: {"accrued_interest": 44.67, "approval_status": "HIGH"},
        dependencies=["RULE-L3-0107", "RULE-L3-0023", "RULE-L3-0129", "RULE-L3-0226"],
        topics=["topic.ledger.11"],
        output_topic="topic.ledger.output.98",
    )

    rule_99 = Rule(
        rule_id="RULE-L3-0099",
        name="classify_ledger_delta",
        group="trading",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.EQ, value="TREASURY"),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=21034),
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=92316),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=83817),
                Condition(field_name="entity_id", operator=ConditionOperator.LT, value=80660),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="RISK"),
            ],
        ),
        transform=lambda r: {"fee_amount": 7479.87, "margin_requirement": 60.57},
        dependencies=["RULE-L3-0096", "RULE-L3-0117", "RULE-L3-0214"],
        topics=["topic.trading.14"],
        output_topic="topic.trading.output.99",
    )

    rule_100 = Rule(
        rule_id="RULE-L3-0100",
        name="project_accrual_entry",
        group="credit",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.EQ, value=92344),
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=74046),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="CANCELLED"),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="EMEA"),
                Condition(field_name="counterparty", operator=ConditionOperator.EQ, value=58012),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="CANCELLED"),
            ],
        ),
        transform=lambda r: {"risk_level": "REJECTED", "clearing_fee": 4460.37},
        dependencies=["RULE-L3-0056", "RULE-L3-0136", "RULE-L3-0078", "RULE-L3-0045"],
        topics=["topic.credit.2"],
        output_topic="topic.credit.output.100",
    )

    rule_101 = Rule(
        rule_id="RULE-L3-0101",
        name="derive_mark_to_market",
        group="equity",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.LT, value=94901),
                Condition(field_name="amount", operator=ConditionOperator.LTE, value=33452),
                Condition(field_name="amount", operator=ConditionOperator.GTE, value=75900),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="JPY"),
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=71031),
            ],
        ),
        transform=lambda r: {"risk_level": "APPROVED"},
        dependencies=["RULE-L3-0096"],
        topics=["topic.equity.2"],
        output_topic="topic.equity.output.101",
    )

    rule_102 = Rule(
        rule_id="RULE-L3-0102",
        name="classify_mark_to_market",
        group="settlement",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=58890),
                Condition(field_name="maturity_date", operator=ConditionOperator.LTE, value=10618),
            ],
        ),
        transform=lambda r: {"fee_amount": 3484.22, "net_value": 1792.95, "settlement_amount": 5377.21},
        dependencies=[],
        topics=["topic.settlement.5"],
        output_topic="topic.settlement.output.102",
    )

    rule_103 = Rule(
        rule_id="RULE-L3-0103",
        name="normalize_ledger_delta",
        group="ledger",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=49812),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="OPERATIONS"),
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=36229),
            ],
        ),
        transform=lambda r: {"approval_status": "LOW"},
        dependencies=["RULE-L3-0235", "RULE-L3-0024", "RULE-L3-0115"],
        topics=["topic.ledger.14"],
        output_topic="topic.ledger.output.103",
    )

    rule_104 = Rule(
        rule_id="RULE-L3-0104",
        name="accumulate_threshold_breach",
        group="credit",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.EQ, value="SETTLED"),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="INVOICE"),
            ],
        ),
        transform=lambda r: {"clearing_fee": 5402.2, "approval_status": "LOW"},
        dependencies=["RULE-L3-0007", "RULE-L3-0206", "RULE-L3-0125", "RULE-L3-0233", "RULE-L3-0130", "RULE-L3-0040", "RULE-L3-0049", "RULE-L3-0088"],
        topics=["topic.credit.5"],
        output_topic="topic.credit.output.104",
    )

    rule_105 = Rule(
        rule_id="RULE-L3-0105",
        name="derive_withholding_amount",
        group="credit",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="counterparty", operator=ConditionOperator.GTE, value=39652),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="CRITICAL"),
                Condition(field_name="entity_id", operator=ConditionOperator.LT, value=8089),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="COLLATERAL"),
                Condition(field_name="notional", operator=ConditionOperator.GT, value=45243),
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=41877),
            ],
        ),
        transform=lambda r: {"settlement_amount": 3005.89, "penalty": 18.39, "risk_level": "REJECTED"},
        dependencies=["RULE-L3-0189", "RULE-L3-0225", "RULE-L3-0136", "RULE-L3-0080", "RULE-L3-0200", "RULE-L3-0084", "RULE-L3-0037"],
        topics=["topic.credit.16"],
        output_topic="topic.credit.output.105",
    )

    rule_106 = Rule(
        rule_id="RULE-L3-0106",
        name="normalize_depreciation_schedule",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.GT, value=73813),
                Condition(field_name="rate", operator=ConditionOperator.LTE, value=73144),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="MEDIUM"),
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=43388),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="GBP"),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="USD"),
            ],
        ),
        transform=lambda r: {"accrued_interest": 60.5, "net_value": 405.08},
        dependencies=["RULE-L3-0212"],
        topics=["topic.operations.3"],
        output_topic="topic.operations.output.106",
    )

    rule_107 = Rule(
        rule_id="RULE-L3-0107",
        name="evaluate_accrual_entry",
        group="fx",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=27862),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="LATAM"),
            ],
        ),
        transform=lambda r: {"penalty": 39.66},
        dependencies=["RULE-L3-0175", "RULE-L3-0256", "RULE-L3-0034", "RULE-L3-0053", "RULE-L3-0187", "RULE-L3-0010", "RULE-L3-0119", "RULE-L3-0100"],
        topics=["topic.fx.8"],
        output_topic="topic.fx.output.107",
    )

    rule_108 = Rule(
        rule_id="RULE-L3-0108",
        name="project_capital_allocation",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.LT, value=34383),
                Condition(field_name="instrument", operator=ConditionOperator.EQ, value=65279),
                Condition(field_name="volume", operator=ConditionOperator.GT, value=94788),
                Condition(field_name="notional", operator=ConditionOperator.LT, value=26724),
            ],
        ),
        transform=lambda r: {"net_value": 466.7, "penalty": 86.41},
        dependencies=["RULE-L3-0030", "RULE-L3-0002", "RULE-L3-0080", "RULE-L3-0240", "RULE-L3-0012", "RULE-L3-0177", "RULE-L3-0219", "RULE-L3-0154"],
        topics=["topic.operations.5"],
        output_topic="topic.operations.output.108",
    )

    rule_109 = Rule(
        rule_id="RULE-L3-0109",
        name="reconcile_exchange_differential",
        group="fixed_income",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="EMEA"),
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=32308),
                Condition(field_name="notional", operator=ConditionOperator.EQ, value=85900),
            ],
        ),
        transform=lambda r: {"net_value": 8217.7, "fee_amount": 9665.42, "accrued_interest": 64.17},
        dependencies=["RULE-L3-0086"],
        topics=["topic.fixed_income.16"],
        output_topic="topic.fixed_income.output.109",
    )

    rule_110 = Rule(
        rule_id="RULE-L3-0110",
        name="correlate_revenue_stream",
        group="valuation",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=71158),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="INVOICE"),
            ],
        ),
        transform=lambda r: {"route": "APPROVED", "accrued_interest": 13.75, "tax_rate": 0.63},
        dependencies=["RULE-L3-0229", "RULE-L3-0012", "RULE-L3-0027", "RULE-L3-0135", "RULE-L3-0198", "RULE-L3-0170", "RULE-L3-0192"],
        topics=["topic.valuation.3"],
        output_topic="topic.valuation.output.110",
    )

    rule_111 = Rule(
        rule_id="RULE-L3-0111",
        name="transform_ledger_delta",
        group="treasury",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=81080),
                Condition(field_name="notional", operator=ConditionOperator.LTE, value=2161),
                Condition(field_name="amount", operator=ConditionOperator.EQ, value=72405),
                Condition(field_name="rate", operator=ConditionOperator.GT, value=2292),
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=37676),
            ],
        ),
        transform=lambda r: {"settlement_amount": 8063.62},
        dependencies=["RULE-L3-0006", "RULE-L3-0149", "RULE-L3-0196", "RULE-L3-0080"],
        topics=["topic.treasury.6"],
        output_topic="topic.treasury.output.111",
    )

    rule_112 = Rule(
        rule_id="RULE-L3-0112",
        name="aggregate_margin_call",
        group="reporting",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.LT, value=35138),
                Condition(field_name="maturity_date", operator=ConditionOperator.GT, value=48996),
            ],
        ),
        transform=lambda r: {"clearing_fee": 2439.65, "adjusted_amount": 6975.39},
        dependencies=["RULE-L3-0083", "RULE-L3-0052", "RULE-L3-0050"],
        topics=["topic.reporting.10"],
        output_topic="topic.reporting.output.112",
    )

    rule_113 = Rule(
        rule_id="RULE-L3-0113",
        name="validate_payment_batch",
        group="compliance",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=62490),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="CREDIT_NOTE"),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="JPY"),
                Condition(field_name="counterparty", operator=ConditionOperator.EQ, value=12599),
            ],
        ),
        transform=lambda r: {"route": "REJECTED", "approval_status": "APPROVED", "clearing_fee": 2718.24},
        dependencies=["RULE-L3-0071", "RULE-L3-0138", "RULE-L3-0082", "RULE-L3-0199"],
        topics=["topic.compliance.3"],
        output_topic="topic.compliance.output.113",
    )

    rule_114 = Rule(
        rule_id="RULE-L3-0114",
        name="dispatch_capital_allocation",
        group="ledger",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.GT, value=39326),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="COLLATERAL"),
            ],
        ),
        transform=lambda r: {"net_value": 7558.54, "penalty": 14.0},
        dependencies=["RULE-L3-0173", "RULE-L3-0031", "RULE-L3-0070", "RULE-L3-0039", "RULE-L3-0041", "RULE-L3-0071", "RULE-L3-0030"],
        topics=["topic.ledger.3"],
        output_topic="topic.ledger.output.114",
    )

    rule_115 = Rule(
        rule_id="RULE-L3-0115",
        name="derive_solvency_metric",
        group="payments",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.EQ, value="COMPLIANCE"),
            ],
        ),
        transform=lambda r: {"accrued_interest": 2.96, "commission": 27.33, "discount_rate": 0.98},
        dependencies=[],
        topics=["topic.payments.16"],
        output_topic="topic.payments.output.115",
    )

    rule_116 = Rule(
        rule_id="RULE-L3-0116",
        name="normalize_solvency_metric",
        group="derivatives",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.GT, value=81183),
                Condition(field_name="entity_id", operator=ConditionOperator.GTE, value=93568),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="GBP"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="MEDIUM"),
            ],
        ),
        transform=lambda r: {"accrued_interest": 10.66, "discount_rate": 0.02, "clearing_fee": 3089.59},
        dependencies=["RULE-L3-0133", "RULE-L3-0027", "RULE-L3-0053", "RULE-L3-0140", "RULE-L3-0090", "RULE-L3-0142", "RULE-L3-0082", "RULE-L3-0070"],
        topics=["topic.derivatives.12"],
        output_topic="topic.derivatives.output.116",
    )

    rule_117 = Rule(
        rule_id="RULE-L3-0117",
        name="enrich_margin_call",
        group="reporting",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="rate", operator=ConditionOperator.LTE, value=73105),
            ],
        ),
        transform=lambda r: {"settlement_amount": 905.29, "route": "REJECTED", "tax_rate": 0.1},
        dependencies=["RULE-L3-0243", "RULE-L3-0182"],
        topics=["topic.reporting.11"],
        output_topic="topic.reporting.output.117",
    )

    rule_118 = Rule(
        rule_id="RULE-L3-0118",
        name="merge_ledger_delta",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="CHF"),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="SETTLEMENT"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="HIGH"),
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=19227),
            ],
        ),
        transform=lambda r: {"discount_rate": 0.44},
        dependencies=["RULE-L3-0148", "RULE-L3-0063", "RULE-L3-0044", "RULE-L3-0019"],
        topics=["topic.operations.14"],
        output_topic="topic.operations.output.118",
    )

    rule_119 = Rule(
        rule_id="RULE-L3-0119",
        name="classify_yield_curve",
        group="compliance",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="TRADING"),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="NA"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="LOW"),
            ],
        ),
        transform=lambda r: {"net_value": 6205.72, "settlement_amount": 8042.72},
        dependencies=["RULE-L3-0158", "RULE-L3-0230", "RULE-L3-0087", "RULE-L3-0140"],
        topics=["topic.compliance.11"],
        output_topic="topic.compliance.output.119",
    )

    rule_120 = Rule(
        rule_id="RULE-L3-0120",
        name="correlate_liquidity_ratio",
        group="fixed_income",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="entity_id", operator=ConditionOperator.LT, value=79164),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="APAC"),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="CLEARING"),
                Condition(field_name="entity_id", operator=ConditionOperator.LTE, value=75581),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="OPERATIONS"),
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=47943),
            ],
        ),
        transform=lambda r: {"penalty": 59.22},
        dependencies=["RULE-L3-0013", "RULE-L3-0034", "RULE-L3-0008", "RULE-L3-0122", "RULE-L3-0233", "RULE-L3-0174", "RULE-L3-0028"],
        topics=["topic.fixed_income.6"],
        output_topic="topic.fixed_income.output.120",
    )

    rule_121 = Rule(
        rule_id="RULE-L3-0121",
        name="project_threshold_breach",
        group="equity",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.LT, value=90911),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="JPY"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="MEDIUM"),
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=93847),
                Condition(field_name="rate", operator=ConditionOperator.LTE, value=9794),
                Condition(field_name="volume", operator=ConditionOperator.EQ, value=62914),
            ],
        ),
        transform=lambda r: {"accrued_interest": 92.35, "reserve_amount": 8697.64, "clearing_fee": 4188.82},
        dependencies=["RULE-L3-0014", "RULE-L3-0023", "RULE-L3-0110", "RULE-L3-0101", "RULE-L3-0046", "RULE-L3-0182"],
        topics=["topic.equity.2"],
        output_topic="topic.equity.output.121",
    )

    rule_122 = Rule(
        rule_id="RULE-L3-0122",
        name="aggregate_interest_rate",
        group="valuation",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.LT, value=56520),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="PENDING"),
            ],
        ),
        transform=lambda r: {"margin_requirement": 74.69, "reserve_amount": 5584.35},
        dependencies=["RULE-L3-0159", "RULE-L3-0092", "RULE-L3-0080", "RULE-L3-0086", "RULE-L3-0211", "RULE-L3-0051", "RULE-L3-0184"],
        topics=["topic.valuation.8"],
        output_topic="topic.valuation.output.122",
    )

    rule_123 = Rule(
        rule_id="RULE-L3-0123",
        name="correlate_exposure_limit",
        group="derivatives",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=63377),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="SETTLED"),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="EUR"),
                Condition(field_name="instrument", operator=ConditionOperator.LT, value=45066),
            ],
        ),
        transform=lambda r: {"penalty": 48.29, "reserve_amount": 4766.86},
        dependencies=["RULE-L3-0021", "RULE-L3-0251", "RULE-L3-0238", "RULE-L3-0195", "RULE-L3-0197", "RULE-L3-0120", "RULE-L3-0147", "RULE-L3-0034"],
        topics=["topic.derivatives.15"],
        output_topic="topic.derivatives.output.123",
    )

    rule_124 = Rule(
        rule_id="RULE-L3-0124",
        name="correlate_capital_allocation",
        group="compliance",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.EQ, value="REJECTED"),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="APPROVED"),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="CLEARING"),
            ],
        ),
        transform=lambda r: {"settlement_amount": 7979.58, "margin_requirement": 62.98, "approval_status": "MEDIUM"},
        dependencies=["RULE-L3-0210"],
        topics=["topic.compliance.14"],
        output_topic="topic.compliance.output.124",
    )

    rule_125 = Rule(
        rule_id="RULE-L3-0125",
        name="accumulate_budget_variance",
        group="equity",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.GT, value=92471),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="APAC"),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="CHF"),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="CLEARING"),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="NA"),
            ],
        ),
        transform=lambda r: {"commission": 96.59, "reserve_amount": 3140.91},
        dependencies=["RULE-L3-0025", "RULE-L3-0117", "RULE-L3-0080", "RULE-L3-0177", "RULE-L3-0166", "RULE-L3-0183", "RULE-L3-0198"],
        topics=["topic.equity.13"],
        output_topic="topic.equity.output.125",
    )

    rule_126 = Rule(
        rule_id="RULE-L3-0126",
        name="accumulate_collateral_value",
        group="risk",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.EQ, value=22713),
                Condition(field_name="entity_id", operator=ConditionOperator.EQ, value=77454),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="GBP"),
            ],
        ),
        transform=lambda r: {"margin_requirement": 30.54},
        dependencies=["RULE-L3-0121", "RULE-L3-0060", "RULE-L3-0244", "RULE-L3-0058", "RULE-L3-0037", "RULE-L3-0222", "RULE-L3-0231"],
        topics=["topic.risk.6"],
        output_topic="topic.risk.output.126",
    )

    rule_127 = Rule(
        rule_id="RULE-L3-0127",
        name="filter_audit_trail",
        group="derivatives",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.LTE, value=24447),
                Condition(field_name="notional", operator=ConditionOperator.EQ, value=90989),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="MARGIN"),
                Condition(field_name="entity_id", operator=ConditionOperator.GTE, value=24623),
            ],
        ),
        transform=lambda r: {"clearing_fee": 545.58, "adjusted_amount": 3596.8},
        dependencies=["RULE-L3-0235", "RULE-L3-0094", "RULE-L3-0101", "RULE-L3-0047"],
        topics=["topic.derivatives.1"],
        output_topic="topic.derivatives.output.127",
    )

    rule_128 = Rule(
        rule_id="RULE-L3-0128",
        name="compute_compliance_flag",
        group="treasury",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="rate", operator=ConditionOperator.LTE, value=54577),
                Condition(field_name="volume", operator=ConditionOperator.LTE, value=22022),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="EUR"),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=36125),
            ],
        ),
        transform=lambda r: {"adjusted_amount": 1690.41},
        dependencies=["RULE-L3-0203", "RULE-L3-0222", "RULE-L3-0227", "RULE-L3-0084", "RULE-L3-0117"],
        topics=["topic.treasury.15"],
        output_topic="topic.treasury.output.128",
    )

    rule_129 = Rule(
        rule_id="RULE-L3-0129",
        name="reduce_duration_gap",
        group="risk",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=48185),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="TRANSFER"),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="NA"),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="TREASURY"),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=45788),
            ],
        ),
        transform=lambda r: {"clearing_fee": 8654.25},
        dependencies=["RULE-L3-0008", "RULE-L3-0017", "RULE-L3-0122", "RULE-L3-0029", "RULE-L3-0090", "RULE-L3-0123", "RULE-L3-0119"],
        topics=["topic.risk.4"],
        output_topic="topic.risk.output.129",
    )

    rule_130 = Rule(
        rule_id="RULE-L3-0130",
        name="normalize_accrual_entry",
        group="valuation",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.EQ, value="SETTLEMENT"),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="APAC"),
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=70717),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="CLEARING"),
                Condition(field_name="entity_id", operator=ConditionOperator.EQ, value=35141),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="SETTLED"),
            ],
        ),
        transform=lambda r: {"reserve_amount": 8671.81},
        dependencies=["RULE-L3-0073", "RULE-L3-0198"],
        topics=["topic.valuation.5"],
        output_topic="topic.valuation.output.130",
    )

    rule_131 = Rule(
        rule_id="RULE-L3-0131",
        name="transform_interest_rate",
        group="reporting",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="OPERATIONS"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="CRITICAL"),
                Condition(field_name="maturity_date", operator=ConditionOperator.LTE, value=9998),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="CHF"),
                Condition(field_name="account_id", operator=ConditionOperator.LT, value=59697),
                Condition(field_name="notional", operator=ConditionOperator.LT, value=76378),
            ],
        ),
        transform=lambda r: {"risk_level": "APPROVED"},
        dependencies=["RULE-L3-0156", "RULE-L3-0149", "RULE-L3-0033", "RULE-L3-0132", "RULE-L3-0027"],
        topics=["topic.reporting.12"],
        output_topic="topic.reporting.output.131",
    )

    rule_132 = Rule(
        rule_id="RULE-L3-0132",
        name="validate_collateral_value",
        group="treasury",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.LT, value=42418),
                Condition(field_name="entity_id", operator=ConditionOperator.LT, value=71837),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="HIGH"),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="INVOICE"),
            ],
        ),
        transform=lambda r: {"clearing_fee": 9295.03, "tax_rate": 0.16, "route": "APPROVED"},
        dependencies=["RULE-L3-0211", "RULE-L3-0184", "RULE-L3-0205", "RULE-L3-0028", "RULE-L3-0084", "RULE-L3-0144"],
        topics=["topic.treasury.1"],
        output_topic="topic.treasury.output.132",
    )

    rule_133 = Rule(
        rule_id="RULE-L3-0133",
        name="split_budget_variance",
        group="reporting",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="TRADE"),
                Condition(field_name="instrument", operator=ConditionOperator.LT, value=10903),
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=6887),
                Condition(field_name="maturity_date", operator=ConditionOperator.LT, value=95256),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="TREASURY"),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="APPROVED"),
            ],
        ),
        transform=lambda r: {"risk_level": "REJECTED", "commission": 22.62},
        dependencies=["RULE-L3-0204"],
        topics=["topic.reporting.15"],
        output_topic="topic.reporting.output.133",
    )

    rule_134 = Rule(
        rule_id="RULE-L3-0134",
        name="reconcile_ledger_delta",
        group="reconciliation",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="LOW"),
            ],
        ),
        transform=lambda r: {"accrued_interest": 8.93},
        dependencies=["RULE-L3-0138", "RULE-L3-0119", "RULE-L3-0103", "RULE-L3-0153"],
        topics=["topic.reconciliation.4"],
        output_topic="topic.reconciliation.output.134",
    )

    rule_135 = Rule(
        rule_id="RULE-L3-0135",
        name="aggregate_capital_allocation",
        group="valuation",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.GTE, value=84192),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="LOW"),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="CLEARING"),
            ],
        ),
        transform=lambda r: {"penalty": 15.14, "net_value": 4122.98, "gross_value": 6868.8},
        dependencies=["RULE-L3-0062", "RULE-L3-0160", "RULE-L3-0063", "RULE-L3-0142", "RULE-L3-0041", "RULE-L3-0251"],
        topics=["topic.valuation.7"],
        output_topic="topic.valuation.output.135",
    )

    rule_136 = Rule(
        rule_id="RULE-L3-0136",
        name="validate_margin_call",
        group="reporting",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=41322),
            ],
        ),
        transform=lambda r: {"margin_requirement": 27.7},
        dependencies=["RULE-L3-0099", "RULE-L3-0017", "RULE-L3-0088", "RULE-L3-0054", "RULE-L3-0210", "RULE-L3-0179", "RULE-L3-0153"],
        topics=["topic.reporting.3"],
        output_topic="topic.reporting.output.136",
    )

    rule_137 = Rule(
        rule_id="RULE-L3-0137",
        name="normalize_withholding_amount",
        group="ledger",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="region", operator=ConditionOperator.EQ, value="LATAM"),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=31470),
                Condition(field_name="notional", operator=ConditionOperator.LTE, value=14877),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="TRADING"),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="GBP"),
                Condition(field_name="counterparty", operator=ConditionOperator.GTE, value=50803),
            ],
        ),
        transform=lambda r: {"settlement_amount": 6832.59, "discount_rate": 0.76, "reserve_amount": 9544.99},
        dependencies=["RULE-L3-0202", "RULE-L3-0252", "RULE-L3-0112", "RULE-L3-0147", "RULE-L3-0203", "RULE-L3-0088"],
        topics=["topic.ledger.3"],
        output_topic="topic.ledger.output.137",
    )

    rule_138 = Rule(
        rule_id="RULE-L3-0138",
        name="reconcile_invoice_line",
        group="ledger",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.EQ, value="ADJUSTMENT"),
                Condition(field_name="entity_id", operator=ConditionOperator.EQ, value=54551),
                Condition(field_name="rate", operator=ConditionOperator.LTE, value=10903),
            ],
        ),
        transform=lambda r: {"fee_amount": 3105.97, "commission": 51.13, "route": "MEDIUM"},
        dependencies=["RULE-L3-0179", "RULE-L3-0061", "RULE-L3-0045", "RULE-L3-0171", "RULE-L3-0173", "RULE-L3-0020", "RULE-L3-0191", "RULE-L3-0240"],
        topics=["topic.ledger.5"],
        output_topic="topic.ledger.output.138",
    )

    rule_139 = Rule(
        rule_id="RULE-L3-0139",
        name="merge_invoice_line",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.EQ, value="RISK"),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="USD"),
                Condition(field_name="volume", operator=ConditionOperator.EQ, value=79900),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="CREDIT_NOTE"),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="APPROVED"),
                Condition(field_name="amount", operator=ConditionOperator.GTE, value=65165),
            ],
        ),
        transform=lambda r: {"reserve_amount": 3724.98, "risk_level": "HIGH"},
        dependencies=["RULE-L3-0030", "RULE-L3-0153", "RULE-L3-0154", "RULE-L3-0119", "RULE-L3-0084", "RULE-L3-0144", "RULE-L3-0025"],
        topics=["topic.operations.4"],
        output_topic="topic.operations.output.139",
    )

    rule_140 = Rule(
        rule_id="RULE-L3-0140",
        name="reconcile_liquidity_ratio",
        group="fixed_income",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=82351),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="JPY"),
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=65584),
            ],
        ),
        transform=lambda r: {"discount_rate": 0.26, "commission": 10.29, "risk_level": "REJECTED"},
        dependencies=["RULE-L3-0046", "RULE-L3-0079", "RULE-L3-0246", "RULE-L3-0104", "RULE-L3-0018", "RULE-L3-0155", "RULE-L3-0028"],
        topics=["topic.fixed_income.4"],
        output_topic="topic.fixed_income.output.140",
    )

    rule_141 = Rule(
        rule_id="RULE-L3-0141",
        name="cascade_ledger_delta",
        group="credit",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=19771),
            ],
        ),
        transform=lambda r: {"route": "REJECTED"},
        dependencies=["RULE-L3-0084", "RULE-L3-0127", "RULE-L3-0167", "RULE-L3-0171", "RULE-L3-0016", "RULE-L3-0024"],
        topics=["topic.credit.14"],
        output_topic="topic.credit.output.141",
    )

    rule_142 = Rule(
        rule_id="RULE-L3-0142",
        name="normalize_capital_allocation",
        group="credit",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.GT, value=75012),
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=65903),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="CREDIT_NOTE"),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="INVOICE"),
            ],
        ),
        transform=lambda r: {"adjusted_amount": 8450.02, "accrued_interest": 32.73},
        dependencies=["RULE-L3-0211", "RULE-L3-0036", "RULE-L3-0229"],
        topics=["topic.credit.15"],
        output_topic="topic.credit.output.142",
    )

    rule_143 = Rule(
        rule_id="RULE-L3-0143",
        name="reconcile_exposure_limit",
        group="treasury",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="COMPLIANCE"),
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=96105),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="TREASURY"),
            ],
        ),
        transform=lambda r: {"tax_rate": 0.54, "approval_status": "LOW"},
        dependencies=[],
        topics=["topic.treasury.11"],
        output_topic="topic.treasury.output.143",
    )

    rule_144 = Rule(
        rule_id="RULE-L3-0144",
        name="reconcile_counterparty_risk",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="OPERATIONS"),
            ],
        ),
        transform=lambda r: {"fee_amount": 7119.41},
        dependencies=["RULE-L3-0171", "RULE-L3-0039"],
        topics=["topic.operations.3"],
        output_topic="topic.operations.output.144",
    )

    rule_145 = Rule(
        rule_id="RULE-L3-0145",
        name="cascade_depreciation_schedule",
        group="fixed_income",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.GT, value=76222),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="SETTLED"),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="JPY"),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="HIGH"),
                Condition(field_name="account_id", operator=ConditionOperator.LT, value=51605),
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=59443),
            ],
        ),
        transform=lambda r: {"margin_requirement": 94.36, "route": "MEDIUM"},
        dependencies=["RULE-L3-0137", "RULE-L3-0075", "RULE-L3-0100", "RULE-L3-0159", "RULE-L3-0149", "RULE-L3-0115", "RULE-L3-0051"],
        topics=["topic.fixed_income.4"],
        output_topic="topic.fixed_income.output.145",
    )

    rule_146 = Rule(
        rule_id="RULE-L3-0146",
        name="project_solvency_metric",
        group="treasury",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.LT, value=15817),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="GBP"),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="PAYMENT"),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="MEDIUM"),
            ],
        ),
        transform=lambda r: {"accrued_interest": 4.9, "reserve_amount": 2995.42},
        dependencies=["RULE-L3-0176", "RULE-L3-0226", "RULE-L3-0082"],
        topics=["topic.treasury.6"],
        output_topic="topic.treasury.output.146",
    )

    rule_147 = Rule(
        rule_id="RULE-L3-0147",
        name="reconcile_collateral_value",
        group="equity",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="PENDING"),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="LOW"),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="CREDIT_NOTE"),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="APAC"),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="USD"),
            ],
        ),
        transform=lambda r: {"risk_level": "MEDIUM"},
        dependencies=["RULE-L3-0146", "RULE-L3-0205", "RULE-L3-0235", "RULE-L3-0175"],
        topics=["topic.equity.15"],
        output_topic="topic.equity.output.147",
    )

    rule_148 = Rule(
        rule_id="RULE-L3-0148",
        name="transform_settlement_window",
        group="reconciliation",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.GT, value=22118),
            ],
        ),
        transform=lambda r: {"settlement_amount": 3956.04, "commission": 2.95, "gross_value": 6835.3},
        dependencies=["RULE-L3-0237", "RULE-L3-0243", "RULE-L3-0241", "RULE-L3-0112"],
        topics=["topic.reconciliation.6"],
        output_topic="topic.reconciliation.output.148",
    )

    rule_149 = Rule(
        rule_id="RULE-L3-0149",
        name="filter_accrual_entry",
        group="settlement",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.GTE, value=4641),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="OPERATIONS"),
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=62887),
            ],
        ),
        transform=lambda r: {"risk_level": "HIGH"},
        dependencies=["RULE-L3-0255", "RULE-L3-0023", "RULE-L3-0151", "RULE-L3-0003", "RULE-L3-0158"],
        topics=["topic.settlement.13"],
        output_topic="topic.settlement.output.149",
    )

    rule_150 = Rule(
        rule_id="RULE-L3-0150",
        name="transform_mark_to_market",
        group="treasury",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.LTE, value=93602),
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=71471),
                Condition(field_name="notional", operator=ConditionOperator.LT, value=74241),
                Condition(field_name="counterparty", operator=ConditionOperator.LTE, value=35546),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="CLEARING"),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="COMPLIANCE"),
            ],
        ),
        transform=lambda r: {"commission": 52.94},
        dependencies=["RULE-L3-0104", "RULE-L3-0218", "RULE-L3-0033", "RULE-L3-0220", "RULE-L3-0076", "RULE-L3-0016", "RULE-L3-0095", "RULE-L3-0232"],
        topics=["topic.treasury.8"],
        output_topic="topic.treasury.output.150",
    )

    rule_151 = Rule(
        rule_id="RULE-L3-0151",
        name="dispatch_margin_call",
        group="credit",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=96707),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="TRANSFER"),
                Condition(field_name="maturity_date", operator=ConditionOperator.LT, value=22868),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="COLLATERAL"),
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=77637),
                Condition(field_name="amount", operator=ConditionOperator.LT, value=74503),
            ],
        ),
        transform=lambda r: {"fee_amount": 8368.6, "adjusted_amount": 8105.91, "approval_status": "APPROVED"},
        dependencies=["RULE-L3-0249", "RULE-L3-0014", "RULE-L3-0001", "RULE-L3-0182", "RULE-L3-0144", "RULE-L3-0212", "RULE-L3-0252", "RULE-L3-0092"],
        topics=["topic.credit.10"],
        output_topic="topic.credit.output.151",
    )

    rule_152 = Rule(
        rule_id="RULE-L3-0152",
        name="dispatch_duration_gap",
        group="payments",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.EQ, value="TREASURY"),
            ],
        ),
        transform=lambda r: {"commission": 91.79, "tax_rate": 0.21, "discount_rate": 0.14},
        dependencies=["RULE-L3-0222"],
        topics=["topic.payments.6"],
        output_topic="topic.payments.output.152",
    )

    rule_153 = Rule(
        rule_id="RULE-L3-0153",
        name="reconcile_audit_trail",
        group="reporting",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="JPY"),
            ],
        ),
        transform=lambda r: {"approval_status": "HIGH", "discount_rate": 0.14, "fee_amount": 1583.46},
        dependencies=["RULE-L3-0223", "RULE-L3-0008", "RULE-L3-0061", "RULE-L3-0111"],
        topics=["topic.reporting.14"],
        output_topic="topic.reporting.output.153",
    )

    rule_154 = Rule(
        rule_id="RULE-L3-0154",
        name="compute_capital_allocation",
        group="settlement",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.EQ, value="OPERATIONS"),
                Condition(field_name="entity_id", operator=ConditionOperator.LT, value=16791),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="COLLATERAL"),
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=4344),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="COLLATERAL"),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="OPERATIONS"),
            ],
        ),
        transform=lambda r: {"net_value": 7455.98},
        dependencies=["RULE-L3-0162", "RULE-L3-0082", "RULE-L3-0184", "RULE-L3-0098", "RULE-L3-0104", "RULE-L3-0112"],
        topics=["topic.settlement.8"],
        output_topic="topic.settlement.output.154",
    )

    rule_155 = Rule(
        rule_id="RULE-L3-0155",
        name="dispatch_settlement_window",
        group="reconciliation",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=32807),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="GBP"),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="PENDING"),
                Condition(field_name="maturity_date", operator=ConditionOperator.LTE, value=96121),
            ],
        ),
        transform=lambda r: {"discount_rate": 0.42, "clearing_fee": 8818.89},
        dependencies=["RULE-L3-0055", "RULE-L3-0171", "RULE-L3-0045", "RULE-L3-0122", "RULE-L3-0036", "RULE-L3-0049", "RULE-L3-0143", "RULE-L3-0099"],
        topics=["topic.reconciliation.12"],
        output_topic="topic.reconciliation.output.155",
    )

    rule_156 = Rule(
        rule_id="RULE-L3-0156",
        name="project_counterparty_risk",
        group="risk",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="TRADE"),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="INVOICE"),
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=13826),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="EUR"),
            ],
        ),
        transform=lambda r: {"discount_rate": 0.08, "gross_value": 9418.92},
        dependencies=["RULE-L3-0217", "RULE-L3-0107", "RULE-L3-0040", "RULE-L3-0074", "RULE-L3-0225"],
        topics=["topic.risk.3"],
        output_topic="topic.risk.output.156",
    )

    rule_157 = Rule(
        rule_id="RULE-L3-0157",
        name="reconcile_position_delta",
        group="settlement",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.EQ, value="TRADE"),
                Condition(field_name="counterparty", operator=ConditionOperator.GTE, value=25001),
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=94738),
                Condition(field_name="account_id", operator=ConditionOperator.LT, value=39080),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="TREASURY"),
            ],
        ),
        transform=lambda r: {"commission": 5.45, "risk_level": "LOW"},
        dependencies=["RULE-L3-0035", "RULE-L3-0003"],
        topics=["topic.settlement.14"],
        output_topic="topic.settlement.output.157",
    )

    rule_158 = Rule(
        rule_id="RULE-L3-0158",
        name="validate_withholding_amount",
        group="fx",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.GTE, value=22491),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=62171),
            ],
        ),
        transform=lambda r: {"adjusted_amount": 7850.92},
        dependencies=["RULE-L3-0167"],
        topics=["topic.fx.16"],
        output_topic="topic.fx.output.158",
    )

    rule_159 = Rule(
        rule_id="RULE-L3-0159",
        name="compute_exchange_differential",
        group="compliance",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="MARGIN"),
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=58528),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="ADJUSTMENT"),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=29754),
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=8179),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="LOW"),
            ],
        ),
        transform=lambda r: {"gross_value": 4145.73, "accrued_interest": 75.65, "reserve_amount": 2282.85},
        dependencies=[],
        topics=["topic.compliance.2"],
        output_topic="topic.compliance.output.159",
    )

    rule_160 = Rule(
        rule_id="RULE-L3-0160",
        name="reduce_interest_rate",
        group="fx",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.GT, value=65911),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="CRITICAL"),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="SETTLEMENT"),
            ],
        ),
        transform=lambda r: {"fee_amount": 436.33},
        dependencies=["RULE-L3-0186", "RULE-L3-0228"],
        topics=["topic.fx.3"],
        output_topic="topic.fx.output.160",
    )

    rule_161 = Rule(
        rule_id="RULE-L3-0161",
        name="route_invoice_line",
        group="compliance",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=68216),
                Condition(field_name="volume", operator=ConditionOperator.GT, value=91904),
                Condition(field_name="rate", operator=ConditionOperator.GT, value=54421),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="LOW"),
            ],
        ),
        transform=lambda r: {"approval_status": "HIGH"},
        dependencies=["RULE-L3-0170", "RULE-L3-0112", "RULE-L3-0251", "RULE-L3-0255", "RULE-L3-0035", "RULE-L3-0022", "RULE-L3-0036"],
        topics=["topic.compliance.12"],
        output_topic="topic.compliance.output.161",
    )

    rule_162 = Rule(
        rule_id="RULE-L3-0162",
        name="split_exchange_differential",
        group="derivatives",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.GT, value=22670),
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=18955),
                Condition(field_name="maturity_date", operator=ConditionOperator.GT, value=51977),
                Condition(field_name="counterparty", operator=ConditionOperator.GTE, value=6560),
                Condition(field_name="notional", operator=ConditionOperator.LT, value=48916),
                Condition(field_name="amount", operator=ConditionOperator.LT, value=39822),
            ],
        ),
        transform=lambda r: {"reserve_amount": 4921.28, "settlement_amount": 6964.87},
        dependencies=["RULE-L3-0222", "RULE-L3-0117", "RULE-L3-0230", "RULE-L3-0203", "RULE-L3-0180", "RULE-L3-0155"],
        topics=["topic.derivatives.4"],
        output_topic="topic.derivatives.output.162",
    )

    rule_163 = Rule(
        rule_id="RULE-L3-0163",
        name="normalize_compliance_flag",
        group="operations",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=95625),
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=84714),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="JPY"),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="LATAM"),
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=67637),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="CLEARING"),
            ],
        ),
        transform=lambda r: {"accrued_interest": 85.13, "risk_level": "REJECTED", "commission": 2.89},
        dependencies=["RULE-L3-0160", "RULE-L3-0047", "RULE-L3-0117", "RULE-L3-0131", "RULE-L3-0109", "RULE-L3-0142"],
        topics=["topic.operations.7"],
        output_topic="topic.operations.output.163",
    )

    rule_164 = Rule(
        rule_id="RULE-L3-0164",
        name="evaluate_credit_memo",
        group="credit",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="CREDIT_NOTE"),
            ],
        ),
        transform=lambda r: {"gross_value": 4647.54, "settlement_amount": 3975.45},
        dependencies=["RULE-L3-0099", "RULE-L3-0091", "RULE-L3-0058", "RULE-L3-0048", "RULE-L3-0109", "RULE-L3-0155", "RULE-L3-0002"],
        topics=["topic.credit.4"],
        output_topic="topic.credit.output.164",
    )

    rule_165 = Rule(
        rule_id="RULE-L3-0165",
        name="reconcile_interest_rate",
        group="valuation",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="COLLATERAL"),
                Condition(field_name="instrument", operator=ConditionOperator.LT, value=21532),
                Condition(field_name="account_id", operator=ConditionOperator.GT, value=37464),
                Condition(field_name="amount", operator=ConditionOperator.LTE, value=6607),
            ],
        ),
        transform=lambda r: {"penalty": 85.71},
        dependencies=["RULE-L3-0218", "RULE-L3-0189", "RULE-L3-0061", "RULE-L3-0184", "RULE-L3-0129", "RULE-L3-0069", "RULE-L3-0106"],
        topics=["topic.valuation.8"],
        output_topic="topic.valuation.output.165",
    )

    rule_166 = Rule(
        rule_id="RULE-L3-0166",
        name="evaluate_tax_obligation",
        group="fixed_income",
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.LTE, value=17442),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="SETTLEMENT"),
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=40137),
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=49445),
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=33129),
            ],
        ),
        transform=lambda r: {"clearing_fee": 3028.43},
        dependencies=["RULE-L3-0148", "RULE-L3-0094", "RULE-L3-0009", "RULE-L3-0252", "RULE-L3-0010", "RULE-L3-0146", "RULE-L3-0124", "RULE-L3-0182"],
        topics=["topic.fixed_income.13"],
        output_topic="topic.fixed_income.output.166",
    )

    rule_167 = Rule(
        rule_id="RULE-L3-0167",
        name="reduce_margin_call",
        group="ledger",
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="entity_id", operator=ConditionOperator.LT, value=89807),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="PENDING"),
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=84064),
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=34329),
                Condition(field_name="entity_id", operator=ConditionOperator.GTE, value=19751),
            ],
        ),
        transform=lambda r: {"margin_requirement": 80.54, "clearing_fee": 8025.61, "tax_rate": 0.6},
        dependencies=["RULE-L3-0029", "RULE-L3-0149", "RULE-L3-0124", "RULE-L3-0248", "RULE-L3-0178"],
        topics=["topic.ledger.11"],
        output_topic="topic.ledger.output.167",
    )

    # === Composite Rules (RULE-L3-0168 to RULE-L3-0256) ===

    rule_168 = CompositeRule(
        rule_id="RULE-L3-0168",
        name="transform_threshold_breach",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_76, rule_67, rule_108],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.EQ, value="PAYMENT"),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="COMPLIANCE"),
                Condition(field_name="entity_id", operator=ConditionOperator.GTE, value=86294),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="TRADE"),
            ],
        ),
    )

    rule_169 = CompositeRule(
        rule_id="RULE-L3-0169",
        name="split_liquidity_ratio",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_150, rule_76, rule_119],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.EQ, value="ADJUSTMENT"),
            ],
        ),
    )

    rule_170 = CompositeRule(
        rule_id="RULE-L3-0170",
        name="evaluate_risk_score",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_136, rule_77, rule_106],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="HIGH"),
            ],
        ),
    )

    rule_171 = CompositeRule(
        rule_id="RULE-L3-0171",
        name="transform_capital_allocation",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_21, rule_125],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="counterparty", operator=ConditionOperator.GT, value=717),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=27544),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="MARGIN"),
            ],
        ),
    )

    rule_172 = CompositeRule(
        rule_id="RULE-L3-0172",
        name="validate_compliance_flag",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_163, rule_110, rule_104],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.GT, value=5044),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="NA"),
                Condition(field_name="counterparty", operator=ConditionOperator.EQ, value=25079),
                Condition(field_name="amount", operator=ConditionOperator.GT, value=82241),
            ],
        ),
    )

    rule_173 = CompositeRule(
        rule_id="RULE-L3-0173",
        name="filter_amortization_table",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_99, rule_129],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.EQ, value="TRADE"),
                Condition(field_name="entity_id", operator=ConditionOperator.LT, value=59859),
                Condition(field_name="counterparty", operator=ConditionOperator.LTE, value=90117),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="CRITICAL"),
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=21711),
            ],
        ),
    )

    rule_174 = CompositeRule(
        rule_id="RULE-L3-0174",
        name="transform_accrual_entry",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_151, rule_130],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=49277),
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=81775),
            ],
        ),
    )

    rule_175 = CompositeRule(
        rule_id="RULE-L3-0175",
        name="cascade_credit_memo",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_6, rule_13],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="rate", operator=ConditionOperator.LTE, value=49940),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="SETTLED"),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="LOW"),
                Condition(field_name="entity_id", operator=ConditionOperator.LTE, value=86825),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="CANCELLED"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="LOW"),
            ],
        ),
    )

    rule_176 = CompositeRule(
        rule_id="RULE-L3-0176",
        name="derive_risk_score",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_28, rule_128],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=26533),
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=38812),
            ],
        ),
    )

    rule_177 = CompositeRule(
        rule_id="RULE-L3-0177",
        name="dispatch_payment_batch",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_54, rule_124, rule_85],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.GT, value=14574),
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=11907),
            ],
        ),
    )

    rule_178 = CompositeRule(
        rule_id="RULE-L3-0178",
        name="derive_invoice_line",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_26, rule_66, rule_165, rule_60],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=6664),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="PENDING"),
                Condition(field_name="entity_id", operator=ConditionOperator.LT, value=88805),
                Condition(field_name="counterparty", operator=ConditionOperator.LTE, value=96901),
            ],
        ),
    )

    rule_179 = CompositeRule(
        rule_id="RULE-L3-0179",
        name="transform_revenue_stream",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_113, rule_160, rule_69],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.LT, value=24069),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="SETTLED"),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=50656),
                Condition(field_name="notional", operator=ConditionOperator.LTE, value=85145),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="SETTLEMENT"),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="INVOICE"),
            ],
        ),
    )

    rule_180 = CompositeRule(
        rule_id="RULE-L3-0180",
        name="split_yield_curve",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_113, rule_47, rule_157, rule_98],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="CRITICAL"),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="SETTLED"),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="PAYMENT"),
            ],
        ),
    )

    rule_181 = CompositeRule(
        rule_id="RULE-L3-0181",
        name="route_ledger_delta",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_135, rule_148, rule_145, rule_58],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="APPROVED"),
                Condition(field_name="notional", operator=ConditionOperator.LT, value=87093),
                Condition(field_name="maturity_date", operator=ConditionOperator.GTE, value=73283),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="CREDIT_NOTE"),
                Condition(field_name="notional", operator=ConditionOperator.LTE, value=21779),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="GBP"),
            ],
        ),
    )

    rule_182 = CompositeRule(
        rule_id="RULE-L3-0182",
        name="normalize_liquidity_ratio",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_130, rule_58],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.GTE, value=10432),
                Condition(field_name="volume", operator=ConditionOperator.LTE, value=75208),
                Condition(field_name="volume", operator=ConditionOperator.GT, value=65433),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=15659),
                Condition(field_name="notional", operator=ConditionOperator.GT, value=13553),
            ],
        ),
    )

    rule_183 = CompositeRule(
        rule_id="RULE-L3-0183",
        name="validate_amortization_table",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_53, rule_117, rule_88, rule_94],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.LT, value=73520),
            ],
        ),
    )

    rule_184 = CompositeRule(
        rule_id="RULE-L3-0184",
        name="filter_hedge_effectiveness",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_57, rule_1],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="entity_id", operator=ConditionOperator.EQ, value=68517),
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=6100),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="SETTLEMENT"),
            ],
        ),
    )

    rule_185 = CompositeRule(
        rule_id="RULE-L3-0185",
        name="split_margin_call",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_51, rule_49, rule_31, rule_101],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="NA"),
                Condition(field_name="rate", operator=ConditionOperator.GT, value=83100),
            ],
        ),
    )

    rule_186 = CompositeRule(
        rule_id="RULE-L3-0186",
        name="reduce_risk_score",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_151, rule_130, rule_35],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="TRANSFER"),
                Condition(field_name="notional", operator=ConditionOperator.EQ, value=23326),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="TRADE"),
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=79550),
            ],
        ),
    )

    rule_187 = CompositeRule(
        rule_id="RULE-L3-0187",
        name="route_counterparty_risk",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_64, rule_71, rule_102, rule_88],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="CRITICAL"),
                Condition(field_name="entity_id", operator=ConditionOperator.EQ, value=41244),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="EMEA"),
            ],
        ),
    )

    rule_188 = CompositeRule(
        rule_id="RULE-L3-0188",
        name="accumulate_withholding_amount",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_34, rule_167, rule_46],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="CANCELLED"),
                Condition(field_name="notional", operator=ConditionOperator.EQ, value=74894),
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=37577),
                Condition(field_name="rate", operator=ConditionOperator.GT, value=68615),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="SETTLED"),
            ],
        ),
    )

    rule_189 = CompositeRule(
        rule_id="RULE-L3-0189",
        name="transform_credit_memo",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_52, rule_69],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=8230),
                Condition(field_name="entity_id", operator=ConditionOperator.GTE, value=98875),
            ],
        ),
    )

    rule_190 = CompositeRule(
        rule_id="RULE-L3-0190",
        name="project_payment_batch",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_27, rule_158, rule_144],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="TREASURY"),
                Condition(field_name="maturity_date", operator=ConditionOperator.LTE, value=54700),
            ],
        ),
    )

    rule_191 = CompositeRule(
        rule_id="RULE-L3-0191",
        name="evaluate_hedge_effectiveness",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_166, rule_95, rule_151, rule_140],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="LATAM"),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="SETTLEMENT"),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="MARGIN"),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="PAYMENT"),
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=21193),
                Condition(field_name="account_id", operator=ConditionOperator.GT, value=43427),
            ],
        ),
    )

    rule_192 = CompositeRule(
        rule_id="RULE-L3-0192",
        name="correlate_audit_trail",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_83, rule_153],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.EQ, value=72210),
            ],
        ),
    )

    rule_193 = CompositeRule(
        rule_id="RULE-L3-0193",
        name="filter_invoice_line",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_135, rule_57, rule_48],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="COLLATERAL"),
                Condition(field_name="maturity_date", operator=ConditionOperator.GT, value=45896),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="COMPLIANCE"),
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=38579),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="NA"),
            ],
        ),
    )

    rule_194 = CompositeRule(
        rule_id="RULE-L3-0194",
        name="aggregate_solvency_metric",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_165, rule_158],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="ADJUSTMENT"),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="REJECTED"),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=67846),
                Condition(field_name="instrument", operator=ConditionOperator.EQ, value=66780),
                Condition(field_name="volume", operator=ConditionOperator.LTE, value=5847),
            ],
        ),
    )

    rule_195 = CompositeRule(
        rule_id="RULE-L3-0195",
        name="aggregate_revenue_stream",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_2, rule_161, rule_17, rule_54],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="rate", operator=ConditionOperator.GT, value=27045),
                Condition(field_name="rate", operator=ConditionOperator.GT, value=97996),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="CRITICAL"),
                Condition(field_name="counterparty", operator=ConditionOperator.GT, value=11571),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="EUR"),
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=9332),
            ],
        ),
    )

    rule_196 = CompositeRule(
        rule_id="RULE-L3-0196",
        name="enrich_mark_to_market",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_162, rule_104, rule_111],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.GT, value=70201),
                Condition(field_name="amount", operator=ConditionOperator.EQ, value=8388),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="PAYMENT"),
            ],
        ),
    )

    rule_197 = CompositeRule(
        rule_id="RULE-L3-0197",
        name="derive_margin_call",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_78, rule_156, rule_23, rule_73],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.GT, value=62226),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="SETTLEMENT"),
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=38763),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="HIGH"),
            ],
        ),
    )

    rule_198 = CompositeRule(
        rule_id="RULE-L3-0198",
        name="aggregate_payment_batch",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_153, rule_101, rule_138, rule_141],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="EMEA"),
            ],
        ),
    )

    rule_199 = CompositeRule(
        rule_id="RULE-L3-0199",
        name="split_audit_trail",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_57, rule_158],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.EQ, value="CANCELLED"),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="TRANSFER"),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="USD"),
            ],
        ),
    )

    rule_200 = CompositeRule(
        rule_id="RULE-L3-0200",
        name="evaluate_duration_gap",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_33, rule_61, rule_26],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="LATAM"),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=80885),
                Condition(field_name="entity_id", operator=ConditionOperator.EQ, value=20074),
            ],
        ),
    )

    rule_201 = CompositeRule(
        rule_id="RULE-L3-0201",
        name="reduce_exposure_limit",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_44, rule_2, rule_81],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="rate", operator=ConditionOperator.LT, value=47218),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="CRITICAL"),
            ],
        ),
    )

    rule_202 = CompositeRule(
        rule_id="RULE-L3-0202",
        name="correlate_hedge_effectiveness",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_125, rule_142, rule_28],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=70697),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="NA"),
            ],
        ),
    )

    rule_203 = CompositeRule(
        rule_id="RULE-L3-0203",
        name="validate_threshold_breach",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_8, rule_149, rule_104, rule_152],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=70836),
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=48048),
            ],
        ),
    )

    rule_204 = CompositeRule(
        rule_id="RULE-L3-0204",
        name="merge_depreciation_schedule",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_75, rule_35, rule_119, rule_129],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.LT, value=65920),
                Condition(field_name="amount", operator=ConditionOperator.GTE, value=80582),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="MARGIN"),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="COLLATERAL"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="HIGH"),
            ],
        ),
    )

    rule_205 = CompositeRule(
        rule_id="RULE-L3-0205",
        name="compute_depreciation_schedule",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_95, rule_60, rule_11],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=61661),
                Condition(field_name="volume", operator=ConditionOperator.GT, value=5330),
                Condition(field_name="counterparty", operator=ConditionOperator.GT, value=92340),
                Condition(field_name="account_id", operator=ConditionOperator.LT, value=75942),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="MARGIN"),
                Condition(field_name="instrument", operator=ConditionOperator.EQ, value=85734),
            ],
        ),
    )

    rule_206 = CompositeRule(
        rule_id="RULE-L3-0206",
        name="validate_exchange_differential",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_133, rule_104],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.LTE, value=79295),
                Condition(field_name="amount", operator=ConditionOperator.EQ, value=18314),
                Condition(field_name="volume", operator=ConditionOperator.GTE, value=30245),
            ],
        ),
    )

    rule_207 = CompositeRule(
        rule_id="RULE-L3-0207",
        name="validate_tax_obligation",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_48, rule_41],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="COMPLIANCE"),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="SETTLED"),
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=77536),
            ],
        ),
    )

    rule_208 = CompositeRule(
        rule_id="RULE-L3-0208",
        name="dispatch_mark_to_market",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_12, rule_33],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="MEDIUM"),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="PAYMENT"),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="COLLATERAL"),
                Condition(field_name="amount", operator=ConditionOperator.LT, value=11339),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="LATAM"),
            ],
        ),
    )

    rule_209 = CompositeRule(
        rule_id="RULE-L3-0209",
        name="compute_revenue_stream",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_154, rule_37, rule_150],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="MARGIN"),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="JPY"),
            ],
        ),
    )

    rule_210 = CompositeRule(
        rule_id="RULE-L3-0210",
        name="merge_compliance_flag",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_52, rule_134],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="MEDIUM"),
                Condition(field_name="notional", operator=ConditionOperator.EQ, value=78718),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="INVOICE"),
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=79198),
                Condition(field_name="amount", operator=ConditionOperator.LTE, value=68525),
            ],
        ),
    )

    rule_211 = CompositeRule(
        rule_id="RULE-L3-0211",
        name="split_exposure_limit",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_136, rule_110, rule_59, rule_124],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="APPROVED"),
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=30575),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="CHF"),
                Condition(field_name="rate", operator=ConditionOperator.LT, value=24875),
            ],
        ),
    )

    rule_212 = CompositeRule(
        rule_id="RULE-L3-0212",
        name="derive_ledger_delta",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_53, rule_81, rule_105, rule_93],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=33344),
            ],
        ),
    )

    rule_213 = CompositeRule(
        rule_id="RULE-L3-0213",
        name="enrich_position_delta",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_157, rule_71, rule_102],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=48624),
                Condition(field_name="notional", operator=ConditionOperator.LT, value=40293),
            ],
        ),
    )

    rule_214 = CompositeRule(
        rule_id="RULE-L3-0214",
        name="reduce_solvency_metric",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_36, rule_31, rule_59],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.EQ, value="CANCELLED"),
                Condition(field_name="maturity_date", operator=ConditionOperator.LT, value=72265),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="ADJUSTMENT"),
                Condition(field_name="amount", operator=ConditionOperator.GT, value=19148),
            ],
        ),
    )

    rule_215 = CompositeRule(
        rule_id="RULE-L3-0215",
        name="compute_position_delta",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_68, rule_57],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="ADJUSTMENT"),
                Condition(field_name="entity_id", operator=ConditionOperator.EQ, value=7631),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="MARGIN"),
            ],
        ),
    )

    rule_216 = CompositeRule(
        rule_id="RULE-L3-0216",
        name="evaluate_payment_batch",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_133, rule_60, rule_158, rule_44],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=85954),
                Condition(field_name="amount", operator=ConditionOperator.GTE, value=11482),
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=46385),
                Condition(field_name="maturity_date", operator=ConditionOperator.LTE, value=76918),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="NA"),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="CHF"),
            ],
        ),
    )

    rule_217 = CompositeRule(
        rule_id="RULE-L3-0217",
        name="filter_tax_obligation",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_50, rule_117, rule_104, rule_148],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="COLLATERAL"),
            ],
        ),
    )

    rule_218 = CompositeRule(
        rule_id="RULE-L3-0218",
        name="aggregate_invoice_line",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_88, rule_30, rule_132],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.LTE, value=73915),
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=99383),
                Condition(field_name="counterparty", operator=ConditionOperator.LTE, value=89437),
            ],
        ),
    )

    rule_219 = CompositeRule(
        rule_id="RULE-L3-0219",
        name="correlate_threshold_breach",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_67, rule_18],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="OPERATIONS"),
                Condition(field_name="instrument", operator=ConditionOperator.EQ, value=70308),
                Condition(field_name="amount", operator=ConditionOperator.LT, value=32639),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=52388),
            ],
        ),
    )

    rule_220 = CompositeRule(
        rule_id="RULE-L3-0220",
        name="project_cost_center",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_91, rule_56, rule_147],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="EMEA"),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="COMPLIANCE"),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="EMEA"),
            ],
        ),
    )

    rule_221 = CompositeRule(
        rule_id="RULE-L3-0221",
        name="aggregate_settlement_window",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_127, rule_158, rule_2, rule_139],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.EQ, value=41442),
            ],
        ),
    )

    rule_222 = CompositeRule(
        rule_id="RULE-L3-0222",
        name="compute_tax_obligation",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_131, rule_72],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="CRITICAL"),
                Condition(field_name="notional", operator=ConditionOperator.EQ, value=4368),
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=90059),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="TRADE"),
            ],
        ),
    )

    rule_223 = CompositeRule(
        rule_id="RULE-L3-0223",
        name="derive_basis_spread",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_3, rule_4, rule_54, rule_98],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="counterparty", operator=ConditionOperator.LT, value=80418),
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=72001),
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=35411),
                Condition(field_name="notional", operator=ConditionOperator.EQ, value=45070),
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=65474),
            ],
        ),
    )

    rule_224 = CompositeRule(
        rule_id="RULE-L3-0224",
        name="split_accrual_entry",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_96, rule_94, rule_103, rule_72],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="LOW"),
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=72889),
                Condition(field_name="rate", operator=ConditionOperator.LTE, value=25798),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="CRITICAL"),
            ],
        ),
    )

    rule_225 = CompositeRule(
        rule_id="RULE-L3-0225",
        name="reconcile_cost_center",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_35, rule_162, rule_133],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.LT, value=32995),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="INVOICE"),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="SETTLEMENT"),
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=82657),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="REJECTED"),
            ],
        ),
    )

    rule_226 = CompositeRule(
        rule_id="RULE-L3-0226",
        name="enrich_exposure_limit",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_143, rule_66, rule_89, rule_6],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.EQ, value=26177),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="CLEARING"),
                Condition(field_name="counterparty", operator=ConditionOperator.EQ, value=63996),
                Condition(field_name="volume", operator=ConditionOperator.GT, value=50047),
            ],
        ),
    )

    rule_227 = CompositeRule(
        rule_id="RULE-L3-0227",
        name="dispatch_liquidity_ratio",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_157, rule_147, rule_104, rule_19],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="counterparty", operator=ConditionOperator.GTE, value=41188),
            ],
        ),
    )

    rule_228 = CompositeRule(
        rule_id="RULE-L3-0228",
        name="route_withholding_amount",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_155, rule_166, rule_102],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="instrument", operator=ConditionOperator.EQ, value=68380),
                Condition(field_name="volume", operator=ConditionOperator.LTE, value=22030),
                Condition(field_name="category", operator=ConditionOperator.EQ, value="SETTLEMENT"),
            ],
        ),
    )

    rule_229 = CompositeRule(
        rule_id="RULE-L3-0229",
        name="normalize_exchange_differential",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_21, rule_54, rule_43, rule_102],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="CHF"),
            ],
        ),
    )

    rule_230 = CompositeRule(
        rule_id="RULE-L3-0230",
        name="cascade_threshold_breach",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_22, rule_27, rule_68, rule_159],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.LT, value=30162),
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="OPERATIONS"),
            ],
        ),
    )

    rule_231 = CompositeRule(
        rule_id="RULE-L3-0231",
        name="derive_revenue_stream",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_92, rule_84],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="account_id", operator=ConditionOperator.EQ, value=58406),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="CRITICAL"),
                Condition(field_name="rate", operator=ConditionOperator.EQ, value=83958),
                Condition(field_name="entity_id", operator=ConditionOperator.LT, value=63231),
            ],
        ),
    )

    rule_232 = CompositeRule(
        rule_id="RULE-L3-0232",
        name="project_depreciation_schedule",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_79, rule_94, rule_106],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=112),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="HIGH"),
                Condition(field_name="notional", operator=ConditionOperator.EQ, value=1190),
            ],
        ),
    )

    rule_233 = CompositeRule(
        rule_id="RULE-L3-0233",
        name="compute_yield_curve",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_111, rule_75],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.EQ, value=49074),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="LATAM"),
                Condition(field_name="maturity_date", operator=ConditionOperator.GTE, value=21500),
                Condition(field_name="maturity_date", operator=ConditionOperator.LTE, value=29013),
                Condition(field_name="account_id", operator=ConditionOperator.GT, value=55443),
            ],
        ),
    )

    rule_234 = CompositeRule(
        rule_id="RULE-L3-0234",
        name="normalize_tax_obligation",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_137, rule_69, rule_106, rule_49],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="LOW"),
            ],
        ),
    )

    rule_235 = CompositeRule(
        rule_id="RULE-L3-0235",
        name="evaluate_capital_allocation",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_13, rule_137],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="REJECTED"),
            ],
        ),
    )

    rule_236 = CompositeRule(
        rule_id="RULE-L3-0236",
        name="reconcile_depreciation_schedule",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_4, rule_127],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="rate", operator=ConditionOperator.LT, value=65425),
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=91448),
            ],
        ),
    )

    rule_237 = CompositeRule(
        rule_id="RULE-L3-0237",
        name="cascade_liquidity_ratio",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_15, rule_69],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=25291),
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=1753),
                Condition(field_name="status", operator=ConditionOperator.EQ, value="SETTLED"),
                Condition(field_name="volume", operator=ConditionOperator.GTE, value=96781),
            ],
        ),
    )

    rule_238 = CompositeRule(
        rule_id="RULE-L3-0238",
        name="cascade_budget_variance",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_25, rule_134, rule_54, rule_122],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="counterparty", operator=ConditionOperator.GTE, value=82565),
                Condition(field_name="type", operator=ConditionOperator.EQ, value="PAYMENT"),
                Condition(field_name="notional", operator=ConditionOperator.LT, value=26147),
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=87485),
            ],
        ),
    )

    rule_239 = CompositeRule(
        rule_id="RULE-L3-0239",
        name="normalize_position_delta",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_43, rule_71],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.GTE, value=1270),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="TRANSFER"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="LOW"),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="OPERATIONS"),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="USD"),
            ],
        ),
    )

    rule_240 = CompositeRule(
        rule_id="RULE-L3-0240",
        name="cascade_solvency_metric",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_138, rule_28],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="department", operator=ConditionOperator.NEQ, value="TRADING"),
                Condition(field_name="instrument", operator=ConditionOperator.LTE, value=96200),
            ],
        ),
    )

    rule_241 = CompositeRule(
        rule_id="RULE-L3-0241",
        name="merge_solvency_metric",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_65, rule_11],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="entity_id", operator=ConditionOperator.EQ, value=91462),
                Condition(field_name="notional", operator=ConditionOperator.GTE, value=74378),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="CLEARING"),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=78570),
            ],
        ),
    )

    rule_242 = CompositeRule(
        rule_id="RULE-L3-0242",
        name="project_revenue_stream",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_40, rule_116, rule_76, rule_68],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.GT, value=83727),
                Condition(field_name="maturity_date", operator=ConditionOperator.GTE, value=2553),
                Condition(field_name="instrument", operator=ConditionOperator.EQ, value=31398),
                Condition(field_name="counterparty", operator=ConditionOperator.GT, value=86383),
                Condition(field_name="maturity_date", operator=ConditionOperator.GTE, value=68790),
            ],
        ),
    )

    rule_243 = CompositeRule(
        rule_id="RULE-L3-0243",
        name="compute_audit_trail",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_83, rule_105, rule_165],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.EQ, value="PENDING"),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="LOW"),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="LATAM"),
            ],
        ),
    )

    rule_244 = CompositeRule(
        rule_id="RULE-L3-0244",
        name="evaluate_margin_call",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_165, rule_100, rule_126, rule_135],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="CREDIT_NOTE"),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="EUR"),
                Condition(field_name="notional", operator=ConditionOperator.GT, value=61449),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="TRANSFER"),
                Condition(field_name="rate", operator=ConditionOperator.LT, value=92955),
            ],
        ),
    )

    rule_245 = CompositeRule(
        rule_id="RULE-L3-0245",
        name="cascade_tax_obligation",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_19, rule_78],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.EQ, value="APPROVED"),
            ],
        ),
    )

    rule_246 = CompositeRule(
        rule_id="RULE-L3-0246",
        name="evaluate_budget_variance",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_64, rule_146, rule_161, rule_46],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="SETTLED"),
                Condition(field_name="rate", operator=ConditionOperator.GT, value=21964),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="COLLATERAL"),
                Condition(field_name="counterparty", operator=ConditionOperator.GTE, value=70079),
                Condition(field_name="volume", operator=ConditionOperator.LT, value=41407),
            ],
        ),
    )

    rule_247 = CompositeRule(
        rule_id="RULE-L3-0247",
        name="filter_mark_to_market",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_83, rule_156, rule_62],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=97693),
                Condition(field_name="account_id", operator=ConditionOperator.LT, value=59397),
                Condition(field_name="volume", operator=ConditionOperator.LTE, value=125),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="TRANSFER"),
                Condition(field_name="amount", operator=ConditionOperator.EQ, value=17805),
            ],
        ),
    )

    rule_248 = CompositeRule(
        rule_id="RULE-L3-0248",
        name="classify_depreciation_schedule",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_6, rule_71, rule_142],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.EQ, value="SETTLED"),
                Condition(field_name="instrument", operator=ConditionOperator.GTE, value=18241),
                Condition(field_name="account_id", operator=ConditionOperator.LT, value=76404),
                Condition(field_name="department", operator=ConditionOperator.EQ, value="COMPLIANCE"),
                Condition(field_name="entity_id", operator=ConditionOperator.GT, value=74874),
            ],
        ),
    )

    rule_249 = CompositeRule(
        rule_id="RULE-L3-0249",
        name="merge_accrual_entry",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_84, rule_124],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="PENDING"),
                Condition(field_name="maturity_date", operator=ConditionOperator.GT, value=7429),
            ],
        ),
    )

    rule_250 = CompositeRule(
        rule_id="RULE-L3-0250",
        name="split_mark_to_market",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_155, rule_3],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="TRANSFER"),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="TRANSFER"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="MEDIUM"),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="CRITICAL"),
                Condition(field_name="volume", operator=ConditionOperator.EQ, value=75499),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="JPY"),
            ],
        ),
    )

    rule_251 = CompositeRule(
        rule_id="RULE-L3-0251",
        name="compute_credit_memo",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_68, rule_22, rule_103],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="CRITICAL"),
                Condition(field_name="region", operator=ConditionOperator.NEQ, value="LATAM"),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="EMEA"),
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="JPY"),
                Condition(field_name="counterparty", operator=ConditionOperator.EQ, value=11843),
            ],
        ),
    )

    rule_252 = CompositeRule(
        rule_id="RULE-L3-0252",
        name="aggregate_mark_to_market",
        mode=CompositionMode.PARALLEL,
        sub_rules=[rule_90, rule_49, rule_83],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="entity_id", operator=ConditionOperator.GTE, value=45938),
                Condition(field_name="volume", operator=ConditionOperator.EQ, value=19212),
                Condition(field_name="volume", operator=ConditionOperator.GT, value=30703),
            ],
        ),
    )

    rule_253 = CompositeRule(
        rule_id="RULE-L3-0253",
        name="aggregate_credit_memo",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_38, rule_74, rule_4, rule_88],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="entity_id", operator=ConditionOperator.LTE, value=61859),
                Condition(field_name="amount", operator=ConditionOperator.LT, value=27495),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="APAC"),
                Condition(field_name="notional", operator=ConditionOperator.EQ, value=95772),
                Condition(field_name="priority", operator=ConditionOperator.EQ, value="CRITICAL"),
                Condition(field_name="type", operator=ConditionOperator.NEQ, value="CREDIT_NOTE"),
            ],
        ),
    )

    rule_254 = CompositeRule(
        rule_id="RULE-L3-0254",
        name="cascade_withholding_amount",
        mode=CompositionMode.SEQUENTIAL,
        sub_rules=[rule_159, rule_70, rule_14, rule_120],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="currency", operator=ConditionOperator.NEQ, value="GBP"),
                Condition(field_name="instrument", operator=ConditionOperator.GT, value=2600),
                Condition(field_name="entity_id", operator=ConditionOperator.LTE, value=30399),
                Condition(field_name="maturity_date", operator=ConditionOperator.EQ, value=93120),
                Condition(field_name="status", operator=ConditionOperator.NEQ, value="SETTLED"),
                Condition(field_name="currency", operator=ConditionOperator.EQ, value="EUR"),
            ],
        ),
    )

    rule_255 = CompositeRule(
        rule_id="RULE-L3-0255",
        name="cascade_interest_rate",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_86, rule_126, rule_101],
        conditions=ConditionGroup(
            logic=LogicOperator.AND,
            conditions=[
                Condition(field_name="amount", operator=ConditionOperator.LT, value=89794),
                Condition(field_name="instrument", operator=ConditionOperator.LT, value=82050),
                Condition(field_name="entity_id", operator=ConditionOperator.GTE, value=65800),
                Condition(field_name="account_id", operator=ConditionOperator.GT, value=82123),
                Condition(field_name="account_id", operator=ConditionOperator.LTE, value=3962),
                Condition(field_name="account_id", operator=ConditionOperator.GTE, value=19984),
            ],
        ),
    )

    rule_256 = CompositeRule(
        rule_id="RULE-L3-0256",
        name="split_interest_rate",
        mode=CompositionMode.CONDITIONAL,
        sub_rules=[rule_110, rule_80],
        conditions=ConditionGroup(
            logic=LogicOperator.OR,
            conditions=[
                Condition(field_name="volume", operator=ConditionOperator.EQ, value=17371),
                Condition(field_name="region", operator=ConditionOperator.EQ, value="EMEA"),
                Condition(field_name="priority", operator=ConditionOperator.NEQ, value="MEDIUM"),
                Condition(field_name="rate", operator=ConditionOperator.GTE, value=86113),
                Condition(field_name="category", operator=ConditionOperator.NEQ, value="TRADE"),
            ],
        ),
    )

    # === Register all rules ===
    all_rules = [
        rule_1, rule_2, rule_3, rule_4, rule_5, rule_6, rule_7, rule_8,
        rule_9, rule_10, rule_11, rule_12, rule_13, rule_14, rule_15, rule_16,
        rule_17, rule_18, rule_19, rule_20, rule_21, rule_22, rule_23, rule_24,
        rule_25, rule_26, rule_27, rule_28, rule_29, rule_30, rule_31, rule_32,
        rule_33, rule_34, rule_35, rule_36, rule_37, rule_38, rule_39, rule_40,
        rule_41, rule_42, rule_43, rule_44, rule_45, rule_46, rule_47, rule_48,
        rule_49, rule_50, rule_51, rule_52, rule_53, rule_54, rule_55, rule_56,
        rule_57, rule_58, rule_59, rule_60, rule_61, rule_62, rule_63, rule_64,
        rule_65, rule_66, rule_67, rule_68, rule_69, rule_70, rule_71, rule_72,
        rule_73, rule_74, rule_75, rule_76, rule_77, rule_78, rule_79, rule_80,
        rule_81, rule_82, rule_83, rule_84, rule_85, rule_86, rule_87, rule_88,
        rule_89, rule_90, rule_91, rule_92, rule_93, rule_94, rule_95, rule_96,
        rule_97, rule_98, rule_99, rule_100, rule_101, rule_102, rule_103, rule_104,
        rule_105, rule_106, rule_107, rule_108, rule_109, rule_110, rule_111, rule_112,
        rule_113, rule_114, rule_115, rule_116, rule_117, rule_118, rule_119, rule_120,
        rule_121, rule_122, rule_123, rule_124, rule_125, rule_126, rule_127, rule_128,
        rule_129, rule_130, rule_131, rule_132, rule_133, rule_134, rule_135, rule_136,
        rule_137, rule_138, rule_139, rule_140, rule_141, rule_142, rule_143, rule_144,
        rule_145, rule_146, rule_147, rule_148, rule_149, rule_150, rule_151, rule_152,
        rule_153, rule_154, rule_155, rule_156, rule_157, rule_158, rule_159, rule_160,
        rule_161, rule_162, rule_163, rule_164, rule_165, rule_166, rule_167, rule_168,
        rule_169, rule_170, rule_171, rule_172, rule_173, rule_174, rule_175, rule_176,
        rule_177, rule_178, rule_179, rule_180, rule_181, rule_182, rule_183, rule_184,
        rule_185, rule_186, rule_187, rule_188, rule_189, rule_190, rule_191, rule_192,
        rule_193, rule_194, rule_195, rule_196, rule_197, rule_198, rule_199, rule_200,
        rule_201, rule_202, rule_203, rule_204, rule_205, rule_206, rule_207, rule_208,
        rule_209, rule_210, rule_211, rule_212, rule_213, rule_214, rule_215, rule_216,
        rule_217, rule_218, rule_219, rule_220, rule_221, rule_222, rule_223, rule_224,
        rule_225, rule_226, rule_227, rule_228, rule_229, rule_230, rule_231, rule_232,
        rule_233, rule_234, rule_235, rule_236, rule_237, rule_238, rule_239, rule_240,
        rule_241, rule_242, rule_243, rule_244, rule_245, rule_246, rule_247, rule_248,
        rule_249, rule_250, rule_251, rule_252, rule_253, rule_254, rule_255, rule_256,
    ]
    for rule in all_rules:
        pipeline.rule_registry.register(rule)

    # === Integration Points (IP-L3-0001 to IP-L3-0064) ===

    ip_1 = IntegrationPoint(
        point_id="IP-L3-0001",
        name="integration_slot_1",
        topic="topic.credit.output.4",
        position=0,
        required_rules=["RULE-L3-0144", "RULE-L3-0239"],
    )
    pipeline.integration_points.add(ip_1)
    ip_1.register_rule("RULE-L3-0144")
    ip_1.register_rule("RULE-L3-0239")

    ip_2 = IntegrationPoint(
        point_id="IP-L3-0002",
        name="integration_slot_2",
        topic="topic.treasury.6",
        position=1,
        required_rules=["RULE-L3-0046"],
    )
    pipeline.integration_points.add(ip_2)
    ip_2.register_rule("RULE-L3-0046")

    ip_3 = IntegrationPoint(
        point_id="IP-L3-0003",
        name="integration_slot_3",
        topic="topic.ledger.8",
        position=2,
        required_rules=["RULE-L3-0040", "RULE-L3-0160", "RULE-L3-0028", "RULE-L3-0176"],
    )
    pipeline.integration_points.add(ip_3)
    ip_3.register_rule("RULE-L3-0040")
    ip_3.register_rule("RULE-L3-0160")
    ip_3.register_rule("RULE-L3-0028")
    ip_3.register_rule("RULE-L3-0176")

    ip_4 = IntegrationPoint(
        point_id="IP-L3-0004",
        name="integration_slot_4",
        topic="topic.treasury.output.150",
        position=3,
        required_rules=["RULE-L3-0241"],
    )
    pipeline.integration_points.add(ip_4)
    ip_4.register_rule("RULE-L3-0241")

    ip_5 = IntegrationPoint(
        point_id="IP-L3-0005",
        name="integration_slot_5",
        topic="topic.settlement.11",
        position=4,
        required_rules=["RULE-L3-0170", "RULE-L3-0216", "RULE-L3-0181", "RULE-L3-0151"],
    )
    pipeline.integration_points.add(ip_5)
    ip_5.register_rule("RULE-L3-0170")
    ip_5.register_rule("RULE-L3-0216")
    ip_5.register_rule("RULE-L3-0181")
    ip_5.register_rule("RULE-L3-0151")

    ip_6 = IntegrationPoint(
        point_id="IP-L3-0006",
        name="integration_slot_6",
        topic="topic.operations.output.108",
        position=5,
        required_rules=["RULE-L3-0019", "RULE-L3-0156"],
    )
    pipeline.integration_points.add(ip_6)
    ip_6.register_rule("RULE-L3-0019")
    ip_6.register_rule("RULE-L3-0156")

    ip_7 = IntegrationPoint(
        point_id="IP-L3-0007",
        name="integration_slot_7",
        topic="topic.valuation.output.89",
        position=6,
        required_rules=["RULE-L3-0032", "RULE-L3-0243", "RULE-L3-0087"],
    )
    pipeline.integration_points.add(ip_7)
    ip_7.register_rule("RULE-L3-0032")
    ip_7.register_rule("RULE-L3-0243")
    ip_7.register_rule("RULE-L3-0087")

    ip_8 = IntegrationPoint(
        point_id="IP-L3-0008",
        name="integration_slot_8",
        topic="topic.credit.3",
        position=7,
        required_rules=["RULE-L3-0014", "RULE-L3-0147", "RULE-L3-0249"],
    )
    pipeline.integration_points.add(ip_8)
    ip_8.register_rule("RULE-L3-0014")
    ip_8.register_rule("RULE-L3-0147")
    ip_8.register_rule("RULE-L3-0249")

    ip_9 = IntegrationPoint(
        point_id="IP-L3-0009",
        name="integration_slot_9",
        topic="topic.credit.output.5",
        position=8,
        required_rules=["RULE-L3-0040", "RULE-L3-0143"],
    )
    pipeline.integration_points.add(ip_9)
    ip_9.register_rule("RULE-L3-0040")
    ip_9.register_rule("RULE-L3-0143")

    ip_10 = IntegrationPoint(
        point_id="IP-L3-0010",
        name="integration_slot_10",
        topic="topic.ledger.output.137",
        position=9,
        required_rules=["RULE-L3-0144", "RULE-L3-0141"],
    )
    pipeline.integration_points.add(ip_10)
    ip_10.register_rule("RULE-L3-0144")
    ip_10.register_rule("RULE-L3-0141")

    ip_11 = IntegrationPoint(
        point_id="IP-L3-0011",
        name="integration_slot_11",
        topic="topic.ledger.output.16",
        position=10,
        required_rules=["RULE-L3-0058"],
    )
    pipeline.integration_points.add(ip_11)
    ip_11.register_rule("RULE-L3-0058")

    ip_12 = IntegrationPoint(
        point_id="IP-L3-0012",
        name="integration_slot_12",
        topic="topic.fixed_income.16",
        position=11,
        required_rules=["RULE-L3-0229", "RULE-L3-0190"],
    )
    pipeline.integration_points.add(ip_12)
    ip_12.register_rule("RULE-L3-0229")
    ip_12.register_rule("RULE-L3-0190")

    ip_13 = IntegrationPoint(
        point_id="IP-L3-0013",
        name="integration_slot_13",
        topic="topic.fixed_income.16",
        position=12,
        required_rules=["RULE-L3-0121", "RULE-L3-0249", "RULE-L3-0093"],
    )
    pipeline.integration_points.add(ip_13)
    ip_13.register_rule("RULE-L3-0121")
    ip_13.register_rule("RULE-L3-0249")
    ip_13.register_rule("RULE-L3-0093")

    ip_14 = IntegrationPoint(
        point_id="IP-L3-0014",
        name="integration_slot_14",
        topic="topic.treasury.output.132",
        position=13,
        required_rules=["RULE-L3-0176"],
    )
    pipeline.integration_points.add(ip_14)
    ip_14.register_rule("RULE-L3-0176")

    ip_15 = IntegrationPoint(
        point_id="IP-L3-0015",
        name="integration_slot_15",
        topic="topic.credit.output.54",
        position=14,
        required_rules=["RULE-L3-0079", "RULE-L3-0254"],
    )
    pipeline.integration_points.add(ip_15)
    ip_15.register_rule("RULE-L3-0079")
    ip_15.register_rule("RULE-L3-0254")

    ip_16 = IntegrationPoint(
        point_id="IP-L3-0016",
        name="integration_slot_16",
        topic="topic.reporting.output.45",
        position=15,
        required_rules=["RULE-L3-0122", "RULE-L3-0226", "RULE-L3-0086", "RULE-L3-0108"],
    )
    pipeline.integration_points.add(ip_16)
    ip_16.register_rule("RULE-L3-0122")
    ip_16.register_rule("RULE-L3-0226")
    ip_16.register_rule("RULE-L3-0086")
    ip_16.register_rule("RULE-L3-0108")

    ip_17 = IntegrationPoint(
        point_id="IP-L3-0017",
        name="integration_slot_17",
        topic="topic.payments.output.41",
        position=16,
        required_rules=["RULE-L3-0136"],
    )
    pipeline.integration_points.add(ip_17)
    ip_17.register_rule("RULE-L3-0136")

    ip_18 = IntegrationPoint(
        point_id="IP-L3-0018",
        name="integration_slot_18",
        topic="topic.derivatives.output.26",
        position=17,
        required_rules=["RULE-L3-0086"],
    )
    pipeline.integration_points.add(ip_18)
    ip_18.register_rule("RULE-L3-0086")

    ip_19 = IntegrationPoint(
        point_id="IP-L3-0019",
        name="integration_slot_19",
        topic="topic.settlement.6",
        position=18,
        required_rules=["RULE-L3-0244", "RULE-L3-0155", "RULE-L3-0120", "RULE-L3-0195"],
    )
    pipeline.integration_points.add(ip_19)
    ip_19.register_rule("RULE-L3-0244")
    ip_19.register_rule("RULE-L3-0155")
    ip_19.register_rule("RULE-L3-0120")
    ip_19.register_rule("RULE-L3-0195")

    ip_20 = IntegrationPoint(
        point_id="IP-L3-0020",
        name="integration_slot_20",
        topic="topic.reporting.3",
        position=19,
        required_rules=["RULE-L3-0135", "RULE-L3-0075", "RULE-L3-0223", "RULE-L3-0007"],
    )
    pipeline.integration_points.add(ip_20)
    ip_20.register_rule("RULE-L3-0135")
    ip_20.register_rule("RULE-L3-0075")
    ip_20.register_rule("RULE-L3-0223")
    ip_20.register_rule("RULE-L3-0007")

    ip_21 = IntegrationPoint(
        point_id="IP-L3-0021",
        name="integration_slot_21",
        topic="topic.operations.output.106",
        position=20,
        required_rules=["RULE-L3-0196", "RULE-L3-0162", "RULE-L3-0022", "RULE-L3-0050"],
    )
    pipeline.integration_points.add(ip_21)
    ip_21.register_rule("RULE-L3-0196")
    ip_21.register_rule("RULE-L3-0162")
    ip_21.register_rule("RULE-L3-0022")
    ip_21.register_rule("RULE-L3-0050")

    ip_22 = IntegrationPoint(
        point_id="IP-L3-0022",
        name="integration_slot_22",
        topic="topic.treasury.output.146",
        position=21,
        required_rules=["RULE-L3-0222", "RULE-L3-0140", "RULE-L3-0172"],
    )
    pipeline.integration_points.add(ip_22)
    ip_22.register_rule("RULE-L3-0222")
    ip_22.register_rule("RULE-L3-0140")
    ip_22.register_rule("RULE-L3-0172")

    ip_23 = IntegrationPoint(
        point_id="IP-L3-0023",
        name="integration_slot_23",
        topic="topic.operations.10",
        position=22,
        required_rules=["RULE-L3-0051", "RULE-L3-0131", "RULE-L3-0201"],
    )
    pipeline.integration_points.add(ip_23)
    ip_23.register_rule("RULE-L3-0051")
    ip_23.register_rule("RULE-L3-0131")
    ip_23.register_rule("RULE-L3-0201")

    ip_24 = IntegrationPoint(
        point_id="IP-L3-0024",
        name="integration_slot_24",
        topic="topic.settlement.5",
        position=23,
        required_rules=["RULE-L3-0100", "RULE-L3-0173"],
    )
    pipeline.integration_points.add(ip_24)
    ip_24.register_rule("RULE-L3-0100")
    ip_24.register_rule("RULE-L3-0173")

    ip_25 = IntegrationPoint(
        point_id="IP-L3-0025",
        name="integration_slot_25",
        topic="topic.fixed_income.6",
        position=24,
        required_rules=["RULE-L3-0006", "RULE-L3-0005", "RULE-L3-0035"],
    )
    pipeline.integration_points.add(ip_25)
    ip_25.register_rule("RULE-L3-0006")
    ip_25.register_rule("RULE-L3-0005")
    ip_25.register_rule("RULE-L3-0035")

    ip_26 = IntegrationPoint(
        point_id="IP-L3-0026",
        name="integration_slot_26",
        topic="topic.compliance.2",
        position=25,
        required_rules=["RULE-L3-0051", "RULE-L3-0054", "RULE-L3-0229", "RULE-L3-0180"],
    )
    pipeline.integration_points.add(ip_26)
    ip_26.register_rule("RULE-L3-0051")
    ip_26.register_rule("RULE-L3-0054")
    ip_26.register_rule("RULE-L3-0229")
    ip_26.register_rule("RULE-L3-0180")

    ip_27 = IntegrationPoint(
        point_id="IP-L3-0027",
        name="integration_slot_27",
        topic="topic.fx.output.107",
        position=26,
        required_rules=["RULE-L3-0129", "RULE-L3-0099", "RULE-L3-0018"],
    )
    pipeline.integration_points.add(ip_27)
    ip_27.register_rule("RULE-L3-0129")
    ip_27.register_rule("RULE-L3-0099")
    ip_27.register_rule("RULE-L3-0018")

    ip_28 = IntegrationPoint(
        point_id="IP-L3-0028",
        name="integration_slot_28",
        topic="topic.compliance.output.159",
        position=27,
        required_rules=["RULE-L3-0030"],
    )
    pipeline.integration_points.add(ip_28)
    ip_28.register_rule("RULE-L3-0030")

    ip_29 = IntegrationPoint(
        point_id="IP-L3-0029",
        name="integration_slot_29",
        topic="topic.fx.9",
        position=28,
        required_rules=["RULE-L3-0062"],
    )
    pipeline.integration_points.add(ip_29)
    ip_29.register_rule("RULE-L3-0062")

    ip_30 = IntegrationPoint(
        point_id="IP-L3-0030",
        name="integration_slot_30",
        topic="topic.derivatives.1",
        position=29,
        required_rules=["RULE-L3-0193", "RULE-L3-0095"],
    )
    pipeline.integration_points.add(ip_30)
    ip_30.register_rule("RULE-L3-0193")
    ip_30.register_rule("RULE-L3-0095")

    ip_31 = IntegrationPoint(
        point_id="IP-L3-0031",
        name="integration_slot_31",
        topic="topic.derivatives.output.162",
        position=30,
        required_rules=["RULE-L3-0130", "RULE-L3-0151"],
    )
    pipeline.integration_points.add(ip_31)
    ip_31.register_rule("RULE-L3-0130")
    ip_31.register_rule("RULE-L3-0151")

    ip_32 = IntegrationPoint(
        point_id="IP-L3-0032",
        name="integration_slot_32",
        topic="topic.settlement.9",
        position=31,
        required_rules=["RULE-L3-0233"],
    )
    pipeline.integration_points.add(ip_32)
    ip_32.register_rule("RULE-L3-0233")

    ip_33 = IntegrationPoint(
        point_id="IP-L3-0033",
        name="integration_slot_33",
        topic="topic.operations.2",
        position=32,
        required_rules=["RULE-L3-0166", "RULE-L3-0132", "RULE-L3-0083", "RULE-L3-0038"],
    )
    pipeline.integration_points.add(ip_33)
    ip_33.register_rule("RULE-L3-0166")
    ip_33.register_rule("RULE-L3-0132")
    ip_33.register_rule("RULE-L3-0083")
    ip_33.register_rule("RULE-L3-0038")

    ip_34 = IntegrationPoint(
        point_id="IP-L3-0034",
        name="integration_slot_34",
        topic="topic.operations.2",
        position=33,
        required_rules=["RULE-L3-0196"],
    )
    pipeline.integration_points.add(ip_34)
    ip_34.register_rule("RULE-L3-0196")

    ip_35 = IntegrationPoint(
        point_id="IP-L3-0035",
        name="integration_slot_35",
        topic="topic.reporting.16",
        position=34,
        required_rules=["RULE-L3-0031", "RULE-L3-0133", "RULE-L3-0136"],
    )
    pipeline.integration_points.add(ip_35)
    ip_35.register_rule("RULE-L3-0031")
    ip_35.register_rule("RULE-L3-0133")
    ip_35.register_rule("RULE-L3-0136")

    ip_36 = IntegrationPoint(
        point_id="IP-L3-0036",
        name="integration_slot_36",
        topic="topic.fixed_income.5",
        position=35,
        required_rules=["RULE-L3-0036", "RULE-L3-0252", "RULE-L3-0103", "RULE-L3-0202"],
    )
    pipeline.integration_points.add(ip_36)
    ip_36.register_rule("RULE-L3-0036")
    ip_36.register_rule("RULE-L3-0252")
    ip_36.register_rule("RULE-L3-0103")
    ip_36.register_rule("RULE-L3-0202")

    ip_37 = IntegrationPoint(
        point_id="IP-L3-0037",
        name="integration_slot_37",
        topic="topic.fixed_income.5",
        position=36,
        required_rules=["RULE-L3-0056", "RULE-L3-0074", "RULE-L3-0221", "RULE-L3-0112"],
    )
    pipeline.integration_points.add(ip_37)
    ip_37.register_rule("RULE-L3-0056")
    ip_37.register_rule("RULE-L3-0074")
    ip_37.register_rule("RULE-L3-0221")
    ip_37.register_rule("RULE-L3-0112")

    ip_38 = IntegrationPoint(
        point_id="IP-L3-0038",
        name="integration_slot_38",
        topic="topic.derivatives.output.123",
        position=37,
        required_rules=["RULE-L3-0133", "RULE-L3-0053", "RULE-L3-0018", "RULE-L3-0038"],
    )
    pipeline.integration_points.add(ip_38)
    ip_38.register_rule("RULE-L3-0133")
    ip_38.register_rule("RULE-L3-0053")
    ip_38.register_rule("RULE-L3-0018")
    ip_38.register_rule("RULE-L3-0038")

    ip_39 = IntegrationPoint(
        point_id="IP-L3-0039",
        name="integration_slot_39",
        topic="topic.credit.output.142",
        position=38,
        required_rules=["RULE-L3-0229", "RULE-L3-0010", "RULE-L3-0255"],
    )
    pipeline.integration_points.add(ip_39)
    ip_39.register_rule("RULE-L3-0229")
    ip_39.register_rule("RULE-L3-0010")
    ip_39.register_rule("RULE-L3-0255")

    ip_40 = IntegrationPoint(
        point_id="IP-L3-0040",
        name="integration_slot_40",
        topic="topic.equity.output.147",
        position=39,
        required_rules=["RULE-L3-0020"],
    )
    pipeline.integration_points.add(ip_40)
    ip_40.register_rule("RULE-L3-0020")

    ip_41 = IntegrationPoint(
        point_id="IP-L3-0041",
        name="integration_slot_41",
        topic="topic.reporting.3",
        position=40,
        required_rules=["RULE-L3-0078", "RULE-L3-0169", "RULE-L3-0201"],
    )
    pipeline.integration_points.add(ip_41)
    ip_41.register_rule("RULE-L3-0078")
    ip_41.register_rule("RULE-L3-0169")
    ip_41.register_rule("RULE-L3-0201")

    ip_42 = IntegrationPoint(
        point_id="IP-L3-0042",
        name="integration_slot_42",
        topic="topic.compliance.10",
        position=41,
        required_rules=["RULE-L3-0245", "RULE-L3-0224", "RULE-L3-0207", "RULE-L3-0036"],
    )
    pipeline.integration_points.add(ip_42)
    ip_42.register_rule("RULE-L3-0245")
    ip_42.register_rule("RULE-L3-0224")
    ip_42.register_rule("RULE-L3-0207")
    ip_42.register_rule("RULE-L3-0036")

    ip_43 = IntegrationPoint(
        point_id="IP-L3-0043",
        name="integration_slot_43",
        topic="topic.valuation.15",
        position=42,
        required_rules=["RULE-L3-0002", "RULE-L3-0197"],
    )
    pipeline.integration_points.add(ip_43)
    ip_43.register_rule("RULE-L3-0002")
    ip_43.register_rule("RULE-L3-0197")

    ip_44 = IntegrationPoint(
        point_id="IP-L3-0044",
        name="integration_slot_44",
        topic="topic.settlement.output.76",
        position=43,
        required_rules=["RULE-L3-0184"],
    )
    pipeline.integration_points.add(ip_44)
    ip_44.register_rule("RULE-L3-0184")

    ip_45 = IntegrationPoint(
        point_id="IP-L3-0045",
        name="integration_slot_45",
        topic="topic.payments.9",
        position=44,
        required_rules=["RULE-L3-0206", "RULE-L3-0029", "RULE-L3-0047"],
    )
    pipeline.integration_points.add(ip_45)
    ip_45.register_rule("RULE-L3-0206")
    ip_45.register_rule("RULE-L3-0029")
    ip_45.register_rule("RULE-L3-0047")

    ip_46 = IntegrationPoint(
        point_id="IP-L3-0046",
        name="integration_slot_46",
        topic="topic.reconciliation.output.134",
        position=45,
        required_rules=["RULE-L3-0042", "RULE-L3-0236", "RULE-L3-0149"],
    )
    pipeline.integration_points.add(ip_46)
    ip_46.register_rule("RULE-L3-0042")
    ip_46.register_rule("RULE-L3-0236")
    ip_46.register_rule("RULE-L3-0149")

    ip_47 = IntegrationPoint(
        point_id="IP-L3-0047",
        name="integration_slot_47",
        topic="topic.fixed_income.output.65",
        position=46,
        required_rules=["RULE-L3-0021", "RULE-L3-0197"],
    )
    pipeline.integration_points.add(ip_47)
    ip_47.register_rule("RULE-L3-0021")
    ip_47.register_rule("RULE-L3-0197")

    ip_48 = IntegrationPoint(
        point_id="IP-L3-0048",
        name="integration_slot_48",
        topic="topic.fixed_income.output.166",
        position=47,
        required_rules=["RULE-L3-0200", "RULE-L3-0055", "RULE-L3-0184"],
    )
    pipeline.integration_points.add(ip_48)
    ip_48.register_rule("RULE-L3-0200")
    ip_48.register_rule("RULE-L3-0055")
    ip_48.register_rule("RULE-L3-0184")

    ip_49 = IntegrationPoint(
        point_id="IP-L3-0049",
        name="integration_slot_49",
        topic="topic.settlement.output.80",
        position=48,
        required_rules=["RULE-L3-0225"],
    )
    pipeline.integration_points.add(ip_49)
    ip_49.register_rule("RULE-L3-0225")

    ip_50 = IntegrationPoint(
        point_id="IP-L3-0050",
        name="integration_slot_50",
        topic="topic.fixed_income.output.166",
        position=49,
        required_rules=["RULE-L3-0019", "RULE-L3-0099"],
    )
    pipeline.integration_points.add(ip_50)
    ip_50.register_rule("RULE-L3-0019")
    ip_50.register_rule("RULE-L3-0099")

    ip_51 = IntegrationPoint(
        point_id="IP-L3-0051",
        name="integration_slot_51",
        topic="topic.compliance.output.159",
        position=50,
        required_rules=["RULE-L3-0251", "RULE-L3-0200"],
    )
    pipeline.integration_points.add(ip_51)
    ip_51.register_rule("RULE-L3-0251")
    ip_51.register_rule("RULE-L3-0200")

    ip_52 = IntegrationPoint(
        point_id="IP-L3-0052",
        name="integration_slot_52",
        topic="topic.credit.output.100",
        position=51,
        required_rules=["RULE-L3-0256", "RULE-L3-0231", "RULE-L3-0009"],
    )
    pipeline.integration_points.add(ip_52)
    ip_52.register_rule("RULE-L3-0256")
    ip_52.register_rule("RULE-L3-0231")
    ip_52.register_rule("RULE-L3-0009")

    ip_53 = IntegrationPoint(
        point_id="IP-L3-0053",
        name="integration_slot_53",
        topic="topic.compliance.output.75",
        position=52,
        required_rules=["RULE-L3-0029", "RULE-L3-0173", "RULE-L3-0022"],
    )
    pipeline.integration_points.add(ip_53)
    ip_53.register_rule("RULE-L3-0029")
    ip_53.register_rule("RULE-L3-0173")
    ip_53.register_rule("RULE-L3-0022")

    ip_54 = IntegrationPoint(
        point_id="IP-L3-0054",
        name="integration_slot_54",
        topic="topic.reporting.output.153",
        position=53,
        required_rules=["RULE-L3-0109"],
    )
    pipeline.integration_points.add(ip_54)
    ip_54.register_rule("RULE-L3-0109")

    ip_55 = IntegrationPoint(
        point_id="IP-L3-0055",
        name="integration_slot_55",
        topic="topic.treasury.output.11",
        position=54,
        required_rules=["RULE-L3-0077", "RULE-L3-0120", "RULE-L3-0037", "RULE-L3-0019"],
    )
    pipeline.integration_points.add(ip_55)
    ip_55.register_rule("RULE-L3-0077")
    ip_55.register_rule("RULE-L3-0120")
    ip_55.register_rule("RULE-L3-0037")
    ip_55.register_rule("RULE-L3-0019")

    ip_56 = IntegrationPoint(
        point_id="IP-L3-0056",
        name="integration_slot_56",
        topic="topic.equity.6",
        position=55,
        required_rules=["RULE-L3-0010", "RULE-L3-0242", "RULE-L3-0024", "RULE-L3-0125"],
    )
    pipeline.integration_points.add(ip_56)
    ip_56.register_rule("RULE-L3-0010")
    ip_56.register_rule("RULE-L3-0242")
    ip_56.register_rule("RULE-L3-0024")
    ip_56.register_rule("RULE-L3-0125")

    ip_57 = IntegrationPoint(
        point_id="IP-L3-0057",
        name="integration_slot_57",
        topic="topic.equity.13",
        position=56,
        required_rules=["RULE-L3-0089"],
    )
    pipeline.integration_points.add(ip_57)
    ip_57.register_rule("RULE-L3-0089")

    ip_58 = IntegrationPoint(
        point_id="IP-L3-0058",
        name="integration_slot_58",
        topic="topic.credit.2",
        position=57,
        required_rules=["RULE-L3-0050", "RULE-L3-0234", "RULE-L3-0088"],
    )
    pipeline.integration_points.add(ip_58)
    ip_58.register_rule("RULE-L3-0050")
    ip_58.register_rule("RULE-L3-0234")
    ip_58.register_rule("RULE-L3-0088")

    ip_59 = IntegrationPoint(
        point_id="IP-L3-0059",
        name="integration_slot_59",
        topic="topic.credit.output.100",
        position=58,
        required_rules=["RULE-L3-0059"],
    )
    pipeline.integration_points.add(ip_59)
    ip_59.register_rule("RULE-L3-0059")

    ip_60 = IntegrationPoint(
        point_id="IP-L3-0060",
        name="integration_slot_60",
        topic="topic.trading.14",
        position=59,
        required_rules=["RULE-L3-0033", "RULE-L3-0104"],
    )
    pipeline.integration_points.add(ip_60)
    ip_60.register_rule("RULE-L3-0033")
    ip_60.register_rule("RULE-L3-0104")

    ip_61 = IntegrationPoint(
        point_id="IP-L3-0061",
        name="integration_slot_61",
        topic="topic.risk.3",
        position=60,
        required_rules=["RULE-L3-0206", "RULE-L3-0167", "RULE-L3-0062"],
    )
    pipeline.integration_points.add(ip_61)
    ip_61.register_rule("RULE-L3-0206")
    ip_61.register_rule("RULE-L3-0167")
    ip_61.register_rule("RULE-L3-0062")

    ip_62 = IntegrationPoint(
        point_id="IP-L3-0062",
        name="integration_slot_62",
        topic="topic.valuation.5",
        position=61,
        required_rules=["RULE-L3-0165", "RULE-L3-0110"],
    )
    pipeline.integration_points.add(ip_62)
    ip_62.register_rule("RULE-L3-0165")
    ip_62.register_rule("RULE-L3-0110")

    ip_63 = IntegrationPoint(
        point_id="IP-L3-0063",
        name="integration_slot_63",
        topic="topic.credit.15",
        position=62,
        required_rules=["RULE-L3-0172", "RULE-L3-0033"],
    )
    pipeline.integration_points.add(ip_63)
    ip_63.register_rule("RULE-L3-0172")
    ip_63.register_rule("RULE-L3-0033")

    ip_64 = IntegrationPoint(
        point_id="IP-L3-0064",
        name="integration_slot_64",
        topic="topic.derivatives.output.48",
        position=63,
        required_rules=["RULE-L3-0073", "RULE-L3-0213", "RULE-L3-0087"],
    )
    pipeline.integration_points.add(ip_64)
    ip_64.register_rule("RULE-L3-0073")
    ip_64.register_rule("RULE-L3-0213")
    ip_64.register_rule("RULE-L3-0087")

    # === Side-Effect Chains (CHAIN-L3-0001 to CHAIN-L3-0032) ===

    chain_1 = SideEffectChain(
        chain_id="CHAIN-L3-0001",
        trigger_topic="topic.operations.output.84",
        services=["audit_service", "notification_service", "metrics_service"],
        expected_log_entries=["audit_logged", "notification_sent", "metrics_updated"],
    )
    pipeline.wiring.add_chain(chain_1)

    chain_2 = SideEffectChain(
        chain_id="CHAIN-L3-0002",
        trigger_topic="topic.trading.output.40",
        services=["audit_service"],
        expected_log_entries=["audit_logged"],
    )
    pipeline.wiring.add_chain(chain_2)

    chain_3 = SideEffectChain(
        chain_id="CHAIN-L3-0003",
        trigger_topic="topic.derivatives.output.123",
        services=["metrics_service", "notification_service", "audit_service"],
        expected_log_entries=["metrics_updated", "notification_sent", "audit_logged"],
    )
    pipeline.wiring.add_chain(chain_3)

    chain_4 = SideEffectChain(
        chain_id="CHAIN-L3-0004",
        trigger_topic="topic.compliance.output.161",
        services=["audit_service", "metrics_service"],
        expected_log_entries=["audit_logged", "metrics_updated"],
    )
    pipeline.wiring.add_chain(chain_4)

    chain_5 = SideEffectChain(
        chain_id="CHAIN-L3-0005",
        trigger_topic="topic.compliance.output.119",
        services=["audit_service"],
        expected_log_entries=["audit_logged"],
    )
    pipeline.wiring.add_chain(chain_5)

    chain_6 = SideEffectChain(
        chain_id="CHAIN-L3-0006",
        trigger_topic="topic.valuation.output.89",
        services=["notification_service", "metrics_service", "audit_service"],
        expected_log_entries=["notification_sent", "metrics_updated", "audit_logged"],
    )
    pipeline.wiring.add_chain(chain_6)

    chain_7 = SideEffectChain(
        chain_id="CHAIN-L3-0007",
        trigger_topic="topic.derivatives.output.48",
        services=["audit_service"],
        expected_log_entries=["audit_logged"],
    )
    pipeline.wiring.add_chain(chain_7)

    chain_8 = SideEffectChain(
        chain_id="CHAIN-L3-0008",
        trigger_topic="topic.valuation.output.135",
        services=["metrics_service", "notification_service"],
        expected_log_entries=["metrics_updated", "notification_sent"],
    )
    pipeline.wiring.add_chain(chain_8)

    chain_9 = SideEffectChain(
        chain_id="CHAIN-L3-0009",
        trigger_topic="topic.payments.output.81",
        services=["audit_service"],
        expected_log_entries=["audit_logged"],
    )
    pipeline.wiring.add_chain(chain_9)

    chain_10 = SideEffectChain(
        chain_id="CHAIN-L3-0010",
        trigger_topic="topic.treasury.output.146",
        services=["audit_service", "metrics_service", "notification_service"],
        expected_log_entries=["audit_logged", "metrics_updated", "notification_sent"],
    )
    pipeline.wiring.add_chain(chain_10)

    chain_11 = SideEffectChain(
        chain_id="CHAIN-L3-0011",
        trigger_topic="topic.treasury.output.146",
        services=["metrics_service"],
        expected_log_entries=["metrics_updated"],
    )
    pipeline.wiring.add_chain(chain_11)

    chain_12 = SideEffectChain(
        chain_id="CHAIN-L3-0012",
        trigger_topic="topic.ledger.output.60",
        services=["notification_service", "audit_service"],
        expected_log_entries=["notification_sent", "audit_logged"],
    )
    pipeline.wiring.add_chain(chain_12)

    chain_13 = SideEffectChain(
        chain_id="CHAIN-L3-0013",
        trigger_topic="topic.settlement.output.79",
        services=["audit_service"],
        expected_log_entries=["audit_logged"],
    )
    pipeline.wiring.add_chain(chain_13)

    chain_14 = SideEffectChain(
        chain_id="CHAIN-L3-0014",
        trigger_topic="topic.derivatives.output.26",
        services=["audit_service", "notification_service", "metrics_service"],
        expected_log_entries=["audit_logged", "notification_sent", "metrics_updated"],
    )
    pipeline.wiring.add_chain(chain_14)

    chain_15 = SideEffectChain(
        chain_id="CHAIN-L3-0015",
        trigger_topic="topic.reporting.output.153",
        services=["metrics_service", "audit_service", "notification_service"],
        expected_log_entries=["metrics_updated", "audit_logged", "notification_sent"],
    )
    pipeline.wiring.add_chain(chain_15)

    chain_16 = SideEffectChain(
        chain_id="CHAIN-L3-0016",
        trigger_topic="topic.credit.output.104",
        services=["audit_service"],
        expected_log_entries=["audit_logged"],
    )
    pipeline.wiring.add_chain(chain_16)

    chain_17 = SideEffectChain(
        chain_id="CHAIN-L3-0017",
        trigger_topic="topic.equity.output.125",
        services=["notification_service", "metrics_service", "audit_service"],
        expected_log_entries=["notification_sent", "metrics_updated", "audit_logged"],
    )
    pipeline.wiring.add_chain(chain_17)

    chain_18 = SideEffectChain(
        chain_id="CHAIN-L3-0018",
        trigger_topic="topic.equity.output.15",
        services=["audit_service", "metrics_service", "notification_service"],
        expected_log_entries=["audit_logged", "metrics_updated", "notification_sent"],
    )
    pipeline.wiring.add_chain(chain_18)

    chain_19 = SideEffectChain(
        chain_id="CHAIN-L3-0019",
        trigger_topic="topic.ledger.output.138",
        services=["notification_service"],
        expected_log_entries=["notification_sent"],
    )
    pipeline.wiring.add_chain(chain_19)

    chain_20 = SideEffectChain(
        chain_id="CHAIN-L3-0020",
        trigger_topic="topic.fx.output.28",
        services=["metrics_service", "notification_service"],
        expected_log_entries=["metrics_updated", "notification_sent"],
    )
    pipeline.wiring.add_chain(chain_20)

    chain_21 = SideEffectChain(
        chain_id="CHAIN-L3-0021",
        trigger_topic="topic.credit.output.10",
        services=["metrics_service"],
        expected_log_entries=["metrics_updated"],
    )
    pipeline.wiring.add_chain(chain_21)

    chain_22 = SideEffectChain(
        chain_id="CHAIN-L3-0022",
        trigger_topic="topic.credit.output.104",
        services=["audit_service", "metrics_service", "notification_service"],
        expected_log_entries=["audit_logged", "metrics_updated", "notification_sent"],
    )
    pipeline.wiring.add_chain(chain_22)

    chain_23 = SideEffectChain(
        chain_id="CHAIN-L3-0023",
        trigger_topic="topic.reporting.output.95",
        services=["audit_service", "metrics_service", "notification_service"],
        expected_log_entries=["audit_logged", "metrics_updated", "notification_sent"],
    )
    pipeline.wiring.add_chain(chain_23)

    chain_24 = SideEffectChain(
        chain_id="CHAIN-L3-0024",
        trigger_topic="topic.reporting.output.117",
        services=["metrics_service", "notification_service", "audit_service"],
        expected_log_entries=["metrics_updated", "notification_sent", "audit_logged"],
    )
    pipeline.wiring.add_chain(chain_24)

    chain_25 = SideEffectChain(
        chain_id="CHAIN-L3-0025",
        trigger_topic="topic.fixed_income.output.120",
        services=["metrics_service", "notification_service", "audit_service"],
        expected_log_entries=["metrics_updated", "notification_sent", "audit_logged"],
    )
    pipeline.wiring.add_chain(chain_25)

    chain_26 = SideEffectChain(
        chain_id="CHAIN-L3-0026",
        trigger_topic="topic.derivatives.output.19",
        services=["audit_service", "metrics_service"],
        expected_log_entries=["audit_logged", "metrics_updated"],
    )
    pipeline.wiring.add_chain(chain_26)

    chain_27 = SideEffectChain(
        chain_id="CHAIN-L3-0027",
        trigger_topic="topic.fixed_income.output.70",
        services=["notification_service", "audit_service", "metrics_service"],
        expected_log_entries=["notification_sent", "audit_logged", "metrics_updated"],
    )
    pipeline.wiring.add_chain(chain_27)

    chain_28 = SideEffectChain(
        chain_id="CHAIN-L3-0028",
        trigger_topic="topic.fixed_income.output.20",
        services=["notification_service"],
        expected_log_entries=["notification_sent"],
    )
    pipeline.wiring.add_chain(chain_28)

    chain_29 = SideEffectChain(
        chain_id="CHAIN-L3-0029",
        trigger_topic="topic.trading.output.78",
        services=["audit_service", "notification_service"],
        expected_log_entries=["audit_logged", "notification_sent"],
    )
    pipeline.wiring.add_chain(chain_29)

    chain_30 = SideEffectChain(
        chain_id="CHAIN-L3-0030",
        trigger_topic="topic.equity.output.121",
        services=["metrics_service"],
        expected_log_entries=["metrics_updated"],
    )
    pipeline.wiring.add_chain(chain_30)

    chain_31 = SideEffectChain(
        chain_id="CHAIN-L3-0031",
        trigger_topic="topic.reporting.output.133",
        services=["notification_service"],
        expected_log_entries=["notification_sent"],
    )
    pipeline.wiring.add_chain(chain_31)

    chain_32 = SideEffectChain(
        chain_id="CHAIN-L3-0032",
        trigger_topic="topic.operations.output.94",
        services=["notification_service"],
        expected_log_entries=["notification_sent"],
    )
    pipeline.wiring.add_chain(chain_32)
