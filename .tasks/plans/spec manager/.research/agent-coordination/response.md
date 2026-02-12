## System overview

### Actors

* **Slice Agents (one per library slice)**
  Implement directly from spec comments in their slice worktree. When blocked, they **stop** and emit a **signal**.
* **Reactive Planner (triage authority)**
  Only runs when it receives a signal. It **matches the need to spec text work items**, decides: *already being worked / unrouted / underspecified*, then **registers a JIT monitor** and returns.
* **Monitor Executor (runtime)**
  Runs monitors (poll + event-triggered). When a monitor condition is met, it emits a **wake event**.
* **Scheduler / PromotionLoop runtime**
  Runs slices. If a slice returns `WAITING`, it is removed from the worker pool. When a wake event arrives, the slice is re-queued.

### Key invariants (aligned to your constraints)

* **No L1 pre-plan**: L1 `PLAN` is a no-op. L1 implementation is driven by spec comments in skeleton files.
* **Work items are spec text**: the primary coordination key is **verbatim spec comment text** (plus location metadata for disambiguation).
* **Agents don’t coordinate**: agents never reference other agents, monitors, or routing logic; they only implement or emit signals.
* **Git is the communication channel**: monitors check state on the **shared branch** (layer dirty), not in-memory assumptions.

---

## Q1: Signal format and emission protocol

### Design goal

Signals must be:

* **Structured enough** for deterministic triage + monitor generation
* **Flexible enough** for edge cases (free-form payload)
* **Grounded**: every signal includes *the exact spec text that triggered it* and the *exact local code anchor*.

### Recommended format: versioned JSON envelope with flexible payload

Use a single required schema + `payload` for extensibility.

#### `CoordinationSignal` (JSON)

```json
{
  "signal_version": 1,
  "signal_id": "sig_9a3c2f7a1b2e",
  "run_id": "run_2026_02_12_001",
  "layer": "l1",
  "slice_id": "LIB-01",
  "iteration": 3,

  "status": "HALT",
  "classification": "MISSING_INTERFACE",

  "need": {
    "summary": "Need RiskEngine.check_exposure interface to implement settlement exposure check",
    "artifact_type": "git_symbol",
    "artifact_key": "RiskEngine.check_exposure",
    "expected_shape": {
      "kind": "callable",
      "signature_hint": "def check_exposure(self, tx: Transaction) -> ExposureResult"
    },
    "confidence": 0.7
  },

  "spec_refs": [
    {
      "spec_text": "Reject settlement when risk engine exposure exceeds limits.",
      "source_file": "libraries/settlement/processor.py",
      "source_symbol": "SettlementProcessor.process",
      "source_line_hint": 142
    }
  ],

  "local_context": {
    "blocked_function": {
      "file": "libraries/settlement/processor.py",
      "symbol": "SettlementProcessor.process",
      "signature_line": "def process(self, instruction: SettlementInstruction) -> Receipt:"
    },
    "attempted_approach": "Call RiskEngine.check_exposure(...) before committing settlement."
  },

  "progress": {
    "functions_implemented": 7,
    "functions_skipped": 1,
    "worktree_branch": "pdd/run_2026_02_12_001/l1/slice/LIB-01/ab12cd",
    "latest_commit": "c0ffee42",
    "artifacts": {
      "patch_path": ".pdd_runs/.../iter_003/patch.diff",
      "notes_path": ".pdd_runs/.../iter_003/notes.md"
    }
  },

  "search_hints": {
    "keywords": ["RiskEngine", "exposure", "check_exposure"],
    "possible_owner_slices": ["LIB-02"]
  },

  "payload": {}
}
```

### Why this structure works

* **Planner-critical fields are stable**: `classification`, `need`, `spec_refs`, `progress`.
* **Search is spec-text-first**: `spec_refs[].spec_text` is verbatim and can be matched across work items.
* **Not overly rigid**: `payload` can carry any additional detail without schema churn.

### Emission protocol

