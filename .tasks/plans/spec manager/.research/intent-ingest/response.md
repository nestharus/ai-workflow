## 1) Intent Agent architecture

### 1.1 Role and boundaries

**Intent Agent** is the *only* user-facing agent. Everything else stays internal.

It owns:

* Understanding and reframing what the user is trying to accomplish
* Eliciting constraints and tradeoff preferences as **questions**
* Translating user language ⇄ system language (constraints, decisions, scope)
* Maintaining a **prioritized question queue** with dedup + reassessment
* Producing the **initial skeleton** (code-as-spec + prose)
* Mediating all later interaction: under-spec, tradeoffs, approvals, problem redefinitions

It does **not** own:

* Architectural decisions beyond what the authority policy allows
* Implementation details (libraries, infrastructure choices) unless the user explicitly constrains them
* Running slices or coordination (it consumes signals; it doesn’t schedule workers)

### 1.2 High-level structure

A **stateful orchestrator** + **LLM subcalls** (no monolithic “just prompt it”).

**Core components**

1. **IntentAgentOrchestrator (deterministic)**

   * Loads/persists session state
   * Reads incoming internal question signals
   * Maintains queue and selects what to ask next
   * Routes user messages to:

     * *intent ingest* vs *answer handling* vs *freeform refinement*

2. **LLM strategies (pluggable)**

   * `IntentFrameStrategy`: derive/update a structured problem frame from user text
   * `UnknownsStrategy`: generate/refresh candidate unknowns to ask about (proportional depth)
   * `QuestionRewriteStrategy`: turn system questions into user-facing questions
   * `AnswerTranslateStrategy`: map user answers into constraints + decisions + concept map updates
   * `QueueReassessStrategy`: decide which pending questions are now answered/irrelevant/need rewording
   * `SkeletonSynthesisStrategy`: generate skeleton artifacts + TODOs referencing open unknowns
   * `RedefinitionDetectStrategy`: detect meaningful drift between original intent and evolving plan

3. **State stores (file-backed, append-only where it matters)**

   * `IntentSessionStore` (snapshot JSON)
   * `IntentEventLog` (append-only JSONL: user messages, internal signals, answers, queue mutations)
   * `QuestionQueueStore` (snapshot + optional JSONL mutations)

This avoids “context pressure” and supports session resumption cleanly.

### 1.3 Intent Agent state model

Persisted state (minimal + sufficient; derived views can be recomputed):

```json
{
  "run_id": "run_2026_02_13_001",
  "session_id": "intent_sess_...",
  "phase": "INTAKE|EXECUTION",
  "original_intent": {
    "user_statement": "I want ...",
    "captured_at": "..."
  },
  "problem_frame": {
    "current_restatement": "...",
    "goals": ["..."],
    "non_goals": ["..."],
    "domain_markers": ["..."],
    "scope": { "in": ["..."], "out": ["..."] },
    "success_metrics": ["..."],
    "risk_flags": ["security", "money_movement", "compliance"],
    "assumptions": [
      { "text": "...", "status": "HYPOTHESIS|CONFIRMED|REJECTED", "provenance": "llm|user" }
    ]
  },
  "concept_map": {
    "user_terms": {
      "settlement processing": { "maps_to": ["SettlementOrchestrator", "LedgerPosting", "Reconciliation"], "confidence": 0.7 }
    },
    "system_terms": {
      "ACID": { "maps_to_user_phrases": ["strong consistency", "transactional writes"] }
    }
  },
  "constraints": {
    "authoritative": [
      { "constraint_id": "c_...", "key": "consistency.ledger", "question": "...", "answer": "...", "source": "user", "scope": "system|slice", "provenance": {...} }
    ],
    "hypotheses": [
      { "key": "throughput.target", "hypothesis": "...", "confidence": 0.4, "source": "llm" }
    ]
  },
  "tradeoff_positions": [
    { "axis": "consistency_vs_availability", "position": "prefer_consistency", "source": "user" }
  ],
  "skeleton": {
    "current_revision": 2,
    "artifacts": ["system/intent.md", "libraries/.../*.py"],
    "open_todos": ["q_..."]
  },
  "question_queue": {
    "open_ids": ["q_..."],
    "closed_ids": ["q_..."],
    "items_by_id": { "...": { /* see Q2 */ } }
  }
}
```

### 1.4 Persistence and resumption

**Persistence** is explicit and durable:

