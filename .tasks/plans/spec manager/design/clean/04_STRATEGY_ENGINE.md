LIBRARY: strategy.engine
VERSION: 1.0
CONSTRAINTS: [CON-0015, CON-0011, CON-0016]

DATA_SHAPES:
  - id: DS-STRAT-0001
    name: StrategyDefinition
    fields:
      - {name: strategy_id, type: string}
      - {name: name, type: string}
      - {name: applies_to_phase, type: enum, values: ["INTAKE","STRUCTURE","CLEAN","DISCOVERY","REFINE","VERIFY","FINALIZE"]}
      - {name: risk_categories, type: list<string>}
      - {name: trigger, type: DS-STRAT-0002}
      - {name: required_inputs, type: list<string>}
      - {name: outputs, type: list<string>}
      - {name: mode, type: enum, values: ["STABLE","EXPERIMENTAL"]}
      - {name: version, type: string}
  - id: DS-STRAT-0002
    name: StrategyTrigger
    fields:
      - {name: predicate, type: enum, values: ["GT","GTE","LT","LTE","EQ","NEQ","CUSTOM"]}
      - {name: signal, type: DS-STRAT-0005.signal_name}
      - {name: threshold, type: float}
      - {name: window, type: enum, values: ["RUN","FILE","LIBRARY","ELEMENT"]}
  - id: DS-STRAT-0003
    name: StrategyExecutionResult
    fields:
      - {name: strategy_id, type: string}
      - {name: actions_taken, type: list<string>}
      - {name: produced_units, type: list<DS-PROV-0001>}
      - {name: produced_gaps, type: list<DS-GAP-0001>}
      - {name: metrics_delta, type: map<string,float>}
      - {name: status, type: enum, values: ["OK","NOOP","FAILED","QUARANTINED"]}
  - id: DS-STRAT-0004
    name: ProcessingContext
    fields:
      - {name: run_id, type: string}
      - {name: phase, type: DS-STRAT-0001.applies_to_phase}
      - {name: evidence_graph, type: DS-EVID-0004}
      - {name: units, type: list<DS-PROV-0001>}
      - {name: libraries, type: list<DS-DISC-0001>}
      - {name: gaps, type: list<DS-GAP-0001>}
      - {name: risk_signals, type: list<DS-STRAT-0005>}
  - id: DS-STRAT-0005
    name: RiskSignal
    fields:
      - {name: signal_name, type: enum, values: ["PROSE_RATIO","REMAINDER_RATIO","LOW_CONFIDENCE_RATE","UNRESOLVED_REF_COUNT","DRIFT_RATE","COVERAGE_GAP_COUNT"]}
      - {name: value, type: float}
      - {name: scope, type: enum, values: ["RUN","FILE","LIBRARY","ELEMENT"]}
      - {name: scope_id, type: string|null}
  - id: DS-STRAT-0006
    name: StrategyTestFixture
    fields:
      - {name: fixture_id, type: string}
      - {name: input_artifacts, type: list<string>}
      - {name: expected_invariants, type: list<string>}
      - {name: expected_gaps, type: list<string>}
  - id: DS-STRAT-0007
    name: StrategyPromotionRecord
    fields:
      - {name: strategy_id, type: string}
      - {name: from_mode, type: string}
      - {name: to_mode, type: string}
      - {name: fixture_results, type: map<string,string>}
      - {name: approved_by, type: string}
      - {name: approved_at, type: string}

ALGORITHMS:
  - id: ALG-STRAT-0001
    name: ComputeRiskSignals
    inputs:
      - {name: units, type: list<DS-PROV-0001>}
      - {name: gaps, type: list<DS-GAP-0001>}
      - {name: projections, type: list<string>}
    outputs:
      - {name: signals, type: list<DS-STRAT-0005>}
    invariants: [INV-ACC-0101]
    pseudocode:
      ```pseudo
      function ComputeRiskSignals(context):
        # Risk signals must be derived from system state, not raw-spec keyword scans.
        signals = {}
        signals.coverage_remainder_ratio = context.coverage_report.remainder_ratio
        signals.low_confidence_mappings = count(context.membership_evidence where confidence < context.policy.confidence_floor)
        signals.unresolved_links = count(context.unresolved_links)
        signals.spec_drift_score = context.drift_report.similarity if context.drift_report else 1.0
        signals.output_schema_failures = context.schema_failures_count
        return signals
      ```
  - id: ALG-STRAT-0002
    name: SelectApplicableStrategies
    inputs:
      - {name: definitions, type: list<DS-STRAT-0001>}
      - {name: context, type: DS-STRAT-0004}
    outputs:
      - {name: selected, type: list<DS-STRAT-0001>}
    invariants: [CON-0015]
    pseudocode:
      ```pseudo
      function SelectApplicableStrategies(phase_id, risk_signals, strategy_registry, policy):
        selected = []
        for s in strategy_registry.strategies_for_phase(phase_id):
          if risk_exceeds_threshold(risk_signals, s.gate, policy) and s.applies_to(risk_signals, policy):
            selected.append(s)
        return selected
      ```
  - id: ALG-STRAT-0003
    name: ExecuteStrategyWithQuarantine
    inputs:
      - {name: strategy, type: DS-STRAT-0001}
      - {name: context, type: DS-STRAT-0004}
    outputs:
      - {name: result, type: DS-STRAT-0003}
    invariants: [CON-0011]
    pseudocode:
      ```pseudo
      function ExecuteStrategyWithQuarantine(strategy, context, policy):
        result = strategy.execute(context)
      
        # Verify invariants after each strategy
        if policy.enforce_coverage and not VerifyCoverageOrEmitGap(context.coverage_report, policy).ok:
          context.quarantine.add(result.artifacts)
          return { ok: false, quarantined: true }
      
        if result.risk_delta > policy.max_risk_increase:
          context.quarantine.add(result.artifacts)
          gaps.emit("GAP-STRATEGY-RISK-INCREASE", evidence={ "strategy_id": strategy.id })
          return { ok: false, quarantined: true }
      
        return { ok: true, quarantined: false }
      ```
  - id: ALG-STRAT-0004
    name: StrategyEvolutionLoop
    inputs:
      - {name: captured_gaps, type: list<DS-GAP-0001>}
      - {name: fixture_store, type: list<DS-STRAT-0006>}
    outputs:
      - {name: proposed_strategies, type: list<DS-STRAT-0001>}
    invariants: [CON-0015]
    pseudocode:
      ```pseudo
      function StrategyEvolutionLoop(gap_stream, strategy_registry, policy):
        # Convert repeated gap patterns into new strategies (experimental -> stable)
        for g in gap_stream:
          if not policy.evolution_enabled:
            continue
      
          if gap_pattern_repeats(g, policy.repeat_threshold):
            proposal = agent.run(policy.strategy_proposer_agent_id, { "gap": g, "policy": policy })
            if schema.validate(policy.strategy_schema_id, proposal).ok:
              strategy_registry.register_experimental(proposal)
              if policy.auto_promote and proposal.pass_rate >= policy.promote_threshold:
                strategy_registry.promote_to_stable(proposal.strategy_id)
      ```