1. **Agent implements sequentially** (per function) until it hits a blocker.
2. On blocker:

   * It **does not** implement the blocked function (no guessing).
   * It emits **exactly one signal per blocker root-cause** (often 1).
3. ImplementationRunner writes:

   * `iter_NNN/signals.json` (array)
   * `iter_NNN/signal_<signal_id>.md` (optional human-readable)
4. PromotionLoop:

   * Commits partial progress to the slice branch (if any).
   * Calls reactive planner triage.
   * Returns `SliceResult(status="WAITING")`.

---

## Q2: Spec text search for dependency matching

### What the planner must do

Given a signal like “Need TransactionValidator interface,” the planner must find the relevant **work item(s)** whose **spec text** implies that interface exists / must be implemented.

### Recommended search: 3-stage retrieval (deterministic → fuzzy → semantic)

#### Stage A: Exact/fingerprint match (fast path)

* Normalize spec text: lowercase, trim, collapse whitespace
* Compute `spec_fingerprint = sha256(normalized_text)[:12]`
* If signal includes the exact spec text, match by fingerprint.

This covers the common case: signal references a spec comment that already exists as a work item.

#### Stage B: Fuzzy lexical match (cheap)

Index each work item with:

* `spec_text`
* `location.file`, `location.symbol` (if available)
* extracted tokens:

  * snake_case & CamelCase tokens
  * error words (“reject”, “validate”, “schema”, “currency”)

Use a score like:

* token overlap (Jaccard)
* trigram similarity (for typos)
* substring boost for symbol-like strings (`RiskEngine`, `validate_schema`)

#### Stage C: LLM semantic rerank (only on top-K)

When wording differs (“validation interface” vs “reject invalid currency codes”), lexical can fail.

Use LLM reranking on top-K lexical candidates:

* Input: signal.need.summary + spec_refs + top 20 candidate work items (spec text + location)
* Output: best match set + confidence + “why” + “missing coverage?”

This keeps the system language-agnostic and avoids an explicit dependency graph.

### Indexing work items

Create a persistent store (workspace-level, not per-slice) with:

* `work_item_id` (hash)
* `spec_text` (verbatim)
* `owner_slice_id` (library slice)
* `status` (`NEW|ASSIGNED|IN_PROGRESS|MERGED|DONE|BLOCKED`)
* `location` metadata

Persist as JSONL for append-only audit + easy recovery:

* `.pdd_runs/<run_id>/coordination/work_items.jsonl`
* plus a compact index: `.pdd_runs/<run_id>/coordination/work_items_index.json`

### Handling “worded differently”

Use a **two-channel query** built from the signal:

* **Spec-text channel**: exact `spec_refs[].spec_text`
* **Artifact channel**: `need.artifact_key` and symbol-like tokens

Even if the work item says “Schema validation rejects instructions with invalid currency codes,” it likely includes tokens like:

* `schema`, `validation`, `reject`, `currency`
  which align with the artifact channel.

### Multiple partial matches

If multiple candidates match:

1. LLM reranker returns:

   * `primary_match`
   * `secondary_matches`
   * `coverage = FULL|PARTIAL|NONE`
2. Planner action:

   * If **FULL**: wait on primary (monitor checks the artifact).
   * If **PARTIAL**: create a *compound monitor* (OR condition) or route a new “interface contract” work item to eliminate ambiguity.
   * If **NONE**: treat as unrouted/underspecified.

---

## Q3: JIT monitor script system

### Recommendation: declarative monitor DSL + safe executor

Use JSON “scripts” (a DSL), not arbitrary Python or shell.

This satisfies:

* “Planner writes arbitrary condition scripts” (the planner can express many conditions)
* Safety: no destructive operations
* Portability: no OS dependencies
* Auditability: monitors are data, not code

### MonitorSpec format

