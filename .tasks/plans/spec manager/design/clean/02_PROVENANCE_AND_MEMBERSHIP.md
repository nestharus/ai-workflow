LIBRARY: provenance.membership
VERSION: 1.0
CONSTRAINTS: [CON-0001, CON-0002, CON-0006, CON-0007, CON-0016]

DATA_SHAPES:
  - id: DS-PROV-0001
    name: TrackedUnit
    fields:
      - {name: unit_id, type: string}
      - {name: unit_type, type: enum, values: ["PROSE","ALGORITHM","CLAIM","INVARIANT","DATA_STRUCTURE","FLOW","DECISION","TASK","UNKNOWN"]}
      - {name: atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: content_preview, type: string}
      - {name: status, type: enum, values: ["PENDING","MAPPED","MERGED","DROPPED","NON_AUTHORITATIVE","QUARANTINED"]}
      - {name: introduced_by, type: string}
      - {name: modified_by, type: list<string>}
      - {name: membership_evidence, type: map<DS-CORE-0005.atom_id,DS-PROV-0003>}
      - {name: lineage_edges, type: list<DS-PROV-0004>}
      - {name: tags, type: set<string>}
  - id: DS-PROV-0002
    name: SourceLocation
    fields:
      - {name: file_uid, type: DS-CORE-0003.file_uid}
      - {name: rev_id, type: DS-CORE-0004.rev_id}
      - {name: start_atom_id, type: DS-CORE-0005.atom_id}
      - {name: end_atom_id, type: DS-CORE-0005.atom_id}
  - id: DS-PROV-0003
    name: MembershipEvidence
    fields:
      - {name: rationale, type: string}
      - {name: confidence, type: float}
      - {name: method, type: enum, values: ["EXACT","SEQUENCE_ALIGN","LLM_ATOM_MAP","HUMAN_ASSERTION","HEURISTIC_FALLBACK"]}
      - {name: supporting_atom_ids, type: list<DS-CORE-0005.atom_id>}
  - id: DS-PROV-0004
    name: LineageEdge
    fields:
      - {name: edge_id, type: string}
      - {name: from_id, type: string}
      - {name: to_id, type: string}
      - {name: transformation, type: enum, values: ["SPLIT","MERGE","REWRITE","PROMOTE","DEMOTE","PATCH_APPLY","INFER"]}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: confidence, type: float}
  - id: DS-PROV-0005
    name: CoverageReport
    fields:
      - {name: file_uid, type: DS-CORE-0003.file_uid}
      - {name: rev_id, type: DS-CORE-0004.rev_id}
      - {name: total_atoms, type: int}
      - {name: mapped_atoms, type: int}
      - {name: remainder_atoms, type: int}
      - {name: excluded_atoms, type: int}
      - {name: unaccounted_atom_ids, type: list<DS-CORE-0005.atom_id>}
  - id: DS-PROV-0006
    name: Exclusion
    fields:
      - {name: atom_id, type: DS-CORE-0005.atom_id}
      - {name: reason_code, type: enum, values: ["FORMAT","DUPLICATE","PURE_MARKUP","OUT_OF_SCOPE","REDACTED"]}
      - {name: justification, type: string}
  - id: DS-PROV-0007
    name: OperationLogEntry
    fields:
      - {name: op_id, type: string}
      - {name: op_type, type: enum, values: ["INGEST","DECOMPOSE","LABEL","MERGE","PROJECT","AUDIT","APPLY_PATCH","SYNC"]}
      - {name: inputs, type: map<string,any>}
      - {name: outputs, type: map<string,any>}
      - {name: created_at, type: string}
  - id: DS-PROV-0008
    name: TraceQueryResult
    fields:
      - {name: atom_id, type: DS-CORE-0005.atom_id}
      - {name: touched_units, type: list<string>}
      - {name: touched_elements, type: list<string>}
      - {name: touched_libraries, type: list<DS-CORE-0007.lib_id>}
      - {name: last_seen_revision, type: DS-CORE-0004.rev_id}
  - id: DS-PROV-0009
    name: ProvenanceStamp
    fields:
      - {name: from_patch, type: string|null}
      - {name: modified_patches, type: list<string>}
      - {name: source_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: lifecycle_state, type: enum, values: ["TEMP_ONLY","STRIP_ON_FINALIZE"]}

