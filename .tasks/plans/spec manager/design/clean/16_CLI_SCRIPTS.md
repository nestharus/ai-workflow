LIBRARY: cli.commands
VERSION: 1.0
CONSTRAINTS: [CON-0016, CON-0009]

DATA_SHAPES:
  - id: DS-CLI-0001
    name: CommandSpec
    fields:
      - {name: command_id, type: string, constraints: ["CMD-{name}"]}
      - {name: purpose, type: string}
      - {name: entry_phase, type: DS-WF-0001.phase_id}
      - {name: exit_phase, type: DS-WF-0001.phase_id}
      - {name: required_artifacts, type: list<string>}
      - {name: produced_artifacts, type: list<string>}
  - id: DS-CLI-0002
    name: CommandInvocation
    fields:
      - {name: invocation_id, type: string}
      - {name: command_id, type: string}
      - {name: args, type: map<string,any>}
      - {name: run_id, type: string}
  - id: DS-CLI-0003
    name: CommandResult
    fields:
      - {name: invocation_id, type: string}
      - {name: ok, type: bool}
      - {name: snapshots_written, type: list<DS-WF-0004.snapshot_id>}
      - {name: outputs, type: list<DS-WF-0007>}
      - {name: gap_ids, type: list<string>}

COMMANDS:
  - {command_id: "CMD-validate", entry_phase: "STRUCTURE", exit_phase: "STRUCTURE", required_artifacts: ["atoms","sections"], produced_artifacts: ["coverage_report","gaps_report"]}
  - {command_id: "CMD-clean", entry_phase: "DECOMPOSE", exit_phase: "CLEAN", required_artifacts: ["units"], produced_artifacts: ["clean_units","compliance_score","gaps_report"]}
  - {command_id: "CMD-discover", entry_phase: "DISCOVER", exit_phase: "DISCOVER", required_artifacts: ["units","entities"], produced_artifacts: ["libraries","unit_labels","shape_report"]}
  - {command_id: "CMD-refine", entry_phase: "REFINE", exit_phase: "REFINE", required_artifacts: ["libraries","units"], produced_artifacts: ["libraries_md","spec_index","gaps_report"]}
  - {command_id: "CMD-project", entry_phase: "PROJECT", exit_phase: "PROJECT", required_artifacts: ["spec_index"], produced_artifacts: ["plan_md","drift_report","gaps_report"]}
  - {command_id: "CMD-plan-tasks", entry_phase: "PLAN_TASKS", exit_phase: "PLAN_TASKS", required_artifacts: ["spec_index","gaps"], produced_artifacts: ["task_plan"]}
  - {command_id: "CMD-trace", entry_phase: "STRUCTURE", exit_phase: "STRUCTURE", required_artifacts: ["evidence_graph"], produced_artifacts: ["trace_report"]}
  - {command_id: "CMD-run", entry_phase: "INTAKE", exit_phase: "PROJECT", required_artifacts: ["inputs"], produced_artifacts: ["all"]}
