# Tech Plan: Project & Ticket System (Index)

- **Replaces**: prior monolithic `Tech_Plan__Project_&_Ticket_System.md` by splitting into library-scoped specs.
- **Updated**: 2026-01-26
- **Scope**: Project Manager + Ticket Manager (CLI) layer that converts planning docs into ticket/task/step execution producing patch stacks + durable evidence.

## How to read this spec set

- The spec is split into “libraries” (code modules). Each library has its own file under `project_ticket_system/`.
- Libraries may reference each other; cross-references use the library IDs below.
- Durable data shapes are authoritative in `Tech_Plan__Core_Infrastructure.md` (out of scope here).

## Library map (recommended breakdown)

| Library ID | File | Responsibilities |
|---|---|---|
| `pm` | `project_ticket_system/Lib__Project_Manager.md` | Project selection/creation, ticket triage entrypoints, project workflows surface |
| `tm` | `project_ticket_system/Lib__Ticket_Manager.md` | Ticket/task execution driver, runs/steps orchestration, error handling, **multi-ticket concurrency rules** |
| `cli` | `project_ticket_system/Lib__CLI_Shells.md` | `/project-manager` + `/ticket-manager` REPL rules and command sets |
| `stack_viz` | `project_ticket_system/Lib__Patch_Stack_Visualization.md` | Patch-Stream stack inspection commands (show stack, list patches, diffs, export status) |
| `wss_surfaces` | `project_ticket_system/Lib__Data_Surfaces.md` | WSS paths used by PM/TM, and the jj/PGS integration surface |
| `workflow_resolver` | `project_ticket_system/Lib__Workflow_Resolution.md` | Workflow selection model, overrides, and deterministic resolution |
| `lifecycle` | `project_ticket_system/Lib__Lifecycle.md` | Ticket/task state machines, locking, optimistic concurrency expectations, **inter-ticket dependencies** |
| `decompose` | `project_ticket_system/Lib__Task_Decomposition.md` | Decomposition contract, progress signatures, step-plan schema, give-up rules |
| `execute` | `project_ticket_system/Lib__Step_Execution.md` | Step execution pipeline, evidence emission, deviations + approval protocol |
| `validate` | `project_ticket_system/Lib__Validation.md` | Sandbox validation contract + result interpretation + recovery |
| `export` | `project_ticket_system/Lib__Export.md` | Ticket close/export policies, review export, scrubbing, **dependency validation + rebase ordering** |
| `indexer` | `project_ticket_system/Lib__Indexing.md` | Derived index (`workspace/index.json`), dirty marker, rebuild + fallback |
| `risk` | `project_ticket_system/Lib__Risk_Register.md` | Risk register (manager layer) |

## Dependency sketch (non-normative)

- `pm` depends on: `cli`, `wss_surfaces`, `workflow_resolver`, `indexer`
- `tm` depends on: `cli`, `stack_viz`, `wss_surfaces`, `workflow_resolver`, `lifecycle`, `decompose`, `execute`, `validate`, `export`
- `decompose` depends on: `wss_surfaces`, `lifecycle`, `workflow_resolver`
- `execute` depends on: `wss_surfaces`, `lifecycle`, `workflow_resolver`
- `validate` depends on: `wss_surfaces`, `workflow_resolver`
- `export` depends on: `wss_surfaces`, `lifecycle`, `validate`

## Quick entry points

- User-facing behavior: `project_ticket_system/Lib__CLI_Shells.md`
- Automation behavior: `project_ticket_system/Lib__Ticket_Manager.md`
- Invariants: `project_ticket_system/Lib__Lifecycle.md`, `project_ticket_system/Lib__Task_Decomposition.md`, `project_ticket_system/Lib__Step_Execution.md`
