# Epic Brief: Multi-Layered Project Management System (Restructured)

- **Doc**: Epic_Brief__Multi-Layered_Project_Management_System.md
- **Updated**: 2026-01-24
- **Audience**: Developers using a local-first CLI prototype; AI agents implementing and operating it.
- **Status**: Living spec (prototype). Defaults optimize **trust** (durability + correctness + privacy) and **low friction**, with **performance third**.

## 0) Problem definition and user context

### 0.1 Primary users (supported)
This system is designed for:

A. **Solo developers** managing complex, multi-step changes who need better organization than git branches.

B. **Small teams (2–5 devs)** who want local-first project management without relying on external services.

C. **Developers building AI-assisted workflows** who need auditable, evidence-based execution and reproducibility.

D. **Teams that want patch-stack development** (jj/Pijul-style) integrated directly into project management.

### 0.2 The concrete problems this solves
Developers using “AI coding assistants” hit recurring failure modes that current tooling does not address:

- **Drift and context contamination**
  - repeated attempts diverge from intent (“it worked yesterday, today it went rogue”)
  - sub-agent / multi-agent setups contaminate shared context and produce inconsistent outcomes
- **Opaque execution**
  - long-running tasks provide no durable “what is happening?” signal
  - users see only “still running” for hours; cancellation loses the investigation context
- **Rogue behavior despite state files**
  - even with “state files”, agents can ignore or overwrite constraints
  - the user must babysit execution because there is no durable evidence, no enforced pause, and no bounded tool surface
- **Workflow sprawl**
  - ad-hoc scripts and commands proliferate with no standards
  - worktree-based approaches are expensive (full repo copies) and encourage fragmentation
- **Model/tooling friction**
  - vendor lock-in and token pressure encourage over-reliance on a single model
  - API key management and per-token billing add friction; provider CLIs are preferred when available
  - other models have different strengths; switching models without observability increases risk
- **Planning/execution split**
  - planning tools capture intent, but execution tools do not preserve that intent through implementation
  - “workflow engines” that could coordinate execution are usually too heavy (databases/daemons/configuration) for local-first use

### 0.3 Why existing solutions are insufficient (by category)

#### Planning tools (Linear, Jira, GitHub Projects)
- Great for **planning and coordination**, but they are not execution substrates:
  - no durable per-step evidence stream for AI-driven implementation
  - no pause/investigate/repair control plane
  - no constrained tool surface for agents (capability-gated execution)
  - no patch-stack semantics tied to ticket state

#### Plain git branches/worktrees
- Branches help humans coordinate changes, but do not solve:
  - evidence durability for “why” and “how” a change was produced
  - step-level pause/resume and deterministic recovery
  - reducing worktree sprawl (repo copies) when parallelizing via automation

#### Heavy workflow engines
- Many require **services** (DBs, daemons, schedulers) or complex ops:
  - too much installation and runtime friction for local developer machines
  - not designed around LLM-specific failure modes (context drift, bounded evidence, auditable tool calls)

### 0.4 Typical environment and workflow assumptions
- Repo size: small to very large; must work without copying the repo repeatedly.
- Change shape: many small patches across many files (refactors, migrations, feature work).
- Execution: local CLI; users frequently run tests/linters/build tools.
- Team size: 1–5 developers is the design center; workflows must still be shareable.
- Constraints: low-friction installs; no required database/services; cross-platform (Linux/macOS/Windows/WSL).


## 0.1 Glossary (terminology)

**This glossary is normative**. When these terms appear in specs, they MUST be used with the meanings below.

- **WSS (Workspace State Store)**: The durable on-disk state store under:
  - `~/.workflow/repos/<repo_uid>/workspace/`
  - Contains tickets, tasks, runs, logs, and artifacts. (Core Infrastructure §2)
- **jj workspace**: A Jujutsu (jj) working copy concept (VCS term). Not the same as WSS.
- **sandbox**: An ephemeral execution environment implemented as a **jj workspace** created under:
  - `~/.workflow/repos/<repo_uid>/sandboxes/<sandbox_id>/`
  - Used for safe validation/execution and destroyed by GC. (Integration §9, Core Infrastructure §11.4)
- **repo root**: The user’s git/jj repository path being managed.
- **runtime root**: `~/.workflow/repos/<repo_uid>/` (the per-repo runtime directory).

The term **“workspace”** MUST be qualified as either **WSS**, **jj workspace**, or **sandbox** (do not use unqualified “workspace” in new text).

## 1) Product priorities (decision order)

