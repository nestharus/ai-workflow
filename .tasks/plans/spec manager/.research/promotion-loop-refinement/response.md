## 1) Git branch strategy for 6 worktrees

### Branch naming convention

Use a **run-scoped namespace** so multiple runs don’t collide and so refs are self-describing:

* `pdd/<run_id>/l1/clean`
* `pdd/<run_id>/l1/dirty`
* `pdd/<run_id>/l2/clean`
* `pdd/<run_id>/l2/dirty`
* `pdd/<run_id>/l3/clean`
* `pdd/<run_id>/l3/dirty`

Add **CI snapshot refs** (one per layer):

* `pdd/<run_id>/l1/candidate`
* `pdd/<run_id>/l2/candidate`
* `pdd/<run_id>/l3/candidate`

Add **slice/grandchild branches only for the active layer**:

* `pdd/<run_id>/<layer>/slice/<slice_id>/<nonce>`

  * example: `pdd/2026-02-09T18-04Z/l1/slice/projection/7f3a2c`

Optional tags for batch identification (see Q2):

* `pdd/<run_id>/batch/<layer>/<seq>`
* `pdd/<run_id>/batch/<layer>/<seq>/accepted`

This stays within “git-based tracking” (branches/refs/tags only).

---

### Are all 6 worktrees created upfront?

Recommended default: **create all 6 upfront** (cheap, simplifies continuous CI):

* L1 dirty + L1 clean worktrees
* L2 dirty + L2 clean worktrees
* L3 dirty + L3 clean worktrees
* grandchild slice worktrees created **lazily** when a slice is scheduled at the active layer

If you want an incremental rollout: create L1 dirty/clean initially, then create L2/L3 pairs the first time L1 clean advances (lazy “first use”). The API can support both.

---

### How do grandchild worktrees relate to layer worktrees?

Keep the existing semantics to minimize refactors:

* **Grandchildren branch off the active layer’s `dirty`**.

  * While L1 is active: slice branches off `pdd/<run_id>/l1/dirty`
  * While L2 is active (if you choose to parallelize architecture): slice branches off `pdd/<run_id>/l2/dirty`
  * While L3 is active (code quality): slice branches off `pdd/<run_id>/l3/dirty`

Reason: this matches your current WorktreeManager behavior and avoids re-plumbing “base branch selection” during migration.

If you want a stability option later, add config `grandchild_base = "dirty" | "clean"`.

---

### Base commit relationship between layers

Do **not** make L2-dirty “branch from” L1-clean in the git sense. Instead:

* All `*/clean` branches start at the run base ref (usually `main` HEAD at run start).
* Promotion between layers is implemented as **merging upstream clean into downstream dirty**:

  * when `l1/clean` advances, merge it into `l2/dirty`
  * when `l2/clean` advances, merge it into `l3/dirty`

This yields the pipeline invariant:

* Each layer’s `clean` is “last-known-good at that layer”
* Each layer’s `dirty` is “clean + pending merges (from below or from layer’s own creative work)”
* `git diff <layer>/clean..<layer>/dirty` is always the “unpromoted queue” for that layer

This keeps layer isolation: L2 failing does not mutate L1 refs.

---

## 2) Batch promotion mechanics

### Merge vs cherry-pick vs rebase

Use **merge** everywhere for batch promotion. Specifically:

* Slice completion: merge slice branch → active layer dirty
* Dirty→clean acceptance: clean is advanced to a commit that already exists on dirty (fast-forward update)
* Cross-layer promotion: merge upstream clean → downstream dirty

Why merge is simplest here:

* No history rewriting (rebases) across worktrees.
* “What went into this batch?” is a commit graph question.
* Conflicts surface as standard merge conflicts.

Cherry-pick is only appropriate if you later enforce “directory ownership per layer” and want to cherry-pick subsets. Not needed for the refined model.

---

### What constitutes a “batch”?

Define a batch as **one frozen candidate commit per layer**.

At layer L:

* `L.clean` is last accepted commit.
* `L.dirty` accumulates incoming merges.
* When CI is ready, snapshot the current `L.dirty` HEAD into `L.candidate`.
* That `L.candidate` commit (a specific SHA) is “the batch” being tested/accepted.

So a batch is:

* `Batch(layer=L, candidate_sha=X, base_clean_sha=Y)`

