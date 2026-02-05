LIBRARY: projection.sync
VERSION: 1.0
CONSTRAINTS: [CON-0010, CON-0013, CON-0007]

DATA_SHAPES:
  - id: DS-PROJ-0001
    name: ProjectionArtifact
    fields:
      - {name: projection_id, type: string}
      - {name: kind, type: enum, values: ["PLAN_MD","COMPOSITE_MD","TASKS_MD","ARCH_MD"]}
      - {name: generated_from, type: enum, values: ["LIBRARIES","SPEC_INDEX","EVIDENCE_GRAPH"]}
      - {name: content, type: string}
      - {name: pins, type: list<DS-PROJ-0002>}
      - {name: created_at, type: string}
  - id: DS-PROJ-0002
    name: Pin
    fields:
      - {name: pin_id, type: string}
      - {name: from_projection_offset, type: int}
      - {name: target_id, type: string}
      - {name: target_kind, type: enum, values: ["LIBRARY","ELEMENT","ATOM_RANGE"]}
      - {name: target_path, type: string|null}
  - id: DS-PROJ-0003
    name: DriftItem
    fields:
      - {name: drift_type, type: enum, values: ["PLAN_ONLY","MISMATCH","MISSING_PIN","PIN_TARGET_MISSING"]}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: projection_excerpt, type: string}
      - {name: best_match_score, type: float}
  - id: DS-PROJ-0004
    name: DriftReport
    fields:
      - {name: projection_id, type: string}
      - {name: compared_to, type: string}
      - {name: drift_items, type: list<DS-PROJ-0003>}
      - {name: drift_rate, type: float}
      - {name: created_at, type: string}

ALGORITHMS:
  - id: ALG-PROJ-0001
    name: GeneratePlanProjectionFromLibraries
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
