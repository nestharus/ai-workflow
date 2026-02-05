LIBRARY: architecture.candidates
VERSION: 1.0
CONSTRAINTS: [CON-0010, CON-0005, CON-0013]

DATA_SHAPES:
  - id: DS-ARCH-0001
    name: ArchitectureCandidate
    fields:
      - {name: arch_id, type: string, constraints: ["ARCH-{seq:04d}"]}
      - {name: title, type: string}
      - {name: description, type: string}
      - {name: components, type: list<DS-ARCH-0003>}
      - {name: tradeoffs, type: list<DS-ARCH-0006>}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: confidence, type: float}
  - id: DS-ARCH-0002
    name: ArchitectureSelection
    fields:
      - {name: selected_arch_id, type: DS-ARCH-0001.arch_id}
      - {name: rejected_architectures, type: list<DS-ARCH-0001.arch_id>}
      - {name: selection_rationale, type: string}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
  - id: DS-ARCH-0003
    name: ArchitectureComponent
    fields:
      - {name: component_id, type: string}
      - {name: name, type: string}
      - {name: responsibilities, type: list<string>}
      - {name: mapped_lib_ids, type: list<DS-CORE-0007.lib_id>}
      - {name: mapped_elem_ids, type: list<DS-CORE-0008.elem_id>}
  - id: DS-ARCH-0004
    name: InterfaceEdge
    fields:
      - {name: edge_id, type: string}
      - {name: from_component_id, type: string}
      - {name: to_component_id, type: string}
      - {name: purpose, type: string}
      - {name: required_elements, type: list<DS-CORE-0008.elem_id>}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
  - id: DS-ARCH-0005
    name: InterfaceContract
    fields:
      - {name: contract_id, type: string}
      - {name: edge_id, type: DS-ARCH-0004.edge_id}
      - {name: inputs, type: list<string>}
      - {name: outputs, type: list<string>}
      - {name: invariants, type: list<string>}
      - {name: error_model, type: list<string>}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
  - id: DS-ARCH-0006
    name: TradeoffRecord
    fields:
      - {name: tradeoff_id, type: string}
      - {name: dimension, type: string}
      - {name: gain, type: string}
      - {name: loss, type: string}
      - {name: priority_driver, type: string}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}

ALGORITHMS:
  - id: ALG-ARCH-0001
    name: ProposeArchitectureCandidates
    inputs:
      - {name: libraries, type: list<DS-DISC-0001>}
      - {name: spec_index, type: DS-SPEC-0003}
      - {name: max_candidates, type: int}
    outputs:
      - {name: candidates, type: list<DS-ARCH-0001>}
    invariants: [CON-0010]
    pseudocode:
      ```pseudo
      function ProposeArchitectureCandidates(system_charter, libraries, policy):
        ctx = { "system_charter": system_charter, "libraries": libraries, "max_candidates": policy.max_arch_candidates }
        candidates = agent.run(policy.arch_proposer_agent_id, ctx)
        return candidates
      ```
  - id: ALG-ARCH-0002
    name: EvaluateArchitectureTradeoffs
    inputs:
      - {name: candidates, type: list<DS-ARCH-0001>}
      - {name: invariants_priority, type: list<string>}
    outputs:
      - {name: enriched_candidates, type: list<DS-ARCH-0001>}
    invariants: [CON-0005]
    pseudocode:
      ```pseudo
      function EvaluateArchitectureTradeoffs(candidates, constraints, policy):
        evaluations = []
        for c in candidates:
          eval = agent.run(policy.arch_tradeoff_judge_agent_id, { "candidate": c, "constraints": constraints })
          evaluations.append(eval)
        return evaluations
      ```
  - id: ALG-ARCH-0003
    name: SelectArchitecture
    inputs:
      - {name: candidates, type: list<DS-ARCH-0001>}
    outputs:
      - {name: selection, type: DS-ARCH-0002}
    invariants: [CON-0010]
    pseudocode:
      ```pseudo
      function SelectArchitecture(evaluations, policy):
        # Select the candidate maximizing constraint satisfaction and minimizing risk
        best = argmax(evaluations, key = (e.score, -e.risk))
        return best.arch_id
      ```
  - id: ALG-ARCH-0004
    name: MapLibrariesToArchitecture
    inputs:
      - {name: selection, type: DS-ARCH-0002}
      - {name: spec_index, type: DS-SPEC-0003}
    outputs:
      - {name: mapped_components, type: list<DS-ARCH-0003>}
    invariants: [CON-0005]
    pseudocode:
      ```pseudo
      function MapLibrariesToArchitecture(selected_arch, libraries, policy):
        mapping = agent.run(policy.arch_library_mapper_agent_id, { "arch": selected_arch, "libraries": libraries })
        return mapping
      ```
  - id: ALG-ARCH-0005
    name: ExtractInterfaceEdgesAndContracts
    inputs:
      - {name: mapped_components, type: list<DS-ARCH-0003>}
      - {name: spec_index, type: DS-SPEC-0003}
    outputs:
      - {name: edges, type: list<DS-ARCH-0004>}
      - {name: contracts, type: list<DS-ARCH-0005>}
    invariants: [CON-0013]
    pseudocode:
      ```pseudo
      function ExtractInterfaceEdgesAndContracts(arch_mapping, libraries, policy):
        edges = agent.run(policy.interface_edge_extractor_agent_id, { "mapping": arch_mapping, "libraries": libraries })
        contracts = []
        for e in edges:
          c = agent.run(policy.interface_contract_writer_agent_id, { "edge": e, "libraries": libraries })
          contracts.append(c)
        return { edges: edges, contracts: contracts }
      ```