1. **Trust**
   - durable state + evidence survives crashes (within platform tiers)
   - correctness is auditable (ID-driven evidence; no hidden mutable state)
   - privacy is explicit (network policy + secret scanning + scrubbed exports)
   - *Accuracy is pass/fail*: if the system produces incorrect patches or misreports state, it is considered failed.

2. **Friction**
   - no database service, no always-on daemon requirement
   - minimal installs (auto-bootstrap where possible)
   - user-defined workflows are editable files (project-defined and shareable)

3. **Performance**
   - optimize where it does not threaten trust or add user burden

## 2) Success criteria and measurable outcomes

### 2.1 “Working correctly” (hard requirements)
A run is considered correct only if:

- every step emits durable evidence (WSS + logs) sufficient to reconstruct what happened
- patch application is validated (hunk-lint) and ticket completion is blocked on required sandbox validation
- pause/resume works reliably: steps ACK pause and stop tool subprocesses at safe boundaries
- recovery is deterministic:
  - `fsck` can detect corruption / partial writes
  - `recover` can restore a coherent state or fail loudly with evidence pointers

### 2.2 UX success signals (prototype-appropriate)
Even though accuracy is pass/fail, the prototype should still be measurable:

**Trust signals**
- crash-recovery drills succeed on representative repos (simulated kill -9 / power loss where feasible)
- “share bundle” exports scrub secrets and include a manifest of what was redacted
- no silent termination criteria (no fixed iteration caps; no “timeout = kill without investigation”)

**Friction signals**
- user can get to first useful run with:
  - one install action, and
  - one per-repo init action
- no required external services (Postgres/Redis/etc.)
- dependency drift is handled by `doctor` + `bootstrap` with clear instructions

**Performance signals (secondary)**
- interactive operations feel responsive (e.g., listing tickets/projects, showing run status)
- hydration and sandbox creation stay within practical budgets for local iteration

### 2.3 What “good enough” means for this phase
- CLI-first prototype (Project Manager, Ticket Manager, workflowctl)
- no full GUI application requirement
- no feature cuts for “MVP”; iteration focuses on correctness, evidence, and UX friction

## 3) Scope and boundaries

### 3.1 In scope (prototype)
- local-first CLI UX for project/ticket/task execution
- durable evidence primitives: WSS + sharded JSONL logs + filesystem queues
- Patch-Stream development model: **Ticket = patch stack**, **Step = patch production**
- mandatory pause/resume control plane + investigate/repair loop
- workflow customization: users can define their own workflows as files and run them through the engine
- no required integrations with external planning tools (docs are imported by paste/file path)

### 3.2 Explicitly out of scope (prototype)
- hosted SaaS UI or multi-user server (see “Future iterations”)
- distributed execution across multiple machines
- required integrations with Linear/Jira/GitHub (optional later)
- default embedding/vector search (optional later)
- making Windows-native durability identical to POSIX (Windows is supported, but with tiered guarantees)

### 3.3 Relationship to existing tools
- **Git**: the system operates inside an existing git repo, but does not require the git CLI for core flows.
- **jj**: the default Patch Graph Store backend; can be auto-bootstrapped for low friction.
- **Planning tools**: Linear/Jira/etc. may still be used upstream, but this system treats them as *inputs*, not dependencies.

## 4) User journey and entry points

### 4.1 Install and onboarding (low friction)
Supported install modes (pick one):

- **Single self-contained executable** per platform (preferred distribution).
- **Remote bootstrap script** that downloads the pinned executable and sets up PATH.
- **Python package** installation for workflow authors (library use), while still running workflows via the engine.

First-run per repo:
1. `workflowctl init` asks user which CLI they use (Claude Code, OpenCode, Cursor, etc.)
2. `init` launches that CLI with a bootstrap prompt
3. Agent installs the workflow-manager skill (`workflowctl install --cli <name>`)
4. Agent now knows how to configure everything (from the skill), and proceeds to:
   - Set up model providers (API keys in OS keychain)
   - Configure default workflows
5. `workflowctl doctor` (checks dependencies + writes a durable doctor report)
6. Optional: `workflowctl bootstrap` (installs pinned `jj` locally when allowed)

**Self-bootstrapping**: The agent installs the skill first, then uses that skill to know how to do everything else.

**Key principle**: Zero project pollution by default. All state lives in `~/.workflow/`. Project-level config (`<repo>/.workflow/`) requires explicit `--project` flag.

See **Tech_Plan__Configuration_&_Onboarding.md** for full onboarding flow and CLI integration.

