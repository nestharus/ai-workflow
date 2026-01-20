# AI-First IDE Platform (Consolidated Spec) [(=DOC-1)]

ID Conventions [(=DOC-ID-1)]
- Definition marker: `[(=ID)]`
- Unlabeled reference marker: `[@(+ID)]`
- Labeled reference marker: `[@(=ID)]`
- Prefixes (suggested):
  - Invariants: `INV-*`
  - Goals: `GOAL-*`
  - UX: `UX-*`
  - Objects / Concepts: `OBJ-*`, `CONCEPT-*`
  - Engine Semantics: `ENG-*`
  - Tools: `TOOL-*`
  - Policies: `POL-*`
  - Events: `EVT-*`
  - Boards: `BOARD-*`
  - Concerns: `CONCERN-*`
  - Gaps: `GAP-*`

---

## Problem Statement [(=SEC-PROBLEM-1)]

Observed Failure Mode [(=PROB-1)]
- Agent IDEs that:
  - assume planning methodology
  - hardcode integrations
  - take ownership of merge/conflict workflows
  - embed opinionated QA/self-validation behaviors  
  => become prescriptive, brittle, and organizationally risky.

Target Shape [(=PROB-2)]
- A neutral platform: workflow engine + task engine + event layer + extensible UI, with policies bounding risk.

---

## Scope & Responsibility Boundaries [(=SEC-SCOPE-1)]

In-Scope Platform Surface [(=SCOPE-1)]
- Workflow engine (execution + control)
- Ticket/task engine (types + states)
- Event layer (emit/subscribe/replay)
- User workspace (prompt runs + artifacts)
- Observability UI (logs, timelines, diffs, lineage)
- CLI UI surface
- Tool contracts (incl. integrations) + tool-defined UI objects
- Policy enforcement points (for tools/integrations)

Explicitly Out-of-Scope (Owned Externally) [(=SCOPE-2)]
- Planning frameworks beyond “ticket exists” [@(=INV-1)]
- Memory/knowledge base implementation (external tool) [@(=INV-2)]
- Hardcoded GitHub/GitLab/Linear integrations [@(=INV-3)]
- Automatic merging/conflict resolution [@(=INV-5)]
- Embedded self-validation QA frameworks (QA is workflow/tool-driven) [@(=INV-6)]
- “Agent work areas” / messaging strategies (tooling customization concern) [(=SCOPE-3)]

---

## Invariants [(=SEC-INVARIANTS-1)]

Planning Invariant [(=INV-1)]
- Planning surface supports agents writing tickets. That is it.
- No built-in planning methodology.
- Ticket schema and workflow lifecycles are user-defined.

Memory Invariant [(=INV-2)]
- Memory is an external tool.
- Platform does not own long-term memory systems.

Integration Invariant [(=INV-3)]
- No hardcoded integrations (GitHub/GitLab/Linear/etc.).
- Provide a common contract to interface with the IDE.
- Agents/users can build integrations against “anything” using that contract.
- Provide default scaffolds/buttons/templates for common integrations without privilege.

Policy Invariant [(=INV-4)]
- Risk across an org is managed via policies bounding tools/integrations.
- Tools/integrations must support policy enforcement hooks.

Worktree Invariant [(=INV-5)]
- Worktree management is supported.
- Merge is not owned by the platform; user/agent merges externally.
- Worktrees may close automatically when external merge occurs.

QA Invariant [(=INV-6)]
- No embedded “self-validation QA” opinions.
- Validation/QA is expressed as workflows and tools; workflows can be released separately as templates.

Neutrality Invariant [(=INV-7)]
- Platform provides capabilities (workflow engine + task engine + events + UI extensibility), not development prescriptions.

Extensibility Invariant [(=INV-8)]
- Tools can define new UI surfaces and first-class objects via contract + events.

---

## Goals [(=SEC-GOALS-1)]

Primary Goals [(=GOAL-GRP-1)]
- Build a workflow engine with strong visualization and control [@(+ENG-CORE-1)].
- Build a task manager (tickets) with user-defined types/states and board views [@(+BOARD-1)].
- Enable bespoke integrations via loose contracts + policies (no hardcoding) [@(=INV-3)] [@(=INV-4)].