This matches your statement: “queue empties each time previous batch clears” — the queue is the diff range `Y..(current dirty head)`, and the “emptied portion” is the tested candidate.

---

### How to track which batches were promoted

Use tags and/or refs only:

Minimum viable tracking:

* `pdd/<run_id>/<layer>/candidate` ref points to the in-flight batch SHA.
* When accepted, move `<layer>/clean` to that SHA, and clear/move candidate.

Recommended tracking for auditability:

* Create an annotated tag at batch start:

  * `pdd/<run_id>/batch/<layer>/<seq>` → candidate SHA
  * tag message includes:

    * base clean SHA
    * candidate SHA
    * list of slice merge commits included (can be computed and stored as text)
* On acceptance:

  * `pdd/<run_id>/batch/<layer>/<seq>/accepted` → same SHA (or just one tag with status in message)

Cross-layer mapping is implicit:

* “Which L1 batch was merged into L2?” can be derived from the merge commit parents, but if you want explicit:

  * store `pdd/<run_id>/l2/upstream_accepted` as a ref pointing to the L1-clean SHA that L2-clean currently includes (more below)

---

### L1 clean → L2 dirty: what operation happens?

Operation: **merge**.

```
git checkout pdd/<run_id>/l2/dirty
git merge --no-ff pdd/<run_id>/l1/clean
```

If no conflicts and L2 has no additional changes, this may fast-forward or produce a trivial merge commit.

Then L2 CI tests run on the new `l2/dirty` head (snapshotted via `l2/candidate`).

---

### Conflicts when promoting to L2 dirty

Policy (simple, correct, consistent with “no creative work at inactive layers”):

* If merge produces conflicts at layer L2 while L1 is active:

  1. abort merge
  2. generate a DemotionTicket targeting **the active layer** (L1) describing incompatibility and required alignment
  3. block further cross-layer promotion until resolved

This enforces “inactive layers don’t get creative conflict resolution.”

Later, when L2 is active, conflicts on merges into L2 dirty are resolvable at L2 (because L2 creative work is allowed).

---

### What if L2 dirty already has content from a previous batch?

Normal case. L2 dirty is an integration branch and will have an evolving history:

* If previous batch was accepted, L2 clean has moved forward; L2 dirty may be ahead or equal.
* If previous batch failed, L2 clean is behind; L2 dirty contains a failing candidate commit.

New promotions from L1 clean should obey backpressure (see Q3), but mechanically it’s still just:

* merge upstream clean into L2 dirty
* snapshot candidate
* test

---

### What happens if L2 tests fail on a promoted batch?

Key properties to preserve:

* Layer isolation: do not mutate L1 clean.
* Determinism: a failing batch SHA is preserved for diagnosis.

Mechanism:

1. **Do not update `l2/clean`**
2. Record failure artifacts + create DemotionTickets
3. Determine demotion target:

   * if active layer is L1, demote to L1
   * if active layer is L2, demote to L2 unless diagnosis indicates spec-layer gap
4. Block further promotion across this boundary until fixed (see backpressure)

You do not roll back anything. Fixes flow forward as new commits in the demotion target layer.

---

## 3) Promotion queue design (multiple slices competing for L1 clean)

### Is the queue explicit?

The queue is **implicit in git refs**, plus one explicit “in-flight batch” ref:

* Pending work at layer L is `L.clean..L.dirty`
* In-flight batch is `L.candidate` (a ref to the snapshot SHA currently under CI)

While `L.candidate` exists and CI is running, new slice merges can continue to move `L.dirty` forward; they remain queued behind the candidate snapshot.

This gives you an actual queue without a database.

---

### How are batches formed?

Simplest correct policy:

* **Promote “whatever is in dirty” when CI is free**, snapshotting at that moment:

  * candidate = dirty HEAD

This naturally tends toward “batch includes as many completed slices as arrived since last promotion.”

Optional policy knobs (don’t start with these):

* max batch size (commit count or diff size)
* min batch size (wait for N slices)
* time window batching (every N minutes)

---

### What prevents unbounded growth if CI is slow?

Backpressure using only git refs:

Track “downstream acceptance” as refs:

* `pdd/<run_id>/l2/upstream_accepted` → points to the L1-clean SHA that is already accepted into L2-clean
* `pdd/<run_id>/l3/upstream_accepted` → points to the L2-clean SHA already accepted into L3-clean

