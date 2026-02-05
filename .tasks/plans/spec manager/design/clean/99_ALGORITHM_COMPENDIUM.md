LIBRARY: clean.algorithm_compendium
VERSION: 2.0
CONSTRAINTS: [CON-0001, CON-0017]

ALGORITHMS:
  - id: ALG-AGENT-0001
    name: RunAgentWithContractValidation
    defined_in: 12_AGENT_CONTRACTS.md
    inputs:
      - {name: invocation, type: DS-AGENT-0002}
      - {name: agent_def, type: DS-AGENT-0001}
    outputs:
      - {name: result, type: DS-AGENT-0003}
    invariants: [CON-0011]
    pseudocode:
      ```pseudo
      function RunAgentWithContractValidation(agent_id, input_payload, output_schema, repair_policy):
        raw = agent.run(agent_id, input_payload)
      
        verdict = schema.validate(output_schema, raw)
        if verdict.ok:
          return raw
      
        repaired = RepairInvalidAgentOutput(agent_id, input_payload, raw, verdict.errors, output_schema, repair_policy)
        if repaired.ok:
          return repaired.output
      
        fallback = AgentFallbackPolicy(agent_id, input_payload, raw, verdict.errors, output_schema, repair_policy)
        return fallback.output
      ```
  - id: ALG-AGENT-0002
    name: RepairInvalidAgentOutput
    defined_in: 12_AGENT_CONTRACTS.md
    inputs:
      - {name: invalid_result, type: DS-AGENT-0003}
      - {name: repair_agent_id, type: string}
      - {name: max_attempts, type: int}
    outputs:
      - {name: repaired_result, type: DS-AGENT-0003}
    invariants: [CON-0011]
    pseudocode:
      ```pseudo
      function RepairInvalidAgentOutput(agent_id, input_payload, raw_output, errors, output_schema, repair_policy):
        for attempt in range(1, repair_policy.max_repair_attempts + 1):
          repair_input = {
            "agent_id": agent_id,
            "input_payload": input_payload,
            "raw_output": raw_output,
            "errors": errors,
            "schema": output_schema
          }
      
          candidate = agent.run(repair_policy.repair_agent_id, repair_input)
      
          verdict = schema.validate(output_schema, candidate)
          if verdict.ok:
            return { ok: true, output: candidate }
      
          raw_output = candidate
          errors = verdict.errors
      
        return { ok: false, output: raw_output, errors: errors }
      ```
  - id: ALG-AGENT-0003
    name: AgentFallbackPolicy
    defined_in: 12_AGENT_CONTRACTS.md
    inputs:
      - {name: result, type: DS-AGENT-0003}
      - {name: fallback_modes, type: list<enum>}
    outputs:
      - {name: next_action, type: string}
    invariants: [CON-0009]
    pseudocode:
      ```pseudo
      function AgentFallbackPolicy(agent_id, input_payload, raw_output, errors, output_schema, repair_policy):
        # 1) Quarantine on schema failure in high-risk phases
        if repair_policy.quarantine_on_invalid:
          quarantine_artifact = {
            "status": "QUARANTINED",
            "agent_id": agent_id,
            "errors": errors,
            "raw_output": raw_output
          }
          gaps.emit("GAP-SCHEMA-INVALID", evidence={ "agent_id": agent_id }, artifact=quarantine_artifact)
          return { output: quarantine_artifact }
      
        # 2) Try alternate model/agent if configured
        for fallback_agent in repair_policy.fallback_agent_ids:
          candidate = agent.run(fallback_agent, input_payload)
          verdict = schema.validate(output_schema, candidate)
          if verdict.ok:
            return { output: candidate }
      
        # 3) Hard-stop output: emit gap; return last output
        gaps.emit("GAP-AGENT-FAILED", evidence={ "agent_id": agent_id }, artifact=raw_output)
        return { output: raw_output }
      ```
  - id: ALG-ARCH-0001
    name: ProposeArchitectureCandidates
    defined_in: 14_ARCHITECTURE_AND_TRADEOFFS.md
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
    defined_in: 14_ARCHITECTURE_AND_TRADEOFFS.md
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
    defined_in: 14_ARCHITECTURE_AND_TRADEOFFS.md
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
    defined_in: 14_ARCHITECTURE_AND_TRADEOFFS.md
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
    defined_in: 14_ARCHITECTURE_AND_TRADEOFFS.md
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
  - id: ALG-AUDIT-0001
    name: AuditCoverageInvariants
    defined_in: 11_AUDIT_AND_QA.md
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
    defined_in: 11_AUDIT_AND_QA.md
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
    defined_in: 11_AUDIT_AND_QA.md
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
    defined_in: 11_AUDIT_AND_QA.md
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
  - id: ALG-COMP-0001
    name: ValidateArtifactContract
    defined_in: 05_COMPLIANCE_AND_VALIDATION.md
    inputs:
      - {name: artifact_json, type: string}
      - {name: schema_path, type: string}
    outputs:
      - {name: result, type: DS-COMP-0001}
    invariants: [CON-0011]
    pseudocode:
      ```pseudo
      function ValidateArtifactContract(artifact, schema_id, allowlists):
        verdict = schema.validate(schema_id, artifact)
      
        errors = []
        warnings = []
      
        if not verdict.ok:
          errors.extend(verdict.errors)
      
        signature_findings = lint.scan_for_bad_signatures(artifact, allowlists)
        errors.extend(signature_findings.errors)
        warnings.extend(signature_findings.warnings)
      
        return { ok: (len(errors) == 0), errors: errors, warnings: warnings }
      ```
  - id: ALG-COMP-0002
    name: ComputeComplianceMetrics
    defined_in: 05_COMPLIANCE_AND_VALIDATION.md
    inputs:
      - {name: coverage_reports, type: list<DS-PROV-0005>}
      - {name: validation_results, type: list<DS-COMP-0001>}
      - {name: drift_reports, type: list<DS-PROJ-0004>}
      - {name: risk_signals, type: list<DS-STRAT-0005>}
    outputs:
      - {name: metrics, type: list<DS-COMP-0002>}
    invariants: [INV-ACC-0101]
    pseudocode:
      ```pseudo
      function ComputeComplianceMetrics(phase_id, artifacts, coverage_report, id_registry):
        format_compliance = metric.format_compliance(artifacts)
        annotation_coverage = metric.annotation_coverage(coverage_report)
        id_normalization = metric.id_normalization(artifacts, id_registry)
      
        return {
          "format_compliance": format_compliance,
          "annotation_coverage": annotation_coverage,
          "id_normalization": id_normalization
        }
      ```
  - id: ALG-COMP-0003
    name: ComputeComplianceScore
    defined_in: 05_COMPLIANCE_AND_VALIDATION.md
    inputs:
      - {name: metrics, type: list<DS-COMP-0002>}
      - {name: penalties, type: map<string}
    outputs:
      - {name: score, type: DS-COMP-0003}
    invariants: [CON-0009]
    pseudocode:
      ```pseudo
      function ComputeComplianceScore(metrics, findings, policy):
        score = avg([metrics.format_compliance, metrics.annotation_coverage, metrics.id_normalization])
      
        penalty = (findings.blockers * policy.blocker_penalty) + (findings.warnings * policy.warning_penalty)
        final = score - penalty
      
        return { score: score, penalty: penalty, final: final }
      ```
  - id: ALG-COMP-0004
    name: GatePhaseTransition
    defined_in: 05_COMPLIANCE_AND_VALIDATION.md
    inputs:
      - {name: from_phase, type: string}
      - {name: to_phase, type: string}
      - {name: score, type: DS-COMP-0003}
      - {name: policy, type: DS-COMP-0005}
    outputs:
      - {name: decision, type: DS-COMP-0004}
    invariants: [CON-0009]
    pseudocode:
      ```pseudo
      function GatePhaseTransition(phase_id, compliance_score, coverage_report, policy):
        if coverage_report.remainder_ratio > policy.max_remainder_ratio:
          gaps.emit("GAP-COVERAGE-REMAINDER", evidence=coverage_report)
          return { pass: false }
      
        if compliance_score.final < policy.compliance_threshold:
          gaps.emit("GAP-COMPLIANCE-LOW", evidence={ "phase_id": phase_id, "score": compliance_score })
          return { pass: false }
      
        if compliance_score.blockers > policy.blocker_threshold:
          gaps.emit("GAP-COMPLIANCE-BLOCKER", evidence={ "phase_id": phase_id })
          return { pass: false }
      
        return { pass: true }
      ```
  - id: ALG-COMP-0005
    name: ScanForForbiddenOutputSignatures
    defined_in: 05_COMPLIANCE_AND_VALIDATION.md
    inputs:
      - {name: artifact, type: object}
      - {name: allowlists, type: map<string,list<string>>}
    outputs:
      - {name: errors, type: list<string>}
      - {name: warnings, type: list<string>}
    invariants: [CON-0021]
    pseudocode:
      ```pseudo
      function ScanForForbiddenOutputSignatures(artifact, allowlists):
        errors = []
        warnings = []

        # Contract-level lint: evidence fields must contain only EVID-* values
        EVIDENCE_FIELD_PATTERN = /^EVID-F\d{4}-R\d{4}-L\d+-L\d+$/

        for field_path, value in walk_json(artifact):
          if field_path.endswith(".evidence_atom_ids[]") or field_path.endswith(".evidence_ids[]"):
            if not EVIDENCE_FIELD_PATTERN.match(value):
              if value not in allowlists.get("evidence_exceptions", []):
                errors.append(format("Invalid evidence reference at %s: %s", field_path, value))

        # Free-text warning: detect derived artifact pointers
        DERIVED_ARTIFACT_PATTERNS = [
          /runs\//,           # run workspace references
          /views\//,          # view directory references
          /\.json$/,          # JSON file references
          /\.yaml$/,          # YAML file references
          /\.md$/             # Markdown file references (unless explicitly allowed)
        ]

        for field_path, value in walk_json(artifact):
          if is_free_text_field(field_path):
            for pattern in DERIVED_ARTIFACT_PATTERNS:
              if pattern.search(value):
                if value not in allowlists.get("derived_artifact_exceptions", []):
                  warnings.append(format("Possible derived artifact reference at %s: %s", field_path, value))

        return { errors: errors, warnings: warnings }
      ```
  - id: ALG-CORE-0001
    name: AllocateFileUid
    defined_in: 00_ID_REGISTRY.md
    inputs:
      - {name: canonical_path, type: string}
      - {name: existing_registry, type: map<string}
    outputs:
      - {name: file_uid, type: DS-CORE-0003.file_uid}
    invariants: [INV-ACC-0001, INV-ACC-0401]
    pseudocode:
      ```pseudo
      function AllocateFileUid(canonical_path, existing_registry):
        if canonical_path in existing_registry:
          return existing_registry[canonical_path].file_uid
      
        next_seq = 1 + max([v.seq for v in existing_registry.values()], default=0)
        file_uid = format("F%04d", next_seq)
      
        existing_registry[canonical_path] = { file_uid: file_uid, canonical_path: canonical_path, seq: next_seq }
        return file_uid
      ```
  - id: ALG-CORE-0002
    name: AllocateRevisionId
    defined_in: 00_ID_REGISTRY.md
    inputs:
      - {name: file_uid, type: DS-CORE-0003.file_uid}
      - {name: sha256, type: string}
      - {name: prior_revisions, type: list<DS-CORE-0004>}
    outputs:
      - {name: rev_id, type: DS-CORE-0004.rev_id}
    invariants: [CON-0001]
    pseudocode:
      ```pseudo
      function AllocateRevisionId(file_uid, sha256, prior_revisions):
        for r in prior_revisions:
          if r.sha256 == sha256:
            return r.rev_id
      
        next_seq = 1 + max([parse_int(r.rev_id[1:]) for r in prior_revisions], default=0)
        rev_id = format("R%04d", next_seq)
      
        prior_revisions.append({ rev_id: rev_id, file_uid: file_uid, sha256: sha256, created_at: now_iso8601() })
        return rev_id
      ```
  - id: ALG-CORE-0003
    name: AllocateDeterministicId
    defined_in: 00_ID_REGISTRY.md
    inputs:
      - {name: prefix, type: DS-CORE-0001.prefix}
      - {name: namespace, type: string|null}
      - {name: content_fingerprint, type: string}
      - {name: allocator_state, type: DS-CORE-0009}
    outputs:
      - {name: allocated_id, type: string}
      - {name: allocator_state, type: DS-CORE-0009}
    invariants: [CON-0008]
    pseudocode:
      ```pseudo
      function AllocateDeterministicId(prefix, namespace, content_fingerprint, allocator_state):
        key = join([prefix, namespace or "∅", content_fingerprint], "|")
      
        if key in allocator_state.stable_maps:
          return allocator_state.stable_maps[key]
      
        counter_key = join([prefix, namespace or "∅"], "|")
        next_seq = 1 + allocator_state.counters.get(counter_key, 0)
      
        candidate = format_id(prefix, namespace, next_seq)
        while candidate in allocator_state.reserved:
          next_seq = next_seq + 1
          candidate = format_id(prefix, namespace, next_seq)
      
        allocator_state.counters[counter_key] = next_seq
        allocator_state.stable_maps[key] = candidate
        allocator_state.reserved.add(candidate)
      
        return candidate
      ```
  - id: ALG-CORE-0004
    name: BuildAtomFingerprint
    defined_in: 00_ID_REGISTRY.md
    inputs:
      - {name: content, type: string}
      - {name: prev_nonblank_content, type: string|null}
      - {name: next_nonblank_content, type: string|null}
      - {name: occurrence_index, type: int}
    outputs:
      - {name: fingerprint, type: string}
    invariants: [INV-ACC-0002]
    pseudocode:
      ```pseudo
      function BuildAtomFingerprint(content, prev_nonblank_content, next_nonblank_content, occurrence_index):
        normalized = normalize(content)
        prev = normalize(prev_nonblank_content or "")
        next = normalize(next_nonblank_content or "")
        payload = join([prev, normalized, next, str(occurrence_index)], "\n---\n")
        return sha256(payload)
      ```
  - id: ALG-CORE-0005
    name: RemapStableIdsAcrossRevisions
    defined_in: 00_ID_REGISTRY.md
    inputs:
      - {name: old_atoms, type: list<DS-EVID-0001>}
      - {name: new_atoms, type: list<DS-EVID-0001>}
    outputs:
      - {name: remap_table, type: map<DS-CORE-0005.atom_fingerprint}
    invariants: [INV-ACC-0301, INV-ACC-0302]
    pseudocode:
      ```pseudo
      function RemapStableIdsAcrossRevisions(old_atoms, new_atoms):
        # Primary: fingerprint-based matching
        old_by_fp = multimap()
        for a in old_atoms:
          old_by_fp[a.atom_fingerprint].append(a.atom_id)
      
        remap = {}  # new_atom_id -> old_atom_id (best effort)
        used_old = set()
      
        for b in new_atoms:
          candidates = old_by_fp.get(b.atom_fingerprint, [])
          if len(candidates) == 1 and candidates[0] not in used_old:
            remap[b.atom_id] = candidates[0]
            used_old.add(candidates[0])
      
        # Secondary: sequence alignment on content for remaining atoms
        unmatched_old = [a for a in old_atoms if a.atom_id not in used_old]
        unmatched_new = [b for b in new_atoms if b.atom_id not in remap]
      
        opcodes = sequence.align([a.content for a in unmatched_old], [b.content for b in unmatched_new])
      
        for op in opcodes:
          if op.tag == "EQUAL":
            for i in range(op.a_start, op.a_end):
              j = op.b_start + (i - op.a_start)
              if j < op.b_end:
                remap[unmatched_new[j].atom_id] = unmatched_old[i].atom_id
      
        return remap
      ```
  - id: ALG-CORE-0006
    name: AllocateLibraryId
    defined_in: 00_ID_REGISTRY.md
    inputs:
      - {name: stability_key, type: string, constraints: ["agent-provided stable identifier for the library concept"]}
      - {name: existing_libraries, type: map<string,DS-DISC-0001>}
    outputs:
      - {name: lib_id, type: DS-CORE-0007.lib_id}
      - {name: is_new, type: bool}
    invariants: [CON-0008]
    pseudocode:
      ```pseudo
      function AllocateLibraryId(stability_key, existing_libraries):
        # Lookup by stability_key first (idempotent)
        for lib in existing_libraries.values():
          if lib.stability_key == stability_key:
            return { lib_id: lib.lib_id, is_new: false }

        # Allocate new lib_id
        next_seq = 1 + max([parse_int(lib.lib_id[4:]) for lib in existing_libraries.values()], default=0)
        lib_id = format("LIB-%04d", next_seq)

        return { lib_id: lib_id, is_new: true }
      ```
  - id: ALG-CORE-0007
    name: ResolveLocalIdsToStableIds
    defined_in: 00_ID_REGISTRY.md
    inputs:
      - {name: tag_delta, type: TagIndexDelta, constraints: ["agent output with local_id references"]}
      - {name: allocator_state, type: DS-CORE-0009}
    outputs:
      - {name: resolved_items, type: list<DS-SPEC-0001>}
      - {name: resolved_relations, type: list<DS-SPEC-0004>}
      - {name: allocator_state, type: DS-CORE-0009}
    invariants: [CON-0019]
    pseudocode:
      ```pseudo
      function ResolveLocalIdsToStableIds(tag_delta, allocator_state):
        # Build local_id -> stable elem_id mapping
        local_to_stable = {}
        resolved_items = []

        for item in tag_delta.items:
          if item.existing_elem_id is not null:
            # Referencing existing element
            local_to_stable[item.local_id] = item.existing_elem_id
            resolved_items.append(lookup_element(item.existing_elem_id))
          else:
            # Allocate new stable elem_id
            fingerprint = sha256(join(sorted(item.evidence_atom_ids), "|"))
            elem_id = AllocateDeterministicId(item.kind, item.lib_id, fingerprint, allocator_state)
            local_to_stable[item.local_id] = elem_id
            resolved_items.append({
              elem_id: elem_id,
              kind: item.kind,
              lib_id: item.lib_id,
              evidence_atom_ids: item.evidence_atom_ids,
              title: item.title,
              body: item.body
            })

        # Rewrite relation endpoints using local_to_stable mapping
        resolved_relations = []
        for rel in tag_delta.relations:
          from_id = local_to_stable.get(rel.from_local_id, rel.from_local_id)
          to_id = local_to_stable.get(rel.to_local_id, rel.to_local_id)
          resolved_relations.append({
            from_id: from_id,
            to_id: to_id,
            relation_type: rel.relation_type,
            evidence_atom_ids: rel.evidence_atom_ids
          })

        return { resolved_items: resolved_items, resolved_relations: resolved_relations, allocator_state: allocator_state }
      ```
  - id: ALG-DISC-0001
    name: BuildCooccurrenceGraphFromEntityTags
    defined_in: 07_LIBRARY_DISCOVERY.md
    inputs:
      - {name: entity_tags, type: list<DS-STRUCT-0005>}
      - {name: evidence_ranges, type: list<DS-EVID-0003>}
    outputs:
      - {name: weighted_graph, type: map<string}
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
    defined_in: 07_LIBRARY_DISCOVERY.md
    inputs:
      - {name: units, type: list<DS-PROV-0001>}
      - {name: cooccurrence_graph, type: map<string}
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
    defined_in: 07_LIBRARY_DISCOVERY.md
    inputs:
      - {name: units, type: list<DS-PROV-0001>}
      - {name: libraries, type: list<DS-DISC-0001>}
      - {name: context_bundles, type: map<string}
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
    defined_in: 07_LIBRARY_DISCOVERY.md
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
    defined_in: 07_LIBRARY_DISCOVERY.md
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
  - id: ALG-EVID-0001
    name: IngestFileToAtoms
    defined_in: 01_EVIDENCE_LAYER.md
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
    defined_in: 01_EVIDENCE_LAYER.md
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
    defined_in: 01_EVIDENCE_LAYER.md
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
    defined_in: 01_EVIDENCE_LAYER.md
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
    defined_in: 01_EVIDENCE_LAYER.md
    inputs:
      - {name: selection, type: DS-EVID-0008}
      - {name: output_layout, type: enum}
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
  - id: ALG-GAP-0001
    name: RunGapDetectors
    defined_in: 06_GAP_DETECTION.md
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
    defined_in: 06_GAP_DETECTION.md
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
    defined_in: 06_GAP_DETECTION.md
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
  - id: ALG-PROJ-0001
    name: GeneratePlanProjectionFromLibraries
    defined_in: 09_PROJECTION_AND_SYNC.md
    inputs:
      - {name: libraries, type: list<DS-DISC-0001>}
      - {name: elements, type: list<DS-SPEC-0001>}
    outputs:
      - {name: projection, type: DS-PROJ-0001}
    invariants: [CON-0010]
    pseudocode:
      ```pseudo
      function GeneratePlanProjectionFromLibraries(libraries, policy):
        # plan.md is a projection view; libraries remain authoritative.
        plan = []
        plan.append(policy.plan_header)
      
        for lib in libraries.sorted_by("lib_id"):
          plan.append(format_plan_entry(lib.lib_id, lib.name, lib.responsibilities, lib.interfaces))
      
        return join(plan, "\n")
      ```
  - id: ALG-PROJ-0002
    name: AtomAwareProjectionComparator
    defined_in: 09_PROJECTION_AND_SYNC.md
    inputs:
      - {name: projection, type: DS-PROJ-0001}
      - {name: authoritative_index, type: DS-SPEC-0003}
      - {name: atoms, type: list<DS-EVID-0001>}
    outputs:
      - {name: drift_report, type: DS-PROJ-0004}
    invariants: [CON-0007, CON-0013]
    pseudocode:
      ```pseudo
      function AtomAwareProjectionComparator(old_plan_atoms, new_plan_atoms, policy):
        # Compare projections by atom alignment, not by raw text heuristics.
        alignment = AlignAtomsAcrossRevisions(old_plan_atoms, new_plan_atoms)
      
        similarity = compute_similarity_from_opcodes(alignment.opcodes)
        drift = { similarity: similarity, opcodes: alignment.opcodes, transforms: alignment.atom_transforms }
      
        return drift
      ```
  - id: ALG-PROJ-0003
    name: ConvertDriftToGaps
    defined_in: 09_PROJECTION_AND_SYNC.md
    inputs:
      - {name: drift_report, type: DS-PROJ-0004}
    outputs:
      - {name: gaps, type: list<DS-GAP-0001>}
    invariants: [CON-0012]
    pseudocode:
      ```pseudo
      function ConvertDriftToGaps(drift_report, policy):
        if drift_report.similarity >= policy.drift_similarity_floor:
          return []
      
        return [{
          kind: "DRIFT",
          severity: policy.drift_severity,
          evidence: drift_report.opcodes,
          message: "Projection drift exceeds floor"
        }]
      ```
  - id: ALG-PROV-0001
    name: BuildUnitFromAtomSlice
    defined_in: 02_PROVENANCE_AND_MEMBERSHIP.md
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
    defined_in: 02_PROVENANCE_AND_MEMBERSHIP.md
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
    defined_in: 02_PROVENANCE_AND_MEMBERSHIP.md
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
    defined_in: 02_PROVENANCE_AND_MEMBERSHIP.md
    inputs:
      - {name: atom_id, type: DS-CORE-0005.atom_id}
      - {name: evidence_graph, type: DS-EVID-0004}
      - {name: indexes, type: map<string}
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
    defined_in: 02_PROVENANCE_AND_MEMBERSHIP.md
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
    defined_in: 02_PROVENANCE_AND_MEMBERSHIP.md
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
  - id: ALG-SPEC-0001
    name: BuildLibraryCharterFromEvidence
    defined_in: 08_LIBRARY_SPEC_BUILDING.md
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
    defined_in: 08_LIBRARY_SPEC_BUILDING.md
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
    defined_in: 08_LIBRARY_SPEC_BUILDING.md
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
    defined_in: 08_LIBRARY_SPEC_BUILDING.md
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
    defined_in: 08_LIBRARY_SPEC_BUILDING.md
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
    defined_in: 08_LIBRARY_SPEC_BUILDING.md
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
  - id: ALG-STRAT-0001
    name: ComputeRiskSignals
    defined_in: 04_STRATEGY_ENGINE.md
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
    defined_in: 04_STRATEGY_ENGINE.md
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
    defined_in: 04_STRATEGY_ENGINE.md
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
    defined_in: 04_STRATEGY_ENGINE.md
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
  - id: ALG-STRUCT-0001
    name: ProposeSectionSpansViaLLM
    defined_in: 13_STRUCTURE_AND_DECOMPOSITION.md
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
    defined_in: 13_STRUCTURE_AND_DECOMPOSITION.md
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
    defined_in: 13_STRUCTURE_AND_DECOMPOSITION.md
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
    defined_in: 13_STRUCTURE_AND_DECOMPOSITION.md
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
  - id: ALG-TASK-0001
    name: ExtractTasksFromSpecIndex
    defined_in: 10_TASK_PLANNING_AND_IMPLEMENTATION_LOOP.md
    inputs:
      - {name: spec_index, type: DS-SPEC-0003}
      - {name: gaps, type: list<DS-GAP-0001>}
    outputs:
      - {name: task_plan, type: DS-TASK-0002}
    invariants: [CON-0014]
    pseudocode:
      ```pseudo
      function ExtractTasksFromSpecIndex(spec_index, policy):
        tasks = agent.run(policy.task_planner_agent_id, { "spec_index": spec_index, "policy": policy })
        # Validate tasks cite elements/evidence
        for t in tasks:
          if t.elem_ids is empty:
            gaps.emit("GAP-TASK-UNGROUNDED", evidence={ "task": t })
        return tasks
      ```
  - id: ALG-TASK-0002
    name: BuildTaskDependencyGraph
    defined_in: 10_TASK_PLANNING_AND_IMPLEMENTATION_LOOP.md
    inputs:
      - {name: tasks, type: list<DS-TASK-0001>}
      - {name: relations, type: list<DS-SPEC-0004>}
    outputs:
      - {name: graph, type: DS-XFORM-0006}
    invariants: [INV-ACC-0401]
    pseudocode:
      ```pseudo
      function BuildTaskDependencyGraph(tasks, policy):
        graph = { nodes: [t.task_id for t in tasks], edges: [] }
      
        for t in tasks:
          for dep in t.depends_on:
            graph.edges.append({ from: dep, to: t.task_id })
      
        graph = graph.deduplicate_edges()
        return graph
      ```
  - id: ALG-TASK-0003
    name: DetectAndBundleCycles
    defined_in: 10_TASK_PLANNING_AND_IMPLEMENTATION_LOOP.md
    inputs:
      - {name: graph, type: DS-XFORM-0006}
    outputs:
      - {name: cycle_groups, type: list<DS-TASK-0003>}
    invariants: [INV-ACC-0401]
    pseudocode:
      ```pseudo
      function DetectAndBundleCycles(task_graph, policy):
        cycles = graph.find_cycles(task_graph)
      
        bundles = []
        if cycles is empty:
          return { bundles: [], acyclic_graph: task_graph }
      
        for cyc in cycles:
          bundles.append({ bundle_id: new_uuid(), task_ids: cyc.nodes })
      
        acyclic = graph.contract_cycles(task_graph, bundles)
        return { bundles: bundles, acyclic_graph: acyclic }
      ```
  - id: ALG-TASK-0004
    name: ImplementationLoopUnknownCapture
    defined_in: 10_TASK_PLANNING_AND_IMPLEMENTATION_LOOP.md
    inputs:
      - {name: task_id, type: DS-TASK-0001.task_id}
      - {name: context_bundle, type: DS-EVID-0007}
      - {name: spec_index, type: DS-SPEC-0003}
    outputs:
      - {name: unknowns, type: list<DS-TASK-0005>}
      - {name: patch_proposals, type: list<DS-TASK-0006>}
    invariants: [CON-0014, INV-ACC-0402]
    pseudocode:
      ```pseudo
      function ImplementationLoopUnknownCapture(task, spec_context, policy):
        # Execute implementation; if unknowns are encountered, emit gaps instead of guessing.
        result = agent.run(policy.task_implementer_agent_id, { "task": task, "context": spec_context })
      
        audit = agent.run(policy.patch_audit_judge_agent_id, { "task": task, "result": result })
        if audit.has_unknowns:
          for u in audit.unknowns:
            gaps.emit("GAP-IMPLEMENTATION-UNKNOWN", evidence={ "task_id": task.task_id, "unknown": u })
      
        return { result: result, audit: audit }
      ```
  - id: ALG-TASK-0005
    name: ConvertUnknownsToGapsAndTasks
    defined_in: 10_TASK_PLANNING_AND_IMPLEMENTATION_LOOP.md
    inputs:
      - {name: unknowns, type: list<DS-TASK-0005>}
    outputs:
      - {name: gaps, type: list<DS-GAP-0001>}
      - {name: tasks, type: list<DS-TASK-0001>}
    invariants: [CON-0012, CON-0014]
    pseudocode:
      ```pseudo
      function ConvertUnknownsToGapsAndTasks(gap_stream, policy, id_alloc):
        unknown_gaps = [g for g in gap_stream if g.kind == "UNKNOWN" or g.kind == "IMPLEMENTATION_UNKNOWN"]
        tasks = EmitGapAsTasks(unknown_gaps, policy.taskify_policy, id_alloc)
        return { gaps: unknown_gaps, tasks: tasks }
      ```
  - id: ALG-WF-0001
    name: OrchestrateRun
    defined_in: 15_WORKFLOW_ORCHESTRATOR.md
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
    defined_in: 15_WORKFLOW_ORCHESTRATOR.md
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
    defined_in: 15_WORKFLOW_ORCHESTRATOR.md
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
    defined_in: 15_WORKFLOW_ORCHESTRATOR.md
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
  - id: ALG-XFORM-0001
    name: AlignAtomsAcrossRevisions
    defined_in: 03_TRANSFORM_AND_COMPOSITING.md
    inputs:
      - {name: old_atoms, type: list<DS-EVID-0001>}
      - {name: new_atoms, type: list<DS-EVID-0001>}
    outputs:
      - {name: opcodes, type: list<DS-XFORM-0002>}
      - {name: atom_transforms, type: list<DS-XFORM-0003>}
    invariants: [INV-ACC-0301, INV-ACC-0303]
    pseudocode:
      ```pseudo
      function AlignAtomsAcrossRevisions(old_atoms, new_atoms):
        a = [normalize(x.content) for x in old_atoms]
        b = [normalize(x.content) for x in new_atoms]
      
        opcodes = sequence.align(a, b)  # EQUAL/REPLACE/DELETE/INSERT with similarity
      
        transforms = []
        for op in opcodes:
          from_ids = [old_atoms[i].atom_id for i in range(op.a_start, op.a_end)]
          to_ids = [new_atoms[j].atom_id for j in range(op.b_start, op.b_end)]
          transforms.append({ op_id: new_uuid(), opcode: op.tag, from_atom_ids: from_ids, to_atom_ids: to_ids })
      
        return { opcodes: opcodes, atom_transforms: transforms }
      ```
  - id: ALG-XFORM-0002
    name: MergeUnitsWithRemainder
    defined_in: 03_TRANSFORM_AND_COMPOSITING.md
    inputs:
      - {name: units_with_same_id, type: list<DS-PROV-0001>}
      - {name: granularity, type: DS-XFORM-0005.level}
    outputs:
      - {name: composite_result, type: DS-XFORM-0004}
    invariants: [CON-0007, INV-ACC-0302]
    pseudocode:
      ```pseudo
      function MergeUnitsWithRemainder(units_with_same_id, granularity):
        # Goal: produce one composite unit + explicit remainder units (never drop atoms).
        all_atoms = union([u.atom_ids for u in units_with_same_id])
      
        composite = choose_primary(units_with_same_id)
      
        merged_atoms = set()
        for u in units_with_same_id:
          merged_atoms |= set(u.atom_ids)
      
        composite.atom_ids = sorted(list(merged_atoms))
        composite.status = "MERGED"
      
        remainder_atoms = set(all_atoms) - set(composite.atom_ids)
        remainders = []
        if remainder_atoms is not empty:
          remainders.append(BuildUnitFromAtomSlice(unit_type="PROSE", atom_ids=sorted(list(remainder_atoms)), atoms=..., id_alloc=..., meta=...))
      
        return { composite_unit: composite, remainder_units: remainders, granularity: granularity }
      ```
  - id: ALG-XFORM-0003
    name: SelectGranularityLevel
    defined_in: 03_TRANSFORM_AND_COMPOSITING.md
    inputs:
      - {name: units, type: list<DS-PROV-0001>}
      - {name: risk_score, type: float}
    outputs:
      - {name: granularity, type: DS-XFORM-0005.level}
    invariants: [CON-0017]
    pseudocode:
      ```pseudo
      function SelectGranularityLevel(units, risk_score):
        # Higher risk -> finer granularity; lower risk -> coarser allowed.
        if risk_score >= 0.80:
          return "LINE"
        if risk_score >= 0.50:
          return "SENTENCE"
        if risk_score >= 0.25:
          return "CLAUSE"
        return "SECTION"
      ```
  - id: ALG-XFORM-0004
    name: BuildPatchDependencyGraph
    defined_in: 03_TRANSFORM_AND_COMPOSITING.md
    inputs:
      - {name: tasks, type: list<DS-TASK-0001>}
      - {name: patch_events, type: list<DS-XFORM-0001>}
    outputs:
      - {name: graph, type: DS-XFORM-0006}
    invariants: [INV-ACC-0401]
    pseudocode:
      ```pseudo
      function BuildPatchDependencyGraph(tasks, patch_events):
        # Nodes: tasks and patch events; edges: task -> patch if task produces/applies it.
        graph = { nodes: [], edges: [] }
        graph.nodes = [t.task_id for t in tasks] + [p.patch_id for p in patch_events]

        for t in tasks:
          for p in patch_events:
            if intersects(t.affected_paths, p.target_paths):
              graph.edges.append({ from: t.task_id, to: p.patch_id, kind: "AFFECTS" })

        graph = graph.deduplicate_edges()
        return graph
      ```
  - id: ALG-XFORM-0005
    name: ValidateAndApplyUnifiedDiff
    defined_in: 03_TRANSFORM_AND_COMPOSITING.md
    inputs:
      - {name: patch, type: DS-XFORM-0001}
      - {name: protected_policy, type: DS-XFORM-0007}
    outputs:
      - {name: apply_log, type: DS-XFORM-0008}
      - {name: needs, type: list<DS-GAP-0001>|null}
    invariants: [CON-0022]
    pseudocode:
      ```pseudo
      function ValidateAndApplyUnifiedDiff(patch, protected_policy):
        logs = []

        # Phase 1: Pre-validate all targets against protected paths
        for target_path in patch.target_paths:
          for pattern in protected_policy.protected_patterns:
            if glob_match(pattern, target_path):
              logs.append({
                log_id: new_uuid(),
                patch_id: patch.patch_id,
                target_path: target_path,
                result: "REJECTED_PROTECTED",
                error_message: format("Path matches protected pattern: %s", pattern)
              })
              # Emit NEED and abort entire patch (all-or-nothing)
              need = emit_need("NEED-PATCH-BLOCKED", evidence={
                "patch_id": patch.patch_id,
                "target_path": target_path,
                "protected_pattern": pattern
              })
              return { apply_log: logs, needs: [need] }

        # Phase 2: Create backups if required
        backups = {}
        if protected_policy.require_backup:
          for target_path in patch.target_paths:
            if file_exists(target_path):
              backup_path = format("%s.backup.%s", target_path, now_iso8601())
              copy_file(target_path, backup_path)
              backups[target_path] = backup_path

        # Phase 3: Apply all-or-nothing
        applied_paths = []
        try:
          for target_path in patch.target_paths:
            apply_unified_diff_to_file(patch, target_path)
            applied_paths.append(target_path)
            logs.append({
              log_id: new_uuid(),
              patch_id: patch.patch_id,
              target_path: target_path,
              applied_at: now_iso8601(),
              result: "SUCCESS",
              backup_path: backups.get(target_path)
            })
        except PatchConflictError as e:
          # Rollback all applied paths
          for path in applied_paths:
            if path in backups:
              restore_file(backups[path], path)
              logs.append({
                log_id: new_uuid(),
                patch_id: patch.patch_id,
                target_path: path,
                result: "ROLLED_BACK"
              })
          logs.append({
            log_id: new_uuid(),
            patch_id: patch.patch_id,
            target_path: e.target_path,
            result: "REJECTED_CONFLICT",
            error_message: e.message
          })
          need = emit_need("NEED-PATCH-CONFLICT", evidence={
            "patch_id": patch.patch_id,
            "target_path": e.target_path,
            "conflict": e.message
          })
          return { apply_log: logs, needs: [need] }

        return { apply_log: logs, needs: null }
      ```
