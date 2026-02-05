LIBRARY: core.id_registry
VERSION: 1.0
CONSTRAINTS: [CON-0004, CON-0008, CON-0016]

DATA_SHAPES:
  - id: DS-CORE-0001
    name: IdPrefix
    fields:
      - {name: prefix, type: string, constraints: ["uppercase", "A-Z0-9_\-"]}
      - {name: domain, type: string, constraints: ["library/module owning the prefix"]}
      - {name: description, type: string}
  - id: DS-CORE-0002
    name: GlobalId
    fields:
      - {name: raw, type: string}
      - {name: prefix, type: string}
      - {name: body, type: string}
      - {name: version, type: string|null}
      - {name: namespace, type: string|null}
  - id: DS-CORE-0003
    name: FileUid
    fields:
      - {name: file_uid, type: string, constraints: ["F####", "stable across revisions"]}
      - {name: canonical_path, type: string}
      - {name: first_seen_run_id, type: string}
  - id: DS-CORE-0004
    name: RevisionId
    fields:
      - {name: rev_id, type: string, constraints: ["R####", "monotonic per file_uid"]}
      - {name: file_uid, type: string}
      - {name: sha256, type: string}
      - {name: created_at, type: string}
  - id: DS-CORE-0005
    name: AtomId
    fields:
      - {name: atom_id, type: string, constraints: ["ATOM-{file_uid}-{rev_id}-L{line:04d}"]}
      - {name: atom_fingerprint, type: string, constraints: ["stable-ish across revisions", "content+context hash"]}
  - id: DS-CORE-0006
    name: EvidenceRangeId
    fields:
      - {name: evidence_id, type: string, constraints: ["EVID-{file_uid}-{rev_id}-L{start_line}-L{end_line}", "span-addressed, deterministic"]}
  - id: DS-CORE-0007
    name: LibraryId
    fields:
      - {name: lib_id, type: string, constraints: ["LIB-{seq:04d}"]}
  - id: DS-CORE-0008
    name: DerivedElementId
    fields:
      - {name: elem_id, type: string, constraints: ["{KIND}-LIB-{lib_seq:04d}-{seq:04d}"]}
      - {name: kind, type: enum, values: ["REQ","FLOW","INV","DEC","ALG","DS","NOTE","GAP"]}
  - id: DS-CORE-0009
    name: DeterministicIdAllocatorState
    fields:
      - {name: counters, type: map<string,int>, constraints: ["keyed by prefix+namespace"]}
      - {name: reserved, type: set<string>}
      - {name: stable_maps, type: map<string,string>, constraints: ["content_fingerprint -> allocated_id"]}

ALGORITHMS:
  - id: ALG-CORE-0001
    name: AllocateFileUid
    inputs:
      - {name: canonical_path, type: string}
      - {name: existing_registry, type: map<string,DS-CORE-0003>}
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
    inputs:
      - {name: old_atoms, type: list<DS-EVID-0001>}
      - {name: new_atoms, type: list<DS-EVID-0001>}
    outputs:
      - {name: remap_table, type: map<DS-CORE-0005.atom_fingerprint,DS-CORE-0005.atom_id>}
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
