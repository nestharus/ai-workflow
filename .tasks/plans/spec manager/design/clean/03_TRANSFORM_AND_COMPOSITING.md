LIBRARY: transforms.diff_merge
VERSION: 1.0
CONSTRAINTS: [CON-0002, CON-0007, CON-0009]

DATA_SHAPES:
  - id: DS-XFORM-0001
    name: PatchEvent
    fields:
      - {name: patch_id, type: string}
      - {name: kind, type: enum, values: ["NEW_REVISION","UNIFIED_DIFF","MANUAL_EDIT"]}
      - {name: target_paths, type: list<string>}
      - {name: created_at, type: string}
      - {name: author, type: string|null}
  - id: DS-XFORM-0002
    name: SequenceOpcode
    fields:
      - {name: tag, type: enum, values: ["EQUAL","REPLACE","DELETE","INSERT"]}
      - {name: a_start, type: int}
      - {name: a_end, type: int}
      - {name: b_start, type: int}
      - {name: b_end, type: int}
      - {name: similarity, type: float}
  - id: DS-XFORM-0003
    name: AtomTransform
    fields:
      - {name: op_id, type: string}
      - {name: opcode, type: DS-XFORM-0002.tag}
      - {name: from_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: to_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: patch_id, type: string}
      - {name: confidence, type: float}
  - id: DS-XFORM-0004
    name: CompositeResult
    fields:
      - {name: merged_units, type: list<DS-PROV-0001>}
      - {name: remainder_units, type: list<DS-PROV-0001>}
      - {name: lineage_edges, type: list<DS-PROV-0004>}
  - id: DS-XFORM-0005
    name: GranularityLevel
    fields:
      - {name: level, type: enum, values: ["LINE","SENTENCE","CLAUSE","SECTION"]}
      - {name: selection_signal, type: enum, values: ["ANNOTATION_DENSITY","RISK_SCORE","MANUAL_OVERRIDE"]}
  - id: DS-XFORM-0006
    name: PatchDependencyGraph
    fields:
      - {name: nodes, type: set<string>}
      - {name: edges, type: list<tuple<string,string>>}
      - {name: topo_order, type: list<string>}
      - {name: cycles, type: list<list<string>>}
  - id: DS-XFORM-0007
    name: ProtectedPathPolicy
    fields:
      - {name: protected_patterns, type: list<string>, constraints: ["glob patterns for paths that cannot be modified"]}
      - {name: require_backup, type: bool}
  - id: DS-XFORM-0008
    name: PatchApplyLog
    fields:
      - {name: log_id, type: string}
      - {name: patch_id, type: string}
      - {name: target_path, type: string}
      - {name: applied_at, type: string}
      - {name: result, type: enum, values: ["SUCCESS", "REJECTED_PROTECTED", "REJECTED_CONFLICT", "ROLLED_BACK"]}
      - {name: backup_path, type: string|null}
      - {name: error_message, type: string|null}

ALGORITHMS:
  - id: ALG-XFORM-0001
    name: AlignAtomsAcrossRevisions
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
