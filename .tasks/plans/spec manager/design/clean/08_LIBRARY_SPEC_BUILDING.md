LIBRARY: spec.building_refinement
VERSION: 1.0
CONSTRAINTS: [CON-0005, CON-0002, CON-0012]

DATA_SHAPES:
  - id: DS-SPEC-0001
    name: DerivedElement
    fields:
      - {name: elem_id, type: DS-CORE-0008.elem_id}
      - {name: kind, type: DS-CORE-0008.kind}
      - {name: lib_id, type: DS-CORE-0007.lib_id}
      - {name: title, type: string}
      - {name: body, type: string}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: confidence, type: float}
      - {name: status, type: enum, values: ["DRAFT","ACTIVE","NON_AUTHORITATIVE","QUARANTINED","DEPRECATED"]}
      - {name: derived_from_elem_ids, type: list<DS-CORE-0008.elem_id>}
      - {name: relations, type: list<DS-SPEC-0004>}
  - id: DS-SPEC-0002
    name: LibraryCharter
    fields:
      - {name: lib_id, type: DS-CORE-0007.lib_id}
      - {name: name, type: string}
      - {name: responsibilities, type: list<string>}
      - {name: boundaries, type: list<string>}
      - {name: invariants, type: list<string>}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
  - id: DS-SPEC-0003
    name: SpecIndex
    fields:
      - {name: libraries, type: list<DS-DISC-0001>}
      - {name: elements, type: map<DS-CORE-0008.elem_id,DS-SPEC-0001>}
      - {name: atom_to_elements, type: map<DS-CORE-0005.atom_id,list<DS-CORE-0008.elem_id>>}
      - {name: element_to_atoms, type: map<DS-CORE-0008.elem_id,list<DS-CORE-0005.atom_id>>}
      - {name: relations, type: list<DS-SPEC-0004>}
      - {name: created_at, type: string}
  - id: DS-SPEC-0004
    name: RelationEdge
    fields:
      - {name: from_id, type: string}
      - {name: to_id, type: string}
      - {name: relation_type, type: enum, values: ["DEPENDS_ON","REFINES","CONTRADICTS","OVERLAPS","IMPLEMENTS"]}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: confidence, type: float}
  - id: DS-SPEC-0005
    name: ProofChainStatus
    fields:
      - {name: elem_id, type: DS-CORE-0008.elem_id}
      - {name: required_links, type: list<enum>, values: ["CLAIM","PROOF","FORMAL"]}
      - {name: missing_links, type: list<string>}
      - {name: status, type: enum, values: ["COMPLETE","INCOMPLETE","BROKEN"]}

