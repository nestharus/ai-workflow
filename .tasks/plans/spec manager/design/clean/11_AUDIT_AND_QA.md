LIBRARY: audit.qa
VERSION: 1.0
CONSTRAINTS: [CON-0002, CON-0011, CON-0012]

DATA_SHAPES:
  - id: DS-AUDIT-0001
    name: AuditCase
    fields:
      - {name: case_id, type: string}
      - {name: scope, type: enum, values: ["RUN","FILE","LIBRARY","ELEMENT"]}
      - {name: target_id, type: string|null}
      - {name: inputs, type: list<string>}
      - {name: expected_invariants, type: list<string>}
      - {name: judge_model, type: string|null}
  - id: DS-AUDIT-0002
    name: AuditResult
    fields:
      - {name: case_id, type: string}
      - {name: passed, type: bool}
      - {name: score, type: float}
      - {name: findings, type: list<DS-GAP-0002>}
      - {name: created_at, type: string}
  - id: DS-AUDIT-0003
    name: EscalationPolicy
    fields:
      - {name: policy_id, type: string}
      - {name: trigger_gap_types, type: list<DS-GAP-0001.gap_type>}
      - {name: trigger_severity, type: DS-GAP-0001.severity}
      - {name: escalation_models, type: list<string>}
      - {name: max_rounds, type: int}

ALGORITHMS:
  - id: ALG-AUDIT-0001
    name: AuditCoverageInvariants
    inputs:
      - {name: coverage_reports, type: list<DS-PROV-0005>}
    outputs:
      - {name: audit_result, type: DS-AUDIT-0002}
    invariants: [INV-ACC-0101]
    pseudocode:
      ```pseudo
      function AuditCoverageInvariants(atoms, evidence_ranges, derived_elements, exclusions, policy):
        # 1) All atoms are either covered by evidence OR excluded
        coverage = compute_atom_coverage(atoms, evidence_ranges, exclusions)
        if coverage.remainder_atoms is not empty:
          gaps.emit("GAP-AUDIT-ATOM-UNCOVERED", evidence={ "remainder_atoms": coverage.remainder_atoms })
      
        # 2) All evidence ranges are referenced by >=1 derived element annotation
        evidence_used = compute_evidence_usage(evidence_ranges, derived_elements)
        if evidence_used.unreferenced_evidence_ids is not empty:
          gaps.emit("GAP-AUDIT-EVIDENCE-UNREFERENCED", evidence={ "evidence_ids": evidence_used.unreferenced_evidence_ids })
      
        return { ok: (coverage.remainder_atoms is empty and evidence_used.unreferenced_evidence_ids is empty) }
      ```
  - id: ALG-AUDIT-0002
    name: AuditDerivedElementsGrounding
    inputs:
      - {name: spec_index, type: DS-SPEC-0003}
      - {name: evidence_graph, type: DS-EVID-0004}
    outputs:
      - {name: audit_result, type: DS-AUDIT-0002}
    invariants: [INV-ACC-0201, INV-ACC-0202]
    pseudocode:
      ```pseudo
      function AuditDerivedElementsGrounding(derived_elements, evidence_index, policy):
        for e in derived_elements:
          if e.evidence_ids is empty:
            gaps.emit("GAP-AUDIT-UNGROUNDED-ELEMENT", evidence={ "elem_id": e.elem_id })
      
          for evid in e.evidence_ids:
            if evid not in evidence_index:
              gaps.emit("GAP-AUDIT-BAD-EVIDENCE-REF", evidence={ "elem_id": e.elem_id, "evidence_id": evid })
      
        return { ok: true }
      ```
  - id: ALG-AUDIT-0003
    name: AuditSemanticConsistencyWithJudges
    inputs:
      - {name: spec_index, type: DS-SPEC-0003}
      - {name: context_bundle, type: DS-EVID-0007}
      - {name: judge_models, type: list<string>}
    outputs:
      - {name: audit_result, type: DS-AUDIT-0002}
    invariants: [CON-0012]
    pseudocode:
      ```pseudo
      function AuditSemanticConsistencyWithJudges(spec_snapshot, evidence_bundle, policy):
        # Use multiple judges to reduce single-model blind spots.
        judges = policy.semantic_judge_agent_ids
        votes = []
      
        for j in judges:
          v = agent.run(j, { "spec": spec_snapshot, "evidence": evidence_bundle })
          votes.append(v)
      
        if any(v.has_contradictions for v in votes):
          gaps.emit("GAP-AUDIT-CONTRADICTION", evidence={ "votes": votes })
      
        if any(v.has_ambiguities for v in votes):
          gaps.emit("GAP-AUDIT-AMBIGUITY", evidence={ "votes": votes })
      
        return { votes: votes }
      ```
  - id: ALG-AUDIT-0004
    name: EscalateOnHighRisk
    inputs:
      - {name: gaps, type: list<DS-GAP-0001>}
      - {name: policy, type: DS-AUDIT-0003}
    outputs:
      - {name: selected_judge_models, type: list<string>}
    invariants: [CON-0011]
    pseudocode:
      ```pseudo
      function EscalateOnHighRisk(risk_signals, audit_findings, policy):
        if risk_signals.coverage_remainder_ratio > 0.0:
          return { action: "BLOCK" }
      
        if audit_findings.blocker_count > 0:
          return { action: "BLOCK" }
      
        if audit_findings.warning_count > policy.warning_escalation_floor:
          return { action: "REVIEW" }
      
        return { action: "CONTINUE" }
      ```