* Snapshot: `.pdd_runs/<run_id>/intent/session_state.json`
* Append-only log: `.pdd_runs/<run_id>/intent/events.jsonl`
* Queue snapshot: `.pdd_runs/<run_id>/intent/question_queue.json`
* Answers: `.pdd_runs/<run_id>/intent/answers.jsonl`

On resume, the agent loads snapshot, replays any new internal signals since last watermark, and presents:

* “What changed while you were away” (pipeline progress + new questions)
* The next highest-priority question

### 1.5 Relationship to Planner and Pipeline

**Intent Agent is a layer above the Planner.**

* Planner remains the system’s internal reasoning/authority engine.
* Intent Agent is the *channel* to the user and the keeper of user-facing state.

Interaction points:

* **From user → system**: Intent Agent translates answers into constraints/decisions; persists; signals wake.
* **From system → user**: Planner/internal agents emit question signals; Intent Agent dedups/prioritizes/asks.

Distinguishing “own” questions vs forwarded questions:

* Same queue item type; difference is provenance:

  * `origin.kind = "INTENT_AGENT"` vs `"PLANNER"` vs `"UNDER_SPEC"` vs `"PROMOTION_LOOP"` etc.
* Priority and wording may differ, but lifecycle is identical.

---

## 2) Question queue design

### 2.1 Queue item schema

A queue item represents an **underlying unknown** (constraint/tradeoff/approval), not just text.

```json
{
  "question_id": "q_7f3a...",
  "status": "OPEN|ANSWERED|STALE|SUPERSEDED|DISMISSED",
  "kind": "INTENT|CONSTRAINT|TRADEOFF|APPROVAL",
  "canonical_key": "consistency.ledger", 
  "user_prompt": {
    "text": "For transaction records, do you require strong consistency (single source of truth) or is eventual consistency acceptable?",
    "why_it_matters": "This determines whether we can use an event-driven pipeline without transactional writes.",
    "answer_format": "free_text|choice|yaml",
    "choices": [
      {"id":"strong", "label":"Strong consistency"},
      {"id":"eventual", "label":"Eventual consistency"},
      {"id":"mixed", "label":"Mixed (specify which records require strong consistency)"}
    ]
  },
  "system_binding": {
    "constraint_targets": [
      { "scope": "system", "constraint_key": "consistency.ledger", "constraint_id_hint": "c_..." }
    ],
    "decision_requirements": ["dr_..."],
    "work_items": ["wi_..."]
  },
  "blockers": {
    "blocked_slices": ["LIB-01", "LIB-03"],
    "blocked_layers": ["l2"],
    "blocked_steps": ["IMPLEMENT", "PLAN"],
    "severity": "BLOCKING|HIGH_RISK|MEDIUM_RISK|INFO"
  },
  "origins": [
    {
      "source": "PLANNER|UNDER_SPEC|LIFECYCLE|INTENT_AGENT",
      "trace_id": "trace_...",
      "signal_id": "sig_...",
      "slice_id": "LIB-01",
      "function_ref": { "file":"...", "symbol":"...", "line": 142 },
      "spec_refs": [{ "spec_text":"...", "source_file":"...", "source_line_hint": 12 }]
    }
  ],
  "priority": {
    "score": 0.92,
    "explanation": "Blocks 2 slices in l2 and a high-risk money-movement workflow."
  },
  "timestamps": { "created_at":"...", "updated_at":"..." }
}
```

**Key point:** `canonical_key` is the dedup/reassessment handle. It is produced by LLM inference at ingest time (not hardcoded templates).

### 2.2 Priority model

Priority is computed from a **mechanical base** plus an **LLM refinement** when needed.

**Mechanical base features (cheap, deterministic):**

* `blocking_count`: number of blocked slices/agents
* `layer_weight`: l2 > l1 > l3 (because wrong architectural assumptions amplify)
* `severity`: HIGH_RISK > BLOCKING > MEDIUM_RISK > INFO
* `scope_blast_radius`: SYSTEM > CROSS_SLICE > SLICE > LOCAL
* `time_sensitivity`: optional (deadlines, external commitments)
* `staleness_penalty`: old questions with no blockers drop

Example scoring sketch (implementation detail, not user-visible):

```
score =
  0.35 * norm(blocking_count) +
  0.20 * severity_weight +
  0.20 * layer_weight +
  0.15 * blast_radius_weight +
  0.10 * time_weight
```