ALGORITHMS:
  - id: ALG-SPEC-0001
    name: BuildLibraryCharterFromEvidence
    inputs:
      - {name: lib_id, type: DS-CORE-0007.lib_id}
      - {name: units, type: list<DS-PROV-0001>}
      - {name: evidence_graph, type: DS-EVID-0004}
    outputs:
      - {name: charter, type: DS-SPEC-0002}
    invariants: [CON-0005]
    pseudocode:
      ```pseudo
      function BuildLibraryCharterFromEvidence(lib_id, evidence_bundle, policy):
        charter = agent.run(policy.charter_builder_agent_id, { "lib_id": lib_id, "evidence": evidence_bundle })
        # Charter must reference evidence IDs; no ungrounded claims
        if not charter.references_only(evidence_bundle.evidence_ids):
          gaps.emit("GAP-CHARTER-UNGROUNDED", evidence={ "lib_id": lib_id })
        return charter
      ```
  - id: ALG-SPEC-0002
    name: ExtractDerivedElementsFromUnits
    inputs:
      - {name: lib_id, type: DS-CORE-0007.lib_id}
      - {name: units, type: list<DS-PROV-0001>}
      - {name: allocator, type: DS-CORE-0009}
    outputs:
      - {name: elements, type: list<DS-SPEC-0001>}
      - {name: allocator, type: DS-CORE-0009}
    invariants: [INV-ACC-0201]
    pseudocode:
      ```pseudo
      function ExtractDerivedElementsFromUnits(units, lib_id, policy):
        # Derived elements (REQ/FLOW/INV/DEC/ALG/DS) must cite atom/evidence IDs.
        ctx = { "lib_id": lib_id, "units": units, "policy": policy }
        out = agent.run(policy.derived_extractor_agent_id, ctx)
      
        # Validate grounding: every element must have >=1 evidence reference
        for e in out.elements:
          if e.evidence_ids is empty:
            gaps.emit("GAP-ELEMENT-UNGROUNDED", evidence={ "elem_id": e.elem_id, "lib_id": lib_id })
      
        return out.elements
      ```
  - id: ALG-SPEC-0003
    name: BuildSpecIndex
    inputs:
      - {name: libraries, type: list<DS-DISC-0001>}
      - {name: elements, type: list<DS-SPEC-0001>}
    outputs:
      - {name: index, type: DS-SPEC-0003}
    invariants: [INV-ACC-0201, INV-ACC-0302]
    pseudocode:
      ```pseudo
      function BuildSpecIndex(libraries, derived_elements, id_alloc, policy):
        # Build canonical indexes for traceability
        index = {
          lib_to_elements: {},
          element_to_evidence: {},
          evidence_to_elements: {},
          element_to_tasks: {}
        }
      
        for lib in libraries:
          elems = [e for e in derived_elements if e.lib_id == lib.lib_id]
          index.lib_to_elements[lib.lib_id] = [e.elem_id for e in elems]
      
          for e in elems:
            index.element_to_evidence[e.elem_id] = e.evidence_ids
            for evid in e.evidence_ids:
              index.evidence_to_elements.setdefault(evid, []).append(e.elem_id)
      
        return index
      ```
  - id: ALG-SPEC-0004
    name: IterativeGapClosureLoop
    inputs:
      - {name: lib_id, type: DS-CORE-0007.lib_id}
      - {name: index, type: DS-SPEC-0003}
      - {name: max_iterations, type: int}
    outputs:
      - {name: updated_index, type: DS-SPEC-0003}
      - {name: new_gaps, type: list<DS-GAP-0001>}
    invariants: [CON-0012]
    pseudocode:
      ```pseudo
      function IterativeGapClosureLoop(lib_id, charter, units, policy):
        spec = initialize_spec_from_charter(charter)
      
        for iter in range(1, policy.max_spec_iterations + 1):
          patch = agent.run(policy.spec_integrator_agent_id, { "lib_id": lib_id, "spec": spec, "units": units })
          spec = apply_patch(spec, patch)
      
          gaps_out = agent.run(policy.spec_gap_judge_agent_id, { "lib_id": lib_id, "spec": spec, "units": units })
      
          if gaps_out.count == 0:
            break
      
          if sha256(gaps_out.signature) == sha256(policy.last_gap_signature_for(lib_id)):
            break  # stagnation
          policy.record_gap_signature(lib_id, gaps_out.signature)
      
        return spec
      ```
  - id: ALG-SPEC-0005
    name: ProofChainValidationAndQuarantine
    inputs:
      - {name: elements, type: list<DS-SPEC-0001>}
    outputs:
      - {name: proof_status, type: list<DS-SPEC-0005>}
      - {name: quarantined_elem_ids, type: list<DS-CORE-0008.elem_id>}
      - {name: gaps, type: list<DS-GAP-0001>}
    invariants: [CON-0012]
    pseudocode:
      ```pseudo
      function ProofChainValidationAndQuarantine(spec_elements, policy):
        # Chain: Algorithm -> Claim -> Proof -> (Optional) Formalization
        for alg in spec_elements.where(kind="ALG"):
          chain = find_proof_chain(alg, spec_elements)
      
          if chain.missing_links is empty:
            continue
      
          if policy.allow_inference:
            inferred = agent.run(policy.proof_inference_agent_id, { "algorithm": alg, "missing": chain.missing_links })
            attach_inferred(chain, inferred)
      
          if chain.still_missing_links():
            alg.status = "NON_AUTHORITATIVE"
            gaps.emit("GAP-PROOF-CHAIN", evidence={ "elem_id": alg.elem_id, "missing": chain.missing_links })
      ```
  - id: ALG-SPEC-0006
    name: ComputeSpecItemHash
    inputs:
      - {name: elem, type: DS-SPEC-0001}
      - {name: mode, type: enum, values: ["EVIDENCE_IDS_ONLY", "FULL"]}
    outputs:
      - {name: hash, type: string}
    invariants: [CON-0020]
    pseudocode:
      ```pseudo
      function ComputeSpecItemHash(elem, mode="EVIDENCE_IDS_ONLY"):
        # Default mode excludes labels to prevent churn on editorial renames
        if mode == "EVIDENCE_IDS_ONLY":
          # Hash only evidence references - stable across label edits
          payload = join([
            elem.elem_id,
            elem.kind,
            elem.lib_id,
            join(sorted(elem.evidence_atom_ids), "|")
          ], "\n")
        else:
          # Full mode includes labels (use sparingly)
          payload = join([
            elem.elem_id,
            elem.kind,
            elem.lib_id,
            elem.title,
            elem.body,
            join(sorted(elem.evidence_atom_ids), "|")
          ], "\n")

        return sha256(payload)
      ```
