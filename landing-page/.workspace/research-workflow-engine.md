# Workflow Engine: Value Proposition Research

**Source docs analyzed:**
- `Epic_Brief__Multi-Layered_Project_Management_System.md`
- `Core_Flows__Project_Management_&_Autonomous_Monitoring.md`
- `Tech_Plan__Configuration_&_Onboarding.md`

---

## 1. What the Workflow Engine IS (User Perspective)

The Workflow Engine is a **local-first command-line tool that manages AI-driven coding work from start to finish**. It sits between the user and their AI coding assistant (Claude Code, Cursor, OpenCode, Windsurf, etc.) and provides structure, visibility, and safety around the work AI agents do.

From a user's perspective, it does three things:

1. **Organizes work into projects, tickets, and tasks** -- like a personal project management system that lives on your machine, not in a SaaS app.
2. **Runs AI agents through structured workflows** -- instead of one long chat session that can go off the rails, work is broken into small, verifiable steps where each step produces a concrete, inspectable patch.
3. **Watches over AI execution and intervenes when things go wrong** -- an autonomous monitoring system detects when the AI is stuck, looping, or drifting, then pauses it, investigates, and either fixes the problem or tells you exactly what happened and what to do.

The mental model for users: **You describe what you want. The engine breaks it into steps. AI executes each step. You can see everything that happened. If something goes wrong, the engine catches it before it spirals.**

### The Problems It Solves (in user-recognizable language)

These map directly to pain points vibe coders already experience:

| What users experience | What's actually happening | How the engine fixes it |
|---|---|---|
| "It worked yesterday, today it went rogue" | Context drift and contamination across long sessions | Each step gets a clean, bounded context with only the files it needs |
| "I've been waiting an hour and it's still running" | Opaque execution -- no visibility into what the AI is doing | Every step produces durable evidence; you can always see exactly what's happening |
| "The AI keeps rewriting things I told it not to touch" | No enforced boundaries on what AI can modify | Each step has explicit "allowed write paths" -- the AI literally cannot edit files outside its scope |
| "I keep going in circles trying to fix the same bug" | No detection of repetitive failure patterns | The monitoring system detects repeated signatures and oscillation, then stops and investigates instead of burning tokens |
| "I lost all my progress when the session crashed" | No durable state -- everything lives in ephemeral chat context | All state is written to disk as it happens; crash-recovery is built in |
| "I can't get the AI to do this complex refactor in one shot" | Planning/execution split -- chat can't maintain intent across many steps | The engine decomposes work into a step plan, then executes each step while preserving the original intent |

---

## 2. The UX Vision

### How Users Interact

The daily workflow is:

1. **Start a project**: Run `/project-manager`, import your planning docs (paste markdown or give a file path).
2. **Pick a ticket**: Select what to work on; the engine suggests ordering and dependencies.
3. **Run the ticket**: Run `/ticket-manager --project <id> --ticket <id>`, paste a task description.
4. **Approve the plan**: The engine decomposes your task into steps and shows you the plan. You approve, edit, or replace it.
5. **Watch it execute**: Each step runs, produces a patch, and gets validated. You can see every step's evidence.
6. **Validate and close**: When all steps are done, the engine validates everything in a sandbox. If it passes, you close the ticket and export the changes.

If something goes wrong at any point: **the engine pauses, investigates, and either auto-repairs or gives you a clear notification with the exact commands to continue.**

### What Makes It Different From Existing Tools

**vs. Long chat sessions (current AI coding)**:
- Chat sessions are ephemeral and fragile. The Workflow Engine gives every step durable state that survives crashes, restarts, and context loss.
- Chat has no "undo" or "replay." The engine keeps every patch on a stack -- you can inspect, revert, or rebuild from any point.

**vs. Project management tools (Linear, Jira)**:
- Those tools plan but don't execute. The Workflow Engine carries intent from planning all the way through implementation.
- No external service required. No account signup. Runs locally.

**vs. Heavy workflow engines (Airflow, Temporal)**:
- Those require databases, daemons, and ops expertise. This requires nothing -- one binary, no services, no ports.
- Those aren't designed for LLM-specific failure modes (context drift, hallucination, rogue edits). This one is.

### The "Never Babysit" Promise

The key UX differentiator is: **you can walk away.** The autonomous monitoring loop watches for problems and handles them:

- No heartbeat from the agent? Pause and investigate.
- Same error signature repeating? Stop the loop and escalate.
- Agent trying to write outside its allowed paths? Blocked at the gateway.
- Step ran for too long with no progress? Pause, analyze bounded evidence, and either repair or notify.

The system has **no fixed timeout kill switches**. It never silently terminates work. It either fixes the problem or tells you exactly what happened with pointers to all the evidence.

---

## 3. Key Capabilities for Vibe Coders

### Custom Workflows

**What it is**: Workflows are YAML files that define how work gets done -- what steps to run, which AI agent handles each step, what to do if something fails. They are plain text files you can read, edit, share, and version control.