```json
{
  "monitor_version": 1,
  "monitor_id": "mon_4d21b8c9",
  "run_id": "run_2026_02_12_001",

  "waiting_slice": { "layer": "l1", "slice_id": "LIB-01" },
  "signal_id": "sig_9a3c2f7a1b2e",

  "condition": {
    "type": "git_symbol_exists",
    "ref": "pdd/run_2026_02_12_001/l1/dirty",
    "file_glob": "libraries/**.py",
    "symbol_fqn": "RiskEngine.check_exposure",
    "signature_regex": "def\\s+check_exposure\\s*\\("
  },

  "execution": {
    "mode": "hybrid",
    "poll_interval_sec": 20,
    "event_triggers": ["GIT_DIRTY_ADVANCED", "SLICE_MERGED"]
  },

  "timeout": {
    "timeout_sec": 7200,
    "on_timeout": "ESCALATE"
  },

  "wake": {
    "action": "WAKE_SLICE",
    "payload": {
      "reason": "Dependency now present on shared branch",
      "artifact_key": "RiskEngine.check_exposure"
    }
  },

  "status": {
    "state": "ACTIVE",
    "created_at": "2026-02-12T07:23:11Z",
    "last_checked_at": null,
    "failures": 0
  }
}
```

### Execution model: hybrid (event-driven + polling fallback)

* **Event-driven** when possible:

  * WorktreeManager emits events when:

    * a slice is merged to dirty
    * dirty advances (new HEAD)
  * MonitorExecutor runs monitors subscribed to those events immediately.
* **Polling fallback**:

  * Periodic checks handle missed events and external updates (e.g., user adds constraints).

### What monitors can access

Monitors should access only **read-only views**:

* Git refs/branches: `git show`, `git grep`, `git ls-tree`
* File contents at a ref
* Work item store status
* Constraint files under `analysis/constraints/`
* Slice status registry

### Safety constraints (must-have)

* Monitor executor runs only **whitelisted condition types**.
* No arbitrary command execution.
* No repo writes. (Executor refuses `git checkout`, `git merge`, etc.)
* Writes are limited to:

  * updating monitor status files
  * writing wake events
  * writing logs/receipts in `.pdd_runs/...`

### Lifecycle management

* **Register**: planner writes monitor spec file to:

  * `.pdd_runs/<run_id>/coordination/monitors/<monitor_id>.json`
* **Track**: MonitorRegistry maintains:

  * active monitors
  * mapping: `slice_id -> [monitor_id]`
  * mapping: `signal_id -> monitor_id`
* **Fire**: when condition becomes true:

  * mark monitor `FIRED`
  * emit wake event
* **Cleanup**:

  * when slice resumes, remove/close monitors associated with that signal
  * keep an immutable receipt record for audit

### Failure handling

* If a monitor check throws:

  * increment `failures`
  * exponential backoff on polling interval
  * if failures exceed threshold (e.g., 5), escalate:

    * emit a new planner signal: `MONITOR_FAILED`
* If condition never met by timeout:

  * escalate to planner for re-triage:

    * maybe the provider slice never got routed
    * maybe interface changed
    * maybe cycle exists

---

## Q4: “Wake agent” mechanics

### Key interpretation: agents are not long-running processes

In this system, “agent” = “a slice run that invokes an LLM implementor.”
So waking means **re-queueing the slice** to run again with updated repo state and additional context.

### Wake protocol

1. Monitor fires → writes a `WakeEvent`:

   * `.pdd_runs/<run_id>/coordination/wake_events/wake_<timestamp>_<slice_id>.json`
2. Scheduler consumes wake event:

   * moves slice from `WAITING` set to `READY` queue
3. Before resuming:

   * **sync slice worktree** with shared dirty:

     * `git fetch`
     * `git rebase pdd/<run_id>/<layer>/dirty` (preferred)
     * if rebase conflict → emit `MERGE_CONFLICT` signal and go back to triage
4. Resume the PromotionLoop for that slice:

   * new iteration number (simple, auditable)
   * previous signal + wake payload is appended to bundle context (`bundle.under_spec.decisions` or a new `bundle.coordination` section)

### What state is restored

