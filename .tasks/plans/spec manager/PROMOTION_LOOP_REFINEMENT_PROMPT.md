# Research: Refining the PromotionLoop — Layer Pipeline and Batch Promotion

## Context

You previously designed the PromotionLoop (per-slice iterative loop with EvidenceBundle, DemotionTickets, under-spec blocking, and incremental migration). That design is in PROMOTION_LOOP_RESEARCH_RESPONSE.md.

After review, the promotion model needs refinement. The key insight that was missing: **each layer has a dirty/clean worktree pair, and promotion flows continuously through layers as batches.** Creative work only happens at the active layer, but CI (merge + test) runs at all layers in parallel.

---

## The Refined Model

### Worktree Hierarchy (6 worktrees + grandchildren)

```text
L1 (Code-as-Spec):
  grandchild-slice-A   (parallel implementation work)
  grandchild-slice-B   (parallel implementation work)
  dirty                (accumulates completed slices from grandchildren)
  clean                (accumulates from dirty after gates + tests pass)

L2 (Architecture):
  dirty                (accumulates batches promoted from L1 clean)
  clean                (accumulates from L2 dirty after tests pass)

L3 (Clean Code):
  dirty                (accumulates batches promoted from L2 clean)
  clean                (accumulates from L3 dirty after tests pass) → main
```

### Batch Flow

```text
L1 grandchild → L1 dirty → [gates + tests] → L1 clean
    → immediately → L2 dirty → [tests] → L2 clean
    → immediately → L3 dirty → [tests] → L3 clean → main
```

- Multiple slices form a **queue** to get into L1 clean.
- Batches are promoted: the queue empties each time the previous batch clears.
- After a batch passes tests in L1 clean, it immediately flows to L2 dirty.
- `git diff dirty clean` at each layer tracks unpromoted work.
- When dirty == clean (no diff), the layer is fully clean.

### Creative Work vs CI

- **CI runs at all layers continuously** — merges and tests as batches arrive.
- **Creative work only at the active layer** — no architectural proposals while L1 is active, no code quality reviews while L2 is active.
- Active layer advances when its dirty == clean.

### What This Changes From Your Previous Design

Your previous PromotionLoop design treated promotion as within-slice (slice passes gates → atoms promoted → architecture gets built). The refined model separates:

1. **Within-layer convergence** — the per-slice loop (gap → implement → analyze → verify gates → merge to L1 dirty → promote to L1 clean). This is what PromotionLoop does.
2. **Between-layer promotion** — batch flow from L(N) clean → L(N+1) dirty. This is a separate pipeline mechanism.
3. **Layer-phase work** — creative work at L2 (architecture design, service building) only starts after L1 is fully clean.

Your previous design merged these concerns. The EvidenceBundle, DemotionTickets, under-spec blocking, and loop steps are still correct — they operate within the active layer's convergence loop. But the integration step and the overall orchestration need to account for the multi-layer pipeline.

---

## What I Need You To Refine

### Question 1: Git Branch Strategy for 6 Worktrees

The current `WorktreeManager` manages one dirty/clean pair plus grandchildren for one layer. Now we need dirty/clean pairs for three layers.

- What is the git branch naming convention? (e.g., `pdd/l1-dirty`, `pdd/l1-clean`, `pdd/l2-dirty`, etc.?)
- Are all 6 worktrees created upfront, or lazily as layers become active?
- How do grandchild worktrees relate to the layer worktrees? (Branch off L1-dirty? Or off a slice-specific branch?)
- What is the base commit relationship between layers? (Does L2-dirty branch from L1-clean's HEAD? Or from L1-clean at promotion time?)

### Question 2: Batch Promotion Mechanics

When a batch moves from L1 clean → L2 dirty:

- Is this a git merge? Cherry-pick? Rebase? Something else?
- How do you handle conflicts if L2 dirty already has content from a previous batch?
- What constitutes a "batch"? (All commits since last promotion? A specific set of slices? A single merge commit in L1 clean?)
- How do you track which batches have been promoted? (Tags? Refs? A manifest file?)
- What happens if L2 tests fail on a promoted batch? (Demotion ticket back to L1? Block future batches? Roll back?)

### Question 3: Promotion Queue Design

Multiple slices compete to merge into L1 clean:

- Is the queue explicit (data structure) or implicit (git branches waiting to merge)?
- How are batches formed? (First-come-first-served? Wait for N slices? Promote as each slice completes?)
- What prevents the queue from growing unbounded if CI is slow?
- How does the queue interact with the PromotionLoop scheduler? (Scheduler picks next slice to work on; queue manages finished slices waiting for CI)

### Question 4: Layer Transition — When Active Layer Advances

When L1 dirty == L1 clean (all work promoted):

- How does the system detect this? (Periodic check? Event-driven after each batch promotion?)
- What happens to the grandchild worktrees? (Cleaned up? Preserved for reference?)
- Does L2 creative work start immediately? Or is there a verification step first? (e.g., global P6/P7 cross-library checks)
- Does L2 also get grandchild worktrees for parallel slice work? Or is L2 work structured differently (since it's architectural, not per-library)?
- Can the system ever go BACK to L1 after advancing to L2? (e.g., L2 work discovers a missing L1 requirement → demotion → L1 re-activates)

### Question 5: Demotion Across Layers in the Batch Model

Your previous DemotionTicket design targets a specific layer. In the batch model:

- If L2 tests fail on a promoted batch, the demotion goes back to L1. But L1 might have already advanced (dirty == clean). Does demotion RE-OPEN L1? (L1 dirty gets new work, dirty != clean again, creative work returns to L1)
- If L3 tests fail, how does the demotion cascade? (L3 → L2 dirty? Or straight to L1 if it's an algorithmic issue?)
- When a demotion reopens a lower layer, what happens to the batches that were already promoted above? (Keep them? Roll back? Mark as "needs re-verification"?)

### Question 6: Revised Integration Step

Your previous INTEGRATE step was: merge grandchild → parent (dirty root) → push to clean sibling → run tests → rebase dirty on clean.

In the refined model, INTEGRATE needs to also handle the between-layer promotion. Revise the INTEGRATE step to include:

- Merge grandchild → L1 dirty
- Promote from L1 dirty → L1 clean (with gates + tests)
- Batch promotion from L1 clean → L2 dirty (immediate)
- Tests on L2 dirty → L2 clean (CI, not creative work)
- If any step fails: which demotion path?

### Question 7: WorktreeManager Extension

The current `WorktreeManager` has:
- `setup()` — creates dirty root, clean sibling
- `create_library_worktree(lib_id)` — creates grandchild for a library
- `promote_library(lib_id)` — merges grandchild → parent → clean
- `rebase_root_on_clean()` — syncs dirty with clean
- `cleanup()` — removes worktrees

What methods need to be added for the multi-layer model? Design the extended WorktreeManager API that manages all 6 worktrees + grandchildren, batch promotion queues, and layer transitions.

---

## Constraints

1. **Incremental extension of WorktreeManager.** Don't replace it — extend it to handle multiple layers.
2. **Git-based tracking.** Use git diff, refs, tags, or similar mechanisms to track promoted/unpromoted work. No separate database.
3. **Layer isolation.** Each layer's dirty/clean pair should be independent — a problem at L2 shouldn't corrupt L1 clean.
4. **The PromotionLoop design from your previous response is preserved.** The per-slice convergence loop, EvidenceBundle, DemotionTickets, under-spec blocking, and loop steps are all still correct. This refinement adds the between-layer pipeline on top.
5. **Batch promotion should be simple.** Don't over-engineer the batching — the simplest correct mechanism is best.