**LLM refinement (only on top-K):**

* If multiple questions are close in score, ask LLM:

  * “Which question unblocks the most work with the least ambiguity?”
* LLM can reorder within the top 5, but cannot promote a low-score item above clearly-blocking items without justification stored in the log.

### 2.3 Reassessment on answer

Reassessment is **hybrid** (fast-path + LLM for ambiguous cases).

**Step 1: Translate answer → ConstraintDelta**

* Extract:

  * constraints to write (authoritative)
  * decisions/tradeoff positions (authoritative only if allowed)
  * implied constraints (hypotheses, non-authoritative)
  * concept map updates

**Step 2: Mechanical resolution pass**
Mark a queued question as `ANSWERED` if any is true:

* `question_id` explicitly answered
* new constraints include its `canonical_key`
* its `constraint_id_hint` is now present in constraint store
* blockers list becomes empty and question is not high-risk

**Step 3: LLM reassessment pass (only if needed)**
For remaining OPEN items, ask LLM:

* Is this already answered by the new constraints?
* Is it irrelevant given updated problem frame?
* Should it be reworded now that we have more context?

Output: `{question_id: KEEP|ANSWERED|STALE|REWORD(new_text, new_key)}`

### 2.4 Deduplication

Three-tier dedup:

1. **Exact key match**: same `canonical_key` ⇒ duplicates.
2. **Event/signal match**: same `event_id` / `decision_requirement_id` ⇒ duplicates.
3. **Semantic match** (LLM): only among candidates with high lexical similarity or shared domain markers.

When deduped:

* Merge `origins` (provenance preserved)
* Union `blockers`
* Keep best `user_prompt` (or rewrite once using merged context)

### 2.5 Batching rules

Default: **one question at a time**.

Allow batching only when:

* 2–3 questions share the same `canonical_key` prefix (e.g., `consistency.*`)
* Answering them together reduces ambiguity and avoids repeated context
* None are high-risk in a way that requires careful isolation

Batch format in UI:

* “These are all about consistency requirements—answer together if you can; ‘not sure’ is fine.”

### 2.6 Staleness / expiry

A question becomes `STALE` (not deleted) when:

* No remaining blockers *and* it’s not classified HIGH_RISK
* Superseded by a confirmed redefinition of the problem frame
* The pipeline generated a new question with a more specific key that subsumes it

Stale items remain in the log for auditability.

---

## 3) Signal flow from internal agents to Intent Agent

### 3.1 New signal type: `UserQuestionSignal`

Add a new coordination signal family that is explicitly “for user”.

This is distinct from `CoordinationSignal` (which is about inter-slice dependency waiting), but it uses the **same file-based emit/react pattern**.

**Storage location**

* `.pdd_runs/<run_id>/coordination/user_questions.jsonl` (append-only)

**Schema (minimal required fields + extensible payload)**

```json
{
  "uq_version": 1,
  "uq_id": "uq_...",
  "run_id": "...",
  "created_at": "...",
  "source": {
    "kind": "PLANNER|UNDER_SPEC|PROMOTION_LOOP|LIFECYCLE|SLICE_AGENT",
    "trace_id": "trace_...",
    "slice_id": "LIB-01",
    "layer": "l2",
    "signal_id": "sig_..."
  },
  "question": {
    "text": "...",
    "kind": "CONSTRAINT|TRADEOFF|APPROVAL|INTENT",
    "canonical_key_hint": "consistency.ledger",
    "choices": []
  },
  "context": {
    "spec_refs": [],
    "code_refs": [],
    "blocking": { "blocked_slices": ["LIB-01"], "severity": "BLOCKING" }
  },
  "payload": {}
}
```

### 3.2 Who emits `UserQuestionSignal`

**Planner**

* When `DecisionAuthority` says “requires human constraint”
* Output of `QuestionComposerStrategy` becomes one or more `UserQuestionSignal`s (already constraint-shaped)

**Under-spec**

* When uncovered events remain and interactive mode is active
* UnderSpecManager emits question signals instead of prompting directly

**PromotionLoop / Lifecycle**

* Approval checkpoints (L1 approval, L2 topology checkpoint, release signoff)
* Merge conflict requiring human intervention (if you treat this as user-facing)

**Slice agents (rare)**

* Only if a slice has user-facing ambiguity that cannot be expressed as a simple missing constraint event
* Still goes through the same signal path; agent never talks to the user directly