Workflow + Execution Goals [(=GOAL-GRP-2)]
- Deep observability of running work: steps, logs, child workflows, lineage, diffs [@(+UX-OBS-1)].
- Human-in-the-loop review and input as first-class workflow steps [@(+UX-REVIEW-1)].
- Robust control for long-running and adaptive flows: pause/resume/skip/fork/branch/converge [@(+ENG-CTRL-1)].

Tooling Goals [(=GOAL-GRP-3)]
- AI tools are scripts; support tool creation, temporary tools, promotion/consolidation, governance [@(+TOOL-LC-1)].
- Recommend tools and workflow updates based on usage history (non-automatic) [@(+TOOL-REC-1)].

Collaboration Goals [(=GOAL-GRP-4)]
- Track cross-ticket and cross-board concerns to support multi-team coordination [@(+CONCERN-1)].

---

## Core Concepts & Object Model (Minimal) [(=SEC-OBJECTS-1)]

Ticket [(=OBJ-TICKET-1)]
- A user-defined schema instance representing work.

Ticket Type [(=OBJ-TICKETTYPE-1)]
- Defines fields, allowed states, transitions, and trigger bindings.

Workflow Definition [(=OBJ-WFDEF-1)]
- Declarative steps/graph (versioned) that consumes/produces events and artifacts.

Workflow Run [(=OBJ-WFRUN-1)]
- An execution instance bound to a ticket and an execution context.

Step Run [(=OBJ-STEPRUN-1)]
- A unit of execution with logs, tool invocations, agent attribution, artifacts, and events.

Artifact [(=OBJ-ARTIFACT-1)]
- Typed output/input (spec/code/image/video/etc.), versioned and diffable.

Tool (AI Tool / Integration) [(=OBJ-TOOL-1)]
- Scripted capability (may wrap external systems) governed by policies; can extend UI and objects [@(=INV-8)].

Workspace Session [(=OBJ-WS-1)]
- User-level container for prompt runs, temporary tools, and exploration artifacts.

Prompt Run [(=OBJ-PROMPTRUN-1)]
- Standalone managed execution producing artifacts/events; attachable to tickets or independent.

Concern [(=OBJ-CONCERN-1)]
- Cross-ticket/board impact signal; first-class collaboration object.

Event [(=OBJ-EVENT-1)]
- Common envelope for auditability, replay, subscriptions, and triggers.

GAP: Define canonical fields for each object’s identity/versioning [(=GAP-OBJ-1)]

---

## Event Layer & Observability [(=SEC-EVENTS-1)]

Event Layer Core [(=EVT-CORE-1)]
- Event-based underlying system; tools subscribe to events.
- Event sources:
  - user actions
  - agent actions
  - tool outputs (incl. CLI)
  - ticket state transitions [@(+BOARD-TRIG-1)]
  - external systems (via tool/integration)

Replay & Audit [(=EVT-AUDIT-1)]
- Ability to replay event streams and inspect workflows step-by-step.

Provenance & Lineage [(=EVT-LINEAGE-1)]
- Capture “why” an artifact exists: prompt/tool/workflow ancestry.

GAP: Define event schema (envelope + payload conventions) [(=GAP-EVT-1)]
GAP: Deterministic replay vs exploratory runs semantics [(=GAP-EVT-2)]
GAP: Cost/time accounting event fields (usage metering) [(=GAP-EVT-3)]

---

## Tickets, Boards, and State-Triggered Work [(=SEC-BOARDS-1)]

Boards as Views [(=BOARD-1)]
- Multiple board types supported.
- Boards visualize tickets; boards do not own execution.

State Transitions Emit Events [(=BOARD-TRIG-1)]
- Board-controlled ticket transitions emit state transition events.
- Workflows can be triggered by these events, scoped by ticket type.

Cross-Board Responsibility Model [(=BOARD-RESP-1)]
- Boards declare ownership/responsibility domains.
- Cross-board impacts raise concerns (not forced dependencies) [@(+CONCERN-RAISE-1)].

