LIBRARY: structure.decomposition
VERSION: 1.0
CONSTRAINTS: [CON-0003, CON-0002, CON-0009]

DATA_SHAPES:
  - id: DS-STRUCT-0001
    name: SectionSpan
    fields:
      - {name: section_id, type: string, constraints: ["SEC-{file_uid}-{rev_id}-{seq:04d}"]}
      - {name: file_uid, type: DS-CORE-0003.file_uid}
      - {name: rev_id, type: DS-CORE-0004.rev_id}
      - {name: start_line, type: int}
      - {name: end_line, type: int}
      - {name: atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: span_type, type: enum, values: ["BLOCK","LIST","TABLE","PARAGRAPH","CODE","MIXED","UNKNOWN"]}
      - {name: confidence, type: float}
  - id: DS-STRUCT-0002
    name: SectionizationOutput
    fields:
      - {name: file_uid, type: DS-CORE-0003.file_uid}
      - {name: rev_id, type: DS-CORE-0004.rev_id}
      - {name: sections, type: list<DS-STRUCT-0001>}
      - {name: unassigned_atom_ids, type: list<DS-CORE-0005.atom_id>}
  - id: DS-STRUCT-0003
    name: Entity
    fields:
      - {name: entity_id, type: string, constraints: ["ENT-{seq:04d}"]}
      - {name: name, type: string}
      - {name: kind, type: enum, values: ["COMPONENT","STORE","PROTOCOL","FLOW","ACTOR","CONCEPT","UNKNOWN"]}
      - {name: canonical_symbol, type: string}
  - id: DS-STRUCT-0004
    name: EntityMention
    fields:
      - {name: entity_id, type: DS-STRUCT-0003.entity_id}
      - {name: section_id, type: DS-STRUCT-0001.section_id}
      - {name: atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: confidence, type: float}
  - id: DS-STRUCT-0005
    name: EntityTag
    fields:
      - {name: entity_id, type: DS-STRUCT-0003.entity_id}
      - {name: evidence_id, type: DS-CORE-0006.evidence_id|null}
      - {name: atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: confidence, type: float}
  - id: DS-STRUCT-0006
    name: DecompositionFragment
    fields:
      - {name: fragment_id, type: string}
      - {name: atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: fragment_type, type: enum, values: ["PROSE","PROJECTED","SPLIT","UNDERSPECIFIED","DECISION","NOISE","EVIDENCE"]}
      - {name: children, type: list<string>}
  - id: DS-STRUCT-0007
    name: SurgicalOperation
    fields:
      - {name: op_type, type: enum, values: ["SPLIT","PROJECT","MARK_UNDERSPEC","MARK_DECISION","MARK_NOISE"]}
      - {name: target_fragment_id, type: string}
      - {name: outputs, type: list<DS-STRUCT-0006>}
      - {name: rationale, type: string}
      - {name: confidence, type: float}
  - id: DS-STRUCT-0008
    name: SurgicalDecompositionOutput
    fields:
      - {name: root_fragment_id, type: string}
      - {name: fragments, type: map<string,DS-STRUCT-0006>}
      - {name: operations, type: list<DS-STRUCT-0007>}
      - {name: coverage_ok, type: bool}
      - {name: coverage_report, type: DS-PROV-0005|null}