### 3.3 How Intent Agent ingests signals

Intent Agent maintains a **watermark** (last processed byte offset or last `uq_id` timestamp) and periodically:

* Reads new lines from `user_questions.jsonl`
* Normalizes → generates/validates `canonical_key` using LLM if missing
* Dedups against existing queue
* Computes priority and updates queue state

This keeps producers decoupled from the interface.

### 3.4 “Ask immediately vs queue vs answer itself”

On ingest, Intent Agent chooses among:

1. **Self-answer (auto mode only, low-risk only)**

   * If question is resolvable via research tools and authority policy allows
2. **Queue**

   * Default for all user authority questions
3. **Try to infer from existing constraints**

   * If constraint store already covers it, mark answered without bothering the user

---

## 4) Answer flow from user back to agents

### 4.1 User answer lifecycle

When the user answers:

1. **Persist answer** (append-only)
   `.pdd_runs/<run_id>/intent/answers.jsonl`

2. **Translate answer → constraints/decisions** (LLM)

   * Output:

     * `constraints_to_save[]` (authoritative)
     * `tradeoff_positions[]` (authoritative preference)
     * `assumptions[]` (hypotheses; non-authoritative)
     * `new_questions[]` (discovered unknowns)

3. **Write to constraints store**

   * System-level: `analysis/constraints/system.json`
   * Slice-level: `analysis/constraints/<slice_id>.json` when scoped
   * Every constraint includes provenance pointing back to:

     * question_id
     * answer log entry
     * source authority (“user”)

4. **Wake blocked work**

   * Two mechanisms; implement both (belt + suspenders):

     * **Direct wake:** Intent Agent enqueues `WakeEvent` for affected slices
     * **Monitor wake:** any monitors waiting on `constraint_present` will fire

5. **Reassess queue**

   * Mark answered/stale/reword, dedup, reprioritize

### 4.2 How answers reach the blocked agent

Blocked slices should be waiting on a condition that becomes true when constraints are saved.

Recommended wiring:

* For each under-spec question emitted, register a monitor:

  * condition: `constraint_present` for that `constraint_id` or `canonical_key`
* When Intent Agent saves constraints:

  * it triggers a `CONSTRAINT_SAVED` event hook (or writes directly to WakeQueue)

Then PromotionLoop resumes slice on wake and re-runs the iteration with the new constraints available.

### 4.3 Recursive discovery

If the user answer introduces a new constraint that implies further decisions:

* `AnswerTranslateStrategy` emits `new_questions[]`
* These become first-class queue items with origin = `INTENT_AGENT` and provenance linking back to the answer
* Queue reassessment runs immediately so only truly-needed follow-ups remain OPEN

---

## 5) Intent understanding algorithm

### 5.1 Conversational but event-driven

The system behaves conversationally to the user, but internally it’s an event processor:

* **User message event** → update frame → generate next best question or produce skeleton
* **Internal question signal event** → enqueue → maybe ask next

### 5.2 Intake loop (proportional depth)

Each user message updates:

* `problem_frame` (goal, scope, domain markers)
* `concept_map` (user terms ↔ system terms)
* `constraints.hypotheses` (non-authoritative assumptions)
* `open_unknowns` (candidate questions)

Then the agent chooses:

* Ask **one** high-value question (or a tiny batch)
* Or, if enough to proceed, generate the skeleton

**What “enough” means**
Enough to produce a skeleton when:

* Core workflows are identifiable (even if partially specified)
* Major risk flags have at least baseline constraints or explicit “unknown” placeholders
* The agent can define a reasonable initial decomposition (libraries/components) without making irreversible commitments
* The user has either:

  * confirmed the restatement of the problem frame, or
  * explicitly said “go ahead / start”

If missing, the skeleton can still be produced with TODOs, but only if those TODOs are *constraints*, not implementation details.

### 5.3 Handling vague input

If user says “Build me a trading platform”:

* Agent produces 2–3 candidate frames (LLM):

  * “Order routing + execution”
  * “Portfolio + risk + reporting”
  * “Treasury + settlement + reconciliation”
* It asks one disambiguating question:

  * “Which of these is closest to what you mean (or describe your variant)?”

No long questionnaire; the system converges by successive narrowing.

### 5.4 How much structure is imposed

Early questions focus on:

* Intended users and primary workflows
* Constraints that strongly shape architecture (latency/consistency/regulatory/auditability)
* Integrations and data sources

