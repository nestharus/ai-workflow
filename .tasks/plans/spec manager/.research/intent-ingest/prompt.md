# Research: Intent Ingest — User-Facing Intent Agent and Question Queue

## What I Need From You

Design the **intent ingest system** — a single user-facing agent (the
Intent Agent) that mediates ALL interaction between the user and the
spec manager pipeline. The user defines WHAT they want. The Intent Agent
works to understand their real intent, surfaces constraints and
tradeoffs as questions, translates between user language and system
language, and produces a HIGH-level skeleton with prose as the initial
deliverable. As the system works, internal agents signal questions back
through the Intent Agent to the user via a prioritized question queue.

This is the sixth research prompt. Research Prompts 1-5 designed the
planning module, QA eval architecture, scoring/multi-model comparison,
agent coordination, and constraint reasoning/architectural planning.
All are implemented or have responses. This prompt designs the user
interaction layer that sits above everything else — the alpha interface
that lets a user interact with a single agent for the entire process.

**Important**: We are describing the problem as we understand it. Our
framing may not be the right frame. The design constraints and tradeoffs
in context.zip define the principles — read them first, then determine
what the actual problem is before designing solutions.

---

## The Core Problem

The system has no coherent user interaction model. Currently:

- **Phase 0 intake** assumes the user hands over a complete prose spec
  upfront. It sectionizes, discovers libraries, routes content, checks
  coverage. But users don't arrive with complete specs — they arrive
  with intent: "I want a treasury management system" or "I need to add
  settlement processing to our existing platform."

- **Under-spec blocking** halts agents when they can't proceed, but
  questions are surfaced ad-hoc from deep inside the pipeline. There's
  no coherent queue, no deduplication, no reassessment when new
  information arrives.

- **The planner** reasons about constraints and makes decisions, but it
  has no channel to ask the user targeted questions about intent vs.
  constraints vs. tradeoffs. It blocks, but doesn't formulate the
  *right* question.

- **Research Prompt 5** (constraint reasoning) designed constraint
  lifecycle, decision authority, and question composition — but those
  questions have no delivery mechanism to the user, no queue management,
  and no way to reassess pending questions when answers arrive.

The missing piece: **a single agent that owns the user relationship**,
translates between user intent and system needs, and manages the flow
of questions and answers across the entire pipeline lifecycle.

---

## What the Intent Agent Must Do

### 1. Understand intent, not just capture spec text

The user says what they want in their own language. The Intent Agent's
first job is to understand the REAL problem:

- What is the user actually trying to accomplish?
- What domain are they in? What does that domain imply?
- What are they NOT saying that matters? (Implied constraints,
  assumed capabilities, unstated requirements)
- Is their framing the right framing? (The stated problem may not
  be the actual problem — Proportional Commitment applied to intake)

This is fundamentally different from Phase 0's current approach, which
takes complete prose and routes it. The Intent Agent must work WITH
the user to build understanding incrementally.

### 2. Ask the right questions at the right time

The Intent Agent doesn't dump a questionnaire on the user. It asks
targeted questions as they become relevant:

- **During initial intake**: "You mentioned settlement processing —
  does this handle real-time settlements or batch processing?"
- **When constraints surface**: "The planner discovered that your
  event-driven architecture implies eventual consistency. Is that
  acceptable for transaction records?"
- **When the problem gets redefined**: "Based on what we've
  learned, it seems like the core challenge is actually X, not Y.
  Does that match your understanding?"
- **When tradeoffs require human authority**: "Two approaches exist
  for risk calculation: approach A prioritizes accuracy but costs 2x
  in latency; approach B is faster but uses approximations. Which
  matters more for your use case?"

Questions come from the Intent Agent's own understanding AND from
signals bubbling up from internal agents (planner, implementors,
reviewers).

### 3. Manage a question queue with reassessment

Internal agents (planner, implementors, coordinators) signal questions
during execution. These questions are queued and managed:

- **Queued, not immediate**: Questions accumulate and are presented
  to the user one at a time, in priority order.