* The slice’s **git branch** already contains partial progress commits.
* The evidence bundle history persists on disk.
* The new run includes:

  * `last_signal_id`
  * `wake_payload` (what changed: commit SHA, artifact found, constraint added)
  * optional: pointer to the provider’s merge commit for context

### Continue vs rerun-from-scratch

PromotionLoop reruns from the top of an iteration, but because:

* functions already implemented are no longer “unresolved”
* gaps are recomputed
  the effect is **continue-from-where-stopped**, without fragile in-memory checkpointing.

---

## Q5: PromotionLoop changes (reactive model)

### L1 step sequence change

Current:
`COLLECT_BASELINE → GAP_EXPLORATION → PLAN → IMPLEMENT → UNDER_SPEC → ...`

New for L1:
`COLLECT_BASELINE → GAP_EXPLORATION → IMPLEMENT → COORDINATE → (WAITING | ANALYZE → PROMOTE → INTEGRATE → VERIFY → ALIGN)`

### Required new states

Add:

* `StepResult.status = "WAITING"`
* `SliceResult.status = "WAITING"`

“WAITING” is not “BLOCKED”:

* **BLOCKED** = unresolvable without human decision or spec change (terminal for scheduler unless user acts)
* **WAITING** = resolvable by expected future condition (monitor-based)

### PLAN step behavior

* For `ctx.layer == "l1"`:

  * `PlanStep.run()` returns `NOOP` (or `OK` with empty plan)
  * skip planning gate (pre-implementation constraints check), because L1 must block *during* implementation, not before

### IMPLEMENT step behavior (L1)

* L1 `ImplementStep` must run even if `bundle.plan.intentions` is empty.
* It should run if there are L1 gaps or unresolved functions.

### New “COORDINATE” step

Replace `UnderSpecCheckStep` (or make it layer-conditional):

* For L1: treat `bundle.implementation.under_spec_events` as **signals**
* Call reactive planner triage
* Register monitors
* Return `WAITING`

For L2/L3: keep existing under-spec behavior (block/resolve constraints), optionally also supporting monitors for external deps.

### Convergence logic changes

* If a slice returns `WAITING`, PromotionLoop exits early and saves bundle.
* Stagnation detection should ignore `WAITING` iterations or track separately (otherwise waiting looks like stagnation).
* Max iteration budget should also have a **max-wake budget**:

  * e.g., `max_wait_cycles = 10` before escalation.

---

## Q6: Parallel coordination via shared branch

### Merge protocol (shared dirty)

* Producer slice merges to `pdd/<run_id>/<layer>/dirty` using `WorktreeManager.merge_slice_to_dirty`.
* Merge operations must be serialized (single integration lock), because they mutate the shared branch.
* After merge:

  * WorktreeManager emits event: `SLICE_MERGED` and `GIT_DIRTY_ADVANCED`
  * MonitorExecutor runs subscribed monitors.

### Pull protocol (consumer on wake)

On wake, consumer slice must incorporate new dirty HEAD:

* `git fetch origin`
* `git rebase pdd/<run_id>/<layer>/dirty` (preferred)
* if conflict: emit `MERGE_CONFLICT` signal → planner triage

### Interface mismatch (provider changed signature)

Expected:

* Monitor triggers on “symbol exists,” but consumer may still fail if signature differs.

Handling:

1. Consumer resumes and re-attempts; if mismatch remains, it emits a new signal:

   * `classification = INTERFACE_MISMATCH`
   * includes:

     * expected signature hint (from prior attempt)
     * observed signature snippet (from shared branch grep/show)
2. Planner triage chooses:

   * route consumer adaptation work item
   * or route provider interface correction
   * or spec expansion to formalize interface contract

### Circular dependencies

A↔B can deadlock if both wait on each other.

Prevention/detection:

* Maintain a runtime **wait graph**:

  * nodes: slices
  * edges: “slice X waiting on artifact owned by slice Y”
* When adding a new wait edge, detect cycles.
* If cycle detected:

  * planner creates a **contract-breaking work item**:

    * “Define minimal interface stub for X→Y dependency in provider slice”
  * route that stub to one side (or a designated “contract authority” slice)
  * monitor on stub merge, then both can proceed