Avoid early questions about:

* specific libraries
* internal component names
* implementation technologies

Those can be constrained later if the user cares.

---

## 6) Skeleton format and depth

### 6.1 Output artifacts

Intent Agent produces two coupled artifacts:

1. **Prose “Intent Spec” (human readable)**

   * `system/intent.md` (or `analysis/intent/intent.md`)
   * Contains:

     * problem restatement
     * confirmed constraints
     * assumptions (clearly marked)
     * tradeoff positions
     * open questions (IDs + short text)

2. **Code-as-spec skeleton (machine actionable)**

   * Written into the same structure expected by L1:

     * `libraries/<lib_id>/.../*.py` (or other language renderer later)
   * Contains:

     * spec comment blocks
     * function/class stubs
     * TODOs referencing question IDs / constraint keys

### 6.2 Depth rule

Skeleton is **one level deeper than names**:

* Include top-level workflows + key interfaces (what calls what)
* Include domain entities (structural shapes)
* Include placeholders for external dependencies
* Do not implement business logic

Concretely:

* Yes: `SettlementProcessor.process(instruction) -> Receipt`
* Yes: `Ledger.post(entry) -> PostingResult`
* Yes: `RiskEngine.check_exposure(tx) -> ExposureResult`
* No: actual exposure computation

### 6.3 Embedding open unknowns in the skeleton

Every unresolved constraint becomes a TODO with a stable handle:

```python
# Q:q_7f3a... (consistency.ledger)
# Need: confirm whether ledger postings must be strongly consistent or can be eventually consistent.
def post(self, entry: LedgerEntry) -> PostingResult:
    raise NotImplementedError
```

This makes “unknowns” durable and discoverable by downstream agents.

### 6.4 Metadata accompanying skeleton

Write a single machine-readable snapshot:

* `analysis/intent/intent_snapshot.json`

  * problem_frame
  * constraints (authoritative + hypotheses separated)
  * tradeoff positions
  * queue open items (IDs + canonical keys)
  * concept map

This is the handshake contract into the existing pipeline.

---

## 7) Problem redefinition protocol

### 7.1 Detecting redefinition triggers

A redefinition proposal is triggered when:

* Planner decomposes a user term into multiple subsystems and the decomposition changes scope materially
* Implementation reveals incompatible requirements
* Architecture proposal implies a different operational model than user assumes

### 7.2 Redefinition interaction pattern (single question, explicit confirmation)

When triggered, Intent Agent creates a **RedefinitionCheck** queue item:

* Presents:

  * original intent statement
  * current restatement
  * “What changed and why”
  * the smallest decision needed from the user:

    * confirm new frame
    * reject and restate
    * accept partially (scope in/out)

User response updates:

* `problem_frame.current_restatement`
* `scope.in/out`
* constraints (as needed)
* queue reassessment (many questions may become stale)

### 7.3 Preventing drift

Maintain a lightweight **alignment checksum**:

* A short list of invariant “must-stay-true” statements derived from original intent and confirmed constraints
* If proposals violate them, Intent Agent asks before allowing commitment

This prevents silent re-interpretation.

---

## 8) Relationship to Phase 0

### Recommended: Phase 0 becomes a strategy inside the Intent Agent (wrap + preserve)

**Behavior selection**

* If user supplies complete prose specs:

  * Intent Agent delegates to Phase 0 for routing/coverage
  * Intent Agent then produces:

    * a distilled intent snapshot
    * a skeleton derived from Phase 0 library outputs (charters + constraints)
* If user supplies intent-level input:

  * Intent Agent produces skeleton directly
  * Phase 0 is optional:

    * either skipped
    * or run on the generated intent prose to create library docs (when useful)

This avoids maintaining two separate intake paradigms while keeping Phase 0’s proven behavior.

**Interface contract**

* Phase 0 output becomes *authoritative evidence* for constraints and library responsibility summaries
* Intent Agent treats Phase 0 constraints as authoritative inputs into the constraint store (already bootstrapped in lifecycle)

---

## 9) Session persistence and resumption

### 9.1 What is saved

Save only what must be durable:

* `session_state.json` (current snapshot)
* `events.jsonl` (append-only)
* `user_questions.jsonl` watermark + processed IDs
* `answers.jsonl` (append-only)
* `intent_snapshot.json` (exportable contract to pipeline)
* skeleton artifacts + revision log

### 9.2 Resume behavior

On resume, Intent Agent:

