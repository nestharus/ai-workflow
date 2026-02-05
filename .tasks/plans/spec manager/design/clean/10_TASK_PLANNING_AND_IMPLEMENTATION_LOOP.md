LIBRARY: tasks.implementation_loop
VERSION: 1.0
CONSTRAINTS: [CON-0014, CON-0009, CON-0002]

DATA_SHAPES:
  - id: DS-TASK-0001
    name: Task
    fields:
      - {name: task_id, type: string, constraints: ["TASK-{seq:04d}"]}
      - {name: title, type: string}
      - {name: description, type: string}
      - {name: target_lib_ids, type: list<DS-CORE-0007.lib_id>}
      - {name: target_elem_ids, type: list<DS-CORE-0008.elem_id>}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: dependencies, type: list<string>}
      - {name: status, type: enum, values: ["PLANNED","IN_PROGRESS","DONE","BLOCKED","NEEDS_SPEC"]}
      - {name: outputs, type: list<DS-TASK-0004>}
  - id: DS-TASK-0002
    name: TaskPlan
    fields:
      - {name: plan_id, type: string}
      - {name: tasks, type: list<DS-TASK-0001>}
      - {name: dependency_graph, type: DS-XFORM-0006}
      - {name: created_at, type: string}
  - id: DS-TASK-0003
    name: CycleGroup
    fields:
      - {name: group_id, type: string}
      - {name: task_ids, type: list<string>}
      - {name: rationale, type: string}
  - id: DS-TASK-0004
    name: TaskOutputArtifact
    fields:
      - {name: kind, type: enum, values: ["CODE_PATCH","SPEC_PATCH","TESTS","DOCS","AUDIT_REPORT"]}
      - {name: path, type: string}
      - {name: sha256, type: string}
  - id: DS-TASK-0005
    name: ImplementationUnknown
    fields:
      - {name: unknown_id, type: string, constraints: ["UNK-{seq:04d}"]}
      - {name: message, type: string}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: encountered_in_task_id, type: DS-TASK-0001.task_id}
      - {name: proposed_questions, type: list<string>}
      - {name: proposed_spec_changes, type: list<string>}
      - {name: severity, type: enum, values: ["WARN","ERROR"]}
  - id: DS-TASK-0006
    name: SpecPatchProposal
    fields:
      - {name: proposal_id, type: string}
      - {name: target_lib_id, type: DS-CORE-0007.lib_id}
      - {name: proposed_changes, type: string}
      - {name: evidence_atom_ids, type: list<DS-CORE-0005.atom_id>}
      - {name: confidence, type: float}

ALGORITHMS:
  - id: ALG-TASK-0001
    name: ExtractTasksFromSpecIndex
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