**Why vibe coders care**: You can define your own coding process. Instead of "hoping the AI does the right thing," you can specify:
- "First, analyze the codebase. Then, plan the changes. Then, implement. Then, validate."
- Different workflows for different tasks (bug fixes vs. new features vs. refactors).
- Your own failure handling ("if the AI fails at this step, try a different approach instead of stopping").

**Key detail**: Workflows are files in your project that you can commit and share with your team. The engine validates them before running. Every workflow run produces the same quality of evidence as built-in workflows -- there is no second-class citizen distinction between custom and built-in.

**Precedence system**: Workflows can exist at multiple levels (project, repo-local, machine-global, built-in) with clear precedence rules. Teams share workflows via the repo; individuals customize locally.

### Model Selection and Configuration

**What it is**: The engine routes different tasks to different AI models based on what each model is good at. You can configure which models handle which kinds of work.

**Why vibe coders care**: Instead of being locked into one AI model for everything, you can use:
- A fast, cheap model for simple formatting and refactoring tasks
- A strong reasoning model for architecture decisions and code review
- A specialized model for long checklist verification
- A multimodal model when screenshots or UI work is involved

**Key detail**: Model routing is configured via TOML files, not hardcoded. API keys are stored in the OS keychain (not in plain text config files). You can add, remove, and test providers with simple commands:
```
workflowctl providers add <name>
workflowctl providers test <name>
```

**Current model routing guidance from the spec:**
| Task type | Suggested model |
|---|---|
| Signal selection, classification | GLM 4.7 |
| Deterministic gruntwork, refactors | MiniMax M2.1 |
| Audits, edge-case reasoning | ChatGPT 5.2 |
| Multimodal interpretation | Gemini 3 |
| Architecture, pattern detection | Opus 4.5 |

### Visibility and Transparency

**What it is**: Every action the engine takes produces durable, inspectable evidence. Logs, patches, decisions, rationale -- all written to disk in structured formats.

**Why vibe coders care**: You can always answer these questions:
- "What did the AI actually do?" -- Every step produces a patch diff and metadata explaining what changed and why.
- "Why did it make that decision?" -- Decomposition rationale, approval records, and deviation logs are all persisted.
- "What went wrong?" -- Investigation bundles, failure signatures, and validation reports point to exactly what broke.
- "What's happening right now?" -- Real-time notifications, progress signals, and heartbeat monitoring.

**Key detail**: The evidence system is append-only JSONL logs with integrity chaining -- evidence cannot be silently modified or deleted after the fact. This is "trust" as the system's #1 priority, above everything else including performance.

The system also provides:
- `workflowctl notifications tail` -- watch what's happening live
- `workflowctl fsck` -- integrity checks on all stored state
- `workflowctl recover` -- deterministic crash recovery

### Error Recovery

**What it is**: A multi-layered system for handling failures gracefully, from automatic retries to autonomous investigation to user-guided repair.

**Why vibe coders care**: When AI coding goes wrong (and it will), the engine does not just throw an error and stop. The recovery chain is:

1. **Automatic detection**: The monitoring thread spots the problem (repeated errors, no progress, timeout, scope violation).
2. **Controlled pause**: The engine requests a pause; the running step must acknowledge. No silent kills.
3. **Bounded investigation**: An investigator agent analyzes only the relevant evidence (last N events, heartbeat status, the failure context) and classifies the problem.
4. **Auto-repair if possible**: If the investigator says it's fixable, a repair agent generates a patch, validates it in a sandbox, and resumes.
5. **Clear escalation if not**: If auto-repair can't fix it, you get a notification with:
   - Exact commands to continue
   - Paths to all relevant evidence
   - The investigator's analysis of what went wrong
   - Recommended next action

**Key detail**: The system remembers failure patterns. A "Conclusions Store" tracks known failures and known remedies. When a pattern repeats, the system can apply the known remedy instead of re-investigating from scratch.

**User unblock path**: You can always edit the step plan directly, approve a manual fix, or create a follow-up task from a validation failure. The system never locks you out.

### Autonomous Monitoring

**What it is**: A monitoring thread that runs alongside AI execution and watches for problems proactively.

**Why vibe coders care**: This is the "never babysit" feature. Anomalies the monitor detects:
- Missing heartbeats (agent might be hung)
- Repeated failure signatures (stuck in a loop)
- No-progress tool runs (doing work that produces nothing)
- Queue and journal anomalies (infrastructure problems)
- Oscillation (alternating between two states without converging)

**Key detail**: Time is "a signal, not the decision." The monitor doesn't kill things after a fixed timeout. It uses time as one input among many to decide whether something is actually stuck. This prevents premature termination of legitimately long-running work while still catching genuine hangs.

---

## 4. The "VS Code for the AI Era" Positioning

### What Extensibility Means Here

The analogy to VS Code is about three things:

**1. Workflows as the extension model**

Just as VS Code has extensions that define behavior, the Workflow Engine has workflow YAML files. They are:
- Plain text files you can read, write, and understand
- Shareable via version control (team workflows live in the repo)
- Composable (steps form a DAG, can depend on each other)
- Validated by schema (the engine catches errors before running)
- First-class (custom workflows get the same evidence, monitoring, and recovery as built-ins)

**2. Agent prompts as configurable intelligence**