GAP: Define board type plug-in contract and required capabilities [(=GAP-BOARD-1)]
GAP: Define state machine model (per ticket type) and transition constraints [(=GAP-BOARD-2)]

---

## Workflow Engine Semantics [(=SEC-ENGINE-1)]

Workflow Engine Core [(=ENG-CORE-1)]
- Execute workflows bound to tickets and/or workspace contexts.
- Support workflow libraries (import/export) including tools [@(+UX-LIB-1)].

Workflow Authoring Lifecycle [(=ENG-AUTH-1)]
- Create / edit / delete workflows.
- Versioning: edits create new versions; running versions are immutable.

Per-Run Customization [(=ENG-CTRL-1)]
- Pause / resume
- Skip steps
- Wait on steps
- Fork: stop current run and continue with a customized or different workflow
- Branch/converge
- Rerun step with new inputs (partial re-execution)
- Rebind step (swap tool/agent mid-run)

Exception Handling & Repair Routing [(=ENG-EXC-1)]
- Exceptions routed to agents for:
  - repairing integrations
  - repairing workflows
- “Repair proposals” become artifacts and can be promoted to tools/workflow patches.

GAP: Define workflow graph/DSL representation and validation rules [(=GAP-ENG-1)]
GAP: Define convergence semantics + conflict handling for branches [(=GAP-ENG-2)]
GAP: Define exception taxonomy + routing matrix (human vs agent vs auto-fork) [(=GAP-ENG-3)]
GAP: Define running-workflow edit policy (patch vs fork vs restart) [(=GAP-ENG-4)]

---

## User Workspace & Arbitrary Prompt Runs [(=SEC-WORKSPACE-1)]

Workspace Core [(=WS-CORE-1)]
- Managed area for running arbitrary prompts and scripts with UI and history.
- Supports “prompt tasks” that are not tickets.

Prompt as First-Class Object [(=WS-PROMPT-1)]
- Named, versioned, parameterized prompts.
- Prompt runs emit events and produce artifacts [@(=OBJ-PROMPTRUN-1)].

Attachability [(=WS-ATTACH-1)]
- Prompt runs can be attached to:
  - a ticket [@(=OBJ-TICKET-1)]
  - a workflow run [@(=OBJ-WFRUN-1)]
  - or remain standalone within the workspace session [@(=OBJ-WS-1)].

GAP: Define workspace snapshot/fork semantics and retention policy [(=GAP-WS-1)]
GAP: Define prompt run UI primitives (inputs, outputs, artifacts, lineage) [(=GAP-WS-2)]

---

## File Explorer & Artifact Navigation [(=SEC-FILES-1)]

Explorer Core [(=UX-FILES-1)]
- Navigate project artifacts (repo + workspace artifacts).
- Reference:
  - files/folders
  - tickets [@(=OBJ-TICKET-1)]
  - workflows [@(=OBJ-WFDEF-1)]
  - workflow runs [@(=OBJ-WFRUN-1)]
- Execute workflows from arbitrary workspace locations.

Boundary Clarity [(=UX-FILES-2)]
- Explicit boundary between:
  - ephemeral workspace artifacts
  - persistent project artifacts

GAP: Define repo/workspace boundary rules + promotion path [(=GAP-FILES-1)]
GAP: Define reference model (symbolic IDs vs paths vs both) [(=GAP-FILES-2)]

---

## Execution UX (Tickets ↔ Workflows ↔ Steps) [(=SEC-UX-EXEC-1)]

Running Tickets View [(=UX-TICKETS-1)]
- Can see running tickets.
- Ticket list indicates execution status: idle/running/blocked/needs-input.

Ticket Detail: Workflow Inspection [(=UX-OBS-1)]
- Open a ticket to see executing workflows.
- Expand workflow to see steps and statuses.

Step Inspection Panel [(=UX-STEP-1)]
- Expand a step to see:
  - logs (CLI stdout/stderr and tool output)
  - timeline of child workflows
  - agent responsible for current step

Alerts & Input Requests [(=UX-ALERTS-1)]
- Alert notifications at top of UI.
- Click alert → open ticket/workflow/step requiring input.

GAP: Define default execution status model + transitions [(=GAP-UX-1)]
GAP: Define standard step log schema + streaming behavior [(=GAP-UX-2)]