- **Reassessed on answer**: When the user answers one question,
  ALL pending questions are reassessed. Some may now be answerable
  (the answer implied a constraint that covers other questions).
  Some may become irrelevant (the answer changed the problem frame).
  Some may need rewording (the answer provides new context).
- **Deduplicated**: Multiple agents may ask equivalent questions
  from different angles. The Intent Agent recognizes these as the
  same underlying question and consolidates them.
- **Prioritized**: Questions that block the most work are asked first.
  Questions that are "nice to know" wait.

### 4. Translate between user language and system language

The user speaks in domain language ("I need ACID-compliant
transactions"). The system speaks in technical constraints and
tradeoffs. The Intent Agent bridges this:

- Translates user answers into constraints the planner can use
- Translates system questions into terms the user can understand
- Maintains a mapping between user concepts and system concepts
- Detects when the user and system are talking past each other

### 5. Produce the initial skeleton

The Intent Agent's output is NOT a complete spec. It is:

- **Constraints**: What must be true (explicit and discovered)
- **Patterns**: High-level structural patterns the system should follow
- **Tradeoffs**: Known tradeoff positions (with user confirmation)
- **A HIGH-level skeleton**: Functions with TODO comments describing
  what they do. This covers core workflows and any details that were
  specified. It deliberately does NOT try to capture everything — the
  system discovers details over time through implementation.

This skeleton is the input to the existing pipeline (Phase 0 can be
skipped or adapted — the Intent Agent has already done the work of
understanding and routing).

### 6. Continue mediating during implementation

The Intent Agent doesn't stop after producing the skeleton. As the
pipeline runs:

- Implementation agents signal when stuck → questions queued to user
- Planner discovers new constraints → Intent Agent validates with user
- Architecture proposals surface tradeoffs → user chooses via Intent Agent
- Problem gets redefined as understanding deepens → Intent Agent
  confirms new understanding with user

The Intent Agent IS the user's interface for the entire lifecycle.

---

## How This Relates to Existing Systems

### Phase 0 Intake

Phase 0 currently assumes complete prose input. With the Intent Agent:

- Phase 0 may receive PARTIAL input (just the skeleton from Intent Agent)
- Phase 0 may be SKIPPED if the Intent Agent directly produces the
  skeleton (the Intent Agent's understanding process IS the intake)
- Phase 0 may be PRESERVED for the case where users DO provide
  complete prose specs (backward compatibility)

The relationship between Intent Agent and Phase 0 needs clarification.

### Planner (Research Prompt 5: Constraint Reasoning)

Research Prompt 5 designed:
- Problem framing and translation (Step A)
- Constraint collection, enrichment, and flow (Steps B-C)
- Candidate generation and assessment (Steps D-E)
- Decision authority policy (Step F)
- Question composition (QuestionComposerStrategy)

The Intent Agent uses QuestionComposerStrategy's output but adds:
- Question queue management
- Reassessment on answer
- Deduplication across agents
- User-language translation

The Intent Agent doesn't replace the planner — it is the planner's
channel to the user.

### Coordination System (Research Prompt 4)

Research Prompt 4 designed:
- CoordinationSignals emitted by agents when stuck
- WorkItemStore for spec text search
- Monitors that wake agents when conditions are met
- WakeQueue and WaitGraph

The Intent Agent receives a new signal type: **questions for the user**.
These flow through the coordination system just like other signals,
but instead of being triaged by the planner, they're triaged by the
Intent Agent and routed to the user.

### Under-Spec System

Currently: `UnderSpecManager` hard-stops and the pipeline blocks.

With the Intent Agent: under-spec events become questions in the
Intent Agent's queue. The pipeline still blocks (agent enters WAITING
state via coordination system), but the question is formulated and
presented to the user through the Intent Agent, not as a raw blocking
event.

### Human Approval Loop (pdd_lifecycle)

Currently: `build_with_approval()` presents an overview document and
asks approve/feedback/quit.

With the Intent Agent: approval is one of many interactions. The Intent
Agent can present the overview AND pending questions in one coherent
interaction, maintaining context across the entire session.

---

## The Research Questions

### Q1: Intent Agent architecture

How should the Intent Agent be structured?

- Is it an LLM agent with a system prompt? A stateful orchestrator?
  A combination?
- What state does it maintain? (Conversation history, constraint
  map, concept translations, question queue, problem frame)
- How does it persist across sessions? (The user may leave and come
  back — the Intent Agent should resume context)
- How does it relate to the existing Planner? Is it a wrapper around
  the Planner? A peer? A layer above?
- How does it handle the distinction between its own questions
  (intent clarification) and forwarded questions (from internal agents)?

### Q2: Question queue design

How should the question queue work?

- **Priority model**: What determines question priority? (Number of
  blocked agents? Criticality of the blocked work? Time sensitivity?
  Question type — intent vs. constraint vs. tradeoff?)
- **Reassessment algorithm**: When an answer arrives, how does the
  system determine which pending questions are now answered, irrelevant,
  or need rewording? Is this an LLM call? Deterministic? Hybrid?
- **Deduplication**: How does the system recognize that two questions
  from different agents are asking the same thing? (Semantic similarity?
  Same underlying constraint? Same spec text reference?)
- **Batching**: Should related questions be presented together? ("These
  three questions are all about your consistency requirements — let me
  ask them together.")
- **Staleness**: How do questions expire? (If the pipeline moved on
  and the question is no longer blocking anything, remove it?)

### Q3: Signal flow from internal agents to Intent Agent

How do internal agent questions reach the Intent Agent?

- What signal type carries a user-facing question? Is it a new
  `CoordinationSignal` kind? A new signal type entirely?
- How does the planner's `QuestionComposerStrategy` output connect
  to the Intent Agent's queue?
- How do implementation agents signal questions? (They currently emit
  `UnderSpecEvent` — does this become a question signal?)
- How does the Intent Agent distinguish between questions it should
  ask immediately vs. queue vs. try to answer itself?

### Q4: Answer flow from user back to agents

When the user answers a question, how does the answer reach the
agent that asked it?

- How is the answer translated into a constraint or decision?
- How does it flow through the constraint store?
- How does it wake blocked agents? (Via WakeQueue? Monitor condition?)
- How are pending questions reassessed? (Separate LLM call? Part of
  the translation step?)
- What if the user's answer creates NEW questions? (Recursive
  discovery)

### Q5: Intent understanding vs. spec capture

How does the Intent Agent's understanding process work?

- Is it conversational? (Back-and-forth dialogue?)
- How does it decide when it has enough understanding to produce a
  skeleton? (Threshold? User says "go"? Both?)
- How does it handle vague input? ("Build me a trading platform"
  vs. "Build a treasury management system with settlement processing,
  risk management, and regulatory compliance")
- How much structure does it impose? (Does it ask about libraries?
  Components? Or does it stay at the intent level and let the system
  decompose?)
- How does it produce the skeleton? (LLM call with accumulated
  understanding? Incremental building? Phase 0 adaptation?)

### Q6: Problem redefinition loop

As the system works, understanding deepens. How does the Intent Agent
handle problem redefinition?

- The planner discovers that what the user called "settlement
  processing" is actually three distinct subsystems. How does the
  Intent Agent communicate this back?
- Implementation reveals that two user requirements conflict. How
  does the Intent Agent present this?
- The architecture proposal suggests a fundamentally different approach
  than what the user described. How does the Intent Agent bridge
  between user's mental model and system's recommendation?
- How do we prevent the problem from drifting too far from original
  intent? (Alignment check against original intent statement?)

### Q7: Session persistence and resumption

Users don't sit in one session forever. How does context persist?

- What is saved between sessions? (Full conversation? Distilled
  understanding? Constraint map? Question queue state?)
- How does the Intent Agent resume? (Summary prompt? Full replay?
  Checkpoint-based?)
- How does it handle the case where the pipeline made progress while
  the user was away? (New questions accumulated, some questions
  resolved by auto-mode research, problem understanding evolved)

### Q8: Relationship to Phase 0

What happens to the existing Phase 0 intake pipeline?

- **Option A**: Phase 0 is subsumed — the Intent Agent replaces it
  entirely. The Intent Agent directly produces skeletons.
- **Option B**: Phase 0 is preserved for prose input — the Intent Agent
  produces a prose spec that Phase 0 then processes.
- **Option C**: Phase 0 becomes a strategy within the Intent Agent —
  when the user provides complete prose, the Intent Agent delegates to
  Phase 0's algorithms internally.
- **Option D**: Something else?

### Q9: Skeleton format and depth

What does the Intent Agent's skeleton output look like?

- How deep? (Just top-level functions? Include internal structure?
  How much detail in TODO comments?)
- How is it different from Phase 0's library output?
- Does it include architecture? Or is architecture left for L2?
- How does it handle the user's primary concerns vs. details to
  discover later?
- What metadata accompanies the skeleton? (Constraints, tradeoffs,
  concept map, question history)

### Q10: Auto-mode behavior

In `--auto` mode (no human), how does the Intent Agent behave?

- Does it use the research team (Opus + GPT + GLM + firecrawl) to
  answer its own questions?
- How does it decide when it has enough understanding without a user?
- How does it handle questions that require human authority?
  (Skip? Block? Use research to make a best guess?)
- How does auto-mode intent understanding compare to human-guided?

---

## Constraints on the Solution

1. **Single interface**: The user talks to ONE agent. Not the planner,
   not the implementor, not the reviewer. One agent, one conversation.

2. **Questions, not questionnaires**: The Intent Agent asks questions
   one at a time (or in small related batches), not a 50-question form.
   Each answer may change what needs to be asked next.

3. **Constraints, not solutions**: When the Intent Agent asks about
   tradeoffs, it's seeking constraints ("prioritize latency over
   throughput"), not implementation decisions ("use Redis"). The user
   provides the WHAT and the boundaries; the system determines HOW.

4. **Proportional depth**: The Intent Agent doesn't try to capture
   everything upfront. It captures enough to produce a skeleton, then
   discovers the rest during implementation. Early questions are broad;
   later questions are specific.

5. **Information permanence**: User answers are constraints. They are
   persisted, not lost. They flow through the constraint lifecycle
   (Research Prompt 5). They have provenance.

6. **Existing infrastructure**: The coordination system (signals, work
   items, monitors, wake queue) already exists. The planner's constraint
   reasoning (problem framing, enrichment, decision authority) already
   exists. The Intent Agent connects to these — it doesn't rebuild them.

7. **Block on ambiguity**: When the system can't proceed and can't
   answer a question autonomously, it queues the question for the user.
   It doesn't guess. The cost of asking is low; the cost of a wrong
   assumption is high.

8. **Incremental delivery**: The skeleton is a starting point, not a
   final product. The system begins working immediately with what it
   has. Questions arrive as the system works, not before.

9. **LLM-only reasoning**: No formal questionnaire templates, no
   decision trees, no hardcoded question flows. The Intent Agent uses
   LLM inference to determine what to ask, when to ask, and how to
   translate.

10. **User answers may be partial or ambiguous**: The user might say
    "I'm not sure" or give a partial answer. The Intent Agent must
    handle this gracefully — record what was learned, note what remains
    unknown, continue with what it has.

---

## What Currently Exists

### Phase 0 Intake (`intake/`)

5-step routing pipeline for complete prose specs:
1. Summarize sources (LLM per file)
2. Discover libraries (LLM)
3. Route source spans to destinations (LLM + reimplementation test)
4. Coverage check (deterministic + LLM)
5. Assemble output (deterministic verbatim copy)

Output: libraries/ with analysis.md, constraints.md, detail files.
Works well for complete specs. Not designed for incremental input.

### Planner Constraint Reasoning (Research Prompt 5)

Planning session pipeline:
- Step A: Problem framing and translation
- Step B: Constraint collection
- Step C: Constraint enrichment
- Step D: Candidate generation
- Step E: Candidate assessment
- Step F: Decision authority
- Step G: Publish/propagate

Includes QuestionComposerStrategy for turning unknowns into
human-usable constraint prompts. Has no delivery mechanism.

### Coordination System (Research Prompt 4)

- `CoordinationSignal`: structured signal with SpecRef, FunctionRef,
  needs, local context, progress, search hints
- `WorkItemStore`: JSONL + index, 3-stage search (exact → fuzzy → LLM)
- `WakeQueue`: file-based wake events
- `WaitGraph`: cycle detection for wait dependencies
- `MonitorSpec`: declarative JSON DSL for condition checking
- `MonitorExecutor`: hybrid poll + event condition checking

### Under-Spec System

- `UnderSpecManager`: hard-stop blocking when ambiguity detected
- `ConstraintsStore`: workspace-level constraint storage
- `PlanningGate`: checks decision requirements against constraints
- 3-agent research pipeline for auto mode (opus → glm → chatgpt)

### Human Approval Loop

- `build_with_approval()` in pdd_lifecycle.py
- Overview document generation → user review → approve/feedback
- Auto/steering/interactive modes
- Max iterations guard

### PromotionLoop

10-step state machine per slice:
```
COLLECT → GAP → PLAN → IMPLEMENT → COORDINATE → ANALYZE → PROMOTE → INTEGRATE → VERIFY → ALIGN
```

Agents enter WAITING state (via coordination) when blocked.
Monitors wake them when conditions met.

---

## What Options Have Been Considered

### For Intent Agent architecture

**Option A: Conversational wrapper** — A stateful LLM agent that wraps
the entire pipeline. Maintains conversation history, constraint map,
question queue as state. Delegates to existing systems for execution.
- Pro: Simple model, natural user interaction, clear ownership
- Con: Context pressure from long conversations, state management complexity

**Option B: Event-driven mediator** — The Intent Agent reacts to events
(user input, agent signals, pipeline state changes). Processes events
through an intent model. Emits responses or new events.
- Pro: Clean separation, scales with pipeline complexity, testable
- Con: Feels mechanical to users, needs state reconstruction on each event

**Option C: Dual-mode agent** — Conversational during initial intake
(building understanding), then event-driven during execution (processing
signals and answers). Switches modes when skeleton is produced.
- Pro: Natural intake, efficient execution, mode matches the work
- Con: Mode transition complexity, two interaction models to maintain

### For question queue

**Option D: Priority queue with LLM reassessment** — Questions scored
by priority (blocked-agent count, work criticality). On each answer,
LLM reassesses all pending questions against new constraint state.
- Pro: Intelligent, handles cross-question dependencies
- Con: Expensive (LLM call per answer), potentially slow

**Option E: Constraint-keyed queue** — Each question is tagged with the
constraint dimension it addresses. When a constraint is answered, all
questions sharing that dimension are re-evaluated mechanically.
- Pro: Fast reassessment, clear structure
- Con: Requires accurate constraint tagging, misses cross-dimension dependencies

**Option F: Hybrid** — Mechanical check first (same constraint key?
same spec reference? same work item?), LLM reassessment only for
ambiguous cases.
- Pro: Fast common case, accurate edge cases
- Con: Two code paths

### For Phase 0 relationship

**Option G: Intent Agent replaces Phase 0** — The Intent Agent's
understanding process IS the intake. No separate Phase 0.
- Pro: No redundancy, user gets to shape the intake
- Con: Loses Phase 0's proven algorithms for complete specs

**Option H: Intent Agent wraps Phase 0** — For complete prose input,
the Intent Agent delegates to Phase 0 internally. For intent-based
input, it builds understanding directly.
- Pro: Preserves Phase 0, adds new capability
- Con: Two paths to maintain, potential divergence

---

## Deliverables

1. **Intent Agent architecture.** How the agent is structured, what
   state it maintains, how it persists, how it relates to the Planner
   and Pipeline. Input/output contracts. Interaction model (conversational
   vs. event-driven vs. hybrid).

2. **Question queue design.** Priority model, reassessment algorithm,
   deduplication strategy, batching rules, staleness handling. How
   questions flow from internal agents to the queue to the user.

3. **Signal flow.** How internal agent questions become Intent Agent
   queue items. Signal types, routing, translation. How the coordination
   system carries user-facing questions.

4. **Answer flow.** How user answers become constraints. How constraints
   flow through the store to blocked agents. How pending questions are
   reassessed. How wake events fire.

5. **Intent understanding algorithm.** How the Intent Agent builds
   understanding from vague user input. Conversational flow, question
   selection, when to produce skeleton, how deep to go.

6. **Skeleton format.** What the skeleton looks like. Depth, structure,
   metadata. How it feeds into the existing pipeline (Phase 0, L1, etc.)

7. **Problem redefinition protocol.** How the Intent Agent handles
   evolving understanding. Alignment checks against original intent.
   How it communicates shifts to the user.

8. **Phase 0 relationship.** How the Intent Agent relates to existing
   Phase 0 intake. Subsumption, wrapping, coexistence, or replacement.

9. **Session persistence.** What state is saved, how context resumes,
   how pipeline progress is communicated on resumption.

10. **Integration wiring.** Concrete changes to planner, coordination,
    under-spec, pdd_lifecycle, and intake modules to connect the
    Intent Agent. Files to create/modify. Migration path.

---

## Context Files (in context.zip)

### Design principles (READ FIRST)

- `design/constraints/00_PROPORTIONAL_COMMITMENT.md`
- `design/constraints/01_INFORMATION_PERMANENCE.md`
- `design/constraints/02_SOURCE_AUTHORITY.md`
- `design/constraints/03_ERROR_AMPLIFICATION.md`
- `design/constraints/04_COUPLING.md`
- `design/constraints/05_FRACTAL_SCOPING.md`
- `design/TRADEOFFS.md`
- `design/patterns/CORE_PATTERNS.md`

### Authoritative source documents

- `LONG_TERM_GOALS.md` — core design principles, QA methodology
- `WORKFLOW_ANALYSIS.md` — promotion model, pipeline architecture
- `simpler.md` — PDD lifecycle, iteration philosophy, user interaction
- `ALGORITHM.md` — evidence preservation, semantic framework
- `CURRENT_STATE_ASSESSMENT.md` — what exists, what works, what doesn't

### Research Prompt 5 response (constraint reasoning)

- `.research/constraint-reasoning/response.md` — constraint lifecycle,
  planning session pipeline, decision authority, question composition

### Research Prompt 4 response (agent coordination)

- `.research/agent-coordination/response.md` — signals, work items,
  monitors, wake queue, reactive planner

### Existing implementation

- `planner/api.py` — Planner + PlanningContext/Request/Result
- `planner/router.py` — LayerPlanner protocol + LayerRouter
- `planner/layers/l1.py` — L1Planner (code-as-spec + triage_signal)
- `planner/tools/constraints_tool.py` — constraint store adapter
- `orchestration/coordination/signals.py` — CoordinationSignal + types
- `orchestration/coordination/work_items.py` — WorkItemStore + search
- `orchestration/coordination/wake_queue.py` — WakeEvent + WakeQueue
- `orchestration/coordination/monitors.py` — MonitorSpec + MonitorRegistry
- `orchestration/under_spec/manager.py` — UnderSpecManager + ConstraintsStore
- `orchestration/pdd_lifecycle.py` — PddLifecycle + build_with_approval()
- `orchestration/promotion_loop.py` — 10-step state machine per slice
- `intake/summarize.py` — Phase 0 step 1
- `intake/discover.py` — Phase 0 step 2
- `intake/route.py` — Phase 0 step 3
- `intake/coverage.py` — Phase 0 step 4
- `intake/assemble.py` — Phase 0 step 5
