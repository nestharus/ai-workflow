# Tech Plan: Integration — Scope & Terminology

* **Doc**: Tech_Plan__Integration/01_Scope_and_Terminology.md
* **Updated**: 2026-01-26
* **Shard**: Integration §1–§1.1
* **Libraries / packages**: `scripts/core/*` (cross-cutting)
* **Depends on**: `Tech_Plan__Core_Infrastructure.md` (global invariants)

## 1) Scope

This file defines how the runtime integrates with developer workflows and the codebase layout after migrating to:

* WSS (durable docs + artifacts)
* sharded JSONL logs (durable evidence)
* notifications + control actions queues (durable control plane)
* Patch-Stream (jj-backed ticket stacks)
* sandboxes (ephemeral tool execution)
* schema-validated user workflows (file-defined)
* a single auditable tool gateway (`workflow_engine`) for agents

**Single source of truth for global invariants**:
* Tech_Plan__Core_Infrastructure.md

This file specifies integration deltas: entrypoints, module boundaries, sandbox wiring, and workflow definition integration.

## 1.1 Terminology (WSS vs sandbox)

To avoid ambiguity:

* **WSS (Workspace State Store)**: the durable state store directory under the runtime root
  * Path example: `~/.workflow/repos/<repo_uid>/workspace/` (directory name is `workspace/`)
  * In text, always call this **WSS** or **WSS root** (never "workspace" unqualified).

* **Sandbox**: an ephemeral environment used for tool execution (Integration §9).
  * In this system, a sandbox is implemented as a **jj workspace** created under the repo runtime root.

* **jj workspace**: the Jujutsu term for a working copy created by `jj workspace add`.
  * When referencing jj documentation, we keep the term "jj workspace"; otherwise we say "sandbox".

### 1.1.1 Linter Rule Specification

**Rule name**: `TERMINO001` - Bare "workspace" usage

**Description**: Flag bare "workspace" tokens except in the following allowed contexts:

1. When preceded by `"jj "` (Jujutsu tool references)
2. When followed by `"/"` (file path contexts)
3. When part of the phrases "Workspace State Store" or "WSS"

**Pattern**: Standalone word `"workspace"` (case-insensitive, word boundary) is a violation unless:
* Preceded by `jj\s+` (e.g., "jj workspace", "jj workspace add")
* Followed by the path separator `\/` (e.g., "workspace/", "workspace/README.md")
* Inside "Workspace State Store" or its abbreviation "WSS"

**Implementation notes**:
* Use regex negative lookbehind/lookahead to detect violations
* File extension scope: `.md` files only
* Severity: `warn` (allows for documentation while flagging potential terminology drift)
* Linter should be categorized under documentation/spec linting

**Reference**: See TERMINOLOGY_RULES.md for full rule documentation and enforcement wiring into CI pipeline.
