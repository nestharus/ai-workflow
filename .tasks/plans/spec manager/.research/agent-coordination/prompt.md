# Research: Agent Coordination, Reactive Planner & JIT Monitors

## What I Need From You

Design the **agent coordination system** — how parallel agents (one per library slice) implement from spec, signal when stuck, and get unblocked by a **reactive planner** that triages signals and schedules **JIT monitor scripts** to wake agents when conditions are met.

This is the fourth research prompt. Research Prompts 1-3 designed the planning module, QA eval architecture, and scoring/multi-model comparison. All are implemented. This prompt redesigns how the planner interacts with implementing agents, replacing the current pre-planning approach with a reactive model.

---

## The Core Problem

The current PromotionLoop runs steps in this order:
```
COLLECT_BASELINE → GAP_EXPLORATION → PLAN → IMPLEMENT → UNDER_SPEC → ...
```

**This is wrong for L1.** The PDD skeletons (Python files with spec comments) ARE the plan. Each spec comment like `# Schema validation rejects instructions with invalid currency codes` above a stub function IS the implementation instruction. Running a planner before implementation is redundant — the agent should implement directly from the spec comments.

The planner should only engage **reactively** — when an agent halts because it can't proceed.

---

## Design Requirements

### 1. Agents implement directly from spec comments

For L1 (code-as-spec), agents receive:
- A set of Python skeleton files with spec comments and stub functions
- Each stub function has one or more spec comments describing what it should do
- The agent's job: fill in the function bodies based on the spec comments

No pre-planning step. The spec comments ARE the plan. The PLAN step for L1 should be skipped (or become a no-op).

### 2. Agents halt with signals when stuck