---

## Artifacts, Diffs, and Review [(=SEC-UX-ARTIFACTS-1)]

Artifact Diffing [(=UX-DIFF-1)]
- View artifact diffs at:
  - step level
  - workflow level
  - ticket level

Human Review Step [(=UX-REVIEW-1)]
- Any workflow step can require human review of any artifact type.
- Review uses external tools (text/image/UI/video/etc.) for annotation and diffs.
- Annotations translate back into workflow-consumable feedback events.

Artifact Type Opinionation (User-Defined) [(=UX-ARTTYPES-1)]
- Users define artifact types they care about (specs, code, videos, art, chapters, memory snapshots, etc.).
- Tooling can provide specialized visualizations per artifact type.

GAP: Define artifact type registry and required metadata (diff/review/render hooks) [(=GAP-ART-1)]
GAP: Define annotation→feedback translation contract (schema + events) [(=GAP-ART-2)]

---

## Workflow Libraries [(=SEC-LIBS-1)]

Library Import/Export [(=UX-LIB-1)]
- Export/import workflow libraries that can include tools.
- Libraries contain:
  - workflow definitions (versioned)
  - tool definitions (versioned)
  - metadata and compatibility constraints

GAP: Define portability model (env vars, secrets, policies, tool deps) [(=GAP-LIB-1)]
GAP: Define library dependency resolution/version pinning [(=GAP-LIB-2)]

---

## Tools & Integrations (AI Tooling as Scripts) [(=SEC-TOOLS-1)]

Tool Lifecycle Core [(=TOOL-LC-1)]
- Control over AI tool usage (tools are typically scripts).
- Create tools (human or AI).
- AI can write temporary tools (workspace-scoped) and propose promotion/consolidation.

Tool States (Suggested) [(=TOOL-STATES-1)]
- Ephemeral → Candidate → Promoted → Deprecated/Superseded

Tool Governance Hooks [(=TOOL-GOV-1)]
- Permissioning, environment constraints, audit logging.
- Policy-bounded execution [@(=INV-4)].

Tool Discovery by Usage [(=TOOL-DISC-1)]
- Discover tools by tasks they have been used for in the past.
- Use this to recommend tools as accessible in workflows.

Tool Recommendation & Workflow Evolution [(=TOOL-REC-1)]
- Recommend:
  - tool inclusion in workflow steps
  - applying new tools across workflows (recommend-only)
  - updates to workflow steps to utilize tools

Integration Contract Requirement [(=TOOL-CONTRACT-1)]
- Common contract for integrations to interface with IDE.
- No privileged/hardcoded GitHub/GitLab/Linear support [@(=INV-3)].

GAP: Define tool contract (inputs/outputs, environment, UI extensions, event subs) [(=GAP-TOOL-1)]
GAP: Define promotion/consolidation workflow + approval rules (human/policy) [(=GAP-TOOL-2)]
GAP: Define recommendation signal model and explainability requirements [(=GAP-TOOL-3)]

---

## Policies [(=SEC-POLICIES-1)]

Policy Scope [(=POL-1)]
- Policies bound:
  - which tools can exist
  - which tools can run
  - where tools can run
  - what integrations can access
  - what UI extensions are allowed

Enforcement Points [(=POL-2)]
- Tool execution
- Integration contract calls
- Workflow triggers
- Artifact access
- External network access

GAP: Define policy language and evaluation model (static + runtime) [(=GAP-POL-1)]
GAP: Define audit/reporting UX for policy decisions [(=GAP-POL-2)]

---

## Cross-Ticket / Cross-Board Concern Tracking [(=SEC-CONCERNS-1)]

Concern as First-Class Object [(=CONCERN-1)]
- Track concerns across tickets/boards when work may impact other work.
- Supports team collaboration, multi-workflow collaboration, cross-team collaboration.

Concern Raising & Propagation [(=CONCERN-RAISE-1)]
- Concerns can be raised by:
  - workflow steps
  - tool outputs
  - ticket state changes
  - artifact diffs/changes
- Concerns attach to multiple tickets and boards.