### 4.2 Daily use (default path)
1. User runs `/project-manager`
2. Import planning docs (paste/file path)
3. Select a ticket and run `/ticket-manager --project <id> --ticket <id>`
4. Paste task input → decomposition → approve step plan → execute
5. Validate in sandbox; close ticket (export stack) only when validation passes
6. If stuck: pause → investigate → repair → resume (no babysitting required)

### 4.3 User-defined workflows and agents (customization)
- **Workflows**: Users can define workflows as YAML files (repo-shared or machine-local), validated by schema.
- **Agents**: Users can define agent prompts as markdown files (for the workflow engine).
- **Skill**: One skill (`workflow-manager`) is deployed into the user's AI coding CLI to teach the agent how to write workflows, configure the system, etc.
- Workflows and agents follow the same precedence: project → repo-local → installation → built-in.
- Workflows run through the same gateway and evidence protocols as built-ins.
- Customization is expected and supported as part of normal usage, not an "advanced mode".

See **Tech_Plan__Configuration_&_Onboarding.md §3-4** for skill deployment and CLI integration.

## 5) System shape (components → responsibilities)

This system intentionally collapses “architecture + algorithms + evidence” into one navigable layer:

- **Components** isolate algorithms, state usage, and responsibilities.
- **Flows** are user-facing responsibilities expressed as step sequences across components.
- **Evidence** (WSS + logs) is the durable truth; everything else is derived.

### 5.1 Core components (authoritative boundaries)

| Component | Primary responsibility | Durable state used |
|---|---|---|
| **Runtime Root** | Flat orchestration (spawn/stop/pause), run lifecycle, recovery | `workspace/runs/*`, queues, journals |
| **Workspace State Store (WSS)** | Durable documents + artifacts | `workspace/**` |
| **Logs Store** | Append-only execution evidence (integrity chained) | `logs/runs/<run_id>/writers/*.jsonl` |
| **Queues (Maildir-like)** | Notifications + control actions | `notifications/**`, `control_actions/**` |
| **PGS Adapter (jj)** | Patch-Stream ticket stacks + patch application + hydration | jj repo + WSS ticket metadata |
| **Sandbox Runner** | Tool execution in isolated hydrated view | `sandboxes/**` (ephemeral) |
| **Workflow Registry + Runner** | Load/validate/execute built-in and user-defined workflows | workflow YAML + run artifacts |
| **Agent Registry** | Load/resolve agent prompts with precedence | agent markdown files |
| **Secrets + Privacy Layer** | Key storage, redaction, export scrubbing, network policy | OS keychain + scrub manifests |
| **workflow_engine Gateway** | Single auditable execution surface for agents | logs + capability checks |

### 5.2 Product-facing components

| Component | Primary responsibility | Output |
|---|---|---|
| **Project Manager (CLI)** | Project selection, doc import, ticket ordering, QA notifications | `workspace/projects/**`, derived index |
| **Ticket Manager (CLI)** | Task creation, decomposition, step execution, validation, close/export | `workspace/tickets/**`, runs, patches |

### 5.3 Autonomy components

| Component | Primary responsibility | Output |
|---|---|---|
| **Monitoring Thread (in-process)** | Detect anomalies via progress signals, trigger pause/investigate | control actions + notifications |
| **Investigator** | Bounded evidence analysis + classification + resume plan | investigation bundle + conclusion updates |
| **Repair Agent** | Produce patch fix + validate + resume/retry | patch on stack + provenance artifacts |
| **Conclusions Store** | “Known failure / known remedy” memory with promotion | `workspace/conclusions/**` |

## 6) Top-level flows (UX responsibilities)

### Flow A — Plan → Execute → Validate → Export (per ticket)
1. Import planning docs (project/ticket).
2. Create/open ticket stack (Patch-Stream).
3. Create a task; decompose into steps; user may edit/approve step plan.
4. Execute steps sequentially; each step produces a patch.
5. Validate in sandbox (required at ticket close).
6. Export (squash or linear) and mark done.

### Flow B — Observe → Pause → Investigate → Repair → Resume
1. Monitor detects anomaly (time is a signal, not the decision).
2. Root requests PAUSE; step must ACK promptly.
3. Investigator analyzes bounded evidence; returns classification.
4. If fixable: repair agent creates patch + validates in sandbox.
5. Root resumes/retries; if not fixable: notify user with concrete instructions.

### Flow C — Integrate baseline changes (Enhanced Rebase)
1. Rebase ticket stack onto new baseline via jj pointer move.
2. Treat conflicts as resolver jobs with evidence gathering.
3. Persist conflict resolution records to prevent repeated confusion.

