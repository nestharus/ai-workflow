LIBRARY: evidence.layer
VERSION: 1.0
CONSTRAINTS: [CON-0001, CON-0002, CON-0017]

DATA_SHAPES:
  - id: DS-EVID-0001
    name: Atom
    fields:
      - {name: atom_id, type: DS-CORE-0005.atom_id}
      - {name: atom_fingerprint, type: DS-CORE-0005.atom_fingerprint}
      - {name: file_uid, type: DS-CORE-0003.file_uid}
      - {name: rev_id, type: DS-CORE-0004.rev_id}
      - {name: line_no, type: int}
      - {name: sequence_index, type: int}
      - {name: content, type: string}
      - {name: content_sha256, type: string}
      - {name: byte_start, type: int}
      - {name: byte_end, type: int}
  - id: DS-EVID-0002
    name: FileRevision
    fields:
      - {name: file_uid, type: DS-CORE-0003.file_uid}
      - {name: rev_id, type: DS-CORE-0004.rev_id}
      - {name: canonical_path, type: string}
      - {name: sha256, type: string}
      - {name: atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: line_count, type: int}
      - {name: created_at, type: string}
  - id: DS-EVID-0003
    name: EvidenceRange
    fields:
      - {name: evidence_id, type: DS-CORE-0006.evidence_id}
      - {name: file_uid, type: DS-CORE-0003.file_uid}
      - {name: rev_id, type: DS-CORE-0004.rev_id}
      - {name: start_atom_id, type: DS-CORE-0005.atom_id}
      - {name: end_atom_id, type: DS-CORE-0005.atom_id}
      - {name: atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: content_sha256, type: string}
      - {name: tags, type: set<string>}
  - id: DS-EVID-0004
    name: EvidenceGraph
    fields:
      - {name: nodes, type: map<string,DS-EVID-0005>}
      - {name: edges, type: list<DS-EVID-0006>}
  - id: DS-EVID-0005
    name: EvidenceGraphNode
    fields:
      - {name: node_id, type: string}
      - {name: node_type, type: enum, values: ["ATOM","EVIDENCE_RANGE","ENTITY","DERIVED_ELEMENT","LIBRARY","TASK","GAP"]}
      - {name: payload_ref, type: string}
  - id: DS-EVID-0006
    name: EvidenceGraphEdge
    fields:
      - {name: edge_id, type: string}
      - {name: from_node_id, type: string}
      - {name: to_node_id, type: string}
      - {name: edge_type, type: enum, values: ["SUPPORTS","MENTIONS","DERIVES","DEPENDS_ON","RELATES_TO","PATCHES"]}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: confidence, type: float}
      - {name: method, type: string}
  - id: DS-EVID-0007
    name: ContextBundle
    fields:
      - {name: bundle_id, type: string}
      - {name: atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: text, type: string}
      - {name: max_chars, type: int}
      - {name: selection_rationale, type: string}
  - id: DS-EVID-0008
    name: EvidenceSelectionQuery
    fields:
      - {name: query_type, type: enum, values: ["BY_ELEMENT","BY_LIBRARY","BY_GAP","BY_ENTITY","BY_RANGE"]}
      - {name: target_id, type: string}
      - {name: max_atoms, type: int}
      - {name: include_neighbors, type: bool}

