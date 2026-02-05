LIBRARY: gaps.detection
VERSION: 1.0
CONSTRAINTS: [CON-0012, CON-0003, CON-0004]

DATA_SHAPES:
  - id: DS-GAP-0001
    name: GapElement
    fields:
      - {name: gap_id, type: string, constraints: ["GAP-{seq:04d}"]}
      - {name: gap_type, type: enum, values: ["COVERAGE","UNRESOLVED_REFERENCE","AMBIGUITY","UNDERSPECIFIED","CONTRADICTION","DRIFT","OVERLAP","NON_AUTHORITATIVE","FORMAT"]}
      - {name: severity, type: enum, values: ["INFO","WARN","ERROR"]}
      - {name: message, type: string}
      - {name: affects_ids, type: list<string>}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: detector_id, type: string}
      - {name: proposed_actions, type: list<string>}
      - {name: created_at, type: string}
  - id: DS-GAP-0002
    name: DetectorFinding
    fields:
      - {name: finding_id, type: string}
      - {name: detector_id, type: string}
      - {name: severity, type: DS-GAP-0001.severity}
      - {name: element_id, type: string|null}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: details, type: map<string,any>}
  - id: DS-GAP-0003
    name: DetectorDefinition
    fields:
      - {name: detector_id, type: string}
      - {name: inputs, type: list<string>}
      - {name: outputs, type: list<string>}
      - {name: uses_llm, type: bool}
      - {name: contract_schema, type: string|null}
  - id: DS-GAP-0004
    name: GapSynthesisPolicy
    fields:
      - {name: cluster_key, type: enum, values: ["ELEMENT_ID","FILE_UID","DETECTOR"]}
      - {name: affects_cap, type: int}
      - {name: severity_rule, type: enum, values: ["MAX","WEIGHTED"]}
      - {name: id_allocator, type: string}

ALGORITHMS:
  - id: ALG-GAP-0001
    name: RunGapDetectors
    inputs:
      - {name: context, type: DS-STRAT-0004}
      - {name: detectors, type: list<DS-GAP-0003>}
    outputs:
      - {name: findings, type: list<DS-GAP-0002>}
    invariants: [CON-0003]
    pseudocode:
      ```pseudo
      function RunGapDetectors(artifacts, detector_registry, policy):
        findings = []
        for d in detector_registry.detectors:
          if d.enabled_for(policy.phase_id):
            findings += d.run(artifacts, policy)
        return findings
      ```
  - id: ALG-GAP-0002
    name: SynthesizeGapElements
    inputs:
      - {name: findings, type: list<DS-GAP-0002>}
      - {name: policy, type: DS-GAP-0004}
    outputs:
      - {name: gaps, type: list<DS-GAP-0001>}
    invariants: [CON-0012]
    pseudocode:
      ```pseudo
      function SynthesizeGapElements(detector_findings, id_alloc, policy):
        clusters = cluster_findings(detector_findings, key=(finding.element_id or finding.detector_id, finding.file_uid))
      
        gaps_out = []
        for c in clusters:
          gap_id = AllocateDeterministicId(prefix="GAP", namespace=policy.run_id, content_fingerprint=sha256(c.signature()), allocator_state=id_alloc)
          gaps_out.append({
            gap_id: gap_id,
            severity: max([f.severity for f in c.findings]),
            kind: policy.classify_gap_kind(c),
            affects: truncate(c.affects, policy.max_affects),
            evidence: c.evidence_refs
          })
      
        return gaps_out
      ```
  - id: ALG-GAP-0003
    name: EmitGapAsTasks
    inputs:
      - {name: gaps, type: list<DS-GAP-0001>}
    outputs:
      - {name: tasks, type: list<DS-TASK-0001>}
    invariants: [CON-0014]
    pseudocode:
      ```pseudo
      function EmitGapAsTasks(gap_elements, task_policy, id_alloc):
        tasks = []
        for g in gap_elements:
          if g.severity >= task_policy.taskify_severity_floor:
            task_id = AllocateDeterministicId(prefix="TASK", namespace=task_policy.run_id, content_fingerprint=sha256(g.gap_id), allocator_state=id_alloc)
            tasks.append({ task_id: task_id, kind: "RESOLVE_GAP", gap_id: g.gap_id, inputs: g.evidence })
        return tasks
      ```