Just as VS Code lets extensions bring their own logic, the Workflow Engine lets you define agent prompts as Markdown files that control what the AI does:
- Purpose and constraints
- Required inputs and outputs (typed)
- Tool access (capability-gated -- agents only get the tools their step declares)
- Searchable and testable: `workflowctl agents validate`, `workflowctl agents test`

**3. One skill teaches the AI everything**

The engine deploys a single "workflow-manager" skill into whatever AI coding CLI you use. This skill teaches the agent how to write workflows, configure the engine, create agents, and run everything. When you say "write me a workflow that validates code," the agent knows how because the skill taught it. This is the self-bootstrapping model: the tool teaches the AI how to extend the tool.

### The Extensibility Spectrum

| What you want to customize | How you do it |
|---|---|
| Which models handle which tasks | Edit config TOML or use `workflowctl config set` |
| How work gets decomposed, executed, validated | Write or edit workflow YAML files |
| What the AI agents know and how they behave | Write or edit agent prompt Markdown files |
| Team-wide standards vs. personal preferences | Project-level files (committed) vs. machine-local files |
| Failure handling behavior | `on_failure` policies in workflow steps: stop, pause, investigate, continue |

---

## 5. Deployment Models

### Local (Free, Power Users)

**What it means for users**: Everything runs on your machine. One binary (`workflowctl`), no services, no database, no daemon. All state lives in `~/.workflow/` on your filesystem.

**Key characteristics**:
- Complete privacy: code never leaves your machine unless you explicitly call an external AI API
- Zero project pollution by default: nothing written to your repo unless you opt in with `--project`
- You bring your own AI API keys (stored in OS keychain, not config files)
- Cross-platform: Linux, macOS, Windows, WSL
- No account, no signup, no credit card
- Full customization: write your own workflows, agents, model routing
- Crash recovery via `fsck` and `recover` commands

**Trade-off**: You manage your own API keys, model configuration, and dependencies. The `doctor` and `bootstrap` commands help, but you're the operator.

### Hybrid ($15/mo, Recommended)

**What it means for users**: A remote control plane handles coordination, monitoring, and model routing, while actual code execution still happens locally on your machine.

**Key characteristics**:
- Your code stays local (privacy preserved for the execution layer)
- Remote handles the "infrastructure tax": model routing optimization, API key management, monitoring intelligence
- You still bring your own AI API keys (but the remote layer can help manage them)
- Easier setup than full local -- less configuration burden

**Trade-off**: Monthly cost, but less operational overhead. Good middle ground for people who want the privacy of local execution without having to manage all the infrastructure themselves.

### Fully Remote (Easiest, Most Expensive, Future)

**What it means for users**: Everything runs in the cloud. Easiest possible setup -- sign up and start working.

**Key characteristics**:
- No local setup required beyond authenticating
- Managed model routing, monitoring, and execution
- Company policy enforcement (for teams)
- Highest convenience, lowest friction

**Trade-off**: Code is processed remotely. Higher cost. Less privacy control. Best for teams that prioritize convenience and are comfortable with cloud-hosted code processing.

### Deployment Model Summary for Landing Page

| | Local | Hybrid | Remote |
|---|---|---|---|
| **Price** | Free | $15/mo | TBD (higher) |
| **Setup** | One binary + your API keys | One binary + account | Account only |
| **Code privacy** | Complete | Execution is local | Cloud-processed |
| **Model management** | You configure | Assisted | Managed |
| **Monitoring** | Local | Remote-enhanced | Remote |
| **Best for** | Privacy-first power users | Most users | Teams wanting zero ops |
| **Available** | Prototype now | Future | Future |

---

## 6. Messaging Angles for Vibe Coders

Based on the problems the docs identify and the capabilities described, here are the strongest messaging angles for people who use AI to code but aren't deeply technical:

### "Stop babysitting your AI"
The autonomous monitoring + investigation + repair loop means you can kick off work and walk away. The engine watches over the AI and either fixes problems or tells you exactly what to do. No more staring at a spinner for an hour wondering if it's stuck.

### "Every change is inspectable"
Unlike a chat session where everything blends together, the engine produces a discrete patch for every step. You can see what changed, why it changed, and revert any step independently. No more "it broke something but I don't know what."

### "Your AI can't go rogue"
Each step runs in a bounded context with explicit allowed-write-paths. The AI literally cannot modify files outside its scope. Gateway capability checks enforce this. No more "the AI rewrote my database migration while fixing a CSS bug."

### "Works with the tools you already use"
Integrates with Claude Code, OpenCode, Cursor, Windsurf. Doesn't replace your AI -- it manages your AI. One skill teaches your existing AI assistant how to use structured workflows.

### "Your process, your rules"
Workflows are YAML files. Agent prompts are Markdown files. You define how work gets done, which models handle what, what happens on failure. The engine validates and runs your definitions with the same quality guarantees as built-in workflows.

### "Crash-proof by design"
Every decision, patch, and piece of evidence is written to disk as it happens. Power goes out? Session crashes? `workflowctl recover` picks up exactly where you left off. No lost work, no re-doing hours of AI computation.
