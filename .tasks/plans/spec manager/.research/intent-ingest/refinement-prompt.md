# Refinement: Intent Ingest — Question Quality, Authority Boundaries, and Constraint Taxonomy

## What This Refinement Addresses

The initial response (response.md) is structurally sound. The module split,
signal flow, queue mechanics, and integration wiring follow existing patterns
correctly. However, it has gaps in three areas:

1. **Authority boundary between Intent Agent and Planner is blurred**
2. **Question quality has no enforcement — only advisory rewriting**
3. **No taxonomy of what questions are valid vs prohibited**

These are not minor polish items. They define whether the Intent Agent asks
users about their business intent (correct) or about implementation
decisions (incorrect). The whole point of the Intent Agent is to shield
users from the system's internal architecture and ask only what the user
is qualified to answer: their goals, their constraints, their priorities.

There is also a fourth gap not in the initial response but in the existing
codebase: the human-in-the-loop points in the lifecycle are disconnected
from the planning constraint pipeline.

4. **Existing human checkpoints don't surface planning decisions**

---

## Refinement 1: Authority Boundary — Who Owns What

### Problem

Section 1.3 state model puts `constraints.authoritative`,
`constraints.hypotheses`, and `tradeoff_positions` inside the Intent
Agent's session state. Section 4.1 step 3 says the Intent Agent writes
directly to the constraint store.

This creates a parallel constraint authority alongside the Planner's
`ConstraintsStore` (designed in RP5). The Planner is the system's
constraint authority. The Intent Agent is the user's representative.
These are different roles.

### Required Change

**Intent Agent state model must NOT own constraint objects.**

Intent Agent may hold only:
- Question queue state (open/closed/stale items)
- `question_id → canonical_key` reference map (for dedup and reassessment)
- User-facing framing metadata (problem_frame, concept_map, scope)
- Answer provenance (what the user said, when, in response to which question)
- Skeleton revision state

Intent Agent must NOT hold:
- `constraints.authoritative` — belongs to `ConstraintsStore`
- `constraints.hypotheses` — belongs to `ConstraintsStore` (as unverified)
- `tradeoff_positions` — belongs to Planner's decision record

**Answer flow must be Planner-mediated:**

Current (Section 4.1):
```
User answers → Intent Agent translates → Intent Agent writes to constraint store → wake
```

Required:
```
User answers → Intent Agent produces AnswerTranslation artifact → Planner receives artifact →
Planner validates and writes to constraint store → Intent Agent observes store changes via
monitors/watermark → Intent Agent updates question status
```

The Planner decides what's authoritative. The Intent Agent observes what
the Planner wrote and uses that to update queue status (mark questions
answered, trigger reassessment). The Intent Agent never writes constraints.

### Why This Matters

If the Intent Agent writes constraints directly, there are two sources of
constraint truth. When they diverge (and they will — the Planner enriches,
propagates, and validates constraints), the system has a consistency problem.
One store, one writer, one authority.

---

## Refinement 2: Question Quality Gate — Hard Enforcement, Not Advisory

### Problem

The response designs `QuestionRewriteStrategy` (Section 1.2) but provides
no quality gate. There is no schema, no validation, no explicit rule set.
The response says "QuestionRewrite will handle it" but doesn't define what
"handle it" means.

Without enforcement, LLM strategies will naturally drift toward abstract,
technical questioning. The response's own example demonstrates this:
"For transaction records, do you require strong consistency (single source
of truth) or is eventual consistency acceptable?" — this is system language,
not user language.

### Required Change

**Add a mandatory quality gate with pass/fail validation.**

Every question that reaches the user must pass ALL of these:

1. **Domain language only.** The question must be answerable by someone who
   knows the business domain but has never written code. No architecture
   jargon, no implementation patterns, no framework names unless the user
   introduced that term in their own input.

2. **Bounded answerability.** The question must have a concrete answer space:
   - Choice set (A/B/C) preferred
   - Yes/no with a specific behavior described
   - A concrete value (number, name, date)
   - NOT open-ended "what do you think about..."
   - NOT vague "what is the minimum acceptable behavior..."

3. **Specific behavior or property.** The question must reference a concrete
   behavior, outcome, or constraint — not an abstract dimension. "Should
   transactions be reversible within 24 hours?" not "What level of
   consistency do you need?"

4. **Scenario grounded.** The question must include or reference a concrete
   scenario that shows why the answer matters. "If a settlement fails
   halfway through, should the system retry automatically or alert a
   human?" — the scenario IS the question.