Cycle-breaking rule:

* “Interface-first commits” are allowed and encouraged:

  * add signature + doc/spec comments + `raise NotImplementedError` (or placeholder) only if the spec supports it
  * then fill implementation after consumers integrate

---

## Q7: Planner triage: already specified vs needs routing vs underspecified

### Triage decision procedure (deterministic first, LLM second)

Given a signal S:

1. **Search work items** (spec-text-first + artifact channel)
2. If strong coverage match exists:

   * If match is assigned/in-progress:

     * schedule monitor on **git artifact presence** (preferred) or work-item completion
   * If match is already merged/done:

     * schedule monitor that will fire immediately (or wake immediately) and instruct consumer to rebase/pull
3. If no work item match:

   * Search **full spec catalog** (all spec comments in repo)
   * If spec exists but is not routed:

     * create/rout a work item to correct owner slice
     * schedule monitor
4. If not found in spec at all:

   * mark **underspecified**
   * initiate **spec expansion** (see Q8)
   * route expansion work item
   * schedule monitor

### Distinguishing “unrouted” vs “partial coverage”

Use a coverage classifier:

* Input: signal.need + top spec matches
* Output:

  * `FULL_COVERAGE` / `PARTIAL_COVERAGE` / `NO_COVERAGE`
  * plus: “what missing detail is required?”

Rule:

* **Unrouted**: a spec comment exists that *directly* names the artifact or behavior, but no work item maps to it (or it’s assigned to the wrong slice).
* **Partial coverage**: spec mentions something related but does not define the interface/behavior needed to implement the blocked function.
* **Underspecified**: no spec text implies the artifact/behavior at all.

Yes: this classification should use an LLM when uncertain. Use deterministic heuristics only to prune candidates.

---

## Q8: Spec expansion mechanism

### What “expand the spec” means mechanically

Expansion must end up as one of:

1. **New spec comments** added to skeleton files (preferred, preserves “code is spec”)
2. **New stub function(s)** with spec comments (when an interface is missing)
3. **Constraint entries** (when the missing piece is a decision, not code)

### Who produces the expansion

Planner does not directly edit code in-place. It:

* creates a **spec expansion work item** (spec text)
* routes it to the appropriate slice agent (usually the provider slice)

### Validation of expansion (prevent drift)

Use the already-implemented QA/scoring architecture:

* Multi-model proposal (3 models if in auto mode)
* Consistency check against existing spec text
* Require explicit provenance:

  * “Expansion created to resolve signal_id X”
  * include citations to existing spec_refs that motivated the change
* If confidence low or contradictions detected:

  * block in interactive mode (user must approve/steer)

### Expansion feedback loop

* Planner routes expansion work item → provider agent implements (adds stub/spec + implementation) → merges to dirty → monitor fires → consumer wakes.

---

## Deliverables summary mapped to your list

### 1) Signal format and emission protocol

* Versioned JSON envelope + flexible payload
* Must include verbatim spec text anchors + progress metadata
* Emitted by ImplementationRunner when blocked; written to iteration dir

### 2) Planner triage algorithm

* Search work items by spec text (plus artifact channel)
* Classify: in-progress / unrouted / underspecified
* Route or expand as needed
* Always register monitor(s)

### 3) Spec text search mechanism

* Exact fingerprint match → fuzzy lexical → LLM rerank
* Index work items with tokens + location metadata
* Handle multiple matches via coverage classification + compound monitors

### 4) JIT monitor system

* Declarative JSON DSL with safe, whitelisted condition types
* Hybrid execution: event-trigger + polling fallback
* Persisted registry + audit receipts + timeouts + failure escalation

### 5) Wake-up protocol

* Wake event is a durable file queue
* Scheduler re-queues slice; slice rebases onto dirty; reruns implementation
* Resume state is repo + bundles + wake payload (not an in-memory continuation)

