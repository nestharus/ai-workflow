LIBRARY: strategy.catalog
VERSION: 1.0
CONSTRAINTS: [CON-0015, CON-0003]

DATA_SHAPES:
  - id: DS-STRATCAT-0001
    name: StrategyCatalogEntry
    fields:
      - {name: strategy_id, type: string, constraints: ["STRAT-{seq:04d}"]}
      - {name: phase, type: DS-WF-0001.phase_id}
      - {name: risk_categories, type: list<string>}
      - {name: trigger_signals, type: list<DS-STRAT-0005.signal_name>}
      - {name: primary_algorithms, type: list<string>}
      - {name: outputs, type: list<string>}
      - {name: mode, type: enum, values: ["STABLE","EXPERIMENTAL"]}

STRATEGIES:
  - {strategy_id: "STRAT-0001", phase: "STRUCTURE", risk_categories: ["span_coverage"], trigger_signals: ["COVERAGE_GAP_COUNT"], primary_algorithms: ["ALG-STRUCT-0002"], outputs: ["sections_repaired","gaps"], mode: "STABLE"}
  - {strategy_id: "STRAT-0002", phase: "DECOMPOSE", risk_categories: ["high_prose"], trigger_signals: ["PROSE_RATIO"], primary_algorithms: ["ALG-STRUCT-0004"], outputs: ["units","lineage","gaps"], mode: "STABLE"}
  - {strategy_id: "STRAT-0003", phase: "DECOMPOSE", risk_categories: ["stagnation"], trigger_signals: ["REMAINDER_RATIO"], primary_algorithms: ["ALG-AUDIT-0003","ALG-AGENT-0001"], outputs: ["decomposition_retry","gaps"], mode: "EXPERIMENTAL"}
  - {strategy_id: "STRAT-0004", phase: "CLEAN", risk_categories: ["contract_invalid"], trigger_signals: ["LOW_CONFIDENCE_RATE"], primary_algorithms: ["ALG-AGENT-0002","ALG-COMP-0001"], outputs: ["repaired_outputs","gaps"], mode: "STABLE"}
  - {strategy_id: "STRAT-0005", phase: "DISCOVER", risk_categories: ["low_convergence"], trigger_signals: ["LOW_CONFIDENCE_RATE"], primary_algorithms: ["ALG-DISC-0004"], outputs: ["shape_refined","gaps"], mode: "STABLE"}
  - {strategy_id: "STRAT-0006", phase: "DISCOVER", risk_categories: ["overlap"], trigger_signals: ["DRIFT_RATE"], primary_algorithms: ["ALG-DISC-0005"], outputs: ["overlap_actions","gaps"], mode: "STABLE"}
  - {strategy_id: "STRAT-0007", phase: "REFINE", risk_categories: ["gap_backlog"], trigger_signals: ["COVERAGE_GAP_COUNT"], primary_algorithms: ["ALG-SPEC-0004","ALG-GAP-0003"], outputs: ["updated_spec","tasks"], mode: "STABLE"}
  - {strategy_id: "STRAT-0008", phase: "PROJECT", risk_categories: ["projection_drift"], trigger_signals: ["DRIFT_RATE"], primary_algorithms: ["ALG-PROJ-0002","ALG-PROJ-0003"], outputs: ["drift_report","gaps"], mode: "STABLE"}
  - {strategy_id: "STRAT-0009", phase: "REFINE", risk_categories: ["proof_chain"], trigger_signals: ["UNRESOLVED_REF_COUNT"], primary_algorithms: ["ALG-SPEC-0005"], outputs: ["quarantine","gaps"], mode: "STABLE"}
  - {strategy_id: "STRAT-0010", phase: "PLAN_TASKS", risk_categories: ["blocked_work"], trigger_signals: ["UNRESOLVED_REF_COUNT"], primary_algorithms: ["ALG-TASK-0001","ALG-TASK-0002","ALG-TASK-0003"], outputs: ["task_plan"], mode: "STABLE"}