When an agent cannot implement a function because it needs something external:
- Missing interface from another library (e.g., needs `TransactionValidator.validate_schema` signature but that's in another agent's slice)
- Ambiguous spec comment (the comment doesn't say enough)
- Conflicting requirements between spec comments

The agent halts and emits a **signal** describing what it needs. The signal references the spec text.

### 3. Planner is a reactive triage authority

When the planner receives a signal from a halted agent, it:

1. **Searches work items by spec text** — work items routed to agents are direct spec text. The planner searches across all work items to find if the needed work already exists and is assigned to another agent.

2. **If found in work items** — the dependency exists and is being worked on. Schedule a monitor to wake the halted agent when that work completes.

3. **If spec exists but is unrouted** — the spec text exists but hasn't been assigned to any agent. Route it to the appropriate agent, then schedule a monitor.

4. **If not in spec at all** — genuine underspecification. The planner expands the spec (creates new work), routes it, and schedules a monitor.

**In all cases**, the planner schedules a JIT monitor. The agent doesn't "wait" — it stops. The monitor wakes it when the condition is met.

### 4. Work items = spec text

Work items are direct text from the spec. This is the universal coordination key:
- To find dependencies: text search across work items
- To match what an agent needs against what other agents are working on
- No explicit dependency graph needed — the spec text IS the graph

### 5. JIT monitor scripts

The planner writes a monitor script for each halted agent. The monitor:
- Is an arbitrary condition-checking script written by the planner
- Executes periodically or on events (e.g., when an agent commits)
- When the condition is met, wakes the halted agent
- Is cleaned up after the agent resumes

The planner can write different scripts for different situations:
- "Check if file X in shared branch has function Y defined" (waiting on another agent's output)
- "Check if work item W is marked complete" (waiting on work item completion)
- "Check if spec expansion for topic T has been routed" (waiting on new spec)

### 6. Agent lifecycle with git branches

Each agent works in its own branch (slice worktree):
- Agent implements from spec comments in its branch
- Agent commits progress to its branch
- Agent merges to shared branch when work is ready
- Other agents can see committed work on the shared branch
- Monitors can check the shared branch for conditions

---

## Specific Questions

### Q1: How should signals be structured?

When an agent halts, what does the signal look like? It needs to carry:
- What the agent needs (description)
- Why it's stuck (classification: missing interface, ambiguous spec, conflict)
- Reference to the spec text that triggered the need
- The agent's partial progress (what it implemented before getting stuck)

Should signals be structured data (JSON)? Free-text with metadata? How does the signal carry enough information for the planner to triage without being overly rigid?

### Q2: How does spec text search work for dependency matching?

Work items are spec text. When an agent says "I need the TransactionValidator interface," the planner needs to find the work item that covers TransactionValidator.

- Is this fuzzy text matching? Exact substring match? LLM-based semantic search?
- How are work items indexed for search?
- How do you handle the case where the spec text for what's needed is worded differently from the work item? (e.g., agent needs "validation interface" but work item says "schema validation rejects instructions with invalid currency codes")
- What happens when multiple work items partially match?

### Q3: What is the JIT monitor script format?

The planner writes arbitrary condition scripts. Questions:

- **Language/format**: Are these Python scripts? Shell scripts? A DSL? JSON condition expressions?
- **Execution model**: Polling (run every N seconds)? Event-driven (trigger on git push/commit)? Hybrid?
- **Scope**: What can the scripts access? Git branch state? File contents? Work item status? Agent status?
- **Safety**: What constraints prevent a monitor script from doing something destructive?
- **Lifecycle**: How are monitors registered, tracked, and cleaned up?
- **Failure handling**: What if the monitor script itself fails? What if the condition is never met?

### Q4: How does "wake agent" work mechanically?

When a monitor's condition is met:
- How is the agent process actually restarted/resumed?
- What state does the agent need to resume from? (Its previous context, the signal resolution, new information from the shared branch)
- Does the agent re-run from scratch or continue from where it stopped?
- How does the agent receive the new information that unblocked it?

### Q5: How does this interact with the existing PromotionLoop?

The PromotionLoop currently runs 10 steps sequentially per slice. With reactive planning:
- The PLAN step for L1 becomes a no-op (spec comments are the plan)
- IMPLEMENT runs first and may halt with signals
- The planner engages reactively on signals
- The loop may pause (agent stops) and resume (monitor wakes agent)

How does this change the loop's step sequence? Does the loop gain a new WAIT/RESUME state? Do we need to modify the convergence logic?

### Q6: How do parallel agents coordinate via the shared branch?

Multiple agents work simultaneously in their own branches:
- Agent A (LIB-01: Settlement Processing) needs Agent B's (LIB-02: Risk Management) `RiskEngine.check_exposure` interface
- Agent A halts, planner schedules monitor checking for `check_exposure` in shared branch
- Agent B eventually implements `check_exposure` and merges to shared branch
- Monitor fires, Agent A wakes up with the interface available

Questions:
- How does merging to the shared branch work? Is there a merge order? Conflict resolution?
- How does an agent "pull" new information from the shared branch after waking?
- What if Agent B's implementation changes the interface Agent A expected?
- How do we prevent circular dependencies (A needs B, B needs A)?

### Q7: How does the planner decide between "already specified," "needs routing," and "underspecified"?

The planner's triage logic:
1. Search work items → found? Wait on it.
2. Search full spec → found but unrouted? Route it.
3. Not found → underspecified → expand spec.

How does step 2 work? How does the planner distinguish between:
- Spec text that SHOULD have been routed but wasn't (routing gap)
- Spec text that's related but doesn't actually cover what's needed (partial coverage)
- Genuinely missing spec (needs expansion)

This requires understanding the spec deeply. Should the planner use an LLM for this classification?

### Q8: How does spec expansion work?

When the planner determines something is underspecified:
- What does "expand the spec" mean mechanically? Add new spec comments to skeleton files? Create new work items?
- Who validates the expansion? (The planner generates new spec — but is the generated spec correct?)
- How does expansion feed back into the pipeline? (New spec → new work item → routed to agent → monitored)
- How do we prevent spec expansion from diverging from the original intent?

---

## What Currently Exists

### PromotionLoop (`orchestration/promotion_loop.py`)

10-step state machine per slice:
```
COLLECT_BASELINE → GAP_EXPLORATION → PLAN → IMPLEMENT → UNDER_SPEC_CHECK
→ ANALYZE → PROMOTE → INTEGRATE → VERIFY → ALIGN
```

- `SliceRef`: (slice_id, layer, library_id, worktree_path)
- `SliceContext`: (slice_id, slice_root, layer, run_id, mode, workspace_root)
- `EvidenceBundle`: per-iteration state with manifest, diff, gaps, plan, implementation, gates
- Steps dispatch by layer (L1/L2/L3)
- The loop iterates until gaps are closed or max iterations reached

### PddLifecycle (`orchestration/pdd_lifecycle.py`)

L1→L2→L3 layer orchestrator:
- `_discover_slices(layer)`: finds work units per layer
  - L1: one slice per library (from `libraries/` dir)
  - L2: one slice per component (from component manifest)
  - L3: one slice per file
- `_run_slices_at_layer(layer)`: creates PromotionLoop + scheduler, runs all slices
- `PromotionScheduler`: ThreadPoolExecutor bounded parallel execution

### Planner (`planner/api.py`)

Current planner is a **pre-planner** (generates plans before implementation):
- `Planner.plan_from_gaps(ctx, gaps)` → list of intentions
- Routes through `LayerRouter` → L1Planner / L2Planner / L3Planner
- Uses tools: ResearchTool, IntegrationTool, ConstraintsTool, EvidenceTool
- Produces `PlannerTrace` with decision records
- **This needs to become reactive** — engage on signals, not pre-plan

### Under-Spec System (`orchestration/under_spec/`)

Current under-spec handling:
- `UnderSpecManager`: hard-stop blocking when ambiguity detected
- `ConstraintsStore`: workspace-level constraint storage
- `PlanningGate`: checks decision requirements against constraints before implementation
- `UnderSpecCheckStep`: 3-agent research pipeline (opus → glm → chatgpt)
- **This is close to the signal system** — but it runs after implementation, not during

### WorktreeManager (`orchestration/worktree_manager.py`)

Git-based parallel execution:
- Creates per-layer worktrees (dirty, clean lanes)
- Creates per-slice grandchild worktrees for parallel implementation
- `create_slice_worktree(layer, slice_id)` → full git worktree
- `merge_slice_to_dirty(layer, slice_id)` → merge completed slice
- `tick_pipeline(active_layer)` → promote clean→dirty, run CI
- **This is the git infrastructure** for agent branches

### ImplementationRunner (`orchestration/implementation/runner.py`)

L1 implementation:
- `run_for_slice(slice_root, iteration_dir, plan_intentions, gap_report)` → RunResult
- Sends code + spec comments + intentions to LLM agent
- Agent fills function bodies
- Produces: patch, applied edits, pin proposals, edge proposals, under_spec_events
- **under_spec_events** are the existing signal mechanism — but they're produced after the fact, not as real-time halts

### Gap Evidence (`core/gap.py`)

What gap exploration finds:
- `GapEvidence`: invariant_family, description, location, detector, details
- Families: `executable_comment` (spec comment), `executable_stub` (stub function)
- Each gap is a spec comment + stub pair = one implementation task

---

## Design Constraints

All design must comply with established principles:

1. **No language-specific parsing** — LLM only, no AST parsers
2. **Routing over extraction** — route work, don't extract data
3. **Code IS the spec** — PDD skeletons are simultaneously spec and code
4. **Promotion, not direct editing** — changes flow through promotion system
5. **Graph operations, not code operations** — operate on relationships
6. **Dynamic structures over rigid types** — language-agnostic
7. **LLM does work during its actual task** — no redundant mechanical steps
8. **Block on ambiguity** — surface the question, don't guess

Additional constraints for this design:

9. **Spec text is the universal key** — work items, dependencies, and coordination all reference spec text directly
10. **Agents are decoupled from coordination** — agents implement and halt; they don't know about monitors, other agents, or the planner's triage logic
11. **Planner writes monitors, doesn't poll** — the planner schedules monitors and moves on; it doesn't sit in a loop checking status
12. **Git branches are the communication channel** — agents share work by merging to shared branch; monitors check branch state

---

## Deliverables

1. **Signal format and emission protocol** — how agents signal what they need when stuck
2. **Planner triage algorithm** — search work items → classify → route/expand → schedule monitor
3. **Spec text search mechanism** — how to find matching work items from signal text
4. **JIT monitor script system** — format, execution model, lifecycle, safety
5. **Agent wake-up protocol** — how monitors wake agents, what state is restored
6. **PromotionLoop modifications** — new step sequence for L1, WAIT/RESUME state
7. **Shared branch coordination** — merge protocol, pull protocol, circular dependency prevention
8. **Spec expansion mechanism** — how the planner creates new spec when underspecified
9. **Integration with existing systems** — how this fits with WorktreeManager, ImplementationRunner, UnderSpecManager, Planner
10. **Implementation plan** — concrete steps, files to create/modify, migration from current pre-planning to reactive model

---

## Context Files (in context.zip)

- `promotion_loop.py` — PromotionLoop 10-step state machine, all step classes, SliceRef/SliceContext
- `pdd_lifecycle.py` — PddLifecycle L1→L2→L3 orchestrator, _discover_slices, _run_slices_at_layer
- `planner/api.py` — Planner class, PlanningContext/Request/Result, plan_from_gaps
- `planner/router.py` — LayerPlanner protocol, LayerRouter, CapabilityRouter
- `planner/layers/l1.py` — L1Planner (code-as-spec discovery + function intentions)
- `under_spec/manager.py` — UnderSpecManager, ConstraintsStore, hard-stop blocking
- `under_spec/planning_gate.py` — PlanningGate, pre-implementation constraint check
- `implementation/runner.py` — ImplementationRunner, RunResult, under_spec_events
- `implementation/types.py` — RunResult, AppliedEdit, PinProposal, UnderSpecEvent
- `worktree_manager.py` — WorktreeManager, per-layer/per-slice worktrees, merge, tick_pipeline
- `promotion_scheduler.py` — PromotionScheduler, ThreadPoolExecutor bounded parallel
- `evidence.py` — EvidenceBundle, Finding, all Ref sub-types
- `core/gap.py` — Gap, GapEvidence, GapType, invariant families
- `WORKFLOW_ANALYSIS.md` — Target state for promotion model, worktree design
- `LONG_TERM_GOALS.md` — QA methodology, design principles
- `agent_coordination_design.md` — Design notes from the QA session that triggered this prompt