### 6) PromotionLoop modifications

* L1 PLAN no-op
* L1 IMPLEMENT runs directly from spec comments
* Add COORDINATE step; add WAITING result handling
* Avoid stagnation penalizing WAITING iterations

### 7) Shared branch coordination

* Serialize merges to dirty
* Monitors watch dirty for artifacts
* On wake: rebase/pull dirty into slice branch
* Handle interface drift with INTERFACE_MISMATCH signals
* Detect/break cycles with wait-graph + interface-first stubs

### 8) Spec expansion

* Planner creates expansion work item(s), routes them
* Agent adds spec comments/stubs via promotion flow
* Validate expansions with existing multi-model QA pipeline + provenance

### 9) Integration with existing systems

* WorktreeManager: event hooks after merge/tick
* ImplementationRunner: emit signals (structured) on halt
* UnderSpecManager: reused for “needs decision” signals (constraint monitor)
* Planner: new reactive triage capability (no L1 pre-plan)

### 10) Concrete implementation plan (files to create/modify)

#### Create new package: `orchestration/coordination/`

* `signals.py`

  * `CoordinationSignal` parse/serialize
  * `signals.json` writer/reader
* `work_items.py`

  * `WorkItem` (id, spec_text, owner_slice, status, location, tags)
  * `WorkItemStore` (JSONL + compact index)
  * `search()` implementing A/B stages + candidate pack for LLM rerank
* `monitors.py`

  * `MonitorSpec`
  * condition checkers (git_symbol_exists, work_item_done, constraint_present, etc.)
* `monitor_executor.py`

  * hybrid event/poll runtime
  * writes wake events
* `wake_queue.py`

  * file-based wake event enqueue/dequeue
* `wait_graph.py`

  * cycle detection for active waits

#### Modify `orchestration/promotion_loop.py`

* Extend `StepResult.status` and `SliceResult.status` with `WAITING`
* L1 `PlanStep.run()` → no-op (skip planning gate)
* L1 `ImplementStep.run()` → run without needing `bundle.plan.intentions`
* Replace `UnderSpecCheckStep` with `CoordinateStep`:

  * calls planner triage on signals
  * registers monitors
  * returns `WAITING` when monitors exist

#### Modify `orchestration/promotion_scheduler.py`

* Replace with or add `ReactivePromotionScheduler`:

  * supports `WAITING` slices
  * runs MonitorExecutor concurrently
  * re-queues slices on wake events
  * terminates when all slices are COMPLETE or terminally BLOCKED/FAILED

#### Modify `orchestration/pdd_lifecycle.py`

* Use `ReactivePromotionScheduler` for L1 (optionally all layers)
* Ensure monitor executor lifecycle is tied to layer run

#### Modify `planner/api.py` + `planner/router.py`

* Add new capability, e.g. `TRIAGE_SIGNAL` (or reuse RESOLVE_SIGNAL but broaden semantics)
* Add `Planner.triage_signal(context, signal)` convenience adapter
* L1Planner implements triage logic:

  * uses WorkItemStore + SpecCatalog + optional LLM rerank
  * outputs: routing decisions + monitor specs

#### Modify `orchestration/implementation/runner.py` and `implementation/types.py`

* Update implementor prompt so under-spec output uses the `CoordinationSignal` envelope shape (or embed required fields inside existing under_spec_events).
* Write `signals.json` in iteration dir.

#### Migration strategy (no big-bang)

1. Add WAITING status plumbing + wake queue + monitor executor (initially only for constraint_present monitors).
2. Make L1 PLAN no-op and allow L1 IMPLEMENT without plan intentions.
3. Add COORDINATE step that:

   * handles legacy under_spec_events
   * schedules simple monitors (constraint present, git_symbol_exists)
4. Add work item store + search + LLM reranker.
5. Replace scheduler with reactive version.

---

If you want the shortest path to first working reactive behavior: implement **WAITING + constraint-present monitors + git-symbol-exists monitors**, then add work item search/routing and finally spec expansion.