Then define backlog metrics:

* `pending_L1_to_L2 = commits_between(l2/upstream_accepted, l1/clean)`
* `pending_L2_to_L3 = commits_between(l3/upstream_accepted, l2/clean)`

Apply backpressure rules:

* If `pending_L1_to_L2 > max_pending_batches` (default 1):

  * **pause starting new L1 candidate batches**
  * optionally reduce slice parallelism (don’t create more grandchildren)

This keeps L1’s “queue to clean” bounded when upper layers are slower.

---

### Scheduler interaction: PromotionLoop vs queue/CI

Split responsibilities:

* **PromotionLoop scheduler (creative)**:

  * chooses slices to work on (GapQueue priority)
  * runs the per-slice convergence loop in grandchild worktrees
  * merges completed slice → active layer dirty

* **BatchPromoter / CI tick (non-creative)**:

  * snapshots dirty→candidate
  * runs gates/tests
  * advances clean
  * propagates clean→next layer dirty
  * runs next-layer tests
  * emits DemotionTickets on failures

In a single-process MVP, you can just call `tick_ci()` after each slice merge and periodically while slices run.

---

## 4) Layer transition (when active layer advances)

### Detecting “dirty == clean”

For a layer L, treat it as fully clean when:

* `rev-parse L.dirty == rev-parse L.clean`
* and either:

  * `L.candidate` does not exist, or
  * `rev-parse L.candidate == rev-parse L.clean` (no in-flight batch)

This is faster and less ambiguous than diffing.

---

### What happens to grandchild worktrees?

When a layer stops being active:

* Remove grandchild worktrees for that layer (worktree cleanup)
* Preserve evidence artifacts (EvidenceBundle dirs) for audit/debug
* Keep any “blocked” slice branches/worktrees only if you need human intervention; otherwise delete after ticketing

This keeps the physical worktree set manageable.

---

### Does L2 creative work start immediately?

Recommended transition gate (simple and safe):

Before switching active layer from L1 → L2:

1. Ensure L1 fully clean (as above)
2. Ensure pipeline has drained above it:

   * `l2.dirty == l2.clean` and `l3.dirty == l3.clean` (or at least no failing candidates)
3. Run a **global verify checkpoint** on L1 clean (or on L2 clean if L2 mirrors L1 at this stage):

   * P6 cross-library connectivity
   * P7 lineage/orphans
   * full test suite on L1 clean (if not already)

Only then mark L2 as active.

This matches the refined model: no architecture work while L1 still moving.

---

### Does L2 also get grandchild worktrees?

You have two workable choices; start with the simpler one:

**Option A (simplest): no L2 grandchildren initially**

* L2 creative work happens directly in `l2/dirty` worktree (single-threaded architectural work).
* Still uses EvidenceBundle per iteration, but slice_id might be “architecture”.

**Option B (parallelizable): L2 grandchildren exist**

* Units of work are architecture components (services, event domains, disconnected graph components from AdjacencyGraph).
* Create grandchildren from `l2/dirty` exactly like L1 library slices.

This keeps the mechanics identical; only the slice discovery differs.

---

### Can the system go back to L1 after advancing to L2?

Yes, and it should be automatic:

* If any CI/test/verification at L2 or L3 emits a DemotionTicket targeting L1:

  * apply ticket → creates new changes on `l1/dirty`
  * now `l1/dirty != l1/clean`
  * active layer is reset to L1 (creative returns to spec)

Pipeline above L1 is frozen (or runs only diagnostic CI) until L1 re-cleans and promotions re-flow upward.

This is the “re-open lower layer” mechanism.

---

## 5) Demotion across layers in the batch model

### Rule: demote to the lowest layer that is allowed to change right now

DemotionTickets already have `target_layer`. In the batch model, choose target based on:

* where the failure is observed (L2 vs L3)
* where creative work is currently allowed (active layer)
* diagnosis (algorithmic/spec vs architecture vs code quality)

Concrete policy:

**While L1 is active**

* Any L2 test failure → ticket targets **L1** (L2 is not allowed to change)
* Any L3 test failure → ticket targets **L1**

**While L2 is active**

* L3 failure:

  * target L2 if architectural/code-assembly issue
  * target L1 if missing requirement / underspec