### Flow D — Define/override workflows (user customization)
1. User edits workflow files (repo-shared or machine-local).
2. Engine validates schema and required capabilities.
3. Workflows become selectable for decomposition, execution, validation, and repair.
4. All workflow runs produce the same durable evidence as built-ins.

### Flow E — Onboard and configure (first-run, self-bootstrapping)
1. User runs `workflowctl init` in a repo.
2. `init` creates `~/.workflow/repos/<repo_uid>/`.
3. `init` asks: "Which CLI do you use?" (Claude Code, OpenCode, Cursor, Windsurf).
4. `init` launches that CLI with a bootstrap prompt.
5. Agent runs `workflowctl install --cli <name>` to install the workflow-manager skill.
6. Agent now has the skill and uses it to configure model providers, default workflows, etc.
7. Optionally, user runs with `--project` flag to create project-level overrides.

## 7) Global invariants (non-negotiable)
Global invariants and data shapes are defined in:
- **Tech_Plan__Core_Infrastructure.md**

Key reminders:
- Local-only, single machine; no required ports or services.
- Durable truth = WSS docs + JSONL logs + patch stacks (PGS/jj).
- Step logging always on; optional per-step tracing.
- Flat orchestration: root owns step/agent processes (no grandchildren).
- PAUSE is mandatory; steps enforce it internally and ACK.
- No fixed “max iteration” termination criteria. Use progress signatures, novelty requirements, oscillation detection, and explicit give-up records.

## 8) Selected defaults (tradeoffs aligned with priorities)

### Selected defaults
- **Patch-Stream (jj) under the hood**:
  - patch stacks are superior for organizing “many small steps” and parallel ticket work
  - complexity cost is acceptable because users do not interact with the patch graph directly
- **Loud failures** over silent “helpful guessing”
- **No heavy dependencies**: file-backed durability primitives, no DB required
- **Workflows are configurable**: avoid hardcoding planning into the tool; support user-defined workflows as files

### Optional features (user-enabled)
- embedding-based semantic search for large doc corpuses
- copy-based sandboxes as fallback on constrained filesystems (guarded by quotas)
- hosted/semi-hosted runtime modes (future)

## 9) System risk register (residual risks + controls)

| Risk | Why it matters | Default controls |
|---|---|---|
| Context drift / rogue agent behavior | produces incorrect or irreproducible changes | gateway allowlist + bounded inputs + durable evidence + pause/investigate loop |
| Exfiltration / privacy | code + secrets may be exposed to remote models | network policy modes + secret scanning + scrubbed exports |
| Hydration/sandbox performance on huge repos | can make iteration sluggish | Mode A preferred; Mode B fallback; quotas; bench harness |
| Platform durability differences | crash/power-loss semantics vary | tiered durability + journals + `fsck`/`recover` |
| Evidence bloat | large logs/artifacts consume disk | sharded logs + retention + GC refusing when active |
| Concurrency hazards | multiple sessions edit same docs | ownership + optimistic concurrency (`expected_rev`) |

## 10) Model routing (implementation guidance)
Model selection is a means; correctness and auditability must not depend on model quirks.

- **GLM 4.7**: signal selection; summarize what matters; classify anomalies.
- **MiniMax M2.1**: deterministic gruntwork (tool runs, refactors, “do exactly this” tasks).
- **ChatGPT 5.2**: audits, long checklists, edge-case reasoning, synthesis.
- **Gemini 3**: multimodal interpretation (UI/screens/terminal captures).
- **Opus 4.5**: architecture proposals; cross-document pattern detection; gap discovery.

## 11) Future iterations (explicitly not required for this prototype)
These are intentionally documented so planners do not repeatedly re-open scope:

- **Semi-hosted / fully hosted modes**
  - individuals: semi-hosted control plane with local file execution
  - companies: hosted execution + policy enforcement
- **External integrations**
  - Linear/Jira/GitHub sync instead of “paste docs”
- **Richer UI**
  - terminal UI, desktop app, or web app on top of the same evidence primitives
- **Better test selection**
  - symbol → test reverse dependency mapping
- **Stronger Windows-native guarantees**
  - narrow remaining semantic gaps vs POSIX tiers

## 12) Source references (core choices)
- JJ workspaces and sparse patterns:
  - https://docs.jj-vcs.dev/latest/working-copy/
- ULID monotonic generation:
  - https://github.com/ulid/spec#monotonicity
- Windows atomic replacement guidance:
  - ReplaceFile: https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilea
