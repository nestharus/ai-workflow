# Tech Plan: Integration & File Structure (Index)

- **Doc**: Tech_Plan__Integration.md
- **Updated**: 2026-01-26
- **Component**: Repo layout + execution integration glue
- **Primary responsibility**: Define module boundaries, entrypoints, and how flows emit durable state/evidence with minimal user friction.

## What this file is

This is the index for the Integration spec suite. The original monolithic Integration spec has been broken into **library-aligned shards** under:

- `Tech_Plan__Integration/` (folder)

**Section numbering is preserved across shards** (Integration §1–§11), so cross-references like “Integration §9.2.4” remain valid.

## Global invariants

**Single source of truth for global invariants**:
- `Tech_Plan__Core_Infrastructure.md`

This Integration suite specifies integration deltas: entrypoints, module boundaries, sandbox wiring, and workflow definition integration.

## Library decomposition

The Integration spec naturally decomposes into the following libraries / packages (as defined by the target repo layout in Integration §10):

| Library / package | Code root(s) | Primary responsibility | Spec shard(s) |
|---|---|---|---|
| Integration overview | (cross-cutting) | Scope, terminology, and cross-shard conventions | [`01_Scope_and_Terminology.md`](Tech_Plan__Integration/01_Scope_and_Terminology.md) |
| `workflowctl` | `workflowctl/` | Stable automation surface (non-interactive CLI) | [`02_Entrypoints_and_CLI_Contract.md`](Tech_Plan__Integration/02_Entrypoints_and_CLI_Contract.md), [`03_Distribution_and_Repo_Init.md`](Tech_Plan__Integration/03_Distribution_and_Repo_Init.md) |
| Interactive CLI shims | `scripts/project_manager/`, `scripts/ticket_manager/` | Slash-command entrypoints that invoke `workflowctl` as a subprocess | [`02_Entrypoints_and_CLI_Contract.md`](Tech_Plan__Integration/02_Entrypoints_and_CLI_Contract.md) |
| Core runtime | `scripts/core/runtime/` | Bootstrap, repo discovery, root orchestration constraints | [`02_Entrypoints_and_CLI_Contract.md`](Tech_Plan__Integration/02_Entrypoints_and_CLI_Contract.md), [`05_Orchestration_Rules.md`](Tech_Plan__Integration/05_Orchestration_Rules.md) |
| Core durability contract | `scripts/core/protocol/`, `scripts/core/storage/` | Step/run docs + log shards + evidence emission | [`04_Step_Instrumentation_Contract.md`](Tech_Plan__Integration/04_Step_Instrumentation_Contract.md) |
| Patch-Stream integration | `scripts/core/vcs/`, Patch-Stream adapters | Mode A / Mode B patch authoring and application via jj-backed ticket stacks | [`06_Patch_Stream_Integration.md`](Tech_Plan__Integration/06_Patch_Stream_Integration.md) |
| Workflows | `scripts/core/workflows/` | Workflow precedence, schema v1, runner model, built-in catalog | [`07_Workflows__Surface_and_Schema_v1.md`](Tech_Plan__Integration/07_Workflows__Surface_and_Schema_v1.md), [`07_Workflows__Runner_Catalog_and_Capabilities_v1.md`](Tech_Plan__Integration/07_Workflows__Runner_Catalog_and_Capabilities_v1.md) |
| Gateway | `workflow_engine` (tool) | Single auditable gateway for tools/LLM/sandbox execution | [`08_Workflow_Engine_Gateway.md`](Tech_Plan__Integration/08_Workflow_Engine_Gateway.md) |
| Sandboxes | `scripts/core/sandbox/` | jj workspace-based sandbox lifecycle, sparse patterns, fallback ladder | [`09_Sandboxes__JJ_Workspaces.md`](Tech_Plan__Integration/09_Sandboxes__JJ_Workspaces.md) |
| Repo layout map | (repo root) | Target module boundary map used by implementers | [`10_Repo_Code_Layout_Target.md`](Tech_Plan__Integration/10_Repo_Code_Layout_Target.md) |
| Integration risk register | (cross-cutting) | Residual risks + controls | [`11_Integration_Risk_Register.md`](Tech_Plan__Integration/11_Integration_Risk_Register.md) |

## Shard index by Integration section

| Integration section | Where it lives now |
|---|---|
| §1 Scope + terminology | `Tech_Plan__Integration/01_Scope_and_Terminology.md` |
| §2 Entry points | `Tech_Plan__Integration/02_Entrypoints_and_CLI_Contract.md` |
| §3 Distribution + repo init | `Tech_Plan__Integration/03_Distribution_and_Repo_Init.md` |
| §4 Step instrumentation | `Tech_Plan__Integration/04_Step_Instrumentation_Contract.md` |
| §5 Flat orchestration rule | `Tech_Plan__Integration/05_Orchestration_Rules.md` |
| §6 Patch-Stream integration | `Tech_Plan__Integration/06_Patch_Stream_Integration.md` |
| §7 Workflows | `Tech_Plan__Integration/07_Workflows__Surface_and_Schema_v1.md` and `Tech_Plan__Integration/07_Workflows__Runner_Catalog_and_Capabilities_v1.md` |
| §8 `workflow_engine` gateway | `Tech_Plan__Integration/08_Workflow_Engine_Gateway.md` |
| §9 Sandboxes | `Tech_Plan__Integration/09_Sandboxes__JJ_Workspaces.md` |
| §10 Repo code layout | `Tech_Plan__Integration/10_Repo_Code_Layout_Target.md` |
| §11 Risk register | `Tech_Plan__Integration/11_Integration_Risk_Register.md` |

## Notes on cross-references

- References of the form **“Integration §X.Y”** refer to the section numbering preserved across these shards.
- Other referenced docs (e.g., `Tech_Plan__Configuration_&_Onboarding.md`, `Tech_Plan__Built-in_Workflow_Definitions.md`) remain external dependencies and are unchanged.