1. Loads snapshot
2. Ingests any new internal question signals
3. Checks pipeline state (slice statuses, waiting reasons) and summarizes deltas
4. Presents:

   * highest-priority open question
   * optionally a short list of queued questions (“next up”)

### 9.3 Pipeline progress while user away

If pipeline advanced (e.g., auto-mode resolved some issues):

* Intent Agent marks corresponding questions as ANSWERED (with provenance: “auto resolution”)
* For any decisions taken without user authority (should be rare), it emits an explicit “Review decision” question item so the user can override later

---

## 10) Integration wiring

### 10.1 New files/modules

Create `spec_manager/orchestration/intent_agent/`:

* `agent.py`

  * `IntentAgentOrchestrator.handle_user_message()`
  * `IntentAgentOrchestrator.ingest_question_signals()`
  * `IntentAgentOrchestrator.next_prompt()`
* `state.py`

  * `IntentSessionState`, `ProblemFrame`, `ConceptMap`, `TradeoffPosition`
* `queue.py`

  * `QuestionItem`, `QuestionQueue`, dedup/prioritize/reassess
* `signals.py`

  * `UserQuestionSignal` read/write to `.pdd_runs/<run_id>/coordination/user_questions.jsonl`
* `translation.py`

  * `AnswerTranslateStrategy` output schema + constraint writing adapter
* `skeleton.py`

  * `SkeletonSynthesisStrategy` + renderers (`python_renderer.py` initially)
* `persistence.py`

  * snapshot + JSONL logs + watermark tracking

Create/extend `spec_manager/orchestration/coordination/`:

* `user_questions.py` (if you prefer to keep signals with coordination)

  * file-backed append-only store + reader with watermark

### 10.2 Modify existing modules

**A) Under-spec system**

* `orchestration/under_spec/manager.py`

  * Add optional `question_sink` (or `intent_agent`) dependency
  * In interactive mode:

    * do **not** run `InteractiveWorkflow`
    * emit `UserQuestionSignal`s instead
    * register monitors for `constraint_present`
    * return outcome that leads to `WAITING` instead of terminal BLOCKED

**B) PromotionLoop**

* `orchestration/promotion_loop.py`

  * In `CoordinateStep._resolve_under_spec()`:

    * if unresolved and interactive:

      * emit question signals
      * return `StepResult(status="WAITING")` (not `BLOCKED`)
    * ensure wake events on constraint save re-queue the slice

**C) Planner**

* No major architectural change required.
* Ensure planner outputs human-usable question payloads consistently:

  * `QuestionComposerStrategy` output should map cleanly into `UserQuestionSignal.question`
* Wire `Planner(on_constraint_saved=...)` to emit coordination events or wake events.

**D) Coordination monitors**

* `orchestration/coordination/monitors.py`

  * Ensure `ConstraintPresentCondition` can target:

    * constraint_id
    * canonical_key (optional)
  * MonitorExecutor should react to:

    * `CONSTRAINT_SAVED` events (optional) or polling

**E) pdd_lifecycle interactive prompts**

* `orchestration/pdd_lifecycle.py`

  * Replace `input()` approval prompts with:

    * creation of `UserQuestionSignal(kind="APPROVAL")`
    * Intent Agent handles user response and writes `approvals/<layer>/decision.json`
  * Keep a CLI adapter only as a thin front-end for the Intent Agent (backward compatibility)

**F) Intake**

* Add an entrypoint:

  * `orchestration/intent_agent/intake_entry.py`

    * If user provides intent → generate skeleton
    * If user provides prose → delegate to Phase 0 then generate skeleton
* Update lifecycle `_run_intake()` to accept either:

  * existing spec folder input
  * or intent session output artifacts

### 10.3 Migration path

1. Add `UserQuestionSignal` store + Intent Agent queue ingestion (no behavior change yet).
2. Route **UnderSpecManager interactive mode** to emit question signals (still blocks).
3. Change PromotionLoop to treat user-constraint wait as `WAITING` with monitors/wake.
4. Replace lifecycle approval prompts with approval question signals.
5. Add “intent-only” intake path that generates skeleton and bypasses Phase 0.
6. Gradually phase out `InteractiveWorkflow` as a user interface (it becomes an internal tool, or removed).

---

If you want this as a concrete spec artifact (one markdown file with schemas + state machines + file paths), the content above is already structured to drop directly into `design/intent_ingest.md`.