Board/Ticket Surfacing [(=CONCERN-SURF-1)]
- Boards and tickets show linked concerns.
- Concerns are actionable signals, not forced dependencies.

GAP: Define concern severity taxonomy, routing, and notification policy [(=GAP-CONCERN-1)]
GAP: Define “impact detection” heuristics vs explicit declarations [(=GAP-CONCERN-2)]

---

## Extensible UI & First-Class Objects (Tool-Defined) [(=SEC-EXT-1)]

UI Extension Capability [(=EXT-UI-1)]
- Tools can define new UI panels/components and first-class objects.
- Extensions subscribe to events and publish events.

Discoverability [(=EXT-DISC-1)]
- Provide capability discovery surfaces so users can find and compose tools/workflows.

GAP: Define UI extension contract + sandboxing model [(=GAP-EXT-1)]
GAP: Define capability registry model (capabilities vs tools) [(=GAP-EXT-2)]

---

## Additional Expected AI-IDE Surfaces (Optional but High-Leverage) [(=SEC-ADD-1)]

Multi-Lens Views [(=ADD-VIEWS-1)]
- Ticket-centric, agent-centric, artifact-centric, event-centric, prompt-centric views.

Trust & Confidence Signals [(=ADD-TRUST-1)]
- Display:
  - validation coverage (workflow-driven)
  - human approvals
  - historical success indicators
  - tool reliability signals

Cost/Time Visibility [(=ADD-COST-1)]
- Cost per workflow/step/tool
- Wait time vs execution time

GAP: Define trust signal sources and UX presentation [(=GAP-ADD-1)]
GAP: Define cost attribution rules and quotas [(=GAP-ADD-2)]

---

## Gap Index (Rollup) [(=SEC-GAPS-1)]

Object Model
- Canonical identity/version fields [@(+GAP-OBJ-1)]

Events
- Event schema [@(+GAP-EVT-1)]
- Determinism/replay semantics [@(+GAP-EVT-2)]
- Metering fields [@(+GAP-EVT-3)]

Boards
- Board type contract [@(+GAP-BOARD-1)]
- Ticket type/state machine constraints [@(+GAP-BOARD-2)]

Engine
- Workflow DSL/graph [@(+GAP-ENG-1)]
- Branch/converge semantics [@(+GAP-ENG-2)]
- Exception taxonomy/routing [@(+GAP-ENG-3)]
- Running-workflow edit policy [@(+GAP-ENG-4)]

Workspace
- Workspace snapshot/fork [@(+GAP-WS-1)]
- Prompt run UI primitives [@(+GAP-WS-2)]

Files
- Repo/workspace boundary + promotion [@(+GAP-FILES-1)]
- Reference model (IDs vs paths) [@(+GAP-FILES-2)]

UX
- Execution status model [@(+GAP-UX-1)]
- Step log schema/streaming [@(+GAP-UX-2)]

Artifacts
- Artifact type registry [@(+GAP-ART-1)]
- Annotation→feedback contract [@(+GAP-ART-2)]

Libraries
- Portability model [@(+GAP-LIB-1)]
- Dependency/version pinning [@(+GAP-LIB-2)]

Tools
- Tool contract [@(+GAP-TOOL-1)]
- Promotion/consolidation workflow [@(+GAP-TOOL-2)]
- Recommendation signal model [@(+GAP-TOOL-3)]

Policies
- Policy language/eval model [@(+GAP-POL-1)]
- Policy audit UX [@(+GAP-POL-2)]

Concerns
- Severity/routing/notifications [@(+GAP-CONCERN-1)]
- Impact detection model [@(+GAP-CONCERN-2)]

Extensibility
- UI extension contract/sandbox [@(+GAP-EXT-1)]
- Capability registry [@(+GAP-EXT-2)]

Additional
- Trust signals [@(+GAP-ADD-1)]
- Cost attribution/quotas [@(+GAP-ADD-2)]

---

## Reference Notes [(=SEC-REFNOTES-1)]

Reference Type Reminder [(=REF-1)]
- Use `[@(+ID)]` for a lightweight pointer without semantic label.
- Use `[@(=ID)]` when you want to explicitly point at a labeled element such as an invariant header.