ALGORITHMS:
  - id: ALG-STRUCT-0001
    name: ProposeSectionSpansViaLLM
    inputs:
      - {name: atoms, type: list<DS-EVID-0001>}
      - {name: max_sections, type: int}
    outputs:
      - {name: sectionization, type: DS-STRUCT-0002}
    invariants: [CON-0003, INV-ACC-0101]
    pseudocode:
      ```pseudo
      function ProposeSectionSpansViaLLM(file_revision, atoms, policy):
        input_payload = {
          "file_uid": file_revision.file_uid,
          "rev_id": file_revision.rev_id,
          "atoms": atoms,
          "policy": policy
        }
      
        spans = agent.run(policy.section_span_agent_id, input_payload)
      
        # Enforce 100% coverage via validation/repair loop
        repaired = ValidateAndRepairSectionCoverage(file_revision, spans, policy)
        return repaired.spans
      ```
  - id: ALG-STRUCT-0002
    name: ValidateAndRepairSectionCoverage
    inputs:
      - {name: sectionization, type: DS-STRUCT-0002}
      - {name: atoms, type: list<DS-EVID-0001>}
    outputs:
      - {name: repaired_sectionization, type: DS-STRUCT-0002}
      - {name: gaps, type: list<DS-GAP-0001>}
    invariants: [INV-ACC-0101, INV-ACC-0401]
    pseudocode:
      ```pseudo
      function ValidateAndRepairSectionCoverage(file_revision, spans, policy):
        for attempt in range(1, policy.max_span_repairs + 1):
          verdict = spans.validate_coverage(line_count=file_revision.line_count)
      
          if verdict.ok and verdict.coverage_ratio == 1.0:
            return { spans: spans }
      
          repair_input = {
            "file_uid": file_revision.file_uid,
            "rev_id": file_revision.rev_id,
            "line_count": file_revision.line_count,
            "spans": spans,
            "coverage_issues": verdict.issues
          }
      
          spans = agent.run(policy.section_span_repair_agent_id, repair_input)
      
        # Deterministic fallback: one span covering entire file
        fallback = [{ line_start: 1, line_end: file_revision.line_count, label: "FULL_FILE", confidence: 0.0 }]
        return { spans: fallback }
      ```
  - id: ALG-STRUCT-0003
    name: ExtractEntitiesAndMentionsViaLLM
    inputs:
      - {name: sectionization, type: DS-STRUCT-0002}
      - {name: context_limit, type: int}
    outputs:
      - {name: entities, type: list<DS-STRUCT-0003>}
      - {name: mentions, type: list<DS-STRUCT-0004>}
    invariants: [CON-0003]
    pseudocode:
      ```pseudo
      function ExtractEntitiesAndMentionsViaLLM(atoms, section_spans, policy):
        # Entities are discovered, not assumed; no fixed taxonomy required.
        input_payload = {
          "atoms": atoms,
          "sections": section_spans,
          "max_entities": policy.max_entities,
          "mention_granularity": policy.mention_granularity
        }
      
        extraction = agent.run(policy.entity_extractor_agent_id, input_payload)
      
        # Normalize into graph nodes/edges
        entities = normalize_entities(extraction.entities)
        mentions = normalize_mentions(extraction.mentions)
      
        graph_nodes = build_entity_nodes(entities) + build_mention_nodes(mentions)
        graph_edges = build_edges_mentions_to_entities(mentions)
      
        return { entities: entities, mentions: mentions, graph_nodes: graph_nodes, graph_edges: graph_edges }
      ```
  - id: ALG-STRUCT-0004
    name: SurgicalDecompositionLoop
    inputs:
      - {name: section_id, type: DS-STRUCT-0001.section_id}
      - {name: atoms, type: list<DS-EVID-0001>}
      - {name: max_iterations, type: int}
    outputs:
      - {name: result, type: DS-STRUCT-0008}
      - {name: produced_units, type: list<DS-PROV-0001>}
      - {name: produced_gaps, type: list<DS-GAP-0001>}
    invariants: [INV-ACC-0101, INV-ACC-0401]
    pseudocode:
      ```pseudo
      function SurgicalDecompositionLoop(prose_units, atoms, policy):
        # Each operation must preserve atom coverage; no rewriting without evidence links.
        output_units = []
        queue = prose_units.copy()
      
        for step in range(1, policy.max_surgical_steps + 1):
          if queue.is_empty():
            break
      
          unit = queue.pop_front()
      
          if unit.unit_type != "PROSE":
            output_units.append(unit)
            continue
      
          context = SelectContextBundle(unit.atom_ids, atoms, policy.evidence_ranges, policy.token_budget, policy.context_policy)
      
          surgeon_input = { "unit": unit, "context": context, "policy": policy.surgeon_policy }
          op = agent.run(policy.surgeon_agent_id, surgeon_input)  # split/transform/route operations (schema-validated)
      
          applied = apply_surgery_operation(unit, op)
      
          # Verify coverage: union(child.atom_ids) == unit.atom_ids
          if not coverage.exact_match(unit.atom_ids, applied.children_atom_ids_union):
            gaps.emit("GAP-SURGICAL-COVERAGE", evidence={ "unit_id": unit.unit_id })
            output_units.append(unit)  # quarantine original
            continue
      
          for child in applied.children:
            if child.unit_type == "PROSE" and policy.requeue_prose:
              queue.push_back(child)
            else:
              output_units.append(child)
      
        # Any remaining PROSE after max steps becomes UNKNOWN (explicit, not dropped)
        for remaining in queue:
          remaining.unit_type = "UNKNOWN"
          output_units.append(remaining)
      
        return output_units
      ```