5. **One question per interaction** (default). Batching only when 2-3
   questions share the same domain concern AND answering together reduces
   ambiguity.

**Quality gate implementation:**

```
QuestionRewriteStrategy produces candidate question
  → QualityValidator checks 5 rules above
  → PASS: emit to queue
  → FAIL: route back for automatic reframe (up to 2 retries)
  → FAIL after retries: log as unaskable, escalate to Planner for
    reformulation or auto-resolution via research tools
```

Every question attempt gets a quality record in the event log:
```json
{
  "question_id": "q_...",
  "attempt": 1,
  "quality_check": {
    "domain_language": true,
    "bounded": true,
    "specific": false,
    "scenario_grounded": false,
    "result": "FAIL",
    "reason": "References 'eventual consistency' without concrete scenario"
  }
}
```

### Example Corrections

**BAD** (from current response):
"For transaction records, do you require strong consistency (single source
of truth) or is eventual consistency acceptable?"

**GOOD**:
"When a settlement is recorded, does every part of the system need to see
it immediately, or is a brief delay (seconds to minutes) acceptable?"

**BAD**: "Should this run event-driven, batch, or synchronous?"

**GOOD**: "Are settlements processed one at a time as they arrive, or
collected and processed together at scheduled intervals (e.g., end of day)?"

**BAD**: "What is the minimum acceptable behavior for this flow?"

**GOOD**: "If a settlement succeeds but the confirmation to the counterparty
fails, should the system: (A) retry the confirmation automatically,
(B) hold the settlement until confirmed, or (C) proceed and flag for
manual follow-up?"

**BAD**: "Should external integrations be plug-in points or hardwired?"

**GOOD**: "Will this system connect to external clearing houses or data
providers? If so, do you expect to switch between providers, or are they
fixed partnerships?"

---

## Refinement 3: Question Taxonomy — What Questions Are Valid

### Problem

The response treats all questions as one type. But questions vary by what
they're asking about and why. The response needs an explicit taxonomy that
defines which question types are valid for the user and which are
internal-only.

### Required Change: Question Taxonomy

Questions fall into these categories. The first five are valid for users.
The rest are internal-only and must never reach the user directly.

#### Valid user-facing question types

**1. INTENT — What is the real problem?**

Problem-discovery is iterative. As the Planner helps define the problem,
questions about the problem itself may flow back to the user via the Intent
Agent. This is legitimate and expected.

Examples:
- "You mentioned settlement processing — does this include reconciliation
  with external counterparties, or only internal ledger updates?"
- "Is the goal to replace the existing system or to run alongside it
  during a transition period?"

**2. CONSTRAINT — What boundaries exist?**

Constraints are not just software constraints. They include:
- **Operational**: latency, throughput, availability requirements
- **Regulatory**: compliance regimes, audit requirements, data residency
- **Organizational**: team size, existing expertise, existing infrastructure
- **Legal/licensing**: open source policies, vendor lock-in policies
- **Financial**: budget constraints, cost targets
- **Platform**: existing cloud commitments, on-premise requirements
- **Data**: sensitivity classification, retention policies, volume estimates

Key principle: **ask about constraints that inform choices, not the choices
themselves.** You don't ask "which cloud platform?" You ask "are there
existing platform commitments or constraints that would affect where this
runs?" — unless the user has already specified.

Examples:
- "Are there regulatory requirements for how long transaction records must
  be retained?"
- "Does your organization have existing cloud platform commitments, or is
  this a greenfield decision?"
- "Are there licensing restrictions on the libraries or frameworks that
  can be used?"
- "What is the expected transaction volume — tens per day, thousands, or
  millions?"

**3. TRADEOFF — When priorities conflict, which wins?**

Examples:
- "If processing speed conflicts with complete audit logging, which takes
  priority?"
- "Would you prefer the system to be simpler with fewer features now, or
  more comprehensive but taking longer to deliver?"

**4. SCOPE — What is in and what is out?**

Examples:
- "Is multi-currency support needed for the initial version, or can that
  come later?"
- "Should the system handle user authentication itself, or will it rely on
  an existing identity provider?"

**5. VALIDATION — How do we know it's correct?**

Examples:
- "What does a successful settlement look like from the user's perspective?
  Walk me through one example."
- "Are there existing test cases or acceptance criteria we should match?"

#### Internal-only question types (NEVER reach the user)

**6. ARCHITECTURE** — "Should this be event-driven or synchronous?"
→ This is the Planner's job. Route to Planner for auto-resolution or
research tools.