ALGORITHMS:
  - id: ALG-PROV-0001
    name: BuildUnitFromAtomSlice
    inputs:
      - {name: unit_type, type: DS-PROV-0001.unit_type}
      - {name: atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: introduced_by, type: string}
    outputs:
      - {name: unit, type: DS-PROV-0001}
    invariants: [INV-ACC-0101]
    pseudocode:
      ```pseudo
      function BuildUnitFromAtomSlice(unit_type, atom_ids, atoms, id_alloc, meta):
        preview = make_preview(atoms, atom_ids, max_chars=meta.preview_chars)
      
        unit_id = AllocateDeterministicId(prefix="UNIT", namespace=meta.run_id, content_fingerprint=sha256(join(atom_ids)), allocator_state=id_alloc)
      
        membership = {}
        for a in atom_ids:
          membership[a] = { method: meta.membership_method, confidence: meta.membership_confidence, rationale: meta.rationale }
      
        unit = {
          unit_id: unit_id,
          unit_type: unit_type,
          atom_ids: atom_ids,
          content_preview: preview,
          status: "PENDING",
          introduced_by: meta.introduced_by,
          modified_by: [],
          membership_evidence: membership,
          lineage_edges: [],
          tags: set()
        }
      
        return unit
      ```
  - id: ALG-PROV-0002
    name: UpdateCoverageReport
    inputs:
      - {name: atoms, type: list<DS-EVID-0001>}
      - {name: units, type: list<DS-PROV-0001>}
      - {name: exclusions, type: list<DS-PROV-0006>}
    outputs:
      - {name: report, type: DS-PROV-0005}
    invariants: [INV-ACC-0101, INV-ACC-0102]
    pseudocode:
      ```pseudo
      function UpdateCoverageReport(prior_report, atoms, units, exclusions):
        covered = set()
        for u in units:
          covered |= set(u.atom_ids)
      
        excluded = set(exclusions.atom_ids)
      
        total = len(atoms)
        covered_count = len(covered)
        excluded_count = len(excluded)
      
        remainder = set([a.atom_id for a in atoms]) - covered - excluded
      
        report = {
          total_atoms: total,
          covered_atoms: covered_count,
          excluded_atoms: excluded_count,
          remainder_atoms: list(remainder),
          coverage_ratio: covered_count / max(1, total),
          remainder_ratio: len(remainder) / max(1, total)
        }
      
        return report
      ```
  - id: ALG-PROV-0003
    name: VerifyCoverageOrEmitGap
    inputs:
      - {name: report, type: DS-PROV-0005}
    outputs:
      - {name: ok, type: bool}
      - {name: gap_ids, type: list<DS-CORE-0008.elem_id>}
    invariants: [INV-ACC-0101]
    pseudocode:
      ```pseudo
      function VerifyCoverageOrEmitGap(coverage_report, policy):
        if coverage_report.coverage_ratio == 1.0 and coverage_report.remainder_ratio == 0.0:
          return { ok: true }
      
        gaps.emit("GAP-COVERAGE-INCOMPLETE", evidence={ "remainder_atoms": coverage_report.remainder_atoms })
        return { ok: false }
      ```
  - id: ALG-PROV-0004
    name: TraceAtomToOutputs
    inputs:
      - {name: atom_id, type: DS-CORE-0005.atom_id}
      - {name: evidence_graph, type: DS-EVID-0004}
      - {name: indexes, type: map<string,any>}
    outputs:
      - {name: result, type: DS-PROV-0008}
    invariants: [CON-0016]
    pseudocode:
      ```pseudo
      function TraceAtomToOutputs(atom_id, lineage_graph, indices):
        # Return all downstream artifacts linked from this atom
        results = { sections: [], units: [], derived_elements: [], tasks: [], patches: [] }
      
        results.sections = indices.atom_to_section.get(atom_id, [])
        results.units = indices.atom_to_units.get(atom_id, [])
      
        for u in results.units:
          results.derived_elements += indices.unit_to_elements.get(u.unit_id, [])
          results.tasks += indices.element_to_tasks.get_many(results.derived_elements)
      
        results.patches = indices.task_to_patches.get_many(results.tasks)
        return results
      ```
  - id: ALG-PROV-0005
    name: InsertTemporaryProvenanceStamps
    inputs:
      - {name: generated_text, type: string}
      - {name: stamp, type: DS-PROV-0009}
    outputs:
      - {name: stamped_text, type: string}
    invariants: [CON-0004]
    pseudocode:
      ```pseudo
      function InsertTemporaryProvenanceStamps(markdown_text, unit_to_source_map, stamp_format):
        # Stamps are system-owned and removed before finalization.
        out_lines = []
        lines = split_lines_preserve_endings(markdown_text)
      
        for i in range(0, len(lines)):
          line = lines[i]
          stamp = stamp_format.for_line(i+1, unit_to_source_map.lookup(i+1))
          out_lines.append(stamp + line)
      
        return join(out_lines, "")
      ```
  - id: ALG-PROV-0006
    name: StripTemporaryProvenanceStamps
    inputs:
      - {name: stamped_text, type: string}
    outputs:
      - {name: clean_text, type: string}
    invariants: [CON-0004, INV-ACC-0001]
    pseudocode:
      ```pseudo
      function StripTemporaryProvenanceStamps(markdown_text, stamp_format):
        lines = split_lines_preserve_endings(markdown_text)
        out = []
        for line in lines:
          out.append(stamp_format.strip_from_line(line))
        return join(out, "")
      ```
