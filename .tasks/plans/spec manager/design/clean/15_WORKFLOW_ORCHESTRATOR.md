LIBRARY: workflow.orchestrator
VERSION: 1.0
CONSTRAINTS: [CON-0009, CON-0016, CON-0011]

DATA_SHAPES:
  - id: DS-WF-0001
    name: WorkflowPhase
    fields:
      - {name: phase_id, type: enum, values: ["INTAKE","STRUCTURE","DECOMPOSE","CLEAN","DISCOVER","REFINE","REVIEW","PROJECT","PLAN_TASKS","IMPLEMENT_LOOP","FINALIZE"]}
      - {name: order_index, type: int}
      - {name: gate_policy_id, type: DS-COMP-0005.policy_id}
  - id: DS-WF-0002
    name: PhaseStatus
    fields:
      - {name: phase_id, type: DS-WF-0001.phase_id}
      - {name: status, type: enum, values: ["NOT_STARTED","RUNNING","PASSED","WARN_PASSED","BLOCKED","FAILED"]}
      - {name: compliance_score, type: DS-COMP-0003|null}
      - {name: produced_artifacts, type: list<DS-WF-0007>}
      - {name: produced_gap_ids, type: list<string>}
  - id: DS-WF-0003
    name: WorkflowConfig
    fields:
      - {name: run_id, type: string}
      - {name: phase_sequence, type: list<DS-WF-0001.phase_id>}
      - {name: max_iterations_by_phase, type: map<string,int>}
      - {name: context_budgets, type: map<string,int>}
      - {name: strategy_allowlist, type: list<string>}
      - {name: strategy_blocklist, type: list<string>}
      - {name: thresholds, type: map<string,float>}
  - id: DS-WF-0004
    name: WorkflowSnapshot
    fields:
      - {name: snapshot_id, type: string}
      - {name: run_id, type: string}
      - {name: phase_id, type: DS-WF-0001.phase_id}
      - {name: state_refs, type: list<DS-WF-0007>}
      - {name: created_at, type: string}
  - id: DS-WF-0005
    name: ResumeToken
    fields:
      - {name: snapshot_id, type: string}
      - {name: resume_phase_id, type: DS-WF-0001.phase_id}
  - id: DS-WF-0006
    name: PhaseResult
    fields:
      - {name: phase_status, type: DS-WF-0002}
      - {name: next_phase_id, type: DS-WF-0001.phase_id|null}
      - {name: decision, type: DS-COMP-0004}
  - id: DS-WF-0007
    name: ArtifactPointer
    fields:
      - {name: artifact_id, type: string}
      - {name: kind, type: string}
      - {name: path, type: string}
      - {name: sha256, type: string}
      - {name: authoritative_layer, type: enum, values: ["L0","L1","L2"]}

ALGORITHMS:
  - id: ALG-WF-0001
    name: OrchestrateRun
    inputs:
      - {name: config, type: DS-WF-0003}
    outputs:
      - {name: final_snapshot, type: DS-WF-0004}
      - {name: phase_statuses, type: list<DS-WF-0002>}
    invariants: [CON-0009, CON-0016]
    pseudocode:
      ```pseudo
      function OrchestrateRun(run_config, phases, policy):
        state = ResumeFromSnapshot(run_config.workspace, policy) if run_config.resume else init_state(run_config)
      
        for phase in phases:
          result = ExecutePhaseWithGate(phase, state, policy)
          state = result.state
      
          if not result.ok:
            SnapshotState(state, phase.phase_id, policy)
            return { ok: false, state: state }
      
          SnapshotState(state, phase.phase_id, policy)
      
        return { ok: true, state: state }
      ```
  - id: ALG-WF-0002
    name: ExecutePhaseWithGate
    inputs:
      - {name: phase_id, type: DS-WF-0001.phase_id}
      - {name: context, type: DS-STRAT-0004}
      - {name: gate_policy, type: DS-COMP-0005}
    outputs:
      - {name: result, type: DS-WF-0006}
    invariants: [CON-0011]
    pseudocode:
      ```pseudo
      function ExecutePhaseWithGate(phase, state, policy):
        artifacts = phase.run(state, policy)
      
        findings = ValidateArtifactContract(artifacts, phase.schema_id, policy.allowlists)
        metrics = ComputeComplianceMetrics(phase.phase_id, artifacts, state.coverage_report, state.id_registry)
        score = ComputeComplianceScore(metrics, findings, policy.compliance_policy)
      
        gate = GatePhaseTransition(phase.phase_id, score, state.coverage_report, policy.compliance_policy)
        if not gate.pass:
          return { ok: false, state: state.with_artifacts(artifacts).with_findings(findings).with_score(score) }
      
        return { ok: true, state: state.with_artifacts(artifacts).with_findings(findings).with_score(score) }
      ```
  - id: ALG-WF-0003
    name: SnapshotState
    inputs:
      - {name: run_id, type: string}
      - {name: phase_id, type: DS-WF-0001.phase_id}
      - {name: artifact_pointers, type: list<DS-WF-0007>}
    outputs:
      - {name: snapshot, type: DS-WF-0004}
    invariants: [CON-0016]
    pseudocode:
      ```pseudo
      function SnapshotState(state, phase_id, policy):
        snapshot_id = format("state_%04d_%s", state.version, phase_id)
        persist.write_json(policy.workspace + "/" + snapshot_id + ".json", state)
        state.version = state.version + 1
        return snapshot_id
      ```
  - id: ALG-WF-0004
    name: ResumeFromSnapshot
    inputs:
      - {name: token, type: DS-WF-0005}
    outputs:
      - {name: restored_context, type: DS-STRAT-0004}
    invariants: [CON-0016]
    pseudocode:
      ```pseudo
      function ResumeFromSnapshot(workspace, policy):
        latest = persist.find_latest_snapshot(workspace)
        if latest is null:
          return init_state(policy.run_config)
        return persist.read_json(latest)
      ```