**7. IMPLEMENTATION** — "Which library should we use for X?"
→ System resolves via research tools and constraint reasoning.

**8. DESIGN PATTERN** — "Should we use the repository pattern here?"
→ System decides based on constraints and patterns.

**9. OPTIMIZATION** — "Should we use caching here?"
→ System decides based on constraints.

If an internal agent asks an architecture/implementation question and it
CANNOT be resolved without user input, it must be **reframed** into a
CONSTRAINT or TRADEOFF question before reaching the user. For example:

Internal: "Should we use WebSockets or polling for real-time updates?"
Reframed: "Do users need to see updates immediately (within seconds) or
is periodic refresh acceptable?"

The answer to the reframed question becomes a constraint that informs the
architecture decision internally.

### System-Wide vs Feature-Specific

Questions also vary in scope. Both are valid:

- **System-wide constraints**: "Are there platform commitments?"
  "What compliance regime applies?" — asked early, inform everything.
- **Feature-specific constraints**: "For the reconciliation workflow,
  is exact-match required or is fuzzy matching acceptable?" — asked when
  that specific feature is being planned.

The queue priority model should reflect this: system-wide questions that
unblock multiple features are higher priority than feature-specific
questions.

---

## Refinement 4: AnswerTranslate Recursion Guard

### Problem

Section 4.3 says `AnswerTranslateStrategy` emits `new_questions[]` from
user answers. These become queue items. But there's no validation that
generated follow-ups meet the quality gate from Refinement 2.

This is the path where abstract cascading questions leak in — a user
answer about data retention could trigger a follow-up about "CAP theorem
tradeoffs."

### Required Change

Generated follow-up questions from AnswerTranslate MUST pass the same
quality gate as all other questions. Same 5 rules, same pass/fail
validation, same retry-and-escalate flow.

Additionally, bound the recursion:
- Maximum 2 follow-up questions per answer (across the full reassessment
  cycle, not per strategy invocation)
- Follow-ups that fail quality gate after retries are routed to Planner
  for auto-resolution, NOT escalated to user as degraded questions

---

## Refinement 5: Phase 0 / Decomposition Ownership

### Problem

Section 6 has the Intent Agent writing skeleton into
`libraries/<lib_id>/.../*.py` — meaning the Intent Agent performs library
decomposition. But library decomposition is Phase 0's job. Phase 0 has
proven algorithms for discovering libraries from summaries (sectionize →
discover → route → coverage → assemble).

If the Intent Agent generates skeleton with library structure for
intent-level input, it's doing decomposition without Phase 0's proven
routing/coverage algorithms. This could produce skeletons with ad-hoc
library boundaries that downstream pipeline steps can't validate.

### Required Change

Make decomposition ownership explicit:

**If intake is prose** → Phase 0 runs and produces libraries. Intent Agent
wraps Phase 0 output into skeleton with TODOs.

**If intake is intent-level** → Intent Agent produces skeleton tied to
discovered workflows + interfaces + entities WITHOUT inventing library
boundaries. The skeleton structure is:
```
system/
  intent.md          # problem frame, constraints, scope
  workflows/
    <workflow>.py    # per core workflow, with TODO comments
  entities/
    <entity>.py      # per domain entity, with TODO comments
  interfaces/
    <interface>.py   # per external interface, with TODO comments
```

Library decomposition happens LATER when the Planner has enough
understanding. The Intent Agent's skeleton is pre-decomposition.
Phase 0 can optionally run on the generated intent prose to create
library boundaries when the system is ready.

---

## Refinement 6: Redefinition Trigger Language

### Problem

Section 7.1 triggers include "implementation reveals incompatible
requirements" and earlier sections mention "strong consistency/eventual
consistency"-style framing. These triggers are legitimate — the issue is
that the resulting question to the user must be in domain language.

### Required Change

Section 7.1 is correct that these are valid triggers. But every
redefinition question must pass the same quality gate. Update the examples:

**BAD**: "Implementation reveals incompatible requirements between
strong consistency and high throughput."

**GOOD**: "We discovered that two of your requirements conflict: you asked
for immediate visibility of all transactions AND processing thousands per
second. Achieving both simultaneously adds significant complexity. Which
is more important for the initial version?"

The trigger is system-level. The question is user-level. The quality gate
enforces this translation.

---

## Refinement 7: Existing Human-in-the-Loop Is Disconnected from Planning

### Problem

The response's integration wiring (Section 10) modifies existing modules
but doesn't address that the **existing human checkpoints in the lifecycle
don't surface the planning constraint pipeline's output**. The Intent Agent
design must replace these broken checkpoints, not layer on top of them.