* L2 failure:

  * target L2 unless it’s clearly a spec-layer gap (then L1)

**While L3 is active**

* L3 failures target L3 (or L2/L1 if diagnosis demands)

DownwardFlowEngine remains the tracer:

* failure → pins → atoms → slice → ticket

---

### If L2 tests fail but L1 had already advanced (dirty==clean)

Yes: demotion re-opens L1.

Mechanically:

* apply ticket patch into `l1/dirty` (or create new L1 slice branches)
* L1 dirty no longer equals L1 clean
* active layer becomes L1 again
* L2/L3 candidates remain unaccepted and are treated as “blocked by upstream fix”

No rollback of L1 clean is required; fixes flow forward.

---

### If L3 tests fail, how does demotion cascade?

Same policy: target the lowest editable layer that can fix.

Typical outcomes:

* If failure traces to architectural wiring or pin misuse → ticket targets L2
* If it traces to missing spec requirement or algorithmic contract mismatch → ticket targets L1

Do not automatically “cascade multiple tickets.” Let one ticket be explicit; if resolving it reveals deeper issues, subsequent tickets will be emitted.

---

### What happens to batches already promoted above when a lower layer reopens?

Keep them. Do not roll back clean refs.

* `L3 clean` is never advanced on a failing batch (so main is protected).
* `L2 clean` is never advanced on a failing batch.
* Failing batches remain on `dirty` (and tagged via candidate/batch tags) for diagnosis.

After fixes land in the target layer and re-promote upward, new merge commits supersede the failing state and CI re-runs.

This matches “layer isolation” and avoids rollback complexity.

---

## 6) Revised INTEGRATE step (within-layer + between-layer pipeline)

This step becomes “merge slice into active layer dirty, then tick the batch pipeline.”

### Revised INTEGRATE algorithm (active layer = L1 case)

1. **Merge grandchild → L1 dirty**

* `git merge` slice branch into `pdd/<run_id>/l1/dirty`
* If conflict:

  * emit DemotionTicket targeting L1 (conflict resolution required)
  * mark slice as needing rework
  * do not proceed to CI tick for this slice

2. **Tick CI pipeline (all layers)**
   Run in order, but each layer can test in parallel worktrees if you want:

#### (A) L1 dirty → L1 clean (gates + tests)

* Preconditions:

  * `l1/candidate` not set (no in-flight batch)
  * `l1/dirty != l1/clean` (there is queued work)
  * backpressure allows it (pending_L1_to_L2 <= max)
* Actions:

  * set `l1/candidate = snapshot_sha(l1/dirty)`
  * run:

    * L1 compliance gates (graph-based)
    * L1 test suite (slice tests or fast suite; full suite optionally)
  * If pass:

    * advance `l1/clean` to `l1/candidate` (fast-forward ref update)
    * create batch tag(s)
    * clear or set `l1/candidate = l1/clean`
  * If fail:

    * generate DemotionTickets targeting L1
    * keep `l1/clean` unchanged
    * clear candidate (or keep it + mark failing; simplest is clear and rely on tags)

#### (B) Propagate L1 clean → L2 dirty (immediate)

* Preconditions:

  * `l1/clean` advanced since last propagation (`l2/upstream_accepted` ref differs)
  * and optionally L2 not currently testing a candidate
* Actions:

  * merge `l1/clean` into `l2/dirty`
  * set `l2/candidate = snapshot_sha(l2/dirty)`
  * run L2 tests
  * If pass:

    * advance `l2/clean` to `l2/candidate`
    * update `l2/upstream_accepted = current l1/clean`
  * If fail:

    * generate DemotionTicket targeting:

      * L1 if L1 is active
      * L2 if L2 is active (later phase)
    * do not advance `l2/clean`
    * stop propagating further upward for this tick

#### (C) Propagate L2 clean → L3 dirty, then L3 dirty → L3 clean (tests)

Same mechanics as (B), just one layer up, and if pass:

* advance `l3/clean`
* update `l3/upstream_accepted = current l2/clean`

#### (D) L3 clean → main

* simplest: fast-forward merge into `main` (or create PR if you prefer)
* only happens after L3 clean advances

3. **Post-CI housekeeping**

* update status artifacts
* optionally rebase or refresh active-layer slice worktrees onto updated `l1/dirty`/`l1/clean` as needed