ALGORITHMS:
  - id: ALG-EVID-0001
    name: IngestFileToAtoms
    inputs:
      - {name: file_uid, type: DS-CORE-0003.file_uid}
      - {name: rev_id, type: DS-CORE-0004.rev_id}
      - {name: raw_text, type: string}
    outputs:
      - {name: atoms, type: list<DS-EVID-0001>}
      - {name: file_revision, type: DS-EVID-0002}
    invariants: [INV-ACC-0001, INV-ACC-0002, INV-ACC-0101]
    pseudocode:
      ```pseudo
      function IngestFileToAtoms(file_uid, rev_id, raw_text):
        lines = split_lines_preserve_endings(raw_text)
      
        atoms = []
        occurrence_counter = counter()  # content -> occurrence_index
      
        nonblank_prev = null
        nonblank_next_cache = compute_next_nonblank(lines)
      
        for idx in range(0, len(lines)):
          line_no = idx + 1
          content = lines[idx]
      
          occurrence_index = occurrence_counter.increment(normalize(content))
      
          prev_nonblank = nonblank_prev
          next_nonblank = nonblank_next_cache[idx]
      
          fp = BuildAtomFingerprint(content, prev_nonblank, next_nonblank, occurrence_index)
      
          atom_id = format("ATOM-%s-%s-L%04d", file_uid, rev_id, line_no)
      
          atoms.append({
            atom_id: atom_id,
            atom_fingerprint: fp,
            file_uid: file_uid,
            rev_id: rev_id,
            line_no: line_no,
            sequence_index: idx,
            content: content
          })
      
          if normalize(content) != "":
            nonblank_prev = content
      
        file_revision = { file_uid: file_uid, rev_id: rev_id, sha256: sha256(raw_text), line_count: len(lines) }
        return { atoms: atoms, file_revision: file_revision }
      ```
  - id: ALG-EVID-0002
    name: BuildEvidenceRangesFromSpans
    inputs:
      - {name: file_revision, type: DS-EVID-0002}
      - {name: spans, type: list<DS-STRUCT-0001>}
      - {name: existing_ranges, type: map<string,DS-EVID-0003>}
    outputs:
      - {name: evidence_ranges, type: list<DS-EVID-0003>}
    invariants: [INV-ACC-0003, CON-0008]
    pseudocode:
      ```pseudo
      function BuildEvidenceRangesFromSpans(file_revision, spans, existing_ranges):
        # spans are validated to be within [1..line_count]
        # Evidence IDs are span-addressed and deterministic (idempotent)
        evidence_ranges = []

        for span in spans:
          # Derive ID from span coordinates (deterministic, not sequence-based)
          evidence_id = format("EVID-%s-%s-L%d-L%d", file_revision.file_uid, file_revision.rev_id, span.line_start, span.line_end)

          # Reuse existing range if already present
          if evidence_id in existing_ranges:
            evidence_ranges.append(existing_ranges[evidence_id])
            continue

          evidence_ranges.append({
            evidence_id: evidence_id,
            file_uid: file_revision.file_uid,
            rev_id: file_revision.rev_id,
            line_start: span.line_start,
            line_end: span.line_end,
            label: span.label,
            confidence: span.confidence
          })

        return evidence_ranges
      ```
  - id: ALG-EVID-0003
    name: BuildEvidenceGraphIncremental
    inputs:
      - {name: prior_graph, type: DS-EVID-0004|null}
      - {name: new_nodes, type: list<DS-EVID-0005>}
      - {name: new_edges, type: list<DS-EVID-0006>}
    outputs:
      - {name: graph, type: DS-EVID-0004}
    invariants: [INV-ACC-0301]
    pseudocode:
      ```pseudo
      function BuildEvidenceGraphIncremental(prior_graph, new_nodes, new_edges):
        graph = prior_graph or { nodes: {}, edges: [] }
      
        for n in new_nodes:
          graph.nodes[n.node_id] = n
      
        for e in new_edges:
          graph.edges.append(e)
      
        # Maintain bidirectional adjacency indexes for queries
        graph = graph.reindex_adjacency()
        return graph
      ```
  - id: ALG-EVID-0004
    name: SelectContextBundle
    inputs:
      - {name: query, type: DS-EVID-0008}
      - {name: evidence_graph, type: DS-EVID-0004}
      - {name: max_chars, type: int}
    outputs:
      - {name: bundle, type: DS-EVID-0007}
    invariants: [CON-0017]
    pseudocode:
      ```pseudo
      function SelectContextBundle(target_ids, atoms, evidence_ranges, token_budget, policy):
        # Select minimal evidence that still supports target_ids
        candidate_ranges = evidence_ranges.filter(range => intersects(range, target_ids))
      
        # Always include direct evidence first
        bundle = take_until_budget(candidate_ranges.sorted_by("priority"), token_budget)
      
        if policy.include_neighbors:
          bundle = expand_with_neighbors(bundle, evidence_ranges, policy.neighbor_radius, token_budget)
      
        # Fallback: if still empty, include atom windows around target atoms
        if bundle.is_empty():
          bundle = window_atoms_around_targets(target_ids, atoms, token_budget)
      
        return bundle
      ```
  - id: ALG-EVID-0005
    name: MaterializeEvidenceProjection
    inputs:
      - {name: selection, type: DS-EVID-0008}
      - {name: output_layout, type: enum, values: ["BY_LIBRARY","BY_ENTITY","BY_ELEMENT"]}
    outputs:
      - {name: materialized_paths, type: list<string>}
    invariants: [AUTH-0001, AUTH-0002]
    pseudocode:
      ```pseudo
      function MaterializeEvidenceProjection(projection_plan, atoms_by_file, output_format):
        # output_format is system-owned (templates/*)
        out = output_format.header(projection_plan.meta)
      
        for block in projection_plan.blocks:
          out += output_format.block_header(block.block_id, block.title)
      
          for ev in block.evidence_refs:
            lines = atoms_by_file[ev.file_uid, ev.rev_id].slice(ev.line_start, ev.line_end)
            out += output_format.emit_evidence(ev.evidence_id, lines)
      
          for derived in block.derived_elements:
            out += output_format.emit_derived_element(derived.elem_id, derived.kind, derived.content, derived.annotation_ids)
      
        return out
      ```