Here's what currently exists and why it's broken:

**L1 Approval** (`pdd_lifecycle._request_approval`):
- Generates an overview document and asks approve/feedback/quit
- The human sees a generated overview of code-as-spec output
- They do NOT see: constraints discovered, tradeoffs identified,
  planning decisions made, authority escalations, non-software checklist
  items, or anything from RP5's strategy pipeline
- What is the human supposed to review? The overview is a generated
  document with no structured constraint or planning quality content
- Per-library approval makes no sense without constraint alignment context

**L2 Checkpoint** (`pdd_lifecycle._request_l2_checkpoint`):
- Just approve/quit with even less context than L1
- The L2 planner's strategy pipeline (ImpactClassifier →
  ConstraintCollection → TradeoffMapper → ProblemFramer →
  ConstraintEnricher → NonSoftwareChecklist → ArchitecturePlanner →
  AuthorityDecider → QuestionComposer) ran during PLAN step
- AuthorityDecider identified human-required items
- QuestionComposer refined questions
- None of this reaches the human at the L2 checkpoint
- The questions go into `under_spec_events` which flow to
  CoordinateStep → UnderSpecManager → InteractiveWorkflow (raw CLI)

**InteractiveWorkflow** (via UnderSpecManager):
- When under_spec_events can't be auto-resolved, writes a
  `constraint_request.md` and runs InteractiveWorkflow
- This is a raw text prompt with no queue, no dedup, no reassessment,
  no quality gate on the questions, no connection to planning context
- It's a blunt instrument disconnected from the structured constraint
  pipeline

**The flow that's broken:**
```
L2 Planner runs strategy pipeline
  → AuthorityDecider marks items "human_required"
  → QuestionComposer refines questions
  → under_spec_events go into plan result
  → PromotionLoop CoordinateStep picks them up
  → L1: converts to CoordinationSignals → WAITING (questions never reach human)
  → L2/L3: UnderSpecManager → InteractiveWorkflow (raw input() prompt)
```

The strategy pipeline GENERATES structured constraint questions but the
lifecycle has NO structured path to present them to the user. The L1
approval reviews an overview that has nothing to do with planning decisions.
The L2 checkpoint doesn't surface the architecture/constraint decisions
the planner just made.

### Required Change

The Intent Agent must **replace** the existing human checkpoints, not
exist alongside them. Specifically:

**1. L1 Approval → Intent Agent constraint alignment review**

Instead of showing an overview and asking approve/feedback:
- Intent Agent presents: constraints discovered during L1 planning,
  any human-required items from AuthorityDecider, non-software checklist
  flags, the problem frame, and unresolved questions
- The question queue already handles this — L1 planning's human-required
  items become UserQuestionSignals that the Intent Agent presents
- Overview can still be generated for context, but the actual approval
  gate is: "are all blocking constraint questions answered?"
- Per-library approval becomes: "do these constraints correctly capture
  what you described?" — which is an INTENT question type

**2. L2 Checkpoint → Intent Agent architecture constraint review**

Instead of approve/quit with no context:
- The L2 strategy pipeline's under_spec_events become
  UserQuestionSignals (they already have QuestionComposer-refined text)
- AuthorityDecider's "human_required" items flow to the Intent Agent
  queue with constraint/tradeoff question types
- The Intent Agent presents them with the quality gate applied
- The L2 checkpoint waits for all BLOCKING questions to be answered
- Architecture decisions that don't need human authority proceed
  automatically (AuthorityDecider already handles this correctly)

**3. InteractiveWorkflow → Intent Agent question queue**

Replace `_resolve_interactive` in UnderSpecManager:
- Instead of writing `constraint_request.md` and running InteractiveWorkflow
- Emit UserQuestionSignals for each unresolved event
- Intent Agent handles queue, dedup, reassessment, quality gate
- Register monitors for `constraint_present` conditions
- Return WAITING status so the slice blocks until answered

**4. Release Signoff → Intent Agent validation question**

Instead of raw approve/reject:
- Intent Agent presents: validation summary, test results, known gaps
- Asks VALIDATION type question: "Does this match what you described?"
- With concrete examples of what was built vs what was requested

**What this means for Section 10 (integration wiring):**

The response's Section 10 modifications to UnderSpecManager and
PromotionLoop are correct directionally. But it needs to explicitly
state that `_request_approval`, `_request_l2_checkpoint`, and
`_request_release_signoff` in pdd_lifecycle.py are **replaced** by
Intent Agent question signals — not preserved alongside.