### Failure demotion paths (summary)

* Merge conflict slice→L1 dirty: demote to L1 (slice rework)
* L1 gates/tests fail: demote to L1
* L2 tests fail while L1 active: demote to L1 (L2 inactive, cannot change)
* L3 tests fail while L1 active: demote to L1
* While L2 active, L3 tests fail: demote to L2 or L1 depending on diagnosis

---

## 7) WorktreeManager extension (API design)

Keep existing methods as L1 defaults and extend with layer-aware methods.

### New core types

```python
Layer = Literal["l1", "l2", "l3"]
Lane  = Literal["dirty", "clean"]
```

### Extended WorktreeManager API

#### Setup / accessors

```python
def setup_layers(self, run_id: str, base_ref: str, layers: list[Layer] = ["l1","l2","l3"], create_all: bool = True) -> None
def layer_branch(self, layer: Layer, lane: Lane) -> str
def candidate_ref(self, layer: Layer) -> str
def layer_worktree_path(self, layer: Layer, lane: Lane) -> str
def get_layer_heads(self, layer: Layer) -> dict  # {dirty_sha, clean_sha, candidate_sha}
def is_layer_clean(self, layer: Layer) -> bool
```

#### Grandchildren (active-layer work)

```python
def create_slice_worktree(self, layer: Layer, slice_id: str, base: Lane = "dirty") -> str  # returns path
def merge_slice_to_dirty(self, layer: Layer, slice_id: str, strategy: str = "merge") -> "MergeResult"
def cleanup_slice_worktree(self, layer: Layer, slice_id: str) -> None
```

#### Batch / CI primitives

```python
def snapshot_candidate(self, layer: Layer) -> str  # sets candidate ref to dirty HEAD; returns sha
def clear_candidate(self, layer: Layer) -> None

def promote_dirty_to_clean(self, layer: Layer, gates: bool = False, tests: bool = True) -> "BatchResult"
# - runs gates/tests against candidate snapshot; if pass, advances clean to candidate

def propagate_clean_to_next_layer(self, from_layer: Layer) -> "PropagateResult"
# - merges from_layer.clean into next_layer.dirty (l1->l2, l2->l3)
```

#### Pipeline tick (drain whatever can advance)

```python
def tick_pipeline(self, active_layer: Layer, backpressure: dict) -> "PipelineTickResult"
# - attempts:
#   l1 dirty->clean (if allowed)
#   propagate l1 clean->l2 dirty + l2 tests->clean
#   propagate l2 clean->l3 dirty + l3 tests->clean
#   merge l3 clean->main
```

#### Layer transition helpers

```python
def compute_active_layer(self) -> Layer
# - derived from which layer has dirty!=clean or open “must-fix” signals

def can_advance_layer(self, layer: Layer) -> bool
# - checks layer clean + pipeline drained + optional global verify gating
```

### Backward-compatible wrappers (keep existing call sites working)

Map old methods to L1:

* `setup()` → `setup_layers(..., layers=["l1"], create_all=False)`
* `create_library_worktree(lib_id)` → `create_slice_worktree(layer="l1", slice_id=lib_id)`
* `promote_library(lib_id)` → `merge_slice_to_dirty("l1", lib_id)` then `tick_pipeline(active_layer="l1", ...)`
* `rebase_root_on_clean()` becomes either a no-op under the “fast-forward clean to dirty commit” invariant, or a helper for refreshing worktrees.

---

## Minimal incremental implementation order (to keep extension small)

1. Add L2/L3 dirty/clean branches + worktrees (no behavior change yet).
2. Add `tick_pipeline()` that only:

   * snapshots and tests L1 dirty→clean
   * merges L1 clean→L2 dirty and tests
   * merges L2 clean→L3 dirty and tests
3. Add backpressure refs (`l2/upstream_accepted`, `l3/upstream_accepted`) to prevent unbounded queue growth.
4. Wire PromotionLoop INTEGRATE to call `tick_pipeline()` after merging slice→L1 dirty.
5. Add layer transition logic + “reopen lower layer on demotion.”

This preserves your per-slice PromotionLoop/EvidenceBundle/DemotionTicket design unchanged; it only refines how “integration” and “promotion beyond the active layer” are executed and tracked.
