LIBRARY: discovery.library_labeling
VERSION: 1.0
CONSTRAINTS: [CON-0003, CON-0009, CON-0012]

DATA_SHAPES:
  - id: DS-DISC-0001
    name: Library
    fields:
      - {name: lib_id, type: DS-CORE-0007.lib_id}
      - {name: name, type: string}
      - {name: charter, type: string}
      - {name: charter_evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: element_ids, type: list<DS-CORE-0008.elem_id>}
      - {name: relation_lib_ids, type: list<DS-CORE-0007.lib_id>}
      - {name: stability_key, type: string}
  - id: DS-DISC-0002
    name: LibraryCandidate
    fields:
      - {name: candidate_id, type: string}
      - {name: seed_unit_ids, type: list<string>}
      - {name: seed_atoms, type: list<DS-CORE-0005.atom_id>}
      - {name: proposed_name, type: string}
      - {name: confidence, type: float}
  - id: DS-DISC-0003
    name: UnitLabel
    fields:
      - {name: unit_id, type: string}
      - {name: primary_lib_id, type: DS-CORE-0007.lib_id|null}
      - {name: secondary_lib_ids, type: list<DS-CORE-0007.lib_id>}
      - {name: confidence, type: float}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
  - id: DS-DISC-0004
    name: Shape
    fields:
      - {name: lib_id, type: DS-CORE-0007.lib_id}
      - {name: strong_unit_ids, type: list<string>}
      - {name: medium_unit_ids, type: list<string>}
      - {name: weak_unit_ids, type: list<string>}
      - {name: convergence, type: float}
  - id: DS-DISC-0005
    name: DiscoveryIterationResult
    fields:
      - {name: iteration, type: int}
      - {name: shapes, type: list<DS-DISC-0004>}
      - {name: convergence_score, type: float}
      - {name: unresolved_units, type: list<string>}
      - {name: overlap_pairs, type: list<tuple<DS-CORE-0007.lib_id,DS-CORE-0007.lib_id>>}

ALGORITHMS:
  - id: ALG-DISC-0001
    name: BuildCooccurrenceGraphFromEntityTags
    inputs:
      - {name: entity_tags, type: list<DS-STRUCT-0005>}
      - {name: evidence_ranges, type: list<DS-EVID-0003>}
    outputs:
      - {name: weighted_graph, type: map<string,map<string,float>>}
    invariants: [CON-0003]
    pseudocode:
      ```pseudo
      function BuildCooccurrenceGraphFromEntityTags(mentions, window_policy):
        # mentions: atom_id -> [entity_id...]
        graph = { nodes: set(), edges: map<(entity_id,entity_id), float>() }
      
        for atom_id in mentions.keys():
          ents = mentions[atom_id]
          for e in ents:
            graph.nodes.add(e)
      
          # window: same atom or neighbor atoms (by sequence index), driven by atom ordering
          for (e1, e2) in all_pairs(ents):
            graph.edges[(e1,e2)] = graph.edges.get((e1,e2), 0.0) + window_policy.same_atom_weight
      
        return graph
      ```
  - id: ALG-DISC-0002
    name: ProposeLibraryCandidates
    inputs:
      - {name: units, type: list<DS-PROV-0001>}
      - {name: cooccurrence_graph, type: map<string,map<string,float>>}
      - {name: evidence_graph, type: DS-EVID-0004}
    outputs:
      - {name: candidates, type: list<DS-DISC-0002>}
    invariants: [CON-0009]
    pseudocode:
      ```pseudo
      function ProposeLibraryCandidates(entities, cooccurrence_graph, policy):
        input_payload = {
          "entities": entities,
          "graph": cooccurrence_graph,
          "max_libraries": policy.max_libraries
        }
      
        # LLM proposes candidate library charters + boundary rationales (schema-validated)
        candidates = agent.run(policy.library_candidate_agent_id, input_payload)
        return candidates
      ```
  - id: ALG-DISC-0003
    name: MultiLabelUnitsToLibraries
    inputs:
      - {name: units, type: list<DS-PROV-0001>}
      - {name: libraries, type: list<DS-DISC-0001>}
      - {name: context_bundles, type: map<string,DS-EVID-0007>}
    outputs:
      - {name: labels, type: list<DS-DISC-0003>}
    invariants: [INV-ACC-0201]
    pseudocode:
      ```pseudo
      function MultiLabelUnitsToLibraries(units, library_candidates, policy):
        # Each unit may belong to multiple libraries; membership is evidence-based.
        labels = []
        for u in units:
          ctx = { "unit": u, "libraries": library_candidates }
          dist = agent.run(policy.multilabel_agent_id, ctx)  # returns distribution + uncertainties
          labels.append({ unit_id: u.unit_id, distribution: dist })
        return labels
      ```
  - id: ALG-DISC-0004
    name: AggregateShapesAndRefine
    inputs:
      - {name: labels, type: list<DS-DISC-0003>}
      - {name: max_iterations, type: int}
    outputs:
      - {name: result, type: DS-DISC-0005}
    invariants: [CON-0012]
    pseudocode:
      ```pseudo
      function AggregateShapesAndRefine(library_candidates, unit_labels, policy):
        # Aggregate per-library evidence: which units/atoms support it.
        libs = build_library_assignments(library_candidates, unit_labels, policy)
      
        refined = agent.run(policy.library_refiner_agent_id, { "libraries": libs, "policy": policy })
        return refined
      ```
  - id: ALG-DISC-0005
    name: ResolveOverlapWithNonDestructiveMoves
    inputs:
      - {name: overlap_pairs, type: DS-DISC-0005.overlap_pairs}
      - {name: shapes, type: list<DS-DISC-0004>}
    outputs:
      - {name: proposed_actions, type: list<string>}
      - {name: gaps, type: list<DS-GAP-0001>}
    invariants: [CON-0002]
    pseudocode:
      ```pseudo
      function ResolveOverlapWithNonDestructiveMoves(libraries, overlap_report, policy):
        # Moves are index-level reassignments; underlying evidence stays immutable.
        for pair in overlap_report.pairs_sorted_by_severity:
          action = agent.run(policy.overlap_resolver_agent_id, { "lib_a": pair.a, "lib_b": pair.b, "evidence": pair.shared_evidence })
      
          if action.kind == "MOVE_EVIDENCE_REF":
            libraries = apply_move(libraries, action)
          if action.kind == "SPLIT_LIBRARY":
            libraries = apply_split(libraries, action)
          if action.kind == "NEW_LIBRARY":
            libraries = apply_new_library(libraries, action)
      
        return libraries
      ```