The CLI adapter for backward compatibility can remain as a thin
passthrough that reads UserQuestionSignals and presents them as
terminal prompts — but the underlying mechanism is the Intent Agent
queue, not raw `input()` calls.

---

## Summary of Required Updates to response.md

| Section | Change |
|---------|--------|
| 1.3 | Remove `constraints` and `tradeoff_positions` from state model. Replace with `question_key_map` and `answer_provenance`. |
| 1.5 | Clarify: Intent Agent translates answers → Planner writes constraints → Intent Agent observes. |
| 2.1 | Add quality gate fields to queue item schema. |
| 2.2 | No change (priority model is fine). |
| 4.1 | Rewrite step 3: Intent Agent produces AnswerTranslation artifact → Planner writes to store. |
| 4.3 | Add recursion bound (max 2 follow-ups) and quality gate requirement. |
| 5.4 | Add the full question taxonomy (5 valid types, 4 prohibited types). |
| 5.4 | Add system-wide vs feature-specific distinction. |
| 5.4 | Add quality gate specification (5 rules, pass/fail, retry, escalate). |
| 5.4 | Add non-compliance examples with corrections. |
| 6.1 | Restructure skeleton to workflows/entities/interfaces (no library decomposition). |
| 7.1 | Keep triggers, add quality gate enforcement for resulting questions. |
| 10.2 | Replace lifecycle approval checkpoints with Intent Agent question signals. |
| 10.2 | UnderSpecManager `_resolve_interactive` emits UserQuestionSignals, not InteractiveWorkflow. |
| 10.2 | L1 approval becomes constraint alignment review via Intent Agent queue. |
| 10.2 | L2 checkpoint becomes architecture constraint review via Intent Agent queue. |
| 10.2 | Release signoff becomes validation question via Intent Agent queue. |
| 10.2 | CLI adapter preserved as thin passthrough for backward compat. |
| NEW | Add `QualityValidator` schema and quality record schema. |
| NEW | Add question taxonomy table with examples per type. |
| NEW | Add constraint dimension list (operational, regulatory, organizational, legal, financial, platform, data). |
| NEW | Add lifecycle checkpoint replacement mapping (old → new). |

## Output Requirement: COMPLETE REPLACEMENT

**Do NOT produce diffs, patches, or partial updates.**

Produce a **complete, self-contained response** that replaces response.md
entirely. Response #2 must be the ONLY document anyone needs to read.
It must synthesize ALL conclusions from both the original response AND
every refinement above into a single coherent implementation spec.

Specifically:

1. **Every section from response.md must appear in response #2** — rewritten
   where refinements apply, preserved verbatim where they don't.

2. **No forward references to response.md.** Response #2 stands alone. A
   reader who has never seen response.md must be able to use response #2
   as the complete implementation spec.

3. **All refinements must be integrated in-place**, not appended as addenda.
   The authority boundary (Refinement 1) rewrites Sections 1.3, 1.5, and
   4.1. The question quality gate (Refinement 2) rewrites Sections 2.1 and
   5.4 and adds new subsections. The taxonomy (Refinement 3) adds new
   content to Section 5. The recursion guard (Refinement 4) rewrites
   Section 4.3. The decomposition ownership (Refinement 5) rewrites
   Section 6. The trigger language (Refinement 6) rewrites Section 7.1.
   The lifecycle replacement (Refinement 7) rewrites Section 10.

4. **Include all schemas.** The response must contain complete JSON schemas
   for: IntentSessionState (corrected — no constraint objects),
   UserQuestionSignal, QuestionItem (with quality gate fields),
   QualityCheckRecord, AnswerTranslation artifact, QueueReassessResult.

5. **Include all examples.** Replace every BAD example from response.md with
   GOOD examples that pass the quality gate. Include the full BAD→GOOD
   correction table so the quality bar is unambiguous.

6. **Include the lifecycle checkpoint replacement mapping.** Show exactly
   which existing `pdd_lifecycle.py` methods are replaced by which Intent
   Agent mechanisms. Show the before/after flow for L1 approval, L2
   checkpoint, under-spec interactive, and release signoff.

7. **Include the question taxonomy table.** 5 valid types with examples,
   4 prohibited types with reframing examples, system-wide vs
   feature-specific distinction.

8. **Maintain the same section numbering** (1-10) for continuity, but
   rewrite section content where refinements apply. Add new subsections
   where needed (e.g., 5.5 for quality gate, 5.6 for taxonomy).
